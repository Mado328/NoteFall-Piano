"""
Application — the top-level orchestrator that replaces the God ``main()`` function.

Responsibilities (each in its own method):
  - ``__init__``          : dependency wiring
  - ``_init_display``     : pygame window creation
  - ``_create_widgets``   : panel widget layout
  - ``_reposition``       : keyboard layout recalculation after resize
  - ``run``               : main event loop
  - ``_handle_*``         : one method per event category
  - ``_render``           : full-frame draw

State that was previously scattered across mutable list-cells (``[None]``,
``[False]``) and closure variables is now plain instance attributes.
"""

from __future__ import annotations

import os
import time
import tkinter
import tkinter.filedialog
from typing import Optional

import mido
import pygame
import pygame.midi

from piano.config         import PianoConfig, load_config, save_config
from piano.theme          import ColorTheme
from piano.midi.output    import IMidiOutput, create_midi_output
from piano.midi.subsystems import (
    VirtualMidiPort, VirtualMidiInput, MidiInputListener, MidiRecorder,
    MidiFilePlayer, MIDI_NOTE_ON, MIDI_NOTE_OFF,
    check_and_offer_driver_install,
)
from piano.ui.drawing     import (
    draw_background, draw_background_image, load_bg_image, scale_bg_image,
)
from piano.ui.renderer    import PianoRenderer
from piano.ui.note_roll   import NoteRoll, PlaybackRoll
from piano.ui.widgets     import FlatButton, PortSelector, ValueControl
from piano.keyboard_map   import WHITE_KEY_MAP, BLACK_KEY_MAP
from piano.settings_window import SettingsWindow
from piano.window_utils   import get_window_rect, restore_pygame_focus

# UI geometry constants
PANEL_H   = 96
ROLL_MIN_H = 420


class Application:
    """
    Grand Piano application lifecycle manager.

    Instantiate once, then call :meth:`run`. All mutable state lives here
    as typed instance attributes instead of closure cells.
    """

    # ── Construction ──────────────────────────────────────────────────────────

    def __init__(self) -> None:
        # Check for teVirtualMIDI driver before initialising pygame.
        # Tkinter dialogs work independently of pygame; calling this after
        # pygame.init() can cause window-focus issues on Windows.
        check_and_offer_driver_install()

        pygame.init()

        self._cfg        = load_config()
        self.theme       = ColorTheme.from_config(self._cfg["colors"])
        self.fps: int    = self._cfg["fps"]
        self.roll_speed: int = self._cfg["roll_speed"]

        self.piano_cfg = PianoConfig(
            scale=self._cfg["scale"],
            number_of_octaves=self._cfg["number_of_octaves"],
        )

        # ── MIDI subsystems ─────────────────────────────────────────────
        self.midi_out:    IMidiOutput       = create_midi_output()
        self.midi_in:     MidiInputListener = MidiInputListener()
        self.recorder:    MidiRecorder      = MidiRecorder()
        self.file_player: MidiFilePlayer    = MidiFilePlayer()

        # Virtual port — create BEFORE enumerating ports so it appears in
        # the OUTPUT list immediately.
        # Notes reach it only when explicitly selected as OUTPUT.
        # Writing is done via the teVirtualMIDI DLL directly (not PortMidi),
        # which is the only reliable method on Windows.
        vport_name        = self._cfg.get("virtual_port_name", "Grand Piano")
        viport_name       = self._cfg.get("virtual_input_port_name", "Grand Piano IN")
        self.virtual_port  = VirtualMidiPort()
        self.virtual_iport = VirtualMidiInput()

        out_ok = self.virtual_port.open(vport_name)
        in_ok  = self.virtual_iport.open(viport_name)

        self.midi_out.set_virtual_port(vport_name, self.virtual_port)

        # ── Fonts ────────────────────────────────────────────────────────
        self.font_ui    = self._load_font(["Segoe UI", "Ubuntu", "Noto Sans"], 15)
        self.font_sm    = self._load_font(["Segoe UI", "Ubuntu", "Noto Sans"], 13)
        self.font_note  = self._load_font(["Segoe UI", "Ubuntu"], 11)
        self.font_oct   = self._load_font(["Segoe UI", "Ubuntu"], 10)

        # ── Renderer / roll ──────────────────────────────────────────────
        self.renderer    = PianoRenderer(self.piano_cfg, self.theme)
        self.note_roll   = NoteRoll(self.theme, roll_speed=self.roll_speed)
        self.playback_roll = PlaybackRoll(
            self.file_player, self.theme,
            look_ahead=self._cfg["roll_look_ahead"],
        )

        # ── Port lists ───────────────────────────────────────────────────
        self.port_list  = ["—"] + self.midi_out.output_names()

        # INPUT list: our virtual input port first, then real hardware ports.
        # Exclude:
        #   - the virtual OUTPUT port ("Grand Piano") — prevents feedback loop
        #   - the system-visible name of the virtual INPUT port — it appears in
        #     mido.get_input_names() but we control it via DLL, not mido
        real_inputs = [
            n for n in mido.get_input_names()
            if n != vport_name
            and not n.startswith(vport_name + " ")
            and n != viport_name
            and not n.startswith(viport_name + " ")
        ]
        virtual_inputs = [viport_name] if self.virtual_iport.is_open else []
        self.iport_list = ["—"] + virtual_inputs + real_inputs

        # ── Application state ────────────────────────────────────────────
        self.is_muted:      bool                        = self._cfg["is_muted"]
        self.is_fullscreen: bool                        = self._cfg.get("fullscreen", False)
        self.file_label:    str                         = "нет файла"
        self.pressed_keys:  set[tuple[int, bool]]       = set()
        self.mouse_key:     Optional[object]            = None  # KeyState | None
        self.bg_cache:      Optional[pygame.Surface]    = None

        # Panel auto-hide animation
        # _panel_offset: 0 = fully visible, -PANEL_H = fully hidden
        self._panel_offset:  float = 0.0
        self._panel_pinned:  bool  = self._cfg.get("panel_pinned", True)
        self._panel_visible: bool  = True   # logical target state

        # Background image state
        self._bg_raw:     Optional[pygame.Surface] = None  # original loaded pixels
        self._bg_scaled:  Optional[pygame.Surface] = None  # scaled to current size
        self._bg_path:    str  = self._cfg.get("bg_image", "")
        self._bg_fit:     str  = self._cfg.get("bg_fit", "fill")
        self._bg_opacity: int  = self._cfg.get("bg_opacity", 255)
        if self._bg_path:
            self._bg_raw = load_bg_image(self._bg_path)
        self.clock = pygame.time.Clock()

        # Widgets (populated in _create_widgets)
        self.port_sel:   Optional[PortSelector]  = None
        self.iport_sel:  Optional[PortSelector]  = None
        self.ctrl_scale: Optional[ValueControl]  = None
        self.btn_load:   Optional[FlatButton]    = None
        self.btn_play:   Optional[FlatButton]    = None
        self.btn_pause:  Optional[FlatButton]    = None
        self.btn_mute:   Optional[FlatButton]    = None
        self.btn_record: Optional[FlatButton]    = None
        self.btn_bg:       Optional[FlatButton]  = None
        self.btn_pin:      Optional[FlatButton]  = None
        self.btn_settings: Optional[FlatButton]  = None
        self._settings_win: Optional[object]     = None  # SettingsWindow instance

        # Cached render surfaces for dynamic labels
        self._rec_lbl_cache: Optional[tuple]    = None
        self._fn_surf_cache:  Optional[tuple]   = None

        # Static label surfaces (pre-rendered once)
        th = self.theme
        self.surf_out_lbl = self.font_sm.render("OUTPUT",    True, th.cyan_dim)
        self.surf_inp_lbl = self.font_sm.render("INPUT",     True, th.cyan_dim)
        self.surf_scl_lbl = self.font_sm.render("МАСШТАБ",   True, th.cyan_dim)
        self.surf_fle_lbl = self.font_sm.render("MIDI ФАЙЛ", True, th.cyan_dim)

        # Tkinter root — initialised once; repeated Tk() calls are expensive
        self._tk_root = tkinter.Tk()
        self._tk_root.withdraw()

        self._init_display()

        # Convert image to display format now that the display surface exists.
        # (convert() fails if called before pygame.display.set_mode())
        if self._bg_raw is not None:
            try:
                self._bg_raw = self._bg_raw.convert()
            except Exception:
                pass

        self._rebuild()
        self._restore_ports()
        restore_pygame_focus()

    # ── Display initialisation ────────────────────────────────────────────────

    def _init_display(self) -> None:
        """Create (or re-create) the pygame window."""
        # Make the first click both activate the window AND register as input.
        # Without this Windows swallows the activating click (click-to-focus).
        os.environ["SDL_MOUSE_FOCUS_CLICKTHROUGH"] = "1"

        cfg = self._cfg
        saved_wx = cfg.get("_window_x")
        saved_wy = cfg.get("_window_y")
        if not self.is_fullscreen and saved_wx is not None and saved_wy is not None:
            os.environ["SDL_VIDEO_WINDOW_POS"] = f"{saved_wx},{saved_wy}"

        if self.is_fullscreen:
            pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        else:
            pygame.display.set_mode(
                (cfg["window_width"], cfg["window_height"]), pygame.RESIZABLE
            )
        os.environ.pop("SDL_VIDEO_WINDOW_POS", None)
        pygame.display.set_caption("Grand Piano")

    # ── Layout helpers ────────────────────────────────────────────────────────

    def _piano_x(self) -> int:
        sw = pygame.display.get_surface().get_width()
        return max(10, (sw - self.renderer.total_width()) // 2)

    def _piano_y(self) -> int:
        sh = pygame.display.get_surface().get_height()
        return sh - self.renderer.total_height() - 8

    def _calc_octaves(self) -> None:
        """Fit the number of octaves to the current window width."""
        sw        = pygame.display.get_surface().get_width()
        available = sw - 20
        step      = self.piano_cfg.step
        full_w    = (2 + 7 * 7 + 1) * step

        if available >= full_w:
            self.piano_cfg.number_of_octaves = 7
            self.piano_cfg.start_oct         = 0
        else:
            n = max(1, (available - step) // (7 * step))
            self.piano_cfg.number_of_octaves = n
            center = 4
            start  = center - (n - 1) // 2
            self.piano_cfg.start_oct = max(0, min(7 - n, start))

    def _reposition(self) -> None:
        """Recalculate octave count, rebuild keys, attach file player."""
        self._calc_octaves()
        self.renderer.build(self._piano_x(), self._piano_y())
        self.file_player.attach_keys(self.renderer.keys)
        self.note_roll.clear()

    def _rebuild(self) -> None:
        """Resize window if necessary, then reposition and recreate widgets."""
        cur = pygame.display.get_surface()
        sw  = cur.get_width()  if cur else self._cfg["window_width"]
        sh  = cur.get_height() if cur else self._cfg["window_height"]
        min_h = PANEL_H + ROLL_MIN_H + self.renderer.total_height() + 20
        ph    = max(sh, min_h)
        if not self.is_fullscreen:
            pygame.display.set_mode((sw, ph), pygame.RESIZABLE)
        self._reposition()
        self._create_widgets()

    # ── Widget creation ───────────────────────────────────────────────────────

    def _create_widgets(self) -> None:
        """Instantiate all panel widgets at their computed positions."""
        th      = self.theme
        wy, wh  = 20, 52
        ps_x, ps_w  = 10,  300
        ip_x, ip_w  = ps_x + ps_w + 6,        200
        sc_x, sc_w  = ip_x + ip_w + 6,        180
        bl_x, bl_w  = sc_x + sc_w + 10,        90
        bp_x, bp_w  = bl_x + bl_w + 4,         90
        bpa_x, bpa_w = bp_x + bp_w + 4,        90
        bm_x, bm_w  = bpa_x + bpa_w + 4,       80
        br_x, br_w  = bm_x + bm_w + 10,        90
        bbg_x, bbg_w = br_x + br_w + 10,       80
        bst_x, bst_w = bbg_x + bbg_w + 6,      90

        self.port_sel  = PortSelector(ps_x, wy, ps_w, wh, self.port_list,
                                      self.font_ui, self.font_sm, th)
        self.iport_sel = PortSelector(ip_x, wy, ip_w, wh, self.iport_list,
                                      self.font_ui, self.font_sm, th)
        self.ctrl_scale = ValueControl(
            sc_x, wy, sc_w, wh,
            "МАСШТАБ", self.piano_cfg.scale, 0.75, 2.5, 0.25,
            "{:.2f}x", self.font_ui, self.font_sm, th,
        )
        self.btn_load   = FlatButton(pygame.Rect(bl_x,  wy, bl_w,  wh), "ОТКРЫТЬ",  self.font_sm, th)
        self.btn_play   = FlatButton(pygame.Rect(bp_x,  wy, bp_w,  wh), "► СТАРТ",  self.font_sm, th)
        self.btn_pause  = FlatButton(pygame.Rect(bpa_x, wy, bpa_w, wh), "■ ПАУЗА",  self.font_sm, th,
                                     color_active=(160, 130, 0))
        self.btn_mute   = FlatButton(
            pygame.Rect(bm_x, wy, bm_w, wh),
            "■ МУТ" if self.is_muted else "► ЗВУК",
            self.font_sm, th, color_active=(180, 60, 60),
        )
        self.btn_mute.active = self.is_muted
        self.btn_record = FlatButton(pygame.Rect(br_x, wy, br_w, wh), "● ЗАПИСЬ",
                                     self.font_sm, th, color_active=(200, 40, 40))
        self.btn_record.active = self.recorder.is_recording

        bg_label = "СБРОС ФОНА" if self._bg_raw is not None else "ФОН..."
        self.btn_bg = FlatButton(
            pygame.Rect(bbg_x, wy, bbg_w, wh), bg_label,
            self.font_sm, th, color_active=(60, 100, 160),
        )
        self.btn_bg.active = self._bg_raw is not None

        self.btn_settings = FlatButton(
            pygame.Rect(bst_x, wy, bst_w, wh), "⚙ НАСТРОЙКИ",
            self.font_sm, th,
        )

        # Pin button — small, top-right corner of the panel
        pin_sz = 24
        sw_cur = pygame.display.get_surface().get_width()
        self.btn_pin = FlatButton(
            pygame.Rect(sw_cur - pin_sz - 4, 4, pin_sz, pin_sz),
            "📌", self.font_sm, th, color_active=(200, 160, 0),
        )
        self.btn_pin.active = self._panel_pinned

        if self.file_player.is_playing:
            self.btn_play.label  = "■ СТОП"
            self.btn_play.active = True
        if self.file_player.is_paused:
            self.btn_pause.active = True

        # Restore widget port indices from saved state
        if hasattr(self, "_saved_port_idx"):
            self.port_sel.idx  = self._saved_port_idx
            self.iport_sel.idx = self._saved_iport_idx

    # ── Port restoration on startup ───────────────────────────────────────────

    def _restore_ports(self) -> None:
        """Re-open MIDI ports from the saved configuration."""
        saved_out = self._cfg["midi_output_port"]
        saved_in  = self._cfg["midi_input_port"]

        if saved_out in self.port_list:
            idx = self.port_list.index(saved_out)
            self.port_sel.idx   = idx
            self._saved_port_idx = idx
            self.midi_out.open_by_name(saved_out)

        if saved_in in self.iport_list:
            idx = self.iport_list.index(saved_in)
            self.iport_sel.idx    = idx
            self._saved_iport_idx = idx
            if saved_in == self.virtual_iport.name:
                self.virtual_iport.enabled = True
            else:
                self.midi_in.set_port(saved_in)

    # ── Main loop ─────────────────────────────────────────────────────────────

    def run(self) -> None:
        """Enter the main event loop. Returns when the window is closed."""
        # Pump one frame first so the window is fully visible before we
        # steal focus — otherwise SetForegroundWindow may be ignored by Windows.
        self._render()
        pygame.display.flip()
        restore_pygame_focus()
        while True:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self._shutdown()
                    return
                self._dispatch(event)

            # Pump Tkinter events only while the settings window is open.
            # Calling update() every frame causes Tkinter to steal focus.
            if self._settings_win is not None:
                try:
                    if self._settings_win._win.winfo_exists():
                        self._tk_root.update()
                    else:
                        self._settings_win = None
                except Exception:
                    self._settings_win = None

            self._render()
            self.clock.tick(self.fps)

    # ── Event dispatch ────────────────────────────────────────────────────────

    def _dispatch(self, event: pygame.event.Event) -> None:
        """Route a single pygame event to the appropriate handler."""
        if event.type == pygame.VIDEORESIZE:
            self.bg_cache = None
            self._reposition()

        # Translate screen pos → panel-local pos (compensate for slide offset)
        panel_bottom = PANEL_H + int(self._panel_offset)

        # Always update hover state for all widgets
        if event.type == pygame.MOUSEMOTION:
            panel_event = self._panel_event(event)
            for w in self._all_widgets():
                w.handle(panel_event)
            # Glissando: LMB held + cursor moved to a different key
            if self.mouse_key and event.pos[1] > panel_bottom:
                key = self.renderer.get_key_at(event.pos)
                if key and (key.note, key.octave) != (self.mouse_key.note, self.mouse_key.octave):
                    self._note_off(self.mouse_key.note, self.mouse_key.octave)
                    self.recorder.note_off(self.mouse_key.note, self.mouse_key.octave)
                    vel = self._vel_from_pos(key, event.pos[1])
                    self.mouse_key = key
                    self._note_on(key.note, key.octave, vel)
                    self.recorder.note_on(key.note, key.octave)

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self._handle_click(self._panel_event(event))

        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self._handle_mouse_up()

        if event.type == pygame.KEYDOWN:
            self._handle_keydown(event)

        if event.type == pygame.KEYUP:
            self._handle_keyup(event)

        if event.type == MIDI_NOTE_ON:
            vel = getattr(event, "velocity", 80)
            self._note_on(event.note, event.octave, vel)
            self.recorder.note_on(event.note, event.octave, vel)

        if event.type == MIDI_NOTE_OFF:
            self._note_off(event.note, event.octave)
            self.recorder.note_off(event.note, event.octave)

    def _panel_event(self, event: pygame.event.Event) -> pygame.event.Event:
        """
        Return a copy of *event* with pos.y shifted by -_panel_offset so
        widget hit-testing (which uses panel-local coordinates) works correctly
        while the panel is sliding.
        """
        o  = int(self._panel_offset)
        ox, oy = event.pos
        new_pos = (ox, oy - o)
        return pygame.event.Event(event.type, {**event.__dict__, "pos": new_pos})

    def _all_widgets(self):
        """Yield all non-None panel widgets for uniform hover handling."""
        for w in (self.port_sel, self.iport_sel, self.ctrl_scale,
                  self.btn_load, self.btn_play, self.btn_pause,
                  self.btn_mute, self.btn_record, self.btn_bg,
                  self.btn_settings, self.btn_pin):
            if w is not None:
                yield w

    # ── Click handler ─────────────────────────────────────────────────────────

    def _handle_click(self, event: pygame.event.Event) -> None:
        """Process a left-mouse-button-down event against all widgets."""
        if self.port_sel and self.port_sel.handle(event):
            self._cfg["midi_output_port"] = self.port_sel.current
            save_config(self._cfg)
            self.midi_out.open_by_name(self.port_sel.current)

        if self.iport_sel and self.iport_sel.handle(event):
            name = self.iport_sel.current
            self._cfg["midi_input_port"] = name
            save_config(self._cfg)
            if name == self.virtual_iport.name:
                # Virtual input port — enable DLL callback, close any mido port.
                self.virtual_iport.enabled = True
                self.midi_in.set_port("—")
            else:
                # Real port or "—" — disable virtual input, open via mido.
                self.virtual_iport.enabled = False
                self.midi_in.set_port(name)

        if self.ctrl_scale and self.ctrl_scale.handle(event):
            self.piano_cfg.scale     = self.ctrl_scale.value
            self._cfg["scale"]       = self.piano_cfg.scale
            save_config(self._cfg)
            self._rebuild()

        if self.btn_load and self.btn_load.rect.collidepoint(event.pos):
            self._open_file_dialog()
        if self.btn_play and self.btn_play.rect.collidepoint(event.pos):
            self._toggle_playback()
        if self.btn_pause and self.btn_pause.rect.collidepoint(event.pos):
            self._toggle_pause()
        if self.btn_mute and self.btn_mute.rect.collidepoint(event.pos):
            self._toggle_mute()
        if self.btn_record and self.btn_record.rect.collidepoint(event.pos):
            self._toggle_record()
        if self.btn_bg and self.btn_bg.rect.collidepoint(event.pos):
            self._pick_bg_image()
        if self.btn_settings and self.btn_settings.rect.collidepoint(event.pos):
            self._open_settings()
        if self.btn_pin and self.btn_pin.rect.collidepoint(event.pos):
            self._toggle_panel_pin()

        # Piano key click — use original (screen) pos, not panel-shifted
        panel_bottom = PANEL_H + int(self._panel_offset)
        orig_pos = pygame.mouse.get_pos()
        if orig_pos[1] > panel_bottom:
            key = self.renderer.get_key_at(orig_pos)
            if key:
                vel = self._vel_from_pos(key, orig_pos[1])
                self.mouse_key = key
                self._note_on(key.note, key.octave, vel)
                self.recorder.note_on(key.note, key.octave)

    def _handle_mouse_up(self) -> None:
        if self.mouse_key:
            key = self.mouse_key
            self._note_off(key.note, key.octave)
            self.recorder.note_off(key.note, key.octave)
            self.mouse_key = None

    # ── Keyboard handler ──────────────────────────────────────────────────────

    def _handle_keydown(self, event: pygame.event.Event) -> None:
        if event.key == pygame.K_F11:
            self._toggle_fullscreen()
            return

        shift  = bool(event.mod & pygame.KMOD_SHIFT)
        km     = BLACK_KEY_MAP if shift else WHITE_KEY_MAP
        pk_id  = (event.key, shift)
        if event.key in km and pk_id not in self.pressed_keys:
            self.pressed_keys.add(pk_id)
            note, oct = km[event.key]
            self._note_on(note, oct)
            self.recorder.note_on(note, oct)

    def _handle_keyup(self, event: pygame.event.Event) -> None:
        for shift in (False, True):
            pk_id = (event.key, shift)
            if pk_id in self.pressed_keys:
                self.pressed_keys.discard(pk_id)
                km = BLACK_KEY_MAP if shift else WHITE_KEY_MAP
                if event.key in km:
                    note, oct = km[event.key]
                    self._note_off(note, oct)
                    self.recorder.note_off(note, oct)

    # ── Note on / off primitives ──────────────────────────────────────────────

    def _vel_from_pos(self, key, pos_y: int) -> int:
        """
        Calculate MIDI velocity (1–127) from the Y position within a key.

        Clicking near the top of the key → soft (low velocity).
        Clicking near the bottom            → loud (high velocity).
        This mimics how a real piano responds to keystrike speed/position.
        """
        top = key.rect.top
        h   = max(key.rect.height, 1)
        t   = max(0.0, min(1.0, (pos_y - top) / h))
        return max(1, int(1 + t * 126))   # range 1-127

    def _note_on(self, note: str, octave: int, vel: int = 80) -> None:
        """Activate a note: update renderer, play audio, feed note roll."""
        self.renderer.set_pressed(note, octave, True)
        if not self.is_muted:
            self.midi_out.play(note, octave, vel)
        key = self.renderer._key_index.get((note, octave))
        if key:
            self.note_roll.press(note, octave, key)

    def _note_off(self, note: str, octave: int) -> None:
        """Deactivate a note: update renderer, stop audio, release note roll."""
        self.renderer.set_pressed(note, octave, False)
        if not self.is_muted:
            self.midi_out.stop(note, octave)
        self.note_roll.release(note, octave)

    # ── UI action handlers ────────────────────────────────────────────────────

    def _toggle_fullscreen(self) -> None:
        self.is_fullscreen = not self.is_fullscreen
        if self.is_fullscreen:
            pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        else:
            rect = get_window_rect()
            w = rect[2] if rect else self._cfg["window_width"]
            h = rect[3] if rect else self._cfg["window_height"]
            pygame.display.set_mode((w, h), pygame.RESIZABLE)
        self.bg_cache = None
        self._reposition()
        self._create_widgets()


    def _open_settings(self) -> None:
        """Open the settings window (non-blocking)."""
        try:
            self._settings_win = SettingsWindow(
                parent_root=self._tk_root,
                cfg=self._cfg,
                white_map=WHITE_KEY_MAP,
                black_map=BLACK_KEY_MAP,
                on_apply=self._apply_settings,
            )
            self._tk_root.update()
        except Exception as exc:
            import traceback
            traceback.print_exc()
            print(f"[Settings] failed to open: {exc}")

    def _apply_settings(self, new_cfg: dict, new_wmap: dict, new_bmap: dict) -> None:
        """Callback invoked by SettingsWindow when the user clicks Apply/OK."""
        WHITE_KEY_MAP.clear()
        WHITE_KEY_MAP.update(new_wmap)
        BLACK_KEY_MAP.clear()
        BLACK_KEY_MAP.update(new_bmap)

        needs_rebuild = (
            new_cfg.get("scale")             != self._cfg.get("scale") or
            new_cfg.get("number_of_octaves") != self._cfg.get("number_of_octaves")
        )
        needs_theme = new_cfg.get("colors") != self._cfg.get("colors")

        self._cfg.update(new_cfg)
        self._cfg["colors"].update(new_cfg.get("colors", {}))

        self._panel_pinned  = bool(self._cfg.get("panel_pinned", True))
        self.roll_speed     = self._cfg.get("roll_speed", 220)
        self.note_roll.speed = self.roll_speed
        self.fps            = int(self._cfg.get("fps", 60))
        self._bg_opacity    = int(self._cfg.get("bg_opacity", 255))
        self.bg_cache       = None

        if needs_theme:
            self.theme    = ColorTheme(self._cfg["colors"])
            self.bg_cache = None

        if needs_rebuild:
            self.piano_cfg.scale             = float(self._cfg["scale"])
            self.piano_cfg.number_of_octaves = int(self._cfg["number_of_octaves"])
            self._rebuild()

        save_config(self._cfg)
        restore_pygame_focus()

    def _toggle_panel_pin(self) -> None:
        self._panel_pinned = not self._panel_pinned
        self._cfg["panel_pinned"] = self._panel_pinned
        save_config(self._cfg)
        if self.btn_pin:
            self.btn_pin.active = self._panel_pinned

    def _toggle_mute(self) -> None:
        self.is_muted = not self.is_muted
        if self.btn_mute:
            self.btn_mute.active = self.is_muted
            self.btn_mute.label  = "■ МУТ" if self.is_muted else "► ЗВУК"
        if self.is_muted:
            self.midi_out.all_notes_off()

    def _toggle_playback(self) -> None:
        if self.file_player.is_playing:
            # сначала глушим колбэки — loop-поток перестаёт спавнить треды
            self.file_player.on_note_on  = None
            self.file_player.on_note_off = None
            self.file_player.stop()
            self.midi_out.all_notes_off()
            for k in self.renderer.keys:
                k.pressed = False
            self.btn_play.label   = "► СТАРТ"
            self.btn_play.active  = False
            self.btn_pause.active = False
            self.btn_pause.label  = '■ ПАУЗА'
        else:
            if self.file_player.notes:
                def _finished():
                    self.btn_play.label  = "► СТАРТ"
                    self.btn_play.active = False
                self.file_player.on_finished = _finished
                def _on_note_on(n, o):
                    self.renderer.set_pressed(n, o, True)
                    if not self.is_muted:
                        self.midi_out.play(n, o)
                def _on_note_off(n, o):
                    self.renderer.set_pressed(n, o, False)
                    if not self.is_muted:
                        self.midi_out.stop(n, o)
                self.file_player.on_note_on  = _on_note_on
                self.file_player.on_note_off = _on_note_off
                self.file_player.play()
                self.btn_play.label   = "■ СТОП"
                self.btn_play.active  = True
                self.btn_pause.active = False
                self.btn_pause.label  = '■ ПАУЗА'

    def _toggle_record(self) -> None:
        if not self.recorder.is_recording:
            self.recorder.start()
            self.note_roll.clear()
            if self.btn_record:
                self.btn_record.active = True
                self.btn_record.label  = "■ СТОП"
        else:
            self.recorder.stop()
            if self.btn_record:
                self.btn_record.active = False
                self.btn_record.label  = "● ЗАПИСЬ"
            self._save_recording_dialog()
        pygame.event.clear([pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP])

    def _save_recording_dialog(self) -> None:
        self._tk_root.attributes("-topmost", True)
        fp = tkinter.filedialog.asksaveasfilename(
            parent=self._tk_root,
            title="Сохранить запись",
            defaultextension=".mid",
            filetypes=[("MIDI files", "*.mid"), ("All files", "*.*")],
        )
        self._tk_root.attributes("-topmost", False)
        self._tk_root.withdraw()
        restore_pygame_focus()
        pygame.event.clear([pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP])
        if fp:
            self.recorder.save(fp)

    def _open_file_dialog(self) -> None:
        self._tk_root.attributes("-topmost", True)
        fp = tkinter.filedialog.askopenfilename(
            parent=self._tk_root,
            title="Открыть MIDI файл",
            filetypes=[("MIDI files", "*.mid *.midi"), ("All files", "*.*")],
        )
        self._tk_root.attributes("-topmost", False)
        self._tk_root.withdraw()
        restore_pygame_focus()
        pygame.event.clear([pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP])
        if fp:
            self.file_player.stop()
            if self.file_player.load(fp):
                self.file_player.attach_keys(self.renderer.keys)
                self.file_label = os.path.basename(fp)
                if self.btn_play:
                    self.btn_play.label  = "► СТАРТ"
                    self.btn_play.active = False
            else:
                self.file_label = "ошибка загрузки"

    def _pick_bg_image(self) -> None:
        """
        Open a file dialog to choose a background image (PNG/JPG).
        If an image is already set, clear it instead (toggle behaviour).
        """
        if self._bg_raw is not None:
            # Clear the current background
            self._bg_raw    = None
            self._bg_scaled = None
            self._bg_path   = ""
            self._cfg["bg_image"] = ""
            save_config(self._cfg)
            self.bg_cache = None
            if self.btn_bg:
                self.btn_bg.label  = "ФОН..."
                self.btn_bg.active = False
            return

        self._tk_root.attributes("-topmost", True)
        fp = tkinter.filedialog.askopenfilename(
            parent=self._tk_root,
            title="Выбрать изображение фона",
            filetypes=[
                ("Изображения", "*.png *.jpg *.jpeg *.bmp *.gif *.tga *.webp"),
                ("PNG", "*.png"),
                ("JPEG", "*.jpg *.jpeg"),
                ("Все файлы", "*.*"),
            ],
        )
        self._tk_root.attributes("-topmost", False)
        self._tk_root.withdraw()
        restore_pygame_focus()
        pygame.event.clear([pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP])

        if not fp:
            return

        img = load_bg_image(fp)
        if img is None:
            return

        self._bg_raw    = img
        self._bg_scaled = None   # will be re-scaled on next render
        self._bg_path   = fp
        self._cfg["bg_image"] = fp
        save_config(self._cfg)
        self.bg_cache = None

        if self.btn_bg:
            self.btn_bg.label  = "СБРОС ФОНА"
            self.btn_bg.active = True


        if self.file_player.is_playing:
            self.file_player.on_note_on  = None
            self.file_player.on_note_off = None
            self.file_player.stop()
            self.midi_out.all_notes_off()
            for k in self.renderer.keys:
                k.pressed = False
            if self.btn_play:
                self.btn_play.label  = "► СТАРТ"
                self.btn_play.active = False
            if self.btn_pause:
                self.btn_pause.active = False
                self.btn_pause.label  = "■ ПАУЗА"
        elif self.file_player.notes:
            def _on_finished():
                if self.btn_play:
                    self.btn_play.label  = "► СТАРТ"
                    self.btn_play.active = False

            def _on_note_on(note: str, octave: int) -> None:
                self.renderer.set_pressed(note, octave, True)
                if not self.is_muted:
                    self.midi_out.play(note, octave)

            def _on_note_off(note: str, octave: int) -> None:
                self.renderer.set_pressed(note, octave, False)
                if not self.is_muted:
                    self.midi_out.stop(note, octave)

            self.file_player.on_note_on  = _on_note_on
            self.file_player.on_note_off = _on_note_off
            self.file_player.on_finished = _on_finished
            self.file_player.play()
            if self.btn_play:
                self.btn_play.label  = "■ СТОП"
                self.btn_play.active = True
            if self.btn_pause:
                self.btn_pause.active = False
                self.btn_pause.label  = "■ ПАУЗА"

    def _toggle_pause(self) -> None:
        fp = self.file_player
        if fp.is_playing:
            fp.pause()
            self.midi_out.all_notes_off()
            for k in self.renderer.keys:
                k.pressed = False
            if self.btn_pause:
                self.btn_pause.active = True
                self.btn_pause.label  = "▶ ПРОДОЛЖ"
        elif fp.is_paused:
            fp.play()
            if self.btn_pause:
                self.btn_pause.active = False
                self.btn_pause.label  = "■ ПАУЗА"

    # ── Rendering ─────────────────────────────────────────────────────────────

    def _render(self) -> None:
        """Draw a complete frame onto the display surface."""
        screen   = pygame.display.get_surface()
        sw, sh   = screen.get_size()
        th       = self.theme

        # Background (cached until window size changes or image changes)
        if self.bg_cache is None or self.bg_cache.get_size() != (sw, sh):
            # Re-scale image if size changed or not yet scaled
            if self._bg_raw is not None:
                if (self._bg_scaled is None or
                        self._bg_scaled.get_size() != (sw, sh)):
                    self._bg_scaled = scale_bg_image(
                        self._bg_raw, sw, sh, self._bg_fit
                    )
            else:
                self._bg_scaled = None

            bg = pygame.Surface((sw, sh))
            draw_background_image(
                bg, th.chassis, th.chassis_ridge,
                self._bg_scaled, self._bg_opacity,
            )
            self.bg_cache = bg
        screen.blit(self.bg_cache, (0, 0))

        # ── Panel auto-hide animation ─────────────────────────────────────
        mx, my = pygame.mouse.get_pos()
        panel_bottom = PANEL_H + int(self._panel_offset)
        # Show trigger: mouse in top 6px strip or inside visible panel area
        if self._panel_pinned or my <= 6 or (self._panel_visible and my <= panel_bottom):
            self._panel_visible = True
        else:
            self._panel_visible = False

        target_offset = 0.0 if self._panel_visible else float(-PANEL_H)
        # Lerp toward target (speed: ~8 panel-heights per second at 60 fps)
        dt           = self.clock.get_time() / 1000.0
        speed        = PANEL_H * 8 * dt
        diff         = target_offset - self._panel_offset
        if abs(diff) <= speed:
            self._panel_offset = target_offset
        else:
            self._panel_offset += speed * (1 if diff > 0 else -1)
        panel_offset_i = int(self._panel_offset)   # integer pixels for blit

        py       = self._piano_y()
        roll_top = PANEL_H + panel_offset_i + 2
        roll_bot = py

        self._render_panel(screen, sw, panel_offset_i)
        self._render_roll_area(screen, sw, roll_top, roll_bot)
        self._render_keyboard(screen, py)

        # Trigger zone hint when panel is hidden
        if not self._panel_visible and self._panel_offset <= -PANEL_H + 2:
            hint = pygame.Surface((sw, 3), pygame.SRCALPHA)
            hint.fill((0, 200, 185, 80))
            screen.blit(hint, (0, 0))

        pygame.display.flip()

    def _render_panel(self, screen: pygame.Surface, sw: int, offset: int = 0) -> None:
        """Draw the top control panel, shifted vertically by *offset* pixels."""
        th = self.theme
        o  = offset  # shorthand

        # Render all panel content onto a temporary surface, then blit with offset.
        # This avoids having to add `o` to every individual blit coordinate.
        panel_surf = pygame.Surface((sw, PANEL_H))
        panel_surf.fill(th.chassis_light)
        pygame.draw.line(panel_surf, th.chassis_ridge,  (0, 0),          (sw, 0),          3)
        pygame.draw.line(panel_surf, th.chassis_border, (0, PANEL_H - 3), (sw, PANEL_H - 3), 1)
        pygame.draw.line(panel_surf, th.cyan,           (0, PANEL_H - 1), (sw, PANEL_H - 1), 2)

        # Dynamic "ЗАПИСЬ" label (cached by recording state)
        rec_state = self.recorder.is_recording
        if self._rec_lbl_cache is None or self._rec_lbl_cache[0] != rec_state:
            color = (200, 40, 40) if rec_state else th.cyan_dim
            self._rec_lbl_cache = (rec_state, self.font_sm.render("ЗАПИСЬ", True, color))
        surf_rec = self._rec_lbl_cache[1]

        # Dynamic filename label (cached by label + playing state)
        fn_key = (self.file_label, self.file_player.is_playing)
        if self._fn_surf_cache is None or self._fn_surf_cache[0] != fn_key:
            color = th.cyan if self.file_player.is_playing else th.cyan_dim
            self._fn_surf_cache = (fn_key, self.font_sm.render(self.file_label, True, color))
        fn_surf = self._fn_surf_cache[1]

        ps = self.port_sel.rect;  ip = self.iport_sel.rect
        sc = self.ctrl_scale.rect; bl = self.btn_load.rect
        bp = self.btn_play.rect;  br = self.btn_record.rect

        panel_surf.blit(self.surf_out_lbl,
                        self.surf_out_lbl.get_rect(centerx=ps.centerx, bottom=ps.y - 2))
        panel_surf.blit(self.surf_inp_lbl,
                        self.surf_inp_lbl.get_rect(centerx=ip.centerx, bottom=ip.y - 2))
        panel_surf.blit(self.surf_scl_lbl,
                        self.surf_scl_lbl.get_rect(centerx=sc.centerx, bottom=sc.y - 2))
        panel_surf.blit(self.surf_fle_lbl,
                        self.surf_fle_lbl.get_rect(
                            centerx=(bl.centerx + bp.centerx) // 2, bottom=bl.y - 2))
        panel_surf.blit(surf_rec,
                        surf_rec.get_rect(centerx=br.centerx, bottom=br.y - 2))

        for w in self._all_widgets():
            w.draw(panel_surf)

        panel_surf.blit(fn_surf, fn_surf.get_rect(
            centerx=(bl.x + bp.right) // 2, top=bl.bottom + 2))

        screen.blit(panel_surf, (0, o))

    def _render_roll_area(
        self, screen: pygame.Surface, sw: int, roll_top: int, roll_bot: int
    ) -> None:
        """Draw the note-roll zone, grid lines, and progress bar."""
        th = self.theme

        # Fill roll background only when there is no background image —
        # otherwise the image (already blitted as bg_cache) shows through.
        if self._bg_raw is None:
            pygame.draw.rect(screen, th.chassis_dark, (0, roll_top, sw, roll_bot - roll_top))
            #Octave dividers
            for k in self.renderer.keys:
                if k.note == "C" and k.kind == "white":
                    pygame.draw.line(screen, th.chassis_border,
                                    (k.rect.x, roll_top), (k.rect.x, roll_bot), 1)

        pygame.draw.line(screen, th.cyan, (0, roll_bot), (sw, roll_bot), 2)

        self.playback_roll.draw(screen, roll_top, roll_bot)
        self.note_roll.draw(screen, roll_top, roll_bot)

        # Playback progress bar
        fp = self.file_player
        if fp.notes and fp.duration > 0:
            pbar_h   = 4
            pbar_y   = roll_bot - pbar_h - 1
            pbar_w   = sw - 2
            progress = min(fp.elapsed() / fp.duration, 1.0)
            pygame.draw.rect(screen, th.chassis_border, (1, pbar_y, pbar_w, pbar_h))
            pygame.draw.rect(screen, th.cyan,
                             (1, pbar_y, int(pbar_w * progress), pbar_h))

    def _render_keyboard(self, screen: pygame.Surface, piano_y: int) -> None:
        """Draw the chassis frame and all piano keys."""
        th  = self.theme
        sw  = screen.get_width()
        pygame.draw.rect(screen, th.chassis,
                         (0, piano_y - 6, sw, self.renderer.total_height() + 10))
        pygame.draw.line(screen, th.chassis_border,
                         (0, piano_y - 6), (sw, piano_y - 6), 1)
        self.renderer.draw(screen, self.font_note, self.font_oct)

    # ── Shutdown ──────────────────────────────────────────────────────────────

    def _shutdown(self) -> None:
        """Persist session state and release all resources."""
        self.file_player.stop()
        self.midi_out.close()   # also calls pygame.midi.quit()
        self.midi_in.close()
        self.virtual_port.close()
        self.virtual_iport.close()

        self._cfg["is_muted"]   = self.is_muted
        self._cfg["fullscreen"] = self.is_fullscreen
        if not self.is_fullscreen:
            rect = get_window_rect()
            if rect:
                x, y, w, h = rect
                self._cfg["window_width"]  = w
                self._cfg["window_height"] = h
                self._cfg["_window_x"]     = x
                self._cfg["_window_y"]     = y
        save_config(self._cfg)

        self._tk_root.destroy()
        pygame.quit()

    # ── Font helper ───────────────────────────────────────────────────────────

    @staticmethod
    def _load_font(names: list[str], size: int) -> pygame.font.Font:
        """Try each font name in order, fall back to the pygame default."""
        for name in names + [None]:
            try:
                return pygame.font.SysFont(name, size)
            except Exception:
                pass
        return pygame.font.Font(None, size)