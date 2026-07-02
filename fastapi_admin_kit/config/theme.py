"""Theme configuration — maps to CSS custom properties."""

from __future__ import annotations

PRESET_DEFAULTS: dict[str, dict[str, str]] = {
    "editorial": {
        "surface_base": "#FAF8F5",
        "surface_raised": "#FFFFFF",
        "text_primary": "#1C1917",
        "text_secondary": "#78716C",
        "border_color": "#E8E4DE",
        "primary_color": "#059669",
        "font_display": "'Instrument Serif', Georgia, serif",
        "font_body": "'DM Sans', system-ui, sans-serif",
        "font_mono": "'JetBrains Mono', monospace",
        "font_import_url": "https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=DM+Sans:ital,opsz,wght@0,9..40,300;0,9..40,400;0,9..40,500;0,9..40,600;1,9..40,400&family=JetBrains+Mono:wght@400;500&display=swap",
        "radius_sm": "3px",
        "radius_md": "5px",
        "radius_lg": "8px",
    },
    "modern": {
        "surface_base": "#F8FAFC",
        "surface_raised": "#FFFFFF",
        "text_primary": "#0F172A",
        "text_secondary": "#64748B",
        "border_color": "#E2E8F0",
        "primary_color": "#6366F1",
        "font_display": "'Inter', system-ui, sans-serif",
        "font_body": "'Inter', system-ui, sans-serif",
        "font_mono": "'JetBrains Mono', ui-monospace, monospace",
        "font_import_url": "https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap",
        "radius_sm": "6px",
        "radius_md": "8px",
        "radius_lg": "12px",
    },
    "midnight": {
        "surface_base": "#0B0F19",
        "surface_raised": "#151B2B",
        "text_primary": "#E2E8F0",
        "text_secondary": "#94A3B8",
        "border_color": "#2A3248",
        "primary_color": "#818CF8",
        "font_display": "'Inter', system-ui, sans-serif",
        "font_body": "'Inter', system-ui, sans-serif",
        "font_mono": "'JetBrains Mono', ui-monospace, monospace",
        "font_import_url": "https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap",
        "radius_sm": "4px",
        "radius_md": "6px",
        "radius_lg": "10px",
    },
    "paper": {
        "surface_base": "#FAF8F5",
        "surface_raised": "#FFFFFF",
        "text_primary": "#1C1917",
        "text_secondary": "#78716C",
        "border_color": "#E8E4DE",
        "primary_color": "#059669",
        "font_display": "'Instrument Serif', Georgia, serif",
        "font_body": "'DM Sans', system-ui, sans-serif",
        "font_mono": "'JetBrains Mono', monospace",
        "font_import_url": "https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=DM+Sans:ital,opsz,wght@0,9..40,300;0,9..40,400;0,9..40,500;0,9..40,600;1,9..40,400&family=JetBrains+Mono:wght@400;500&display=swap",
        "radius_sm": "3px",
        "radius_md": "5px",
        "radius_lg": "8px",
    },
    "forest": {
        "surface_base": "#F0FDF4",
        "surface_raised": "#FFFFFF",
        "text_primary": "#14532D",
        "text_secondary": "#166534",
        "border_color": "#BBF7D0",
        "primary_color": "#22C55E",
        "font_display": "'Instrument Serif', Georgia, serif",
        "font_body": "'DM Sans', system-ui, sans-serif",
        "font_mono": "'JetBrains Mono', monospace",
        "font_import_url": "https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=DM+Sans:ital,opsz,wght@0,9..40,300;0,9..40,400;0,9..40,500;0,9..40,600;1,9..40,400&family=JetBrains+Mono:wght@400;500&display=swap",
        "radius_sm": "4px",
        "radius_md": "6px",
        "radius_lg": "10px",
    },
    "minimal": {
        "surface_base": "#FFFFFF",
        "surface_raised": "#FFFFFF",
        "text_primary": "#171717",
        "text_secondary": "#737373",
        "border_color": "#E5E5E5",
        "primary_color": "#404040",
        "font_display": "'Inter', system-ui, sans-serif",
        "font_body": "'Inter', system-ui, sans-serif",
        "font_mono": "'JetBrains Mono', ui-monospace, monospace",
        "font_import_url": "https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap",
        "radius_sm": "0px",
        "radius_md": "0px",
        "radius_lg": "0px",
    },
}


class ThemeConfig:
    """Complete theme configuration — maps to CSS custom properties.

    When preset is set, its defaults are used. Any explicit attribute
    override takes precedence over the preset defaults.
    """

    def __init__(
        self,
        preset: str = "editorial",
        *,
        primary_color: str | None = None,
        surface_base: str | None = None,
        surface_raised: str | None = None,
        text_primary: str | None = None,
        text_secondary: str | None = None,
        border_color: str | None = None,
        font_display: str | None = None,
        font_body: str | None = None,
        font_mono: str | None = None,
        font_import_url: str | None = None,
        radius_sm: str | None = None,
        radius_md: str | None = None,
        radius_lg: str | None = None,
        shadow_sm: str | None = None,
        shadow_md: str | None = None,
        shadow_lg: str | None = None,
        topbar_height: str = "56px",
        sidebar_width: str = "248px",
        sidebar_collapsed_width: str = "60px",
        content_max_width: str = "1360px",
        content_padding: str = "32px",
        duration_fast: str = "100ms",
        duration_base: str = "180ms",
        duration_slow: str = "280ms",
        easing: str = "cubic-bezier(0.16, 1, 0.3, 1)",
        show_grain_texture: bool = True,
        show_accent_line: bool = True,
        compact_mode: bool = False,
    ):
        defaults = PRESET_DEFAULTS.get(preset, PRESET_DEFAULTS["editorial"])
        self.preset = preset
        self.primary_color = primary_color or defaults["primary_color"]
        self.surface_base = surface_base or defaults["surface_base"]
        self.surface_raised = surface_raised or defaults["surface_raised"]
        self.text_primary = text_primary or defaults["text_primary"]
        self.text_secondary = text_secondary or defaults["text_secondary"]
        self.border_color = border_color or defaults["border_color"]
        self.font_display = font_display or defaults["font_display"]
        self.font_body = font_body or defaults["font_body"]
        self.font_mono = font_mono or defaults["font_mono"]
        self.font_import_url = font_import_url or defaults["font_import_url"]
        self.radius_sm = radius_sm or defaults["radius_sm"]
        self.radius_md = radius_md or defaults["radius_md"]
        self.radius_lg = radius_lg or defaults["radius_lg"]
        self.shadow_sm = shadow_sm
        self.shadow_md = shadow_md
        self.shadow_lg = shadow_lg
        self.topbar_height = topbar_height
        self.sidebar_width = sidebar_width
        self.sidebar_collapsed_width = sidebar_collapsed_width
        self.content_max_width = content_max_width
        self.content_padding = content_padding
        self.duration_fast = duration_fast
        self.duration_base = duration_base
        self.duration_slow = duration_slow
        self.easing = easing
        self.show_grain_texture = show_grain_texture
        self.show_accent_line = show_accent_line
        self.compact_mode = compact_mode

    def to_css_variables(self) -> str:
        """Generate CSS :root{} block from config."""
        lines = [
            f"  --primary-500: {self.primary_color};",
            f"  --surface-base: {self.surface_base};",
            f"  --surface-raised: {self.surface_raised};",
            f"  --text-primary: {self.text_primary};",
            f"  --text-secondary: {self.text_secondary};",
            f"  --surface-border: {self.border_color};",
            f"  --font-display: {self.font_display};",
            f"  --font-body: {self.font_body};",
            f"  --font-mono: {self.font_mono};",
            f"  --topbar-height: {self.topbar_height};",
            f"  --sidebar-width: {self.sidebar_width};",
            f"  --sidebar-collapsed: {self.sidebar_collapsed_width};",
            f"  --content-max-width: {self.content_max_width};",
            f"  --content-padding: {self.content_padding};",
            f"  --radius-sm: {self.radius_sm};",
            f"  --radius-md: {self.radius_md};",
            f"  --radius-lg: {self.radius_lg};",
            f"  --duration-fast: {self.duration_fast};",
            f"  --duration-base: {self.duration_base};",
            f"  --duration-slow: {self.duration_slow};",
            f"  --easing-out: {self.easing};",
            f"  --admin-grain-opacity: {'0.025' if self.show_grain_texture else '0'};",
            f"  --admin-accent-line-opacity: {'0.4' if self.show_accent_line else '0'};",
        ]
        if self.shadow_sm:
            lines.append(f"  --shadow-sm: {self.shadow_sm};")
        if self.shadow_md:
            lines.append(f"  --shadow-md: {self.shadow_md};")
        if self.shadow_lg:
            lines.append(f"  --shadow-lg: {self.shadow_lg};")
        body = "\n".join(lines)
        return f":root {{\n{body}\n}}"

    def to_context(self) -> dict:
        """Return dict suitable for template context."""
        return {
            "theme": self,
            "theme_preset": self.preset,
            "theme_css": self.to_css_variables(),
            "theme_font_import_url": self.font_import_url,
            "theme_show_grain": self.show_grain_texture,
            "theme_show_accent_line": self.show_accent_line,
        }
