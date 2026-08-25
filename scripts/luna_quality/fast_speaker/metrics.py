"""Timing records for FAST Speaker worker results, without playback claims."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .pcm import PcmFrame


WORKER_METRICS_SCHEMA_VERSION = "luna-fast-speaker-metrics/1"


@dataclass(frozen=True)
class PhraseMetrics:
    """Worker-side timings; audio-callback TTFA belongs to the future UI."""

    worker_ready_seconds: float | None
    synthesis_started_monotonic: float
    synthesis_finished_monotonic: float
    pcm_ready_monotonic: float
    audio_duration_seconds: float
    generation_seconds: float
    rtf: float | None
    schema_version: str = WORKER_METRICS_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.synthesis_finished_monotonic < self.synthesis_started_monotonic:
            raise ValueError("synthesis finish precedes start")
        if self.pcm_ready_monotonic < self.synthesis_finished_monotonic:
            raise ValueError("PCM readiness precedes synthesis finish")
        if self.audio_duration_seconds <= 0:
            raise ValueError("audio duration must be positive")
        if self.generation_seconds < 0:
            raise ValueError("generation_seconds must not be negative")
        if self.rtf is not None and self.rtf < 0:
            raise ValueError("rtf must not be negative")

    def to_mapping(self) -> Mapping[str, Any]:
        return {
            "schema_version": self.schema_version,
            "worker_ready_seconds": self.worker_ready_seconds,
            "synthesis_started_monotonic": self.synthesis_started_monotonic,
            "synthesis_finished_monotonic": self.synthesis_finished_monotonic,
            "pcm_ready_monotonic": self.pcm_ready_monotonic,
            "audio_duration_seconds": self.audio_duration_seconds,
            "generation_seconds": self.generation_seconds,
            "rtf": self.rtf,
            "playback_ttfa": "not_run",
        }


def phrase_metrics(
    *,
    worker_ready_seconds: float | None,
    synthesis_started_monotonic: float,
    synthesis_finished_monotonic: float,
    pcm_ready_monotonic: float,
    frame: PcmFrame,
    generation_seconds: float,
) -> PhraseMetrics:
    duration = frame.duration_seconds
    return PhraseMetrics(
        worker_ready_seconds=worker_ready_seconds,
        synthesis_started_monotonic=synthesis_started_monotonic,
        synthesis_finished_monotonic=synthesis_finished_monotonic,
        pcm_ready_monotonic=pcm_ready_monotonic,
        audio_duration_seconds=duration,
        generation_seconds=generation_seconds,
        rtf=(generation_seconds / duration) if duration else None,
    )
