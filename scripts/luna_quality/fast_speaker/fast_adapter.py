"""Adapter from the existing resident runtime to the FAST Speaker contract.

This module deliberately imports the existing Luna text helpers instead of
copying or modifying their rules. It does not create workers, UI, queues, or
WAV files; those belong to later stages.
"""

from __future__ import annotations

from array import array
import importlib
import sys
import time
from typing import Any, Mapping

from .contracts import FastBackend, FastPhrase, FastSynthesisResult


def waveform_to_pcm_s16le(waveform: Any) -> bytes:
    """Convert an already peak-limited mono waveform to little-endian PCM16."""

    samples = _flatten_waveform(waveform)
    if not samples:
        raise ValueError("waveform must contain at least one sample")
    pcm = array(
        "h",
        (
            max(
                -32768,
                min(
                    32767,
                    int(round(float(sample) * (32767.0 if float(sample) >= 0 else 32768.0))),
                ),
            )
            for sample in samples
        ),
    )
    if sys.byteorder != "little":
        pcm.byteswap()
    return pcm.tobytes()


def _flatten_waveform(waveform: Any) -> list[float]:
    value = waveform
    if hasattr(value, "detach"):
        value = value.detach()
    if hasattr(value, "cpu"):
        value = value.cpu()
    if hasattr(value, "reshape"):
        value = value.reshape(-1)
    if hasattr(value, "tolist"):
        value = value.tolist()
    if not isinstance(value, (list, tuple)):
        raise TypeError("waveform must expose tensor/list samples")
    flattened: list[float] = []
    for sample in value:
        if isinstance(sample, (list, tuple)):
            flattened.extend(float(item) for item in sample)
        else:
            flattened.append(float(sample))
    return flattened


class LunaFastBackend(FastBackend):
    """Expose the current Luna FAST primitive without changing its CLI path."""

    def __init__(self, runtime: Any) -> None:
        self.runtime = runtime

    def initialize_once(self) -> Mapping[str, Any]:
        return self.runtime.start()

    def split_fast_text(self, text: str) -> tuple[FastPhrase, ...]:
        if not text or not text.strip():
            raise ValueError("text is required")
        from scripts import luna_narration_pipeline_v1 as pipeline

        spoken_text = pipeline.respell(text.strip())
        return tuple(
            FastPhrase(
                phrase_id=f"P{index:02d}",
                text=item["text"],
                sentence_final=bool(item["sentence_final"]),
                forced=bool(item["forced"]),
            )
            for index, item in enumerate(pipeline.build_phrase_list(spoken_text))
        )

    def postprocess_to_pcm_s16le(self, waveform: Any) -> bytes:
        return waveform_to_pcm_s16le(waveform)

    def synthesize_fast_phrase(self, phrase: FastPhrase, seed: int) -> FastSynthesisResult:
        waveform, spoken_text, generation_seconds = self._synthesize_current_fast(phrase.text, seed)
        return FastSynthesisResult(
            phrase=phrase,
            spoken_text=spoken_text,
            seed=seed,
            waveform=waveform,
            pcm_s16le=self.postprocess_to_pcm_s16le(waveform),
            sample_rate=int(self.runtime.model.sr),
            generation_seconds=generation_seconds,
            metadata={
                "engine": "Chatterbox Multilingual V3",
                "voice": "Candidate B",
                "model_load_count": self.runtime.model_load_count,
                "condition_prepare_count": getattr(self.runtime._conditioner, "prepare_count", None),
            },
        )

    def _synthesize_current_fast(self, text: str, seed: int) -> tuple[Any, str, float]:
        """Reuse the existing resident FAST primitive without changing its CLI.

        The legacy runtime has no memory-audio public surface. This adapter
        uses its existing model, lock, seed setter, and fixed parameter module
        under the same serialized invocation boundary; normal FAST continues
        to execute its unchanged WAV path.
        """

        self.runtime.start()
        with self.runtime._lock:
            assert self.runtime.model is not None
            self.runtime._seed_setter(seed)
            pipeline = importlib.import_module("scripts.luna_narration_pipeline_v1")
            spoken_text = pipeline.respell(text)
            started = time.perf_counter()
            waveform = self.runtime.model.generate(
                spoken_text,
                audio_prompt_path=None,
                **self._synthesis_parameters(),
            )
            generation_seconds = time.perf_counter() - started
            return self._peak_limit_current_fast(waveform), spoken_text, generation_seconds

    @staticmethod
    def _synthesis_parameters() -> Mapping[str, Any]:
        from scripts.luna_quality.voice_runtime.runtime import SYNTHESIS_PARAMETERS

        return SYNTHESIS_PARAMETERS

    @staticmethod
    def _peak_limit_current_fast(waveform: Any) -> Any:
        if not hasattr(waveform, "abs"):
            return waveform
        peak = float(waveform.abs().max())
        if peak > 0.89:
            return waveform * (0.89 / peak)
        return waveform


class FakeFastBackend(FastBackend):
    """Deterministic in-memory PCM backend for later controller/UI tests."""

    SAMPLE_RATE = 24_000
    KNOWN_PCM_S16LE = b"\x00\x00\x00@\x00\xc0\xff\x7f"
    KNOWN_WAVEFORM = (0.0, 0.5, -0.5, 1.0)

    def __init__(self) -> None:
        self.initialize_count = 0
        self.requests: list[tuple[FastPhrase, int]] = []

    def initialize_once(self) -> Mapping[str, Any]:
        self.initialize_count += 1
        return {"status": "ready", "backend": "fake", "initialize_count": self.initialize_count}

    def split_fast_text(self, text: str) -> tuple[FastPhrase, ...]:
        if not text or not text.strip():
            raise ValueError("text is required")
        return (FastPhrase("P00", text.strip(), True, False),)

    def postprocess_to_pcm_s16le(self, waveform: Any) -> bytes:
        if tuple(waveform) != self.KNOWN_WAVEFORM:
            return waveform_to_pcm_s16le(waveform)
        return self.KNOWN_PCM_S16LE

    def synthesize_fast_phrase(self, phrase: FastPhrase, seed: int) -> FastSynthesisResult:
        if not 0 <= seed < 2**31:
            raise ValueError("seed must be in [0, 2^31)")
        self.requests.append((phrase, seed))
        return FastSynthesisResult(
            phrase=phrase,
            spoken_text=phrase.text,
            seed=seed,
            waveform=self.KNOWN_WAVEFORM,
            pcm_s16le=self.KNOWN_PCM_S16LE,
            sample_rate=self.SAMPLE_RATE,
            generation_seconds=0.001,
            metadata={"backend": "fake", "deterministic": True},
        )
