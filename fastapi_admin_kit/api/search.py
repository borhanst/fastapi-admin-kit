"""Global search API — returns model and field suggestions for the topbar search bar."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

router = APIRouter(tags=["api-search"])


async def require_any_auth(request: Request) -> Any:
    """Accept either JWT Bearer token or session cookie.

    Only validates the credential — no DB lookup (pure metadata search needs
    no user object, just proof of authentication).
    """
    # Try JWT first (Authorization: Bearer <token>)
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        from fastapi_admin_kit.api.auth import _get_secret_key, decode_access_token

        token = auth_header[7:]
        secret_key = _get_secret_key(request)
        payload = decode_access_token(token, secret_key)
        if payload is not None:
            return payload

    # Fall back to session cookie — just verify it decodes, no DB hit
    session_backend = getattr(request.app.state, "admin_session_backend", None)
    if session_backend is not None:
        token = request.cookies.get(session_backend.cookie_name)
        if token:
            session = session_backend.decode(token)
            if session and session.get("user_id") is not None:
                return session

    raise HTTPException(status_code=401, detail="Not authenticated.")


@router.get("/search/suggestions")
async def get_search_suggestions(
    request: Request,
    q: str = Query("", min_length=0),
    _user: Any = Depends(require_any_auth),
) -> dict[str, Any]:
    """GET /admin/search/suggestions?q=... — return model and field suggestions.

    Pure metadata scan — no DB queries, extremely fast.
    Results are categorised into:
      - ``model`` suggestions  (verbose model name matches the query)
      - ``field``  suggestions (field label / name matches the query)
    """

    registry = getattr(request.app.state, "admin_registry", None)
    if registry is None or not q.strip():
        return {"suggestions": [], "query": q}

    query_lower = q.strip().lower()
    suggestions: list[dict[str, Any]] = []

    for registered in registry.all():
        if getattr(registered.admin, "skip_auto_routes", False):
            continue
        table_name: str = registered.table_name
        verbose_name: str = registered.verbose_name
        verbose_name_plural: str = registered.verbose_name_plural
        admin = registered.admin

        # ── Model-level match ─────────────────────────────────────────────
        if (
            query_lower in verbose_name.lower()
            or query_lower in verbose_name_plural.lower()
            or query_lower in table_name.lower()
        ):
            suggestions.append(
                {
                    "type": "model",
                    "model": table_name,
                    "label": verbose_name_plural,
                    "sublabel": table_name,
                    "url": f"/admin/{table_name}",
                }
            )

        # ── Field-level matches ───────────────────────────────────────────
        field_entries: list[tuple[str, str]] = []  # (field_name, human_label)

        for col in registered.columns:
            if col.primary_key:
                continue
            name = col.name
            if name.endswith("_id"):
                label = name[:-3].replace("_", " ").title()
            else:
                label = name.replace("_", " ").title()
            field_entries.append((name, label))

        for rel in getattr(registered, "relationships", []):
            label = rel.name.replace("_", " ").title()
            field_entries.append((rel.name, label))

        extra_fields: list[str] = list(
            set(
                (getattr(admin, "search_fields", None) or [])
                + (getattr(admin, "list_display", None) or [])
            )
        )
        existing_names = {fe[0] for fe in field_entries}
        for fname in extra_fields:
            if fname not in existing_names:
                field_entries.append((fname, fname.replace("_", " ").title()))

        for field_name, field_label in field_entries:
            if query_lower in field_label.lower() or query_lower in field_name.lower():
                suggestions.append(
                    {
                        "type": "field",
                        "model": table_name,
                        "field": field_name,
                        "label": f"{verbose_name_plural} → {field_label}",
                        "sublabel": f"{table_name}.{field_name}",
                        "url": f"/admin/{table_name}?q={q}",
                    }
                )

    # ── Rank: model matches first, then field matches; cap at 15 ──────────
    model_hits = [s for s in suggestions if s["type"] == "model"]
    field_hits = [s for s in suggestions if s["type"] == "field"]
    ranked = (model_hits + field_hits)[:15]

    return {"suggestions": ranked, "query": q}
