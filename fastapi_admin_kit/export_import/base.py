"""Base classes for Export and Import functionality."""

from __future__ import annotations

import csv
import io
from abc import ABC, abstractmethod
from typing import Any


class ExportBase(ABC):
    """Base class for all export implementations.

    Subclass this to create custom export formats. The export class
    is responsible for serializing model instances to a file format.
    """

    # Configuration options
    columns: list[str] | None = None
    headers: dict[str, str] | None = None
    delimiter: str = ","
    encoding: str = "utf-8"
    include_header: bool = True
    max_rows: int | None = None
    queryset_filter: callable | None = None

    def __init__(self, registered: Any) -> None:
        self.registered = registered
        self.admin = registered.admin

    def get_queryset(self, request: Any = None) -> Any:
        """Get the base queryset for export.

        Override to apply custom filtering or ordering.
        """
        from fastapi_admin_kit.db import get_db_session

        session = get_db_session(request) if request else None
        if session:
            qs = self.admin.get_queryset(session, request)
        else:
            qs = None

        if self.queryset_filter and qs:
            qs = self.queryset_filter(qs)

        return qs

    def get_columns(self) -> list[str]:
        """Get the list of columns to export.

        Returns configured columns or all model columns.
        """
        if self.columns:
            return self.columns
        return [c.name for c in self.registered.columns]

    def get_headers(self) -> dict[str, str]:
        """Get column headers for export.

        Returns configured headers or auto-generated headers.
        """
        if self.headers:
            return self.headers
        return {col: col.replace("_", " ").title() for col in self.get_columns()}

    def get_value(self, obj: Any, column: str) -> Any:
        """Extract a value from an object for a given column.

        Override for custom value extraction (e.g., related objects).
        """
        return getattr(obj, column, None)

    def format_value(self, value: Any, column: str) -> Any:
        """Format a value for export.

        Override for custom formatting (e.g., date formatting, currency).
        """
        if value is None:
            return ""
        return value

    @abstractmethod
    def export(self, queryset: Any, request: Any = None) -> io.BytesIO:
        """Export data to a file-like object.

        Args:
            queryset: The queryset to export
            request: Optional request object for context

        Returns:
            A BytesIO object containing the exported data
        """
        ...

    def export_rows(self, rows: list[Any], request: Any = None) -> io.BytesIO:
        """Export a list of objects.

        This is an alternative to export() that takes a pre-fetched list.
        Useful for exporting selected items.
        """
        columns = self.get_columns()
        headers = self.get_headers()

        output = io.BytesIO()
        wrapper = io.TextIOWrapper(output, encoding=self.encoding, newline="")
        writer = csv.writer(wrapper, delimiter=self.delimiter)

        if self.include_header:
            writer.writerow([headers.get(col, col) for col in columns])

        row_count = 0
        for obj in rows:
            if self.max_rows and row_count >= self.max_rows:
                break
            row = []
            for col in columns:
                value = self.get_value(obj, col)
                value = self.format_value(value, col)
                row.append(value)
            writer.writerow(row)
            row_count += 1

        wrapper.flush()
        # Detach wrapper before reading to prevent it from closing the BytesIO
        data = wrapper.buffer.getvalue()
        wrapper.detach()
        output = io.BytesIO(data)
        output.seek(0)
        return output


class ImportBase(ABC):
    """Base class for all import implementations.

    Subclass this to create custom import formats. The import class
    is responsible for parsing files and creating/updating model instances.
    """

    # Configuration options
    required_columns: list[str] = []
    field_map: dict[str, str] | None = None
    unique_key: str | list[str] | None = None
    batch_size: int = 1000
    skip_errors: bool = False
    dry_run: bool = False
    encoding: str = "utf-8"

    def __init__(self, registered: Any) -> None:
        self.registered = registered
        self.admin = registered.admin

    def get_field_map(self) -> dict[str, str]:
        """Get the mapping from file headers to model fields.

        Returns configured field_map or auto-generated mapping.
        """
        if self.field_map:
            return self.field_map
        # Default: map header names to model field names (lowercase, underscored)
        return {col.name.replace("_", " ").title(): col.name for col in self.registered.columns}

    def validate_row(self, row: dict[str, Any], index: int) -> tuple[bool, str | None]:
        """Validate a single row before import.

        Args:
            row: The row data as a dictionary
            index: The row number (0-based, excluding header)

        Returns:
            A tuple of (is_valid, error_message)
        """
        # Check required columns
        for col in self.required_columns:
            if col not in row or row[col] is None or str(row[col]).strip() == "":
                return False, f"Row {index + 1}: Required column '{col}' is missing or empty"
        return True, None

    def transform_row(self, row: dict[str, Any]) -> dict[str, Any]:
        """Transform a row before saving.

        Coerces string values from CSV/Excel to proper Python types
        based on the model column types.
        """
        from datetime import datetime

        from sqlalchemy import Boolean, DateTime, Float, Integer, Numeric
        from sqlalchemy.sql import sqltypes

        col_types = {c.name: c.type for c in self.registered.columns}
        coerced = {}
        for field, value in row.items():
            col_type = col_types.get(field)

            if value is None or (isinstance(value, str) and value.strip() == ""):
                coerced[field] = None
            elif col_type is None:
                coerced[field] = value
            elif isinstance(col_type, Boolean):
                coerced[field] = str(value).strip().lower() in ("true", "1", "yes")
            elif isinstance(col_type, Integer):
                try:
                    coerced[field] = int(value)
                except (ValueError, TypeError):
                    coerced[field] = value
            elif isinstance(col_type, Float | Numeric):
                try:
                    coerced[field] = float(value)
                except (ValueError, TypeError):
                    coerced[field] = value
            elif isinstance(col_type, DateTime | sqltypes.TIMESTAMP):
                if isinstance(value, datetime):
                    coerced[field] = value
                elif isinstance(value, str) and value.strip():
                    try:
                        coerced[field] = datetime.fromisoformat(value.strip())
                    except ValueError:
                        coerced[field] = value
                else:
                    coerced[field] = None
            else:
                coerced[field] = value

        return coerced

    def get_unique_key(self) -> str | list[str] | None:
        """Get the unique key column(s) for upsert operations.

        Defaults to the model's primary key if not configured.
        """
        if self.unique_key:
            return self.unique_key
        from sqlalchemy import inspect as sa_inspect

        mapper = sa_inspect(self.registered.model)
        pk_cols = [c.key for c in mapper.primary_key]
        if len(pk_cols) == 1:
            return pk_cols[0]
        return pk_cols if pk_cols else None

    @abstractmethod
    def parse(self, file_content: bytes, request: Any = None) -> list[dict[str, Any]]:
        """Parse the uploaded file and return a list of row dictionaries.

        Args:
            file_content: The raw file content as bytes
            request: Optional request object for context

        Returns:
            A list of dictionaries, each representing a row
        """
        ...

    async def import_data(
        self,
        rows: list[dict[str, Any]],
        request: Any = None,
    ) -> dict[str, Any]:
        """Import parsed rows into the database.

        Args:
            rows: List of row dictionaries from parse()
            request: Optional request object for context

        Returns:
            A summary dict with 'created', 'updated', 'errors', 'error_messages'
        """
        from fastapi_admin_kit.db import get_db_session

        session = get_db_session(request) if request else None
        if not session:
            return {
                "created": 0,
                "updated": 0,
                "errors": 0,
                "error_messages": ["No database session"],
            }

        # Disable autoflush to prevent sync greenlet calls during loop
        session.autoflush = False

        field_map = self.get_field_map()
        unique_key = self.get_unique_key()
        model = self.registered.model

        from sqlalchemy import inspect as sa_inspect

        pk_fields = {c.key for c in sa_inspect(model).primary_key}

        created = 0
        updated = 0
        errors = 0
        error_messages: list[str] = []

        for i, row in enumerate(rows):
            try:
                # Map file headers to model field names
                mapped_row = {}
                for file_header, value in row.items():
                    model_field = field_map.get(file_header, file_header)
                    mapped_row[model_field] = value

                # Validate row
                is_valid, error_msg = self.validate_row(mapped_row, i)
                if not is_valid:
                    errors += 1
                    error_messages.append(error_msg or f"Row {i + 1}: Validation failed")
                    continue

                # Transform row
                mapped_row = self.transform_row(mapped_row)

                if self.dry_run:
                    continue

                # Check for existing record (upsert)
                if unique_key:
                    key_conditions = {}
                    keys = unique_key if isinstance(unique_key, list) else [unique_key]
                    for key in keys:
                        if key in mapped_row:
                            key_conditions[key] = mapped_row[key]

                    if key_conditions:
                        from sqlalchemy import select

                        stmt = select(model)
                        for k, v in key_conditions.items():
                            stmt = stmt.where(getattr(model, k) == v)
                        result = await session.execute(stmt)
                        existing = result.scalar_one_or_none()

                        if existing:
                            # Update existing — skip primary key fields
                            for field, value in mapped_row.items():
                                if field not in pk_fields and hasattr(existing, field):
                                    setattr(existing, field, value)
                            self.admin.on_update(existing, mapped_row, request)
                            updated += 1
                            continue

                # Create new record — skip primary key fields to let DB auto-generate
                create_data = {
                    k: v for k, v in mapped_row.items() if k not in pk_fields and hasattr(model, k)
                }
                obj = model(**create_data)
                self.admin.on_create(obj, request)
                session.add(obj)
                created += 1

            except Exception as e:
                errors += 1
                error_msg = f"Row {i + 1}: {str(e)}"
                error_messages.append(error_msg)
                if not self.skip_errors:
                    break

        if not self.dry_run and (created > 0 or updated > 0):
            try:
                session.autoflush = True
                await session.flush()
            except Exception as e:
                await session.rollback()
                return {
                    "created": 0,
                    "updated": 0,
                    "errors": len(rows),
                    "error_messages": [f"Database error: {str(e)}"],
                }
        else:
            session.autoflush = True

        return {
            "created": created,
            "updated": updated,
            "errors": errors,
            "error_messages": error_messages,
        }
