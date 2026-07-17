"""Usage tracking — UsageInfo, AIUsageWriter, AIUsageLog model."""

from __future__ import annotations

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.sql import func

from fastapi_admin_kit.models.base import Base


class AIUsageLog(Base):
    """SQLAlchemy model for AI usage logging."""

    __tablename__ = "admin_ai_usage_log"
    __table_args__ = (
        Index("idx_ai_usage_agent", "agent_name", "timestamp"),
        Index("idx_ai_usage_user", "user_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_name = Column(String(100), nullable=False)
    model = Column(String(255), nullable=False)
    user_id = Column(
        Integer,
        ForeignKey("admin_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    user_email = Column(String(255))
    request_tokens = Column(Integer, default=0)
    response_tokens = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)
    cost = Column(Numeric(12, 6), default=0)
    tool_calls = Column(JSON)
    success = Column(Boolean, default=True)
    error = Column(Text)
    latency_ms = Column(Integer)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())


class AIConversation(Base):
    """SQLAlchemy model for AI conversations."""

    __tablename__ = "admin_ai_conversations"
    __table_args__ = (Index("idx_ai_conv_user", "user_id", "last_message_at"),)

    id = Column(String(36), primary_key=True)
    agent_name = Column(String(100), nullable=False)
    user_id = Column(
        Integer,
        ForeignKey("admin_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    user_email = Column(String(255))
    title = Column(String(255))
    status = Column(String(20), default="active")
    message_history = Column(JSON)
    total_tokens = Column(Integer, default=0)
    total_cost = Column(Numeric(12, 6), default=0)
    turn_count = Column(Integer, default=0)
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    last_message_at = Column(DateTime(timezone=True))


class AIMessage(Base):
    """SQLAlchemy model for AI conversation messages."""

    __tablename__ = "admin_ai_messages"
    __table_args__ = (Index("idx_ai_msg_conv", "conversation_id", "created_at"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(
        String(36),
        ForeignKey("admin_ai_conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    role = Column(String(20), nullable=False)
    content = Column(Text)
    tool_name = Column(String(100))
    tool_args = Column(JSON)
    tool_result = Column(JSON)
    tokens = Column(Integer)
    latency_ms = Column(Integer)
    error = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AIUsageWriter:
    """Writes AI usage logs and aggregates statistics."""

    async def write(
        self,
        *,
        agent_name: str,
        model: str,
        request_tokens: int,
        response_tokens: int,
        total_tokens: int,
        cost: float,
        user: Any,
        success: bool,
        session: Any,
        error: str | None = None,
        latency_ms: int | None = None,
        tool_calls: list[dict] | None = None,
    ) -> None:
        session.add(
            AIUsageLog(
                agent_name=agent_name,
                model=model,
                user_id=getattr(user, "id", None),
                user_email=getattr(user, "email", None),
                request_tokens=request_tokens,
                response_tokens=response_tokens,
                total_tokens=total_tokens,
                cost=cost,
                tool_calls=tool_calls or [],
                success=success,
                error=error,
                latency_ms=latency_ms,
            )
        )
        await session.commit()

    async def aggregate(
        self,
        agent_name: str,
        period: str,
        session: Any,
    ) -> dict:
        from sqlalchemy import func as sqlfunc
        from sqlalchemy import select

        from fastapi_admin_kit.ai.usage import AIUsageLog

        interval_map = {"day": "1 day", "week": "7 days", "month": "30 days"}
        interval = interval_map.get(period, "1 day")
        days = int(interval.split()[0])

        result = await session.execute(
            select(
                sqlfunc.sum(AIUsageLog.total_tokens).label("total_tokens"),
                sqlfunc.sum(AIUsageLog.cost).label("total_cost"),
                sqlfunc.count(AIUsageLog.id).label("total_runs"),
                sqlfunc.avg(AIUsageLog.latency_ms).label("avg_latency_ms"),
                sqlfunc.sum(
                    sqlfunc.case(
                        (AIUsageLog.success == True, 1),  # noqa: E712
                        else_=0,
                    )
                ).label("success_count"),
            )
            .where(AIUsageLog.agent_name == agent_name)
            .where(AIUsageLog.timestamp >= func.now() - func.make_interval(*[0, 0, 0, 0, days]))
        )
        row = result.one()
        total_runs = row.total_runs or 0
        success_count = row.success_count or 0
        rate = round(success_count / total_runs * 100, 1) if total_runs else 0
        return {
            "total_tokens": row.total_tokens or 0,
            "total_cost": float(row.total_cost or 0),
            "total_runs": total_runs,
            "avg_latency_ms": round(row.avg_latency_ms or 0, 2),
            "success_rate": rate,
        }


from typing import Any  # noqa: E402
