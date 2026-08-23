"""Optional, lazy WhisperX transcription and Korean alignment adapter."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..capability import optional_dependency
from ..contracts import CapabilityStatus, ValidationStatus


@dataclass(frozen=True)
class WordTimestamp:
    word: str
    start_seconds: float | None
    end_seconds: float | None
    confidence: float | None = None


@dataclass(frozen=True)
class AsrOutput:
    status: ValidationStatus
    text: str = ""
    words: list[WordTimestamp] = field(default_factory=list)
    segments: list[dict[str, Any]] = field(default_factory=list)
    reason: str | None = None
    language_code: str = "ko"


class WhisperXAdapter:
    """Loads WhisperX only during explicit transcription/alignment calls."""

    def __init__(self, language_code: str = "ko", model_name: str = "large-v3", device: str = "cpu", package_name: str = "whisperx") -> None:
        if language_code != "ko": raise ValueError("S04 supports Korean language code 'ko' only")
        self.language_code, self.model_name, self.device, self.package_name = language_code, model_name, device, package_name

    def capability(self) -> CapabilityStatus:
        return optional_dependency(self.package_name)

    def alignment_capability(self) -> CapabilityStatus:
        capability = self.capability()
        return CapabilityStatus("whisperx_korean_alignment", capability.status, package=capability.package, detail=capability.detail)

    def transcribe(self, audio_path: str | Path) -> AsrOutput:
        if self.capability().status is not ValidationStatus.PASS:
            return AsrOutput(ValidationStatus.NOT_RUN, reason="whisperx_not_installed", language_code=self.language_code)
        try:
            import whisperx  # lazy: unit tests never import or download the model
            model = whisperx.load_model(self.model_name, self.device, language=self.language_code)
            result = model.transcribe(str(audio_path), language=self.language_code)
            segments = _alignment_segments(result)
            return AsrOutput(ValidationStatus.PASS, text=" ".join(segment["text"] for segment in segments), segments=segments, language_code=self.language_code)
        except Exception as exc:
            return AsrOutput(ValidationStatus.UNKNOWN, reason=f"asr_exception:{type(exc).__name__}", language_code=self.language_code)

    def align(self, audio_path: str | Path, transcription: AsrOutput) -> AsrOutput:
        if transcription.status is not ValidationStatus.PASS:
            return AsrOutput(transcription.status, text=transcription.text, reason=transcription.reason, language_code=self.language_code)
        if self.alignment_capability().status is not ValidationStatus.PASS:
            return AsrOutput(ValidationStatus.NOT_RUN, text=transcription.text, reason="alignment_not_available", language_code=self.language_code)
        if not transcription.segments:
            return AsrOutput(ValidationStatus.UNKNOWN, text=transcription.text, reason="asr_segments_unavailable", language_code=self.language_code)
        try:
            import whisperx  # lazy import; this explicit call may load weights only in integration use
            align_model, metadata = whisperx.load_align_model(language_code=self.language_code, device=self.device)
            aligned = whisperx.align(transcription.segments, align_model, metadata, str(audio_path), self.device, return_char_alignments=False)
            words = _word_timestamps(aligned)
            if not words:
                return AsrOutput(ValidationStatus.UNKNOWN, text=transcription.text, reason="alignment_words_unavailable", language_code=self.language_code)
            return AsrOutput(ValidationStatus.PASS, text=transcription.text, words=words, language_code=self.language_code)
        except Exception as exc:
            return AsrOutput(ValidationStatus.UNKNOWN, text=transcription.text, reason=f"alignment_exception:{type(exc).__name__}", language_code=self.language_code)


def _alignment_segments(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Keep WhisperX segment bounds; alignment must never receive invented ones."""
    segments: list[dict[str, Any]] = []
    for item in result.get("segments", []):
        text = str(item.get("text", "")).strip()
        start, end = _number(item.get("start")), _number(item.get("end"))
        if text and start is not None and end is not None and end >= start:
            segments.append({"text": text, "start": start, "end": end})
    return segments


def _word_timestamps(result: dict[str, Any]) -> list[WordTimestamp]:
    words: list[WordTimestamp] = []
    for segment in result.get("segments", []):
        for item in segment.get("words", []):
            word = str(item.get("word", "")).strip()
            if word:
                words.append(WordTimestamp(word, _number(item.get("start")), _number(item.get("end")), _number(item.get("score"))))
    return words


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None
