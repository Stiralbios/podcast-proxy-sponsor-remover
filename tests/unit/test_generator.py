from __future__ import annotations

import calendar
import time

import feedparser

import generator
from config import FeedConfig
from generator import _first_audio_enclosure, _struct_time_to_datetime, generate_atom


RSS_XML = """\<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Test Podcast</title>
    <description>A test feed</description>
    <link>https://example.com/</link>
    <language>en</language>
    <item>
      <title>Episode 1</title>
      <guid isPermaLink="false">guid-1</guid>
      <link>https://example.com/ep1</link>
      <pubDate>Mon, 01 Jan 2024 00:00:00 GMT</pubDate>
      <enclosure url="https://example.com/ep1.mp3" length="1234" type="audio/mpeg"/>
    </item>
    <item>
      <title>Episode 2</title>
      <guid isPermaLink="false">guid-2</guid>
      <link>https://example.com/ep2</link>
      <pubDate>Tue, 02 Jan 2024 00:00:00 GMT</pubDate>
      <enclosure url="https://example.com/ep2.mp3" length="5678" type="audio/mpeg"/>
    </item>
  </channel>
</rss>
"""


def test_struct_time_to_datetime():
    st = time.gmtime(1704067200)
    dt = _struct_time_to_datetime(st)
    assert dt is not None
    assert dt.year == 2024
    assert dt.month == 1
    assert dt.day == 1
    assert dt.tzinfo is not None
    assert dt.utcoffset().total_seconds() == 0


def test_first_audio_enclosure():
    parsed = feedparser.parse(RSS_XML)
    entry = parsed.entries[0]
    enc = _first_audio_enclosure(entry)
    assert enc is not None
    assert enc["href"] == "https://example.com/ep1.mp3"
    assert enc["type"] == "audio/mpeg"


def test_generate_atom_guid_match():
    parsed = feedparser.parse(RSS_XML)
    cfg = FeedConfig(
        feed_url="https://example.com/feed.rss",
        keep_article=10,
        podcast_slug="test-podcast",
    )
    entries = parsed.entries[: cfg.keep_article]
    media_urls = {
        "https://example.com/ep1.mp3": "abc123.mp3",
        "https://example.com/ep2.mp3": "def456.mp3",
    }
    xml = generate_atom(cfg, parsed, entries, media_urls, "https://proxy.example.com")

    # Round-trip parse and verify GUIDs match exactly
    reparsed = feedparser.parse(xml)
    assert len(reparsed.entries) == 2
    assert reparsed.entries[0].id == "guid-1"
    assert reparsed.entries[1].id == "guid-2"

    # Verify enclosure URLs point to proxy
    assert reparsed.entries[0].enclosures[0].href == "https://proxy.example.com/test-podcast/new/media/abc123.mp3"
    assert reparsed.entries[1].enclosures[0].href == "https://proxy.example.com/test-podcast/new/media/def456.mp3"


def test_generate_atom_respects_keep_article():
    parsed = feedparser.parse(RSS_XML)
    cfg = FeedConfig(
        feed_url="https://example.com/feed.rss",
        keep_article=1,
        podcast_slug="test-podcast",
    )
    entries = parsed.entries[: cfg.keep_article]
    xml = generate_atom(cfg, parsed, entries, {}, "https://proxy.example.com")
    reparsed = feedparser.parse(xml)
    assert len(reparsed.entries) == 1


def test_generate_atom_requires_author():
    rss_no_author = """\<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>No Author Feed</title>
    <item>
      <title>Episode 1</title>
      <guid>guid-1</guid>
      <enclosure url="https://example.com/ep1.mp3" length="1234" type="audio/mpeg"/>
    </item>
  </channel>
</rss>
"""
    parsed = feedparser.parse(rss_no_author)
    cfg = FeedConfig(
        feed_url="https://example.com/feed.rss",
        keep_article=10,
        podcast_slug="test-podcast",
    )
    entries = parsed.entries[: cfg.keep_article]
    xml = generate_atom(cfg, parsed, entries, {}, "https://proxy.example.com")
    reparsed = feedparser.parse(xml)
    assert len(reparsed.entries) == 1
    # feedgen adds author element even if missing upstream
    assert reparsed.entries[0].author == "No Author Feed"
