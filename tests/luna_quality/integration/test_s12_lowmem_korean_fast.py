"""Opt-in real Korean FAST synthesis through the 4 GiB low-memory backend."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
import wave

ROOT = Path(__file__).resolve().parents[3]

from scripts.luna_quality.voice_runtime.low_memory import run_low_memory_fast


@unittest.skipUnless(os.getenv("RUN_LUNA_S12_LOWMEM_FAST") == "1", "set RUN_LUNA_S12_LOWMEM_FAST=1")
class S12LowMemoryKoreanFastIntegrationTest(unittest.TestCase):
    def test_real_lowmem_fast_keeps_pcm_contract_without_new_oom_kill(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "lowmem.wav"
            result = run_low_memory_fast(
                ROOT,
                {
                    "request_id": "ko-lowmem",
                    "text": "오늘의 이야기는 냉장고가 말한다 입니다",
                    "output_wav": str(output),
                    "seed": 20260823,
                },
            )
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["runtime_backend"], "lowmem")
            self.assertEqual(result["sample_rate"], 24000)
            if result["oom_kill_before"] is not None and result["oom_kill_after"] is not None:
                self.assertEqual(result["oom_kill_before"], result["oom_kill_after"])
            with wave.open(str(output), "rb") as handle:
                self.assertEqual(handle.getnchannels(), 1)
                self.assertEqual(handle.getframerate(), 24000)
                self.assertEqual(handle.getsampwidth(), 2)
                self.assertGreater(handle.getnframes(), 0)


if __name__ == "__main__":
    unittest.main()
