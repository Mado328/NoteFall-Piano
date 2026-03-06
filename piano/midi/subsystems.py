"""
Remaining MIDI subsystems:
  - VirtualMidiPort   — creates a virtual loopback device (Windows/teVirtualMIDI)
  - MidiInputListener — background thread that posts pygame events for MIDI input
  - MidiRecorder      — records live keystrokes and writes a .mid file
  - MidiFilePlayer    — loads and plays back a .mid file with note callbacks
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

import mido
import mido.backends.rtmidi  # Explicitly activate rtmidi backend.
                              # Without this import mido may fall back to a
                              # different (or no) backend on some systems,
                              # causing mido.open_input() to fail silently.
import pygame
import ctypes, sys as _sys, os  # noqa: E401

from piano.midi_constants import midi_number, note_from_midi

# Custom pygame event types for thread-safe MIDI input routing.
# A background thread posts these; the main loop reads them like keyboard events.
MIDI_NOTE_ON  = pygame.event.custom_type()
MIDI_NOTE_OFF = pygame.event.custom_type()


# ─────────────────────────────── teVirtualMIDI loader ────────────────────────

def _load_tevirtualmidi() -> "ctypes.WinDLL":
    """
    Load the teVirtualMIDI DLL.

    Search order:
    1. ``drivers/`` subfolder next to the running script / frozen exe.
       Bundle the DLLs there so the app is self-contained.
    2. The application root directory itself.
    3. System PATH (fallback for users who installed the driver globally).

    The kernel-mode driver (``teVirtualMIDI.sys``) must be installed once on
    the target machine — it cannot be loaded at runtime.  Only the user-mode
    DLL is bundled with the application.

    Raises:
        FileNotFoundError: if the DLL cannot be found in any location.
        OSError: if the DLL is found but fails to load (e.g. the kernel
                 driver is not installed / the wrong bitness).
    """

    is64    = _sys.maxsize > 2 ** 32
    dll_name = "teVirtualMIDI64.dll" if is64 else "teVirtualMIDI.dll"

    # Determine the application root: works for both script and frozen exe.
    if getattr(_sys, "frozen", False):
        app_root = os.path.dirname(_sys.executable)
    else:
        app_root = os.path.dirname(os.path.abspath(_sys.argv[0]))

    search_paths = [
        os.path.join(app_root, "drivers", dll_name),
        os.path.join(app_root, dll_name),
        dll_name,   # system PATH / Windows\System32
    ]

    for path in search_paths:
        if os.path.isfile(path) or path == dll_name:
            try:
                dll = ctypes.WinDLL(path)
                if path != dll_name:
                    print(f"[teVirtualMIDI] loaded from: {path}")
                return dll
            except OSError:
                if path != dll_name:
                    continue  # try next location
                raise

    raise FileNotFoundError(
        f"{dll_name} not found. "
        f"Place it in '{os.path.join(app_root, 'drivers')}' "
        f"or install the teVirtualMIDI driver globally."
    )


def _find_installer() -> "Optional[str]":
    """
    Look for the teVirtualMIDI installer in the ``drivers/`` folder.

    Searches for both the full installer (``teVirtualMIDISetup*.exe``) and
    the MSI variant.  Returns the full path of the first match, or ``None``.
    """
    import sys as _sys, os, glob  # noqa: E401

    if getattr(_sys, "frozen", False):
        app_root = os.path.dirname(_sys.executable)
    else:
        app_root = os.path.dirname(os.path.abspath(_sys.argv[0]))

    patterns = [
        os.path.join(app_root, "drivers", "teVirtualMIDISetup*.exe"),
        os.path.join(app_root, "drivers", "teVirtualMIDI*.exe"),
        os.path.join(app_root, "drivers", "teVirtualMIDI*.msi"),
        os.path.join(app_root, "teVirtualMIDISetup*.exe"),
        os.path.join(app_root, "teVirtualMIDI*.exe"),
    ]
    for pattern in patterns:
        matches = glob.glob(pattern)
        if matches:
            return matches[0]
    return None


def check_and_offer_driver_install() -> bool:
    """
    Check whether the teVirtualMIDI DLL is loadable.

    If it is not, show a Tkinter dialog offering to run the bundled installer.
    The function is safe to call before ``pygame.init()`` because it uses
    only Tkinter (which works independently of pygame).

    Returns:
        ``True``  — driver is available (was already installed or user just
                    ran the installer and it succeeded).
        ``False`` — driver is not available and user declined or installer
                    was not found.
    """
    # Fast path: DLL already available.
    try:
        _load_tevirtualmidi()
        return True
    except (FileNotFoundError, OSError):
        pass

    import sys as _sys  # noqa: E401

    # Try to show a GUI dialog.  Fall back to console if Tkinter is absent.
    installer_path = _find_installer()

    try:
        import tkinter as tk
        import tkinter.messagebox as mb

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)

        if installer_path:
            import os
            installer_name = os.path.basename(installer_path)
            answer = mb.askyesno(
                title="Требуется драйвер teVirtualMIDI",
                message=(
                    "Виртуальные MIDI-порты недоступны.\n\n"
                    "Для их работы необходим kernel-драйвер teVirtualMIDI "
                    "(бесплатный, от Tobias Erichsen).\n\n"
                    f"Установщик найден: {installer_name}\n\n"
                    "Установить драйвер сейчас?"
                ),
            )
            root.destroy()

            if answer:
                import subprocess
                print(f"[teVirtualMIDI] launching installer: {installer_path}")
                try:
                    # runas — запрос UAC для установки драйвера
                    import ctypes as _ct
                    result = _ct.windll.shell32.ShellExecuteW(
                        None, "runas", installer_path, None, None, 1
                    )
                    if result <= 32:
                        raise RuntimeError(f"ShellExecute returned {result}")

                    # Ждём пока пользователь завершит установку
                    root2 = tk.Tk()
                    root2.withdraw()
                    root2.attributes("-topmost", True)
                    mb.showinfo(
                        title="teVirtualMIDI",
                        message=(
                            "После завершения установки нажмите OK\n"
                            "и перезапустите приложение."
                        ),
                    )
                    root2.destroy()
                except Exception as exc:
                    print(f"[teVirtualMIDI] installer launch failed: {exc}")
                    root3 = tk.Tk()
                    root3.withdraw()
                    mb.showerror(
                        title="teVirtualMIDI",
                        message=f"Не удалось запустить установщик:\n{exc}",
                    )
                    root3.destroy()
        else:
            mb.showwarning(
                title="Требуется драйвер teVirtualMIDI",
                message=(
                    "Виртуальные MIDI-порты недоступны.\n\n"
                    "Установщик драйвера не найден в папке drivers/.\n\n"
                    "Скачайте и установите teVirtualMIDI вручную:\n"
                    "https://www.tobias-erichsen.de/software/virtualmidi.html\n\n"
                    "После установки перезапустите приложение.\n\n"
                    "Приложение запустится без виртуальных MIDI-портов."
                ),
            )
            root.destroy()

    except Exception as exc:
        # Tkinter unavailable — print to console.
        print()
        print("=" * 60)
        print("  Драйвер teVirtualMIDI не установлен.")
        if installer_path:
            print(f"  Установщик: {installer_path}")
            print("  Запустите его вручную и перезапустите приложение.")
        else:
            print("  Скачайте драйвер:")
            print("  https://www.tobias-erichsen.de/software/virtualmidi.html")
        print("=" * 60)
        print()

    # Check again after potential install.
    try:
        _load_tevirtualmidi()
        print("[teVirtualMIDI] driver is now available.")
        return True
    except (FileNotFoundError, OSError):
        print("[teVirtualMIDI] driver still not available — "
              "virtual ports will be disabled.")
        return False


# ─────────────────────────────── VirtualMidiPort ─────────────────────────────

class VirtualMidiPort:
    """
    Virtual MIDI port on Windows via teVirtualMIDI (Tobias Erichsen).

    Driver download (free, one-time install):
      https://www.tobias-erichsen.de/software/virtualmidi.html

    The created port appears to other apps as a MIDI *input* device,
    allowing DAWs and notation software to receive notes from Grand Piano.

    teVirtualMIDI flags used:
      PARSE_TX            = 0x02
      INSTANTIATE_BOTH    = 0x0C  (creates both INPUT and OUTPUT sides)
    """

    _FLAGS = 0x08 | 0x02  # INSTANTIATE_RX_ONLY | PARSE_TX
    # INSTANTIATE_RX_ONLY (0x08) — other apps receive (RX) from this port
    #                              → they see it as MIDI INPUT only ✓
    # PARSE_TX            (0x02) — DLL parses our outgoing bytes

    def __init__(self) -> None:
        self._dll:      Optional[object] = None   # ctypes.WinDLL
        self._handle:   Optional[int]    = None   # LPVM_MIDI_PORT
        self._callback: Optional[object] = None   # keep reference — prevents GC
        self._fn_send:  Optional[object] = None   # cached virtualMIDISendData
        self._fn_close: Optional[object] = None   # cached virtualMIDIClosePort
        self._lock:     threading.Lock   = threading.Lock()
        self._name:     str              = ""
        self.error:     str              = ""

    # ── Port lifecycle ────────────────────────────────────────────────────

    def open(self, name: str = "Grand Piano") -> bool:
        """
        Create the virtual MIDI port with the given *name*.

        Returns:
            ``True`` on success, ``False`` if the driver is not installed
            or the name is already taken.
        """
        self.close()
        self.error = ""
        try:
            import ctypes  # noqa: E401

            dll = _load_tevirtualmidi()

            # Callback MUST use WINFUNCTYPE (__stdcall).
            CB_TYPE = ctypes.WINFUNCTYPE(
                None,
                ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_uint8),
                ctypes.c_uint32,
                ctypes.c_size_t,
            )

            @CB_TYPE
            def _rx_discard(port, data, length, instance):
                pass  # incoming data is discarded

            create_fn            = dll.virtualMIDICreatePortEx2
            create_fn.restype    = ctypes.c_void_p
            create_fn.argtypes   = [
                ctypes.c_wchar_p, CB_TYPE, ctypes.c_size_t,
                ctypes.c_uint32,  ctypes.c_uint32,
            ]

            send_fn              = dll.virtualMIDISendData
            send_fn.restype      = ctypes.c_bool
            send_fn.argtypes     = [
                ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_uint8),
                ctypes.c_uint32,
            ]

            close_fn             = dll.virtualMIDIClosePort
            close_fn.restype     = None
            close_fn.argtypes    = [ctypes.c_void_p]

            handle = create_fn(name, _rx_discard, 0, 65535, self._FLAGS)
            if not handle:
                raise RuntimeError(
                    f"virtualMIDICreatePortEx2 returned NULL — "
                    f"name '{name}' already taken or driver not installed"
                )

            with self._lock:
                self._dll      = dll
                self._handle   = handle
                self._callback = _rx_discard  # prevent GC
                self._fn_send  = send_fn
                self._fn_close = close_fn
                self._name     = name

            print(f"[VirtualMIDI] port '{name}' created — visible to other apps as INPUT")
            return True

        except FileNotFoundError as exc:
            self.error = "teVirtualMIDI DLL not found"
            print(f"[VirtualMIDI] {exc}")
            return False
        except Exception as exc:
            self.error = str(exc)
            print(f"[VirtualMIDI] error: {exc}")
            return False

    def close(self) -> None:
        """Destroy the virtual port and release all resources."""
        with self._lock:
            if self._handle and self._fn_close:
                try:
                    self._fn_close(self._handle)
                except Exception as exc:
                    print(f"[VirtualMIDI close] {exc}")
            self._handle   = None
            self._dll      = None
            self._callback = None
            self._fn_send  = None
            self._fn_close = None
            self._name     = ""

    # ── Messaging ─────────────────────────────────────────────────────────

    def send(self, msg: mido.Message) -> None:
        """Transmit a mido Message over the virtual port."""
        with self._lock:
            if not self._handle or not self._fn_send:
                return
            try:
                import ctypes
                raw = bytes(msg.bytes())
                buf = (ctypes.c_uint8 * len(raw))(*raw)
                ok  = self._fn_send(self._handle, buf, ctypes.c_uint32(len(raw)))
                if not ok:
                    print("[VirtualMIDI send] virtualMIDISendData returned False")
            except Exception as exc:
                print(f"[VirtualMIDI send] {exc}")

    def all_notes_off(self) -> None:
        """Send CC 123 (All Notes Off) on all 16 channels."""
        for ch in range(16):
            self.send(mido.Message("control_change", channel=ch, control=123, value=0))

    # ── Properties ────────────────────────────────────────────────────────

    @property
    def is_open(self) -> bool:
        return self._handle is not None

    @property
    def name(self) -> str:
        return self._name



# ─────────────────────────────── VirtualMidiInput ────────────────────────────

class VirtualMidiInput:
    """
    Virtual MIDI input port on Windows via teVirtualMIDI.

    Other applications see this port as a MIDI **output** device and write
    notes to it. When ``enabled`` is ``True``, the DLL callback parses the
    incoming bytes and posts ``MIDI_NOTE_ON`` / ``MIDI_NOTE_OFF`` pygame
    events to the main loop — identical to a real hardware MIDI input.

    The port is created at startup and exists until the app closes, but it
    only delivers events when ``enabled = True`` (i.e. when the user selects
    it in the INPUT selector). This mirrors the OUTPUT virtual port behaviour.

    teVirtualMIDI flags:
      PARSE_RX            = 0x01  — driver parses bytes into complete messages
      INSTANTIATE_RX_ONLY = 0x08  — port is receive-only from our side
    """

    _FLAGS        = 0x04 | 0x02  # INSTANTIATE_TX_ONLY | PARSE_TX
    # INSTANTIATE_TX_ONLY (0x04) — other apps transmit (TX) to this port
    #                              → they see it as MIDI OUTPUT ✓
    # PARSE_TX            (0x02) — DLL parses their TX bytes into complete
    #                              MIDI messages before calling our callback
    _NOTE_OFF     = 0x80
    _NOTE_ON      = 0x90

    def __init__(self) -> None:
        self._dll:      Optional[object] = None
        self._handle:   Optional[int]    = None
        self._callback: Optional[object] = None  # hold ref — prevents GC
        self._fn_close: Optional[object] = None
        self._lock:     threading.Lock   = threading.Lock()
        self._name:     str              = ""
        self.error:     str              = ""
        self.enabled:   bool             = False  # only post events when True

    # ── Port lifecycle ────────────────────────────────────────────────────

    def open(self, name: str = "Grand Piano IN") -> bool:
        """
        Create the virtual MIDI input port named *name*.

        The DLL callback fires on a DLL-owned thread whenever another app
        writes to the port. We check ``self.enabled`` and, if set, post a
        pygame event so the main loop handles the note safely.

        Returns ``True`` on success, ``False`` if the driver is not
        installed or the name is already taken.
        """
        self.close()
        self.error = ""
        try:
            import ctypes  # noqa: E401

            dll = _load_tevirtualmidi()

            # MUST use WINFUNCTYPE (__stdcall).
            # CFUNCTYPE (__cdecl) corrupts the call stack on Windows.
            CB_TYPE = ctypes.WINFUNCTYPE(
                None,
                ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_uint8),
                ctypes.c_uint32,
                ctypes.c_size_t,
            )

            # Keep a reference to self so the closure can read self.enabled.
            _self = self

            @CB_TYPE
            def _on_rx(port, data, length, instance):
                if not _self.enabled:
                    return
                try:
                    if length < 3:
                        return
                    status   = data[0] & 0xF0
                    note_num = data[1]
                    velocity = data[2]

                    if status == VirtualMidiInput._NOTE_ON and velocity > 0:
                        evt = MIDI_NOTE_ON
                    elif (status == VirtualMidiInput._NOTE_OFF or
                          (status == VirtualMidiInput._NOTE_ON and velocity == 0)):
                        evt = MIDI_NOTE_OFF
                    else:
                        return

                    note_name, octave = note_from_midi(note_num)
                    if note_name is None:
                        return

                    pygame.event.post(pygame.event.Event(
                        evt, note=note_name, octave=octave,
                        velocity=velocity if evt == MIDI_NOTE_ON else 0,
                    ))
                except Exception as exc:
                    print(f"[VirtualMidiInput rx] {exc}")

            create_fn          = dll.virtualMIDICreatePortEx2
            create_fn.restype  = ctypes.c_void_p
            create_fn.argtypes = [
                ctypes.c_wchar_p, CB_TYPE, ctypes.c_size_t,
                ctypes.c_uint32,  ctypes.c_uint32,
            ]
            close_fn           = dll.virtualMIDIClosePort
            close_fn.restype   = None
            close_fn.argtypes  = [ctypes.c_void_p]

            handle = create_fn(name, _on_rx, 0, 65535, self._FLAGS)
            if not handle:
                raise RuntimeError(
                    f"virtualMIDICreatePortEx2 returned NULL — "
                    f"name '{name}' already taken or driver not installed"
                )

            with self._lock:
                self._dll      = dll
                self._handle   = handle
                self._callback = _on_rx
                self._fn_close = close_fn
                self._name     = name

            print(f"[VirtualMidiInput] port '{name}' ready "
                  f"(visible to other apps as MIDI OUTPUT)")
            return True

        except FileNotFoundError as exc:
            self.error = "teVirtualMIDI DLL not found"
            print(f"[VirtualMidiInput] {exc}")
            return False
        except Exception as exc:
            self.error = str(exc)
            print(f"[VirtualMidiInput] open error: {exc}")
            return False

    def close(self) -> None:
        """Disable delivery and destroy the virtual port."""
        self.enabled = False
        with self._lock:
            if self._handle and self._fn_close:
                try:
                    self._fn_close(self._handle)
                except Exception as exc:
                    print(f"[VirtualMidiInput close] {exc}")
            self._handle   = None
            self._dll      = None
            self._callback = None
            self._fn_close = None
            self._name     = ""

    # ── Properties ────────────────────────────────────────────────────────

    @property
    def is_open(self) -> bool:
        return self._handle is not None

    @property
    def name(self) -> str:
        return self._name




class MidiInputListener:
    """
    Listens to a MIDI input port in a background thread.

    Instead of calling application callbacks directly (which would create
    race conditions), it posts ``MIDI_NOTE_ON`` / ``MIDI_NOTE_OFF`` pygame
    events to the main event queue. The main loop then handles them exactly
    like keyboard and mouse events — safe, consistent, zero race conditions.
    """

    def __init__(self) -> None:
        self._port:     Optional[mido.ports.BaseInput] = None
        self._thread:   Optional[threading.Thread]     = None
        self._stop_evt: threading.Event                = threading.Event()

    def set_port(self, name: str) -> None:
        """Non-blocking port switch: closes current port and opens *name*."""
        threading.Thread(target=self._open_port, args=(name,), daemon=True).start()

    def stop(self) -> None:
        """Stop listening and join the background thread."""
        self._stop_evt.set()
        if self._port:
            try:
                self._port.close()
            except Exception:
                pass
            self._port = None
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._thread = None

    def close(self) -> None:
        self.stop()

    # ── Internal ──────────────────────────────────────────────────────────

    def _open_port(self, name: str) -> None:
        self.stop()
        if not name or name == "—":
            return
        try:
            port = mido.open_input(name)
        except Exception as exc:
            print(f"[MIDI input] cannot open '{name}': {exc}")
            return
        print(f"[MIDI input] opened: {name}")
        self._stop_evt.clear()
        self._port   = port
        self._thread = threading.Thread(target=self._loop, args=(port,), daemon=True)
        self._thread.start()

    def _loop(self, port: mido.ports.BaseInput) -> None:
        """Blocking iterator — posts events with zero polling delay."""
        try:
            for msg in port:
                if self._stop_evt.is_set():
                    break
                self._post(msg)
        except EOFError:
            pass   # port closed cleanly while blocking on next message
        except Exception as exc:
            if not self._stop_evt.is_set():
                print(f"[MIDI input] loop error: {exc}")

    def _post(self, msg: mido.Message) -> None:
        """Convert a mido Message to a pygame event and post it."""
        if msg.type not in ("note_on", "note_off"):
            return
        note, octave = note_from_midi(msg.note)
        if note is None:
            return
        # note_on with velocity=0 is the standard alternative to note_off
        is_on    = msg.type == "note_on" and msg.velocity > 0
        evt_type = MIDI_NOTE_ON if is_on else MIDI_NOTE_OFF
        pygame.event.post(pygame.event.Event(
            evt_type, note=note, octave=octave,
            velocity=msg.velocity if is_on else 0,
        ))


# ─────────────────────────────── MidiRecorder ────────────────────────────────

class MidiRecorder:
    """Records live note events and saves them as a standard MIDI file."""

    TICKS_PER_BEAT = 480
    TEMPO          = 500_000   # 120 BPM

    def __init__(self) -> None:
        self.is_recording: bool                          = False
        self._start_t:     float                         = 0.0
        self._events:      list[tuple[float, int, int]]  = []  # (t_sec, midi_num, vel)
        self._lock:        threading.Lock                = threading.Lock()

    def start(self) -> None:
        """Begin a new recording session (discards any previous data)."""
        with self._lock:
            self._events.clear()
            self._start_t     = time.time()
            self.is_recording = True

    def stop(self) -> None:
        """End the current recording session."""
        with self._lock:
            self.is_recording = False

    def note_on(self, note: str, octave: int, vel: int = 80) -> None:
        """Record a note-on event at the current timestamp."""
        if not self.is_recording:
            return
        num = midi_number(note, octave)
        t   = time.time() - self._start_t
        with self._lock:
            self._events.append((t, num, vel))

    def note_off(self, note: str, octave: int) -> None:
        """Record a note-off event at the current timestamp."""
        if not self.is_recording:
            return
        num = midi_number(note, octave)
        t   = time.time() - self._start_t
        with self._lock:
            self._events.append((t, num, 0))

    def save(self, filepath: str) -> bool:
        """
        Write the recorded events to a .mid file.

        Args:
            filepath: Destination path for the MIDI file.

        Returns:
            ``True`` on success, ``False`` on any error.
        """
        try:
            with self._lock:
                events = list(self._events)

            mid   = mido.MidiFile(ticks_per_beat=self.TICKS_PER_BEAT)
            track = mido.MidiTrack()
            mid.tracks.append(track)
            track.append(
                mido.MetaMessage("set_tempo", tempo=self.TEMPO, time=0)
            )

            def _sec_to_ticks(seconds: float) -> int:
                return int(
                    seconds * self.TICKS_PER_BEAT * 1_000_000 / self.TEMPO
                )

            prev_tick = 0
            for t_sec, midi_num, vel in sorted(events, key=lambda e: e[0]):
                tick      = _sec_to_ticks(t_sec)
                delta     = tick - prev_tick
                msg_type  = "note_on" if vel > 0 else "note_off"
                track.append(
                    mido.Message(msg_type, note=midi_num, velocity=vel, time=delta)
                )
                prev_tick = tick

            mid.save(filepath)
            return True
        except Exception as exc:
            print(f"[MidiRecorder save] {exc}")
            return False


# ─────────────────────────────── MidiFilePlayer ──────────────────────────────

@dataclass
class PlaybackNote:
    """A single note from a loaded MIDI file, with display coordinates."""
    note:      str
    octave:    int
    start_sec: float
    duration:  float
    is_black:  bool
    x:         int = 0
    width:     int = 0


class MidiFilePlayer:
    """
    Loads and plays back a MIDI file with tight timing.

    Playback runs in a daemon thread. Note events are delivered via
    :attr:`on_note_on` / :attr:`on_note_off` callbacks. Pause and resume
    preserve the playback position.
    """

    def __init__(self) -> None:
        self.notes:    list[PlaybackNote]   = []
        self.filepath: str                  = ""
        self.duration: float                = 0.0

        self._thread:     Optional[threading.Thread] = None
        self._stop_ev:    threading.Event            = threading.Event()
        self._pause_ev:   threading.Event            = threading.Event()
        self._start_t:    float                      = 0.0
        self._paused_at:  float                      = 0.0
        self._resume_idx: int                        = 0

        self.is_playing: bool = False
        self.is_paused:  bool = False

        self.on_note_on:  Optional[Callable[[str, int], None]] = None
        self.on_note_off: Optional[Callable[[str, int], None]] = None
        self.on_finished: Optional[Callable[[], None]]         = None

    # ── Loading ───────────────────────────────────────────────────────────

    def load(self, filepath: str) -> bool:
        """
        Parse a .mid file and populate :attr:`notes`.

        Args:
            filepath: Path to the MIDI file.

        Returns:
            ``True`` on success, ``False`` on any parse error.
        """
        try:
            mid    = mido.MidiFile(filepath)
            tempo  = 500_000
            events: list[tuple[int, mido.Message]] = []

            for track in mid.tracks:
                abs_tick = 0
                for msg in track:
                    abs_tick += msg.time
                    if msg.type in ("note_on", "note_off", "set_tempo"):
                        events.append((abs_tick, msg))

            events.sort(key=lambda e: e[0])

            def _ticks_to_sec(ticks: int, t_tempo: int, tpb: int) -> float:
                return ticks * t_tempo / (tpb * 1_000_000)

            tpb                                                 = mid.ticks_per_beat
            pending: dict[int, tuple[float, str, int]]          = {}
            cur_tick, cur_sec                                    = 0, 0.0
            self.notes                                           = []

            for abs_tick, msg in events:
                cur_sec  += _ticks_to_sec(abs_tick - cur_tick, tempo, tpb)
                cur_tick  = abs_tick

                if msg.type == "set_tempo":
                    tempo = msg.tempo
                    continue

                note_name, octave = note_from_midi(msg.note)
                if note_name is None:
                    continue

                is_on = msg.type == "note_on" and msg.velocity > 0

                if is_on:
                    pending[msg.note] = (cur_sec, note_name, octave)
                elif msg.note in pending:
                    start_sec, pnote, poct = pending.pop(msg.note)
                    dur      = max(0.05, cur_sec - start_sec)
                    self.notes.append(PlaybackNote(
                        note=pnote, octave=poct,
                        start_sec=start_sec, duration=dur,
                        is_black=("#" in pnote),
                    ))

            # Close any unterminated notes
            for midi_num_val, (start_sec, pnote, poct) in pending.items():
                self.notes.append(PlaybackNote(
                    note=pnote, octave=poct,
                    start_sec=start_sec, duration=0.25,
                    is_black=("#" in pnote),
                ))

            self.filepath = filepath
            self.duration = max(
                (n.start_sec + n.duration for n in self.notes), default=0.0
            )
            return True
        except Exception as exc:
            print(f"[MIDI load] {exc}")
            return False

    def attach_keys(self, renderer_keys: list) -> None:
        """
        Map loaded :class:`PlaybackNote` objects to pixel positions.

        Must be called after both :meth:`load` and the renderer has been
        built, as well as after every window resize.

        Args:
            renderer_keys: List of :class:`~piano.ui.renderer.KeyState` objects.
        """
        key_map = {(k.note, k.octave): k for k in renderer_keys}
        for note in self.notes:
            key = key_map.get((note.note, note.octave))
            if key:
                note.x     = key.rect.centerx
                note.width = max(key.rect.width - 2, 4)
            else:
                note.x = note.width = 0

    # ── Playback control ──────────────────────────────────────────────────

    def play(self) -> None:
        """Start or resume playback."""
        if self.is_playing:
            return
        self._stop_ev.clear()
        self._pause_ev.clear()
        if self.is_paused:
            self._start_t  = time.time() - self._paused_at
            self.is_paused = False
        else:
            self._start_t    = time.time()
            self._resume_idx = 0
        self.is_playing = True
        self._thread    = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def pause(self) -> None:
        """Pause playback, saving the current position."""
        if not self.is_playing:
            return
        self._paused_at = self.elapsed()
        self._pause_ev.set()
        self.is_playing = False
        self.is_paused  = True

    def stop(self) -> None:
        """Stop playback and reset position to the beginning."""
        self.on_note_on  = None
        self.on_note_off = None
        self._stop_ev.set()
        self._pause_ev.set()
        self.is_playing  = False
        self.is_paused   = False
        self._paused_at  = 0.0
        self._resume_idx = 0
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.5)
        self._thread = None

    def elapsed(self) -> float:
        """Return seconds elapsed since playback started (pause-aware)."""
        if self.is_paused:
            return self._paused_at
        if not self.is_playing:
            return 0.0
        return time.time() - self._start_t

    # ── Background playback loop ──────────────────────────────────────────

    def _loop(self) -> None:
        scheduled   = sorted(self.notes, key=lambda n: n.start_sec)
        pending_off: list[tuple[float, PlaybackNote]] = []
        idx         = self._resume_idx

        while not self._stop_ev.is_set() and not self._pause_ev.is_set():
            now_sec = time.time() - self._start_t
            on_on   = self.on_note_on
            on_off  = self.on_note_off

            # Fire note-on events that are due
            while idx < len(scheduled) and scheduled[idx].start_sec <= now_sec:
                n = scheduled[idx]
                if on_on:
                    on_on(n.note, n.octave)
                pending_off.append((n.start_sec + n.duration, n))
                idx += 1

            # Fire note-off events that are due
            still_pending = []
            for end_sec, n in pending_off:
                if end_sec <= now_sec:
                    if on_off:
                        on_off(n.note, n.octave)
                else:
                    still_pending.append((end_sec, n))
            pending_off = still_pending

            # All notes played and released — playback finished
            if idx >= len(scheduled) and not pending_off:
                self.is_playing = False
                if self.on_finished:
                    self.on_finished()
                break

            time.sleep(0.005)

        self._resume_idx = idx