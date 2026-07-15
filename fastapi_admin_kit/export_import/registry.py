"""Registry for export/import format classes."""

from __future__ import annotations

# Global registry for export/import formats
_EXPORT_REGISTRY: dict[str, type] = {}
_IMPORT_REGISTRY: dict[str, type] = {}


def register_export(name: str, format_class: type) -> None:
    """Register an export format class.

    Args:
        name: Format name (e.g., "csv", "excel")
        format_class: The export class to register
    """
    _EXPORT_REGISTRY[name.lower()] = format_class


def register_import(name: str, format_class: type) -> None:
    """Register an import format class.

    Args:
        name: Format name (e.g., "csv", "excel")
        format_class: The import class to register
    """
    _IMPORT_REGISTRY[name.lower()] = format_class


def get_export_class(name: str) -> type | None:
    """Get a registered export format class.

    Args:
        name: Format name (e.g., "csv", "excel")

    Returns:
        The export class or None if not registered
    """
    return _EXPORT_REGISTRY.get(name.lower())


def get_import_class(name: str) -> type | None:
    """Get a registered import format class.

    Args:
        name: Format name (e.g., "csv", "excel")

    Returns:
        The import class or None if not registered
    """
    return _IMPORT_REGISTRY.get(name.lower())


def get_available_export_formats() -> list[str]:
    """Get list of registered export format names."""
    return list(_EXPORT_REGISTRY.keys())


def get_available_import_formats() -> list[str]:
    """Get list of registered import format names."""
    return list(_IMPORT_REGISTRY.keys())


def _register_defaults() -> None:
    """Register default export/import formats."""
    from fastapi_admin_kit.export_import.csv_export import CSVExport
    from fastapi_admin_kit.export_import.csv_import import CSVImport

    register_export("csv", CSVExport)
    register_import("csv", CSVImport)

    # Try to register Excel formats if openpyxl is available
    try:
        from fastapi_admin_kit.export_import.excel import ExcelExport, ExcelImport

        register_export("excel", ExcelExport)
        register_import("excel", ExcelImport)
    except ImportError:
        pass


# Register defaults on module load
_register_defaults()
