"""Download utilities for PS2 Mod Manager.

Downloads files over HTTPS with progress callbacks.
No copyrighted content is fetched — only metadata/thumbnails from
open public APIs (GameTDB, etc.) or user-provided URLs.
"""

import os
import threading
import urllib.parse
from pathlib import Path
from typing import Callable, Optional

import requests


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
