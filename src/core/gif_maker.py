"""GIF creation utilities for PS2 Mod Manager."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Iterable

from PIL import Image

from src.core.ffmpeg_utils import resolve_ffmpeg_path


def _normalize_frames(frames: Iterable[str | Path], temp_dir: Path) -> list[Path]:
    normalized: list[Path] = []
    for idx, frame in enumerate(frames):
        src = Path(frame)
        if not src.exists():
            raise FileNotFoundError(f"Frame not found: {src}")
        out = temp_dir / f"frame_{idx:04d}.png"
        with Image.open(src) as img:
            img.convert("RGBA").save(out, format="PNG")
        normalized.append(out)
    return normalized


def create_gif(
    frames: Iterable[str | Path],
    output_path: str | Path,
    *,
    duration_ms: int = 100,
    loop: int = 0,
    prefer_ffmpeg: bool = True,
) -> bool:
    """Create a GIF from frames and return True if ffmpeg was used."""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    if duration_ms <= 0:
        raise ValueError("duration_ms must be greater than 0")

    ffmpeg_path = resolve_ffmpeg_path() if prefer_ffmpeg else None
    if ffmpeg_path:
        fps = max(1.0, 1000.0 / float(duration_ms))
        with tempfile.TemporaryDirectory(prefix="ps2mm_gif_") as tmp_dir:
            tmp_path = Path(tmp_dir)
            _normalize_frames(frames, tmp_path)
            cmd = [
                ffmpeg_path,
                "-y",
                "-framerate",
                f"{fps:.4f}",
                "-i",
                str(tmp_path / "frame_%04d.png"),
                "-vf",
                "scale=trunc(iw/2)*2:trunc(ih/2)*2:flags=lanczos",
                "-loop",
                str(loop),
                str(output),
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or "ffmpeg failed to create GIF.")
        return True

    # Pillow fallback
    frames_list = [Path(p) for p in frames]
    if not frames_list:
        raise ValueError("No frames provided")
    images = []
    for path in frames_list:
        with Image.open(path) as img:
            images.append(img.convert("RGBA"))
    base, *rest = images
    base.save(
        output,
        save_all=True,
        append_images=rest,
        duration=duration_ms,
        loop=loop,
        format="GIF",
        optimize=False,
    )
    return False
