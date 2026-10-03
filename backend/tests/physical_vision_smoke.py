"""Manual targeted-window screenshot → configured vision-provider smoke test."""
from __future__ import annotations

import asyncio
import sys

from akashi_agent.actions import ActionExecutor
from akashi_agent.config import AgentSettings
from app.core.config import get_settings
from app.core.model_router import ModelRouter


async def main() -> int:
    if sys.platform != "win32":
        print("BLOCKED: Windows required")
        return 2
    executor = ActionExecutor(AgentSettings.from_env())
    state = executor.execute("get_desktop_state", {"limit": 200})["data"]
    candidates = [
        item for item in state["windows"]
        if item["process_name"].casefold() == "code.exe" and "akashi-ai" in item["title"].casefold()
    ]
    if not candidates:
        print("BLOCKED: AKASHI VS Code window not found")
        return 3
    target = candidates[0]
    focused = executor.execute(
        "window_control",
        {"operation": "focus", "window_id": target["window_id"]},
        approved=True,
    )["data"]
    if not focused["verified"]:
        print("BLOCKED: VS Code foreground verification failed")
        return 4
    capture = executor.execute("take_screenshot", {"window_id": target["window_id"]})["data"]
    provider = ModelRouter(get_settings()).provider_for("vision")
    if provider.name == "mock":
        print("BLOCKED: no configured vision provider")
        return 5
    answer = await provider.generate_with_images(
        message=(
            "This is a one-shot screenshot of the AKASHI project window selected for a physical test. "
            "State only the visible application and whether a code project/workspace is visibly open. "
            "Do not infer hidden content. Keep the answer under 40 words."
        ),
        system_prompt="Use only visible evidence in the supplied image.",
        history=[],
        intent="planning",
        images=[f"data:image/jpeg;base64,{capture['base64']}"],
    )
    print(f"WORKING: targeted {capture['source_window']['process_name']} screenshot analyzed by {provider.name}: {answer[:500]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
