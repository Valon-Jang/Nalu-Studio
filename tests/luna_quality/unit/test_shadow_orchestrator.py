import json
import math
import tempfile
import unittest
import wave
from pathlib import Path

from scripts.luna_quality.cli import main
from scripts.luna_quality.contracts import ValidationResult, ValidationStatus
from scripts.luna_quality.orchestrator.engine import ShadowOrchestrator
from scripts.luna_quality.orchestrator.report import write_shadow_report
from scripts.luna_quality.ranking.artifact import artifact_payload, save_artifact
from scripts.luna_quality.ranking.features import FEATURE_NAMES
from scripts.luna_quality.ranking.pairwise import PairwiseLogisticRanker


def _result(name, status=ValidationStatus.PASS, hard_gate=True, metrics=None):
    return ValidationResult(name, f"{name}/test", status, hard_gate, metrics=metrics or {})


def _wav(path, zero=False):
    rate, frames = 24000, 7200
    samples = []
    for index in range(frames):
        value = 0.0 if zero or index >= frames - 120 else 0.12 * math.sin(2 * math.pi * 220 * index / rate)
        samples.append(int(value * 32767).to_bytes(2, "little", signed=True))
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        writer.writeframes(b"".join(samples))


def _take(path, take_id, *, ok=True, score_variant=0.0):
    row = {
        "take": take_id,
        "seed": 100 + take_id,
        "ok": ok,
        "why": [] if ok else ["existing_gate_rejected"],
        "text": "테스트 문장입니다.",
        "n_syl": 6.54 + score_variant,
        "metrics": {
            "dur": 1.0,
            "median_hz": 235.0 + score_variant,
            "range_st": 8.0,
            "end_slope": -12.0,
            "tail_delta": -2.5,
            "final_glide": 5.0,
            "final_rebound": 3.0,
        },
    }
    path.write_text(json.dumps(row, ensure_ascii=False), encoding="utf-8")


class ShadowOrchestratorTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.outdir = self.root / "existing"
        block = self.outdir / "B01"
        block.mkdir(parents=True)
        (block / "phrases.json").write_text(json.dumps([{"text": "테스트 문장입니다.", "sentence_final": True}], ensure_ascii=False), encoding="utf-8")
        _take(block / "P00_t1.json", 1, score_variant=0.0)
        _take(block / "P00_t0.json", 0, score_variant=1.0)
        _wav(block / "P00_t0.wav")
        _wav(block / "P00_t1.wav")
        (self.outdir / "B01_report.json").write_text(json.dumps({"id": "B01", "picks": [0]}), encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def evaluate(self, **kwargs):
        return ShadowOrchestrator(**kwargs).evaluate(self.outdir).report

    def phrase(self, report):
        return report["blocks"][0]["phrases"][0]

    def test_default_optional_validators_are_not_run_and_baseline_is_used(self):
        report = self.evaluate()
        phrase = self.phrase(report)
        self.assertEqual(phrase["ranking_mode"], "existing_quality_score")
        self.assertEqual(phrase["ranker"]["reason"], "ranker_not_configured")
        self.assertEqual(phrase["shadow_top_1"], 1)
        self.assertFalse(phrase["agreement"])
        statuses = {row["validator_name"]: row["status"] for row in phrase["takes"][0]["validations"]}
        self.assertEqual(statuses["content_asr"], "not_run")
        self.assertEqual(statuses["speaker_identity"], "not_run")
        self.assertTrue(report["input"]["read_only_verified"])
        self.assertFalse(report["production_selection_changed"])

    def test_all_configured_validators_pass(self):
        report = self.evaluate(
            content_runner=lambda take: _result("content_asr"),
            speaker_runner=lambda take: _result("speaker_identity"),
            mos_runner=lambda take: _result("mos", hard_gate=False, metrics={"mos_score": 4.0}),
        )
        for take in self.phrase(report)["takes"]:
            self.assertTrue(take["hard_gate_pass"])
            self.assertEqual({row["status"] for row in take["validations"]}, {"pass"})

    def test_hard_failure_excludes_only_that_take_without_crash(self):
        _wav(self.outdir / "B01" / "P00_t0.wav", zero=True)
        report = self.evaluate()
        phrase = self.phrase(report)
        failed = next(take for take in phrase["takes"] if take["take_id"] == 0)
        self.assertFalse(failed["hard_gate_pass"])
        self.assertIn(0, [take["take_id"] for take in phrase["takes"]])
        self.assertEqual(phrase["hard_gate_survivor_take_ids"], [1])

    def test_validator_exception_is_unknown_and_does_not_stop_shadow_report(self):
        def broken(_take):
            raise RuntimeError("fixture failure")

        phrase = self.phrase(self.evaluate(content_runner=broken))
        content = next(row for row in phrase["takes"][0]["validations"] if row["validator_name"] == "content_asr")
        self.assertEqual(content["status"], "unknown")
        self.assertIn("validator_exception:RuntimeError", content["reasons"])
        self.assertEqual(phrase["shadow_top_1"], 1)

    def test_ranker_schema_mismatch_falls_back_to_existing_quality(self):
        artifact = self.root / "bad-ranker.json"
        artifact.write_text('{"artifact_schema_version":"wrong"}', encoding="utf-8")
        phrase = self.phrase(self.evaluate(ranker_artifact=artifact))
        self.assertEqual(phrase["ranking_mode"], "existing_quality_score")
        self.assertEqual(phrase["ranker"]["reason"], "artifact_schema_mismatch")

    def test_active_ranker_records_scores_but_does_not_change_production(self):
        artifact = self.root / "ranker.json"
        weights = (1.0,) + (0.0,) * (len(FEATURE_NAMES) - 1)
        ranker = PairwiseLogisticRanker(FEATURE_NAMES, (0.0,) * len(FEATURE_NAMES), (1.0,) * len(FEATURE_NAMES), weights, 0.0, 407)
        save_artifact(artifact, artifact_payload(ranker, dataset_hash="a" * 64, source_hashes=[], data_sufficiency={}, evaluation={}))
        report = self.evaluate(ranker_artifact=artifact)
        phrase = self.phrase(report)
        self.assertEqual(phrase["ranking_mode"], "preference_ranker")
        self.assertIsNotNone(phrase["takes"][0]["rank_score"])
        self.assertFalse(report["production_selection_changed"])

    def test_existing_pin_takes_precedence_and_comparison_is_reported(self):
        (self.outdir / "B01_pins.json").write_text('{"P00": 1}', encoding="utf-8")
        phrase = self.phrase(self.evaluate())
        self.assertEqual(phrase["actual_selected_take"], 1)
        self.assertEqual(phrase["actual_selection"]["source"], "pins")
        self.assertTrue(phrase["agreement"])

    def test_deterministic_take_order_and_input_files_are_unchanged(self):
        before = {path.relative_to(self.outdir): path.read_bytes() for path in self.outdir.rglob("*") if path.is_file()}
        first, second = self.evaluate(), self.evaluate()
        self.assertEqual([take["take_id"] for take in self.phrase(first)["takes"]], [0, 1])
        self.assertEqual([take["take_id"] for take in self.phrase(second)["takes"]], [0, 1])
        after = {path.relative_to(self.outdir): path.read_bytes() for path in self.outdir.rglob("*") if path.is_file()}
        self.assertEqual(before, after)

    def test_report_writer_rejects_writing_into_read_only_outdir(self):
        result = ShadowOrchestrator().evaluate(self.outdir)
        with self.assertRaisesRegex(ValueError, "outside"):
            write_shadow_report(result, self.outdir / "shadow.json", self.outdir)

    def test_cli_writes_only_new_report(self):
        report = self.root / "shadow-report.json"
        self.assertEqual(main(["shadow-evaluate", "--outdir", str(self.outdir), "--report", str(report)]), 0)
        payload = json.loads(report.read_text(encoding="utf-8"))
        self.assertTrue(payload["input"]["read_only_verified"])
        self.assertFalse(payload["production_selection_changed"])

    def test_block_filter_excludes_unrequested_blocks(self):
        other = self.outdir / "B02"
        other.mkdir()
        (other / "phrases.json").write_text(
            json.dumps([{"text": "다른 문장입니다.", "sentence_final": True}], ensure_ascii=False), encoding="utf-8"
        )
        _take(other / "P00_t0.json", 0)
        _wav(other / "P00_t0.wav")
        report = ShadowOrchestrator().evaluate(self.outdir, block_ids={"B01"}).report
        self.assertEqual([block["block_id"] for block in report["blocks"]], ["B01"])
        self.assertEqual(report["input"]["block_filter"], ["B01"])


if __name__ == "__main__":
    unittest.main()
