import json
import math
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from scripts.luna_narration_pipeline_v1 import (
    apply_quality_selection,
    quality_integration_requested,
    write_quality_import_fallback,
)
from scripts.luna_quality.hashing import sha256_file
from scripts.luna_quality.production_integration import (
    FeatureFlags,
    ProductionQualitySession,
    SELECT_APPROVAL_SCHEMA_VERSION,
    selection_config_hash,
    write_startup_fallback_report,
)
from scripts.luna_quality.ranking.artifact import artifact_payload, save_artifact
from scripts.luna_quality.ranking.features import FEATURE_NAMES
from scripts.luna_quality.ranking.pairwise import PairwiseLogisticRanker


def _wav(path, *, zero=False):
    rate = 24000
    samples = []
    for index in range(7200):
        value = 0.0 if zero or index >= 7080 else 0.12 * math.sin(2 * math.pi * 220 * index / rate)
        samples.append(int(value * 32767).to_bytes(2, "little", signed=True))
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        writer.writeframes(b"".join(samples))


def _row(take_id, median_hz=235.0, *, ok=True):
    return {
        "take": take_id,
        "seed": 100 + take_id,
        "ok": ok,
        "why": [] if ok else ["existing_gate_rejected"],
        "text": "한글 테스트 문장입니다.",
        "n_syl": 6.54,
        "metrics": {
            "dur": 1.0,
            "median_hz": median_hz,
            "range_st": 8.0,
            "end_slope": -12.0,
            "first_hz": 235.0,
            "last_hz": 235.0,
            "tail_delta": -2.5,
            "final_glide": 5.0,
            "final_rebound": 3.0,
        },
    }


class _FakeConditionals:
    def save(self, path):
        Path(path).write_bytes(b"conditionals")

    @classmethod
    def load(cls, path, map_location="cpu"):
        if Path(path).read_bytes() != b"conditionals":
            raise ValueError("bad fixture")
        return cls()

    def to(self, _device):
        return self


class _FakeModel:
    def __init__(self):
        self.conds = _FakeConditionals()
        self.prepare_calls = 0
        self.ve = None

    def prepare_conditionals(self, _path, exaggeration=0.5):
        self.prepare_calls += 1
        self.conds = _FakeConditionals()


class S10ProductionIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.outdir = self.root / "production-출력"
        self.block = self.outdir / "B한글01"
        self.block.mkdir(parents=True)
        (self.block / "phrases.json").write_text(
            json.dumps([{"text": "한글 테스트 문장입니다.", "sentence_final": True}], ensure_ascii=False),
            encoding="utf-8",
        )
        for take_id, pitch in ((0, 235.0), (1, 236.0)):
            (self.block / f"P00_t{take_id}.json").write_text(
                json.dumps(_row(take_id, pitch), ensure_ascii=False), encoding="utf-8"
            )
            _wav(self.block / f"P00_t{take_id}.wav")
        (self.outdir / "B한글01_report.json").write_text(
            json.dumps({"id": "B한글01", "picks": [0]}, ensure_ascii=False), encoding="utf-8"
        )

    def tearDown(self):
        self.temp.cleanup()

    def _flags(self, **overrides):
        values = {"report_dir": str(self.root / "quality-reports")}
        values.update(overrides)
        return FeatureFlags(**values)

    def _quality_report(self):
        reports = list((self.root / "quality-reports").glob("*.quality.json"))
        self.assertEqual(len(reports), 1)
        return json.loads(reports[0].read_text(encoding="utf-8"))

    def _ranker(self):
        path = self.root / "ranker.json"
        weights = (0.0, 1.0) + (0.0,) * (len(FEATURE_NAMES) - 2)
        ranker = PairwiseLogisticRanker(
            FEATURE_NAMES,
            (0.0,) * len(FEATURE_NAMES),
            (1.0,) * len(FEATURE_NAMES),
            weights,
            0.0,
            410,
        )
        save_artifact(
            path,
            artifact_payload(
                ranker,
                dataset_hash="a" * 64,
                source_hashes=[],
                data_sufficiency={},
                evaluation={},
            ),
        )
        return path

    def test_default_off_does_not_request_or_write_integration_output(self):
        self.assertFalse(quality_integration_requested({}))
        self.assertFalse(quality_integration_requested({"LUNA_QUALITY_MODE": "OFF"}))
        self.assertTrue(quality_integration_requested({"LUNA_QUALITY_MODE": "shadow"}))
        self.assertTrue(quality_integration_requested({"LUNA_QUALITY_REPORT_DIR": "reports"}))

    def test_invalid_flag_is_rejected_before_any_selection(self):
        with self.assertRaisesRegex(ValueError, "LUNA_QUALITY_MODE"):
            FeatureFlags.from_environment({"LUNA_QUALITY_MODE": "maybe"})

    def test_shadow_is_read_only_and_atomic_across_restart(self):
        before = {path.relative_to(self.outdir): path.read_bytes() for path in self.outdir.rglob("*") if path.is_file()}
        flags = self._flags(quality_mode="shadow")
        first = ProductionQualitySession(self.root, self.outdir, _FakeModel(), flags)
        self.assertEqual(first.evaluate_block("B한글01"), {})
        second = ProductionQualitySession(self.root, self.outdir, _FakeModel(), flags)
        self.assertEqual(second.evaluate_block("B한글01"), {})
        after = {path.relative_to(self.outdir): path.read_bytes() for path in self.outdir.rglob("*") if path.is_file()}
        self.assertEqual(before, after)
        report = self._quality_report()
        self.assertFalse(report["production_selection_changed"])
        self.assertFalse(any((self.root / "quality-reports").glob("*.tmp-*")))

    def test_select_without_artifacts_or_user_approval_falls_back(self):
        flags = self._flags(quality_mode="select", preference_ranker="select")
        session = ProductionQualitySession(self.root, self.outdir, _FakeModel(), flags)
        self.assertEqual(session.evaluate_block("B한글01"), {})
        payload = self._quality_report()
        self.assertIn("ranker_artifact_missing", payload["selection"]["reasons"])
        self.assertTrue(payload["fallback_to_existing_selector"])

    def test_fully_hashed_user_approval_can_only_propose_hard_survivor(self):
        ranker = self._ranker()
        calibration = self.root / "calibration.json"
        calibration.write_text(
            json.dumps({"status": "calibrated_candidate", "recommended_threshold_candidate": 0.8}), encoding="utf-8"
        )
        approval = self.root / "approval.json"
        flags = self._flags(
            quality_mode="select",
            preference_ranker="select",
            ranker_artifact=str(ranker),
            speaker_calibration_artifact=str(calibration),
            select_approval_manifest=str(approval),
        )
        ranker_hash, calibration_hash = sha256_file(ranker), sha256_file(calibration)
        approval.write_text(
            json.dumps(
                {
                    "schema_version": SELECT_APPROVAL_SCHEMA_VERSION,
                    "approved_by": "USER",
                    "approved_for_production_select": True,
                    "ranker_artifact_sha256": ranker_hash,
                    "speaker_calibration_sha256": calibration_hash,
                    "feature_config_sha256": selection_config_hash(flags, ranker_hash, calibration_hash),
                    "approved_validators": ["audio_sanity", "existing_prosody_gate"],
                    "minimum_top_confidence": 0.0,
                    "minimum_feature_coverage": 0.5,
                }
            ),
            encoding="utf-8",
        )
        session = ProductionQualitySession(self.root, self.outdir, _FakeModel(), flags)
        self.assertEqual(session.evaluate_block("B한글01"), {0: 1})

        _wav(self.block / "P00_t1.wav", zero=True)
        session = ProductionQualitySession(self.root, self.outdir, _FakeModel(), flags)
        self.assertEqual(session.evaluate_block("B한글01"), {})

    def test_mos_and_hybrid_cannot_enter_select(self):
        flags = self._flags(
            quality_mode="select",
            preference_ranker="select",
            mos_validator="on",
            hybrid_synthesis="experiment",
        )
        session = ProductionQualitySession(self.root, self.outdir, _FakeModel(), flags)
        self.assertEqual(session.evaluate_block("B한글01"), {})
        payload = self._quality_report()
        self.assertIn("mos_select_not_supported", payload["selection"]["reasons"])
        self.assertIn("hybrid_not_approved_for_production_select", payload["selection"]["reasons"])

    def test_production_guard_preserves_pins_and_rejects_bad_take(self):
        takes = [[_row(0), _row(1, 236.0)], [_row(0), _row(1, 236.0)]]
        picks, guard = apply_quality_selection([0, 0], {0: 1, 1: 1}, takes, {"P00": 0})
        self.assertEqual(picks, [0, 1])
        self.assertEqual(guard["status"], "applied")
        takes[1][1]["ok"] = False
        picks, guard = apply_quality_selection([0, 0], {1: 1}, takes, {})
        self.assertEqual(picks, [0, 0])
        self.assertEqual(guard["status"], "fallback")

    def test_production_guard_rejects_reset_and_block_median_regression(self):
        takes = [[_row(0), _row(1)], [_row(0), _row(1)]]
        takes[1][1]["metrics"]["first_hz"] = 600.0
        picks, guard = apply_quality_selection([0, 0], {1: 1}, takes, {})
        self.assertEqual(picks, [0, 0])
        self.assertTrue(any(reason.startswith("reset_outside_gate") for reason in guard["reasons"]))
        takes[1][1]["metrics"]["first_hz"] = 235.0
        takes[0][1]["metrics"]["end_slope"] = 2.0
        takes[1][1]["metrics"]["end_slope"] = 2.0
        picks, guard = apply_quality_selection([0, 0], {0: 1, 1: 1}, takes, {})
        self.assertEqual(picks, [0, 0])
        self.assertTrue(any(reason.startswith("block_median_outside_gate") for reason in guard["reasons"]))

    def test_cache_creates_then_hits_exact_manifest_and_bad_manifest_falls_back(self):
        repo = self.root / "cache-repo"
        reference = repo / "assets" / "voice_ref" / "B_voiced_spectral_micro_smooth.wav"
        reference.parent.mkdir(parents=True)
        reference.write_bytes(b"candidate-b-fixture")
        source = repo / "engine" / "chatterbox-v3" / "chatterbox" / "src" / "chatterbox" / "mtl_tts.py"
        source.parent.mkdir(parents=True)
        source.write_text("# fixture", encoding="utf-8")
        snapshot = repo / "engine" / "chatterbox-v3" / "hf-cache" / "hub" / "models--ResembleAI--chatterbox" / "snapshots" / "only"
        snapshot.mkdir(parents=True)
        for name in ("t3_mtl23ls_v3.safetensors", "s3gen.pt", "ve.pt", "grapheme_mtl_merged_expanded_v1.json"):
            (snapshot / name).write_bytes(name.encode("ascii"))
        cache_dir = self.root / "conditionals"
        flags = FeatureFlags(
            conditionals_cache="on",
            report_dir=str(self.root / "cache-reports"),
            conditionals_cache_dir=str(cache_dir),
        )
        with patch("scripts.luna_quality.production_integration.CANDIDATE_B_SHA256", sha256_file(reference)):
            first_model = _FakeModel()
            first = ProductionQualitySession(repo, self.outdir, first_model, flags)
            self.assertTrue(first.conditionals_cache_active)
            self.assertEqual(first.conditionals_status["status"], "created")
            self.assertEqual(first_model.prepare_calls, 1)
            second_model = _FakeModel()
            second = ProductionQualitySession(repo, self.outdir, second_model, flags)
            self.assertTrue(second.conditionals_cache_active)
            self.assertEqual(second.conditionals_status["status"], "hit")
            (cache_dir / "candidate_b.conditionals.manifest.json").write_text("not-json", encoding="utf-8")
            bad_model = _FakeModel()
            bad = ProductionQualitySession(repo, self.outdir, bad_model, flags)
            self.assertFalse(bad.conditionals_cache_active)
            self.assertEqual(bad.conditionals_status["reason"], "manifest_invalid")
            self.assertEqual(bad_model.prepare_calls, 0)

    def test_startup_failure_report_never_enters_production_outdir(self):
        path = write_startup_fallback_report(
            self.root,
            self.outdir,
            RuntimeError("fixture"),
            {"LUNA_QUALITY_REPORT_DIR": str(self.outdir / "unsafe")},
        )
        self.assertIsNotNone(path)
        self.assertFalse(path.is_relative_to(self.outdir))
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["status"], "fallback")

        import_path = write_quality_import_fallback(
            self.outdir,
            ImportError("fixture"),
            {"LUNA_QUALITY_REPORT_DIR": str(self.outdir / "also-unsafe")},
        )
        self.assertIsNotNone(import_path)
        self.assertFalse(import_path.is_relative_to(self.outdir))
        self.assertIn("ImportError", json.loads(import_path.read_text(encoding="utf-8"))["reason"])


if __name__ == "__main__":
    unittest.main()
