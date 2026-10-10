"""
Minimal API-key authentication (report section 4.2.4: "authenticating
requests"). Deliberately simple -- a single shared key via header -- since
a full user/role system is out of scope for this case study; swap for
OAuth2/JWT later without touching route logic (just this dependency).
"""

from __future__ import annotations

from fastapi import Header, HTTPException, status

from api.config import settings


def require_api_key(x_api_key: str = Header(...)) -> None:
    if x_api_key != settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-API-Key header",
        )
