"""Optional external-model adapters, imported without loading model weights."""

from .whisperx_adapter import AsrOutput, WhisperXAdapter, WordTimestamp

__all__ = ["AsrOutput", "WhisperXAdapter", "WordTimestamp"]
