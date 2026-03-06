"""
Piano keyboard renderer.

Builds a list of :class:`KeyState` objects from a :class:`PianoConfig` and
draws the full 3-D keybed with press animations and glow effects.

All colour access goes through the injected :class:`ColorTheme` — no
reference to module-level colour globals.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

import pygame

from piano.config  import PianoConfig
from piano.theme   import ColorTheme
from piano.ui.drawing import (
    lerp_color,
    draw_gradient_rect,
    draw_rounded_gradient,
    draw_glow,
)

# ── Constants ─────────────────────────────────────────────────────────────────

WHITE_NOTES       = ["C", "D", "E", "F", "G", "A", "B"]
BLACK_AFTER_WHITE = [0, 1, 3, 4, 5]
BLACK_NOTE_NAMES  = ["C#", "D#", "F#", "G#", "A#"]

PRESS_ANIM_DUR  = 0.07   # seconds for the press animation to complete
SUBCONTRA_OCT   = -1     # sub-contra octave index used in display logic


# ── Key state ─────────────────────────────────────────────────────────────────

@dataclass
class KeyState:
    """Visual and logical state of a single piano key."""
    note:    str
    octave:  int
    kind:    str            # 'white' or 'black'
    rect:    pygame.Rect    = field(default_factory=pygame.Rect)
    pressed: bool           = False
    press_t: float          = 0.0


# ── Renderer ──────────────────────────────────────────────────────────────────

class PianoRenderer:
    """
    Builds and draws the piano keyboard.

    Parameters
    ----------
    config : PianoConfig
        Key dimensions derived from the scale factor.
    theme : ColorTheme
        All colours used during rendering.
    """

    def __init__(self, config: PianoConfig, theme: ColorTheme) -> None:
        self.cfg   = config
        self.theme = theme
        self.keys: list[KeyState] = []
        # O(1) lookup: (note, octave) → KeyState
        self._key_index: dict[tuple[str, int], KeyState] = {}
        # Cache gradient / highlight surfaces to avoid per-frame allocation
        self._grad_cache: dict[tuple, pygame.Surface] = {}
        self._hl_cache:   dict[tuple, pygame.Surface] = {}

    # ── Layout ────────────────────────────────────────────────────────────

    def build(self, x0: int, y0: int) -> None:
        """
        (Re)build the key list starting at pixel position (*x0*, *y0*).

        Handles two modes:
        - ``config.start_oct == 0`` — full keyboard with sub-contra octave.
        - ``config.start_oct > 0``  — reduced keyboard centred on octave 4.

        Args:
            x0: Left edge of the first white key.
            y0: Top edge of all keys.
        """
        self.keys = []
        cfg = self.cfg

        if cfg.start_oct == 0:
            self._build_full(x0, y0)
        else:
            self._build_partial(x0, y0)

        self._rebuild_index()

    def _build_full(self, x0: int, y0: int) -> None:
        """Full keyboard: sub-contra octave + 7 octaves + final C."""
        cfg = self.cfg
        oct_sc = SUBCONTRA_OCT

        # Sub-contra octave: A and B only
        for i, note in enumerate(["A", "B"]):
            r = pygame.Rect(x0 + i * cfg.step, y0, cfg.ww, cfg.wh)
            self.keys.append(KeyState(note, oct_sc, "white", r))
        bx = x0 + cfg.step - cfg.bw // 2
        self.keys.append(
            KeyState("A#", oct_sc, "black", pygame.Rect(bx, y0, cfg.bw, cfg.bh))
        )
        prefix_white = 2

        for oct in range(cfg.number_of_octaves):
            ox = x0 + (prefix_white + oct * 7) * cfg.step
            self._add_octave(ox, y0, oct)

        ox_last = x0 + (prefix_white + cfg.number_of_octaves * 7) * cfg.step
        self.keys.append(
            KeyState("C", cfg.number_of_octaves, "white",
                     pygame.Rect(ox_last, y0, cfg.ww, cfg.wh))
        )

    def _build_partial(self, x0: int, y0: int) -> None:
        """Partial keyboard: start_oct…start_oct+number_of_octaves + final C."""
        cfg = self.cfg
        for i, oct in enumerate(range(cfg.start_oct,
                                      cfg.start_oct + cfg.number_of_octaves)):
            ox = x0 + i * 7 * cfg.step
            self._add_octave(ox, y0, oct)

        ox_last  = x0 + cfg.number_of_octaves * 7 * cfg.step
        final_oct = cfg.start_oct + cfg.number_of_octaves
        self.keys.append(
            KeyState("C", final_oct, "white",
                     pygame.Rect(ox_last, y0, cfg.ww, cfg.wh))
        )

    def _add_octave(self, ox: int, y0: int, oct: int) -> None:
        """Append all 7 white and 5 black keys for one octave."""
        cfg = self.cfg
        for i, note in enumerate(WHITE_NOTES):
            r = pygame.Rect(ox + i * cfg.step, y0, cfg.ww, cfg.wh)
            self.keys.append(KeyState(note, oct, "white", r))
        for wi, note in zip(BLACK_AFTER_WHITE, BLACK_NOTE_NAMES):
            bx = ox + (wi + 1) * cfg.step - cfg.bw // 2
            self.keys.append(
                KeyState(note, oct, "black", pygame.Rect(bx, y0, cfg.bw, cfg.bh))
            )

    def _rebuild_index(self) -> None:
        """Rebuild the O(1) lookup index and clear surface caches."""
        self._key_index = {(k.note, k.octave): k for k in self.keys}
        self._grad_cache.clear()
        self._hl_cache.clear()

    # ── Dimensions ────────────────────────────────────────────────────────

    def total_width(self) -> int:
        """Total pixel width of the keyboard."""
        cfg = self.cfg
        if cfg.start_oct == 0:
            return (2 + cfg.number_of_octaves * 7 + 1) * cfg.step
        return (cfg.number_of_octaves * 7 + 1) * cfg.step

    def total_height(self) -> int:
        """Total pixel height of the keyboard (= white-key height)."""
        return self.cfg.wh

    # ── State mutation ────────────────────────────────────────────────────

    def set_pressed(self, note: str, octave: int, pressed: bool) -> None:
        """Toggle the pressed state of a key and record the press time."""
        key = self._key_index.get((note, octave))
        if key is not None:
            key.pressed = pressed
            if pressed:
                key.press_t = time.time()

    def get_key_at(self, pos: tuple[int, int]) -> Optional[KeyState]:
        """
        Return the key at screen position *pos*.

        Black keys take priority over white keys when they overlap.

        Args:
            pos: (x, y) pixel coordinates.
        """
        hit = None
        for key in self.keys:
            if key.rect.collidepoint(pos):
                if hit is None or key.kind == "black":
                    hit = key
        return hit

    # ── Drawing ───────────────────────────────────────────────────────────

    def draw(
        self,
        surf: pygame.Surface,
        font_note: pygame.font.Font,
        font_oct: pygame.font.Font,
    ) -> None:
        """
        Draw the full keyboard — white keys first, black keys on top.

        Args:
            surf:      Target surface (the screen).
            font_note: Font for note-name labels.
            font_oct:  Font for octave-number labels.
        """
        for key in self.keys:
            if key.kind == "white":
                self._draw_white(surf, key, font_note, font_oct)
        for key in self.keys:
            if key.kind == "black":
                self._draw_black(surf, key, font_note)

    def _anim(self, key: KeyState) -> float:
        """Return press-animation progress [0, 1] for *key*."""
        if not key.pressed:
            return 0.0
        return min((time.time() - key.press_t) / PRESS_ANIM_DUR, 1.0)

    def _draw_white(
        self,
        surf: pygame.Surface,
        key: KeyState,
        fn: pygame.font.Font,
        fo: pygame.font.Font,
    ) -> None:
        t     = self._anim(key)
        shift = int(t * 2)
        r     = key.rect.move(0, shift)
        th    = self.theme

        if key.pressed:
            draw_glow(surf, r, th.key_glow_white, layers=4, spread=5)

        body_top = lerp_color(th.white_key_top, th.white_pressed, t)
        body_btm = lerp_color(
            th.white_key_btm,
            lerp_color(th.white_pressed, (180, 240, 235), 0.4),
            t,
        )

        if t == 0.0:
            # Cache the idle gradient to avoid per-frame Surface allocation
            cache_key = ("wgrad", key.rect.width, key.rect.height)
            grad_surf = self._grad_cache.get(cache_key)
            if grad_surf is None:
                grad_surf = pygame.Surface(
                    (key.rect.width, key.rect.height), pygame.SRCALPHA
                )
                draw_gradient_rect(
                    grad_surf,
                    pygame.Rect(0, 0, key.rect.width, key.rect.height),
                    th.white_key_top, th.white_key_btm,
                )
                mask = pygame.Surface(
                    (key.rect.width, key.rect.height), pygame.SRCALPHA
                )
                mask.fill((0, 0, 0, 0))
                pygame.draw.rect(
                    mask, (255, 255, 255, 255),
                    (0, 0, key.rect.width, key.rect.height), border_radius=3,
                )
                grad_surf.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
                self._grad_cache[cache_key] = grad_surf
            surf.blit(grad_surf, r.topleft)
        else:
            draw_rounded_gradient(surf, r, body_top, body_btm, radius=3)

        pygame.draw.line(surf, th.white_key_side,
                         (r.right - 1, r.y + 3), (r.right - 1, r.bottom - 3))

        border_c = lerp_color(th.white_border, th.cyan, t * 0.6)
        pygame.draw.rect(surf, border_c, r, width=1, border_radius=3)

        note_c = th.cyan if key.pressed else th.text_color
        lbl    = fn.render(key.note, True, note_c)
        surf.blit(lbl, lbl.get_rect(centerx=r.centerx, bottom=r.bottom - 4))

        if key.note == "C":
            oct_label = str(key.octave)
            olbl = fo.render(oct_label, True,
                             th.cyan_dim if not key.pressed else th.cyan)
            surf.blit(olbl, olbl.get_rect(centerx=r.centerx, bottom=r.bottom - 13))

    def _draw_black(
        self,
        surf: pygame.Surface,
        key: KeyState,
        fn: pygame.font.Font,
    ) -> None:
        t     = self._anim(key)
        shift = int(t * 2)
        r     = key.rect.move(0, shift)
        th    = self.theme

        if key.pressed:
            draw_glow(surf, r, th.key_glow_black, layers=5, spread=6)

        body = lerp_color(th.black_key_clr, th.black_pressed, t)
        pygame.draw.rect(surf, body, r, border_radius=3)

        if not key.pressed:
            hl_w   = r.width - 4
            hl_h   = max(4, int(r.height * 0.15))
            hl_key = ("bhl", hl_w, hl_h)
            hl_s   = self._hl_cache.get(hl_key)
            if hl_s is None:
                hl_s = pygame.Surface((hl_w, hl_h), pygame.SRCALPHA)
                draw_gradient_rect(hl_s, pygame.Rect(0, 0, hl_w, hl_h),
                                   th.black_key_top, th.black_key_clr)
                self._hl_cache[hl_key] = hl_s
            surf.blit(hl_s, (r.x + 2, r.y + 2))

        if key.pressed:
            dot_r = 3
            pygame.draw.circle(surf, th.cyan,
                                (r.centerx, r.bottom - dot_r - 2), dot_r)

        note_c = th.cyan if key.pressed else th.text_color
        lbl    = fn.render(key.note, True, note_c)
        surf.blit(lbl, lbl.get_rect(centerx=r.centerx, bottom=r.bottom - 5))
