"""The request's user, as a FastAPI dependency.

With Supabase configured, every analysis endpoint requires
``Authorization: Bearer <access token>`` from a signed-in, email-verified
user (Supabase does not issue a token before the address is confirmed).
Without it the API is open, as before, and the dependency yields ``None``.
"""

from __future__ import annotations

from fastapi import Header, HTTPException

from app.auth import AuthenticationError, User, get_verifier
from app.config.settings import get_settings

SIGN_IN_REQUIRED = "Sign in to use SatQuery."


def current_user(authorization: str | None = Header(None)) -> User | None:
    """The verified user making this request, or ``None`` when auth is off."""
    settings = get_settings()
    if not settings.auth_enabled:
        return None
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(401, SIGN_IN_REQUIRED, headers={"WWW-Authenticate": "Bearer"})
    try:
        return get_verifier(settings).verify(token.strip())
    except AuthenticationError as error:
        raise HTTPException(401, str(error), headers={"WWW-Authenticate": "Bearer"}) from error


__all__ = ["SIGN_IN_REQUIRED", "current_user"]
