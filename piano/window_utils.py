"""
OS-level window utilities.

Previously the SDL2 window helpers were duplicated as two nearly identical
inner functions inside ``main()``. Here they live once as a small module.
The tkinter focus-restoration pattern is also extracted and shared.
"""

from __future__ import annotations

from typing import Optional

import pygame


# ── SDL2 window helpers ───────────────────────────────────────────────────────

def get_window_rect() -> Optional[tuple[int, int, int, int]]:
    """
    Return ``(x, y, width, height)`` of the current OS window via
    ``pygame._sdl2``, or ``None`` if the API is unavailable.
    """
    try:
        from pygame._sdl2.video import Window as _SDLWindow  # type: ignore
        win  = _SDLWindow.from_display_module()
        x, y = win.position
        w, h = win.size
        return x, y, w, h
    except Exception:
        return None


def restore_pygame_focus() -> None:
    """
    Bring the pygame window to the foreground and give it keyboard/mouse focus.

    On Windows the standard SetForegroundWindow + SetFocus approach is used so
    that the *very first* click registers as an action rather than merely
    activating the window.  Falls back to the SDL2 API on other platforms.
    """
    # ── Windows: ctypes approach ──────────────────────────────────────────────
    try:
        import ctypes
        import os

        # Get the native HWND from the pygame window title
        hwnd = None

        # SDL2 exposes the HWND via WM_INFO
        info = pygame.display.get_wm_info()
        hwnd = info.get("window")

        if hwnd:
            user32 = ctypes.windll.user32
            # AttachThreadInput trick: attach our thread to the foreground
            # thread so SetForegroundWindow is guaranteed to work.
            fg_hwnd   = user32.GetForegroundWindow()
            cur_tid   = ctypes.windll.kernel32.GetCurrentThreadId()
            fg_tid    = user32.GetWindowThreadProcessId(fg_hwnd, None)
            if fg_tid and fg_tid != cur_tid:
                user32.AttachThreadInput(cur_tid, fg_tid, True)
                user32.SetForegroundWindow(hwnd)
                user32.SetFocus(hwnd)
                user32.AttachThreadInput(cur_tid, fg_tid, False)
            else:
                user32.SetForegroundWindow(hwnd)
                user32.SetFocus(hwnd)
            return
    except Exception:
        pass

    # ── Fallback: SDL2 API ────────────────────────────────────────────────────
    try:
        from pygame._sdl2.video import Window as _SDLWindow  # type: ignore
        _SDLWindow.from_display_module().focus()
    except Exception:
        pass