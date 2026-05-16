"""Scriberr API client (v1 endpoints)."""

from __future__ import annotations

import logging
import time
from pathlib import Path

import requests

logger = logging.getLogger(__name__)


class ScriberrClient:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.headers = {"X-API-Key": api_key}

    def upload_file(self, file_path: str | Path) -> str:
        """Upload an audio file. Returns the job id."""
        url = f"{self.base_url}/api/v1/transcription/upload"
        logger.debug("POST %s file=%s", url, file_path)
        with open(file_path, "rb") as f:
            files = {"audio": f}
            resp = requests.post(url, headers=self.headers, files=files, timeout=300)
        resp.raise_for_status()
        data = resp.json()
        job_id = data.get("id")
        logger.info("Scriberr upload complete, job_id=%s", job_id)
        return job_id

    def get_profile_parameters_by_name(self, name: str) -> dict | None:
        """Look up a transcription profile by name and return its parameters."""
        url = f"{self.base_url}/api/v1/profiles"
        logger.debug("GET %s", url)
        resp = requests.get(url, headers=self.headers, timeout=30)
        resp.raise_for_status()
        profiles = resp.json()
        for profile in profiles:
            if profile.get("name") == name:
                params = profile.get("parameters", {})
                logger.info("Found profile '%s' with %d keys", name, len(params))
                return params
        logger.warning("No profile named '%s' found, using default parameters", name)
        return None

    def start_transcription(self, job_id: str, parameters: dict | None = None) -> None:
        """Start transcription for an already uploaded audio file."""
        url = f"{self.base_url}/api/v1/transcription/{job_id}/start"
        body = parameters or {}
        logger.debug("POST %s with %d param keys", url, len(body))
        resp = requests.post(url, headers=self.headers, json=body, timeout=30)
        resp.raise_for_status()

    def is_transcript_ready(self, job_id: str) -> bool:
        """Check whether the transcript for *job_id* is finished."""
        url = f"{self.base_url}/api/v1/transcription/{job_id}/status"
        logger.debug("GET %s", url)
        resp = requests.get(url, headers=self.headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        status = data.get("status", "")
        logger.debug("Scriberr job %s status=%s", job_id, status)
        return status in ("completed", "done", "success")

    def download_transcript(self, job_id: str, dest_path: str | Path) -> None:
        """Download the transcript as JSON and write an SRT to *dest_path*."""
        url = f"{self.base_url}/api/v1/transcription/{job_id}/transcript"
        logger.debug("GET %s", url)
        resp = requests.get(url, headers=self.headers, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        segments = data.get("transcript", {}).get("segments", [])

        # Convert raw JSON segments to SRT format
        with open(dest_path, "w", encoding="utf-8") as f:
            for i, seg in enumerate(segments, start=1):
                start_s = seg.get("start", 0)
                end_s = seg.get("end", 0)
                text = seg.get("text", "").strip()
                start_str = _seconds_to_srt_timestamp(start_s)
                end_str = _seconds_to_srt_timestamp(end_s)
                f.write(f"{i}\n{start_str} --> {end_str}\n{text}\n\n")

        logger.info("Downloaded SRT transcript to %s", dest_path)


def _seconds_to_srt_timestamp(seconds: float) -> str:
    """Convert seconds to HH:MM:SS,mmm format for SRT."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:06.3f}".replace(".", ",")
