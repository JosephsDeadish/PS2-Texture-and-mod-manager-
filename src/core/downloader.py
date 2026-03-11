"""Download utilities for PS2 Mod Manager.

Downloads files over HTTPS with progress callbacks.
No copyrighted content is fetched — only metadata/thumbnails from
open public APIs (GameTDB, GitHub, etc.) or user-provided URLs.
"""

import json
import os
import re
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


# ---------------------------------------------------------------------------
# MediaFire URL resolver
# ---------------------------------------------------------------------------

#: Regex matching a MediaFire file-page URL.
_MEDIAFIRE_FILE_RE = re.compile(
    r"https?://(?:www\.)?mediafire\.com/file/[^\s\"'<>]+",
    re.IGNORECASE,
)

#: Regex matching the direct-download href found inside MediaFire HTML pages.
_MEDIAFIRE_DL_RE = re.compile(
    r'href="(https?://download\d*\.mediafire\.com/[^"]+)"',
    re.IGNORECASE,
)


def resolve_mediafire_url(page_url: str, timeout: int = 15) -> Optional[str]:
    """Resolve a MediaFire *file* page URL to a direct HTTPS download URL.

    MediaFire file-page URLs look like::

        https://www.mediafire.com/file/<key>/<filename>/file

    The function fetches the page HTML and extracts the ``href`` of the
    ``<a id="downloadButton">`` element (or any ``download*.mediafire.com``
    link).  Returns the direct download URL on success, or ``None`` if the
    page could not be fetched, no link was found, or *page_url* is not a
    MediaFire file page.

    This function never raises; all errors are silently suppressed.
    """
    if not page_url:
        return None
    # Validate domain via URL parsing to avoid substring-match bypasses
    try:
        _parsed = urllib.parse.urlparse(page_url)
        netloc = _parsed.netloc.lower()
        if not (netloc == "www.mediafire.com" or netloc == "mediafire.com"):
            return None
        if "/file/" not in _parsed.path.lower():
            return None
    except Exception:
        return None
    try:
        resp = requests.get(
            page_url,
            timeout=timeout,
            headers={"User-Agent": _USER_AGENT},
            allow_redirects=True,
        )
        if resp.status_code != 200:
            return None
        html = resp.text

        # Primary: look for id="downloadButton" with an href
        m = re.search(
            r'<a[^>]+id=["\']downloadButton["\'][^>]+href=["\']([^"\']+)["\']',
            html,
            re.IGNORECASE,
        )
        if m:
            return m.group(1)

        # Fallback: any download*.mediafire.com href
        m2 = _MEDIAFIRE_DL_RE.search(html)
        if m2:
            return m2.group(1)

        return None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# GBAtemp thread scraper
# ---------------------------------------------------------------------------

#: PS2 game serial pattern: SLUS-20062, SCES-53133, SCUS-97399 …
#: Avoids plain \b because filenames use underscores which are \w characters.
_SERIAL_RE = re.compile(r"(?<![A-Za-z0-9])(S[LC][A-Z]{2}-\d{5})(?![A-Za-z0-9])", re.IGNORECASE)

#: (pattern, host-label) pairs for recognised download hosts.
_DOWNLOAD_PATTERNS: List[tuple] = [
    (re.compile(
        r"https?://(?:www\.)?mediafire\.com/(?:file|folder)/[^\s\"'<>]+",
        re.IGNORECASE,
    ), "MediaFire"),
    (re.compile(
        r"https?://drive\.google\.com/[^\s\"'<>]+",
        re.IGNORECASE,
    ), "Google Drive"),
    (re.compile(
        r"https?://mega\.nz/[^\s\"'<>]+",
        re.IGNORECASE,
    ), "MEGA"),
    (re.compile(
        r"https?://1drv\.ms/[^\s\"'<>]+",
        re.IGNORECASE,
    ), "OneDrive"),
    (re.compile(
        r"https?://(?:www\.)?dropbox\.com/[^\s\"'<>]+",
        re.IGNORECASE,
    ), "Dropbox"),
    (re.compile(
        r"https?://github\.com/[^\s\"'<>]+\.(?:zip|7z|pnach|rar)[^\s\"'<>]*",
        re.IGNORECASE,
    ), "GitHub"),
    (re.compile(
        r"https?://archive\.org/(?:download|details)/[^\s\"'<>]+",
        re.IGNORECASE,
    ), "Archive.org"),
]


def _make_download_label(url: str) -> str:
    """Derive a human-readable label from a download URL."""
    parsed = urllib.parse.urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]
    # For MediaFire /file/<key>/<filename>/file → use <filename>
    netloc = parsed.netloc.lower()
    if (netloc in ("www.mediafire.com", "mediafire.com")) and len(parts) >= 3:
        return urllib.parse.unquote(parts[-2]) if parts[-1] == "file" else urllib.parse.unquote(parts[-1])
    # MEGA file links: mega.nz/file/<id>#<key> — the URL path is opaque; return bare "MEGA Download"
    if "mega.nz" in netloc:
        return "MEGA Download"
    return urllib.parse.unquote(parts[-1]) if parts else url


#: Regex that matches a full anchor tag whose href contains a recognised download URL.
#: Group 1 = raw href value, Group 2 = anchor inner text (stripped of sub-tags).
_ANCHOR_HREF_RE = re.compile(
    r'<a\b[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
    re.DOTALL | re.IGNORECASE,
)

#: Maximum length of anchor text we consider as a useful label.
_MAX_ANCHOR_LABEL = 120


def _extract_anchor_label(href: str, html: str) -> Optional[str]:
    """Search *html* for an ``<a href="…">text</a>`` tag whose href matches *href*.

    Returns the cleaned anchor text if it is short enough to be a useful label
    (i.e. a game title or "Download" button label), otherwise returns ``None``.

    This allows the scraper to show "Baroque" instead of "MEGA Download" when
    the HTML looks like ``<a href="https://mega.nz/…">Baroque</a>``.
    """
    for m in _ANCHOR_HREF_RE.finditer(html):
        if href in m.group(1):
            text = re.sub(r"<[^>]+>", "", m.group(2)).strip()
            # Skip unhelpful generic labels
            if text and len(text) <= _MAX_ANCHOR_LABEL and text.lower() not in (
                "download", "here", "click here", "link", "mega", "mediafire",
                "google drive", "gdrive", "mirror",
            ):
                return text
    return None


def scrape_gbatemp_thread(thread_url: str, timeout: int = 15) -> Dict:
    """Scrape a GBAtemp page and extract mod metadata.

    Handles both GBAtemp thread pages (``/threads/…``) and GBAtemp resource/
    download pages (``/download/…``).

    Fetches *thread_url* and parses the HTML to extract:

    * **title** — the thread or resource title
    * **author** — display name of the thread author (first post or resource author)
    * **author_url** — absolute URL to the author's GBAtemp profile
    * **download_urls** — list of dicts, each with keys:

      * ``url``   — raw URL found in the page
      * ``host``  — host label (e.g. ``"MediaFire"``, ``"Google Drive"``)
      * ``label`` — human-readable file/folder name derived from the URL

    * **game_serial** — first PS2 serial found in the URL, title or post body
      (upper-cased, e.g. ``"SLUS-21372"``), or ``""`` if none detected
    * **source_url** — echoes back *thread_url*

    Returns a dict with the above keys (all empty/empty-list on failure).
    This function never raises; all errors are silently suppressed.
    """
    result: Dict = {
        "title": "",
        "author": "",
        "author_url": "",
        "download_urls": [],
        "game_serial": "",
        "source_url": thread_url,
    }
    try:
        resp = requests.get(
            thread_url,
            timeout=timeout,
            headers={"User-Agent": _USER_AGENT},
            allow_redirects=True,
        )
        if resp.status_code != 200:
            return result
        html = resp.text

        # ── Title ───────────────────────────────────────────────────────────
        # XenForo: <h1 class="p-title-value">…</h1>  (threads and downloads)
        m = re.search(
            r'<h1[^>]+class="[^"]*p-title-value[^"]*"[^>]*>(.*?)</h1>',
            html,
            re.DOTALL | re.IGNORECASE,
        )
        if m:
            result["title"] = re.sub(r"<[^>]+>", "", m.group(1)).strip()

        # ── Author name ─────────────────────────────────────────────────────
        # XenForo: itemprop="name" inside first message — works for threads
        m_name = re.search(
            r'<span[^>]+itemprop=["\']name["\'][^>]*>(.*?)</span>',
            html,
            re.DOTALL | re.IGNORECASE,
        )
        if m_name:
            result["author"] = re.sub(r"<[^>]+>", "", m_name.group(1)).strip()

        # For /download/ resource pages the author is in a "resource-author"
        # section or inside the first "p-description" author block.
        if not result["author"]:
            m_ra = re.search(
                r'<dt[^>]*>Author</dt>\s*<dd[^>]*>(.*?)</dd>',
                html,
                re.DOTALL | re.IGNORECASE,
            )
            if m_ra:
                result["author"] = re.sub(r"<[^>]+>", "", m_ra.group(1)).strip()

        # ── Author profile URL ───────────────────────────────────────────────
        # XenForo: <a class="username" href="/members/…"> or similar
        m_url = re.search(
            r'<a[^>]+class="[^"]*username[^"]*"[^>]+href="([^"]+)"',
            html,
            re.IGNORECASE,
        )
        if m_url:
            href = m_url.group(1)
            if href.startswith("/"):
                href = "https://gbatemp.net" + href
            result["author_url"] = href

        # ── Download links (external hosts) ─────────────────────────────────
        seen: set = set()
        for pattern, host in _DOWNLOAD_PATTERNS:
            for m_dl in pattern.finditer(html):
                raw = m_dl.group(0).rstrip(".,;)")
                if raw in seen:
                    continue
                seen.add(raw)
                # Try to get a meaningful label from the surrounding anchor tag
                # (e.g. "Baroque" instead of "MEGA Download" for a labelled MEGA link)
                anchor_label = _extract_anchor_label(raw, html)
                result["download_urls"].append({
                    "url": raw,
                    "host": host,
                    "label": anchor_label or _make_download_label(raw),
                })

        # For GBAtemp-hosted resource downloads (/download/ pages) also expose
        # the on-site download action URL so the scraper dialog can offer it.
        _psd = urllib.parse.urlparse(thread_url)
        if "/download/" in _psd.path:
            # XenForo resource manager: look for the "Download" button href
            # pattern: /download/<slug>/download
            m_gbadl = re.search(
                r'href="(/download/[^"]+/download)"',
                html,
                re.IGNORECASE,
            )
            if m_gbadl:
                dl_path = m_gbadl.group(1)
                gbatemp_dl = "https://gbatemp.net" + dl_path
                if gbatemp_dl not in seen:
                    seen.add(gbatemp_dl)
                    result["download_urls"].insert(0, {
                        "url": gbatemp_dl,
                        "host": "GBAtemp",
                        "label": "Download from GBAtemp (login required)",
                    })

        # ── PS2 game serial ──────────────────────────────────────────────────
        # Check in order: URL, title, then first 64 KB of body
        for text in (thread_url, result["title"], html[:65536]):
            m_ser = _SERIAL_RE.search(text)
            if m_ser:
                result["game_serial"] = m_ser.group(1).upper()
                break

    except Exception:
        pass

    return result


def scrape_ps2home_post(post_url: str, timeout: int = 15) -> Dict:
    """Scrape a PS2-Home forum topic page and extract mod/save metadata.

    Fetches *post_url* (a ``ps2-home.com/forum/viewtopic.php`` URL) and
    parses the phpBB HTML to extract:

    * **title** — the topic title
    * **author** — display name of the first post's author
    * **author_url** — ``""`` (PS2-Home does not expose profile URLs in a
      consistent way without login)
    * **download_urls** — list of dicts with ``url``, ``host``, ``label`` for
      any recognised download links (MediaFire, Google Drive, MEGA, etc.) found
      in the first post
    * **game_serial** — first PS2 serial found in the URL, title, or body
    * **source_url** — echoes back *post_url*

    Returns a dict with the above keys (all empty/empty-list on failure).
    This function never raises; all errors are silently suppressed.
    """
    result: Dict = {
        "title": "",
        "author": "",
        "author_url": "",
        "download_urls": [],
        "game_serial": "",
        "source_url": post_url,
    }
    try:
        resp = requests.get(
            post_url,
            timeout=timeout,
            headers={"User-Agent": _USER_AGENT},
            allow_redirects=True,
        )
        if resp.status_code != 200:
            return result
        html = resp.text

        # ── Topic title ──────────────────────────────────────────────────────
        # phpBB: <h2 class="topic-title">…</h2>  or  <title>Board… • Topic</title>
        m_t = re.search(
            r'<h[12][^>]+class="[^"]*topic-title[^"]*"[^>]*>(.*?)</h[12]>',
            html,
            re.DOTALL | re.IGNORECASE,
        )
        if m_t:
            result["title"] = re.sub(r"<[^>]+>", "", m_t.group(1)).strip()
        else:
            # Fallback: page <title>
            m_pt = re.search(r"<title>(.+?)</title>", html, re.IGNORECASE | re.DOTALL)
            if m_pt:
                raw = re.sub(r"<[^>]+>", "", m_pt.group(1)).strip()
                # phpBB titles look like "Board • View topic - Game Save Title"
                if " - " in raw:
                    raw = raw.split(" - ", 1)[-1].strip()
                result["title"] = raw

        # ── Author (first post) ─────────────────────────────────────────────
        # phpBB: <p class="author"> or <strong class="postauthor">
        m_a = re.search(
            r'<(?:strong|span)[^>]+class="[^"]*postauthor[^"]*"[^>]*>(.*?)</(?:strong|span)>',
            html,
            re.DOTALL | re.IGNORECASE,
        )
        if m_a:
            result["author"] = re.sub(r"<[^>]+>", "", m_a.group(1)).strip()

        # ── Download links ───────────────────────────────────────────────────
        # Also check for direct attachment links on ps2-home.com itself
        seen: set = set()
        for pattern, host in _DOWNLOAD_PATTERNS:
            for m_dl in pattern.finditer(html):
                raw = m_dl.group(0).rstrip(".,;)")
                if raw in seen:
                    continue
                seen.add(raw)
                anchor_label = _extract_anchor_label(raw, html)
                result["download_urls"].append({
                    "url": raw,
                    "host": host,
                    "label": anchor_label or _make_download_label(raw),
                })

        # phpBB attachments: <a href="./download/...">filename</a>
        _ps2home_base = "https://www.ps2-home.com/forum"
        for m_att in re.finditer(
            r'<a[^>]+href="(\./download/file\.php[^"]*)"[^>]*>(.*?)</a>',
            html,
            re.DOTALL | re.IGNORECASE,
        ):
            raw_href = m_att.group(1)
            label = re.sub(r"<[^>]+>", "", m_att.group(2)).strip() or "attachment"
            full_url = _ps2home_base + "/" + raw_href.lstrip("./")
            if full_url in seen:
                continue
            seen.add(full_url)
            result["download_urls"].append({
                "url": full_url,
                "host": "PS2-Home",
                "label": label,
            })

        # ── PS2 game serial ──────────────────────────────────────────────────
        for text in (post_url, result["title"], html[:65536]):
            m_ser = _SERIAL_RE.search(text)
            if m_ser:
                result["game_serial"] = m_ser.group(1).upper()
                break

    except Exception:
        pass

    return result
