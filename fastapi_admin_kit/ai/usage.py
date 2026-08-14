"""Usage tracking — UsageInfo, AIUsageWriter, AIUsageLog model.

The AI models (``AIUsageLog``, ``AIConversation``, ``AIMessage``) are
defined as schemas in ``schemas/builtin.py`` and materialized in
``migrations.models`` so they share the same schema-first pipeline as the
rest of the admin models (User, AuditLog, etc.). They are re-exported here
for backward compatibility.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi_admin_kit.migrations.models import AIAttachment, AIConversation, AIMessage, AIUsageLog

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from fastapi_admin_kit.auth.protocol import AdminUserProtocol

__all__ = ["AIUsageLog", "AIConversation", "AIMessage", "AIAttachment", "AIUsageWriter"]


def _is_session_backend(obj: object) -> bool:
    """True if *obj* satisfies the :class:`SessionBackend` protocol."""
    from fastapi_admin_kit.backends.protocols import SessionBackend

    return isinstance(obj, SessionBackend)


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
        user: AdminUserProtocol,
        success: bool,
        session: AsyncSession,
        error: str | None = None,
        latency_ms: int | None = None,
        tool_calls: list[dict[str, object]] | None = None,
    ) -> None:
        # Route the insert through a SessionBackend adapter so a custom ORM
        # backend (not just raw SQLAlchemy) can be used.  Fall back to wrapping
        # the raw session when no adapter is passed.
        from fastapi_admin_kit.backends.sqlalchemy import SqlAlchemySessionAdapter

        sb = session if _is_session_backend(session) else SqlAlchemySessionAdapter(session)
        sb.add(
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
        from fastapi_admin_kit.db import flush_with_rollback

        await flush_with_rollback(session)

    async def aggregate(
        self,
        agent_name: str,
        period: str,
        session: AsyncSession,
    ) -> dict[str, object]:
        from datetime import UTC, datetime, timedelta

        from sqlalchemy import case as sqlcase
        from sqlalchemy import func as sqlfunc
        from sqlalchemy import select

        days_map = {"day": 1, "week": 7, "month": 30}
        days = days_map.get(period, 1)
        cutoff = datetime.now(UTC) - timedelta(days=days)

        from fastapi_admin_kit.backends.sqlalchemy import SqlAlchemySessionAdapter

        sb = session if _is_session_backend(session) else SqlAlchemySessionAdapter(session)

        # Aggregation with func.sum/case is backend-specific and has no
        # QueryBackend equivalent, so the SELECT is built with SQLAlchemy
        # directly; only execution is routed through the session adapter.
        row = (
            await sb.rows(
                select(
                    sqlfunc.sum(AIUsageLog.total_tokens).label("total_tokens"),
                    sqlfunc.sum(AIUsageLog.cost).label("total_cost"),
                    sqlfunc.count(AIUsageLog.id).label("total_runs"),
                    sqlfunc.avg(AIUsageLog.latency_ms).label("avg_latency_ms"),
                    sqlfunc.sum(
                        sqlcase(
                            (AIUsageLog.success == True, 1),  # noqa: E712
                            else_=0,
                        )
                    ).label("success_count"),
                )
                .where(AIUsageLog.agent_name == agent_name)
                .where(AIUsageLog.timestamp >= cutoff)
            )
        )[0]
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
