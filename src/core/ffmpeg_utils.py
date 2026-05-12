"""FFmpeg discovery utilities for PS2 Mod Manager."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Optional


def resolve_ffmpeg_path(
    preferred: str | None = None,
    *,
    allow_download: bool = True,
) -> Optional[str]:
    """Return a usable ffmpeg executable path, or ``None`` if not found."""
    if preferred:
        path = Path(preferred)
        if path.exists():
            return str(path)

    env_path = os.getenv("PS2MM_FFMPEG_PATH") or os.getenv("FFMPEG_PATH")
    if env_path:
        env_path = Path(env_path)
        if env_path.exists():
            return str(env_path)

    if allow_download:
        try:
            import imageio_ffmpeg  # type: ignore

            ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
            if ffmpeg_path and Path(ffmpeg_path).exists():
                return str(ffmpeg_path)
        except Exception:
            pass

    return shutil.which("ffmpeg")


def ffmpeg_available(preferred: str | None = None, *, allow_download: bool = False) -> bool:
    """Return True if ffmpeg can be resolved."""
    return bool(resolve_ffmpeg_path(preferred, allow_download=allow_download))
