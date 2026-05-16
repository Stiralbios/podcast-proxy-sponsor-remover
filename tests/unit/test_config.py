from __future__ import annotations

import pytest
from pydantic import ValidationError

from config import AppConfig, FeedConfig, load_config


def test_load_valid_config(tmp_path):
    yaml_path = tmp_path / "feeds.yaml"
    yaml_path.write_text(
        """
feeds:
  - feed_url: "https://example.com/podcast.rss"
    keep_article: 10
    podcast_slug: "my-podcast"
    feed_path: "my-podcast"
"""
    )
    cfg = load_config(yaml_path)
    assert isinstance(cfg, AppConfig)
    assert len(cfg.feeds) == 1
    assert cfg.feeds[0].feed_url == "https://example.com/podcast.rss"
    assert cfg.feeds[0].keep_article == 10
    assert cfg.feeds[0].podcast_slug == "my-podcast"
    assert cfg.feeds[0].feed_path == "my-podcast"


def test_missing_field():
    with pytest.raises(ValidationError):
        FeedConfig.model_validate(
            {"feed_url": "https://example.com", "keep_article": 5, "podcast_slug": "ok"}
        )


def test_bad_slug():
    with pytest.raises(ValidationError):
        FeedConfig.model_validate(
            {
                "feed_url": "https://example.com",
                "keep_article": 5,
                "podcast_slug": "bad/slug",
                "feed_path": "bad/slug",
            }
        )


def test_bad_slug_with_backslash():
    with pytest.raises(ValidationError):
        FeedConfig.model_validate(
            {
                "feed_url": "https://example.com",
                "keep_article": 5,
                "podcast_slug": "bad\\slug",
                "feed_path": "bad/slug",
            }
        )


def test_bad_slug_with_space():
    with pytest.raises(ValidationError):
        FeedConfig.model_validate(
            {
                "feed_url": "https://example.com",
                "keep_article": 5,
                "podcast_slug": "bad slug",
                "feed_path": "bad/slug",
            }
        )
