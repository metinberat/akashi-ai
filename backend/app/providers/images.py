"""Bounded inline image input. Never fetch client-supplied remote URLs."""
import base64
import binascii
from typing import Tuple


def decode_image(value: str) -> Tuple[str, bytes]:
    header, separator, encoded = value.partition(",")
    allowed = {"data:image/png;base64": "image/png", "data:image/jpeg;base64": "image/jpeg", "data:image/webp;base64": "image/webp"}
    if not separator or header not in allowed or len(encoded) > 7_000_000:
        raise ValueError("Use a PNG, JPEG or WebP image smaller than 5 MB.")
    try:
        data = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("Invalid image encoding.") from exc
    mime = allowed[header]
    valid = ((mime == "image/png" and data.startswith(b"\x89PNG\r\n\x1a\n")) or
             (mime == "image/jpeg" and data.startswith(b"\xff\xd8\xff")) or
             (mime == "image/webp" and data[:4] == b"RIFF" and data[8:12] == b"WEBP"))
    if not valid or len(data) > 5 * 1024 * 1024:
        raise ValueError("Invalid image signature or size.")
    return mime, data
