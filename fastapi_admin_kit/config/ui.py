"""UI configuration."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi_admin_kit.config.theme import ThemeConfig


class UIConfig:
    """UI configuration — wraps ThemeConfig + component-level options."""

    def __init__(
        self,
        title: str = "FastAPI Admin Kit",
        logo_url: str | None = None,
        favicon_url: str | None = None,
        primary_color: str = "#0ea5e9",
        primary_color_dark: str = "#0284c7",
        dark_mode_default: bool = False,
        per_page_default: int = 25,
        # Theme
        theme: ThemeConfig | None = None,
        # Component config
        sidebar_style: str = "default",
        sidebar_show_icons: bool = True,
        sidebar_show_badges: bool = True,
        sidebar_group_style: str = "label",
        sidebar_position: str = "left",
        table_style: str = "default",
        table_hover_effect: bool = True,
        table_row_height: str = "normal",
        form_layout: str = "two-column",
        form_label_position: str = "top",
        form_spacing: str = "normal",
        form_card_style: bool = True,
        dashboard_grid: str = "auto",
        dashboard_card_style: str = "default",
        dashboard_stat_size: str = "normal",
        content_width: str = "default",
        topbar_style: str = "default",
        sticky_header: bool = True,
        # Custom injection
        custom_css: str = "",
        custom_css_url: str = "",
        custom_js: str = "",
        custom_js_url: str = "",
        # Feature toggles
        show_history: bool = True,
        show_view_on_site: bool = True,
        show_back_button: bool = False,
        environment_label: str | None = None,
        environment_color: str = "info",
        site_url: str = "/",
        site_symbol: str | None = None,
        login_background_url: str | None = None,
        # Mobile
        mobile_sidebar: str = "overlay",
        mobile_topbar_height: str = "48px",
        mobile_content_padding: str = "16px",
    ):
        self.title = title
        self.logo_url = logo_url
        self.favicon_url = favicon_url
        self.primary_color = primary_color
        self.primary_color_dark = primary_color_dark
        self.dark_mode_default = dark_mode_default
        self.per_page_default = per_page_default
        self.theme = theme
        self.sidebar_style = sidebar_style
        self.sidebar_show_icons = sidebar_show_icons
        self.sidebar_show_badges = sidebar_show_badges
        self.sidebar_group_style = sidebar_group_style
        self.sidebar_position = sidebar_position
        self.table_style = table_style
        self.table_hover_effect = table_hover_effect
        self.table_row_height = table_row_height
        self.form_layout = form_layout
        self.form_label_position = form_label_position
        self.form_spacing = form_spacing
        self.form_card_style = form_card_style
        self.dashboard_grid = dashboard_grid
        self.dashboard_card_style = dashboard_card_style
        self.dashboard_stat_size = dashboard_stat_size
        self.content_width = content_width
        self.topbar_style = topbar_style
        self.sticky_header = sticky_header
        self.custom_css = custom_css
        self.custom_css_url = custom_css_url
        self.custom_js = custom_js
        self.custom_js_url = custom_js_url
        self.show_history = show_history
        self.show_view_on_site = show_view_on_site
        self.show_back_button = show_back_button
        self.environment_label = environment_label
        self.environment_color = environment_color
        self.site_url = site_url
        self.site_symbol = site_symbol
        self.login_background_url = login_background_url
        self.mobile_sidebar = mobile_sidebar
        self.mobile_topbar_height = mobile_topbar_height
        self.mobile_content_padding = mobile_content_padding

    def apply_to_template_context(self) -> dict:
        """Apply UI configuration to template context."""
        ctx = {
            "title": self.title,
            "logo_url": self.logo_url,
            "favicon_url": self.favicon_url,
            "primary_color": self.primary_color,
            "primary_color_dark": self.primary_color_dark,
            "dark_mode_default": self.dark_mode_default,
            "per_page_default": self.per_page_default,
            "sidebar_style": self.sidebar_style,
            "sidebar_show_icons": self.sidebar_show_icons,
            "sidebar_show_badges": self.sidebar_show_badges,
            "sidebar_group_style": self.sidebar_group_style,
            "sidebar_position": self.sidebar_position,
            "table_style": self.table_style,
            "table_hover_effect": self.table_hover_effect,
            "table_row_height": self.table_row_height,
            "form_layout": self.form_layout,
            "form_label_position": self.form_label_position,
            "form_spacing": self.form_spacing,
            "form_card_style": self.form_card_style,
            "dashboard_grid": self.dashboard_grid,
            "dashboard_card_style": self.dashboard_card_style,
            "dashboard_stat_size": self.dashboard_stat_size,
            "content_width": self.content_width,
            "topbar_style": self.topbar_style,
            "sticky_header": self.sticky_header,
            "show_history": self.show_history,
            "show_view_on_site": self.show_view_on_site,
            "show_back_button": self.show_back_button,
            "environment_label": self.environment_label,
            "environment_color": self.environment_color,
            "site_url": self.site_url,
            "site_symbol": self.site_symbol,
            "login_background_url": self.login_background_url,
            "mobile_sidebar": self.mobile_sidebar,
            "mobile_topbar_height": self.mobile_topbar_height,
            "mobile_content_padding": self.mobile_content_padding,
        }
        if self.theme:
            ctx.update(self.theme.to_context())
        return ctx
