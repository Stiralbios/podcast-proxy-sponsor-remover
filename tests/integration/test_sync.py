from __future__ import annotations

from pathlib import Path

import feedparser
import pytest

import sync as sync_module
from config import FeedConfig
from sync import sync_feed


RSS_XML = """\
<?xml version="1.0"?>
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


class FakeFeedPaths:
    """Simplified FeedPaths for integration tests."""

    def __init__(self, slug: str, base_dir: Path):
        self.slug = slug
        self.base_dir = base_dir

    @property
    def podcast_dir(self) -> Path:
        return self.base_dir / self.slug

    @property
    def old_media_dir(self) -> Path:
        path = self.podcast_dir / "old" / "media"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def old_rss_file(self) -> Path:
        path = self.podcast_dir / "old" / "rss"
        path.mkdir(parents=True, exist_ok=True)
        return path / "full.atom"

    @property
    def new_media_dir(self) -> Path:
        path = self.podcast_dir / "new" / "media"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def new_rss_file(self) -> Path:
        path = self.podcast_dir / "new" / "rss"
        path.mkdir(parents=True, exist_ok=True)
        return path / "full.atom"

    @property
    def metadata_dir(self) -> Path:
        path = self.podcast_dir / "metadata"
        path.mkdir(parents=True, exist_ok=True)
        return path


def _make_fake_fetcher(xml: str):
    def fake_fetch_feed(url: str):
        parsed = feedparser.parse(xml)
        return xml, parsed
    return fake_fetch_feed


def _make_fake_download_media():
    def fake_download(url: str, dest: Path) -> None:
        import subprocess

        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-f", "lavfi",
                "-i", "anullsrc=r=44100:cl=mono",
                "-t", "2",
                "-acodec", "libmp3lame",
                "-q:a", "4",
                str(dest),
            ],
            check=True,
            capture_output=True,
        )
    return fake_download


def _make_mock_processor():
    """Build a mock AudioProcessor that copies old to new."""
    class MockProcessor:
        def process(self, input_path: Path, output_path: Path, metadata_dir: Path) -> None:
            import shutil
            shutil.copy2(input_path, output_path)
    return MockProcessor()


def test_sync_feed_pipeline(tmp_path, monkeypatch):
    monkeypatch.setattr(sync_module, "FeedPaths", lambda slug: FakeFeedPaths(slug, base_dir=tmp_path))
    monkeypatch.setattr(sync_module, "fetch_feed", _make_fake_fetcher(RSS_XML))
    monkeypatch.setattr(sync_module, "download_media", _make_fake_download_media())

    cfg = FeedConfig(
        feed_url="https://example.com/feed.rss",
        keep_article=2,
        podcast_slug="test-podcast",
    )
    sync_feed(cfg, "https://proxy.example.com", _make_mock_processor())

    fp = FakeFeedPaths("test-podcast", base_dir=tmp_path)
    assert fp.old_rss_file.exists()
    assert fp.new_rss_file.exists()
    assert any(fp.old_media_dir.iterdir())
    assert any(fp.new_media_dir.iterdir())

    # Verify new feed has entries
    reparsed = feedparser.parse(fp.new_rss_file.read_text())
    assert len(reparsed.entries) == 2
    assert reparsed.entries[0].id == "guid-1"
    assert reparsed.entries[1].id == "guid-2"


def test_sync_feed_idempotent(tmp_path, monkeypatch):
    dummy_calls = {"fetch": 0, "download": 0}

    def counting_fetch(url):
        dummy_calls["fetch"] += 1
        parsed = feedparser.parse(RSS_XML)
        return RSS_XML, parsed

    def counting_download(url, dest):
        dummy_calls["download"] += 1

    monkeypatch.setattr(sync_module, "fetch_feed", counting_fetch)
    monkeypatch.setattr(sync_module, "download_media", counting_download)
    monkeypatch.setattr(sync_module, "FeedPaths", lambda slug: FakeFeedPaths(slug, base_dir=tmp_path))

    cfg = FeedConfig(
        feed_url="https://example.com/feed.rss",
        keep_article=2,
        podcast_slug="test-podcast",
    )

    # Create pre-existing old/new media so skips happen
    fp = FakeFeedPaths("test-podcast", base_dir=tmp_path)
    filename = sync_module._derive_filename("https://example.com/ep1.mp3", "guid-1")
    (fp.old_media_dir / filename).write_bytes(b"old1")
    (fp.new_media_dir / filename).write_bytes(b"new1")
    filename2 = sync_module._derive_filename("https://example.com/ep2.mp3", "guid-2")
    (fp.old_media_dir / filename2).write_bytes(b"old2")
    (fp.new_media_dir / filename2).write_bytes(b"new2")

    sync_feed(cfg, "https://proxy.example.com", _make_mock_processor())
    assert dummy_calls["download"] == 0


def test_sync_feed_cleanup_orphaned(tmp_path, monkeypatch):
    """Files for entries that fall out of keep_article should be deleted."""
    monkeypatch.setattr(sync_module, "fetch_feed", _make_fake_fetcher(RSS_XML))
    monkeypatch.setattr(sync_module, "download_media", lambda url, dest: dest.write_bytes(b"audio"))
    monkeypatch.setattr(sync_module, "FeedPaths", lambda slug: FakeFeedPaths(slug, base_dir=tmp_path))

    cfg = FeedConfig(
        feed_url="https://example.com/feed.rss",
        keep_article=2,  # start with 2
        podcast_slug="test-podcast",
    )
    sync_feed(cfg, "https://proxy.example.com", _make_mock_processor())

    fp = FakeFeedPaths("test-podcast", base_dir=tmp_path)
    assert len(list(fp.new_media_dir.iterdir())) == 2
    assert len(list(fp.old_media_dir.iterdir())) == 2

    # Reduce to 1 episode — only guid-1 is first in the feed
    cfg.keep_article = 1
    sync_feed(cfg, "https://proxy.example.com", _make_mock_processor())

    # Orphaned file for ep2/guid-2 should be removed
    remaining_new = {f.name for f in fp.new_media_dir.iterdir()}
    remaining_old = {f.name for f in fp.old_media_dir.iterdir()}
    filename_ep2 = sync_module._derive_filename("https://example.com/ep2.mp3", "guid-2")
    assert filename_ep2 not in remaining_new
    assert filename_ep2 not in remaining_old


def test_sync_feed_partial_failure(tmp_path, monkeypatch):
    def fail_on_ep2(url, dest):
        if "ep2" in url:
            raise RuntimeError("simulated download failure")
        dest.write_bytes(b"audio1")

    monkeypatch.setattr(sync_module, "fetch_feed", _make_fake_fetcher(RSS_XML))
    monkeypatch.setattr(sync_module, "download_media", fail_on_ep2)
    monkeypatch.setattr(sync_module, "FeedPaths", lambda slug: FakeFeedPaths(slug, base_dir=tmp_path))

    cfg = FeedConfig(
        feed_url="https://example.com/feed.rss",
        keep_article=2,
        podcast_slug="test-podcast",
    )
    sync_feed(cfg, "https://proxy.example.com", _make_mock_processor())

    fp = FakeFeedPaths("test-podcast", base_dir=tmp_path)
    reparsed = feedparser.parse(fp.new_rss_file.read_text())
    assert len(reparsed.entries) == 1
    assert reparsed.entries[0].id == "guid-1"
