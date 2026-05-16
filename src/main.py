from __future__ import annotations

import logging
import os
import signal
import sys
from pathlib import Path

# Force unbuffered output so logs appear immediately even when redirected
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

import yaml
from dotenv import load_dotenv

from config import load_config
from llm import LLMClient, load_user_prompt
from paths import FeedPaths
from processor import AudioProcessor, verify_ffmpeg
from scheduler import start_scheduler
from scriberr_api import ScriberrClient
from web import create_app

try:
    import uvicorn
except ImportError:
    uvicorn = None  # type: ignore

logger = logging.getLogger(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


def _load_settings(path: str = "config/settings.yml") -> dict:
    p = Path(path)
    if not p.exists():
        logger.warning("Settings file %s not found, using defaults", path)
        return {}
    raw = p.read_text(encoding="utf-8")
    data = yaml.safe_load(raw)
    return data if data is not None else {}


def main() -> None:
    load_dotenv()
    settings = _load_settings()
    config = load_config("config/feeds.yaml")

    # Ensure directories exist
    podcasts_dir = Path("podcasts")
    podcasts_dir.mkdir(parents=True, exist_ok=True)
    for feed in config.feeds:
        fp = FeedPaths(feed.podcast_slug, base_dir=podcasts_dir)
        _ = fp.old_media_dir
        _ = fp.new_media_dir
        _ = fp.metadata_dir
        _ = fp.old_rss_file
        _ = fp.new_rss_file

    # Verify ffmpeg is installed
    verify_ffmpeg()

    # Build API clients
    scriberr_client = ScriberrClient(
        os.getenv("SCRIBERR_BASE_URL", ""), os.getenv("SCRIBERR_API_KEY", "")
    )
    llm_client = LLMClient(
        base_url=os.getenv("OPENAI_BASE_URL", ""),
        api_key=os.getenv("OPENAI_API_KEY", ""),
        model=settings.get("inference_model", ""),
        max_retry=settings.get("llm_max_retry", 3),
        temperature=settings.get("llm_temperature", 0.0),
        reasoning_effort=settings.get("inference_reasoning_effort") or None,
    )
    user_prompt = load_user_prompt()

    profile_name = settings.get("scriberr_profile_name", "")
    profile_params: dict | None = None
    if profile_name:
        profile_params = scriberr_client.get_profile_parameters_by_name(profile_name)

    processor = AudioProcessor(
        scriberr_client=scriberr_client,
        llm_client=llm_client,
        user_prompt_template=user_prompt,
        profile_params=profile_params,
        scriberr_check_interval=settings.get("scriberr_check_interval", 30),
    )

    base_url = os.environ.get("BASE_URL", "http://localhost:3000")
    sync_interval = settings.get("sync_interval_hours", 1)
    sched = start_scheduler(config.feeds, base_url, processor, sync_interval)
    app = create_app(podcasts_dir)

    # Graceful shutdown
    def _shutdown(signum, frame):
        logger.info("Shutting down scheduler...")
        sched.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    uvicorn.run(app, host="0.0.0.0", port=3000)
    sched.shutdown(wait=False)


if __name__ == "__main__":
    main()
