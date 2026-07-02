"""Session backend — ABC + signed-cookie implementation."""

from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from typing import Any

from itsdangerous import BadSignature, SignatureExpired, TimestampSigner


class SessionBackend(ABC):
    """Abstract session backend — encode/decode session payloads."""

    @abstractmethod
    def encode(self, payload: dict[str, Any]) -> str:
        """Sign *payload* and return a token string suitable for a cookie."""
        ...

    @abstractmethod
    def decode(self, token: str | None) -> dict[str, Any] | None:
        """Verify *token* and return the payload dict, or ``None`` if invalid/expired."""
        ...


class SignedCookieSessionBackend(SessionBackend):
    """Session backend that signs a JSON payload using ``itsdangerous``.

    The cookie value is a ``TimestampSigner``-signed, base64-encoded JSON string
    containing at minimum ``{"user_id": <int|str>}``.
    """

    COOKIE_NAME = "admin_session"

    def __init__(
        self,
        secret_key: str,
        session_ttl: int = 28800,
        cookie_name: str = COOKIE_NAME,
        secure: bool = False,
    ) -> None:
        self._secret_key = secret_key
        self._signer = TimestampSigner(secret_key)
        self._session_ttl = session_ttl
        self.cookie_name = cookie_name
        self.secure = secure

    @property
    def secret_key(self) -> str:
        """The signing key used by this backend.

        Public accessor so CSRF / JWT signing can share the same key without
        reaching into the (private) itsdangerous signer. Swapping the session
        backend no longer silently breaks CSRF.
        """
        return self._secret_key

    def encode(self, payload: dict[str, Any]) -> str:
        """Sign *payload* and return the signed token.

        Automatically adds ``iat`` (issued-at) timestamp if not present.
        """
        if "iat" not in payload:
            payload["iat"] = time.time()
        data = json.dumps(payload, separators=(",", ":")).encode()
        return self._signer.sign(data).decode()

    def decode(self, token: str | None) -> dict[str, Any] | None:
        """Verify *token* and return the decoded payload, or ``None``."""
        if not token:
            return None
        try:
            data = self._signer.unsign(token, max_age=self._session_ttl)
            return json.loads(data.decode())
        except (BadSignature, SignatureExpired, ValueError, json.JSONDecodeError):
            return None
