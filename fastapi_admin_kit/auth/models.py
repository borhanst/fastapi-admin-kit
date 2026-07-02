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

from fastapi_admin_kit.modeladmin import ModelAdmin
from fastapi_admin_kit.models.base import Base

# Junction table — no ORM model needed
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


class AdminRole(Base):
    __tablename__ = "admin_roles"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    description = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    users = relationship(
        "AdminUser", secondary=admin_user_roles, back_populates="roles"
    )
    permissions = relationship(
        "AdminPermission", back_populates="role", cascade="all, delete-orphan"
    )

    def __str__(self) -> str:
        return str(self.name)

    def __repr__(self) -> str:
        return f"<AdminRole {self.name!r}>"


class AdminUser(Base):
    __tablename__ = "admin_users"

    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(255))
    is_superuser = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    last_login = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    password_changed_at = Column(DateTime(timezone=True), nullable=True)

    # Many-to-many roles
    roles = relationship(
        "AdminRole", secondary=admin_user_roles, back_populates="users"
    )
    # Direct permission overrides
    direct_permissions = relationship(
        "AdminUserPermission",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    refresh_tokens = relationship(
        "AdminRefreshToken", back_populates="user", cascade="all, delete-orphan"
    )
    totp = relationship(
        "AdminUserTOTP",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )

    @property
    def role_ids(self) -> list[int]:
        return [r.id for r in self.roles]

    def __str__(self) -> str:
        return str(self.email)

    def __repr__(self) -> str:
        return f"<AdminUser {self.email!r}>"


class AdminPermission(Base):
    """Permission matrix per role per model."""

    __tablename__ = "admin_permissions"
    __table_args__ = (
        UniqueConstraint(
            "role_id", "table_name", name="uq_admin_perm_role_table"
        ),
    )

    id = Column(Integer, primary_key=True)
    role_id = Column(
        Integer,
        ForeignKey("admin_roles.id", ondelete="CASCADE"),
        nullable=False,
    )
    table_name = Column(String(255), nullable=False)
    can_view = Column(Boolean, default=False)
    can_create = Column(Boolean, default=False)
    can_edit = Column(Boolean, default=False)
    can_delete = Column(Boolean, default=False)

    role = relationship("AdminRole", back_populates="permissions")

    def __str__(self) -> str:
        return f"{self.table_name} (role {self.role_id})"

    def __repr__(self) -> str:
        return (
            f"<AdminPermission role={self.role_id} table={self.table_name!r}>"
        )


class AdminUserPermission(Base):
    """Direct per-user permission overrides — merged with role permissions."""

    __tablename__ = "admin_user_permissions"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "table_name", name="uq_admin_user_perm_user_table"
        ),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(
        Integer,
        ForeignKey("admin_users.id", ondelete="CASCADE"),
        nullable=False,
    )
    table_name = Column(String(255), nullable=False)
    can_view = Column(Boolean, default=False)
    can_create = Column(Boolean, default=False)
    can_edit = Column(Boolean, default=False)
    can_delete = Column(Boolean, default=False)

    user = relationship("AdminUser", back_populates="direct_permissions")

    def __str__(self) -> str:
        return f"{self.table_name} (user {self.user_id})"

    def __repr__(self) -> str:
        return f"<AdminUserPermission user={self.user_id} table={self.table_name!r}>"


class AdminRefreshToken(Base):
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

    user = relationship("AdminUser", back_populates="refresh_tokens")

    __table_args__ = (
        UniqueConstraint(
            "user_id", "token_hash", name="uq_admin_refresh_token"
        ),
    )

    def __str__(self) -> str:
        return f"Token {self.token_hash[:8]}..."

    def __repr__(self) -> str:
        return f"<AdminRefreshToken user={self.user_id}>"


class AdminRefreshTokenAdmin(ModelAdmin):
    exclude = ["user"]


class AdminUserTOTP(Base):
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

    user = relationship("AdminUser", back_populates="totp")

    def __str__(self) -> str:
        return f"TOTP for user {self.user_id}"

    def __repr__(self) -> str:
        return f"<AdminUserTOTP user={self.user_id}>"


class AdminLoginAttempt(Base):
    __tablename__ = "admin_login_attempts"

    id = Column(Integer, primary_key=True)
    email = Column(String(255), nullable=False, index=True)
    ip_address = Column(String(45), nullable=False)
    user_agent = Column(String(512), nullable=True)
    success = Column(Boolean, default=False)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("id", name="uq_admin_login_attempt_id"),)

    def __str__(self) -> str:
        return f"{self.email} - {'success' if self.success else 'failed'}"

    def __repr__(self) -> str:
        return (
            f"<AdminLoginAttempt email={self.email!r} success={self.success}>"
        )
