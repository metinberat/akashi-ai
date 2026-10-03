"""Generate the cross-language Spatial Lab contract artifacts.

``shared/contracts/spatial/requests.schema.json`` — JSON Schema of the public
request contract (from the pydantic models). ``replay-fixture.json`` — a
deterministic recorded session (with undo/redo) and its expected final state.

Both are checked in. The backend test fails if they are stale; the frontend
test validates TypeScript-built requests against the schema and reconstructs the
fixture with the client's replay code. Regenerate with:

    python -m app.spatial.contract --write
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from itertools import count
from pathlib import Path
from typing import Any, Dict

from app.history import ActionHistory
from app.spatial.assets import AssetRegistry
from app.spatial.compiler import CompileContext, compile_request
from app.spatial.domain import SpatialSceneDomain
from app.spatial.form_library import FormLibrary
from app.spatial.model import initial_scene
from app.spatial.requests import REQUEST_ADAPTER, parse_request

ROOT = Path(__file__).resolve().parents[3] / "shared" / "contracts" / "spatial"


def request_schema() -> Dict[str, Any]:
    return REQUEST_ADAPTER.json_schema()


def replay_fixture() -> Dict[str, Any]:
    ticks = count(1)
    ids = count(1)
    history = ActionHistory.create(SpatialSceneDomain(), "spatial-00000000000000ff", initial_scene(),
                                   clock=lambda: f"2026-01-01T00:00:{next(ticks):02d}+00:00",
                                   ids=lambda: f"event-{next(ids):04d}")
    objects = count(1)
    with tempfile.TemporaryDirectory() as temp:
        assets = AssetRegistry(Path(temp), FormLibrary(None, candidates=[]))
        origin = {"kind": "ui", "provider": "contract-fixture"}
        script = [
            {"type": "scene.add_asset", "fixture": "calibration"},
            {"type": "scene.add_asset", "fixture": "calibration", "label": "Second"},
            {"type": "object.transform", "target": {"ref": "leftmost"}, "mode": "rotate", "degrees": 90},
            {"type": "object.transform", "target": {"ref": "selected"}, "mode": "scale", "factor": 1.5},
            {"type": "object.display", "target": {"ref": "selected"}, "skeleton": True},
            {"type": "history.undo"},
            {"type": "history.undo"},
            {"type": "history.redo"},
            {"type": "animation.control", "target": {"ref": "leftmost"}, "action": "play", "clip": "sway"},
            {"type": "view.set", "hud_visible": False},
            {"type": "selection.select", "target": {"ref": "rightmost"}},
        ]
        for raw in script:
            prepared = compile_request(parse_request(raw), CompileContext(
                state=history.state, events=history.events, assets=assets,
                new_id=lambda: f"obj-{next(objects):012x}"))
            if prepared.history == "undo":
                history.undo(origin, prepared.request)
            elif prepared.history == "redo":
                history.redo(origin, prepared.request)
            else:
                for command in prepared.commands:
                    history.execute(command, origin, prepared.request)
    return {
        "schema": "akashi.spatial.contract-fixture/1",
        "header": history.log.header,
        "initial_state": history.initial_state,
        "events": history.events,
        "final_state": history.state,
        "final_digest": history.digest(),
    }


def artifacts() -> Dict[str, str]:
    return {
        "requests.schema.json": json.dumps(request_schema(), indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        "replay-fixture.json": json.dumps(replay_fixture(), indent=1, sort_keys=True, ensure_ascii=False) + "\n",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    stale = []
    for name, content in artifacts().items():
        path = ROOT / name
        if args.write:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        elif not path.exists() or path.read_text(encoding="utf-8") != content:
            stale.append(name)
    if stale:
        print("Stale contract artifacts: " + ", ".join(stale) + ". Run: python -m app.spatial.contract --write", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
