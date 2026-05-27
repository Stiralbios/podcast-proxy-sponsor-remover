from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
from typing import Any

from config import FeedConfig
from fetcher import download_media, fetch_feed
from generator import _first_audio_enclosure, generate_rss
from paths import FeedPaths
from processor import AudioProcessor

logger = logging.getLogger(__name__)


def _cleanup_orphaned(paths: FeedPaths, valid_filenames: set[str]) -> None:
    """Delete old/new media and metadata files not in the current feed."""
    for directory in (paths.old_media_dir, paths.new_media_dir, paths.metadata_dir):
        if not directory.exists():
            continue
        for fpath in directory.iterdir():
            if not fpath.is_file():
                continue
            # Keep files whose stem matches a valid filename stem
            if fpath.stem in {Path(n).stem for n in valid_filenames}:
                continue
            logger.info("Removing orphaned file: %s", fpath)
            try:
                fpath.unlink()
            except OSError:
                logger.exception("Failed to remove %s", fpath)


def _derive_filename(enclosure_url: str, entry_id: str) -> str:
    """Derive a unique filename from the enclosure URL or entry GUID."""
    key = f"{entry_id}:{enclosure_url}"
    digest = hashlib.sha256(key.encode()).hexdigest()[:16]
    return f"{digest}.mp3"


def _safe_download_media(enclosure_url: str, dest: Path) -> None:
    """Download media with basic error handling."""
    try:
        download_media(enclosure_url, dest)
    except Exception:
        logger.exception("Failed to download media %s", enclosure_url)
        raise


def sync_feed(feed_config: FeedConfig, base_url: str, processor: AudioProcessor) -> None:
    logger.info("sync_feed starting for %s", feed_config.podcast_slug)
    paths = FeedPaths(feed_config.podcast_slug)

    # 1. Download upstream feed
    raw_xml, parsed = fetch_feed(feed_config.feed_url)
    rss_tmp = paths.old_rss_file.with_suffix(".tmp.rss")
    rss_tmp.write_text(raw_xml, encoding="utf-8")
    os.replace(rss_tmp, paths.old_rss_file)

    # 2. Collect entries to keep
    kept_entries = parsed.entries[: feed_config.keep_article]
    media_mappings: dict[str, str] = {}

    # 3. For each entry: download original, process audio
    for entry in kept_entries:
        orig_enc = _first_audio_enclosure(entry)
        if not orig_enc:
            continue

        enclosure_url = orig_enc.get("href", orig_enc.get("url", ""))
        if not enclosure_url:
            logger.warning("Enclosure without URL, skipping entry %s", getattr(entry, "id", "?"))
            continue

        filename = _derive_filename(enclosure_url, getattr(entry, "id", enclosure_url))
        old_path = paths.old_media_dir / filename
        new_path = paths.new_media_dir / filename

        try:
            # 3a. Download original if not present
            if not old_path.exists() or old_path.stat().st_size == 0:
                logger.info("Downloading %s", enclosure_url)
                _safe_download_media(enclosure_url, old_path)
            else:
                logger.debug("Skipping download, exists: %s", old_path)

            # 3b. Process with sponsor removal if not present
            if not new_path.exists() or new_path.stat().st_size == 0:
                logger.info("Processing %s -> %s", old_path, new_path)
                processor.process(old_path, new_path, paths.metadata_dir)
            else:
                logger.debug("Skipping process, exists: %s", new_path)
        except Exception:
            logger.error("Skipping entry %s due to failure", getattr(entry, "id", "?"))
            continue

        media_mappings[enclosure_url] = filename

    # 4. Filter only entries whose new media exists and is non-empty
    def _has_valid_media(entry: Any) -> bool:
        orig_enc = _first_audio_enclosure(entry)
        if not orig_enc:
            return False
        enclosure_url = orig_enc.get("href", orig_enc.get("url", ""))
        if not enclosure_url:
            return False
        filename = media_mappings.get(enclosure_url)
        if not filename:
            return False
        new_path = paths.new_media_dir / filename
        return new_path.exists() and new_path.stat().st_size > 0

    valid_entries = [e for e in kept_entries if _has_valid_media(e)]

    # 5. Generate new Atom feed
    rss_xml = generate_rss(feed_config, parsed, valid_entries, media_mappings, base_url)
    new_rss_tmp = paths.new_rss_file.with_suffix(".tmp.rss")
    new_rss_tmp.write_text(rss_xml, encoding="utf-8")
    os.replace(new_rss_tmp, paths.new_rss_file)

    # 6. Clean up orphaned files no longer referenced
    _cleanup_orphaned(paths, set(media_mappings.values()))
    logger.info("sync_feed finished for %s", feed_config.podcast_slug)
