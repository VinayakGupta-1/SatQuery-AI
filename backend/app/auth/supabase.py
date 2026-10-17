"""Verifying Supabase access tokens without asking Supabase each time.

A Supabase project signs its users' access tokens with an asymmetric key
(ES256) and publishes the public half at ``/auth/v1/.well-known/jwks.json``.
The backend fetches that key set once, caches it, and checks every token
locally: signature, expiry, issuer (this project), audience (``authenticated``)
and role. A token from another project, an expired one, or an anonymous key
passed off as a user token is refused.

Sign-up, email verification, sign-in and password recovery all happen between
the browser and Supabase. The backend only needs to know that a request comes
from a verified user, and which one.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from app import USER_AGENT
from app.config.settings import Settings, get_settings

#: Supabase issues user tokens with this audience and role.
AUDIENCE = "authenticated"
ALGORITHMS = ["ES256", "RS256", "EdDSA"]


class AuthenticationError(Exception):
    """The request does not come from a verified user."""


@dataclass(frozen=True)
class User:
    id: str
    email: str | None
    #: The access token itself, used to act as this user against the
    #: database, so row level security applies to everything the backend does
    #: on their behalf.
    token: str


class SupabaseVerifier:
    """Checks access tokens issued by one Supabase project."""

    def __init__(self, project_url: str) -> None:
        import jwt

        self.issuer = f"{project_url.rstrip('/')}/auth/v1"
        self._keys = jwt.PyJWKClient(
            f"{self.issuer}/.well-known/jwks.json",
            cache_keys=True,
            lifespan=3600,
            headers={"User-Agent": USER_AGENT},
            timeout=10,
        )

    def verify(self, token: str) -> User:
        import jwt

        try:
            key = self._keys.get_signing_key_from_jwt(token)
        except jwt.PyJWKClientConnectionError as error:
            raise AuthenticationError(
                "Sign-in could not be checked: the authentication service is unreachable."
            ) from error
        except jwt.PyJWTError as error:
            raise AuthenticationError("The sign-in token is not valid.") from error

        try:
            claims = jwt.decode(
                token,
                key.key,
                algorithms=ALGORITHMS,
                audience=AUDIENCE,
                issuer=self.issuer,
                options={"require": ["exp", "iat", "sub", "aud", "iss"]},
            )
        except jwt.ExpiredSignatureError as error:
            raise AuthenticationError("Your session has expired. Sign in again.") from error
        except jwt.PyJWTError as error:
            raise AuthenticationError("The sign-in token is not valid.") from error

        if claims.get("role") != AUDIENCE:
            raise AuthenticationError("The sign-in token does not belong to a user.")
        return User(id=str(claims["sub"]), email=claims.get("email"), token=token)


_verifier: SupabaseVerifier | None = None
_verifier_url: str | None = None
_lock = threading.Lock()


def get_verifier(settings: Settings | None = None) -> SupabaseVerifier:
    """The verifier for the configured project, created once and reused."""
    global _verifier, _verifier_url
    settings = settings or get_settings()
    with _lock:
        if _verifier is None or _verifier_url != settings.supabase_url:
            _verifier = SupabaseVerifier(settings.supabase_url)
            _verifier_url = settings.supabase_url
        return _verifier


def reset_verifier() -> None:
    global _verifier, _verifier_url
    with _lock:
        _verifier = None
        _verifier_url = None


__all__ = ["AuthenticationError", "SupabaseVerifier", "User", "get_verifier", "reset_verifier"]
