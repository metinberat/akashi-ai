import asyncio
import json
from typing import Any, Dict, Optional
from urllib.parse import urlsplit

import httpx

from app.core.config import Settings
from app.devices.store import DeviceStore


class DesktopActionError(RuntimeError):
    """A bounded, user-safe desktop action failure."""


class DesktopActionGateway:
    """Reach the local Windows body or an authenticated paired desktop.

    The direct bridge accepts loopback URLs only. Remote clients never receive
    the local agent token and cannot choose an executable path.
    """

    def __init__(self, settings: Settings, devices: DeviceStore) -> None:
        self.settings = settings
        self.devices = devices
        parsed = urlsplit(settings.local_agent_base_url)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username
            or parsed.password
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("AKASHI_AGENT_URL must be a loopback HTTP origin.")

    async def execute(
        self,
        action: str,
        arguments: Dict[str, Any],
        approved: bool,
    ) -> Dict[str, Any]:
        local_error: Optional[Exception] = None
        if self.settings.local_agent_token:
            try:
                return await self._execute_local(action, arguments, approved)
            except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout) as exc:
                local_error = exc

        paired = next(
            (
                device
                for device in self.devices.list_devices()
                if device.get("online")
                and not device.get("revoked")
                and action in set(device.get("capabilities", []))
            ),
            None,
        )
        if paired is not None:
            return await self._execute_paired(
                str(paired["id"]), action, arguments, approved
            )
        if local_error is not None:
            raise DesktopActionError(
                "Desktop agent offline. Start the loopback Windows agent."
            ) from local_error
        if not self.settings.local_agent_token:
            raise DesktopActionError(
                "Desktop body is not configured. Set AKASHI_AGENT_TOKEN on Core and the Windows agent."
            )
        raise DesktopActionError("Desktop agent offline.")

    async def _execute_local(
        self,
        action: str,
        arguments: Dict[str, Any],
        approved: bool,
    ) -> Dict[str, Any]:
        token = self.settings.local_agent_token or ""
        timeout = max(5.0, min(self.settings.local_agent_timeout_seconds, 300.0))
        async with httpx.AsyncClient(
            base_url=self.settings.local_agent_base_url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout,
            follow_redirects=False,
        ) as client:
            response = await client.post(
                "/v1/actions/execute",
                json={
                    "action": action,
                    "arguments": arguments,
                    "approved": approved,
                },
            )
        if len(response.content) > 2_100_000:
            raise DesktopActionError("Desktop action result exceeded the safe size limit.")
        if response.status_code >= 400:
            detail = "Desktop action failed."
            try:
                payload = response.json()
                if isinstance(payload.get("detail"), str):
                    detail = payload["detail"][:1_000]
            except (ValueError, AttributeError):
                pass
            raise DesktopActionError(detail)
        payload = response.json()
        if not isinstance(payload, dict) or not payload.get("ok"):
            raise DesktopActionError("Desktop action returned an invalid result.")
        return payload

    async def _execute_paired(
        self,
        device_id: str,
        action: str,
        arguments: Dict[str, Any],
        approved: bool,
    ) -> Dict[str, Any]:
        queued = self.devices.queue_action(device_id, action, arguments, approved)
        deadline = asyncio.get_running_loop().time() + max(
            5.0, min(self.settings.local_agent_timeout_seconds, 300.0)
        )
        while asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.5)
            current = self.devices.get_action(str(queued["id"]))
            if current is None:
                raise DesktopActionError("Desktop action disappeared from the queue.")
            if current.get("status") == "completed":
                result = current.get("result")
                if not isinstance(result, dict) or len(json.dumps(result)) > 2_100_000:
                    raise DesktopActionError("Desktop action returned an invalid result.")
                return result
            if current.get("status") in {"failed", "expired", "unknown"}:
                raise DesktopActionError(
                    str(current.get("error") or "Desktop action failed.")[:1_000]
                )
        raise DesktopActionError("Desktop action timed out before acknowledgement.")

