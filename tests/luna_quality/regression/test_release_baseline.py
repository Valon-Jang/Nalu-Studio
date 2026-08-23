import inspect
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import luna_narration_pipeline_v1 as pipeline
from scripts.luna_quality.hashing import sha256_file
from scripts.luna_quality.production_integration import (
    CANDIDATE_B_SHA256,
    FEATURE_ENV_DEFAULTS,
)


ROOT = Path(__file__).resolve().parents[3]
MANIFEST = json.loads(
    (ROOT / "docs" / "luna_quality" / "baseline" / "BASELINE_MANIFEST.json").read_text(encoding="utf-8")
)


class ReleaseBaselineRegressionTest(unittest.TestCase):
    def test_candidate_b_skill_target_and_frozen_outputs_are_byte_identical(self):
        expected = {
            MANIFEST["candidate_b_path"]: MANIFEST["candidate_b_actual_sha256"],
            MANIFEST["skill_path"]: MANIFEST["skill_sha256"],
            MANIFEST["prosody_target_path"]: MANIFEST["prosody_target_sha256"],
            **MANIFEST["frozen_final_wav_sha256"],
            **MANIFEST["frozen_timing_sha256"],
        }
        for relative, digest in expected.items():
            with self.subTest(path=relative):
                self.assertEqual(sha256_file(ROOT / relative), digest)

    def test_pinned_chatterbox_checkpoint_bytes_are_identical(self):
        snapshot = ROOT / MANIFEST["model_checkpoint_root"]
        for record in MANIFEST["model_checkpoint_files"]:
            path = snapshot / record["filename"]
            with self.subTest(path=record["filename"]):
                self.assertEqual(path.stat().st_size, record["size_bytes"])
                self.assertEqual(sha256_file(path), record["sha256"])

    def test_production_engine_parameters_and_output_contract_remain_fixed(self):
        fixed = MANIFEST["fixed_parameters"]
        generation = fixed["generation"]
        self.assertEqual(pipeline.RUNTIME, ROOT / "engine" / "chatterbox-v3")
        self.assertEqual(pipeline.REF, ROOT / MANIFEST["candidate_b_path"])
        self.assertEqual((pipeline.EXAG, pipeline.CFG, pipeline.TEMP), (
            generation["exaggeration"], generation["cfg_weight"], generation["temperature"]
        ))
        self.assertEqual(pipeline.ESCALATION_TEMPS, tuple(fixed["escalation"]["temperatures"]))
        self.assertEqual(pipeline.RESET_GATE, tuple(fixed["reset_st"]))
        self.assertEqual(pipeline.BLOCK_MEDIAN_BAND, tuple(fixed["block_median_slope"]))
        self.assertEqual(pipeline.PAUSE_CONT, tuple(fixed["pause_seconds"]["continuation"]))
        self.assertEqual(pipeline.PAUSE_FINAL, tuple(fixed["pause_seconds"]["final"]))
        self.assertEqual(pipeline.PAUSE_FORCED, tuple(fixed["pause_seconds"]["forced"]))
        source = inspect.getsource(pipeline.synthesize_block)
        for contract in (
            'language_id="ko"',
            "repetition_penalty=1.2",
            "min_p=0.05",
            "top_p=1.0",
            'f"{bid}_luna.wav"',
            'f"{bid}_report.json"',
        ):
            self.assertIn(contract, source)

    def test_every_release_feature_is_default_off(self):
        self.assertTrue(FEATURE_ENV_DEFAULTS)
        self.assertEqual(set(FEATURE_ENV_DEFAULTS.values()), {"off"})
        self.assertEqual(FEATURE_ENV_DEFAULTS, pipeline.QUALITY_FEATURE_DEFAULTS)
        self.assertEqual(CANDIDATE_B_SHA256, MANIFEST["candidate_b_actual_sha256"])
        self.assertFalse(pipeline.quality_integration_requested({}))

    def test_no_production_select_artifact_was_approved(self):
        insufficiency = json.loads(
            (ROOT / "docs" / "luna_quality" / "ranking" / "S07_INSUFFICIENT_DATA.json").read_text(encoding="utf-8")
        )
        self.assertEqual(insufficiency["status"], "insufficient_data")
        self.assertFalse(any((ROOT / "docs" / "luna_quality").rglob("*SELECT_APPROVAL*.json")))

    def test_completed_block_resume_keeps_block_output_and_default_off_contract(self):
        class FakeModel:
            sr = 24000

        class FakeChatterboxMultilingualTTS:
            @classmethod
            def from_pretrained(cls, *, device, t3_model):
                if (device, t3_model) != ("cpu", "v3"):
                    raise AssertionError("production loader contract changed")
                return FakeModel()

        package = types.ModuleType("chatterbox")
        package.__path__ = []
        mtl_tts = types.ModuleType("chatterbox.mtl_tts")
        mtl_tts.ChatterboxMultilingualTTS = FakeChatterboxMultilingualTTS
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            jobs = root / "jobs.json"
            outdir = root / "out"
            outdir.mkdir()
            jobs.write_text(
                json.dumps({"blocks": [{"id": "B01", "text": "재시작 검사입니다.", "seed": 1}]}, ensure_ascii=False),
                encoding="utf-8",
            )
            block_report = outdir / "B01_report.json"
            original = json.dumps({"id": "B01", "picks": [3], "sentinel": "unchanged"}, ensure_ascii=False)
            block_report.write_text(original, encoding="utf-8")
            with (
                patch.dict(sys.modules, {"chatterbox": package, "chatterbox.mtl_tts": mtl_tts}),
                patch.object(sys, "argv", ["luna_narration_pipeline_v1.py", str(jobs), str(outdir)]),
                patch.dict(os.environ, {}, clear=True),
            ):
                pipeline.main()
            self.assertEqual(block_report.read_text(encoding="utf-8"), original)
            self.assertFalse((outdir / "B01_luna.wav").exists())
            self.assertEqual(
                json.loads((outdir / "pipeline_report.json").read_text(encoding="utf-8")),
                [{"id": "B01", "picks": [3], "sentinel": "unchanged"}],
            )
            self.assertFalse((root / "out.luna_quality_reports").exists())


if __name__ == "__main__":
    unittest.main()
