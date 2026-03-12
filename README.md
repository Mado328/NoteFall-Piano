# NoteFall-Piano

<p align="center">
  <img src="https://img.shields.io/github/license/Mado328/NoteFall-Piano" alt="License">
  <img src="https://img.shields.io/github/stars/Mado328/NoteFall-Piano" alt="Stars">
  <img src="https://img.shields.io/github/forks/Mado328/NoteFall-Piano" alt="Forks">
  <img src="https://img.shields.io/badge/Platform-Windows-blue" alt="Platform">
</p>

## Overview

NoteFall-Piano is an open-source Windows application for visualizing pressed piano notes in real-time. Originally designed for piano learners and MIDI enthusiasts, it provides an intuitive "falling notes" visualization similar to popular software like Synthesia. The application reads MIDI input from connected devices or MIDI files and displays notes as colored blocks falling toward a virtual 88-key piano keyboard, making it an excellent tool for learning pieces, practicing playing, or simply visualizing musical data.

The visualization works intuitively: notes scroll downward toward the keyboard, where the horizontal position of each block corresponds to its pitch on the piano, and the vertical length of the block represents note duration. This creates a clear visual mapping that helps pianists understand piece structure and timing at a glance.

## Features

- **MIDI File Playback** — Load and play MIDI files with real-time visual note tracking
- **Real-time MIDI Input** — Connect your MIDI keyboard controller and see your playing visualized instantly
- **Full 88-Key Virtual Piano** — Complete piano keyboard with octave markers and note labels
- **Recording Capability** — Record your MIDI performances for later review or practice
- **Adjustable Scale** — Zoom in or out to customize the visual experience
- **Dark Theme Interface** — Eye-friendly dark interface with high-contrast cyan accents for comfortable long practice sessions

## Download

### Latest Release

Download the latest version from the Releases page:

➡️ **[NoteFall-Piano Releases](https://github.com/Mado328/NoteFall-Piano/releases)**

Choose the ZIP file appropriate for your system, extract it, and run the executable to start the application. No installation required — the application is distributed as a portable ready-to-use package.

## System Requirements

- **Operating System**: Windows 10 or later (64-bit)

## Usage Guide

### Loading and Playing MIDI Files

1. Click the **Open** button in the MIDI FILE section of the control panel
2. Browse and select a `.mid` or `.midi` file from your computer
3. Click **Start** to begin playback
4. Watch as notes appear as colored blocks falling toward the keyboard

### Using a MIDI Controller

1. Use the **INPUT** dropdown menu to select your MIDI device
2. Start playing — each key press will light up on the virtual keyboard in real-time

### Recording Your Performance

1. Click the **Record** button (red dot icon) to begin recording
2. Play your MIDI controller or click notes on the virtual keyboard
3. Click **Record** again to stop recording
4. Your performance can be reviewed or saved for practice purposes

### Adjusting the View

Use the **Scale** controls (plus/minus buttons) to zoom in for detailed practice or zoom out to see a larger portion of the musical piece. The current scale is displayed (e.g., "1.50x").

## Technology Stack

- **Python** — Core application logic and runtime
- **PyGame** — Graphics rendering and user interface
- **mido** — MIDI input/output handling and file parsing

## License

This project is licensed under the **Apache License 2.0**. See the LICENSE file for full license text.

```
Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
```

## Contributing

Contributions, bug reports, and feature suggestions are welcome! Please feel free to:

- Open an issue for bugs or feature requests
- Submit pull requests for improvements
- Share your feedback and experience

---

<p align="center">
  Made with 🎵 for piano learners and music enthusiasts
</p>
