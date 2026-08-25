from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
import wave
from array import array

from scripts import luna_narration_pipeline_v1 as pipeline
from scripts.luna_quality.fast_speaker.contracts import FastPhrase
from scripts.luna_quality.fast_speaker.fast_adapter import LunaFastBackend
from scripts.luna_quality.voice_runtime.runtime import LunaVoiceRuntime, SYNTHESIS_PARAMETERS


ROOT = Path(__file__).resolve().parents[3]
FIXTURE = json.loads((ROOT / "tests" / "luna_quality" / "fixtures" / "fast_speaker_benchmark.json").read_text(encoding="utf-8"))


class FastSpeakerBaselineRegressionTest(unittest.TestCase):
    def test_fast_config_identity_is_frozen(self) -> None:
        expected = dict(FIXTURE["fast_config"])
        self.assertEqual(SYNTHESIS_PARAMETERS, {key: expected.pop(key) for key in SYNTHESIS_PARAMETERS})
        self.assertEqual(expected.pop("sample_rate"), 24000)
        self.assertEqual(expected.pop("peak_guard"), 0.89)
        self.assertIsNone(expected.pop("audio_prompt_path"))
        self.assertFalse(expected)

    def test_luna_phrase_baseline_matches_fixture(self) -> None:
        class SplitOnlyRuntime:
            pass

        backend = LunaFastBackend(SplitOnlyRuntime())
        for case in FIXTURE["cases"]:
            with self.subTest(case=case["id"]):
                self.assertEqual(pipeline.respell(case["input"]), case["spoken_text"])
                actual = backend.split_fast_text(case["input"])
                self.assertEqual(
                    [
                        {"id": item.phrase_id, "text": item.text, "sentence_final": item.sentence_final, "forced": item.forced}
                        for item in actual
                    ],
                    case["phrases"],
                )

    def test_adapter_keeps_existing_fast_entrypoints_unchanged(self) -> None:
        source = (ROOT / "scripts" / "luna_quality" / "voice_runtime" / "runtime.py").read_text(encoding="utf-8")
        self.assertIn("def _run_fast", source)
        self.assertIn("def _run_production", source)
        self.assertIn("audio_prompt_path=None", source)
        adapter_source = (ROOT / "scripts" / "luna_quality" / "fast_speaker" / "fast_adapter.py").read_text(encoding="utf-8")
        self.assertIn("def _synthesize_current_fast", adapter_source)

    @unittest.skipUnless(
        os.getenv("RUN_LUNA_FAST_SPEAKER_REAL") == "1",
        "set RUN_LUNA_FAST_SPEAKER_REAL=1",
    )
    def test_real_fast_pcm_is_repeatable_and_within_one_lsb_of_current_wav_writer(self) -> None:
        runtime = LunaVoiceRuntime(ROOT)
        backend = LunaFastBackend(runtime)
        phrase = FastPhrase("P00", "상주 워커 회귀 검사입니다.", True, False)
        first = backend.synthesize_fast_phrase(phrase, 20260825)
        second = backend.synthesize_fast_phrase(phrase, 20260825)
        self.assertEqual(first.pcm_s16le, second.pcm_s16le)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "current_fast.wav"
            runtime._default_audio_writer(output, first.waveform, first.sample_rate)
            with wave.open(str(output), "rb") as handle:
                self.assertEqual(handle.getframerate(), first.sample_rate)
                self.assertEqual(handle.getnchannels(), 1)
                self.assertEqual(handle.getsampwidth(), 2)
                encoded_pcm = handle.readframes(handle.getnframes())
            expected_samples = array("h")
            expected_samples.frombytes(first.pcm_s16le)
            encoded_samples = array("h")
            encoded_samples.frombytes(encoded_pcm)
            self.assertEqual(len(encoded_samples), len(expected_samples))
            self.assertLessEqual(
                max(abs(left - right) for left, right in zip(encoded_samples, expected_samples)),
                1,
            )


if __name__ == "__main__":
    unittest.main()
