"""
Low-level pygame drawing helpers.

All functions are pure (no global state) and receive colours / surfaces as
arguments. This makes them independently testable and reusable across the
renderer and note-roll subsystems.
"""

from __future__ import annotations

import pygame

_GRAD_STEPS = 48  # Maximum colour bands used for gradient rendering


# ── Colour utilities ──────────────────────────────────────────────────────────

def lerp_color(
    c1: tuple[int, ...],
    c2: tuple[int, ...],
    t: float,
) -> tuple[int, ...]:
    """
    Linearly interpolate between two RGB(A) colours.

    Args:
        c1: Start colour (3 or 4 components).
        c2: End colour (must have the same number of components as *c1*).
        t:  Blend factor in [0, 1]; 0 → *c1*, 1 → *c2*.

    Returns:
        Blended colour as a tuple of integers.
    """
    return tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(len(c1)))


# ── Gradient drawing ──────────────────────────────────────────────────────────

def draw_gradient_rect(
    surf: pygame.Surface,
    rect: pygame.Rect,
    c_top: tuple[int, ...],
    c_btm: tuple[int, ...],
) -> None:
    """
    Fill *rect* on *surf* with a vertical linear gradient from *c_top* to *c_btm*.

    Args:
        surf:  Target surface.
        rect:  Destination rectangle.
        c_top: Colour at the top edge.
        c_btm: Colour at the bottom edge.
    """
    if rect.width <= 0 or rect.height <= 0:
        return
    steps  = min(_GRAD_STEPS, rect.height)
    step_h = rect.height / steps
    for i in range(steps):
        t     = i / max(steps - 1, 1)
        color = lerp_color(c_top, c_btm, t)
        y     = rect.y + int(i * step_h)
        h     = int((i + 1) * step_h) - int(i * step_h)
        pygame.draw.rect(surf, color, (rect.x, y, rect.width, max(h, 1)))


def draw_rounded_gradient(
    surf: pygame.Surface,
    rect: pygame.Rect,
    c_top: tuple[int, ...],
    c_btm: tuple[int, ...],
    radius: int = 6,
) -> None:
    """
    Draw a rounded-rectangle gradient on *surf*.

    Composites a gradient surface through a rounded-rect mask using
    ``BLEND_RGBA_MIN``.

    Args:
        surf:   Target surface.
        rect:   Destination rectangle.
        c_top:  Colour at the top edge.
        c_btm:  Colour at the bottom edge.
        radius: Corner radius in pixels.
    """
    if rect.width <= 0 or rect.height <= 0:
        return
    w, h = rect.width, rect.height
    tmp  = pygame.Surface((w, h), pygame.SRCALPHA)
    draw_gradient_rect(tmp, pygame.Rect(0, 0, w, h), c_top, c_btm)
    mask = pygame.Surface((w, h), pygame.SRCALPHA)
    mask.fill((0, 0, 0, 0))
    pygame.draw.rect(mask, (255, 255, 255, 255), (0, 0, w, h), border_radius=radius)
    tmp.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
    surf.blit(tmp, rect.topleft)


# ── Glow effect ───────────────────────────────────────────────────────────────

def draw_glow(
    surf: pygame.Surface,
    rect: pygame.Rect,
    color_rgba: tuple[int, int, int, int],
    layers: int = 5,
    spread: int = 8,
) -> None:
    """
    Draw a multi-layer rectangular glow around *rect*.

    Args:
        surf:       Target surface.
        rect:       Rectangle to glow around.
        color_rgba: Glow colour with alpha.
        layers:     Number of concentric glow bands.
        spread:     Total spread radius in pixels.
    """
    r, g, b, a = color_rgba
    gw, gh     = rect.width + spread * 2, rect.height + spread * 2
    glow       = pygame.Surface((gw, gh), pygame.SRCALPHA)
    for i in range(layers, 0, -1):
        alpha = int(a * (i / layers) ** 1.5)
        pad   = int(spread * (1 - i / layers))
        pygame.draw.rect(
            glow, (r, g, b, alpha),
            (pad, pad, gw - pad * 2, gh - pad * 2),
            border_radius=8,
        )
    surf.blit(glow, (rect.x - spread, rect.y - spread))


# ── Background ────────────────────────────────────────────────────────────────

def draw_background(surf: pygame.Surface, chassis: tuple, chassis_ridge: tuple) -> None:
    """
    Render the application background — a solid chassis fill with top/bottom ridges.

    Args:
        surf:          Target surface (typically the full screen).
        chassis:       Main chassis colour.
        chassis_ridge: Highlight ridge colour.
    """
    surf.fill(chassis)
    pygame.draw.rect(surf, chassis_ridge, (0, 0, surf.get_width(), 4))
    pygame.draw.rect(surf, chassis_ridge,
                     (0, surf.get_height() - 4, surf.get_width(), 4))


def load_bg_image(path: str) -> "Optional[pygame.Surface]":
    """
    Load a PNG or JPG image for use as background.

    Calls ``convert()`` for fast blitting only when a display surface exists.
    Falls back to the raw surface if the display is not yet initialised.

    Args:
        path: Absolute or relative path to the image file.

    Returns:
        A ``pygame.Surface``, or ``None`` on any error.
    """
    import os
    if not path or not os.path.isfile(path):
        return None
    try:
        img = pygame.image.load(path)
        # convert() requires an active display surface
        if pygame.display.get_surface() is not None:
            img = img.convert()
        return img
    except Exception as exc:
        print(f"[Background] failed to load '{path}': {exc}")
        return None


def scale_bg_image(
    img: pygame.Surface,
    target_w: int,
    target_h: int,
    fit_mode: str,
) -> pygame.Surface:
    """
    Scale *img* to fit *target_w* × *target_h* according to *fit_mode*.

    Modes
    -----
    ``"fill"``    — cover the full area, crop excess from centre (default).
    ``"fit"``     — fit inside, black bars on empty sides.
    ``"stretch"`` — stretch to exact size ignoring aspect ratio.
    ``"center"``  — no scaling, centre the image, crop or pad with black.
    ``"tile"``    — repeat the original image to fill the area.
    """
    iw, ih = img.get_size()
    # Use a regular (non-alpha) surface — avoids blending issues on all platforms.
    out = pygame.Surface((target_w, target_h))
    out.fill((0, 0, 0))

    mode = fit_mode.lower().strip()

    if mode == "stretch":
        scaled = pygame.transform.smoothscale(img, (target_w, target_h))
        out.blit(scaled, (0, 0))

    elif mode == "fit":
        ratio  = min(target_w / iw, target_h / ih)
        nw, nh = max(1, int(iw * ratio)), max(1, int(ih * ratio))
        scaled = pygame.transform.smoothscale(img, (nw, nh))
        out.blit(scaled, ((target_w - nw) // 2, (target_h - nh) // 2))

    elif mode == "center":
        ox = (target_w - iw) // 2
        oy = (target_h - ih) // 2
        out.blit(img, (ox, oy))

    elif mode == "tile":
        for ty in range(0, target_h, ih):
            for tx in range(0, target_w, iw):
                out.blit(img, (tx, ty))

    else:  # "fill"
        ratio  = max(target_w / iw, target_h / ih)
        nw, nh = max(1, int(iw * ratio)), max(1, int(ih * ratio))
        scaled = pygame.transform.smoothscale(img, (nw, nh))
        cx     = (nw - target_w) // 2
        cy     = (nh - target_h) // 2
        out.blit(scaled, (-cx, -cy))

    return out


def draw_background_image(
    surf: pygame.Surface,
    chassis: tuple,
    chassis_ridge: tuple,
    bg_image: "Optional[pygame.Surface]",
    opacity: int,
) -> None:
    """
    Render background: solid colour, optional image overlay, then ridges.

    Args:
        surf:          Target surface.
        chassis:       Solid fill colour shown when no image or opacity < 255.
        chassis_ridge: Thin ridge lines drawn on top.
        bg_image:      Pre-scaled surface (regular, non-alpha), or ``None``.
        opacity:       0-255 applied to the image (255 = fully opaque).
    """
    # 1. Solid colour base
    surf.fill(chassis)

    # 2. Image overlay
    if bg_image is not None:
        opacity = max(0, min(255, opacity))
        if opacity >= 255:
            surf.blit(bg_image, (0, 0))
        else:
            # Clone, apply alpha, blit
            tmp = bg_image.copy()
            tmp.set_alpha(opacity)
            surf.blit(tmp, (0, 0))

    # 3. Ridge lines on top
    w, h = surf.get_width(), surf.get_height()
    pygame.draw.rect(surf, chassis_ridge, (0, 0, w, 4))
    pygame.draw.rect(surf, chassis_ridge, (0, h - 4, w, 4))


# needed for type hint in load_bg_image without importing typing at top level
from typing import Optional  # noqa: E402