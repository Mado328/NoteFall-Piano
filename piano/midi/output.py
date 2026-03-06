"""
MIDI output — pygame.midi (PortMidi) backend with VirtualMidiPort support.

Port enumeration  →  pygame.midi (PortMidi) — gives Microsoft MIDI Mapper,
                     GS Wavetable and all standard WinMM devices.
                     The virtual port name is injected into the list manually
                     (PortMidi may not see teVirtualMIDI ports in time).

Opening a port    →  For the virtual port: route notes via VirtualMidiPort.send()
                     using the teVirtualMIDI DLL directly — the only reliable
                     method since PortMidi/rtmidi cannot open the same-process
                     teVirtualMIDI port as an output on Windows.
                     For all other ports: pygame.midi.Output as before.
"""

from __future__ import annotations

import abc
import threading
import time
from typing import Optional

import mido
import pygame.midi

from piano.midi_constants import midi_number


# ─────────────────────────────── Abstract interface ──────────────────────────

class IMidiOutput(abc.ABC):

    @abc.abstractmethod
    def play(self, note: str, octave: int, vel: int = 80) -> None: ...

    @abc.abstractmethod
    def stop(self, note: str, octave: int) -> None: ...

    @abc.abstractmethod
    def all_notes_off(self) -> None: ...

    @abc.abstractmethod
    def open_by_name(self, name: str) -> None: ...

    @abc.abstractmethod
    def output_names(self) -> list[str]: ...

    @abc.abstractmethod
    def set_virtual_port(self, name: str, port) -> None: ...

    @abc.abstractmethod
    def close(self) -> None: ...


# ─────────────────────────────── Implementation ───────────────────────────────

class MidiOutput(IMidiOutput):
    """
    MIDI output via pygame.midi (PortMidi).

    Virtual port support
    --------------------
    Call ``set_virtual_port(name, port)`` once at startup with the
    VirtualMidiPort instance.  When ``open_by_name`` is called with that
    name, notes are routed through ``VirtualMidiPort.send()`` (DLL direct)
    instead of PortMidi — the only reliable path on Windows.

    Thread safety
    -------------
    ``self._lock`` guards ``_out``, ``_out_id``, ``_use_vport``, and
    ``_note_count``.  Background open thread holds the lock only for the
    brief pointer-swap; all blocking I/O happens outside.
    """

    INSTRUMENT = 0  # Acoustic Grand Piano

    def __init__(self) -> None:
        pygame.midi.init()
        self._lock:       threading.Lock        = threading.Lock()
        self._out:        Optional[pygame.midi.Output] = None
        self._out_id:     int                   = -1
        self._note_count: dict[int, int]        = {}

        # Virtual port routing
        self._vport_name: str                   = ""
        self._vport:      Optional[object]      = None  # VirtualMidiPort | None
        self._use_vport:  bool                  = False  # True when vport selected

    # ── Configuration ─────────────────────────────────────────────────────

    def set_virtual_port(self, name: str, port) -> None:
        """
        Register the VirtualMidiPort instance.

        Must be called before ``output_names()`` is used so the name
        appears in the list.
        """
        self._vport_name = name
        self._vport      = port

    # ── Port enumeration ──────────────────────────────────────────────────

    def output_names(self) -> list[str]:
        """
        Return all output port names.

        PortMidi names come first (Microsoft MIDI Mapper, GS Wavetable…).
        The virtual port name is prepended if PortMidi does not list it
        yet (teVirtualMIDI registration may lag behind).
        """
        pm_names: list[str] = []
        try:
            for i in range(pygame.midi.get_count()):
                info = pygame.midi.get_device_info(i)
                if info[3]:  # is_output
                    pm_names.append(info[1].decode(errors="replace"))
        except Exception as exc:
            print(f"[PortMidi] get_count error: {exc}")

        # Ensure virtual port is always present.
        if self._vport_name and self._vport_name not in pm_names:
            pm_names = [self._vport_name] + pm_names

        return pm_names

    # ── Port switching ────────────────────────────────────────────────────

    def open_by_name(self, name: str) -> None:
        """Non-blocking port switch in a daemon thread."""
        threading.Thread(target=self._open_bg, args=(name,), daemon=True).start()

    def close(self) -> None:
        with self._lock:
            self._close_pm_unlocked()
            self._use_vport = False
        try:
            pygame.midi.quit()
        except Exception:
            pass

    # ── Note API ──────────────────────────────────────────────────────────

    def play(self, note: str, octave: int, vel: int = 80) -> None:
        with self._lock:
            try:
                num   = midi_number(note, octave)
                count = self._note_count.get(num, 0)
                if count == 0:
                    self._send_on_unlocked(num, vel)
                self._note_count[num] = count + 1
            except Exception as exc:
                print(f"[MIDI play] {exc}")

    def stop(self, note: str, octave: int) -> None:
        with self._lock:
            try:
                num   = midi_number(note, octave)
                count = self._note_count.get(num, 0)
                if count <= 1:
                    self._send_off_unlocked(num)
                    self._note_count.pop(num, None)
                else:
                    self._note_count[num] = count - 1
            except Exception as exc:
                print(f"[MIDI stop] {exc}")

    def all_notes_off(self) -> None:
        with self._lock:
            try:
                if self._use_vport and self._vport:
                    self._vport.all_notes_off()
                elif self._out:
                    for ch in range(16):
                        self._out.write_short(0xB0 | ch, 123, 0)
                self._note_count.clear()
            except Exception as exc:
                print(f"[MIDI all_notes_off] {exc}")

    # ── Internal ──────────────────────────────────────────────────────────

    def _send_on_unlocked(self, num: int, vel: int) -> None:
        if self._use_vport and self._vport:
            self._vport.send(mido.Message("note_on", note=num, velocity=vel))
        elif self._out:
            self._out.note_on(num, vel)

    def _send_off_unlocked(self, num: int) -> None:
        if self._use_vport and self._vport:
            self._vport.send(mido.Message("note_off", note=num, velocity=0))
        elif self._out:
            self._out.note_off(num, 0)

    def _close_pm_unlocked(self) -> None:
        if self._out:
            try:
                self._out.close()
            except Exception:
                pass
            self._out    = None
            self._out_id = -1

    def _pm_id_for_name(self, name: str) -> int:
        for i in range(pygame.midi.get_count()):
            info = pygame.midi.get_device_info(i)
            if info[3] and info[1].decode(errors="replace") == name:
                return i
        return -1

    def _open_bg(self, name: str) -> None:
        """Background thread: close current port and open *name*."""
        with self._lock:
            old_out        = self._out
            self._out      = None
            self._out_id   = -1
            self._use_vport = False
            self._note_count.clear()

        if old_out:
            try:
                old_out.close()
            except Exception:
                pass

        if not name or name == "—":
            print("[MIDI] port deselected")
            return

        # ── Virtual port: route via DLL directly ─────────────────────────
        if name == self._vport_name and self._vport and self._vport.is_open:
            with self._lock:
                self._use_vport = True
            print(f"[MIDI] routing to virtual port '{name}' via DLL")
            return

        # ── Standard port: open via PortMidi ─────────────────────────────
        target_id = self._pm_id_for_name(name)
        if target_id == -1:
            print(f"[PortMidi] port not found: '{name}'")
            return

        try:
            new_out = pygame.midi.Output(target_id, latency=1)
            new_out.set_instrument(self.INSTRUMENT)
            with self._lock:
                self._out    = new_out
                self._out_id = target_id
            print(f"[PortMidi] opened: '{name}'")
            return
        except Exception as exc:
            print(f"[PortMidi] open failed, retrying with reinit: {exc}")

        try:
            pygame.midi.quit()
            time.sleep(0.05)
            pygame.midi.init()
            target_id = self._pm_id_for_name(name)
            if target_id != -1:
                new_out = pygame.midi.Output(target_id, latency=1)
                new_out.set_instrument(self.INSTRUMENT)
                with self._lock:
                    self._out    = new_out
                    self._out_id = target_id
                print(f"[PortMidi] opened after reinit: '{name}'")
        except Exception as exc:
            print(f"[PortMidi] open after reinit failed: {exc}")


# ─────────────────────────────── Factory ─────────────────────────────────────

def create_midi_output() -> IMidiOutput:
    return MidiOutput()