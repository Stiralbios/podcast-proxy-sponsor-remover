from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler

from config import load_config
from sync import sync_feed

logger = logging.getLogger(__name__)


def start_scheduler(config_path: str, base_url: str, processor, sync_interval_hours: int = 1):
    logger.info("Starting scheduler (interval=%dh)", sync_interval_hours)
    sched = BackgroundScheduler()

    def _sync_all() -> None:
        try:
            config = load_config(config_path)
        except Exception:
            logger.exception("Failed to reload config from %s", config_path)
            return
        logger.info("Reloaded %d feeds from %s", len(config.feeds), config_path)
        for feed in config.feeds:
            logger.info("Syncing %s", feed.podcast_slug)
            try:
                sync_feed(feed, base_url, processor)
            except Exception:
                logger.exception("Sync failed for %s", feed.podcast_slug)
        logger.info("Batch sync finished (%d feeds)", len(config.feeds))

    sched.add_job(
        _sync_all,
        trigger="interval",
        hours=sync_interval_hours,
        id="sync-all",
        max_instances=1,
        replace_existing=True,
    )
    sched.start()

    # Initial sync
    logger.info("Beginning initial sync")
    _sync_all()
    logger.info("All initial syncs finished")
    return sched
