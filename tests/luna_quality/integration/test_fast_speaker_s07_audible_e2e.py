"""Opt-in S07 real V3/Candidate B playback and restart audit."""

from __future__ import annotations

import json
import os
from pathlib import Path
import time
import unittest

from scripts.luna_quality.fast_speaker.audio_sink import WinmmAudioSink
from scripts.luna_quality.fast_speaker.batch import BatchSession
from scripts.luna_quality.fast_speaker.contracts import FastPhrase
from scripts.luna_quality.fast_speaker.controller import FastSpeakerController
from scripts.luna_quality.fast_speaker.worker import WorkerProcess


ROOT = Path(__file__).resolve().parents[3]


class MeasuringAudioSink:
    def __init__(self) -> None:
        self.delegate = WinmmAudioSink()
        self.starts: list[float] = []
        self.finishes: list[float] = []

    def play(self, frame, on_started, on_finished) -> None:
        def started() -> None:
            self.starts.append(time.perf_counter())
            on_started()

        def finished() -> None:
            self.finishes.append(time.perf_counter())
            on_finished()

        self.delegate.play(frame, started, finished)

    def stop(self) -> None:
        self.delegate.stop()

    def close(self) -> None:
        self.delegate.close()


def two_phrases(_: str) -> tuple[FastPhrase, ...]:
    return (
        FastPhrase("P00", "루나 실제 발화 검사입니다.", True, False),
        FastPhrase("P01", "두 번째 구절도 재생합니다.", True, False),
    )


def wait_for(predicate, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError(f"timed out after {timeout}s")


@unittest.skipUnless(
    os.getenv("RUN_LUNA_FAST_SPEAKER_AUDIBLE") == "1",
    "set RUN_LUNA_FAST_SPEAKER_AUDIBLE=1 to play real Luna through the Windows default speaker",
)
class FastSpeakerS07AudibleE2ETest(unittest.TestCase):
    def test_real_speech_metrics_no_normal_wav_and_clean_restart(self) -> None:
        before_wavs = {path.resolve() for path in (ROOT / "fast_speaker").glob("**/*.wav")} if (ROOT / "fast_speaker").exists() else set()
        process = WorkerProcess(ROOT)
        controller = None
        batch = BatchSession.from_text("s07-real", "루나 실제 발화 검사입니다.\n두 번째 구절도 재생합니다.", code_revision="S07")
        try:
            cold_started = time.perf_counter()
            client = process.start(180)
            cold_ready = time.perf_counter() - cold_started
            sink = MeasuringAudioSink()
            controller = FastSpeakerController(client, sink, split_text=two_phrases)
            controller.submit(batch.source_text, seed=20260826)
            wait_for(lambda: len(sink.finishes) == 2 and controller.snapshot()["state"] == "ready", 360)
            view = controller.snapshot()
            recent = controller.recent_phrases()
            gaps = [sink.starts[index] - sink.finishes[index - 1] for index in range(1, len(sink.starts))]
            self.assertEqual(len(recent), 2)
            self.assertTrue(all(item.frame.sample_rate == 24000 and item.frame.pcm_s16le for item in recent))
            self.assertIsNotNone(view["warm_ttfa_seconds"])
            self.assertTrue(all(float(item.metrics["audio_duration_seconds"]) > 0 for item in recent))
            self.assertTrue(all(float(item.metrics["rtf"]) >= 0 for item in recent))

            session_before = json.dumps(batch.to_mapping(), ensure_ascii=False, sort_keys=True)
            restart_started = time.perf_counter()
            replacement = process.restart(180)
            restart_ready = time.perf_counter() - restart_started
            controller.replace_worker_after_restart(replacement)
            self.assertEqual(json.dumps(batch.to_mapping(), ensure_ascii=False, sort_keys=True), session_before)
            self.assertEqual(controller.snapshot()["state"], "ready")

            report = {
                "cold_ready_seconds": cold_ready,
                "restart_ready_seconds": restart_ready,
                "warm_ttfa_seconds": view["warm_ttfa_seconds"],
                "phrases": [dict(item.metrics) for item in recent],
                "average_rtf": view["average_rtf"],
                "inter_phrase_gaps_seconds": gaps,
                "underrun_count": view["underrun_count"],
                "sample_rate": recent[0].frame.sample_rate,
                "normal_wav_written": False,
            }
            print("S07_REAL_METRICS=" + json.dumps(report, ensure_ascii=False, sort_keys=True))
        finally:
            if controller is not None:
                controller.close()
            process.shutdown()
        after_wavs = {path.resolve() for path in (ROOT / "fast_speaker").glob("**/*.wav")} if (ROOT / "fast_speaker").exists() else set()
        self.assertEqual(after_wavs, before_wavs)


if __name__ == "__main__":
    unittest.main()
