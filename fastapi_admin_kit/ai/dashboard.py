"""AI Dashboard routes.

Thin layer: each route parses the request, delegates orchestration to
:class:`~fastapi_admin_kit.ai.service.AIChatService`, and returns the
response.  Persistence, serialization, and streaming framing all live in the
service / its seams, so this module stays small.
"""

from __future__ import annotations

import io
from typing import TYPE_CHECKING

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse

if TYPE_CHECKING:
    import jinja2

    from fastapi_admin_kit.admin.core import Admin
    from fastapi_admin_kit.ai.agent import AIAgent

from fastapi_admin_kit.ai.service import AIChatService, _resolve_user

router = APIRouter(prefix="/ai", tags=["ai"])


def _get_jinja(request: Request) -> jinja2.Environment:
    return request.app.state.admin_jinja_env


def _get_admin(request: Request) -> Admin | None:
    return getattr(request.app.state, "admin", None)


def _get_ai_agents(request: Request) -> dict[str, AIAgent]:
    return getattr(request.app.state, "ai_agents", {})


@router.get("/chat")
async def ai_chat_page(request: Request) -> jinja2.TemplateResponse:
    """Full-page AI chat interface."""
    await _resolve_user(request)
    admin = _get_admin(request)
    jinja = _get_jinja(request)

    context: dict[str, object] = {
        "title": "AI Chat",
        "admin_path": admin.admin_path if admin else "/admin",
    }
    context.update(await admin.sidebar_template_kwargs(request) if admin else {})
    return jinja.TemplateResponse(request, "pages/ai/chat.html", context)


@router.post("/chat/upload", response_model=None)
async def ai_chat_upload(
    request: Request,
    files: list[UploadFile] = File(...),
) -> JSONResponse:
    """Upload files for AI chat attachments."""
    from fastapi_admin_kit.ai.attachments import (
        ALLOWED_EXTENSIONS,
        detect_mime,
        validate_extension,
        validate_mime,
    )
    from fastapi_admin_kit.ai.usage import AIAttachment
    from fastapi_admin_kit.backends.sqlalchemy import SqlAlchemySessionAdapter
    from fastapi_admin_kit.db import flush_with_rollback, get_db_session

    admin = _get_admin(request)
    if admin is None:
        raise HTTPException(status_code=500, detail="Admin not configured.")

    max_size_bytes = int(admin.config.ai_chat.max_file_size_mb * 1024 * 1024)
    allowed_exts = set(admin.config.ai_chat.allowed_extensions) or ALLOWED_EXTENSIONS

    storage = getattr(request.app.state, "admin_storage", None)
    if storage is None:
        raise HTTPException(status_code=500, detail="Storage not configured.")

    session = get_db_session(request)
    # Route persistence through the Admin class's backend session adapter.
    session_backend_class = getattr(request.app.state, "admin_session_backend_class", None)
    sb = (
        session_backend_class(session)
        if session_backend_class is not None
        else SqlAlchemySessionAdapter(session)
    )
    results: list[dict[str, object]] = []

    for file in files:
        if file.filename is None:
            continue

        ext = validate_extension(file.filename)
        if ext not in allowed_exts:
            raise HTTPException(
                status_code=400,
                detail=f"File extension '{ext}' is not allowed.",
            )

        content = await file.read()
        if len(content) > max_size_bytes:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"File '{file.filename}' exceeds maximum size of "
                    f"{admin.config.ai_chat.max_file_size_mb}MB."
                ),
            )

        mime_type = detect_mime(file.filename, content)
        try:
            validate_mime(ext, mime_type)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        upload_file = UploadFile(filename=file.filename, file=io.BytesIO(content))
        try:
            saved_path = await storage.save(upload_file, directory="ai_attachments")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to save file: {e}")

        file_url = storage.url(saved_path)

        attachment = AIAttachment(
            conversation_id=None,
            message_id=None,
            filename=file.filename,
            file_path=saved_path,
            file_size=len(content),
            mime_type=mime_type,
        )
        sb.add(attachment)
        await flush_with_rollback(session)

        results.append(
            {
                "id": attachment.id,
                "filename": file.filename,
                "url": file_url,
                "mime_type": mime_type,
                "size": len(content),
            }
        )

    return JSONResponse(results)


@router.get("/logs")
async def ai_logs_page(request: Request) -> jinja2.TemplateResponse:
    """Full-page AI logs viewer."""
    await _resolve_user(request)
    admin = _get_admin(request)
    jinja = _get_jinja(request)

    context: dict[str, object] = {
        "title": "AI Logs",
        "admin_path": admin.admin_path if admin else "/admin",
    }
    context.update(await admin.sidebar_template_kwargs(request) if admin else {})
    return jinja.TemplateResponse(request, "pages/ai/logs.html", context)


@router.get("/dashboard")
async def ai_dashboard(request: Request) -> jinja2.TemplateResponse:
    """AI operations dashboard showing costs, logs, and tool calls."""
    await _resolve_user(request)
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
    context.update(await admin.sidebar_template_kwargs(request) if admin else {})
    return jinja.TemplateResponse(request, "pages/ai/dashboard.html", context)


@router.get("/tools")
async def ai_tools_page(request: Request) -> jinja2.TemplateResponse:
    """Full-page AI tools viewer."""
    await _resolve_user(request)
    admin = _get_admin(request)
    jinja = _get_jinja(request)

    context: dict[str, object] = {
        "title": "AI Tools",
        "admin_path": admin.admin_path if admin else "/admin",
    }
    context.update(await admin.sidebar_template_kwargs(request) if admin else {})
    return jinja.TemplateResponse(request, "pages/ai/tools.html", context)


@router.get("/agents")
async def ai_agents_page(request: Request) -> jinja2.TemplateResponse:
    """Full-page AI agents viewer."""
    await _resolve_user(request)
    admin = _get_admin(request)
    jinja = _get_jinja(request)

    context: dict[str, object] = {
        "title": "AI Agents",
        "admin_path": admin.admin_path if admin else "/admin",
    }
    context.update(await admin.sidebar_template_kwargs(request) if admin else {})
    return jinja.TemplateResponse(request, "pages/ai/agents.html", context)


# ---------------------------------------------------------------------------
# Data endpoints — delegate to AIChatService
# ---------------------------------------------------------------------------


@router.post("/chat")
async def ai_chat(request: Request) -> JSONResponse:
    return await AIChatService(request).chat()


@router.post("/chat/stream")
async def ai_chat_stream(request: Request):
    return await AIChatService(request).stream()


@router.get("/logs/api")
async def get_ai_logs(
    request: Request,
    limit: int = 100,
    offset: int = 0,
    agent: str | None = None,
    tool: str | None = None,
) -> JSONResponse:
    return await AIChatService(request).get_logs(limit, offset, agent, tool)


@router.get("/tool-calls/api")
async def get_tool_calls(
    request: Request,
    limit: int = 100,
    offset: int = 0,
    tool: str | None = None,
    success: bool | None = None,
) -> JSONResponse:
    return await AIChatService(request).get_tool_calls(limit, offset, tool, success)


@router.get("/costs")
async def get_ai_costs(
    request: Request,
    period: str = "day",
    agent: str | None = None,
) -> JSONResponse:
    return await AIChatService(request).get_costs(period, agent)


@router.get("/tools/api")
async def get_ai_tools(request: Request) -> JSONResponse:
    return await AIChatService(request).list_tools()


@router.post("/tools/{tool_name}/execute")
async def execute_tool_endpoint(tool_name: str, request: Request) -> JSONResponse:
    return await AIChatService(request).execute_tool(tool_name)


@router.get("/agents/api")
async def get_ai_agents(request: Request) -> JSONResponse:
    return await AIChatService(request).list_agents()


@router.get("/conversations")
async def list_conversations(request: Request) -> JSONResponse:
    return await AIChatService(request).list_conversations()


@router.get("/conversations/{conversation_id}")
async def load_conversation(conversation_id: str, request: Request) -> JSONResponse:
    return await AIChatService(request).load_conversation(conversation_id)


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str, request: Request) -> JSONResponse:
    return await AIChatService(request).delete_conversation(conversation_id)
