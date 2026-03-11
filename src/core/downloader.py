"""Download utilities for PS2 Mod Manager.

Downloads files over HTTPS with progress callbacks.
No copyrighted content is fetched — only metadata/thumbnails from
open public APIs (GameTDB, GitHub, etc.) or user-provided URLs.
"""

import json
import os
import threading
import urllib.parse
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import requests

# Common User-Agent header used across all requests from this module
_USER_AGENT = "PS2ModManager/1.0 (+https://github.com/JosephsDeadish/PS2-Texture-and-mod-manager-)"
_GITHUB_HEADERS = {
    "Accept": "application/vnd.github.v3+json",
    "User-Agent": _USER_AGENT,
}


class DownloadError(Exception):
    pass


def download_file(
    url: str,
    dest_path: str,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    timeout: int = 30,
) -> str:
    """
    Download *url* to *dest_path*.

    *progress_callback(bytes_received, total_bytes)* is called periodically.
    Returns the destination path on success.
    Raises DownloadError on failure.
    """
    dest = Path(dest_path)
    dest.parent.mkdir(parents=True, exist_ok=True)

    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise DownloadError(f"Only http/https URLs are supported, got: {url!r}")

    try:
        with requests.get(url, stream=True, timeout=timeout) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("Content-Length", 0))
            received = 0
            with open(dest, "wb") as f:
                for chunk in resp.iter_content(chunk_size=65536):
                    if chunk:
                        f.write(chunk)
                        received += len(chunk)
                        if progress_callback:
                            progress_callback(received, total)
    except requests.RequestException as exc:
        raise DownloadError(f"Download failed: {exc}") from exc

    return str(dest)


class AsyncDownloader:
    """Non-blocking downloader that runs in a background thread."""

    def __init__(self):
        self._thread: Optional[threading.Thread] = None
        self._cancel_event = threading.Event()

    def start(
        self,
        url: str,
        dest_path: str,
        on_progress: Optional[Callable[[int, int], None]] = None,
        on_complete: Optional[Callable[[str], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
    ):
        """
        Start an asynchronous download in a background thread.

        Cancellation works by setting a threading.Event that is checked inside
        the progress callback.  When set, the callback raises DownloadError
        which propagates up through download_file() and is caught here,
        invoking on_error with a "Download cancelled" message.
        """
        self._cancel_event.clear()

        def _run():
            try:
                def _progress(received, total):
                    if self._cancel_event.is_set():
                        raise DownloadError("Download cancelled")
                    if on_progress:
                        on_progress(received, total)

                path = download_file(url, dest_path, _progress)
                if on_complete:
                    on_complete(path)
            except DownloadError as exc:
                if on_error:
                    on_error(str(exc))

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()

    def cancel(self):
        self._cancel_event.set()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()


def fetch_gametdb_art(game_id: str, dest_dir: str, region: str = "EN") -> Optional[str]:
    """
    Download cover art from GameTDB (https://www.gametdb.com) for *game_id*.
    GameTDB provides free cover images; no copyrighted content is transferred
    beyond what is publicly hosted by the service.
    Returns local path or None on failure.
    """
    url = f"https://art.gametdb.com/ps2/cover/{region}/{game_id}.jpg"
    dest = str(Path(dest_dir) / f"{game_id}.jpg")
    try:
        download_file(url, dest, timeout=10)
        return dest
    except DownloadError:
        return None


# ---------------------------------------------------------------------------
# Online game title lookup (GameTDB)
# ---------------------------------------------------------------------------

def lookup_game_title_online(serial: str, timeout: int = 5) -> str:
    """
    Look up the PS2 game title for *serial* from the GameTDB database.

    Makes a request to the GameTDB website to retrieve the game title for
    serials that are not present in the local ``_KNOWN_SERIALS`` registry.
    GameTDB is a free, community-maintained database (https://www.gametdb.com).

    Returns the game title string, or ``""`` on any error or if not found.
    This function never raises; all errors are silently suppressed.
    """
    if not serial:
        return ""
    serial_clean = serial.upper().strip()
    try:
        url = f"https://www.gametdb.com/PS2/{serial_clean}"
        resp = requests.get(
            url,
            timeout=timeout,
            headers={"User-Agent": _USER_AGENT},
            allow_redirects=True,
        )
        if resp.status_code != 200:
            return ""
        # Parse game title from HTML (GameTDB page title follows pattern "<title>SERIAL - Game Title | GameTDB</title>")
        import re
        m = re.search(r"<title>\s*[^<\-]+\s*[-–]\s*(.+?)\s*[|]", resp.text)
        if m:
            title = m.group(1).strip()
            # Filter out "GameTDB" itself
            if title and title.lower() not in ("gametdb", "ps2", ""):
                return title
        return ""
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# PCSX2 widescreen PNACH index + download (GitHub)
# ---------------------------------------------------------------------------

# GitHub API endpoint for the PCSX2 widescreen patches directory
_PCSX2_WS_API = (
    "https://api.github.com/repos/PCSX2/pcsx2/contents/bin/cheats_ws"
)
# GitHub API endpoint for the PCSX2 community cheat database
_PCSX2_CHEATDB_API = (
    "https://api.github.com/repos/PCSX2/cheatdb/contents"
)
# Raw content base URL (bypasses the GitHub API rate limit for small files)
_PCSX2_WS_RAW = (
    "https://raw.githubusercontent.com/PCSX2/pcsx2/master/bin/cheats_ws/"
)


def list_pcsx2_widescreen_patches(timeout: int = 10) -> List[Dict]:
    """
    Fetch the list of available widescreen PNACH patches from the official
    PCSX2 GitHub repository (``bin/cheats_ws/``).

    Returns a list of dicts, each with:
        ``crc``          — 8-char hex game CRC (upper-case)
        ``filename``     — e.g. ``F0A235B4.pnach``
        ``download_url`` — direct raw download URL

    Returns an empty list on any network error.
    This function is designed to be called from a background thread.
    """
    try:
        resp = requests.get(
            _PCSX2_WS_API,
            timeout=timeout,
            headers=_GITHUB_HEADERS,
        )
        resp.raise_for_status()
        entries = resp.json()
        result = []
        for entry in entries:
            name = entry.get("name", "")
            if name.lower().endswith(".pnach"):
                crc = name[:-6].upper()
                result.append({
                    "crc": crc,
                    "filename": name,
                    "download_url": entry.get(
                        "download_url",
                        f"{_PCSX2_WS_RAW}{name}",
                    ),
                })
        return result
    except Exception:
        return []


def download_pcsx2_widescreen_patch(crc: str, dest_dir: str, timeout: int = 15) -> Optional[str]:
    """
    Download the widescreen PNACH patch for *crc* from the PCSX2 GitHub
    repository into *dest_dir*.

    *crc* should be an 8-character hex string (case-insensitive).
    Returns the local file path on success, or ``None`` on failure.
    """
    crc_upper = crc.upper().strip()
    filename = f"{crc_upper}.pnach"
    url = f"{_PCSX2_WS_RAW}{filename}"
    dest = str(Path(dest_dir) / filename)
    try:
        download_file(url, dest, timeout=timeout)
        return dest
    except DownloadError:
        return None


def search_pcsx2_patches_by_crc(
    crc: str,
    timeout: int = 10,
) -> Optional[Dict]:
    """
    Check whether a widescreen PNACH exists in the PCSX2 GitHub repository
    for the given 8-digit CRC.

    Returns a dict ``{"crc": ..., "filename": ..., "download_url": ...}``
    if found, or ``None`` if not found or on network error.
    """
    crc_upper = crc.upper().strip()
    filename = f"{crc_upper}.pnach"
    url = f"{_PCSX2_WS_RAW}{filename}"
    try:
        resp = requests.head(url, timeout=timeout, allow_redirects=True,
                             headers={"User-Agent": _USER_AGENT})
        if resp.status_code == 200:
            return {
                "crc": crc_upper,
                "filename": filename,
                "download_url": url,
            }
        return None
    except Exception:
        return None
