from __future__ import annotations

from pathlib import Path
import sys
import threading
import time
import unittest
from uuid import uuid4

from scripts.luna_quality.fast_speaker.contracts import FastPhrase
from scripts.luna_quality.fast_speaker.fast_adapter import FakeFastBackend
from scripts.luna_quality.fast_speaker.ipc import WorkerCommand
from scripts.luna_quality.fast_speaker.worker import ResidentWorker, WorkerClient, WorkerPipeServer, WorkerProcess


ROOT = Path(__file__).resolve().parents[3]


def fake_backend_factory(_: Path) -> FakeFastBackend:
    return FakeFastBackend()


class BlockingFakeBackend(FakeFastBackend):
    def __init__(self) -> None:
        super().__init__()
        self.entered = threading.Event()
        self.release = threading.Event()

    def synthesize_fast_phrase(self, phrase: FastPhrase, seed: int):
        self.entered.set()
        if not self.release.wait(5):
            raise TimeoutError("test backend was not released")
        return super().synthesize_fast_phrase(phrase, seed)


class WorkerHarness:
    def __init__(self, backend: FakeFastBackend) -> None:
        self.address = rf"\\.\pipe\luna-fast-speaker-test-{uuid4().hex}"
        self.authkey = uuid4().bytes
        self.worker = ResidentWorker(ROOT, backend_factory=lambda _: backend)
        self.server = WorkerPipeServer(self.address, self.authkey, self.worker)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.client = WorkerClient(self.address, self.authkey)
        self.client.request(WorkerCommand("health", uuid4().hex))

    def close(self) -> None:
        if self.thread.is_alive():
            self.client.request(WorkerCommand("shutdown", uuid4().hex))
            self.thread.join(2)


class FastSpeakerWorkerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.backend = FakeFastBackend()
        self.harness = WorkerHarness(self.backend)

    def tearDown(self) -> None:
        self.harness.close()

    def test_reuses_fake_backend_and_returns_memory_pcm_metrics(self) -> None:
        phrase = FastPhrase("P00", "테스트입니다.", True, False)
        first = self.harness.client.request(WorkerCommand("synthesize", "r1", "session", "g1", phrase, 1))
        second = self.harness.client.request(WorkerCommand("synthesize", "r2", "session", "g1", phrase, 2))
        self.assertEqual(self.backend.initialize_count, 1)
        self.assertEqual(len(self.backend.requests), 2)
        self.assertFalse(first["stale"])
        self.assertEqual(first["pcm"]["pcm_s16le"], FakeFastBackend.KNOWN_PCM_S16LE)
        self.assertEqual(first["pcm"]["sample_rate"], 24000)
        self.assertEqual(first["pcm"]["sample_count"], 4)
        self.assertEqual(first["metrics"]["playback_ttfa"], "not_run")
        self.assertGreater(first["metrics"]["audio_duration_seconds"], 0)
        self.assertEqual(second["metadata"]["backend"], "fake")

    def test_invalidation_marks_a_completed_inflight_result_stale(self) -> None:
        self.harness.close()
        blocking = BlockingFakeBackend()
        self.harness = WorkerHarness(blocking)
        phrase = FastPhrase("P01", "느린 테스트입니다.", True, False)
        response: dict[str, object] = {}

        def synthesize() -> None:
            response.update(self.harness.client.request(WorkerCommand("synthesize", "r3", "session", "old", phrase, 3)))

        thread = threading.Thread(target=synthesize)
        thread.start()
        self.assertTrue(blocking.entered.wait(2))
        invalidated = self.harness.client.request(WorkerCommand("invalidate", "r4", "session", "new"))
        self.assertTrue(invalidated["invalidated"])
        blocking.release.set()
        thread.join(3)
        self.assertTrue(response["stale"])
        self.assertEqual(response["generation_id"], "old")

    def test_external_process_restarts_cleanly_with_fake_backend(self) -> None:
        process = WorkerProcess(
            ROOT,
            python_executable=Path(sys.executable),
            backend_factory_spec="tests.luna_quality.unit.test_fast_speaker_worker:fake_backend_factory",
        )
        try:
            first_client = process.start(10)
            first = first_client.request(WorkerCommand("health", "r5"))
            first_pid = process.process.pid if process.process is not None else None
            second_client = process.restart(10)
            second = second_client.request(WorkerCommand("health", "r6"))
            second_pid = process.process.pid if process.process is not None else None
            self.assertEqual(first["worker_status"], "ready")
            self.assertEqual(second["worker_status"], "ready")
            self.assertNotEqual(first_pid, second_pid)
        finally:
            process.shutdown()


if __name__ == "__main__":
    unittest.main()
