"""FFmpeg helpers to cut out sponsor/ad segments from an audio file."""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

from utils import srt_time_to_seconds

logger = logging.getLogger(__name__)


def _build_aselect_expr(segments: list[dict]) -> str:
    """Build an ffmpeg aselect filter expression that *excludes* the given segments."""
    if not segments:
        return ""
    clauses = []
    for seg in segments:
        start = srt_time_to_seconds(seg["start_time"])
        end = srt_time_to_seconds(seg["end_time"])
        clauses.append(f"between(t\\,{start}\\,{end})")
    joined = "+".join(clauses)
    return f"not({joined})"


def remove_segments(
    audio_path: str | Path,
    segments: list[dict],
    output_path: str | Path,
) -> Path:
    """Remove ad segments from an MP3 file, preserving metadata and cover art.

    Returns the path to the new MP3 (or the original path if no segments to remove).
    """
    if not segments:
        logger.info("No segments to remove, returning original")
        return Path(audio_path)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    stem = output_path.stem
    parent = output_path.parent

    # Step 1: try to extract cover art (if any) to a temp file
    cover_path = parent / f"{stem}_cover.jpg"
    try:
        _run(
            [
                "ffmpeg",
                "-y",
                "-i", str(audio_path),
                "-an",
                "-vcodec", "copy",
                str(cover_path),
            ]
        )
    except subprocess.CalledProcessError as exc:
        if "does not contain any stream" in exc.stderr:
            logger.info("No cover art found in %s, skipping cover extraction", audio_path)
        else:
            raise

    # Step 2: cut out sponsor segments
    aselect = _build_aselect_expr(segments)
    temp_audio = parent / f"{stem}_temp.mp3"
    _run(
        [
            "ffmpeg",
            "-y",
            "-i", str(audio_path),
            "-af", f"aselect='{aselect}',asetpts=N/SR/TB",
            "-c:a", "libmp3lame",
            "-b:a", "128k",
            "-map_metadata", "0",
            str(temp_audio),
        ]
    )

    # Step 3: merge cover art back in
    has_cover = cover_path.exists() and cover_path.stat().st_size > 0
    if has_cover:
        _run(
            [
                "ffmpeg",
                "-y",
                "-i", str(temp_audio),
                "-i", str(cover_path),
                "-c:a", "copy",
                "-c:v", "copy",
                "-map", "0:a",
                "-map", "1:v",
                "-map_metadata", "0",
                str(output_path),
            ]
        )
    else:
        os.replace(temp_audio, output_path)

    # Cleanup
    for p in (cover_path, temp_audio):
        if Path(p).exists():
            os.remove(p)

    return output_path


def _run(cmd: list[str]) -> None:
    """Run an ffmpeg command, raising on failure."""
    logger.debug("Running: %s", " ".join(cmd))
    subprocess.run(cmd, check=True, capture_output=True, text=True)
