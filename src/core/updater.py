"""Mod update checking utilities for PS2 Mod Manager.

Checks whether installed mods have known updates available by comparing
version strings against source metadata (where a source URL is known and
the source provides a version endpoint).

This module is intentionally lightweight — it only contacts URLs that the
user has explicitly associated with a mod as a source.  It never phones
home on its own.
"""

from __future__ import annotations

import threading
from typing import Callable, Dict, List, Optional, Tuple

from src.core.mod_manager import ModDatabase
from src.models.mod import ModInfo


def _check_single_mod(mod: ModInfo) -> Tuple[str, bool]:
    """
    Return ``(mod_id, has_update)`` for a single mod.

    Currently uses a simple heuristic:
    - If the mod has no source_url, no update can be checked → False.
    - If the source is a GitHub Releases URL we try to fetch the latest
      release tag and compare against mod.version.
    - For all other sources we fall back to False (cannot determine).
    """
    if not mod.source_url:
        return mod.id, False

    url = mod.source_url.strip()

    # GitHub Releases heuristic — validate the hostname via proper URL parsing
    # to prevent substring-matching attacks (e.g. evil.com/github.com/).
    try:
        import urllib.parse
        parsed = urllib.parse.urlparse(url)
        is_github = (
            parsed.scheme in ("https", "http")
            and parsed.hostname is not None
            and (parsed.hostname == "github.com" or parsed.hostname.endswith(".github.com"))
        )
    except Exception:
        is_github = False

    if is_github:
        try:
            import urllib.request
            import json

            # e.g. https://github.com/OWNER/REPO/… → API call
            parts = parsed.path.strip("/").split("/")
            if len(parts) >= 2:
                owner = parts[0]
                repo = parts[1]
                api_url = f"https://api.github.com/repos/{owner}/{repo}/releases/latest"
                req = urllib.request.Request(
                    api_url,
                    headers={"User-Agent": "PS2ModManager/1.0", "Accept": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=8) as resp:
                    data = json.loads(resp.read())
                latest_tag = data.get("tag_name", "").lstrip("v")
                current = mod.version.lstrip("v")
                if latest_tag and current and latest_tag != current:
                    return mod.id, True
        except Exception:
            pass

    return mod.id, False


class UpdateChecker:
    """
    Background update checker.

    Usage::

        checker = UpdateChecker(db)
        checker.start(on_result=lambda mod_id, has_update: ...)

    ``on_result`` is called from the background thread for every mod that
    has an update.  The caller must ensure thread-safe UI updates (e.g.
    via Qt signals).
    """

    def __init__(self, db: ModDatabase):
        self.db = db
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def start(
        self,
        on_result: Optional[Callable[[str, bool], None]] = None,
        on_complete: Optional[Callable[[int], None]] = None,
    ):
        """
        Start checking in a background thread.

        ``on_result(mod_id, has_update)`` is called for every mod.
        ``on_complete(updates_found)`` is called when all mods have been checked.
        """
        self._stop_event.clear()

        def _run():
            mods = self.db.all()
            updates = 0
            for mod in mods:
                if self._stop_event.is_set():
                    break
                mod_id, has_update = _check_single_mod(mod)
                if has_update:
                    # Persist the flag
                    mod.has_update = True
                    try:
                        self.db.update(mod)
                    except Exception:
                        pass
                    updates += 1
                if on_result:
                    on_result(mod_id, has_update)
            if on_complete:
                on_complete(updates)

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()
