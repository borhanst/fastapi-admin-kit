"""Export and Import module for FastAPI Admin Kit."""

from fastapi_admin_kit.export_import.base import ExportBase, ImportBase
from fastapi_admin_kit.export_import.csv import CSVExport, CSVImport
from fastapi_admin_kit.export_import.registry import (
    get_export_class,
    get_import_class,
    register_export,
    register_import,
)

__all__ = [
    "ExportBase",
    "ImportBase",
    "CSVExport",
    "CSVImport",
    "register_export",
    "register_import",
    "get_export_class",
    "get_import_class",
]

try:
    from fastapi_admin_kit.export_import.excel import ExcelExport, ExcelImport

    __all__ += ["ExcelExport", "ExcelImport"]
except ImportError:
    pass
