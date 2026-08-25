"""Versioned in-memory PCM contract for the FAST Speaker worker."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


PCM_FRAME_SCHEMA_VERSION = "luna-fast-speaker-pcm/1"


@dataclass(frozen=True)
class PcmFrame:
    """One mono signed-16-bit little-endian audio frame kept only in memory."""

    pcm_s16le: bytes
    sample_rate: int
    channels: int = 1
    schema_version: str = PCM_FRAME_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.pcm_s16le, bytes) or not self.pcm_s16le:
            raise ValueError("pcm_s16le must be non-empty bytes")
        if len(self.pcm_s16le) % 2:
            raise ValueError("pcm_s16le must contain whole 16-bit samples")
        if self.sample_rate <= 0:
            raise ValueError("sample_rate must be positive")
        if self.channels != 1:
            raise ValueError("FAST Speaker PCM must be mono")
        if self.schema_version != PCM_FRAME_SCHEMA_VERSION:
            raise ValueError(f"unsupported PCM schema: {self.schema_version}")

    @property
    def sample_count(self) -> int:
        return len(self.pcm_s16le) // 2

    @property
    def duration_seconds(self) -> float:
        return self.sample_count / self.sample_rate

    def to_mapping(self) -> Mapping[str, Any]:
        return {
            "schema_version": self.schema_version,
            "encoding": "pcm_s16le",
            "channels": self.channels,
            "sample_rate": self.sample_rate,
            "sample_count": self.sample_count,
            "pcm_s16le": self.pcm_s16le,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "PcmFrame":
        if str(value.get("encoding", "")) != "pcm_s16le":
            raise ValueError("only pcm_s16le is supported")
        return cls(
            pcm_s16le=value.get("pcm_s16le", b""),
            sample_rate=int(value.get("sample_rate", 0)),
            channels=int(value.get("channels", 1)),
            schema_version=str(value.get("schema_version", PCM_FRAME_SCHEMA_VERSION)),
        )
