"""Non-Tk controller for manual phrase-first FAST Speaker playback."""

from __future__ import annotations

from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
import threading
import time
from typing import Any, Callable, Mapping, Protocol
from uuid import uuid4

from .audio_sink import AudioSink
from .contracts import FastPhrase
from .ipc import WorkerCommand
from .pcm import PcmFrame


class WorkerRequester(Protocol):
    def request(self, command: WorkerCommand, timeout_seconds: float = 30.0) -> Mapping[str, Any]: ...


@dataclass
class ManualRun:
    session_id: str
    generation_id: str
    phrases: tuple[FastPhrase, ...]
    submitted_monotonic: float
    seed: int
    next_index: int = 0
    cached: list[PcmFrame] = field(default_factory=list)
    current_sentence: list[PcmFrame] = field(default_factory=list)
    ready_results: deque[Mapping[str, Any]] = field(default_factory=deque)


def split_current_luna_phrases(text: str) -> tuple[FastPhrase, ...]:
    from scripts import luna_narration_pipeline_v1 as pipeline

    spoken_text = pipeline.respell(text.strip())
    return tuple(
        FastPhrase(f"P{index:02d}", item["text"], bool(item["sentence_final"]), bool(item["forced"]))
        for index, item in enumerate(pipeline.build_phrase_list(spoken_text))
    )


class FastSpeakerController:
    """Keeps Tk responsive; model IPC and audio completion run outside Tk callbacks."""

    def __init__(self, worker: WorkerRequester, audio: AudioSink, *, split_text: Callable[[str], tuple[FastPhrase, ...]] = split_current_luna_phrases) -> None:
        self.worker, self.audio, self.split_text = worker, audio, split_text
        self._lock = threading.RLock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="luna-fast-speaker")
        self._pending: deque[ManualRun] = deque()
        self._active: ManualRun | None = None
        self._synthesis_busy = False
        self._audio_busy = False
        self._paused = False
        self._state = "ready"
        self._last_phrase: PcmFrame | None = None
        self._last_sentence: tuple[PcmFrame, ...] = ()
        self._recent_phrases: list[tuple[str, PcmFrame, int]] = []
        self._metrics: dict[str, Any] = {"warm_ttfa_seconds": None, "rolling_rtf": [], "last": None}

    def submit(self, text: str, seed: int = 20260826) -> str:
        phrases = self.split_text(text)
        if not phrases:
            raise ValueError("text produced no phrases")
        run = ManualRun(uuid4().hex, uuid4().hex, phrases, time.perf_counter(), seed)
        with self._lock:
            self._pending.append(run)
            self._state = "queued" if self._active else "synthesizing"
            self._activate_next_locked()
        return run.session_id

    def stop(self) -> None:
        with self._lock:
            active = self._active
            self._pending.clear()
            self._paused = False
            self._state = "stopped"
            if active is not None:
                active.generation_id = uuid4().hex
                self._executor.submit(self._invalidate, active.session_id, active.generation_id)
            self.audio.stop()
            self._audio_busy = False

    def pause(self) -> None:
        with self._lock:
            self._paused = True
            self._state = "pause_pending" if self._audio_busy else "paused"

    def continue_playback(self) -> None:
        with self._lock:
            self._paused = False
            self._state = "ready"
            self._pump_locked()

    def replay_last_phrase(self) -> bool:
        with self._lock:
            if self._audio_busy or self._last_phrase is None:
                return False
            self._play_locked(self._last_phrase, None)
            return True

    def replay_current_sentence(self) -> bool:
        with self._lock:
            if self._audio_busy or not self._last_sentence:
                return False
            frames = iter(self._last_sentence)
            self._play_replay_sequence_locked(frames)
            return True

    def recent_phrases(self) -> tuple[tuple[str, PcmFrame, int], ...]:
        with self._lock:
            return tuple(self._recent_phrases)

    def snapshot(self) -> Mapping[str, Any]:
        with self._lock:
            rolling = self._metrics["rolling_rtf"]
            return {
                "state": self._state,
                "paused": self._paused,
                "queue_runs": len(self._pending) + (1 if self._active else 0),
                "audio_busy": self._audio_busy,
                "synthesis_busy": self._synthesis_busy,
                "warm_ttfa_seconds": self._metrics["warm_ttfa_seconds"],
                "average_rtf": (sum(rolling) / len(rolling)) if rolling else None,
                "last_metrics": self._metrics["last"],
            }

    def close(self) -> None:
        self.stop()
        self._executor.shutdown(wait=False, cancel_futures=True)
        self.audio.close()

    def _activate_next_locked(self) -> None:
        if self._active is None and self._pending:
            self._active = self._pending.popleft()
            self._pump_locked()
        elif self._active is None:
            self._state = "ready"

    def _pump_locked(self) -> None:
        run = self._active
        if run is None or self._paused or self._state == "stopped":
            return
        if not self._synthesis_busy and not run.ready_results and run.next_index < len(run.phrases):
            phrase = run.phrases[run.next_index]
            run.next_index += 1
            self._synthesis_busy = True
            self._state = "synthesizing" if not self._audio_busy else "playing"
            self._executor.submit(self._synthesize, run, phrase, int(run.seed))
        if not self._audio_busy and run.ready_results:
            result = run.ready_results.popleft()
            if not result.get("stale", False):
                frame = PcmFrame.from_mapping(result["pcm"])
                self._play_locked(frame, result)
            else:
                if run.next_index >= len(run.phrases) and not self._synthesis_busy:
                    self._active = None
                    self._activate_next_locked()
                self._pump_locked()

    def _synthesize(self, run: ManualRun, phrase: FastPhrase, seed: int) -> None:
        requested_generation = run.generation_id
        try:
            response = self.worker.request(WorkerCommand("synthesize", uuid4().hex, run.session_id, requested_generation, phrase, seed), timeout_seconds=180)
        except Exception as error:
            response = {"stale": True, "error": f"{type(error).__name__}: {error}"}
        with self._lock:
            self._synthesis_busy = False
            if self._active is run:
                if run.generation_id != requested_generation:
                    response = {**response, "stale": True}
                run.ready_results.append(response)
                self._pump_locked()

    def _invalidate(self, session_id: str, generation_id: str) -> None:
        try:
            self.worker.request(WorkerCommand("invalidate", uuid4().hex, session_id, generation_id), timeout_seconds=10)
        except Exception:
            pass

    def _play_locked(self, frame: PcmFrame, result: Mapping[str, Any] | None) -> None:
        self._audio_busy = True
        self._state = "playing"
        run = self._active

        def started() -> None:
            with self._lock:
                if run is not None and self._metrics["warm_ttfa_seconds"] is None and _has_non_silent_pcm(frame):
                    self._metrics["warm_ttfa_seconds"] = time.perf_counter() - run.submitted_monotonic

        def finished() -> None:
            with self._lock:
                self._audio_busy = False
                self._last_phrase = frame
                if run is not None:
                    run.cached.append(frame)
                    run.current_sentence.append(frame)
                    if result is not None:
                        phrase_text = str(result.get("phrase", {}).get("text", ""))
                        self._recent_phrases = (self._recent_phrases + [(phrase_text, frame, run.seed)])[-3:]
                        metrics = result.get("metrics", {})
                        self._metrics["last"] = metrics
                        if isinstance(metrics.get("rtf"), (int, float)):
                            self._metrics["rolling_rtf"] = (self._metrics["rolling_rtf"] + [metrics["rtf"]])[-10:]
                    if result is not None and result.get("phrase", {}).get("sentence_final"):
                        self._last_sentence = tuple(run.current_sentence)
                        run.current_sentence.clear()
                    if run.next_index >= len(run.phrases) and not self._synthesis_busy and not run.ready_results:
                        self._active = None
                        self._activate_next_locked()
                if self._paused:
                    self._state = "paused"
                else:
                    self._pump_locked()

        self.audio.play(frame, started, finished)
        if run is not None:
            self._pump_locked()  # prefetch phrase N+1 during phrase N playback

    def _play_replay_sequence_locked(self, frames: Any) -> None:
        try:
            frame = next(frames)
        except StopIteration:
            return
        self._audio_busy = True
        self.audio.play(frame, lambda: None, lambda: self._replay_next(frames))

    def _replay_next(self, frames: Any) -> None:
        with self._lock:
            self._audio_busy = False
            self._play_replay_sequence_locked(frames)


def _has_non_silent_pcm(frame: PcmFrame) -> bool:
    return any(frame.pcm_s16le[index:index + 2] != b"\x00\x00" for index in range(0, len(frame.pcm_s16le), 2))
