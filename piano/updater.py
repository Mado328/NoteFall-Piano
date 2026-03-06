"""
Auto-updater via GitHub Releases API.

Flow
----
1. Fetch latest release from  GET /repos/{owner}/{repo}/releases/latest
2. Compare tag (e.g. "v1.2.3") with current VERSION.
3. If newer: download the release zip asset, extract to a temp dir.
4. Write a small helper .bat script that:
     - waits for this process to exit
     - removes old app files
     - copies new files in place
     - restarts main.py  (or the .exe)
5. Launch the .bat as a detached process and signal the app to quit.

The updater never touches itself while running — all file operations happen
AFTER the process exits, via the helper script.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
import tempfile
import threading
import zipfile
from typing import Callable, Optional

from piano.version import VERSION, GITHUB_REPO


# ── Version comparison ────────────────────────────────────────────────────────

def _parse_version(v: str) -> tuple[int, ...]:
    """'v1.2.3' or '1.2.3' → (1, 2, 3)."""
    digits = re.findall(r"\d+", v)
    return tuple(int(d) for d in digits)


def is_newer(remote_tag: str, local: str = VERSION) -> bool:
    return _parse_version(remote_tag) > _parse_version(local)


# ── GitHub API ────────────────────────────────────────────────────────────────

def fetch_latest_release() -> dict:
    """
    Return the latest GitHub release dict.

    Raises ``RuntimeError`` on network or API errors.
    """
    import urllib.request, json

    url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/vnd.github+json",
                 "User-Agent": "GrandPianoUpdater/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except Exception as exc:
        raise RuntimeError(f"Не удалось получить информацию о релизе: {exc}") from exc


def find_zip_asset(release: dict) -> Optional[dict]:
    """Return the first .zip asset in the release, or None."""
    for asset in release.get("assets", []):
        if asset["name"].endswith(".zip"):
            return asset
    # Fall back to zipball_url
    return None


# ── Download ──────────────────────────────────────────────────────────────────

def download_file(
    url: str,
    dest: str,
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> None:
    """
    Download *url* to *dest*, calling ``progress_cb(downloaded, total)``
    periodically if provided.
    """
    import urllib.request

    req = urllib.request.Request(url, headers={"User-Agent": "GrandPianoUpdater/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        total = int(resp.headers.get("Content-Length", 0))
        downloaded = 0
        chunk = 65536
        with open(dest, "wb") as fh:
            while True:
                data = resp.read(chunk)
                if not data:
                    break
                fh.write(data)
                downloaded += len(data)
                if progress_cb:
                    progress_cb(downloaded, total)


# ── Install helper ────────────────────────────────────────────────────────────

def _app_root() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(sys.argv[0]))


def _write_updater_bat(
    bat_path:   str,
    pid:        int,
    src_dir:    str,
    dst_dir:    str,
    restart_cmd: str,
) -> None:
    """
    Write a Windows .bat that:
      1. Waits for *pid* to exit.
      2. Robocopy new files over the old ones.
      3. Deletes the temp dir.
      4. Restarts the app.
    """
    bat = f"""@echo off
:wait
tasklist /FI "PID eq {pid}" 2>NUL | find "{pid}" >NUL
if not errorlevel 1 (
    timeout /t 1 /nobreak >NUL
    goto wait
)

robocopy "{src_dir}" "{dst_dir}" /E /IS /IT /IM >NUL
if errorlevel 8 (
    echo Ошибка копирования файлов
    pause
    exit /b 1
)

rmdir /S /Q "{os.path.dirname(src_dir)}"
start "" {restart_cmd}
"""
    with open(bat_path, "w", encoding="cp1251") as fh:
        fh.write(bat)


def extract_zip(zip_path: str, extract_dir: str) -> str:
    """
    Extract *zip_path* into *extract_dir*.

    GitHub release zips typically contain a single top-level folder.
    Returns the path to the actual app root inside the archive.
    """
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(extract_dir)

    # If all entries share a common prefix folder, step into it
    entries = os.listdir(extract_dir)
    if len(entries) == 1:
        candidate = os.path.join(extract_dir, entries[0])
        if os.path.isdir(candidate):
            return candidate
    return extract_dir


def _launch_bat(bat_path: str) -> None:
    """Launch the updater .bat as a fully detached process."""
    import subprocess
    subprocess.Popen(
        ["cmd.exe", "/c", bat_path],
        creationflags=(
            subprocess.CREATE_NEW_PROCESS_GROUP |
            subprocess.DETACHED_PROCESS
        ),
        close_fds=True,
    )


# ── Public high-level API ─────────────────────────────────────────────────────

class UpdaterJob:
    """
    Runs the full check → download → prepare cycle in a background thread.

    Callbacks are called from the worker thread — use ``root.after()`` or
    similar if updating Tkinter widgets.

    Parameters
    ----------
    on_status  : Callable[[str], None]
        Receives human-readable status messages.
    on_progress: Callable[[int, int], None]
        Receives (downloaded_bytes, total_bytes) during download.
    on_done    : Callable[[bool, str], None]
        Called when the job finishes. (success, message).
    on_ready   : Callable[[], None]
        Called when the update is fully prepared and ready to install.
        The caller should ask the user to confirm restart.
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
        self._tmp_dir:    Optional[str] = None
        self._src_dir:    Optional[str] = None
        self._cancelled   = threading.Event()

    def start(self) -> None:
        threading.Thread(target=self._run, daemon=True).start()

    def cancel(self) -> None:
        self._cancelled.set()

    def apply(self) -> None:
        """
        Write the updater .bat and signal the main process to quit.
        Must be called from the main thread after the user confirms.
        """
        if not self._src_dir:
            return

        dst_dir  = _app_root()
        tmp_dir  = tempfile.mkdtemp(prefix="gp_update_bat_")
        bat_path = os.path.join(tmp_dir, "apply_update.bat")

        if getattr(sys, "frozen", False):
            exe = os.path.join(dst_dir, os.path.basename(sys.executable))
            restart_cmd = f'"{exe}"'
        else:
            restart_cmd = f'"{sys.executable}" "{os.path.join(dst_dir, "main.py")}"'

        _write_updater_bat(
            bat_path    = bat_path,
            pid         = os.getpid(),
            src_dir     = self._src_dir,
            dst_dir     = dst_dir,
            restart_cmd = restart_cmd,
        )
        _launch_bat(bat_path)
        # Signal the app to quit — the bat will restart it
        import pygame
        pygame.event.post(pygame.event.Event(pygame.QUIT))

    def _run(self) -> None:
        try:
            self._on_status("Проверка обновлений…")
            release = fetch_latest_release()
            tag     = release.get("tag_name", "")
            name    = release.get("name", tag)

            if not is_newer(tag):
                self._on_done(True, f"Установлена последняя версия ({VERSION})")
                return

            if self._cancelled.is_set():
                return

            self._on_status(f"Доступна версия {tag} — загрузка…")

            asset = find_zip_asset(release)
            if asset:
                url      = asset["browser_download_url"]
            else:
                url      = release.get("zipball_url", "")
            if not url:
                self._on_done(False, "Архив релиза не найден")
                return

            self._tmp_dir = tempfile.mkdtemp(prefix="gp_update_")
            zip_path      = os.path.join(self._tmp_dir, "update.zip")

            def _prog(dl, total):
                if self._cancelled.is_set():
                    raise InterruptedError
                self._on_progress(dl, total)

            download_file(url, zip_path, _prog)

            if self._cancelled.is_set():
                return

            self._on_status("Распаковка…")
            extract_dir  = os.path.join(self._tmp_dir, "extracted")
            os.makedirs(extract_dir, exist_ok=True)
            self._src_dir = extract_zip(zip_path, extract_dir)

            self._on_status(f"Версия {tag} готова к установке")
            self._on_ready()

        except InterruptedError:
            self._on_status("Отменено")
        except Exception as exc:
            self._on_done(False, str(exc))
        finally:
            # Clean up zip but keep extracted dir until apply()
            if self._tmp_dir:
                zp = os.path.join(self._tmp_dir, "update.zip")
                if os.path.exists(zp):
                    try:
                        os.remove(zp)
                    except Exception:
                        pass
