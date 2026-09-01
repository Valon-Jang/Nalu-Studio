"""Opt-in real Korean FAST synthesis using the immutable production venv."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import wave


ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.luna_quality.voice_runtime.runtime import LunaVoiceRuntime


@unittest.skipUnless(os.getenv("RUN_LUNA_S12_REAL_FAST") == "1", "set RUN_LUNA_S12_REAL_FAST=1")
class S12ResidentKoreanFastIntegrationTest(unittest.TestCase):
    def test_two_korean_requests_reuse_model_and_candidate_b(self) -> None:
        runtime = LunaVoiceRuntime(ROOT)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = runtime.handle({
                "request_id": "ko-fast-one",
                "text": "안녕하세요. Nalu입니다.",
                "output_wav": str(root / "one.wav"),
                "output_json": str(root / "one.json"),
                "seed": 20260823,
            })
            second = runtime.handle({
                "request_id": "ko-fast-two",
                "text": "기술 이야기를 시작합니다.",
                "output_wav": str(root / "two.wav"),
                "output_json": str(root / "two.json"),
                "seed": 20260824,
            })
            for name in ("one", "two"):
                wav_path = root / f"{name}.wav"
                self.assertGreater(wav_path.stat().st_size, 44)
                with wave.open(str(wav_path), "rb") as handle:
                    self.assertEqual(handle.getframerate(), 24000)
                    self.assertGreater(handle.getnframes(), 0)
                payload = json.loads((root / f"{name}.json").read_text(encoding="utf-8"))
                self.assertEqual(payload["status"], "ok")
                self.assertEqual(payload["take_count"], 1)
            self.assertEqual(first["model_load_count"], 1)
            self.assertEqual(second["model_load_count"], 1)
            self.assertEqual(second["condition_prepare_count"], 1)


if __name__ == "__main__":
    unittest.main()
