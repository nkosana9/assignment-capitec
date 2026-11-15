"""Signed, expiring download tokens.

A token is a JWT (HS256) whose claims identify the stored object and its expiry.
Verification needs only the signing key, so the server keeps no per-link state.
"""

import time
import uuid

import jwt

_ALGORITHM = "HS256"
_AUDIENCE = "customer-account-svc"


class LinkError(Exception):
    """Base class for download-token failures."""


class LinkExpired(LinkError):
    pass


class LinkInvalid(LinkError):
    pass


def issue_download_token(
    *, object_key: str, filename: str, owner: str, signing_key: str, ttl_seconds: int
) -> tuple[str, int]:
    """Return (token, expiry as a Unix timestamp). `owner` is the customer the file belongs to."""
    issued_at = int(time.time())
    expires_at = issued_at + ttl_seconds
    claims = {
        "sub": object_key,
        "fn": filename,
        "own": owner,
        "iat": issued_at,
        "exp": expires_at,
        "aud": _AUDIENCE,
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(claims, signing_key, algorithm=_ALGORITHM), expires_at


def verify_download_token(token: str, signing_key: str) -> dict:
    try:
        return jwt.decode(
            token,
            signing_key,
            algorithms=[_ALGORITHM],
            audience=_AUDIENCE,
            options={"require": ["exp", "iat", "sub", "aud"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise LinkExpired from exc
    except jwt.PyJWTError as exc:
        raise LinkInvalid from exc
