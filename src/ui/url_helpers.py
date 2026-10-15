"""Small helpers for opening external URLs from the UI."""

from __future__ import annotations

import logging
import webbrowser
from typing import Optional

logger = logging.getLogger(__name__)


def open_external_url(
    url: str,
    *,
    parent=None,
    context: str = "external link",
    title: str = "Open Link Failed",
    failure_message: Optional[str] = None,
) -> bool:
    """Open *url* in the user's browser and warn if it fails.

    Parameters
    ----------
    url:
        The URL to open.
    parent:
        Optional Qt parent used for the warning dialog.
    context:
        Human-readable description used in log messages.
    title:
        Warning dialog title shown on failure.
    failure_message:
        Optional custom message shown to the user if opening fails.
    """
    if failure_message is None:
        failure_message = f"Could not open the {context}."

    try:
        opened = webbrowser.open(url, new=2)
    except Exception as exc:
        logger.warning("Failed to open %s %s: %s", context, url, exc)
        opened = False

    if opened:
        return True

    logger.warning("Failed to open %s %s: browser refused", context, url)
    if parent is not None:
        from PyQt6.QtWidgets import QMessageBox

        QMessageBox.warning(parent, title, failure_message)
    return False
