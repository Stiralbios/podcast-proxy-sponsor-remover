from __future__ import annotations

import subprocess

import pytest

from ffmpeg_segments import _build_aselect_expr, mark_segments, remove_segments
from utils import srt_time_to_seconds


def test_build_aselect_expr():
    segments = [
        {"start_time": "00:00:10.000", "end_time": "00:00:20.000"},
        {"start_time": "00:01:00.000", "end_time": "00:01:30.000"},
    ]
    expr = _build_aselect_expr(segments)
    assert "between(t\\,10.0\\,20.0)" in expr
    assert "between(t\\,60.0\\,90.0)" in expr
    assert expr.startswith("not(")
    assert expr.endswith(")")


def test_build_aselect_expr_empty():
    assert _build_aselect_expr([]) == ""


def test_remove_segments_empty_returns_original(tmp_path):
    input_path = tmp_path / "input.mp3"
    input_path.write_bytes(b"audio_data")
    output_path = tmp_path / "output.mp3"
    result = remove_segments(input_path, [], output_path)
    assert result == input_path
    assert not output_path.exists()


def test_remove_segments_real_audio(tmp_path):
    """Create a 3-second MP3, remove the middle 1 second."""
    input_path = tmp_path / "input.mp3"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f", "lavfi",
            "-i", "anullsrc=r=44100:cl=mono",
            "-t", "3",
            "-acodec", "libmp3lame",
            "-q:a", "4",
            str(input_path),
        ],
        check=True,
        capture_output=True,
    )

    segments = [{"start_time": "00:00:01.000", "end_time": "00:00:02.000"}]
    output_path = tmp_path / "output.mp3"
    remove_segments(input_path, segments, output_path)

    assert output_path.exists()
    assert output_path.stat().st_size > 0

    # Verify duration is approximately 2 seconds
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(output_path)],
        capture_output=True,
        text=True,
        check=True,
    )
    duration = float(probe.stdout.strip())
    assert 1.5 <= duration <= 2.5


def test_mark_segments_adds_chapters(tmp_path):
    """Create a 3-second MP3; mark two short ad segments and verify chapters."""
    input_path = tmp_path / "input.mp3"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f", "lavfi",
            "-i", "anullsrc=r=44100:cl=mono",
            "-t", "3",
            "-acodec", "libmp3lame",
            "-q:a", "4",
            str(input_path),
        ],
        check=True,
        capture_output=True,
    )
    segments = [
        {"start_time": "00:00:01.000", "end_time": "00:00:02.000"},
    ]
    output_path = tmp_path / "marked.mp3"
    mark_segments(input_path, segments, output_path)

    assert output_path.exists()
    assert output_path.stat().st_size > 0

    # Verify duration unchanged
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(output_path)],
        capture_output=True,
        text=True,
        check=True,
    )
    duration = float(probe.stdout.strip())
    assert 2.8 <= duration <= 3.2

    # Verify chapters (ffprobe -show_chapters)
    probe2 = subprocess.run(
        ["ffprobe", "-v", "error", "-show_chapters", "-print_format", "json", str(output_path)],
        capture_output=True,
        text=True,
        check=True,
    )
    data = __import__("json").loads(probe2.stdout)
    chapters = data.get("chapters", [])
    assert len(chapters) == 3  # Content, Ad, Content
    titles = [ch["tags"]["title"] for ch in chapters]
    assert "Content" in titles
    assert "Ad / Sponsor" in titles
    assert titles == ["Content", "Ad / Sponsor", "Content"]


def test_mark_segments_no_segments_copies(tmp_path):
    input_path = tmp_path / "input.mp3"
    input_path.write_bytes(b"audio_data")
    output_path = tmp_path / "out.mp3"
    result = mark_segments(input_path, [], output_path)
    assert result == input_path
    assert not output_path.exists()