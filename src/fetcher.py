from __future__ import annotations

import logging
from pathlib import Path

import feedparser
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

_session: requests.Session | None = None


def _get_session() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
        retries = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retries)
        _session.mount("https://", adapter)
        _session.mount("http://", adapter)
    return _session


def fetch_feed(url: str) -> tuple[str, feedparser.FeedParserDict]:
    """Download upstream feed and return (raw_xml, parsed)."""
    session = _get_session()
    resp = session.get(url, timeout=60)
    resp.raise_for_status()
    raw = resp.text
    parsed = feedparser.parse(raw)
    return raw, parsed


def download_media(url: str, dest: Path) -> None:
    """Stream an audio file to disk."""
    session = _get_session()
    resp = session.get(url, stream=True, timeout=600)
    resp.raise_for_status()
    tmp = dest.with_suffix(".tmp" + dest.suffix)
    with tmp.open("wb") as fh:
        for chunk in resp.iter_content(chunk_size=8192):
            if chunk:
                fh.write(chunk)
    tmp.replace(dest)
