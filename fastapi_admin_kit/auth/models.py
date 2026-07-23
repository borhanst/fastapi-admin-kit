"""SQLAlchemy models for admin auth: roles, users, permissions."""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from fastapi_admin_kit.auth.mixins import AuthModelMixin
from fastapi_admin_kit.models.base import Base

# Junction tables — no ORM models needed
admin_user_roles = Table(
    "admin_user_roles",
    Base.metadata,
    Column(
        "user_id",
        Integer,
        ForeignKey("admin_users.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "role_id",
        Integer,
        ForeignKey("admin_roles.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)

admin_role_permissions = Table(
    "admin_role_permissions",
    Base.metadata,
    Column(
        "role_id",
        Integer,
        ForeignKey("admin_roles.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "permission_id",
        Integer,
        ForeignKey("admin_permissions.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class Role(Base):
    __tablename__ = "admin_roles"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    description = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    users = relationship("User", secondary=admin_user_roles, back_populates="roles")
    permissions = relationship(
        "Permission", secondary=admin_role_permissions, back_populates="roles"
    )

    def __str__(self) -> str:
        return str(self.name)

    def __repr__(self) -> str:
        return f"<Role {self.name!r}>"


class User(AuthModelMixin, Base):
    """Admin user model with authentication support via AuthModelMixin.

    The mixin provides: hashed_password, is_active, is_superuser columns,
    role_ids property, verify_password() and hash_password() methods.
    """

    __tablename__ = "admin_users"

    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, nullable=False)
    full_name = Column(String(255))
    last_login = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    password_changed_at = Column(DateTime(timezone=True), nullable=True)

    # Many-to-many roles
    roles = relationship("Role", secondary=admin_user_roles, back_populates="users")
    # Direct permission overrides
    direct_permissions = relationship(
        "UserPermission",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    refresh_tokens = relationship(
        "RefreshToken", back_populates="user", cascade="all, delete-orphan"
    )
    totp = relationship(
        "UserTOTP",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )

    def __str__(self) -> str:
        return str(self.email)

    def __repr__(self) -> str:
        return f"<User {self.email!r}>"


class Permission(Base):
    """Permission matrix per model — shared across roles via M2M."""

    __tablename__ = "admin_permissions"
    __table_args__ = (UniqueConstraint("name", name="uq_admin_perm_name"),)

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    table_name = Column(String(255), nullable=False)
    can_view = Column(Boolean, default=False)
    can_create = Column(Boolean, default=False)
    can_edit = Column(Boolean, default=False)
    can_delete = Column(Boolean, default=False)

    roles = relationship("Role", secondary=admin_role_permissions, back_populates="permissions")

    def __str__(self) -> str:
        return str(self.name)

    def __repr__(self) -> str:
        return f"<Permission name={self.name!r} table={self.table_name!r}>"


class UserPermission(Base):
    """Direct per-user permission overrides — merged with role permissions."""

    __tablename__ = "admin_user_permissions"
    __table_args__ = (
        UniqueConstraint("user_id", "permission_id", name="uq_admin_user_perm_user_perm"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(
        Integer,
        ForeignKey("admin_users.id", ondelete="CASCADE"),
        nullable=False,
    )
    permission_id = Column(
        Integer,
        ForeignKey("admin_permissions.id", ondelete="CASCADE"),
        nullable=False,
    )

    user = relationship("User", back_populates="direct_permissions")
    permission = relationship("Permission", backref="user_overrides")

    def __str__(self) -> str:
        if self.permission:
            return f"{self.permission.name} (user {self.user_id})"
        return f"user {self.user_id}"

    def __repr__(self) -> str:
        return f"<UserPermission user={self.user_id} perm={self.permission_id}>"


class RefreshToken(Base):
    __tablename__ = "admin_refresh_tokens"

    id = Column(Integer, primary_key=True)
    user_id = Column(
        Integer,
        ForeignKey("admin_users.id", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash = Column(String(64), nullable=False, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    revoked_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="refresh_tokens")

    __table_args__ = (UniqueConstraint("user_id", "token_hash", name="uq_admin_refresh_token"),)

    def __str__(self) -> str:
        return f"Token {self.token_hash[:8]}..."

    def __repr__(self) -> str:
        return f"<RefreshToken user={self.user_id}>"


class UserTOTP(Base):
    __tablename__ = "admin_user_totp"

    id = Column(Integer, primary_key=True)
    user_id = Column(
        Integer,
        ForeignKey("admin_users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    secret_key = Column(String(255), nullable=False)
    enabled = Column(Boolean, default=False)
    backup_codes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="totp")

    def __str__(self) -> str:
        return f"TOTP for user {self.user_id}"

    def __repr__(self) -> str:
        return f"<UserTOTP user={self.user_id}>"


class LoginAttempt(Base):
    __tablename__ = "admin_login_attempts"

    id = Column(Integer, primary_key=True)
    email = Column(String(255), nullable=False, index=True)
    ip_address = Column(String(45), nullable=False)
    user_agent = Column(String(512), nullable=True)
    success = Column(Boolean, default=False)
    note = Column(Text, nullable=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("id", name="uq_admin_login_attempt_id"),)

    def __str__(self) -> str:
        return f"{self.email} - {'success' if self.success else 'failed'}"

    def __repr__(self) -> str:
        return f"<LoginAttempt email={self.email!r} success={self.success}>"
