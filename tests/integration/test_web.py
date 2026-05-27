from __future__ import annotations

from pathlib import Path

from starlette.testclient import TestClient

from web import create_app


def test_static_rss_serving():
    base = Path("/tmp/podcast-web-test")
    base.mkdir(parents=True, exist_ok=True)
    rss = base / "test" / "new" / "rss" / "full.rss"
    rss.parent.mkdir(parents=True, exist_ok=True)
    rss.write_text("<?xml version='1.0'?\n\n<rss version='2.0'><channel></channel></rss>")

    app = create_app(base)
    client = TestClient(app)
    resp = client.get("/test/new/rss/full.rss")
    assert resp.status_code == 200
    assert resp.headers["content-type"] in ("application/rss+xml", "application/xml", "application/x-rss+xml")


def test_static_media_serving():
    base = Path("/tmp/podcast-web-test")
    media = base / "test" / "new" / "media" / "sample.mp3"
    media.parent.mkdir(parents=True, exist_ok=True)
    media.write_bytes(b"\xff\xfb")

    app = create_app(base)
    client = TestClient(app)
    resp = client.get("/test/new/media/sample.mp3")
    assert resp.status_code == 200
    assert resp.headers["content-type"] in ("audio/mpeg", "audio/mp3")


def test_missing_file_404():
    base = Path("/tmp/podcast-web-test")
    app = create_app(base)
    client = TestClient(app)
    resp = client.get("/nonexistent.rss")
    assert resp.status_code == 404
