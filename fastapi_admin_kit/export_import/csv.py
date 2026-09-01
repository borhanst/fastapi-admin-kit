"""CSV Export implementation."""

from __future__ import annotations

import csv
import io
from typing import Any

from fastapi_admin_kit.export_import.base import ExportBase, ImportBase, sanitize_export_cell


class CSVExport(ExportBase):
    """Export data to CSV format.

    This is the default export format. It supports streaming for large
    datasets and respects all ExportBase configuration options.

    Usage::

        class ProductExport(CSVExport):
            columns = ["id", "name", "price"]
            headers = {"name": "Product Name", "price": "Price (USD)"}
            delimiter = ","
    """

    def export(self, queryset: Any, request: Any = None) -> io.BytesIO:
        """Export queryset to CSV format.

        Args:
            queryset: SQLAlchemy queryset or list of objects
            request: Optional request object

        Returns:
            BytesIO object containing CSV data
        """
        columns = self.get_columns()
        headers = self.get_headers()

        output = io.BytesIO()
        wrapper = io.TextIOWrapper(output, encoding=self.encoding, newline="")
        writer = csv.writer(wrapper, delimiter=self.delimiter)

        if self.include_header:
            header_row = []
            if self.include_serial:
                header_row.append(self.serial_header)
            header_row.extend([headers.get(col, col) for col in columns])
            writer.writerow(header_row)

        row_count = 0
        if queryset is not None:
            for obj in queryset:
                if self.max_rows and row_count >= self.max_rows:
                    break
                row = []
                if self.include_serial:
                    row.append(str(row_count + 1))
                for col in columns:
                    value = self.get_value(obj, col)
                    value = self.format_value(value, col)
                    row.append(sanitize_export_cell(value))
                writer.writerow(row)
                row_count += 1

        wrapper.flush()
        # Detach wrapper before reading to prevent it from closing the BytesIO
        data = wrapper.buffer.getvalue()
        wrapper.detach()
        output = io.BytesIO(data)
        output.seek(0)
        return output

    def export_filtered(
        self,
        request: Any,
        q: str = "",
        page: int = 1,
        filters: dict[str, str] | None = None,
    ) -> io.BytesIO:
        """Export filtered data from the list view.

        This method uses the same filtering as the list view to export
        the currently visible data.

        Args:
            request: FastAPI request object
            q: Search query
            page: Page number (for pagination context)
            filters: Active filters

        Returns:
            BytesIO object containing CSV data
        """
        from fastapi_admin_kit.db import get_db_session

        session = get_db_session(request)
        queryset = self.admin.get_queryset(session, request)

        # Apply search filter
        if q:
            from fastapi_admin_kit.search_utils import apply_search_filter

            search_fields = getattr(self.admin, "search_fields", None) or [
                "name",
                "title",
            ]
            from sqlalchemy import select

            queryset = apply_search_filter(
                select(self.registered.model),
                self.registered.model,
                search_fields,
                q,
            )
            # Execute the query
            queryset = session.all(queryset)

        return self.export(queryset, request)


class CSVImport(ImportBase):
    """Import data from CSV format.

    This is the default import format. It supports validation,
    transformation, and upsert operations.

    Usage::

        class ProductImport(CSVImport):
            required_columns = ["name", "price"]
            field_map = {"Product Name": "name", "Price": "price"}
            unique_key = "id"
    """

    def parse(self, file_content: bytes, request: Any = None) -> list[dict[str, Any]]:
        """Parse CSV file content and return list of row dictionaries.

        Args:
            file_content: Raw CSV file content as bytes
            request: Optional request object

        Returns:
            List of dictionaries, each representing a row
        """
        # Decode the content
        text = file_content.decode(self.encoding)

        # Parse CSV
        reader = csv.DictReader(io.StringIO(text))

        rows = []
        for row in reader:
            # Clean up row - strip whitespace from keys and values
            cleaned_row = {}
            for key, value in row.items():
                if key:
                    cleaned_key = key.strip()
                    cleaned_value = value.strip() if value else ""
                    cleaned_row[cleaned_key] = cleaned_value
            rows.append(cleaned_row)

        return rows

    def validate_row(self, row: dict[str, Any], index: int) -> tuple[bool, str | None]:
        """Validate a CSV row.

        Args:
            row: The row data as a dictionary
            index: The row number (0-based, excluding header)

        Returns:
            A tuple of (is_valid, error_message)
        """
        # Call parent validation first
        is_valid, error_msg = super().validate_row(row, index)
        if not is_valid:
            return is_valid, error_msg

        # Additional CSV-specific validation can be added here
        return True, None
