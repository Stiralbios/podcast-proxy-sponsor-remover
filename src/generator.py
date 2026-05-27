from __future__ import annotations

import calendar
import logging
from datetime import datetime, timezone
from typing import Any

from feedgen.feed import FeedGenerator
from lxml import etree

from config import FeedConfig

logger = logging.getLogger(__name__)


def _struct_time_to_datetime(st: Any) -> datetime | None:
    """Convert feedparser's time.struct_time to timezone-aware datetime (UTC)."""
    if st is None:
        return None
    import time

    if isinstance(st, time.struct_time):
        ts = calendar.timegm(st)
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    if isinstance(st, datetime):
        if st.tzinfo is None:
            return st.replace(tzinfo=timezone.utc)
        return st
    return None


def _first_audio_enclosure(entry: Any) -> dict | None:
    if not hasattr(entry, "enclosures"):
        return None
    for enc in entry.enclosures:
        if enc.get("type", "").startswith("audio/"):
            return enc
    return None


def generate_atom(
    feed_config: FeedConfig,
    original_parsed: Any,
    entries: list[Any],
    media_urls: dict[str, str],
    base_url: str,
) -> str:
    fg = FeedGenerator()
    fg.load_extension("podcast")

    # Feed-level metadata
    feed_title = getattr(original_parsed.feed, "title", feed_config.podcast_slug)
    fg.title(str(feed_title) if feed_title else feed_config.podcast_slug)

    feed_desc = getattr(original_parsed.feed, "description", "")
    if not feed_desc:
        feed_desc = getattr(original_parsed.feed, "subtitle", "")
    fg.description(str(feed_desc) if feed_desc else "")

    feed_link = getattr(original_parsed.feed, "link", "")
    if feed_link:
        fg.link(href=str(feed_link), rel="alternate")

    feed_lang = getattr(original_parsed.feed, "language", "en")
    fg.language(str(feed_lang) if feed_lang else "en")

    feed_id = getattr(original_parsed.feed, "id", getattr(original_parsed.feed, "link", ""))
    if not feed_id:
        feed_id = feed_config.feed_url
    fg.id(str(feed_id))

    # Image
    image = getattr(original_parsed.feed, "image", None)
    if image and hasattr(image, "href"):
        fg.logo(str(image.href))

    # Podcast itunes:image (podcast extension)
    itunes_image = getattr(original_parsed.feed, "image", None)
    if itunes_image and hasattr(itunes_image, "href"):
        fg.podcast.itunes_image(str(itunes_image.href))

    # Author
    author_name = getattr(original_parsed.feed, "author", "")
    if not author_name:
        author_name = getattr(original_parsed.feed, "title", "Unknown")
    if not author_name:
        author_name = "Unknown"
    fg.author(name=str(author_name))

    # Updated (mandatory for Atom)
    feed_updated = getattr(original_parsed.feed, "updated_parsed", None)
    if feed_updated is None:
        # Fallback: use the most recent entry published date, or now
        feed_updated = max(
            (getattr(e, "published_parsed", None) for e in entries),
            default=None,
        )
    dt_updated = _struct_time_to_datetime(feed_updated)
    if dt_updated:
        fg.updated(dt_updated)
    else:
        fg.updated(datetime.now(tz=timezone.utc))

    # Collect enclosure info keyed by entry id
    enclosure_map: dict[str, dict[str, Any]] = {}

    # feedgen prepends entries internally; iterating reversed preserves upstream order
    for entry in reversed(entries):
        fe = fg.add_entry()

        entry_id = getattr(entry, "id", getattr(entry, "guid", ""))
        if not entry_id:
            entry_id = getattr(entry, "link", "")
        if not entry_id:
            entry_id = getattr(entry, "title", "")
        fe.id(str(entry_id))

        title = getattr(entry, "title", "Untitled")
        fe.title(str(title))

        link = getattr(entry, "link", "")
        if link:
            fe.link(href=str(link))

        summary = getattr(entry, "summary", "")
        if summary:
            fe.summary(str(summary))

        # Dates
        published = _struct_time_to_datetime(getattr(entry, "published_parsed", None))
        updated = _struct_time_to_datetime(getattr(entry, "updated_parsed", None))
        if published:
            fe.published(published)
        if updated:
            fe.updated(updated)
        elif published:
            fe.updated(published)

        # Author per entry
        entry_author = getattr(entry, "author", author_name)
        if not entry_author:
            entry_author = author_name
        fe.author(name=str(entry_author))

        # Enclosure info (feedgen's enclosure() is broken for Atom links)
        orig_enc = _first_audio_enclosure(entry)
        if orig_enc:
            orig_url = orig_enc.get("href", orig_enc.get("url", ""))
            filename = media_urls.get(str(orig_url), "")
            if filename:
                enc_url = f"{base_url.rstrip('/')}/{feed_config.podcast_slug}/new/media/{filename}"
                enc_type = orig_enc.get("type", "audio/mpeg")
                enc_length = orig_enc.get("length", "0")
                try:
                    enc_length = int(enc_length)
                except (ValueError, TypeError):
                    enc_length = 0
                enclosure_map[str(entry_id)] = {
                    "url": enc_url,
                    "type": str(enc_type),
                    "length": enc_length,
                }

    xml_bytes = fg.atom_str(pretty=True)
    tree = etree.fromstring(xml_bytes)
    ns = "{http://www.w3.org/2005/Atom}"

    for entry_el in tree.findall(f"{ns}entry"):
        id_el = entry_el.find(f"{ns}id")
        if id_el is None or id_el.text is None:
            continue
        enc_info = enclosure_map.get(id_el.text)
        if enc_info:
            link_el = etree.SubElement(entry_el, f"{ns}link")
            link_el.set("rel", "enclosure")
            link_el.set("href", enc_info["url"])
            link_el.set("type", enc_info["type"])
            link_el.set("length", str(enc_info["length"]))

    return etree.tostring(tree, pretty_print=True, xml_declaration=True, encoding="utf-8").decode("utf-8")
