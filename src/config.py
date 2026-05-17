from __future__ import annotations

import re
from pathlib import Path

import yaml
from pydantic import BaseModel, field_validator

_SLUG_RE = re.compile(r"^[a-zA-Z0-9-]+$")


class FeedConfig(BaseModel):
    feed_url: str
    keep_article: int
    podcast_slug: str

    @field_validator("podcast_slug")
    @classmethod
    def _validate_slug(cls, v: str) -> str:
        if not _SLUG_RE.match(v):
            raise ValueError(
                f"podcast_slug must be alphanumeric plus hyphens only, got: {v!r}"
            )
        return v


class AppConfig(BaseModel):
    feeds: list[FeedConfig]


def load_config(path: str | Path) -> AppConfig:
    raw = Path(path).read_text(encoding="utf-8")
    data = yaml.safe_load(raw)
    return AppConfig.model_validate(data)
