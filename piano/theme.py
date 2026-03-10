from __future__ import annotations

from dataclasses import dataclass

Color3 = tuple[int, int, int]
Color4 = tuple[int, int, int, int]


@dataclass
class ColorTheme:
    """
    Immutable colour palette for the Grand Piano UI.

    All fields carry sensible defaults so the theme can be constructed
    with ``ColorTheme()`` and then overridden selectively via
    :meth:`from_config`.
    """

    # ── Chassis / frame ────────────────────────────────────────────────────
    chassis:        Color3 = (38,  38,  40)
    chassis_light:  Color3 = (52,  52,  55)
    chassis_dark:   Color4 = (26,  26,  28)
    chassis_border: Color3 = (65,  65,  68)
    chassis_ridge:  Color3 = (22,  22,  24)

    # ── White keys ────────────────────────────────────────────────────────
    white_key_top:  Color3 = (240, 240, 238)
    white_key_btm:  Color3 = (210, 208, 205)
    white_key_side: Color3 = (170, 168, 165)
    white_pressed:  Color3 = (0,   220, 210)
    white_border:   Color3 = (140, 138, 135)

    # ── Black keys ────────────────────────────────────────────────────────
    black_key_clr:  Color3 = (42,  42,  44)
    black_key_top:  Color3 = (90,  90,  92)
    black_pressed:  Color3 = (0,   180, 165)

    # ── Accent / LED ──────────────────────────────────────────────────────
    cyan:           Color3 = (0,   220, 200)
    cyan_dim:       Color3 = (0,   120, 110)
    led_green:      Color3 = (80,  220, 80)

    # ── Text ──────────────────────────────────────────────────────────────
    white_text:     Color3 = (220, 220, 215)
    dim_text:       Color3 = (140, 138, 132)
    accent:         Color3 = (0,   220, 200)
    text_color:     Color3 = (110, 108, 104)

    # ── Glow overlays (RGBA) ──────────────────────────────────────────────
    key_glow_white: Color4 = (0,   220, 200, 70)
    key_glow_black: Color4 = (0,   200, 185, 90)

    # ── Note-roll bars ────────────────────────────────────────────────────
    note_white:     Color3 = (0,   200, 185)
    note_black:     Color3 = (0,   160, 150)
    note_white_dim: Color3 = (0,   80,  75)
    note_black_dim: Color3 = (0,   60,  55)

    # ──────────────────────────────────────────────────────────────────────

    @classmethod
    def from_config(cls, colors: dict) -> ColorTheme:
        """
        Build a :class:`ColorTheme` from the ``"colors"`` section of the
        application config dict.

        Unknown keys in *colors* are silently ignored so that partial
        config files still work correctly.

        Args:
            colors: Mapping of colour-key → RGB/RGBA list, as stored in
                    ``piano_config.json``.

        Returns:
            New :class:`ColorTheme` instance with overrides applied.
        """
        def _get(key: str, default):
            raw = colors.get(key)
            return tuple(raw) if raw is not None else default

        theme = cls()
        theme.chassis        = _get("chassis",        theme.chassis)
        theme.chassis_light  = _get("chassis_light",  theme.chassis_light)
        theme.chassis_dark   = _get("chassis_dark",   theme.chassis_dark)
        theme.chassis_border = _get("chassis_border", theme.chassis_border)
        theme.chassis_ridge  = _get("chassis_ridge",  theme.chassis_ridge)
        theme.white_key_top  = _get("white_key_top",  theme.white_key_top)
        theme.white_key_btm  = _get("white_key_btm",  theme.white_key_btm)
        theme.white_key_side = _get("white_key_side", theme.white_key_side)
        theme.white_pressed  = _get("white_pressed",  theme.white_pressed)
        theme.white_border   = _get("white_border",   theme.white_border)
        theme.black_key_clr  = _get("black_key_clr",  theme.black_key_clr)
        theme.black_key_top  = _get("black_key_top",  theme.black_key_top)
        theme.black_pressed  = _get("black_pressed",  theme.black_pressed)
        theme.cyan           = _get("cyan",           theme.cyan)
        theme.cyan_dim       = _get("cyan_dim",       theme.cyan_dim)
        theme.led_green      = _get("led_green",      theme.led_green)
        theme.white_text     = _get("white_text",     theme.white_text)
        theme.dim_text       = _get("dim_text",       theme.dim_text)
        theme.text_color     = _get("text_color",     theme.text_color)
        theme.key_glow_white = _get("key_glow_white", theme.key_glow_white)
        theme.key_glow_black = _get("key_glow_black", theme.key_glow_black)
        theme.note_white     = _get("note_white",     theme.note_white)
        theme.note_black     = _get("note_black",     theme.note_black)
        theme.note_white_dim = _get("note_white_dim", theme.note_white_dim)
        theme.note_black_dim = _get("note_black_dim", theme.note_black_dim)
        return theme

    def note_color(self, is_black: bool, dim: bool = False) -> Color3:
        """
        Return the correct note-bar colour for a key type.

        Args:
            is_black: ``True`` for black (sharp/flat) keys.
            dim:      ``True`` to return the dimmed (background) variant.
        """
        if is_black:
            return self.note_black_dim if dim else self.note_black
        return self.note_white_dim if dim else self.note_white
