"""AdminExtra — per-model extra CSS and JS asset declarations."""

from __future__ import annotations

from typing import Any


class AdminExtra:
    """Per-model extra CSS and JS configuration.

    SRP: Only manages asset declarations. No rendering logic.

    Usage::

        class ProductAdmin(ModelAdmin):
            extra = AdminExtra(
                css=["css/product-admin.css"],
                js=["js/product-admin.js"],
                css_urls=["https://cdn.example.com/lib.css"],
                js_urls=["https://cdn.example.com/lib.js"],
                css_inline=".product-table { color: red; }",
                js_inline="console.log('product admin loaded');",
            )
    """

    def __init__(
        self,
        css: list[str] | None = None,
        js: list[str] | None = None,
        css_urls: list[str] | None = None,
        js_urls: list[str] | None = None,
        css_inline: str | None = None,
        js_inline: str | None = None,
    ):
        self.css = css or []
        self.js = js or []
        self.css_urls = css_urls or []
        self.js_urls = js_urls or []
        self.css_inline = css_inline
        self.js_inline = js_inline

    def get_css_urls(self, admin_path: str = "/admin") -> list[str]:
        """Return all CSS URLs (static + external)."""
        urls = []
        for path in self.css:
            urls.append(f"{admin_path}/static/{path.lstrip('/')}")
        urls.extend(self.css_urls)
        return urls

    def get_js_urls(self, admin_path: str = "/admin") -> list[str]:
        """Return all JS URLs (static + external)."""
        urls = []
        for path in self.js:
            urls.append(f"{admin_path}/static/{path.lstrip('/')}")
        urls.extend(self.js_urls)
        return urls

    def to_context(self, admin_path: str = "/admin") -> dict[str, Any]:
        """Convert to template context dict for base.html."""
        return {
            "extra_css": self.get_css_urls(admin_path),
            "extra_js": self.get_js_urls(admin_path),
            "extra_css_inline": self.css_inline,
            "extra_js_inline": self.js_inline,
        }
