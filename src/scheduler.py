"""Scheduler: reloads config and runs periodic sync via APScheduler."""

from __future__ import annotations

import logging
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler

from config import load_config
from sync import sync_feed

logger = logging.getLogger(__name__)


def build_scheduler(config_path: str, base_url: str, processor: Any, sync_interval_hours: int = 1):
    """Build and start the APScheduler background thread.

    Returns (sched, sync_all) so the caller can trigger the initial sync
    from an ASGI lifespan event or run it inline as desired.
    """
    logger.info("Building scheduler (interval=%dh)", sync_interval_hours)
    sched = BackgroundScheduler()
    _running = False  # Guard against overlapping execution

    def _sync_all() -> None:
        nonlocal _running
        if _running:
            logger.warning("Previous sync still running, skipping this scheduled run")
            return
        _running = True
        try:
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
        finally:
            _running = False

    sched.add_job(
        _sync_all,
        trigger="interval",
        hours=sync_interval_hours,
        id="sync-all",
        max_instances=1,
        replace_existing=True,
        misfire_grace_time=1,
    )
    sched.start()
    logger.info("APScheduler background thread started")
    return sched, _sync_all
