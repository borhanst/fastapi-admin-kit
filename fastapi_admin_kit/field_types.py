"""Column type → widget name mapping."""

from __future__ import annotations

from sqlalchemy import (
    JSON,
    UUID,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    Time,
)
from sqlalchemy.types import TypeEngine

# Widget name constants
TEXT_INPUT = "text_input"
TEXTAREA = "textarea"
NUMBER_INPUT = "number_input"
TOGGLE = "toggle"
DATE_PICKER = "date_picker"
DATETIME_PICKER = "datetime_picker"
TIME_PICKER = "time_picker"
SELECT = "select"
JSON_EDITOR = "json_editor"
FILE_UPLOAD = "file_upload"
TAG_INPUT = "tag_input"
RELATION_PICKER = "relation_picker"
MULTI_RELATION_PICKER = "multi_relation_picker"


# SQLAlchemy type → widget name mapping
TYPE_WIDGET_MAP: dict[type[TypeEngine], str] = {
    String: TEXT_INPUT,
    Text: TEXTAREA,
    Integer: NUMBER_INPUT,
    BigInteger: NUMBER_INPUT,
    Float: NUMBER_INPUT,
    Numeric: NUMBER_INPUT,
    Boolean: TOGGLE,
    Date: DATE_PICKER,
    DateTime: DATETIME_PICKER,
    Time: TIME_PICKER,
    Enum: SELECT,
    JSON: JSON_EDITOR,
    LargeBinary: FILE_UPLOAD,
    UUID: TEXT_INPUT,
}


def get_widget_for_type(col_type: TypeEngine) -> str:
    """Map a SQLAlchemy column type to a widget name."""
    # Check for exact type match first
    for sa_type, widget in TYPE_WIDGET_MAP.items():
        if isinstance(col_type, sa_type):
            return widget

    # Check by class name for custom types
    type_name = type(col_type).__name__
    if "ARRAY" in type_name:
        return TAG_INPUT

    # Default fallback
    return TEXT_INPUT


def get_widget_for_column(column_meta) -> str:
    """Get the appropriate widget for a column, considering foreign keys."""
    from fastapi_admin_kit.inspection import ColumnMeta

    if isinstance(column_meta, ColumnMeta) and column_meta.is_foreign_key:
        return RELATION_PICKER

    return get_widget_for_type(column_meta.type)
