"""Small fail-closed bearer-token guard for personal backend access."""

import secrets
from typing import Optional

from fastapi import Header, HTTPException

from app.core.config import get_settings


def require_api_token(authorization: Optional[str] = Header(default=None)) -> None:
    expected = get_settings().api_token
    if not expected or len(expected) < 32:
        raise HTTPException(status_code=503, detail="Backend access token is not configured.")

    scheme, separator, token = (authorization or "").partition(" ")
    if not separator or scheme.lower() != "bearer" or len(token) > 512 or not secrets.compare_digest(token.encode("utf-8"), expected.encode("utf-8")):
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing access token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
