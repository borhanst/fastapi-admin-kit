"""CSV Import implementation."""

from __future__ import annotations

import csv
import io
from typing import Any

from fastapi_admin_kit.export_import.base import ImportBase


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
