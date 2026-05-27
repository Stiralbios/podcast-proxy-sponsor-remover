from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FeedPaths:
    slug: str
    base_dir: Path = Path("podcasts")

    @property
    def podcast_dir(self) -> Path:
        return self.base_dir / self.slug

    @property
    def old_media_dir(self) -> Path:
        path = self.podcast_dir / "old" / "media"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def old_rss_file(self) -> Path:
        path = self.podcast_dir / "old" / "rss"
        path.mkdir(parents=True, exist_ok=True)
        return path / "full.rss"

    @property
    def new_media_dir(self) -> Path:
        path = self.podcast_dir / "new" / "media"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def new_rss_file(self) -> Path:
        path = self.podcast_dir / "new" / "rss"
        path.mkdir(parents=True, exist_ok=True)
        return path / "full.rss"

    @property
    def metadata_dir(self) -> Path:
        path = self.podcast_dir / "metadata"
        path.mkdir(parents=True, exist_ok=True)
        return path
