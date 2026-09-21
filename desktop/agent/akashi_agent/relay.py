import asyncio
import socket
from urllib.parse import urlsplit
from typing import Any, Dict

import httpx

from akashi_agent.actions import ActionExecutor
from akashi_agent.config import AgentSettings
from akashi_agent.security import CredentialStore


class DeviceRelay:
    def __init__(self, settings: AgentSettings) -> None:
        self.settings = settings
        self.credentials = CredentialStore(settings.credential_file)
        self.executor = ActionExecutor(settings)

    async def pair(self, core_url: str, code: str, name: str = "AKASHI Desktop") -> Dict[str, Any]:
        base_url = core_url.strip().rstrip("/")
        url = urlsplit(base_url)
        if (url.username or url.password or url.path not in {"", "/"} or url.query or url.fragment
            or not url.hostname or not (url.scheme == "https" or (url.scheme == "http" and url.hostname in {"127.0.0.1", "localhost", "::1"}))):
            raise ValueError("Use HTTPS, or loopback HTTP for local development.")
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=False) as client:
            response = await client.post(
                f"{base_url}/devices/pair",
                json={
                    "code": code,
                    "name": name,
                    "device_type": "windows-desktop",
                    "capabilities": self.executor.capabilities(),
                },
            )
            response.raise_for_status()
            payload = response.json()
        credential = {
            "base_url": base_url,
            "device_id": payload["device"]["id"],
            "device_token": payload["device_token"],
        }
        self.credentials.save(credential)
        return payload["device"]

    async def run_once(self) -> int:
        credential = self.credentials.load()
        headers = {
            "Authorization": f"Bearer {credential['device_token']}",
            "X-Akashi-Device-Id": credential["device_id"],
        }
        async with httpx.AsyncClient(timeout=150.0, headers=headers, follow_redirects=False) as client:
            response = await client.get(f"{credential['base_url']}/devices/agent/actions")
            response.raise_for_status()
            actions = response.json().get("actions", [])
            for action in actions:
                try:
                    result = await asyncio.to_thread(
                        self.executor.execute,
                        action["action"],
                        action.get("arguments", {}),
                        bool(action.get("approved")),
                    )
                    payload = {"ok": True, "result": result}
                except Exception as exc:
                    payload = {"ok": False, "error": str(exc)[:1_000]}
                report = await client.post(
                    f"{credential['base_url']}/devices/agent/actions/{action['id']}/result",
                    json=payload,
                )
                report.raise_for_status()
            if not actions:
                heartbeat = await client.post(
                    f"{credential['base_url']}/devices/agent/heartbeat"
                )
                heartbeat.raise_for_status()
            return len(actions)

    async def run_forever(self, interval_seconds: float = 3.0) -> None:
        while True:
            try:
                await self.run_once()
            except (httpx.HTTPError, OSError, ValueError):
                await asyncio.sleep(min(max(interval_seconds * 2, 5), 30))
            else:
                await asyncio.sleep(max(interval_seconds, 1))
