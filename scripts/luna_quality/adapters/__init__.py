"""Optional external-model adapters, imported without loading model weights."""

from .whisperx_adapter import AsrOutput, WhisperXAdapter, WordTimestamp
from .chatterbox_ve_adapter import ChatterboxVEAdapter
from .speechbrain_adapter import SpeechBrainAdapter

__all__ = ["AsrOutput", "WhisperXAdapter", "WordTimestamp", "ChatterboxVEAdapter", "SpeechBrainAdapter"]
