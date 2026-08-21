"""Session backend — ABC + signed-cookie implementation."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Any

from itsdangerous import (
    BadSignature,
    SignatureExpired,
    URLSafeTimedSerializer,
)


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

    The cookie value is a ``URLSafeTimedSerializer``-serialized string — the JSON
    payload is base64-encoded so its output is safe for ``Cookie`` headers (unlike
    raw JSON, which contains ``{``, ``}``, ``\"`` and other characters that break
    the ``http.cookies.SimpleCookie`` parser).
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
        self._serializer = URLSafeTimedSerializer(secret_key, salt="admin-session")
        # Separate salt + short TTL: a pending-2FA token can never be
        # replayed as a full session cookie (different signing domain).
        self._mfa_serializer = URLSafeTimedSerializer(secret_key, salt="admin-2fa")
        self._mfa_ttl = 300
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
        """Sign *payload* and return the signed token."""
        if "iat" not in payload:
            payload["iat"] = time.time()
        return self._serializer.dumps(payload)

    def decode(self, token: str | None) -> dict[str, Any] | None:
        """Verify *token* and return the decoded payload dict, or ``None``.

        Tokens without an ``iat`` claim are rejected outright (S18): the
        ``iat`` timestamp powers the password-change invalidation check, and
        a token minted without it would silently bypass that revocation.
        """
        if not token:
            return None
        try:
            payload = self._serializer.loads(token, max_age=self._session_ttl)
        except (BadSignature, SignatureExpired, ValueError):
            return None
        if not isinstance(payload, dict) or "iat" not in payload:
            return None
        return payload

    def should_secure(self, request: Any) -> bool:
        """Return True only when the configured secure flag is set AND the
        current request arrived over HTTPS.  This prevents browsers from
        dropping the cookie on plain-HTTP dev servers."""
        if not self.secure:
            return False
        return getattr(request.url, "scheme", "") == "https"

    def load(self, token: str | None) -> dict[str, Any] | None:
        """Alias for decode — used by flash message system."""
        return self.decode(token)

    def encode_pending_2fa(self, user_id: int | str) -> str:
        """Sign a short-lived token proving credentials were verified but 2FA is pending."""
        return self._mfa_serializer.dumps({"user_id": user_id})

    def decode_pending_2fa(self, token: str | None) -> int | str | None:
        """Verify a pending-2FA token and return the user_id, or ``None``."""
        if not token:
            return None
        try:
            payload = self._mfa_serializer.loads(token, max_age=self._mfa_ttl)
        except (BadSignature, SignatureExpired, ValueError):
            return None
        return payload.get("user_id")

    def save(self, response: Any, data: dict[str, Any], *, request: Any | None = None) -> None:
        """Encode *data* and set it as a signed cookie on *response*."""
        token = self.encode(data)
        if request is not None:
            secure = self.should_secure(request)
        else:
            secure = self.secure
        response.set_cookie(
            key=self.cookie_name,
            value=token,
            max_age=self._session_ttl,
            path="/",
            secure=secure,
            httponly=True,
            samesite="strict",
        )
