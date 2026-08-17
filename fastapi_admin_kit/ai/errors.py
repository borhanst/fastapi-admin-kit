"""Error formatting helpers for AI tools and agents."""

from __future__ import annotations

import traceback


def error_detail(exc: BaseException, *, debug: bool = False) -> str:
    """Return a stable error message, or a full traceback when debug is on.

    Tools and agents use this so that, in non-debug mode, only a concise
    message is surfaced to the model, while ``debug=True`` exposes the full
    exception traceback for troubleshooting.
    """
    if debug:
        return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    return str(exc)
