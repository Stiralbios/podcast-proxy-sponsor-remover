import subprocess

import pytest

from processor import AudioProcessor, verify_ffmpeg


def test_verify_ffmpeg():
    verify_ffmpeg()


def test_verify_ffmpeg_missing(monkeypatch):
    def raise_fn(*args, **kwargs):
        raise FileNotFoundError("no ffmpeg")

    import processor as proc_mod
    monkeypatch.setattr(proc_mod, "subprocess", type("Fake", (), {"run": raise_fn})())
    # Actually verify_ffmpeg uses subprocess.run directly, so monkeypatch that
    monkeypatch.setattr("subprocess.run", raise_fn)
    with pytest.raises(RuntimeError, match="ffmpeg is not installed"):
        verify_ffmpeg()


def test_audio_processor_fallback_copy(tmp_path, monkeypatch):
    """If any step fails, processor should copy original file to output."""
    input_path = tmp_path / "input.mp3"
    input_path.write_bytes(b"fake_audio")
    output_path = tmp_path / "output.mp3"
    metadata_dir = tmp_path / "metadata"

    def failing_transcribe(*args, **kwargs):
        raise RuntimeError("scriberr down")

    fake_sc = type("FakeScriberr", (), {"upload_file": failing_transcribe})()
    fake_llm = type("FakeLLM", (), {})()

    processor = AudioProcessor(
        scriberr_client=fake_sc,
        llm_client=fake_llm,
        user_prompt_template="test",
    )
    processor.process(input_path, output_path, metadata_dir)

    assert output_path.exists()
    assert output_path.read_bytes() == b"fake_audio"


def test_audio_processor_no_segments_copies_original(tmp_path, monkeypatch):
    """If LLM returns no segments, processor copies original."""
    input_path = tmp_path / "input.mp3"
    input_path.write_bytes(b"fake_audio")
    output_path = tmp_path / "output.mp3"
    metadata_dir = tmp_path / "metadata"

    # Pre-create SRT and empty segments to skip transcription + LLM
    srt_path = metadata_dir / "input.srt"
    srt_path.parent.mkdir(parents=True, exist_ok=True)
    srt_path.write_text("1\n00:00:00,000 --> 00:00:01,000\nHello\n\n")
    segments_path = metadata_dir / "input.segments.json"
    segments_path.write_text("[]")

    fake_sc = type("FakeScriberr", (), {})()
    fake_llm = type("FakeLLM", (), {})()

    processor = AudioProcessor(
        scriberr_client=fake_sc,
        llm_client=fake_llm,
        user_prompt_template="test",
    )
    processor.process(input_path, output_path, metadata_dir)

    assert output_path.exists()
    assert output_path.read_bytes() == b"fake_audio"
