"""
Note-roll subsystem.

NoteRoll    — records live keystrokes as falling rectangles.
PlaybackRoll — displays note bars from a loaded MidiFilePlayer (look-ahead view).

Both receive a :class:`ColorTheme` at construction — no global colour constants.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

import pygame

from piano.theme import ColorTheme


# ─────────────────────────────── NoteRoll ────────────────────────────────────

@dataclass
class FallingNote:
    """A single live-played note bar in the NoteRoll."""
    note:     str
    octave:   int
    x:        int
    width:    int
    is_black: bool
    start_t:  float
    end_t:    float = 0.0


class NoteRoll:
    """
    Renders live-played notes as falling coloured rectangles above the keyboard.

    Thread-safe: ``press`` / ``release`` may be called from any thread;
    ``draw`` is called from the main thread.

    Args:
        theme:      Colour palette used for note bars.
        roll_speed: Pixels per second at which bars travel upward.
    """

    def __init__(self, theme: ColorTheme, roll_speed: int = 220) -> None:
        self.theme      = theme
        self.roll_speed = roll_speed
        self.notes:  list[FallingNote] = []
        self._lock   = threading.Lock()

    def press(self, note: str, octave: int, key) -> None:
        """
        Start a new falling bar for (*note*, *octave*).

        If the note is already active (not yet released), it is forcibly
        closed first to prevent orphaned infinite-height bars.

        Args:
            note:   Note name, e.g. ``'C'`` or ``'F#'``.
            octave: Octave index.
            key:    :class:`~piano.ui.renderer.KeyState` instance
                    providing pixel position and width.
        """
        now = time.time()
        with self._lock:
            for fn in self.notes:
                if fn.note == note and fn.octave == octave and fn.end_t == 0.0:
                    fn.end_t = now
            self.notes.append(FallingNote(
                note=note, octave=octave,
                x=key.rect.centerx,
                width=max(key.rect.width - 2, 4),
                is_black=(key.kind == "black"),
                start_t=now,
            ))

    def release(self, note: str, octave: int) -> None:
        """
        Mark the most recent bar for (*note*, *octave*) as released.

        Args:
            note:   Note name.
            octave: Octave index.
        """
        now = time.time()
        with self._lock:
            for fn in self.notes:
                if fn.note == note and fn.octave == octave and fn.end_t == 0.0:
                    fn.end_t = now
                    break

    def draw(
        self, surf: pygame.Surface, roll_top: int, roll_bottom: int
    ) -> None:
        """
        Render all active and recently released note bars.

        Bars that have scrolled completely above *roll_top* are pruned.

        Args:
            surf:        Target surface (the screen).
            roll_top:    Top pixel boundary of the roll zone.
            roll_bottom: Bottom pixel boundary (immediately above the keyboard).
        """
        now    = time.time()
        zone_h = roll_bottom - roll_top
        alive  = []

        surf.set_clip(pygame.Rect(0, roll_top, surf.get_width(), zone_h))

        with self._lock:
            for fn in self.notes:
                elapsed = now - fn.start_t
                top_y   = roll_bottom - int(elapsed * self.roll_speed)

                if fn.end_t:
                    fly      = now - fn.end_t
                    bottom_y = roll_bottom - int(fly * self.roll_speed)
                else:
                    bottom_y = roll_bottom

                if bottom_y < roll_top:
                    continue   # fully above the clip zone — discard
                alive.append(fn)

                draw_y = max(top_y,    roll_top)
                draw_h = min(bottom_y, roll_bottom) - draw_y
                if draw_h <= 0:
                    continue

                color  = self.theme.note_color(fn.is_black)
                half_w = fn.width // 2
                r      = pygame.Rect(fn.x - half_w, draw_y, fn.width, draw_h)

                top_r    = 4 if top_y    >= roll_top    else 0
                bottom_r = 4 if bottom_y <= roll_bottom else 0
                pygame.draw.rect(
                    surf, color, r,
                    border_top_left_radius=top_r,
                    border_top_right_radius=top_r,
                    border_bottom_left_radius=bottom_r,
                    border_bottom_right_radius=bottom_r,
                )

            self.notes = alive

        surf.set_clip(None)

    def clear(self) -> None:
        """Remove all note bars (e.g. after a stop or reposition)."""
        with self._lock:
            self.notes.clear()


# ─────────────────────────────── PlaybackRoll ─────────────────────────────────

class PlaybackRoll:
    """
    Renders upcoming notes from a :class:`MidiFilePlayer` as a look-ahead roll.

    Notes scroll downward toward the keyboard and arrive exactly when the
    player fires the note-on callback. The look-ahead window is configurable.

    Args:
        player:     Active :class:`MidiFilePlayer` instance.
        theme:      Colour palette.
        look_ahead: Time window in seconds shown above the keyboard.
    """

    def __init__(self, player, theme: ColorTheme, look_ahead: float = 4.0) -> None:
        self.player     = player
        self.theme      = theme
        self.look_ahead = look_ahead

    def draw(
        self, surf: pygame.Surface, roll_top: int, roll_bottom: int
    ) -> None:
        """
        Draw look-ahead note bars for the current playback position.

        Args:
            surf:        Target surface.
            roll_top:    Top boundary of the roll area.
            roll_bottom: Bottom boundary (top of the keyboard).
        """
        player = self.player
        if not player.is_playing and not player.is_paused and player.elapsed() == 0:
            return

        elapsed = player.elapsed()
        zone_h  = roll_bottom - roll_top
        speed   = zone_h / self.look_ahead

        surf.set_clip(pygame.Rect(0, roll_top, surf.get_width(), zone_h))

        for n in player.notes:
            if n.x == 0:
                continue

            dt_start   = n.start_sec - elapsed
            dt_end     = (n.start_sec + n.duration) - elapsed
            bar_bottom = roll_bottom - int(dt_start * speed)
            bar_top    = roll_bottom - int(dt_end   * speed)
            bar_h      = bar_bottom - bar_top

            if bar_h < 1 or bar_top > roll_bottom or bar_bottom < roll_top:
                continue

            color  = self.theme.note_color(n.is_black)
            draw_y = max(bar_top,    roll_top)
            draw_h = min(bar_bottom, roll_bottom) - draw_y
            if draw_h <= 0:
                continue

            r        = pygame.Rect(n.x - n.width // 2, draw_y, n.width, draw_h)
            top_r    = 4 if bar_top    >= roll_top    else 0
            bottom_r = 4 if bar_bottom <= roll_bottom else 0
            pygame.draw.rect(
                surf, (*color, 220), r,
                border_top_left_radius=top_r,
                border_top_right_radius=top_r,
                border_bottom_left_radius=bottom_r,
                border_bottom_right_radius=bottom_r,
            )

        surf.set_clip(None)

    def active_notes(self) -> list[tuple[str, int]]:
        """Return (note, octave) pairs currently within the playback window."""
        elapsed = self.player.elapsed()
        return [
            (n.note, n.octave)
            for n in self.player.notes
            if n.start_sec <= elapsed < n.start_sec + n.duration
        ]
