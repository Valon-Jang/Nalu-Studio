"""Narrow, transport-free contract for the future FAST Speaker worker."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, runtime_checkable


FAST_SPEAKER_BACKEND_SCHEMA_VERSION = "luna-fast-speaker-backend/1"


@dataclass(frozen=True)
class FastPhrase:
    """One phrase supplied to the unchanged one-take FAST primitive."""

    phrase_id: str
    text: str
    sentence_final: bool
    forced: bool

    def __post_init__(self) -> None:
        if not self.phrase_id:
            raise ValueError("phrase_id is required")
        if not self.text or not self.text.strip():
            raise ValueError("phrase text is required")


@dataclass(frozen=True)
class FastSynthesisResult:
    """In-memory result of one current-FAST phrase synthesis.

    ``waveform`` remains opaque so a real Chatterbox tensor and a deterministic
    test double share one interface. ``pcm_s16le`` is always little-endian mono
    PCM and is suitable for the S02 worker transport; no WAV is written here.
    """

    phrase: FastPhrase
    spoken_text: str
    seed: int
    waveform: Any
    pcm_s16le: bytes
    sample_rate: int
    generation_seconds: float
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = FAST_SPEAKER_BACKEND_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.spoken_text or not self.spoken_text.strip():
            raise ValueError("spoken_text is required")
        if not 0 <= self.seed < 2**31:
            raise ValueError("seed must be in [0, 2^31)")
        if self.sample_rate <= 0:
            raise ValueError("sample_rate must be positive")
        if self.generation_seconds < 0:
            raise ValueError("generation_seconds must not be negative")
        if not isinstance(self.pcm_s16le, bytes) or not self.pcm_s16le:
            raise ValueError("pcm_s16le must be non-empty bytes")
        if len(self.pcm_s16le) % 2:
            raise ValueError("pcm_s16le must contain whole 16-bit samples")


@runtime_checkable
class FastBackend(Protocol):
    """Minimal surface shared by the real runtime and deterministic fake."""

    def initialize_once(self) -> Mapping[str, Any]:
        """Load or return the already-loaded fixed Luna runtime."""

    def split_fast_text(self, text: str) -> tuple[FastPhrase, ...]:
        """Apply the current Luna respell and phrase-splitting rules."""

    def postprocess_to_pcm_s16le(self, waveform: Any) -> bytes:
        """Apply the current FAST peak guard and return mono PCM16 bytes."""

    def synthesize_fast_phrase(self, phrase: FastPhrase, seed: int) -> FastSynthesisResult:
        """Generate exactly one fixed-parameter FAST take for one phrase."""
