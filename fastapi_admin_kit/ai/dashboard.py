"""AI Dashboard routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/ai", tags=["ai"])


def _get_jinja(request: Request) -> Any:
    return request.app.state.admin_jinja_env


def _get_admin(request: Request) -> Any:
    return getattr(request.app.state, "admin", None)


def _get_ai_agents(request: Request) -> dict[str, Any]:
    return getattr(request.app.state, "ai_agents", {})


async def _resolve_user(request: Request) -> Any:
    """Manually resolve the admin user from the session cookie."""
    from fastapi_admin_kit.auth.dependencies import get_session
    from fastapi_admin_kit.auth.identity import resolve_user

    session_payload = get_session(request)
    if session_payload is None:
        raise HTTPException(status_code=401, detail="Not authenticated.")

    user_id = session_payload.get("user_id")
    if user_id is None:
        raise HTTPException(status_code=401, detail="Invalid session.")

    user = await resolve_user(request, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="User not found.")
    return user


async def _resolve_checker(request: Request, user: Any) -> Any:
    """Manually build a permission checker."""
    from fastapi_admin_kit.auth.permissions import PermissionChecker
    from fastapi_admin_kit.db import get_db_session

    session = get_db_session(request)
    snapshot = getattr(request.state, "admin_user_snapshot", None)
    return PermissionChecker(session=session, user=user, user_snapshot=snapshot)


@router.get("/chat")
async def ai_chat_page(request: Request):
    """Full-page AI chat interface."""
    admin = _get_admin(request)
    jinja = _get_jinja(request)

    context = {
        "title": "AI Chat",
        "admin_path": admin.admin_path if admin else "/admin",
    }
    context.update(admin.sidebar_template_kwargs(request) if admin else {})
    return jinja.TemplateResponse(request, "pages/ai/chat.html", context)


@router.get("/logs")
async def ai_logs_page(request: Request):
    """Full-page AI logs viewer."""
    admin = _get_admin(request)
    jinja = _get_jinja(request)

    context = {
        "title": "AI Logs",
        "admin_path": admin.admin_path if admin else "/admin",
    }
    context.update(admin.sidebar_template_kwargs(request) if admin else {})
    return jinja.TemplateResponse(request, "pages/ai/logs.html", context)


@router.get("/dashboard")
async def ai_dashboard(request: Request):
    """AI operations dashboard showing costs, logs, and tool calls."""
    agents = _get_ai_agents(request)
    admin = _get_admin(request)
    jinja = _get_jinja(request)

    stats: list[dict[str, Any]] = []
    for name, agent in agents.items():
        try:
            s = await agent.get_usage_stats(period="day")
        except Exception:
            s = {
                "total_tokens": 0,
                "total_cost": 0,
                "total_runs": 0,
                "success_rate": 0,
            }
        stats.append({"name": name, **s})

    context = {
        "title": "AI Dashboard",
        "agent_stats": stats,
        "admin_path": admin.admin_path if admin else "/admin",
    }
    context.update(admin.sidebar_template_kwargs(request) if admin else {})
    return jinja.TemplateResponse(request, "pages/ai/dashboard.html", context)


@router.get("/logs/api")
async def get_ai_logs(
    request: Request,
    limit: int = 100,
    offset: int = 0,
    agent: str | None = None,
    tool: str | None = None,
) -> JSONResponse:
    """Get AI operation logs."""
    from sqlalchemy import select

    from fastapi_admin_kit.ai.usage import AIUsageLog
    from fastapi_admin_kit.db import get_db_session

    session = get_db_session(request)
    stmt = select(AIUsageLog).order_by(AIUsageLog.timestamp.desc())

    if agent:
        stmt = stmt.where(AIUsageLog.agent_name == agent)
    stmt = stmt.offset(offset).limit(limit)

    result = await session.execute(stmt)
    rows = result.scalars().all()

    return JSONResponse(
        [
            {
                "id": r.id,
                "agent_name": r.agent_name,
                "model": r.model,
                "user_email": r.user_email,
                "request_tokens": r.request_tokens,
                "response_tokens": r.response_tokens,
                "total_tokens": r.total_tokens,
                "cost": float(r.cost or 0),
                "tool_calls": r.tool_calls or [],
                "success": r.success,
                "error": r.error,
                "latency_ms": r.latency_ms,
                "timestamp": str(r.timestamp) if r.timestamp else None,
            }
            for r in rows
        ]
    )


@router.get("/costs")
async def get_ai_costs(
    request: Request,
    period: str = "day",
    agent: str | None = None,
) -> JSONResponse:
    """Get AI cost breakdown."""
    from fastapi_admin_kit.ai.usage import AIUsageWriter
    from fastapi_admin_kit.db import get_db_session

    session = get_db_session(request)
    writer = AIUsageWriter()
    agent_name = agent or "default"

    stats = await writer.aggregate(agent_name=agent_name, period=period, session=session)
    return JSONResponse(stats)


@router.get("/tools")
async def ai_tools_page(request: Request):
    """Full-page AI tools viewer."""
    admin = _get_admin(request)
    jinja = _get_jinja(request)

    context = {
        "title": "AI Tools",
        "admin_path": admin.admin_path if admin else "/admin",
    }
    context.update(admin.sidebar_template_kwargs(request) if admin else {})
    return jinja.TemplateResponse(request, "pages/ai/tools.html", context)


@router.get("/tools/api")
async def get_ai_tools(request: Request) -> JSONResponse:
    """Get list of available AI tools."""
    from fastapi_admin_kit.ai.tools import tool_registry

    tools = tool_registry.all()
    return JSONResponse(
        [
            {
                "name": t.name,
                "description": t.description,
                "category": t.category,
                "uses_context": t.uses_context,
            }
            for t in tools
        ]
    )


@router.post("/tools/{tool_name}/execute")
async def execute_tool_endpoint(
    tool_name: str,
    request: Request,
    params: dict | None = None,
) -> JSONResponse:
    """Execute an AI tool directly (bypasses the LLM)."""
    agents = _get_ai_agents(request)
    if not agents:
        raise HTTPException(status_code=400, detail="No AI agents configured.")

    agent_name = request.query_params.get("agent", "default")
    agent = agents.get(agent_name)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not found.")

    user = await _resolve_user(request)
    checker = await _resolve_checker(request, user)

    from fastapi_admin_kit.ai.deps import AdminDeps
    from fastapi_admin_kit.db import get_db_session

    session = get_db_session(request)

    deps = AdminDeps(
        session=session,
        admin_user=user,
        request=request,
        registry=request.app.state.admin_registry,
        permission_checker=checker,
    )

    try:
        result = await agent.execute_tool(tool_name, params or {}, deps)
        return JSONResponse({"success": True, "result": result})
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=400)


@router.get("/agents")
async def ai_agents_page(request: Request):
    """Full-page AI agents viewer."""
    admin = _get_admin(request)
    jinja = _get_jinja(request)

    context = {
        "title": "AI Agents",
        "admin_path": admin.admin_path if admin else "/admin",
    }
    context.update(admin.sidebar_template_kwargs(request) if admin else {})
    return jinja.TemplateResponse(request, "pages/ai/agents.html", context)


@router.get("/agents/api")
async def get_ai_agents(request: Request) -> JSONResponse:
    """Get list of configured AI agents."""
    agents = _get_ai_agents(request)
    return JSONResponse(
        [
            {
                "name": name,
                "model": getattr(agent._config, "model", "unknown"),
                "tools": len(getattr(agent._config, "tools", [])),
            }
            for name, agent in agents.items()
        ]
    )


@router.post("/chat")
async def ai_chat(request: Request) -> JSONResponse:
    """Send a message to an AI agent."""
    from fastapi_admin_kit.ai.deps import AdminDeps
    from fastapi_admin_kit.db import get_db_session

    body = await request.json()
    message = body.get("message", "")
    agent_name = body.get("agent", "default")
    conversation_id = body.get("conversation_id")

    agents = _get_ai_agents(request)
    agent = agents.get(agent_name)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not found.")

    user = await _resolve_user(request)
    session = get_db_session(request)
    checker = await _resolve_checker(request, user)

    deps = AdminDeps(
        session=session,
        admin_user=user,
        request=request,
        registry=request.app.state.admin_registry,
        permission_checker=checker,
    )

    try:
        result = await agent.chat(message, deps, conversation_id=conversation_id)
        return JSONResponse(
            {
                "output": str(result.output),
                "usage": {
                    "request_tokens": result.usage.request_tokens,
                    "response_tokens": result.usage.response_tokens,
                    "total_tokens": result.usage.total_tokens,
                    "cost": result.usage.cost,
                },
                "conversation_id": result.conversation_id,
            }
        )
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)
