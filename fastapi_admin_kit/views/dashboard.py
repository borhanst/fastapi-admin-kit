"""Dashboard view handler factory."""

from __future__ import annotations

import importlib
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select

from fastapi_admin_kit.auth.dependencies import get_current_admin_user
from fastapi_admin_kit.db import get_db_session


def _resolve_callback(dotted_path: str) -> Any | None:
    """Resolve a dotted path like 'myapp.dashboards.custom_stats' to the function."""
    if not dotted_path:
        return None
    try:
        module_path, _, func_name = dotted_path.rpartition(".")
        module = importlib.import_module(module_path)
        return getattr(module, func_name, None)
    except (ImportError, AttributeError):
        return None


def dashboard_view_factory(admin: Any):
    """Return a dashboard view function bound to the given admin instance."""
    async def dashboard_view(
        request: Request,
        current_user: Any = Depends(get_current_admin_user),
    ):
        templates = request.app.state.admin_jinja_env
        admin_instance = request.app.state.admin
        config = request.app.state.admin_config
        session = get_db_session(request)

        # Get registered models
        registered_models = admin_instance.registry.all()

        # Determine which models to show stats for
        dashboard_stats = config.get("dashboard_stats", [])
        if dashboard_stats:
            models_for_stats = [
                m for m in registered_models if m.table_name in dashboard_stats
            ]
        else:
            models_for_stats = registered_models

        # Get record counts for each model
        now = datetime.now(timezone.utc)  # noqa: UP017
        thirty_days_ago = now - timedelta(days=30)

        stat_cards = []
        for model in models_for_stats:
            count_query = select(func.count()).select_from(model.model)
            count = (await session.execute(count_query)).scalar()

            # Trend: count in last 30 days vs previous 30 days
            model_cls = model.model
            trend_current = 0
            trend_previous = 0
            has_timestamp = False
            # Look for a created_at or timestamp column
            for col_name in ("created_at", "timestamp", "date", "created"):
                if hasattr(model_cls, col_name):
                    has_timestamp = True
                    col = getattr(model_cls, col_name)
                    recent_q = select(func.count()).select_from(model_cls).where(
                        col >= thirty_days_ago
                    )
                    trend_current = (await session.execute(recent_q)).scalar() or 0
                    older_q = select(func.count()).select_from(model_cls).where(
                        col < thirty_days_ago
                    )
                    trend_previous = (await session.execute(older_q)).scalar() or 0
                    break

            # Calculate trend percentage
            trend_pct = 0
            trend_direction = "up"
            if has_timestamp and trend_previous > 0:
                trend_pct = int(((trend_current - trend_previous) / trend_previous) * 100)
                trend_direction = "up" if trend_pct >= 0 else "down"
            elif has_timestamp and trend_current > 0:
                trend_pct = 100
                trend_direction = "up"

            stat_cards.append({
                "title": model.verbose_name_plural,
                "icon": getattr(model.admin, "icon", None) or "cube",
                "count": count,
                "url": f"{admin_instance.admin_path}/{model.table_name}/",
                "trend_pct": trend_pct,
                "trend_direction": trend_direction,
                "has_trend": has_timestamp,
            })

        # Fetch last 10 audit entries
        from fastapi_admin_kit.audit.models import AuditLog
        audit_query = select(AuditLog).order_by(AuditLog.timestamp.desc()).limit(10)
        recent_audit = (await session.execute(audit_query)).scalars().all()

        # Check if charts are enabled
        show_charts = config.get("dashboard_charts", True)

        # Resolve dashboard callback if configured
        dashboard_callback = admin_instance.config.behavior.dashboard_callback
        callback_data = {}
        if dashboard_callback:
            cb_fn = _resolve_callback(dashboard_callback)
            if cb_fn and callable(cb_fn):
                import asyncio
                if asyncio.iscoroutinefunction(cb_fn):
                    callback_data = await cb_fn(request, session) or {}
                else:
                    callback_data = cb_fn(request, session) or {}

        # Dashboard components
        dashboard_components = admin_instance.config.behavior.dashboard_components

        # System overview data for donut chart
        overview_data = []
        overview_colors = [
            "#14b8a6", "#8b5cf6", "#3b82f6", "#f97316",
            "#22c55e", "#eab308", "#ec4899", "#ef4444",
        ]
        total_count = 0
        for i, model in enumerate(registered_models):
            count_query = select(func.count()).select_from(model.model)
            count = (await session.execute(count_query)).scalar() or 0
            total_count += count
            overview_data.append({
                "label": model.verbose_name_plural,
                "value": count,
                "color": overview_colors[i % len(overview_colors)],
            })

        template = templates.get_template("pages/dashboard.html")
        context: dict[str, Any] = {
            "request": request,
            "registered_models": registered_models,
            "stat_cards": stat_cards,
            "recent_audit": recent_audit,
            "show_charts": show_charts,
            "admin_path": admin_instance.admin_path,
            "title": admin_instance.title,
            "dashboard_callback_data": callback_data,
            "dashboard_components": dashboard_components,
            "overview_data": overview_data,
            "overview_total": total_count,
        }
        if hasattr(admin_instance, "build_sidebar_context") and current_user is not None:
            from fastapi_admin_kit.views.sidebar import inject_sidebar_context
            context = await inject_sidebar_context(request, context)
        html = template.render(**context)
        return HTMLResponse(content=html)

    dashboard_view.__name__ = "dashboard"
    return dashboard_view
