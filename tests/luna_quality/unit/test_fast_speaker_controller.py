from __future__ import annotations

import time
import threading
import unittest

from scripts.luna_quality.fast_speaker.audio_sink import FakeAudioSink
from scripts.luna_quality.fast_speaker.controller import FastSpeakerController
from scripts.luna_quality.fast_speaker.contracts import FastPhrase
from scripts.luna_quality.fast_speaker.fast_adapter import FakeFastBackend
from scripts.luna_quality.fast_speaker.ipc import WorkerCommand


class FakeWorker:
    def __init__(self) -> None:
        self.commands: list[WorkerCommand] = []
        self.entered = threading.Event()
        self.release = threading.Event()
        self.block_synthesis = False

    def request(self, command: WorkerCommand, timeout_seconds: float = 30.0):
        self.commands.append(command)
        if command.command == "invalidate":
            return {"status": "ok", "invalidated": True}
        if command.command != "synthesize":
            return {"status": "ok"}
        self.entered.set()
        if self.block_synthesis:
            self.release.wait(2)
        return {
            "status": "ok", "stale": False,
            "phrase": {"phrase_id": command.phrase.phrase_id, "text": command.phrase.text, "sentence_final": command.phrase.sentence_final},
            "pcm": {"schema_version": "luna-fast-speaker-pcm/1", "encoding": "pcm_s16le", "channels": 1, "sample_rate": 24000, "sample_count": 4, "pcm_s16le": FakeFastBackend.KNOWN_PCM_S16LE},
            "metrics": {"rtf": 2.0, "generation_seconds": 0.001},
        }


def phrases(_: str) -> tuple[FastPhrase, ...]:
    return (FastPhrase("P00", "첫 구절", False, False), FastPhrase("P01", "둘째 구절.", True, False))


def wait_for(predicate) -> None:
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("timed out")


class FastSpeakerControllerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.worker, self.audio = FakeWorker(), FakeAudioSink()
        self.controller = FastSpeakerController(self.worker, self.audio, split_text=phrases)

    def tearDown(self) -> None:
        self.controller.close()

    def test_phrase_first_prefetch_pause_and_cached_replay(self) -> None:
        self.controller.submit("입력")
        wait_for(lambda: len(self.audio.frames) == 1)
        self.assertEqual(self.audio.frames[0].pcm_s16le, FakeFastBackend.KNOWN_PCM_S16LE)
        wait_for(lambda: len([item for item in self.worker.commands if item.command == "synthesize"]) == 2)
        self.controller.pause()
        self.audio.finish()
        self.assertEqual(self.controller.snapshot()["state"], "paused")
        self.assertEqual(self.controller.recent_phrases()[-1].text, "첫 구절")
        self.assertEqual(len(self.audio.frames), 1)
        self.controller.continue_playback()
        wait_for(lambda: len(self.audio.frames) == 2)
        self.audio.finish()
        wait_for(lambda: self.controller.replay_last_phrase())
        self.assertEqual(len([item for item in self.worker.commands if item.command == "synthesize"]), 2)
        self.audio.finish()
        self.assertTrue(self.controller.replay_current_sentence())
        self.audio.finish()
        self.audio.finish()

    def test_stop_invalidates_and_never_hands_late_result_to_audio(self) -> None:
        self.worker.block_synthesis = True
        self.controller.submit("입력")
        self.assertTrue(self.worker.entered.wait(1))
        self.controller.stop()
        self.worker.release.set()
        time.sleep(0.1)
        self.assertEqual(len(self.audio.frames), 0)
        self.assertTrue(self.audio.stopped)
        self.assertTrue(any(item.command == "invalidate" for item in self.worker.commands))

    def test_successful_worker_replacement_discards_old_request_and_accepts_new_one(self) -> None:
        self.worker.block_synthesis = True
        self.controller.submit("첫 작업")
        self.assertTrue(self.worker.entered.wait(1))
        new_worker = FakeWorker()
        self.controller.replace_worker_after_restart(new_worker)
        self.worker.release.set()
        self.controller.submit("새 작업")
        wait_for(lambda: len(self.audio.frames) == 1)
        self.assertTrue(any(item.command == "synthesize" for item in new_worker.commands))
        self.assertEqual(self.controller.snapshot()["state"], "playing")

    def test_stop_then_new_submission_is_not_blocked_by_old_run(self) -> None:
        self.worker.block_synthesis = True
        self.controller.submit("중단할 작업")
        self.assertTrue(self.worker.entered.wait(1))
        self.controller.stop()
        self.worker.release.set()
        self.controller.submit("새 작업")
        wait_for(lambda: len(self.audio.frames) == 1)
        self.assertEqual(self.controller.recent_phrases(), ())
        self.audio.finish()
        self.assertEqual(self.controller.recent_phrases()[0].text, "첫 구절")

    def test_metrics_include_ttfa_and_inter_phrase_gap(self) -> None:
        self.controller.submit("측정")
        wait_for(lambda: len(self.audio.frames) == 1)
        self.audio.finish()
        wait_for(lambda: len(self.audio.frames) == 2)
        self.audio.finish()
        view = self.controller.snapshot()
        self.assertIsNotNone(view["warm_ttfa_seconds"])
        self.assertEqual(len(view["inter_phrase_gaps_seconds"]), 1)
        self.assertEqual(len(self.controller.recent_phrases()), 2)

    def test_new_manual_input_queues_and_recent_history_is_bounded_to_three(self) -> None:
        one_phrase = lambda text: (FastPhrase("P00", text, True, False),)
        controller = FastSpeakerController(self.worker, self.audio, split_text=one_phrase)
        self.controller.close()
        self.controller = controller
        for text in ("하나", "둘", "셋", "넷"):
            controller.submit(text)
        for expected_count in range(1, 5):
            wait_for(lambda: len(self.audio.frames) == expected_count)
            self.audio.finish()
        wait_for(lambda: controller.snapshot()["state"] == "ready")
        self.assertEqual([item.text for item in controller.recent_phrases()], ["둘", "셋", "넷"])


if __name__ == "__main__":
    unittest.main()
