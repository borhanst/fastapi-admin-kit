"""Default dynamic prompt / instruction providers.

Each provider is a function from ``RunContext[AdminDeps]`` to a prompt string
(or ``None`` to contribute nothing). They are registered as *instructions* on
the underlying Pydantic AI agent so every run is contextualised with the
current user, their permissions, the page they are viewing, and baseline
security guardrails. They are plain functions over ``AdminDeps`` so they can
be unit-tested without invoking a model.
"""

from __future__ import annotations

from pydantic_ai import RunContext

from fastapi_admin_kit.ai.deps import AdminDeps

#: Default security guardrails injected into every agent run unless disabled.
GUARDRAILS_TEXT = (
    "SECURITY GUARDRAILS (always follow):\n"
    "- Never query or return personally identifiable information (PII) such "
    "as full street addresses with house numbers, phone numbers, or payment "
    "details unless the user has explicit permission for the specific record "
    "they are already viewing.\n"
    "- Never expose credentials, secrets, tokens, or API keys.\n"
    "- Never create, update, or delete users, or change roles/permissions, "
    "without explicit, unambiguous confirmation from the user.\n"
    "- Never attempt to bypass authentication or escalate privileges.\n"
    "- Do not provide instructions that could be used to compromise the system.\n"
    "- If a request seems unsafe or ambiguous, decline and explain why.\n"
    "- Never output tool calls or JSON as plain text (e.g. no `\u003cfunction=...\u003e`).\n"
    "- Only call a tool when the user explicitly asks to perform a data operation "
    "(look up, list, create, update, or delete a record). For greetings (e.g. "
    "'hi'), small talk, or general questions you can answer directly, reply in "
    "plain natural language and do NOT call any tool.\n"
    "- When page context is provided (e.g. 'viewing record with ID: X'), use "
    "that ID automatically in your tool calls without asking, unless it seems derived.\n"
)


def guardrails(_: RunContext[AdminDeps]) -> str:
    """Static security rules applied to every run."""
    return GUARDRAILS_TEXT


def page_context(ctx: RunContext[AdminDeps]) -> str | None:
    """Describe the table/record the user is currently viewing, if resolvable."""
    deps = ctx.deps
    page_url = deps.page_url
    if not page_url:
        return None

    admin_path = "/"
    try:
        admin_path = deps.request.app.state.admin_config.get("admin_path", "/admin")
    except Exception:
        pass

    path = page_url.rstrip("/")
    if not path.startswith(admin_path):
        return None
    relative = path[len(admin_path) :].strip("/")
    if not relative:
        return None

    parts = relative.split("/")
    table_name = parts[0]
    registered = deps.registry.get(table_name)
    if registered is None:
        return None

    col_names = [c.name for c in registered.columns]
    col_types = {c.name: str(c.type) for c in registered.columns}
    cols_desc = ", ".join(f"{name} ({col_types.get(name, '?')})" for name in col_names)

    context = (
        f"The user is currently on the {registered.verbose_name} page "
        f"(table: {table_name}). "
        f"Available columns: {cols_desc}. "
        f"Use these exact table and column names when querying."
    )

    if len(parts) > 1 and parts[1]:
        context += f" The user is viewing record with ID: {parts[1]}."

    return context


async def user_context(ctx: RunContext[AdminDeps]) -> str:
    """Tell the model who the current user is and which tables they may act on.

    Only tables the user can actually access are listed, so the model does not
    propose operations that the permission layer would later reject.
    """
    deps = ctx.deps
    user = deps.admin_user
    name = getattr(user, "name", None) or getattr(user, "email", None) or "an admin"
    is_superuser = bool(getattr(user, "is_superuser", False))

    lines = [f"Current admin user: {name}."]

    # Best effort: enumerate the tables this user may read.
    try:
        checker = deps.permission_checker
        registry = deps.registry
        if not is_superuser:
            allowed: list[str] = []
            for registered in registry.all():
                try:
                    if await checker.has_permission(registered.table_name, "read"):
                        allowed.append(registered.table_name)
                except Exception:
                    continue
            if allowed:
                lines.append("You may query these tables: " + ", ".join(sorted(allowed)) + ".")
            else:
                lines.append(
                    "This user has no read access to any table; only use tools the "
                    "user can legitimately call, otherwise decline."
                )
        else:
            tables = ", ".join(sorted(r.table_name for r in registry.all())) or "none"
            lines.append(f"Superuser; all tables available: {tables}.")
    except Exception:
        pass

    return " ".join(lines)
