import json
import tempfile
import unittest
from pathlib import Path

from scripts.luna_quality.ranking.artifact import load_artifact, save_artifact
from scripts.luna_quality.ranking.data import (
    assert_no_group_leakage,
    assess_data_sufficiency,
    build_pairwise_examples,
    grouped_split,
)
from scripts.luna_quality.ranking.features import FEATURE_NAMES
from scripts.luna_quality.ranking.pairwise import fit_pairwise_logistic
from scripts.luna_quality.ranking.train import main, train_ranker
from scripts.luna_quality.prosody_bank import ProsodyBankStore, ingest_directory
from scripts.luna_quality.prosody_bank.queries import ranking_training_rows


def synthetic_rows(projects=2, blocks=5, phrases=5, alternatives=3):
    rows = []
    classes = ("statement", "question", "transition")
    for project in range(projects):
        for block in range(blocks):
            for phrase in range(phrases):
                for take in range(alternatives + 1):
                    quality = 1.5 if take == 0 else -0.4 * take
                    features = {
                        "syllables_per_second": 4.1 + quality * 0.08,
                        "pitch_median_hz": 235.0 + quality,
                        "pitch_range_st": 7.0 + quality * 0.2,
                        "tail_delta_st": -1.8 + quality * 0.1,
                        "relative_tail": -0.25 + quality * 0.02,
                        "final_glide_st_per_s": -0.5 + quality * 0.1,
                        "final_rebound_st": 0.3 - quality * 0.05,
                        "level_deviation_db": 1.4 - quality * 0.2,
                        "phrase_reset_st": 1.0 + quality * 0.1,
                        "speaker_similarity_chatterbox": 0.80 + quality * 0.04,
                        "speaker_similarity_speechbrain": 0.78 + quality * 0.03,
                        "content_score": 0.84 + quality * 0.04,
                        "content_error_rate": 0.12 - quality * 0.02,
                        "mos_score": 3.4 + quality * 0.1,
                    }
                    rows.append(
                        {
                            "project_id": f"PROJECT-{project}",
                            "block_id": f"B{block:02d}",
                            "phrase_id": f"P{phrase:02d}",
                            "take_id": take,
                            "text": f"고유 문장 {project} {block} {phrase}",
                            "sentence_class": classes[phrase % len(classes)],
                            "decision": "selected" if take == 0 else "not_selected",
                            "hard_gate_pass": True,
                            "features": features,
                            # Intentionally weak/inverted baseline for comparison.
                            "baseline_score": -quality,
                        }
                    )
    return rows


class PreferenceRankerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = synthetic_rows()
        cls.result = train_ranker(cls.rows)

    def test_data_sufficiency_inventory(self):
        inventory = assess_data_sufficiency(self.rows)
        self.assertEqual(inventory.status, "sufficient")
        self.assertEqual(inventory.pinned_phrase_count, 50)
        self.assertEqual(inventory.pair_count, 150)
        self.assertEqual(inventory.block_count, 10)
        self.assertEqual(inventory.project_count, 2)
        self.assertEqual(inventory.feature_missing_rate, 0.0)
        self.assertEqual(inventory.project_concentration, 0.5)

    def test_group_split_has_no_block_or_sentence_leakage(self):
        pairs = build_pairwise_examples(self.rows)
        train, test = grouped_split(pairs, seed=99)
        assert_no_group_leakage(train, test)
        self.assertFalse({(p.project_id, p.block_id) for p in train} & {(p.project_id, p.block_id) for p in test})
        self.assertFalse({p.sentence_key for p in train} & {p.sentence_key for p in test})

    def test_duplicate_sentence_connects_blocks(self):
        rows = synthetic_rows(projects=1, blocks=2, phrases=1, alternatives=1)
        for row in rows:
            row["text"] = "같은 문장"
        pairs = build_pairwise_examples(rows)
        self.assertEqual(len({pair.split_group for pair in pairs}), 1)
        with self.assertRaisesRegex(ValueError, "independent"):
            grouped_split(pairs)

    def test_deterministic_training(self):
        pairs = build_pairwise_examples(self.rows)[:12]
        first = fit_pairwise_logistic(pairs, seed=7, iterations=120)
        second = fit_pairwise_logistic(pairs, seed=7, iterations=120)
        self.assertEqual(first.to_dict(), second.to_dict())

    def test_grouped_and_project_evaluation(self):
        self.assertEqual(self.result.status, "trained")
        grouped = self.result.evaluation["grouped_holdout"]
        self.assertGreaterEqual(grouped["model"]["pairwise_accuracy"], 0.9)
        self.assertGreater(grouped["baseline_pairwise_accuracy_delta"], 0.5)
        self.assertIn("project_holdout", self.result.evaluation)
        self.assertIn("ablation_pairwise_accuracy_delta", grouped)
        self.assertIn("expected_calibration_error", grouped["model"])

    def test_artifact_round_trip_and_inference_safety(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ranker.json"
            save_artifact(path, self.result.artifact)
            loaded = load_artifact(path)
            self.assertEqual(loaded.status, "active")
            inference = loaded.ranker.rank_candidates(
                [
                    {"take_id": 0, "hard_gate_pass": True, "features": self.rows[0]["features"]},
                    {"take_id": 1, "hard_gate_pass": False, "features": self.rows[1]["features"]},
                    {"take_id": 2, "hard_gate_pass": True, "features": self.rows[0]["features"]},
                ]
            )
            self.assertFalse(inference["production_selection_changed"])
            self.assertFalse(inference["candidate_reduction_allowed"])
            excluded = next(row for row in inference["results"] if row["take_id"] == 1)
            self.assertEqual(excluded["reason"], "hard_gate_not_pass")

    def test_prosody_bank_export_fails_closed_without_gate_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "B01").mkdir()
            for take in (0, 1):
                (root / "B01" / f"P00_t{take}.json").write_text(
                    json.dumps({"text": "테스트", "n_syl": 4, "metrics": {"dur": 1.0}}), encoding="utf-8"
                )
            (root / "B01_pins.json").write_text('{"P00": 0}', encoding="utf-8")
            store = ProsodyBankStore(root / "bank.sqlite")
            try:
                store.migrate()
                ingest_directory(store, root, "PROJECT")
                exported = ranking_training_rows(store.connection, "PROJECT")
                self.assertEqual(len(exported), 2)
                self.assertTrue(all(row["hard_gate_pass"] is False for row in exported))
                self.assertTrue(all(row["hard_gate_status"] == "unknown" for row in exported))
                selected = next(row for row in exported if row["decision"] == "selected")
                self.assertEqual(len(selected["selection_source_sha256"]), 64)
                self.assertEqual(build_pairwise_examples(exported), [])
            finally:
                store.close()

    def test_feature_schema_mismatch_disables_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ranker.json"
            payload = dict(self.result.artifact)
            payload["feature_schema_hash"] = "0" * 64
            save_artifact(path, payload)
            loaded = load_artifact(path)
            self.assertEqual((loaded.status, loaded.reason), ("disabled", "feature_schema_mismatch"))

    def test_insufficient_data_does_not_fit_model(self):
        rows = synthetic_rows(projects=1, blocks=1, phrases=2, alternatives=1)
        result = train_ranker(rows)
        self.assertEqual(result.status, "insufficient_data")
        self.assertIsNone(result.ranker)
        self.assertIsNone(result.artifact["model"])
        self.assertEqual(result.artifact["status"], "insufficient_data")

    def test_unknowns_and_hard_gate_failures_are_not_negatives(self):
        rows = synthetic_rows(projects=1, blocks=1, phrases=1, alternatives=2)
        rows[1]["decision"] = "unknown"
        rows[2]["hard_gate_pass"] = False
        self.assertEqual(build_pairwise_examples(rows), [])

    def test_all_features_are_text_free_and_mos_is_explicit(self):
        self.assertNotIn("text_embedding", FEATURE_NAMES)
        self.assertEqual(FEATURE_NAMES[-1], "mos_score")

    def test_cli_writes_insufficient_artifact_and_evaluation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, artifact, evaluation = root / "rows.json", root / "model.json", root / "evaluation.json"
            source.write_text(json.dumps(synthetic_rows(1, 1, 1, 1), ensure_ascii=False), encoding="utf-8")
            status = main(["--input", str(source), "--artifact", str(artifact), "--evaluation", str(evaluation)])
            self.assertEqual(status, 0)
            self.assertEqual(json.loads(artifact.read_text(encoding="utf-8"))["status"], "insufficient_data")
            self.assertEqual(json.loads(evaluation.read_text(encoding="utf-8"))["status"], "insufficient_data")


if __name__ == "__main__":
    unittest.main()
