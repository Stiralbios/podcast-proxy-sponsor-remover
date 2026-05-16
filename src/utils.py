"""Utility helpers."""

from __future__ import annotations


def srt_time_to_seconds(time_str: str) -> float:
    """Convert an SRT timestamp 'HH:MM:SS,mmm' or 'HH:MM:SS.mmm' to seconds."""
    time_str = time_str.replace(",", ".")
    parts = time_str.split(":")
    if len(parts) == 3:
        h, m, s = parts
    elif len(parts) == 2:
        h = 0
        m, s = parts
    else:
        raise ValueError(f"Invalid SRT time format: {time_str}")
    return int(h) * 3600 + int(m) * 60 + float(s)


def seconds_to_srt_time(seconds: float) -> str:
    """Convert seconds to SRT timestamp 'HH:MM:SS.mmm'."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:06.3f}"


def _seconds_to_srt_timestamp(seconds: float) -> str:
    """Convert seconds to HH:MM:SS,mmm format for SRT."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:06.3f}".replace(".", ",")
