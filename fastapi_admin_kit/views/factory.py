"""View factories — deprecated. Use class-based views instead.

Backward-compatible factory functions are in:
- fastapi_admin_kit.views.list  (list_view_factory)
- fastapi_admin_kit.views.form   (create_form_factory, etc.)
- fastapi_admin_kit.views.delete (delete_factory)
- fastapi_admin_kit.views.bulk   (bulk_factory)
- fastapi_admin_kit.views.search (search_factory)

The ViewFactory class has been removed. Route everything through
class-based views (ListView, CreateView, EditView, DeleteView, BulkView).
"""

from __future__ import annotations
