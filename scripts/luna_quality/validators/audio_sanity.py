"""Deterministic WAV integrity checks for Luna shadow validation.

This module intentionally has no model or production-pipeline dependency.  It
only inspects an existing WAV and always reports a structured failure instead
of substituting audio or silently treating an unreadable file as valid.
"""
from __future__ import annotations

import hashlib
import json
import math
import struct
import wave
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..contracts import ValidationResult, ValidationStatus
from ..hashing import sha256_file


@dataclass(frozen=True)
class AudioSanityConfig:
    """Versioned thresholds; changing any field changes the validator version."""

    config_version: str = "1"
    expected_sample_rate_hz: int = 24000
    minimum_duration_seconds: float = 0.10
    silence_threshold_dbfs: float = -60.0
    maximum_leading_silence_seconds: float = 1.50
    maximum_trailing_silence_seconds: float = 1.50
    maximum_internal_silence_seconds: float = 0.75
    peak_guard: float = 0.89
    maximum_clipping_ratio: float = 0.001
    maximum_dc_offset: float = 0.02
    abrupt_end_window_seconds: float = 0.005
    abrupt_end_max_rms_dbfs: float = -25.0
    tail_window_seconds: float = 0.50
    maximum_tail_seconds: float = 1.50

    def __post_init__(self) -> None:
        if self.minimum_duration_seconds <= 0 or self.expected_sample_rate_hz <= 0:
            raise ValueError("duration and sample rate must be positive")
        if not 0 < self.peak_guard <= 1 or not 0 <= self.maximum_clipping_ratio <= 1:
            raise ValueError("peak and clipping thresholds must be within range")

    @property
    def config_hash(self) -> str:
        payload = json.dumps(asdict(self), sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


class AudioSanityValidator:
    validator_name = "audio_sanity"

    def __init__(self, config: AudioSanityConfig | None = None) -> None:
        self.config = config or AudioSanityConfig()

    @property
    def validator_version(self) -> str:
        return f"audio-sanity/{self.config.config_version}+{self.config.config_hash[:12]}"

    def validate(self, source_wav_path: str | Path) -> ValidationResult:
        started_at = _now()
        path = Path(source_wav_path)
        source_hashes: dict[str, str] = {}
        if not path.is_file():
            return self._result(ValidationStatus.FAIL, ["file_missing"], {}, source_hashes, started_at)
        try:
            source_hashes["source_wav_sha256"] = sha256_file(path)
            samples, sample_rate, channels, sample_width = _read_wav(path)
        except (OSError, EOFError, ValueError, wave.Error, struct.error) as exc:
            return self._result(
                ValidationStatus.FAIL, ["decode_error"], {"decode_error_type": type(exc).__name__}, source_hashes, started_at
            )

        metrics = _metrics(samples, sample_rate, channels, sample_width, self.config)
        reasons = _failures(metrics, self.config)
        return self._result(
            ValidationStatus.FAIL if reasons else ValidationStatus.PASS,
            reasons,
            metrics,
            source_hashes,
            started_at,
        )

    def _result(self, status, reasons, metrics, source_hashes, started_at) -> ValidationResult:
        return ValidationResult(
            validator_name=self.validator_name,
            validator_version=self.validator_version,
            status=status,
            hard_gate=True,
            reasons=reasons,
            metrics={**metrics, "config_hash": self.config.config_hash, "config_version": self.config.config_version},
            source_hashes=source_hashes,
            started_at=started_at,
            finished_at=_now(),
        )


def _read_wav(path: Path) -> tuple[list[float], int, int, int]:
    with wave.open(str(path), "rb") as reader:
        if reader.getcomptype() != "NONE":
            raise ValueError("compressed WAV is not supported by the deterministic decoder")
        channels, sample_width, sample_rate, frames = reader.getnchannels(), reader.getsampwidth(), reader.getframerate(), reader.getnframes()
        if channels < 1 or sample_width not in (1, 2, 3, 4) or frames < 1:
            raise ValueError("unsupported WAV format or empty waveform")
        raw = reader.readframes(frames)
    if len(raw) != frames * channels * sample_width:
        raise ValueError("truncated WAV payload")
    # Convert every interleaved channel to a deterministic mono analysis view.
    values = _decode_interleaved(raw, sample_width)
    samples = [sum(values[i : i + channels]) / channels for i in range(0, len(values), channels)]
    return samples, sample_rate, channels, sample_width


def _decode_interleaved(raw: bytes, width: int) -> list[float]:
    scale = float(1 << (8 * width - 1))
    if width == 1:
        return [(byte - 128) / 128.0 for byte in raw]
    if width == 2:
        return [value / scale for (value,) in struct.iter_unpack("<h", raw)]
    if width == 4:
        return [value / scale for (value,) in struct.iter_unpack("<i", raw)]
    values: list[float] = []
    for index in range(0, len(raw), 3):
        value = int.from_bytes(raw[index : index + 3], "little", signed=False)
        if value & 0x800000:
            value -= 0x1000000
        values.append(value / scale)
    return values


def _metrics(samples, sample_rate, channels, sample_width, config):
    count = len(samples)
    finite = all(math.isfinite(value) for value in samples)
    if not finite:
        return {"sample_count": count, "sample_rate_hz": sample_rate, "channels": channels, "sample_width_bits": sample_width * 8, "finite": False}
    peak = max((abs(value) for value in samples), default=0.0)
    rms = math.sqrt(sum(value * value for value in samples) / count) if count else 0.0
    silence_amplitude = 10 ** (config.silence_threshold_dbfs / 20.0)
    active = [abs(value) > silence_amplitude for value in samples]
    leading = _edge_silence(active, from_start=True) / sample_rate
    trailing = _edge_silence(active, from_start=False) / sample_rate
    internal = _longest_internal_silence(active) / sample_rate
    end_window = max(1, round(config.abrupt_end_window_seconds * sample_rate))
    end_rms = math.sqrt(sum(value * value for value in samples[-end_window:]) / min(end_window, count))
    tail_active = _edge_silence(active, from_start=False) / sample_rate
    clipping = sum(abs(value) >= 0.999 for value in samples) / count
    return {
        "sample_count": count, "duration_seconds": count / sample_rate, "sample_rate_hz": sample_rate,
        "channels": channels, "sample_width_bits": sample_width * 8, "finite": True,
        "zero_waveform": peak == 0.0, "peak": peak, "peak_dbfs": _dbfs(peak), "rms": rms,
        "rms_dbfs": _dbfs(rms), "crest_factor_db": _dbfs(peak / rms) if rms else float("inf"),
        "clipping_ratio": clipping, "dc_offset": sum(samples) / count,
        "leading_silence_seconds": leading, "trailing_silence_seconds": trailing,
        "longest_internal_silence_seconds": internal, "end_window_rms_dbfs": _dbfs(end_rms),
        "tail_silence_seconds": tail_active,
    }


def _failures(metrics, config):
    if not metrics.get("finite", False): return ["non_finite_samples"]
    failures = []
    def fail(condition, reason):
        if condition: failures.append(reason)
    fail(metrics["sample_rate_hz"] != config.expected_sample_rate_hz, "unexpected_sample_rate")
    fail(metrics["duration_seconds"] < config.minimum_duration_seconds, "file_too_short")
    fail(metrics["zero_waveform"], "zero_waveform")
    fail(metrics["peak"] > config.peak_guard, "peak_guard_exceeded")
    fail(metrics["clipping_ratio"] > config.maximum_clipping_ratio, "clipping_ratio_exceeded")
    fail(abs(metrics["dc_offset"]) > config.maximum_dc_offset, "dc_offset_exceeded")
    fail(metrics["leading_silence_seconds"] > config.maximum_leading_silence_seconds, "leading_silence_too_long")
    fail(metrics["trailing_silence_seconds"] > config.maximum_trailing_silence_seconds, "trailing_silence_too_long")
    fail(metrics["longest_internal_silence_seconds"] > config.maximum_internal_silence_seconds, "internal_silence_too_long")
    fail(metrics["tail_silence_seconds"] > config.maximum_tail_seconds, "tail_too_long")
    fail(metrics["end_window_rms_dbfs"] > config.abrupt_end_max_rms_dbfs, "abrupt_end")
    return failures


def _edge_silence(active, from_start):
    iterable = active if from_start else reversed(active)
    count = 0
    for is_active in iterable:
        if is_active: break
        count += 1
    return count


def _longest_internal_silence(active):
    first = next((i for i, value in enumerate(active) if value), None)
    last = next((i for i, value in enumerate(reversed(active)) if value), None)
    if first is None or last is None: return 0
    longest = current = 0
    for value in active[first : len(active) - last]:
        current = 0 if value else current + 1
        longest = max(longest, current)
    return longest


def _dbfs(value): return 20.0 * math.log10(max(value, 1e-12))
def _now(): return datetime.now(timezone.utc).isoformat()
