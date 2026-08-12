"""Chat orchestration service — the deep layer behind the AI routes.

This module owns the orchestration that used to be inlined in
``dashboard.py``: building deps, loading history, running the agent, and
persisting the turn.  After the architecture review the dashboard routes are
thin wrappers that parse the request and return the response; everything
cross-cutting (persistence via :class:`AIConversationStore`, serialization via
:func:`serialize`, usage via :class:`AIUsageWriter`) lives here.

The streaming route now consumes the agent through ``chat_stream`` (the real
seam) instead of escaping the interface via ``get_raw_agent``.
"""

from __future__ import annotations

import json
import logging
from pathlib import PurePosixPath
from typing import Any

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic_ai import BinaryContent, DocumentUrl, ImageUrl
from starlette.responses import StreamingResponse

from fastapi_admin_kit.ai.agent import ToolCallRecord, UsageInfo
from fastapi_admin_kit.ai.backends.pydantic_ai_backend import _FRIENDLY_TOOL_FAILURE
from fastapi_admin_kit.ai.conversation import AIConversationStore
from fastapi_admin_kit.ai.deps import AdminDeps
from fastapi_admin_kit.ai.serialization import serialize
from fastapi_admin_kit.ai.usage import AIConversation, AIUsageWriter
from fastapi_admin_kit.db import get_db_session, rollback_if_needed

logger = logging.getLogger("fastapi_admin_kit.ai")


def _backend(request: Request) -> Any:
    """Return the Admin class's composite backend from app.state, if any."""
    return getattr(request.app.state, "admin_backend", None)


def _session_adapter(session: Any) -> Any:
    """Wrap a raw session in a :class:`SessionBackend` adapter."""
    from fastapi_admin_kit.backends.sqlalchemy import SqlAlchemySessionAdapter

    return SqlAlchemySessionAdapter(session)


def _select(backend: Any, model: Any) -> Any:
    """Build a SELECT for *model* via the backend's QueryBackend, else raw SA."""
    qb = getattr(backend, "query", None) if backend is not None else None
    if qb is not None:
        return qb.select(model)
    from sqlalchemy import select

    return select(model)


# ---------------------------------------------------------------------------
# Shared transport helpers (moved here so routes and service share one copy)
# ---------------------------------------------------------------------------


def _get_ai_agents(request: Request) -> dict[str, Any]:
    return getattr(request.app.state, "ai_agents", {})


def _build_multimodal_input(parts: list[dict], model: str = "") -> str | list:
    """Build a pydantic-ai multimodal input from Vercel AI Data Stream parts.

    Text parts are concatenated into a single string. File parts are
    converted to ImageUrl, DocumentUrl, or BinaryContent depending on MIME type.
    """
    text_segments: list[str] = []
    content_parts: list[Any] = []

    for part in parts:
        part_type = part.get("type")
        if part_type == "text":
            text = part.get("text", "")
            if text:
                text_segments.append(text)
        elif part_type == "file":
            url = part.get("url", "")
            mime_type = part.get("mimeType", "")
            filename = part.get("filename", "")
            if not url:
                continue
            if mime_type and mime_type.startswith("image/"):
                content_parts.append(ImageUrl(url=url))
            elif filename:
                ext = PurePosixPath(filename).suffix.lower()
                if ext in {".pdf", ".docx", ".doc", ".xlsx", ".xls", ".csv"}:
                    if model.startswith("groq:"):
                        # Groq does not support DocumentUrl in user prompts.
                        # Fall back to a text mention so the model is aware of the attachment.
                        text_segments.append(f"[Attached file: {filename}]")
                    else:
                        content_parts.append(DocumentUrl(url=url))
                else:
                    content_parts.append(
                        BinaryContent(data=b"", media_type=mime_type or "application/octet-stream")
                    )
            else:
                content_parts.append(
                    BinaryContent(data=b"", media_type=mime_type or "application/octet-stream")
                )

    text = " ".join(text_segments).strip()
    if not content_parts:
        return text
    if not text:
        return content_parts
    return [text] + content_parts


def _deserialize_messages(raw: list[dict]) -> list:
    """Convert stored message dicts back to ModelMessage objects."""
    import dataclasses as _dc

    from pydantic_ai.messages import (
        ModelRequest,
        ModelResponse,
        TextPart,
        ThinkingPart,
        ToolCallPart,
        ToolReturnPart,
        UserPromptPart,
    )

    part_map = {
        "user-prompt": UserPromptPart,
        "text": TextPart,
        "thinking": ThinkingPart,
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
        return None

    messages = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        kind = item.get("kind", "request")
        data = dict(item)
        if "parts" in data and isinstance(data["parts"], list):
            data["parts"] = [p for p in (_build_part(p) for p in data["parts"]) if p is not None]
        if kind == "request":
            fields = {k: v for k, v in data.items() if k in ModelRequest.__dataclass_fields__}
            messages.append(ModelRequest(**fields))
        elif kind == "response":
            fields = {k: v for k, v in data.items() if k in ModelResponse.__dataclass_fields__}
            messages.append(ModelResponse(**fields))
    return messages


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


class _SafeUser:
    """Detached view of the admin user for persistence callbacks."""

    def __init__(self, user: Any) -> None:
        self.id = getattr(user, "id", None)
        self.email = getattr(user, "email", None)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class AIChatService:
    """Deep orchestration layer for the AI chat feature."""

    def __init__(self, request: Request) -> None:
        self.request = request

    # -- chat (non-streaming) -----------------------------------------------

    async def chat(self) -> JSONResponse:
        request = self.request
        body = await request.json()
        agent_name = body.get("agent", "default")
        conversation_id = body.get("conversation_id")
        page_url = body.get("page_url")
        parts = body.get("parts", [])
        message = body.get("message", "")

        agents = _get_ai_agents(request)
        agent = agents.get(agent_name)
        if agent is None:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not found.")

        if parts:
            message = _build_multimodal_input(parts, model=getattr(agent._config, "model", ""))

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
            existing_conv = None
            if conversation_id:
                backend = _backend(request)
                sb = _session_adapter(session)
                stmt = _select(backend, AIConversation).where(AIConversation.id == conversation_id)
                existing_conv = (await sb.execute(stmt)).scalar_one_or_none()
                if existing_conv and existing_conv.message_history:
                    message_history = _deserialize_messages(existing_conv.message_history)

            result = await agent.chat(
                message,
                deps,
                message_history=message_history,
                conversation_id=conversation_id,
            )

            output_text = str(result.output)
            display_content = (
                message if isinstance(message, str) else json.dumps(message, default=str)
            )

            store = AIConversationStore(session, backend=_backend(request))
            await store.save_turn(
                agent_name=agent_name,
                user=user,
                user_message=display_content,
                output=output_text,
                usage=result.usage,
                tool_calls=result.tool_calls,
                conversation_id=conversation_id if existing_conv else None,
                new_messages=result.new_messages,
            )

            tool_calls_data = [
                {
                    "name": getattr(tc, "name", ""),
                    "args": serialize(getattr(tc, "args", {})),
                    "result": serialize(getattr(tc, "result", None)),
                    "is_error": getattr(tc, "is_error", False),
                }
                for tc in result.tool_calls
            ]

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
            await rollback_if_needed(session)
            return JSONResponse({"error": str(e)}, status_code=400)

    # -- chat (streaming) ---------------------------------------------------

    def _session_factory(self):
        request = self.request
        factory = getattr(request.app.state, "admin_session_factory", None)
        if factory is None:
            real_app = request.scope.get("app")
            if real_app is not None:
                factory = getattr(real_app.state, "admin_session_factory", None)
        if factory is None:
            factory = getattr(request.state, "admin_session_factory", None)
        return factory

    async def _persist_stream_result(
        self,
        agent_name: str,
        agent: Any,
        conversation_id: str | None,
        user_message: str,
        done: dict[str, Any],
    ) -> None:
        factory = self._session_factory()
        if factory is None:
            logger.error("admin_session_factory not found! Cannot save conversation.")
            return

        cb_session = factory()
        from fastapi_admin_kit.backends.sqlalchemy import SqlAlchemySessionAdapter

        cb_adapter = SqlAlchemySessionAdapter(cb_session)
        store = AIConversationStore(
            cb_session, session_backend=cb_adapter, backend=_backend(self.request)
        )
        user = await _resolve_user(self.request)
        safe_user = _SafeUser(user)

        try:
            conv = await store.get_or_create(
                conversation_id,
                agent_name=agent_name,
                user=safe_user,
                title=user_message[:80] if user_message else None,
            )

            if user_message:
                await store.append_message(conv, role="user", content=user_message)

            usage_dict = done.get("usage") or {}
            usage_info = UsageInfo(
                request_tokens=usage_dict.get("request_tokens", 0),
                response_tokens=usage_dict.get("response_tokens", 0),
                total_tokens=usage_dict.get("total_tokens", 0),
                cost=usage_dict.get("cost", 0.0),
            )
            is_error = False
            output_text = done.get("output") or ""

            await store.append_message(
                conv,
                role="error" if is_error else "assistant",
                content=output_text,
                tokens=usage_info.total_tokens,
            )

            for tc in done.get("tool_calls", []):
                await store.log_tool_call(
                    conv,
                    ToolCallRecord(
                        name=tc.get("name", ""),
                        args=tc.get("args", {}),
                        result=tc.get("result"),
                        is_error=tc.get("is_error", False),
                    ),
                )

            cost = usage_info.cost
            new_msgs = (
                [serialize(m) for m in done.get("new_messages", [])]
                if done.get("new_messages")
                else None
            )
            await store.touch(
                conv,
                message_history=new_msgs,
                tokens_delta=usage_info.total_tokens,
                cost_delta=cost,
            )

            if not done.get("usage_recorded", False):
                await store.record_usage(
                    agent_name=agent_name,
                    model=str(agent._config.model),
                    usage=usage_info,
                    user=safe_user,
                    success=not is_error,
                    latency_ms=0,
                    tool_calls=[
                        ToolCallRecord(
                            name=tc.get("name", ""),
                            args=tc.get("args", {}),
                            result=tc.get("result"),
                            is_error=tc.get("is_error", False),
                        )
                        for tc in done.get("tool_calls", [])
                    ],
                    cost=cost,
                )

            commit_coro = cb_adapter.commit()
            if hasattr(commit_coro, "__await__"):
                await commit_coro
        except Exception as e:
            logger.error(f"Error in AI stream on_complete: {e}", exc_info=True)
            if cb_session is not None:
                try:
                    rb = cb_adapter.rollback()
                    if hasattr(rb, "__await__"):
                        await rb
                except Exception:
                    pass
        finally:
            if cb_session is not None:
                try:
                    close_coro = cb_adapter.close()
                    if hasattr(close_coro, "__await__"):
                        await close_coro
                except Exception:
                    pass

    async def stream(self) -> StreamingResponse:
        request = self.request
        body = await request.json()
        agent_name = body.get("agent", "default")
        page_url = body.get("page_url")
        conversation_id = body.get("id") or body.get("conversation_id")
        user_message = ""
        parts: list[dict] = []
        messages = body.get("messages", [])
        if messages:
            last_msg = messages[-1]
            if last_msg.get("role") == "user":
                parts = last_msg.get("parts", [])
                for part in parts:
                    if part.get("type") == "text":
                        user_message = part.get("text", "")
                    elif part.get("type") == "file":
                        pass
                if parts and not user_message:
                    user_message = "[file attachment]"

        agents = _get_ai_agents(request)
        agent = agents.get(agent_name)
        multimodal_input = (
            _build_multimodal_input(parts, model=getattr(agent._config, "model", ""))
            if parts and agent
            else user_message
        )
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

        message_history = None
        if conversation_id:
            backend = _backend(request)
            sb = _session_adapter(session)
            stmt = _select(backend, AIConversation).where(AIConversation.id == conversation_id)
            conv = (await sb.execute(stmt)).scalar_one_or_none()
            if conv and conv.message_history:
                message_history = _deserialize_messages(conv.message_history)

        async def generate():
            final_event: dict[str, Any] | None = None
            try:
                async for event in agent.stream(
                    multimodal_input,
                    deps,
                    message_history=message_history,
                    conversation_id=conversation_id,
                ):
                    event_type = event.get("type")
                    if event_type == "delta":
                        payload = json.dumps({"type": "text-delta", "delta": event.get("text", "")})
                        yield f"data: {payload}\n\n"
                    elif event_type == "done":
                        final_event = event
                        yield f"data: {json.dumps({'type': 'done'})}\n\n"
                    elif event_type == "error":
                        err = event.get("error", _FRIENDLY_TOOL_FAILURE)
                        yield f"data: {json.dumps({'type': 'error', 'error': err})}\n\n"
                    else:
                        # Forward tool_call / tool_args / tool_call_end / tool_result
                        # frames to the client verbatim.
                        yield f"data: {json.dumps(event)}\n\n"
                if final_event is not None:
                    # The agent ran on the per-request session and may have
                    # left an open write transaction (e.g. a tool call that
                    # updated a record).  Commit it *before* the streaming
                    # persistence opens its own session, otherwise both
                    # sessions hold the SQLite write lock at once and the
                    # second INSERT fails with "database is locked".
                    try:
                        commit_coro = session.commit()
                        if hasattr(commit_coro, "__await__"):
                            await commit_coro
                    except Exception:
                        logger.warning(
                            "Pre-commit of request session before AI persistence failed",
                            exc_info=True,
                        )
                    await self._persist_stream_result(
                        agent_name, agent, conversation_id, user_message, final_event
                    )
            except Exception as e:
                # The agent already converts provider tool-call rejections into a
                # graceful assistant reply; if we get here it is an unexpected
                # streaming error, so surface the real cause instead of the
                # misleading tool-failure text.
                err_text = str(e) or "Unknown streaming error"
                logger.error("AI stream crashed: %s", err_text, exc_info=True)
                yield f"data: {json.dumps({'type': 'error', 'error': err_text})}\n\n"

        return StreamingResponse(generate(), media_type="text/event-stream")

    # -- tool execution ----------------------------------------------------

    async def execute_tool(self, tool_name: str) -> JSONResponse:
        import time

        from fastapi.encoders import jsonable_encoder

        request = self.request
        agents = _get_ai_agents(request)
        if not agents:
            raise HTTPException(status_code=400, detail="No AI agents configured.")

        agent_name = request.query_params.get("agent", "default")
        agent = agents.get(agent_name)
        if agent is None:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not found.")

        try:
            params = await request.json()
        except Exception:
            params = None

        user = await _resolve_user(request)
        checker = await _resolve_checker(request, user)

        session = get_db_session(request)
        deps = AdminDeps(
            session=session,
            admin_user=user,
            request=request,
            registry=request.app.state.admin_registry,
            permission_checker=checker,
        )

        start = time.perf_counter()
        try:
            result = await agent.execute_tool(tool_name, params or {}, deps)
            latency_ms = int((time.perf_counter() - start) * 1000)

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

            return JSONResponse({"success": True, "result": jsonable_encoder(result)})
        except Exception as e:
            latency_ms = int((time.perf_counter() - start) * 1000)

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

    # -- conversation CRUD --------------------------------------------------

    async def list_conversations(self) -> JSONResponse:
        request = self.request
        user = await _resolve_user(request)
        session = get_db_session(request)
        backend = _backend(request)
        sb = _session_adapter(session)

        stmt = (
            _select(backend, AIConversation)
            .where(AIConversation.user_id == getattr(user, "id", None))
            .order_by(AIConversation.last_message_at.desc().nullslast())
            .limit(50)
        )
        convs = (await sb.execute(stmt)).scalars().all()

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

    async def load_conversation(self, conversation_id: str) -> JSONResponse:
        request = self.request
        user = await _resolve_user(request)
        session = get_db_session(request)
        backend = _backend(request)
        sb = _session_adapter(session)

        store = AIConversationStore(session, backend=backend)
        conv = await store.load(conversation_id, user)
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found.")

        msgs = await store.load_messages(conversation_id)

        from fastapi_admin_kit.ai.usage import AIAttachment

        att_stmt = (
            _select(backend, AIAttachment)
            .where(AIAttachment.conversation_id == conversation_id)
            .order_by(AIAttachment.created_at)
        )
        attachments = (await sb.execute(att_stmt)).scalars().all()

        attachments_by_message: dict[int, list[dict]] = {}
        for att in attachments:
            if att.message_id is not None:
                storage_url = (
                    request.app.state.admin_storage.url(att.file_path)
                    if request.app.state.admin_storage
                    else att.file_path
                )
                attachments_by_message.setdefault(att.message_id, []).append(
                    {
                        "id": att.id,
                        "filename": att.filename,
                        "url": storage_url,
                        "mime_type": att.mime_type,
                        "size": att.file_size,
                    }
                )

        user_msg_indices = [i for i, m in enumerate(msgs) if m.role == "user"]
        unattached = [att for att in attachments if att.message_id is None]
        for idx, att in zip(user_msg_indices, unattached):
            storage_url = (
                request.app.state.admin_storage.url(att.file_path)
                if request.app.state.admin_storage
                else att.file_path
            )
            attachments_by_message.setdefault(msgs[idx].id, []).append(
                {
                    "id": att.id,
                    "filename": att.filename,
                    "url": storage_url,
                    "mime_type": att.mime_type,
                    "size": att.file_size,
                }
            )

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
                    "attachments": attachments_by_message.get(m.id, []),
                }
                for m in msgs
            ]
        )

    async def delete_conversation(self, conversation_id: str) -> JSONResponse:
        request = self.request
        user = await _resolve_user(request)
        session = get_db_session(request)

        deleted = await AIConversationStore(session, backend=_backend(request)).delete(
            conversation_id, user
        )
        if not deleted:
            raise HTTPException(status_code=404, detail="Conversation not found.")
        return JSONResponse({"success": True})

    # -- read-only analytics endpoints -------------------------------------

    async def get_logs(
        self, limit: int, offset: int, agent: str | None, tool: str | None
    ) -> JSONResponse:
        from fastapi_admin_kit.ai.usage import AIUsageLog

        session = get_db_session(self.request)
        backend = _backend(self.request)
        sb = _session_adapter(session)
        stmt = _select(backend, AIUsageLog).order_by(AIUsageLog.timestamp.desc())
        if agent:
            stmt = stmt.where(AIUsageLog.agent_name == agent)
        stmt = stmt.offset(offset).limit(limit)
        rows = (await sb.execute(stmt)).scalars().all()

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

    async def get_tool_calls(
        self, limit: int, offset: int, tool: str | None, success: bool | None
    ) -> JSONResponse:
        from fastapi_admin_kit.ai.usage import AIMessage

        session = get_db_session(self.request)
        backend = _backend(self.request)
        sb = _session_adapter(session)
        stmt = (
            _select(backend, AIMessage)
            .where(AIMessage.role == "tool")
            .order_by(AIMessage.created_at.desc())
        )
        if tool:
            stmt = stmt.where(AIMessage.tool_name == tool)
        if success is not None:
            is_error = not bool(success)
            stmt = stmt.where(AIMessage.is_error == is_error)
        stmt = stmt.offset(offset).limit(limit)
        msgs = (await sb.execute(stmt)).scalars().all()

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

    async def get_costs(self, period: str, agent: str | None) -> JSONResponse:
        from fastapi_admin_kit.ai.usage import AIUsageWriter

        session = get_db_session(self.request)
        writer = AIUsageWriter()
        agent_name = agent or "default"
        stats = await writer.aggregate(agent_name=agent_name, period=period, session=session)
        return JSONResponse(stats)

    async def list_agents(self) -> JSONResponse:
        agents = _get_ai_agents(self.request)
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

    async def list_tools(self) -> JSONResponse:
        plugin = getattr(self.request.app.state, "ai_config", None)
        agents = getattr(plugin, "agents", None) or []

        seen: dict[str, dict[str, object]] = {}
        for cfg in agents:
            resolved = getattr(cfg, "_resolved_tools", None) or []
            for t in resolved:
                seen.setdefault(
                    t.name,
                    {
                        "name": t.name,
                        "description": t.description,
                        "category": t.category,
                        "uses_context": t.uses_context,
                    },
                )

        return JSONResponse(list(seen.values()))
