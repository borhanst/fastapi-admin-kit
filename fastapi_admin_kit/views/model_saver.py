"""ModelSaver — ORM-agnostic module for applying parsed data to ORM objects.

Consolidates duplicated logic for:
- Mapping relationship names to FK column names
- Extracting and applying MANYTOMANY data
- Saving inline formset objects

Depends on IntrospectionBackend and SessionBackend protocols for ORM-agnosticism.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request

from fastapi_admin_kit.registry import RegisteredModel


class ModelSaver:
    """ORM-agnostic helper for writing parsed data to ORM objects.

    Uses IntrospectionBackend for model metadata and SessionBackend for
    data access, allowing future non-SQLAlchemy backends.
    """

    def __init__(self, registered: RegisteredModel) -> None:
        self.registered = registered

    def _get_introspection(self, request: Request) -> Any:
        """Get the IntrospectionBackend from app.state."""
        return getattr(request.app.state, "admin_introspection_adapter", None)

    def _get_session(self, request: Request) -> Any:
        """Get the SessionBackend from request."""
        from fastapi_admin_kit.db import get_db_session

        return get_db_session(request)

    def apply_parsed(self, obj: Any, parsed: dict[str, Any], request: Request) -> None:
        """Apply parsed form/JSON data to an ORM object.

        Relationship fields (e.g. ``"user"``) are resolved to their
        local foreign-key column (e.g. ``"user_id"``) so that the
        correct column is persisted by the ORM.
        """
        introspection = self._get_introspection(request)
        col_names = {c.name for c in self.registered.columns}

        # Build mapping: relationship key -> local FK column key
        rel_fk_map: dict[str, str] = {}
        if introspection is not None:
            for rel in self.registered.relationships:
                if rel.direction == "MANYTOMANY":
                    continue
                local_cols = introspection.get_relationship_local_columns(
                    self.registered.model, rel.name
                )
                if local_cols:
                    rel_fk_map[rel.name] = local_cols[0]
        else:
            # Fallback for missing introspection (should not happen)
            from sqlalchemy import inspect as sa_inspect

            try:
                mapper = sa_inspect(type(obj))
            except Exception:
                mapper = None
            if mapper is not None:
                for rel_key, rel_prop in mapper.relationships.items():
                    if rel_prop.direction.name == "MANYTOMANY":
                        continue
                    local_cols = [c.key for c in rel_prop.local_columns]
                    if local_cols:
                        rel_fk_map[rel_key] = local_cols[0]

        for key, value in parsed.items():
            if key in col_names:
                setattr(obj, key, value)
            elif key in rel_fk_map:
                setattr(obj, rel_fk_map[key], value)

    def resolve_rel_keys(self, parsed: dict[str, Any], request: Request) -> dict[str, Any]:
        """Convert relationship keys in parsed data to their FK column names.

        Returns a new dict with relationship keys replaced by FK column keys.
        """
        introspection = self._get_introspection(request)
        col_names = {c.name for c in self.registered.columns}
        rel_fk_map: dict[str, str] = {}
        if introspection is not None:
            for rel in self.registered.relationships:
                if rel.direction == "MANYTOMANY":
                    continue
                local_cols = introspection.get_relationship_local_columns(
                    self.registered.model, rel.name
                )
                if local_cols:
                    rel_fk_map[rel.name] = local_cols[0]
        else:
            # Fallback
            from sqlalchemy import inspect as sa_inspect

            try:
                mapper = sa_inspect(self.registered.model)
            except Exception:
                mapper = None
            if mapper is not None:
                for rel_key, rel_prop in mapper.relationships.items():
                    if rel_prop.direction.name == "MANYTOMANY":
                        continue
                    local_cols = [c.key for c in rel_prop.local_columns]
                    if local_cols:
                        rel_fk_map[rel_key] = local_cols[0]

        resolved: dict[str, Any] = {}
        for key, value in parsed.items():
            if key in rel_fk_map and key not in col_names:
                resolved[rel_fk_map[key]] = value
            else:
                resolved[key] = value
        return resolved

    def extract_m2m(self, obj: Any, parsed: dict[str, Any], request: Request) -> dict[str, Any]:
        """Extract MANYTOMANY relationship data from parsed dict in-place.

        Returns a dict mapping rel_key -> raw parsed value for M2M fields.
        """
        introspection = self._get_introspection(request)
        m2m_data: dict[str, Any] = {}
        if introspection is not None:
            model_class = obj if isinstance(obj, type) else type(obj)
            for rel in self.registered.relationships:
                if rel.direction == "MANYTOMANY" and rel.name in parsed:
                    m2m_data[rel.name] = parsed.pop(rel.name)
        else:
            # Fallback
            from sqlalchemy import inspect as sa_inspect

            try:
                model_class = type(obj) if not isinstance(obj, type) else obj
                mapper = sa_inspect(model_class)
            except Exception:
                return m2m_data
            for rel_key, rel_prop in mapper.relationships.items():
                if rel_prop.direction.name == "MANYTOMANY" and rel_key in parsed:
                    m2m_data[rel_key] = parsed.pop(rel_key)
        return m2m_data

    async def apply_m2m(self, obj: Any, m2m_data: dict[str, Any], request: Request) -> None:
        """Apply MANYTOMANY data extracted by extract_m2m."""
        if not m2m_data:
            return
        session = self._get_session(request)
        introspection = self._get_introspection(request)

        if introspection is not None:
            for rel in self.registered.relationships:
                if rel.direction != "MANYTOMANY":
                    continue
                if rel.name not in m2m_data:
                    continue
                raw = m2m_data[rel.name]
                pk_list = list(raw) if isinstance(raw, list) else [raw]
                target_model = rel.target_model
                objs = []
                for pk in pk_list:
                    if not pk:
                        continue
                    try:
                        casted_pk = introspection.cast_pk_value(target_model, pk)
                        loaded = await session.get(target_model, casted_pk)
                        if loaded:
                            objs.append(loaded)
                    except (ValueError, TypeError):
                        pass
                # Pre-load the collection inside the async greenlet so the
                # subsequent setattr does not trigger a lazy load (MissingGreenlet).
                await session.refresh(obj, [rel.name])
                setattr(obj, rel.name, objs)
        else:
            # Fallback
            from sqlalchemy import inspect as sa_inspect

            try:
                mapper = sa_inspect(type(obj))
            except Exception:
                return
            for rel_key, rel_prop in mapper.relationships.items():
                if rel_prop.direction.name != "MANYTOMANY":
                    continue
                if rel_key not in m2m_data:
                    continue
                raw = m2m_data[rel_key]
                pk_list = list(raw) if isinstance(raw, list) else [raw]
                target_model = rel_prop.mapper.class_
                objs = []
                for pk in pk_list:
                    if not pk:
                        continue
                    try:
                        from fastapi_admin_kit.inspection import cast_pk_value

                        loaded = await session.get(target_model, cast_pk_value(target_model, pk))
                        if loaded:
                            objs.append(loaded)
                    except (ValueError, TypeError):
                        pass
                await session.refresh(obj, [rel_key])
                setattr(obj, rel_key, objs)

    async def save_inline_objects(self, request: Request, parent_obj: Any) -> None:
        """Parse and save inline formset objects."""
        from fastapi_admin_kit.inspection import cast_pk_value

        inlines = getattr(self.registered.admin, "inlines", [])
        if not inlines:
            return

        # Use cached form data from form_parser.parse()
        form_data = getattr(request, "_cached_form_data", None)
        if form_data is None:
            form_data = await request.form()
        session = self._get_session(request)
        introspection = self._get_introspection(request)

        for inline_cls in inlines:
            inline_instance = inline_cls() if isinstance(inline_cls, type) else inline_cls
            related_model = inline_instance.model
            if related_model is None:
                continue

            prefix = f"{related_model.__tablename__}_set"

            # Get FK field
            fk_field = inline_instance.fk_name
            if not fk_field:
                if introspection is not None:
                    # Use introspection to find FK field
                    for rel in self.registered.relationships:
                        if rel.direction == "MANYTOONE":
                            # This is a relationship from parent to related, not what we need
                            pass
                    # We need to inspect the related model for relationships pointing to parent
                    parent_table = self.registered.table_name
                    # This is a bit tricky; we need to find the FK on the related model
                    # that points to the parent table. We'll use a helper method.
                    fk_field = self._find_fk_field(introspection, related_model, parent_table)
                else:
                    # Fallback
                    from sqlalchemy import inspect as sa_inspect

                    mapper = sa_inspect(related_model)
                    parent_table = self.registered.table_name
                    for rel_key, rel_prop in mapper.relationships.items():
                        if rel_prop.direction.name == "MANYTOONE":
                            target_table = rel_prop.mapper.class_.__tablename__
                            if target_table == parent_table:
                                local_cols = [c.key for c in rel_prop.local_columns]
                                if local_cols:
                                    fk_field = local_cols[0]
                                    break

            if not fk_field:
                continue

            # Parse formset data
            total_forms = int(form_data.get(f"{prefix}-TOTAL_FORMS", "0"))
            initial_forms = int(form_data.get(f"{prefix}-INITIAL_FORMS", "0"))
            deleted_ids: list[str] = []

            # Collect deleted IDs
            for i in range(initial_forms):
                delete_key = f"{prefix}-{i}-DELETE"
                if form_data.get(delete_key) in ("on", "1"):
                    obj_id = form_data.get(f"{prefix}-{i}-id", "")
                    if obj_id:
                        deleted_ids.append(obj_id)

            # Delete marked objects
            for obj_id in deleted_ids:
                try:
                    pk_val = cast_pk_value(related_model, obj_id)
                    existing = await session.get(related_model, pk_val)
                    if existing:
                        await session.delete(existing)
                except Exception:
                    pass

            # Get fields to save — use registered columns if inline has no explicit fields
            from fastapi_admin_kit.registry import AdminRegistry

            related_registry = AdminRegistry()
            related_registered = related_registry.get(related_model.__tablename__)
            related_columns = related_registered.columns if related_registered else None
            fields = inline_instance.get_form_fields(columns=related_columns)
            if not fields:
                continue

            # Create/update objects
            for i in range(total_forms):
                obj_id = form_data.get(f"{prefix}-{i}-id", "")
                delete_key = f"{prefix}-{i}-DELETE"
                if form_data.get(delete_key) in ("on", "1"):
                    continue

                # Build data dict
                data: dict[str, Any] = {}
                for field_name in fields:
                    val = form_data.get(f"{prefix}-{i}-{field_name}")
                    if val is not None:
                        # Check if field is a relationship
                        rel = None
                        if introspection is not None:
                            rel = introspection.get_relationship(related_model, field_name)
                        else:
                            from sqlalchemy import inspect as sa_inspect

                            try:
                                mapper = sa_inspect(related_model)
                                rel = mapper.relationships.get(field_name)
                            except Exception:
                                rel = None

                        if rel is not None:
                            # Relationship field
                            if introspection is not None:
                                local_cols = introspection.get_relationship_local_columns(
                                    related_model, field_name
                                )
                            else:
                                local_cols = [c.key for c in rel.local_columns]
                            fk_col = local_cols[0] if local_cols else None
                            if val and fk_col:
                                casted_val = val
                                try:
                                    casted_val = cast_pk_value(related_model, val)
                                except Exception:
                                    pass
                                data[fk_col] = casted_val
                            elif not val and fk_col:
                                data[fk_col] = None
                        else:
                            # Regular column
                            related_col = None
                            if related_registered:
                                related_col = next(
                                    (c for c in related_registered.columns if c.name == field_name),
                                    None,
                                )
                            if related_col is not None:
                                from fastapi_admin_kit.inspection import (
                                    cast_value,
                                )

                                val = cast_value(related_col, val)
                            data[field_name] = val

                if obj_id:
                    try:
                        pk_val = cast_pk_value(related_model, obj_id)
                        existing = await session.get(related_model, pk_val)
                        if existing:
                            for k, v in data.items():
                                setattr(existing, k, v)
                    except Exception:
                        pass
                else:
                    parent_pk_field = self.registered.pk_field or "id"
                    data[fk_field] = getattr(parent_obj, parent_pk_field, None)
                    new_obj = related_model(**data)
                    session.add(new_obj)

            await session.flush()

    def _find_fk_field(
        self, introspection: Any, related_model: type, parent_table: str
    ) -> str | None:
        """Find the FK field on related_model that points to parent_table."""
        # Use introspection to get relationships of related_model
        rel_names = introspection.get_relationship_names(related_model)
        for rel_name in rel_names:
            rel = introspection.get_relationship(related_model, rel_name)
            if rel is None:
                continue
            # Check if this relationship points to the parent table
            target_model = rel.target_model if hasattr(rel, "target_model") else None
            if target_model is None:
                continue
            target_table = getattr(target_model, "__tablename__", None)
            if target_table == parent_table:
                local_cols = introspection.get_relationship_local_columns(related_model, rel_name)
                if local_cols:
                    return local_cols[0]
        return None
