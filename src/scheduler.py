from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from apscheduler.schedulers.background import BackgroundScheduler

from sync import sync_feed

if TYPE_CHECKING:
    from config import FeedConfig
    from processor import AudioProcessor

logger = logging.getLogger(__name__)


def start_scheduler(feeds: list[FeedConfig], base_url: str, processor: AudioProcessor) -> BackgroundScheduler:
    logger.info("Starting scheduler with %d feeds", len(feeds))
    sched = BackgroundScheduler()
    for feed in feeds:
        logger.info("Registering scheduled job for %s", feed.podcast_slug)
        sched.add_job(
            sync_feed,
            trigger="interval",
            hours=1,
            args=[feed, base_url, processor],
            id=feed.podcast_slug,
            max_instances=1,
            replace_existing=True,
        )
    logger.info("Starting APScheduler background thread")
    sched.start()
    # Initial sync: sequential, not parallel
    logger.info("Beginning initial sync (sequential)")
    for feed in feeds:
        logger.info("Initial sync for %s starting", feed.podcast_slug)
        try:
            sync_feed(feed, base_url, processor)
            logger.info("Initial sync for %s completed", feed.podcast_slug)
        except Exception:
            logger.exception("Initial sync failed for %s", feed.podcast_slug)
    logger.info("All initial syncs finished")
    return sched
