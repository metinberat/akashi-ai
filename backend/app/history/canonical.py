"""Canonical JSON and content digests shared by every action-history stream.

Digests must be identical across processes and platforms, so documents are
serialised with sorted keys, no insignificant whitespace, no NaN/Infinity and
negative zero folded to zero. Domains that store floats produced by
trigonometry should quantise them before they reach a document (see
``quantize``) so that libm differences cannot change a digest.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any


def _normalize(value: Any) -> Any:
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Non-finite numbers cannot enter an action document.")
        return 0.0 if value == 0 else value
    if isinstance(value, dict):
        return {str(key): _normalize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(
        _normalize(value),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def quantize(value: float, places: int = 6) -> float:
    """Round to a fixed number of decimal places and fold negative zero."""
    if not math.isfinite(value):
        raise ValueError("Non-finite numbers cannot be quantized.")
    rounded = round(float(value), places)
    return 0.0 if rounded == 0 else rounded
