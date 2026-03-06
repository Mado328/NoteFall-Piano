"""
Computer keyboard → MIDI note mappings.

Isolated here so the Application class does not carry this large literal
table, and so the mappings can be tested or extended independently.

``WHITE_KEY_MAP`` — base keys (no modifier).
``BLACK_KEY_MAP`` — same keys + Shift → sharps/flats.
"""

import pygame

# ── White keys ────────────────────────────────────────────────────────────────
WHITE_KEY_MAP: dict[int, tuple[str, int]] = {
    # Octave 0
    pygame.K_KP4: ("A", 0), pygame.K_KP5: ("B", 0),
    # Octave 1
    pygame.K_1: ("C", 1), pygame.K_2: ("D", 1), pygame.K_3: ("E", 1),
    pygame.K_4: ("F", 1), pygame.K_5: ("G", 1), pygame.K_6: ("A", 1),
    pygame.K_7: ("B", 1),
    # Octave 2
    pygame.K_8: ("C", 2), pygame.K_9: ("D", 2), pygame.K_0: ("E", 2),
    pygame.K_q: ("F", 2), pygame.K_w: ("G", 2), pygame.K_e: ("A", 2),
    pygame.K_r: ("B", 2),
    # Octave 3
    pygame.K_t: ("C", 3), pygame.K_y: ("D", 3), pygame.K_u: ("E", 3),
    pygame.K_i: ("F", 3), pygame.K_o: ("G", 3), pygame.K_p: ("A", 3),
    pygame.K_a: ("B", 3),
    # Octave 4
    pygame.K_s: ("C", 4), pygame.K_d: ("D", 4), pygame.K_f: ("E", 4),
    pygame.K_g: ("F", 4), pygame.K_h: ("G", 4), pygame.K_j: ("A", 4),
    pygame.K_k: ("B", 4),
    # Octave 5
    pygame.K_l: ("C", 5), pygame.K_z: ("D", 5), pygame.K_x: ("E", 5),
    pygame.K_c: ("F", 5), pygame.K_v: ("G", 5), pygame.K_b: ("A", 5),
    pygame.K_n: ("B", 5),
    # C of octave 6
    pygame.K_m: ("C", 6),
}

# ── Black keys ────────────────────────────────────────────────────────────────
BLACK_KEY_MAP: dict[int, tuple[str, int]] = {
    # Octave 0
    pygame.K_KP4: ("A#", 0),
    # Octave 1
    pygame.K_1: ("C#", 1), pygame.K_2: ("D#", 1),
    pygame.K_4: ("F#", 1), pygame.K_5: ("G#", 1), pygame.K_6: ("A#", 1),
    # Octave 2
    pygame.K_8: ("C#", 2), pygame.K_9: ("D#", 2),
    pygame.K_q: ("F#", 2), pygame.K_w: ("G#", 2), pygame.K_e: ("A#", 2),
    # Octave 3
    pygame.K_t: ("C#", 3), pygame.K_y: ("D#", 3),
    pygame.K_i: ("F#", 3), pygame.K_o: ("G#", 3), pygame.K_p: ("A#", 3),
    # Octave 4
    pygame.K_s: ("C#", 4), pygame.K_d: ("D#", 4),
    pygame.K_g: ("F#", 4), pygame.K_h: ("G#", 4), pygame.K_j: ("A#", 4),
    # Octave 5
    pygame.K_l: ("C#", 5), pygame.K_z: ("D#", 5),
    pygame.K_c: ("F#", 5), pygame.K_v: ("G#", 5), pygame.K_b: ("A#", 5),
}
