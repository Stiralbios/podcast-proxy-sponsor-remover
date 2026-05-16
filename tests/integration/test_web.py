from __future__ import annotations

from pathlib import Path

from starlette.testclient import TestClient

from web import create_app


def test_static_atom_serving():
    base = Path("/tmp/podcast-web-test")
    base.mkdir(parents=True, exist_ok=True)
    atom = base / "test" / "new" / "full.atom"
    atom.parent.mkdir(parents=True, exist_ok=True)
    atom.write_text("<?xml version='1.0'?\n\n<feed/>")

    app = create_app(base)
    client = TestClient(app)
    resp = client.get("/test/new/full.atom")
    assert resp.status_code == 200
    assert resp.headers["content-type"] in ("application/atom+xml", "application/xml")


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
    resp = client.get("/nonexistent.atom")
    assert resp.status_code == 404
