"""
Application configuration: loading, saving, and the PianoConfig value object.

Responsibilities:
  - Declare default config values in ONE place (``_DEFAULTS``).
  - Load / merge config from disk without touching global state.
  - Save config asynchronously so the main loop never blocks.
  - Expose :class:`PianoConfig` — the layout-geometry value object.
"""

from __future__ import annotations

import copy
import json
import os
import threading
from dataclasses import dataclass

CONFIG_PATH = "piano_config.json"

# ── Default values ────────────────────────────────────────────────────────────
_DEFAULTS: dict = {
    # UI / playback
    "scale":              1.5,
    "number_of_octaves":  7,
    "midi_output_port":   "—",
    "midi_input_port":    "—",
    "window_width":       1400,
    "window_height":      900,
    "is_muted":           False,
    "roll_speed":         220,
    "roll_look_ahead":    4.0,
    "fps":                60,
    "fullscreen":         False,
    "asio_mode":          False,
    "virtual_port_name":  "NoteFall Piano",
    "virtual_input_port_name": "NoteFall Piano IN",
    # Background image
    # "bg_image": "path/to/image.png",  ← set this key to use an image
    "bg_image":           "",           # empty = use solid colour
    "bg_fit":             "fill",       # "fill" | "fit" | "stretch" | "center" | "tile"
    "bg_opacity":         255,          # 0-255, 255 = fully opaque
    "panel_pinned":       True,         # False = auto-hide panel
    # Action hotkeys — pygame key names (e.g. "space", "f5", "return")
    "hotkey_play":        "f5",
    "hotkey_pause":       "f6",
    "hotkey_record":      "f9",
    # Colour overrides (RGB lists); merged on top of ColorTheme defaults
    "colors": {
        "chassis":          [38,  38,  40],
        "chassis_light":    [52,  52,  55],
        "chassis_dark":     [26,  26,  28],
        "chassis_border":   [65,  65,  68],
        "chassis_ridge":    [22,  22,  24],
        "white_key_top":    [240, 240, 238],
        "white_key_btm":    [210, 208, 205],
        "white_key_side":   [170, 168, 165],
        "white_pressed":    [0,   220, 210],
        "white_border":     [140, 138, 135],
        "black_key_clr":    [42,  42,  44],
        "black_key_top":    [90,  90,  92],
        "black_pressed":    [0,   180, 165],
        "cyan":             [0,   220, 200],
        "cyan_dim":         [0,   120, 110],
        "led_green":        [80,  220, 80],
        "white_text":       [220, 220, 215],
        "dim_text":         [140, 138, 132],
        "text_color":       [110, 108, 104],
        "key_glow_white":   [0,   220, 200, 70],
        "key_glow_black":   [0,   200, 185, 90],
        "note_white":       [0,   200, 185],
        "note_black":       [0,   160, 150],
        "note_white_dim":   [0,   80,  75],
        "note_black_dim":   [0,   60,  55],
    },
}


# ── Public API ────────────────────────────────────────────────────────────────

def load_config() -> dict:
    """
    Load config from *piano_config.json*, falling back to built-in defaults.

    The ``"colors"`` sub-dict is merged separately so partial colour
    overrides don't wipe the defaults for unmentioned keys.

    Returns:
        Fully-populated config dictionary.
    """
    cfg = copy.deepcopy(_DEFAULTS)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            colors_override = data.pop("colors", {})
            cfg.update(data)
            cfg["colors"].update(colors_override)
        except Exception as exc:
            print(f"[config] load failed: {exc}")
    return cfg


def save_config(cfg: dict) -> None:
    """
    Asynchronously persist *cfg* to disk without blocking the main loop.

    A deep copy is taken immediately so subsequent mutations to *cfg* in
    the caller do not race with the background write.

    Args:
        cfg: Current application configuration dictionary.
    """
    snapshot = copy.deepcopy(cfg)

    def _write() -> None:
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
                json.dump(snapshot, fh, ensure_ascii=False, indent=2)
        except Exception as exc:
            print(f"[config] save failed: {exc}")

    threading.Thread(target=_write, daemon=True).start()


# ── Value object ──────────────────────────────────────────────────────────────

@dataclass
class PianoConfig:
    """
    Physical layout geometry of piano keys, derived from a single *scale* factor.

    All raw measurements (``white_base_w`` etc.) are in virtual pixels at
    scale 1.0. The computed properties (``ww``, ``bw``, …) return the
    actual pixel sizes for the current scale.
    """

    scale:             float = 1.5
    number_of_octaves: int   = 7
    start_oct:         int   = 0      # first displayed octave (0 = full keyboard)
    white_base_w:      float = 23.6
    black_base_w:      float = 12.7
    white_base_h:      float = 145
    black_base_h:      float = 100
    spacing:           float = 1.1

    @property
    def ww(self) -> int:
        """White-key width in pixels."""
        return int(self.white_base_w * self.scale)

    @property
    def bw(self) -> int:
        """Black-key width in pixels."""
        return int(self.black_base_w * self.scale)

    @property
    def wh(self) -> int:
        """White-key height in pixels."""
        return int(self.white_base_h * self.scale)

    @property
    def bh(self) -> int:
        """Black-key height in pixels."""
        return int(self.black_base_h * self.scale)

    @property
    def sp(self) -> int:
        """Inter-key spacing in pixels (minimum 1)."""
        return max(1, int(self.spacing * self.scale))

    @property
    def step(self) -> int:
        """Horizontal stride from one white key to the next."""
        return self.ww + self.sp