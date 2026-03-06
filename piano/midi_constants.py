"""
Shared MIDI constants and pure conversion utilities.

Previously duplicated verbatim in MidiPlayer, MidiOutputMido, MidiRecorder,
MidiInputListener, and MidiFilePlayer. Now defined once and imported everywhere.
"""

# Chromatic note name → MIDI pitch-class (0-11)
NOTE_MAP: dict[str, int] = {
    'C': 0, 'C#': 1, 'D': 2, 'D#': 3, 'E': 4,  'F': 5,
    'F#': 6, 'G': 7, 'G#': 8, 'A': 9, 'A#': 10, 'B': 11,
}

# Reverse mapping: pitch-class → note name
NOTE_NAMES: dict[int, str] = {v: k for k, v in NOTE_MAP.items()}

# Middle-C convention: MIDI note 60 = C4 when BASE_OCTAVE = 1
BASE_OCTAVE: int = 1


def midi_number(note: str, octave: int) -> int:
    """
    Convert a (note-name, octave) pair to an absolute MIDI note number.

    Args:
        note:   Chromatic note name, e.g. ``'C'``, ``'F#'``, ``'A#'``.
        octave: Piano octave index (0-based as used internally by this app).

    Returns:
        Integer MIDI note number in the range 0-127.
    """
    return 12 * (BASE_OCTAVE + octave + 1) + NOTE_MAP.get(note, 0)


def note_from_midi(midi_num: int) -> tuple[str | None, int]:
    """
    Decompose an absolute MIDI note number into (note-name, octave).

    Args:
        midi_num: MIDI note number (0-127).

    Returns:
        ``(note_name, octave)`` where *note_name* is ``None`` for unknown
        pitch-classes (should never happen with standard MIDI).
    """
    note   = NOTE_NAMES.get(midi_num % 12)
    octave = midi_num // 12 - BASE_OCTAVE - 1
    return note, octave
