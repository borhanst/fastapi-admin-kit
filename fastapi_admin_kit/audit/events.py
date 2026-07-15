"""Audit events — data structures for audit events."""

from __future__ import annotations

import datetime
from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class AuditEvent:
    """Represents a single audit event (CREATE, UPDATE, DELETE, EXPORT, or IMPORT).

    This is a pure data structure with no side effects, making it
    easy to test and serialize.
    """

    event_type: str  # "CREATE" | "UPDATE" | "DELETE" | "EXPORT" | "IMPORT"
    model_name: str
    table_name: str
    object_id: str
    object_repr: str = ""
    changes: dict[str, Any] | None = None
    full_snapshot: dict[str, Any] | None = None
    user_id: int | None = None
    user_email: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    timestamp: datetime.datetime | None = None

    def __post_init__(self) -> None:
        if self.timestamp is None:
            self.timestamp = datetime.datetime.now(datetime.UTC)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the event to a dictionary."""
        data = asdict(self)
        if self.timestamp is not None:
            data["timestamp"] = self.timestamp.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AuditEvent:
        """Deserialize an event from a dictionary."""
        ts = data.get("timestamp")
        if isinstance(ts, str):
            data["timestamp"] = datetime.datetime.fromisoformat(ts)
        return cls(**data)
