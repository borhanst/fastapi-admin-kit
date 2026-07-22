"""AI Dashboard routes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

if TYPE_CHECKING:
    import jinja2

    from fastapi_admin_kit.admin.core import Admin
    from fastapi_admin_kit.ai.agent import AIAgent
    from fastapi_admin_kit.auth.permissions import PermissionChecker
    from fastapi_admin_kit.auth.protocol import AdminUserProtocol

router = APIRouter(prefix="/ai", tags=["ai"])


def _deserialize_messages(raw: list[dict]) -> list:
    """Convert stored message dicts back to ModelMessage objects."""
    import dataclasses as _dc

    from pydantic_ai.messages import (
        ModelRequest,
        ModelResponse,
        TextPart,
        ToolCallPart,
        ToolReturnPart,
        UserPromptPart,
    )

    part_map = {
        "user-prompt": UserPromptPart,
        "text": TextPart,
        "tool-call": ToolCallPart,
        "tool-return": ToolReturnPart,
    }

    def _build_part(d: dict):
        if not isinstance(d, dict):
            return d
        cls = part_map.get(d.get("part_kind", ""))
        if cls and _dc.is_dataclass(cls):
            fields = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
            return cls(**fields)
        return d

    messages = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        kind = item.get("kind", "request")
        data = dict(item)
        if "parts" in data and isinstance(data["parts"], list):
            data["parts"] = [_build_part(p) for p in data["parts"]]
        if kind == "request":
            fields = {k: v for k, v in data.items() if k in ModelRequest.__dataclass_fields__}
            messages.append(ModelRequest(**fields))
        elif kind == "response":
            fields = {k: v for k, v in data.items() if k in ModelResponse.__dataclass_fields__}
            messages.append(ModelResponse(**fields))
    return messages


def _get_jinja(request: Request) -> jinja2.Environment:
    return request.app.state.admin_jinja_env


def _get_admin(request: Request) -> Admin | None:
    return getattr(request.app.state, "admin", None)


def _get_ai_agents(request: Request) -> dict[str, AIAgent]:
    return getattr(request.app.state, "ai_agents", {})


async def _resolve_user(request: Request) -> AdminUserProtocol:
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


async def _resolve_checker(request: Request, user: AdminUserProtocol) -> PermissionChecker:
    """Manually build a permission checker."""
    from fastapi_admin_kit.auth.permissions import PermissionChecker
    from fastapi_admin_kit.db import get_db_session

    session = get_db_session(request)
    snapshot = getattr(request.state, "admin_user_snapshot", None)
    return PermissionChecker(session=session, user=user, user_snapshot=snapshot)


@router.get("/chat")
async def ai_chat_page(request: Request) -> jinja2.TemplateResponse:
    """Full-page AI chat interface."""
    admin = _get_admin(request)
    jinja = _get_jinja(request)

    context: dict[str, object] = {
        "title": "AI Chat",
        "admin_path": admin.admin_path if admin else "/admin",
    }
    context.update(admin.sidebar_template_kwargs(request) if admin else {})
    return jinja.TemplateResponse(request, "pages/ai/chat.html", context)


@router.get("/logs")
async def ai_logs_page(request: Request) -> jinja2.TemplateResponse:
    """Full-page AI logs viewer."""
    admin = _get_admin(request)
    jinja = _get_jinja(request)

    context: dict[str, object] = {
        "title": "AI Logs",
        "admin_path": admin.admin_path if admin else "/admin",
    }
    context.update(admin.sidebar_template_kwargs(request) if admin else {})
    return jinja.TemplateResponse(request, "pages/ai/logs.html", context)


@router.get("/dashboard")
async def ai_dashboard(request: Request) -> jinja2.TemplateResponse:
    """AI operations dashboard showing costs, logs, and tool calls."""
    from fastapi_admin_kit.db import get_db_session

    agents = _get_ai_agents(request)
    admin = _get_admin(request)
    jinja = _get_jinja(request)
    session = get_db_session(request)

    stats: list[dict[str, object]] = []
    for name, agent in agents.items():
        try:
            s = await agent.get_usage_stats(period="day", session=session)
        except Exception:
            s = {
                "total_tokens": 0,
                "total_cost": 0,
                "total_runs": 0,
                "success_rate": 0,
            }
        stats.append({"name": name, **s})

    context: dict[str, object] = {
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


@router.get("/tool-calls/api")
async def get_tool_calls(
    request: Request,
    limit: int = 100,
    offset: int = 0,
    tool: str | None = None,
    success: bool | None = None,
) -> JSONResponse:
    """Get tool call history across all conversations."""
    from sqlalchemy import select

    from fastapi_admin_kit.ai.usage import AIMessage
    from fastapi_admin_kit.db import get_db_session

    session = get_db_session(request)
    stmt = select(AIMessage).where(AIMessage.role == "tool").order_by(AIMessage.created_at.desc())

    if tool:
        stmt = stmt.where(AIMessage.tool_name == tool)
    if success is not None:
        is_error = not bool(success)
        stmt = stmt.where(AIMessage.is_error == is_error)

    stmt = stmt.offset(offset).limit(limit)
    result = await session.execute(stmt)
    msgs = result.scalars().all()

    return JSONResponse(
        [
            {
                "id": m.id,
                "conversation_id": m.conversation_id,
                "tool_name": m.tool_name,
                "tool_args": m.tool_args,
                "tool_result": m.tool_result,
                "is_error": m.is_error,
                "error": m.error,
                "latency_ms": m.latency_ms,
                "created_at": str(m.created_at) if m.created_at else None,
            }
            for m in msgs
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
async def ai_tools_page(request: Request) -> jinja2.TemplateResponse:
    """Full-page AI tools viewer."""
    admin = _get_admin(request)
    jinja = _get_jinja(request)

    context: dict[str, object] = {
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
    params: dict[str, object] | None = None,
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

    import time

    start = time.perf_counter()
    try:
        result = await agent.execute_tool(tool_name, params or {}, deps)
        latency_ms = int((time.perf_counter() - start) * 1000)

        from fastapi_admin_kit.ai.usage import AIUsageWriter

        writer = AIUsageWriter()
        await writer.write(
            agent_name=agent_name,
            model=getattr(agent._config, "model", "unknown"),
            request_tokens=0,
            response_tokens=0,
            total_tokens=0,
            cost=0,
            user=user,
            success=True,
            latency_ms=latency_ms,
            tool_calls=[{"name": tool_name, "args": params or {}, "ok": True}],
            session=session,
        )

        return JSONResponse({"success": True, "result": result})
    except Exception as e:
        latency_ms = int((time.perf_counter() - start) * 1000)

        from fastapi_admin_kit.ai.usage import AIUsageWriter

        writer = AIUsageWriter()
        await writer.write(
            agent_name=agent_name,
            model=getattr(agent._config, "model", "unknown"),
            request_tokens=0,
            response_tokens=0,
            total_tokens=0,
            cost=0,
            user=user,
            success=False,
            error=str(e),
            latency_ms=latency_ms,
            tool_calls=[{"name": tool_name, "args": params or {}, "ok": False}],
            session=session,
        )

        return JSONResponse({"success": False, "error": str(e)}, status_code=400)


@router.get("/agents")
async def ai_agents_page(request: Request) -> jinja2.TemplateResponse:
    """Full-page AI agents viewer."""
    admin = _get_admin(request)
    jinja = _get_jinja(request)

    context: dict[str, object] = {
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
    from uuid import uuid4

    from sqlalchemy import select

    from fastapi_admin_kit.ai.deps import AdminDeps
    from fastapi_admin_kit.ai.usage import AIConversation, AIMessage
    from fastapi_admin_kit.db import get_db_session

    body = await request.json()
    message = body.get("message", "")
    agent_name = body.get("agent", "default")
    conversation_id = body.get("conversation_id")
    page_url = body.get("page_url")

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
        page_url=page_url,
    )

    try:
        message_history = None

        if conversation_id:
            result = await session.execute(
                select(AIConversation).where(AIConversation.id == conversation_id)
            )
            conv = result.scalar_one_or_none()
            if conv and conv.message_history:
                message_history = _deserialize_messages(conv.message_history)

        result = await agent.chat(
            message,
            deps,
            message_history=message_history,
            conversation_id=conversation_id,
        )

        output_text = str(result.output)
        import dataclasses as _dc
        from datetime import datetime

        def _safe_dict(obj):
            d = _dc.asdict(obj) if _dc.is_dataclass(obj) and not isinstance(obj, type) else str(obj)
            return _sanitize(d)

        def _sanitize(v):
            if isinstance(v, datetime):
                return v.isoformat()
            if isinstance(v, dict):
                return {k: _sanitize(val) for k, val in v.items()}
            if isinstance(v, list):
                return [_sanitize(item) for item in v]
            return v

        new_messages = [_safe_dict(m) for m in result.new_messages]

        if conversation_id:
            conv_result = await session.execute(
                select(AIConversation).where(AIConversation.id == conversation_id)
            )
            conv = conv_result.scalar_one_or_none()
            if conv:
                existing = conv.message_history or []
                conv.message_history = existing + new_messages
                conv.turn_count = (conv.turn_count or 0) + 1
                conv.total_tokens = (conv.total_tokens or 0) + result.usage.total_tokens
                conv.total_cost = float(conv.total_cost or 0) + result.usage.cost
                from datetime import UTC, datetime

                conv.last_message_at = datetime.now(UTC)
            else:
                conversation_id = str(uuid4())
                conv = AIConversation(
                    id=conversation_id,
                    agent_name=agent_name,
                    user_id=getattr(user, "id", None),
                    user_email=getattr(user, "email", None),
                    title=message[:80],
                    message_history=new_messages,
                    turn_count=1,
                    total_tokens=result.usage.total_tokens,
                    total_cost=result.usage.cost,
                )
                session.add(conv)
        else:
            conversation_id = str(uuid4())
            conv = AIConversation(
                id=conversation_id,
                agent_name=agent_name,
                user_id=getattr(user, "id", None),
                user_email=getattr(user, "email", None),
                title=message[:80],
                message_history=new_messages,
                turn_count=1,
                total_tokens=result.usage.total_tokens,
                total_cost=result.usage.cost,
            )
            session.add(conv)

        session.add(
            AIMessage(
                conversation_id=conversation_id,
                role="user",
                content=message,
            )
        )
        session.add(
            AIMessage(
                conversation_id=conversation_id,
                role="assistant",
                content=output_text,
                tokens=result.usage.total_tokens,
                latency_ms=None,
            )
        )
        try:
            for tc in getattr(result, "tool_calls", []):
                session.add(
                    AIMessage(
                        conversation_id=conversation_id,
                        role="tool",
                        tool_name=getattr(tc, "name", None),
                        tool_args=getattr(tc, "args", None),
                        tool_result=getattr(tc, "result", None),
                        content=str(getattr(tc, "result", "")),
                        is_error=getattr(tc, "is_error", False),
                    )
                )
        except Exception:
            pass
        await session.flush()

        tool_calls_data = []
        for tc in getattr(result, "tool_calls", []):
            tool_calls_data.append(
                {
                    "name": getattr(tc, "name", ""),
                    "args": getattr(tc, "args", {}),
                    "result": getattr(tc, "result", None),
                    "is_error": getattr(tc, "is_error", False),
                }
            )

        return JSONResponse(
            {
                "output": output_text,
                "usage": {
                    "request_tokens": result.usage.request_tokens,
                    "response_tokens": result.usage.response_tokens,
                    "total_tokens": result.usage.total_tokens,
                    "cost": result.usage.cost,
                },
                "conversation_id": conversation_id,
                "tool_calls": tool_calls_data,
            }
        )
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@router.get("/conversations")
async def list_conversations(request: Request) -> JSONResponse:
    """List current user's conversations."""
    from sqlalchemy import select

    from fastapi_admin_kit.ai.usage import AIConversation
    from fastapi_admin_kit.db import get_db_session

    user = await _resolve_user(request)
    session = get_db_session(request)

    result = await session.execute(
        select(AIConversation)
        .where(AIConversation.user_id == getattr(user, "id", None))
        .order_by(AIConversation.last_message_at.desc().nullslast())
        .limit(50)
    )
    convs = result.scalars().all()

    return JSONResponse(
        [
            {
                "id": c.id,
                "title": c.title or "Untitled",
                "agent_name": c.agent_name,
                "turn_count": c.turn_count or 0,
                "started_at": str(c.started_at) if c.started_at else None,
                "last_message_at": str(c.last_message_at) if c.last_message_at else None,
            }
            for c in convs
        ]
    )


@router.get("/conversations/{conversation_id}")
async def load_conversation(conversation_id: str, request: Request) -> JSONResponse:
    """Load messages for a conversation."""
    from sqlalchemy import select

    from fastapi_admin_kit.ai.usage import AIConversation, AIMessage
    from fastapi_admin_kit.db import get_db_session

    user = await _resolve_user(request)
    session = get_db_session(request)

    conv_result = await session.execute(
        select(AIConversation).where(
            AIConversation.id == conversation_id,
            AIConversation.user_id == getattr(user, "id", None),
        )
    )
    conv = conv_result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found.")

    result = await session.execute(
        select(AIMessage)
        .where(AIMessage.conversation_id == conversation_id)
        .order_by(AIMessage.created_at)
    )
    msgs = result.scalars().all()

    return JSONResponse(
        [
            {
                "role": m.role,
                "content": m.content,
                "created_at": str(m.created_at) if m.created_at else None,
                "tool_name": m.tool_name,
                "tool_args": m.tool_args,
                "tool_result": m.tool_result,
                "is_error": m.is_error,
            }
            for m in msgs
        ]
    )


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str, request: Request) -> JSONResponse:
    """Delete a conversation and its messages."""
    from sqlalchemy import select

    from fastapi_admin_kit.ai.usage import AIConversation, AIMessage
    from fastapi_admin_kit.db import get_db_session

    user = await _resolve_user(request)
    session = get_db_session(request)

    result = await session.execute(
        select(AIConversation).where(
            AIConversation.id == conversation_id,
            AIConversation.user_id == getattr(user, "id", None),
        )
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found.")

    await session.execute(select(AIMessage).where(AIMessage.conversation_id == conversation_id))
    from sqlalchemy import delete as sqldel

    await session.execute(sqldel(AIMessage).where(AIMessage.conversation_id == conversation_id))
    await session.delete(conv)

    return JSONResponse({"success": True})
