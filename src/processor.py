"""Podcast audio processor: transcribes, detects ads, and either strips or
marks them depending on configuration."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
from pathlib import Path

from ffmpeg_segments import mark_segments, remove_segments
from llm import LLMClient
from scriberr_api import ScriberrClient

logger = logging.getLogger(__name__)


class AudioProcessor:
    """Transcribe -> detect ads -> either strip them (default) or mark them.

    If any step fails, falls back to copying the original file unchanged.
    """

    def __init__(
        self,
        scriberr_client: ScriberrClient,
        llm_client: LLMClient,
        user_prompt_template: str,
        profile_params: dict | None = None,
        scriberr_check_interval: int = 30,
        mark_ads: bool = False,
    ) -> None:
        self.sc = scriberr_client
        self.llm = llm_client
        self.user_prompt = user_prompt_template
        self.profile_params = profile_params
        self.check_interval = scriberr_check_interval
        self.mark_ads = mark_ads

    def process(self, input_path: Path, output_path: Path, metadata_dir: Path) -> None:
        """Process audio with checkpoint/resume. On failure, copy original."""
        metadata_dir = Path(metadata_dir)
        metadata_dir.mkdir(parents=True, exist_ok=True)
        stem = input_path.stem
        srt_path = metadata_dir / f"{stem}.srt"
        segments_path = metadata_dir / f"{stem}.segments.json"

        try:
            # --- Step 1: Transcribe via Scriberr ---
            if not srt_path.exists() or srt_path.stat().st_size == 0:
                logger.info("Transcribing %s via Scriberr", input_path)
                self._transcribe(input_path, srt_path)
            else:
                logger.debug("Skipping transcription, SRT exists: %s", srt_path)

            # --- Step 2: Detect ad segments via LLM ---
            segments: list[dict] = []
            if not segments_path.exists() or segments_path.stat().st_size == 0:
                logger.info("Detecting ad segments via LLM for %s", input_path)
                segments = self._detect_segments(srt_path, segments_path)
            else:
                logger.debug("Skipping LLM, segments exist: %s", segments_path)
                segments = json.loads(segments_path.read_text(encoding="utf-8"))

            # --- Step 3: Strip or Mark segments via ffmpeg ---
            if not segments:
                logger.info("No ad segments detected, copying original to %s", output_path)
                shutil.copy2(input_path, output_path)
                return

            if self.mark_ads:
                logger.info(
                    "Marking %d ad segments in %s (chapter-based)", len(segments), input_path
                )
                tmp = output_path.with_suffix(".tmp" + output_path.suffix)
                mark_segments(input_path, segments, tmp, new_chapter_label="Ad / Sponsor")
            else:
                logger.info(
                    "Removing %d ad segments from %s", len(segments), input_path
                )
                tmp = output_path.with_suffix(".tmp" + output_path.suffix)
                remove_segments(input_path, segments, tmp)

            if not tmp.exists() or tmp.stat().st_size == 0:
                raise RuntimeError("ffmpeg produced no output")
            os.replace(tmp, output_path)

        except Exception as exc:
            logger.warning(
                "Sponsor removal failed for %s: %s. Falling back to original copy.",
                input_path,
                exc,
            )
            shutil.copy2(input_path, output_path)

    def _transcribe(self, input_path: Path, srt_path: Path) -> None:
        job_id = self.sc.upload_file(input_path)
        self.sc.start_transcription(job_id, self.profile_params)
        while not self.sc.is_transcript_ready(job_id):
            logger.debug("Transcript not ready, sleeping %d seconds", self.check_interval)
            time.sleep(self.check_interval)
        self.sc.download_transcript(job_id, srt_path)

    def _detect_segments(self, srt_path: Path, segments_path: Path) -> list[dict]:
        srt_content = srt_path.read_text(encoding="utf-8")
        segments = self.llm.detect_ad_segments(srt_content, self.user_prompt)
        segments_path.write_text(json.dumps(segments, indent=2), encoding="utf-8")
        return segments


def verify_ffmpeg() -> None:
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, timeout=10)
    except FileNotFoundError as exc:
        raise RuntimeError("ffmpeg is not installed or not on $PATH") from exc
