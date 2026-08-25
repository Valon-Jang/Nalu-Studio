from __future__ import annotations

import os
from pathlib import Path
import unittest

from scripts.luna_quality.fast_speaker.contracts import FastPhrase
from scripts.luna_quality.fast_speaker.ipc import WorkerCommand
from scripts.luna_quality.fast_speaker.worker import WorkerProcess


ROOT = Path(__file__).resolve().parents[3]


@unittest.skipUnless(
    os.getenv("RUN_LUNA_FAST_SPEAKER_WORKER_REAL") == "1",
    "set RUN_LUNA_FAST_SPEAKER_WORKER_REAL=1",
)
class FastSpeakerRealWorkerIntegrationTest(unittest.TestCase):
    def test_real_worker_returns_in_memory_pcm_without_wav_and_shuts_down(self) -> None:
        process = WorkerProcess(ROOT)
        try:
            client = process.start(120)
            health = client.request(WorkerCommand("health", "real-health"))
            response = client.request(
                WorkerCommand(
                    "synthesize",
                    "real-synth",
                    "real-session",
                    "generation-1",
                    FastPhrase("P00", "상주 워커 메모리 PCM 검사입니다.", True, False),
                    20260826,
                ),
                timeout_seconds=180,
            )
            self.assertEqual(health["worker_status"], "ready")
            self.assertFalse(response["stale"])
            self.assertEqual(response["pcm"]["encoding"], "pcm_s16le")
            self.assertEqual(response["pcm"]["sample_rate"], 24000)
            self.assertGreater(len(response["pcm"]["pcm_s16le"]), 0)
            self.assertGreater(response["metrics"]["audio_duration_seconds"], 0)
            self.assertIsNotNone(response["metrics"]["rtf"])
            self.assertEqual(response["metrics"]["playback_ttfa"], "not_run")
            self.assertNotIn("output_wav", response)
        finally:
            process.shutdown()
        self.assertIsNone(process.process)


if __name__ == "__main__":
    unittest.main()
