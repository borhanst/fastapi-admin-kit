"""AI Plugin — routes, nav items, and startup wiring."""

from __future__ import annotations

from typing import Any


class AIPlugin:
    """Plugin that adds AI agent capabilities to the admin panel."""

    name = "ai"

    def __init__(self, agents: list[Any] | None = None) -> None:
        self.agents = agents or []

    def get_routes(self) -> Any:
        from fastapi_admin_kit.ai.dashboard import router

        return router

    def get_nav_items(self) -> list[dict]:
        return [{"label": "AI", "url": "/admin/ai/dashboard", "icon": "sparkles"}]

    def get_dashboard_widgets(self) -> list[Any]:
        return []

    def on_startup(self, admin: Any) -> None:
        """Initialize AI agents and store on admin state."""
        from fastapi_admin_kit.ai.backends.pydantic_ai_backend import (
            PydanticAIAgent,
        )
        from fastapi_admin_kit.ai.deps import get_admin_deps
        from fastapi_admin_kit.ai.usage import AIUsageWriter

        writer = AIUsageWriter()
        ai_agents: dict[str, Any] = {}

        for cfg in self.agents:
            agent = PydanticAIAgent(
                config=cfg,
                deps_factory=get_admin_deps,
                usage_writer=writer,
            )
            ai_agents[cfg.name] = agent

        admin._app.state.ai_agents = ai_agents  # type: ignore[attr-defined]
        admin._app.state.ai_config = self  # type: ignore[attr-defined]
