from __future__ import annotations

import pytest

from utils import seconds_to_srt_time, srt_time_to_seconds


def test_srt_time_to_seconds():
    assert srt_time_to_seconds("00:00:05,000") == 5.0
    assert srt_time_to_seconds("00:01:30,500") == 90.5
    assert srt_time_to_seconds("01:00:00,000") == 3600.0
    assert srt_time_to_seconds("00:00:05.000") == 5.0


def test_srt_time_to_seconds_two_parts():
    assert srt_time_to_seconds("01:30,500") == 90.5


def test_srt_time_to_seconds_invalid():
    with pytest.raises(ValueError):
        srt_time_to_seconds("bad_format")


def test_seconds_to_srt_time():
    assert seconds_to_srt_time(5.0) == "00:00:05.000"
    assert seconds_to_srt_time(90.5) == "00:01:30.500"
    assert seconds_to_srt_time(3600.0) == "01:00:00.000"
