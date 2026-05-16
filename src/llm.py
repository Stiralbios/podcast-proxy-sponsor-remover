"""LLM client to detect ad/sponsor segments in an SRT transcript."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI

logger = logging.getLogger(__name__)


class LLMClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        max_retry: int = 3,
        temperature: float = 0.0,
        reasoning_effort: str | None = None,
    ):
        self.max_retry = max_retry
        self.reasoning_effort = reasoning_effort
        kwargs: dict = {
            "base_url": base_url,
            "api_key": api_key,
            "model": model,
            "temperature": temperature,
        }
        self.llm = ChatOpenAI(**kwargs)

    def detect_ad_segments(self, srt_content: str, user_prompt_template: str) -> list[dict]:
        """Send the SRT content to the LLM and return a list of ad-segment dicts."""
        prompt = user_prompt_template.replace("{{SRT_CONTENT}}", srt_content)
        messages = [HumanMessage(content=prompt)]

        invoke_kwargs: dict = {}
        if self.reasoning_effort:
            invoke_kwargs["extra_body"] = {"reasoning_effort": self.reasoning_effort}

        for attempt in range(1, self.max_retry + 1):
            logger.debug("LLM call attempt %d/%d", attempt, self.max_retry)
            response = self.llm.invoke(messages, **invoke_kwargs)
            raw = response.content.strip()
            if not raw:
                return []

            try:
                segments = self._parse_jsonl(raw)
                logger.info("LLM returned %d ad segments", len(segments))
                return segments
            except Exception as exc:
                logger.warning(
                    "LLM returned unparsable JSONL on attempt %d: %s", attempt, exc
                )
                if attempt == self.max_retry:
                    raise Exception(
                        f"Failed to parse LLM response after {self.max_retry} attempts"
                    ) from exc

        return []  # unreachable

    @staticmethod
    def _parse_jsonl(text: str) -> list[dict]:
        """Parse a JSONL string (one JSON object per line)."""
        segments = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            segments.append(json.loads(line))
        return segments


def load_user_prompt(path: str = "config/user_prompt.txt") -> str:
    """Load the user prompt template from disk."""
    return Path(path).read_text(encoding="utf-8")
