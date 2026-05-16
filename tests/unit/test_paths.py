from __future__ import annotations

from pathlib import Path

from paths import FeedPaths


def test_feed_paths(tmp_path):
    fp = FeedPaths(slug="test-podcast", base_dir=tmp_path)
    assert fp.podcast_dir == tmp_path / "test-podcast"
    assert fp.old_media_dir == tmp_path / "test-podcast" / "old" / "media"
    assert fp.old_rss_file == tmp_path / "test-podcast" / "old" / "rss" / "full.atom"
    assert fp.new_media_dir == tmp_path / "test-podcast" / "new" / "media"
    assert fp.new_rss_file == tmp_path / "test-podcast" / "new" / "full.atom"


def test_directories_created(tmp_path):
    fp = FeedPaths(slug="fresh", base_dir=tmp_path)
    _ = fp.old_media_dir
    _ = fp.new_media_dir
    assert (tmp_path / "fresh" / "old" / "media").exists()
    assert (tmp_path / "fresh" / "new" / "media").exists()
