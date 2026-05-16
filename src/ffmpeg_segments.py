"""FFmpeg helpers to cut out or mark sponsor/ad segments in an audio file."""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

from utils import srt_time_to_seconds, seconds_to_srt_time

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


def mark_segments(
    audio_path: str | Path,
    segments: list[dict],
    output_path: str | Path,
    new_chapter_label: str = "Ad / Sponsor",
) -> Path:
    """Embed detected ad segments as chapter markers in an MP3.

    Preserves existing metadata and cover art. Each ad segment is added as a
    chapter titled *new_chapter_label*. Gaps between ads are labeled as regular
    content chapters. Returns the output path.
    """
    if not segments:
        logger.info("No segments to mark, returning original")
        return Path(audio_path)

    audio_path = Path(audio_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # 1. Extract existing cover art
    stem = output_path.stem
    parent = output_path.parent
    cover_path = parent / f"{stem}_mark_cover.jpg"
    try:
        _run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(audio_path),
                "-an",
                "-vcodec",
                "copy",
                str(cover_path),
            ]
        )
    except subprocess.CalledProcessError as exc:
        if "does not contain any stream" in exc.stderr:
            logger.info("No cover art found in %s, skipping cover extraction", audio_path)
        else:
            raise

    # 2. Build FFMetadata file with chapters
    duration, existing_chapters = _probe_chapters(audio_path)
    if duration <= 0.0:
        duration = max(srt_time_to_seconds(seg["end_time"]) for seg in segments)

    ad_ranges = sorted(
        {
            (srt_time_to_seconds(s["start_time"]), srt_time_to_seconds(s["end_time"]))
            for s in segments
        }
    )
    # Merge overlapping / touching segments
    merged_ads: list[tuple[float, float]] = []
    for start, end in ad_ranges:
        if merged_ads and start <= merged_ads[-1][1]:
            merged_ads[-1] = (merged_ads[-1][0], max(merged_ads[-1][1], end))
        else:
            merged_ads.append((start, end))

    # Build chapter intervals: [0, ad0_start], [ad0_start, ad0_end], [ad0_end, ad1_start], ...
    intervals: list[tuple[float, float, str]] = []
    prev = 0.0
    for start, end in merged_ads:
        if start > prev and (start - prev) > 0.001:
            intervals.append((prev, start, "Content"))
        intervals.append((start, end, new_chapter_label))
        prev = end
    if prev < duration and (duration - prev) > 0.001:
        intervals.append((prev, duration, "Content"))

    # Also include existing non-ad chapters (if the source already had chapters)
    # We keep them if they don't overlap with detected ad ranges.
    kept_existing: list[tuple[float, float, str]] = []
    for ch in existing_chapters:
        cs, ce = ch["start"], ch["end"]
        overlap = False
        for start, end in merged_ads:
            if ce > start and cs < end:
                overlap = True
                break
        if not overlap:
            kept_existing.append((cs, ce, ch["title"]))

    all_intervals = kept_existing + intervals
    all_intervals.sort(key=lambda x: x[0])

    metadata = _build_ffmetadata(all_intervals)
    meta_path = parent / f"{stem}_meta.txt"
    meta_path.write_text(metadata, encoding="utf-8")

    # 3. Remux with metadata
    temp_out = parent / f"{stem}_mark_tmp.mp3"
    _run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(audio_path),
            "-i",
            str(meta_path),
            "-map_metadata",
            "1",
            "-map",
            "0",
            "-c:0",
            "copy",
            "-id3v2_version",
            "3",
            str(temp_out),
        ]
    )

    # 4. Attach cover art back
    has_cover = cover_path.exists() and cover_path.stat().st_size > 0
    if has_cover:
        _run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(temp_out),
                "-i",
                str(cover_path),
                "-c:0",
                "copy",
                "-c:v",
                "copy",
                "-map",
                "0:a",
                "-map",
                "1:v",
                "-map_metadata",
                "0",
                str(output_path),
            ]
        )
    else:
        os.replace(temp_out, output_path)

    # Cleanup
    for p in (cover_path, meta_path, temp_out):
        if Path(p).exists():
            os.remove(p)

    return output_path


def _probe_chapters(audio_path: Path) -> tuple[float, list[dict]]:
    """Probe an audio file for duration and existing chapters via ffprobe."""
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_chapters",
        "-show_entries",
        "format=duration",
        "-print_format",
        "json",
        str(audio_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        import json

        data = json.loads(result.stdout)
        duration = float(data.get("format", {}).get("duration", 0))
        chapters = []
        for ch in data.get("chapters", []):
            chapters.append(
                {
                    "start": float(ch.get("start_time", 0)),
                    "end": float(ch.get("end_time", 0)),
                    "title": ch.get("tags", {}).get("title", "Chapter"),
                }
            )
        return duration, chapters
    except Exception:
        logger.debug("ffprobe chapter detection failed for %s", audio_path)
        return 0.0, []


def _build_ffmetadata(intervals: list[tuple[float, float, str]]) -> str:
    """Convert (start, end, title) intervals to FFMetadata chapter format.

    TIMEBASE=1/1000 is used to keep millisecond precision with integer values.
    """
    lines = [";FFMETADATA1", ""]
    for idx, (start, end, title) in enumerate(intervals, 1):
        start_ms = int(round(start * 1000))
        end_ms = int(round(end * 1000))
        lines.extend(
            [
                "[CHAPTER]",
                "TIMEBASE=1/1000",
                f"START={start_ms}",
                f"END={end_ms}",
                f"id={idx}",
                f"title={title}",
                "",
            ]
        )
    return "\n".join(lines)


def _run(cmd: list[str]) -> None:
    """Run an ffmpeg command, raising on failure."""
    logger.debug("Running: %s", " ".join(cmd))
    subprocess.run(cmd, check=True, capture_output=True, text=True)
