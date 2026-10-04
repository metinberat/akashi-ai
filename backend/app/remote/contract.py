"""Generate the remote presence contract shared with the TypeScript client.

``python -m app.remote.contract`` exits 1 when ``shared/contracts/remote`` is
stale; ``--write`` regenerates it. The frontend tests read the same files.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict

from app.devices.store import DeviceStore
from app.remote import capabilities, flow, identity, protocol, scopes
from app.remote.runtime import RemoteRuntime
from app.spatial.service import SpatialLabService

ROOT = Path(__file__).resolve().parents[3] / "shared" / "contracts" / "remote"


def protocol_contract() -> Dict[str, Any]:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        runtime = RemoteRuntime(DeviceStore(root / "devices.json", 600, 75), directory=None,
                                spatial=SpatialLabService(root / "spatial", interpreter="rules"))
        kinds = {name: {"delivery": spec.delivery, "any_of": sorted(spec.any_of), "rate_class": spec.rate_class,
                        "max_age_ms": spec.max_age_ms, "owner_only": spec.owner_only}
                 for name, spec in sorted(runtime.hub.kinds.items())}
    return {
        "protocol": protocol.PROTOCOL,
        "version": protocol.VERSION,
        "max_message_bytes": protocol.MAX_MESSAGE_BYTES,
        "max_batch": protocol.MAX_BATCH,
        "id_pattern": protocol.ID_PATTERN.pattern,
        "kind_pattern": protocol.KIND_PATTERN.pattern,
        "proof_prefix": identity.PROOF_PREFIX,
        "nonce_ttl_seconds": identity.NONCE_TTL_SECONDS,
        "kinds": kinds,
        "scopes": scopes.catalog(),
        "presets": scopes.PRESETS,
        "capabilities": sorted(capabilities.CAPABILITIES),
        "capability_states": list(capabilities.STATES),
        "rate_classes": {name: {"per_second": rate, "burst": burst} for name, (rate, burst) in flow.RATE_CLASSES.items()},
    }


def artifacts() -> Dict[str, str]:
    return {"protocol.json": json.dumps(protocol_contract(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"}


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
        print("Stale remote contract artifacts: " + ", ".join(stale) + ". Run: python -m app.remote.contract --write", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
