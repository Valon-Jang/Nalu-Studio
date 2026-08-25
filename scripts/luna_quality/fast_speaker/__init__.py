"""FAST Speaker v1 contracts and adapters introduced in S01."""

from .contracts import (
    FAST_SPEAKER_BACKEND_SCHEMA_VERSION,
    FastBackend,
    FastPhrase,
    FastSynthesisResult,
)
from .fast_adapter import FakeFastBackend, LunaFastBackend
from .ipc import WorkerCommand
from .pcm import PcmFrame

__all__ = [
    "FAST_SPEAKER_BACKEND_SCHEMA_VERSION",
    "FakeFastBackend",
    "FastBackend",
    "FastPhrase",
    "FastSynthesisResult",
    "LunaFastBackend",
    "PcmFrame",
    "WorkerCommand",
]
