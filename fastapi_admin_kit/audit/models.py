"""SQLAlchemy model for the admin audit log."""

from __future__ import annotations

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.sql import func

from fastapi_admin_kit.models.base import Base


class AuditLog(Base):
    __tablename__ = "admin_audit_log"
    __table_args__ = (
        Index("idx_audit_model", "model_name", "table_name"),
        Index("idx_audit_user", "user_id"),
        Index("idx_audit_timestamp", "timestamp"),
        Index("idx_audit_object", "table_name", "object_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer,
        ForeignKey("admin_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    user_email = Column(String(255))
    action = Column(String(10), nullable=False)  # CREATE | UPDATE | DELETE
    model_name = Column(String(255), nullable=False)
    table_name = Column(String(255), nullable=False)
    object_id = Column(String(255), nullable=False)
    object_repr = Column(String(500))
    changes = Column(JSON)  # diff (null for CREATE/DELETE)
    full_snapshot = Column(JSON)  # full object state at time of action
    ip_address = Column(String(45))
    user_agent = Column(Text)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())

    def __str__(self) -> str:
        return f"{self.action} {self.model_name}#{self.object_id}"

    def __repr__(self) -> str:
        return f"<AuditLog {self.action} {self.model_name}#{self.object_id}>"
