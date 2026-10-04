import importlib
import pkgutil
import re
from dataclasses import asdict
from typing import Any, Dict, List, Optional, Tuple

from app.live import actions as actions_package
from app.live.actions.base import LiveAction, LiveActionRuntime
from app.remote import context as remote_context
from app.live.models import ActionMatch


class LiveActionRegistry:
    """Discover action modules without a central dispatch chain."""

    def __init__(self, runtime: LiveActionRuntime) -> None:
        self._actions: Dict[str, LiveAction] = {}
        self._rejections: List[Dict[str, str]] = []
        prefix = actions_package.__name__ + "."
        for module_info in sorted(
            pkgutil.iter_modules(actions_package.__path__, prefix),
            key=lambda item: item.name,
        ):
            if module_info.name.endswith(".base"):
                continue
            try:
                module = importlib.import_module(module_info.name)
                factory = getattr(module, "create_actions", None)
                if factory is None:
                    continue
                for action in factory(runtime):
                    definition = action.definition
                    name = definition.name
                    if not re.fullmatch(r"[a-z][a-z0-9_.-]{1,79}", name):
                        raise ValueError(f"Invalid action name '{name}'.")
                    if name in self._actions:
                        raise ValueError(f"Duplicate action name '{name}'.")
                    if not definition.description.strip():
                        raise ValueError(f"Action '{name}' has no description.")
                    if definition.risk not in {"safe", "confirm", "restricted"}:
                        raise ValueError(f"Action '{name}' has an invalid risk level.")
                    if definition.input_schema.get("type") != "object":
                        raise ValueError(f"Action '{name}' must declare an object input schema.")
                    self._actions[name] = action
            except Exception as exc:
                # One optional action must not take the whole Core offline.
                self._rejections.append({
                    "module": module_info.name.rsplit(".", 1)[-1],
                    "error": str(exc)[:300],
                })

    def definitions(self) -> List[Dict[str, Any]]:
        return [asdict(self._actions[name].definition) for name in sorted(self._actions)]

    def diagnostics(self) -> Dict[str, Any]:
        return {
            "active": len(self._actions),
            "rejected": list(self._rejections),
        }

    def select(self, message: str) -> Optional[Tuple[LiveAction, ActionMatch]]:
        matches: List[Tuple[int, str, LiveAction, ActionMatch]] = []
        for name, action in self._actions.items():
            if not remote_context.live_action_allowed(name):
                continue  # a remote device's utterance may only reach remote-safe actions
            match = action.match(message)
            if match is not None:
                matches.append((match.score, name, action, match))
        if not matches:
            return None
        _, _, action, match = max(matches, key=lambda item: (item[0], item[1]))
        return action, match
