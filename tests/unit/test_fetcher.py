from __future__ import annotations

import feedparser
import pytest
import requests

import fetcher
from fetcher import download_media, fetch_feed


class FakeResponse:
    def __init__(self, text: str = "", content: bytes = b"", status_code: int = 200):
        self.text = text
        self._content = content
        self.status_code = status_code
        self.headers = {"content-type": "application/rss+xml"}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}")

    def iter_content(self, chunk_size: int = 1):
        for i in range(0, len(self._content), chunk_size):
            yield self._content[i : i + chunk_size]


RSS_XML = """\<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Test Podcast</title>
    <item>
      <title>Episode 1</title>
      <guid isPermaLink="false">guid-1</guid>
      <enclosure url="https://example.com/ep1.mp3" length="1234" type="audio/mpeg"/>
    </item>
  </channel>
</rss>
"""


def test_fetch_feed(monkeypatch):
    def fake_get(*args, **kwargs):
        return FakeResponse(text=RSS_XML)

    monkeypatch.setattr(fetcher.requests.Session, "get", fake_get)
    raw, parsed = fetch_feed("https://example.com/feed.rss")
    assert "Test Podcast" in raw
    assert parsed.feed.title == "Test Podcast"
    assert len(parsed.entries) == 1
    assert parsed.entries[0].id == "guid-1"


def test_download_media(tmp_path, monkeypatch):
    data = b"fake_audio_data" * 100

    def fake_get(*args, **kwargs):
        return FakeResponse(content=data)

    monkeypatch.setattr(fetcher.requests.Session, "get", fake_get)
    dest = tmp_path / "audio.mp3"
    download_media("https://example.com/audio.mp3", dest)
    assert dest.exists()
    assert dest.stat().st_size == len(data)


def test_fetch_feed_404(monkeypatch):
    def fake_get(*args, **kwargs):
        return FakeResponse(status_code=404)

    monkeypatch.setattr(fetcher.requests.Session, "get", fake_get)
    with pytest.raises(requests.HTTPError):
        fetch_feed("https://example.com/missing.rss")
