"""Authentication configuration."""

from typing import TYPE_CHECKING, Any

from fastapi_admin_kit.exceptions import ConfigError

if TYPE_CHECKING:
    pass


class AuthConfig:
    """Authentication configuration."""

    def __init__(
        self,
        auth_model: type | None = None,
        auth_backend: Any | None = None,
        password_hasher: Any | None = None,
        session_ttl: int = 28800,
        session_cookie_name: str = "admin_session",
        session_secure: bool = True,
        superuser_emails: list[str] | None = None,
        password_min_length: int = 12,
        password_require_uppercase: bool = True,
        password_require_lowercase: bool = True,
        password_require_digit: bool = True,
        password_require_special: bool = True,
        session_samesite: str = "strict",
    ):
        self.auth_model = auth_model
        self.auth_backend = auth_backend
        self.password_hasher = password_hasher
        self.session_ttl = session_ttl
        self.session_cookie_name = session_cookie_name
        self.session_secure = session_secure
        self.superuser_emails = superuser_emails or []
        self.password_min_length = password_min_length
        self.password_require_uppercase = password_require_uppercase
        self.password_require_lowercase = password_require_lowercase
        self.password_require_digit = password_require_digit
        self.password_require_special = password_require_special
        self.session_samesite = session_samesite

    def get_hasher(self) -> Any:
        """Return the configured password hasher, or default BcryptHasher."""
        if self.password_hasher is not None:
            return self.password_hasher
        from fastapi_admin_kit.auth.hasher import BcryptHasher

        return BcryptHasher

    def validate_auth_model(self) -> None:
        """Validate that auth_model satisfies AdminUserProtocol."""
        model = self.auth_model
        if model is None:
            return

        # Required: id, email
        required_attrs = ["id", "email"]
        missing = [attr for attr in required_attrs if not hasattr(model, attr)]
        if missing:
            raise ConfigError(
                f"auth_model {model.__name__!r} is missing required attributes: "
                f"{', '.join(missing)}. Every auth model must have id and email."
            )

        # Required: is_active, is_superuser (can be provided by AutoModelMixin)
        missing_flags = []
        if not hasattr(model, "is_active"):
            missing_flags.append("is_active")
        if not hasattr(model, "is_superuser"):
            missing_flags.append("is_superuser")
        if missing_flags:
            raise ConfigError(
                f"auth_model {model.__name__!r} is missing: {', '.join(missing_flags)}. "
                f"Use AutoModelMixin or add these columns to your model."
            )

        # Required: roles or role_ids (for RBAC)
        if not hasattr(model, "roles") and not hasattr(model, "role_ids"):
            raise ConfigError(
                f"auth_model {model.__name__!r} has no 'roles' relationship or "
                f"'role_ids' property. RBAC requires role lookups. "
                f"Use AutoModelMixin or define a roles relationship on your model."
            )

        # Check password-related attributes for authentication
        missing_auth = []
        if not hasattr(model, "hashed_password"):
            missing_auth.append("hashed_password")
        if not callable(getattr(model, "verify_password", None)):
            missing_auth.append("verify_password()")
        if missing_auth:
            raise ConfigError(
                f"auth_model {model.__name__!r} is missing password-related "
                f"attributes: {', '.join(missing_auth)}. "
                f"Use AutoModelMixin or implement hashed_password (str) and "
                f"verify_password(password) -> bool."
            )
