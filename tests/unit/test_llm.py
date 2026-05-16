from __future__ import annotations

import json

import pytest

from llm import LLMClient, load_user_prompt


def test_parse_jsonl():
    text = '{"start_time": "00:00:00.000", "end_time": "00:00:05.000"}\n{"start_time": "00:10:00.000", "end_time": "00:10:30.000"}'
    result = LLMClient._parse_jsonl(text)
    assert len(result) == 2
    assert result[0]["start_time"] == "00:00:00.000"
    assert result[1]["end_time"] == "00:10:30.000"


def test_parse_jsonl_empty():
    assert LLMClient._parse_jsonl("") == []
    assert LLMClient._parse_jsonl("   \n  \n") == []


def test_parse_jsonl_invalid_json():
    with pytest.raises(json.JSONDecodeError):
        LLMClient._parse_jsonl("not json")


def test_load_user_prompt(tmp_path):
    prompt_path = tmp_path / "user_prompt.txt"
    prompt_path.write_text("Hello {{SRT_CONTENT}} world")
    result = load_user_prompt(str(prompt_path))
    assert "{{SRT_CONTENT}}" in result
    assert "Hello" in result
