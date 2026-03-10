"""
Auto-updater via GitHub Releases API.

Flow
----
1. Fetch latest release from GET /repos/{owner}/{repo}/releases/latest
2. Compare tag (e.g. "v1.2.3") with current VERSION.
3. If newer: download the .exe asset (or find exe inside .zip fallback).
4. Write a helper .bat that waits for this process to exit, swaps the exe, restarts.
5. Launch the .bat and signal the app to quit via pygame.QUIT.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.request
import zipfile
from typing import Callable, Optional

import pygame

from piano.version import VERSION, GITHUB_REPO


# ── Version comparison ────────────────────────────────────────────────────────

def _parse_version(v: str) -> tuple[int, ...]:
    """'v1.2.3' or '1.2.3' -> (1, 2, 3)."""
    return tuple(int(d) for d in re.findall(r"\d+", v))


def is_newer(remote_tag: str, local: str = VERSION) -> bool:
    """Return True if remote_tag represents a version newer than local."""
    return _parse_version(remote_tag) > _parse_version(local)


# ── GitHub API ────────────────────────────────────────────────────────────────

def fetch_latest_release() -> dict:
    """
    Return the latest GitHub release dict.
    Raises RuntimeError on network or API errors.
    """
    url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
    req = urllib.request.Request(
        url,
        headers={
            "Accept":     "application/vnd.github+json",
            "User-Agent": "NoteFallUpdater/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except Exception as exc:
        raise RuntimeError(f"Не удалось получить информацию о релизе: {exc}") from exc


def find_exe_asset(release: dict) -> Optional[dict]:
    """Return the first .exe asset in the release, or None."""
    for asset in release.get("assets", []):
        if asset["name"].lower().endswith(".exe"):
            return asset
    return None


def find_zip_asset(release: dict) -> Optional[dict]:
    """Return the first .zip asset in the release, or None."""
    for asset in release.get("assets", []):
        if asset["name"].lower().endswith(".zip"):
            return asset
    return None


# ── Download ──────────────────────────────────────────────────────────────────

def download_file(
    url:         str,
    dest:        str,
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> None:
    """Download url to dest, calling progress_cb(downloaded, total) periodically."""
    req = urllib.request.Request(url, headers={"User-Agent": "NoteFallUpdater/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        total      = int(resp.headers.get("Content-Length", 0))
        downloaded = 0
        with open(dest, "wb") as fh:
            while True:
                data = resp.read(65536)
                if not data:
                    break
                fh.write(data)
                downloaded += len(data)
                if progress_cb:
                    progress_cb(downloaded, total)


# ── Zip extraction ────────────────────────────────────────────────────────────

def extract_zip(zip_path: str, extract_dir: str) -> str:
    """
    Extract zip_path into extract_dir.
    If the archive has a single top-level folder, returns its path;
    otherwise returns extract_dir.
    """
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(extract_dir)

    entries = os.listdir(extract_dir)
    if len(entries) == 1:
        candidate = os.path.join(extract_dir, entries[0])
        if os.path.isdir(candidate):
            return candidate
    return extract_dir


# ── Install helper ────────────────────────────────────────────────────────────

def _write_updater_bat(
    bat_path: str,
    old_exe:  str,
    new_exe:  str,
) -> None:
    """Write a .bat that deletes old_exe and launches new_exe with clean env."""
    bat = (
        "@echo off\n"
        f"del /F /Q \"{old_exe}\"\n"
        f"start /I \"\" \"{new_exe}\"\n"
        "exit\n"
    )
    with open(bat_path, "w", encoding="utf-8") as fh:
        fh.write(bat)


def _launch_bat(bat_path: str) -> None:
    """Launch the bat in a new console with a completely clean environment."""
    # Only the bare minimum Windows needs to run cmd.exe and an exe
    clean_env = {
        "SystemRoot":  os.environ.get("SystemRoot", r"C:\Windows"),
        "SystemDrive": os.environ.get("SystemDrive", "C:"),
        "PATHEXT":     os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD"),
        "PATH":        os.environ.get("SystemRoot", r"C:\Windows") + r"\system32;"
                       + os.environ.get("SystemRoot", r"C:\Windows") + ";"
                       + os.environ.get("SystemRoot", r"C:\Windows") + r"\System32\Wbem",
        "TEMP":        os.environ.get("TEMP", os.environ.get("TMP", r"C:\Windows\Temp")),
        "TMP":         os.environ.get("TMP",  os.environ.get("TEMP", r"C:\Windows\Temp")),
        "USERPROFILE": os.environ.get("USERPROFILE", ""),
    }
    subprocess.Popen(
        ["cmd.exe", "/c", bat_path],
        creationflags=subprocess.CREATE_NEW_CONSOLE,
        env=clean_env,
    )


# ── Public high-level API ─────────────────────────────────────────────────────

class UpdaterJob:
    """
    Runs the full check -> download -> prepare cycle in a background thread.

    Callbacks are invoked from the worker thread — callers must marshal to the
    main thread if updating Tkinter or pygame UI elements.

    Parameters
    ----------
    on_status   : receives human-readable status strings.
    on_progress : receives (downloaded_bytes, total_bytes) during download.
    on_done     : called when the job finishes with (success: bool, message: str).
    on_ready    : called when the update is downloaded and ready to install;
                  the caller should then prompt the user and call apply().
    """

    def __init__(
        self,
        on_status:   Callable[[str], None],
        on_progress: Callable[[int, int], None],
        on_done:     Callable[[bool, str], None],
        on_ready:    Callable[[], None],
    ) -> None:
        self._on_status   = on_status
        self._on_progress = on_progress
        self._on_done     = on_done
        self._on_ready    = on_ready
        self._tmp_dir: Optional[str] = None
        self._new_exe: Optional[str] = None
        self._new_tag: str           = ""
        self._cancelled              = threading.Event()

    def start(self) -> None:
        """Start the background check-and-download thread."""
        threading.Thread(target=self._run, daemon=True).start()

    def cancel(self) -> None:
        """Signal the background thread to stop."""
        self._cancelled.set()

    def apply(self) -> None:
        """
        Last actions before quitting:
          1. Rename current exe to .old.exe
          2. Copy new exe to original path
          3. Launch bat that deletes .old.exe and starts new exe
          4. Quit
        """
        if not self._new_exe:
            return

        cur_exe  = sys.executable
        app_dir  = os.path.dirname(cur_exe)
        exe_stem = os.path.splitext(os.path.basename(cur_exe))[0]
        old_exe  = os.path.join(app_dir, exe_stem + ".old.exe")

        try:
            if os.path.exists(old_exe):
                os.remove(old_exe)
            os.rename(cur_exe, old_exe)
            shutil.copy2(self._new_exe, cur_exe)
        except Exception as exc:
            if not os.path.exists(cur_exe) and os.path.exists(old_exe):
                try:
                    os.rename(old_exe, cur_exe)
                except Exception:
                    pass
            self._on_done(False, f"Ошибка подготовки обновления: {exc}")
            return

        bat_dir  = tempfile.mkdtemp(prefix="nf_upd_")
        bat_path = os.path.join(bat_dir, "launch.bat")
        _write_updater_bat(bat_path=bat_path, old_exe=old_exe, new_exe=cur_exe)
        _launch_bat(bat_path)
        pygame.event.post(pygame.event.Event(pygame.QUIT))

    def _run(self) -> None:
        try:
            self._on_status("Проверка обновлений…")
            release       = fetch_latest_release()
            tag           = release.get("tag_name", "")
            self._new_tag = tag

            if not is_newer(tag):
                self._on_done(True, f"Установлена последняя версия ({VERSION})")
                return

            if self._cancelled.is_set():
                return

            self._on_status(f"Доступна версия {tag} — загрузка…")

            exe_asset = find_exe_asset(release)
            if exe_asset:
                url    = exe_asset["browser_download_url"]
                is_exe = True
            else:
                zip_asset = find_zip_asset(release)
                if zip_asset:
                    url    = zip_asset["browser_download_url"]
                    is_exe = False
                else:
                    self._on_done(False, "Файл релиза не найден (.exe или .zip)")
                    return

            self._tmp_dir = tempfile.mkdtemp(prefix="nf_update_")
            dl_path       = os.path.join(self._tmp_dir, "update.exe" if is_exe else "update.zip")

            def _prog(dl: int, total: int) -> None:
                if self._cancelled.is_set():
                    raise InterruptedError
                self._on_progress(dl, total)

            download_file(url, dl_path, _prog)

            if self._cancelled.is_set():
                return

            if is_exe:
                self._new_exe = dl_path
            else:
                self._on_status("Распаковка…")
                extract_dir = os.path.join(self._tmp_dir, "extracted")
                os.makedirs(extract_dir, exist_ok=True)
                src = extract_zip(dl_path, extract_dir)

                found: Optional[str] = None
                for root, _dirs, files in os.walk(src):
                    for fname in files:
                        if fname.lower().endswith(".exe"):
                            found = os.path.join(root, fname)
                            break
                    if found:
                        break

                if not found:
                    self._on_done(False, "exe не найден внутри архива")
                    return
                self._new_exe = found

            self._on_status(f"Версия {tag} готова к установке")
            self._on_ready()

        except InterruptedError:
            self._on_status("Отменено")
        except Exception as exc:
            self._on_done(False, str(exc))