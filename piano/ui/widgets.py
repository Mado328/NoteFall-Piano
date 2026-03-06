"""
Reusable UI widgets for the Grand Piano panel.

All widgets are plain Python classes with two methods:
  - ``handle(event) -> bool`` — process a pygame event, return True if changed.
  - ``draw(surf)``            — render onto *surf*.

Colours are received via a :class:`~piano.theme.ColorTheme` instance.
No references to module-level colour globals.
"""

from __future__ import annotations

import math
from typing import Optional

import pygame

from piano.theme import ColorTheme


# ── Lazy font initialisation ──────────────────────────────────────────────────

_WIDGET_LABEL_FONT: Optional[pygame.font.Font] = None


def _label_font() -> pygame.font.Font:
    """Return (and lazily initialise) the small widget-label font."""
    global _WIDGET_LABEL_FONT
    if _WIDGET_LABEL_FONT is None:
        _WIDGET_LABEL_FONT = pygame.font.Font(None, 15)
    return _WIDGET_LABEL_FONT


# ── IconButton ────────────────────────────────────────────────────────────────

class IconButton:
    """
    Small circular button with a single glyph (e.g. ``◄`` / ``►``).

    Args:
        cx, cy:  Centre coordinates.
        radius:  Hit radius in pixels.
        symbol:  Unicode glyph to render inside.
        font:    Font used for the symbol.
        theme:   Colour palette.
    """

    def __init__(
        self,
        cx: int, cy: int, radius: int,
        symbol: str,
        font: pygame.font.Font,
        theme: ColorTheme,
    ) -> None:
        self.cx     = cx
        self.cy     = cy
        self.r      = radius
        self.symbol = symbol
        self.font   = font
        self.theme  = theme
        self.hovered = False

    def draw(self, surf: pygame.Surface) -> None:
        th   = self.theme
        rect = pygame.Rect(self.cx - self.r, self.cy - self.r,
                           self.r * 2, self.r * 2)
        body = th.chassis_border if self.hovered else th.chassis
        bord = th.cyan           if self.hovered else th.chassis_border
        pygame.draw.rect(surf, body, rect, border_radius=3)
        pygame.draw.rect(surf, bord, rect, width=1, border_radius=3)
        lbl = self.font.render(
            self.symbol, True, th.cyan if self.hovered else th.dim_text
        )
        surf.blit(lbl, lbl.get_rect(center=(self.cx, self.cy)))

    def handle(self, event: pygame.event.Event) -> bool:
        """Return ``True`` if the button was clicked."""
        if event.type == pygame.MOUSEMOTION:
            self.hovered = (
                math.hypot(event.pos[0] - self.cx, event.pos[1] - self.cy) <= self.r
            )
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if math.hypot(event.pos[0] - self.cx, event.pos[1] - self.cy) <= self.r:
                return True
        return False


# ── PortSelector ─────────────────────────────────────────────────────────────

class PortSelector:
    """
    Horizontal scrolling selector for a list of port names.

    Left/right arrow buttons step through the *ports* list. The selected
    item is accessible via :attr:`current`.

    Args:
        x, y:    Top-left corner.
        w, h:    Widget dimensions.
        ports:   Ordered list of port-name strings.
        font:    Font for the port name label.
        font_sm: Smaller font used for the arrow buttons.
        theme:   Colour palette.
    """

    def __init__(
        self,
        x: int, y: int, w: int, h: int,
        ports: list[str],
        font: pygame.font.Font,
        font_sm: pygame.font.Font,
        theme: ColorTheme,
    ) -> None:
        self.rect  = pygame.Rect(x, y, w, h)
        self.ports = ports
        self.idx   = 0
        self.font  = font
        self.theme = theme
        br = h // 2 - 4
        self.bl = IconButton(x + br + 5,     y + h // 2, br, "◄", font_sm, theme)
        self.br = IconButton(x + w - br - 5, y + h // 2, br, "►", font_sm, theme)

    @property
    def current(self) -> str:
        """The currently selected port name, or ``'—'`` if the list is empty."""
        return self.ports[self.idx] if self.ports else "—"

    def handle(self, event: pygame.event.Event) -> bool:
        """Step left/right and return ``True`` when the selection changed."""
        changed = False
        if self.bl.handle(event):
            self.idx = (self.idx - 1) % len(self.ports)
            changed  = True
        if self.br.handle(event):
            self.idx = (self.idx + 1) % len(self.ports)
            changed  = True
        return changed

    def draw(self, surf: pygame.Surface) -> None:
        th = self.theme
        pygame.draw.rect(surf, th.chassis_dark, self.rect, border_radius=4)
        pygame.draw.rect(surf, th.chassis_border, self.rect, width=1, border_radius=4)

        lbl_t = _label_font().render("MIDI PORT", True, th.cyan_dim)
        surf.blit(lbl_t, lbl_t.get_rect(
            centerx=self.rect.centerx, y=self.rect.y + 4
        ))

        inner = pygame.Rect(
            self.rect.x + 34, self.rect.y,
            self.rect.width - 68, self.rect.height,
        )
        lbl = self.font.render(self.current, True, th.cyan)
        surf.blit(lbl, lbl.get_rect(center=inner.center))
        self.bl.draw(surf)
        self.br.draw(surf)


# ── ValueControl ─────────────────────────────────────────────────────────────

class ValueControl:
    """
    Numeric value selector with ``+`` / ``−`` buttons.

    Args:
        x, y:    Top-left corner.
        w, h:    Widget dimensions.
        label:   Static label shown above the value.
        value:   Initial value.
        mn, mx:  Inclusive value range.
        step:    Increment / decrement amount.
        fmt:     Python format string for the displayed value (e.g. ``'{:.2f}x'``).
        font:    Font for the value label.
        font_sm: Font for the ± buttons.
        theme:   Colour palette.
    """

    def __init__(
        self,
        x: int, y: int, w: int, h: int,
        label: str,
        value: float,
        mn: float, mx: float, step: float,
        fmt: str,
        font: pygame.font.Font,
        font_sm: pygame.font.Font,
        theme: ColorTheme,
    ) -> None:
        self.rect  = pygame.Rect(x, y, w, h)
        self.label = label
        self.value = value
        self.mn    = mn
        self.mx    = mx
        self.step  = step
        self.fmt   = fmt
        self.font  = font
        self.theme = theme
        br = h // 2 - 4
        self.bd = IconButton(x + br + 5,     y + h // 2, br, "−", font_sm, theme)
        self.bu = IconButton(x + w - br - 5, y + h // 2, br, "+", font_sm, theme)

    def handle(self, event: pygame.event.Event) -> bool:
        """Adjust the value and return ``True`` when it changed."""
        changed = False
        if self.bd.handle(event):
            self.value = round(max(self.mn, self.value - self.step), 4)
            changed    = True
        if self.bu.handle(event):
            self.value = round(min(self.mx, self.value + self.step), 4)
            changed    = True
        return changed

    def draw(self, surf: pygame.Surface) -> None:
        th = self.theme
        pygame.draw.rect(surf, th.chassis_dark, self.rect, border_radius=4)
        pygame.draw.rect(surf, th.chassis_border, self.rect, width=1, border_radius=4)

        lbl_s = _label_font().render(self.label, True, th.cyan_dim)
        surf.blit(lbl_s, lbl_s.get_rect(
            centerx=self.rect.centerx, y=self.rect.y + 4
        ))

        val_s = self.font.render(self.fmt.format(self.value), True, th.cyan)
        surf.blit(val_s, val_s.get_rect(center=self.rect.center).move(0, 6))
        self.bd.draw(surf)
        self.bu.draw(surf)


# ── FlatButton ────────────────────────────────────────────────────────────────

class FlatButton:
    """
    Simple rectangular toggle / momentary button.

    Supports an *active* state (e.g. for STOP / MUTE / REC buttons) and a
    hover highlight.

    Args:
        rect:         Bounding rectangle.
        label:        Button text.
        font:         Font for the label.
        theme:        Colour palette (used for hover/disabled states).
        color_active: Background colour when :attr:`active` is ``True``.
        color_idle:   Background colour in the default state.
    """

    def __init__(
        self,
        rect: pygame.Rect,
        label: str,
        font: pygame.font.Font,
        theme: ColorTheme,
        color_active: tuple = (0, 200, 185),
        color_idle:   tuple = (48, 48, 52),
    ) -> None:
        self.rect         = rect
        self.label        = label
        self.font         = font
        self.theme        = theme
        self.color_active = color_active
        self.color_idle   = color_idle
        self.hovered      = False
        self.active       = False

    def draw(self, surf: pygame.Surface) -> None:
        th  = self.theme
        bg  = self.color_active if (self.active or self.hovered) else self.color_idle
        bc  = self.color_active if self.active else th.chassis_border
        pygame.draw.rect(surf, bg, self.rect, border_radius=4)
        pygame.draw.rect(surf, bc, self.rect, width=1, border_radius=4)
        fg  = (
            th.chassis_dark if self.active
            else (th.white_text if self.hovered else th.dim_text)
        )
        lbl = self.font.render(self.label, True, fg)
        surf.blit(lbl, lbl.get_rect(center=self.rect.center))

    def handle(self, event: pygame.event.Event) -> bool:
        """Return ``True`` when the button is clicked."""
        if event.type == pygame.MOUSEMOTION:
            self.hovered = self.rect.collidepoint(event.pos)
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.rect.collidepoint(event.pos):
                return True
        return False
