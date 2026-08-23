import json
import math
import shutil
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from scripts.luna_quality.cli import main
from scripts.luna_quality.experiments.hybrid_synthesis.evaluator import evaluate_results, write_analysis_bundle
from scripts.luna_quality.experiments.hybrid_synthesis.planner import (
    ASSEMBLY_POLICY_SOURCE,
    INPUT_SCHEMA_VERSION,
    MODEL_MAX_TEXT_TOKENS,
    MODES,
    REFERENCE_RELATIVE_PATH,
    RUNTIME_LIMIT_SOURCES,
    RUNTIME_MAX_AUDIO_SECONDS,
    plan_experiment,
    write_plan_bundle,
)
from scripts.luna_quality.experiments.hybrid_synthesis.runner import (
    RESULT_SCHEMA_VERSION,
    dry_run_plan,
    execute_generation,
)

SOURCE_REPO = Path(__file__).resolve().parents[3]


def _input(text="첫 문장입니다. 두 번째 문장입니다.", phrases=None, *, experiment_id="s09-test"):
    phrases = phrases or ["첫 문장입니다.", "두 번째 문장입니다."]
    return {
        "schema_version": INPUT_SCHEMA_VERSION,
        "experiment_id": experiment_id,
        "frozen_project": False,
        "scripts": [
            {
                "script_id": "script-01",
                "text": text,
                "seed": 407,
                "existing_phrases": [{"text": phrase} for phrase in phrases],
            }
        ],
    }


def _validation(name, status="pass", *, hard_gate=True, score=None, metrics=None):
    return {
        "validator_name": name,
        "validator_version": f"{name}/fixture/1",
        "status": status,
        "hard_gate": hard_gate,
        "score": score,
        "metrics": metrics or {},
        "reasons": [],
    }


def _result(mode, index, *, signal=None):
    return {
        "candidate_id": f"{mode}.candidate-{index}",
        "script_id": "script-01",
        "segment_id": f"{mode}.segment-{index}",
        "mode": mode,
        "status": "pass",
        "failure_reasons": [],
        "audio_relative_path": f"audio/{mode}/candidate-{index}.wav",
        "duration_seconds": 2.0 + index,
        "generation_seconds": 4.0 + index,
        "signals": {
            "hallucination": False,
            "repetition": signal == "repetition",
            "speaker_drift": False,
            "abnormal_silence": False,
        },
        "validations": [
            _validation("content_accuracy", score=0.98 - index * 0.01),
            _validation("audio_sanity"),
            _validation("speaker_similarity", score=0.82 - index * 0.01),
            _validation("existing_prosody_gates", score=0.75 - index * 0.01),
            _validation("phrase_transition", hard_gate=False, score=0.8 - index * 0.01),
        ],
    }


def _results_fixture():
    rows = []
    for mode in MODES:
        rows.append(_result(mode, 0))
        rows.append(_result(mode, 1, signal="repetition" if mode == "hybrid" else None))
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "experiment_id": "s09-fixture",
        "production_selection_changed": False,
        "results": rows,
    }


class HybridSynthesisTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name)
        reference = self.repo / REFERENCE_RELATIVE_PATH
        reference.parent.mkdir(parents=True)
        shutil.copyfile(SOURCE_REPO / REFERENCE_RELATIVE_PATH, reference)
        for relative in RUNTIME_LIMIT_SOURCES:
            target = self.repo / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(SOURCE_REPO / relative, target)
        assembly_source = self.repo / ASSEMBLY_POLICY_SOURCE
        assembly_source.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(SOURCE_REPO / ASSEMBLY_POLICY_SOURCE, assembly_source)

    def tearDown(self):
        self.temp.cleanup()

    def plan(self, payload=None, budget=6, name="run"):
        root = self.repo / "experiments" / "luna_quality" / name
        plan_path = write_plan_bundle(payload or _input(), root, candidate_budget=budget, repo_root=self.repo)
        return plan_path, root

    def test_planner_uses_same_budget_parameters_reference_and_seed_rule(self):
        plan = plan_experiment(_input(), output_root="experiments/luna_quality/test", candidate_budget=6, repo_root=self.repo)
        self.assertEqual(plan["fairness"]["same_candidate_budget_per_script_and_mode"], 6)
        self.assertTrue(plan["runtime_provenance"]["limits_verified_from_pinned_runtime"])
        self.assertEqual(plan["safety_limits"]["model_max_text_tokens"], MODEL_MAX_TEXT_TOKENS)
        self.assertAlmostEqual(plan["safety_limits"]["runtime_max_audio_seconds_after_terminal_token_drop"], RUNTIME_MAX_AUDIO_SECONDS)
        for mode in MODES:
            self.assertEqual(len(plan["candidates"][mode]), 6)
            self.assertEqual(len(plan["jobs"][mode]), 12)
            self.assertTrue(all(job["seed"] >= 0 for job in plan["jobs"][mode]))
        self.assertEqual(
            plan["jobs"]["existing_phrase"][0]["seed"],
            plan["jobs"]["sentence"][0]["seed"],
        )

    def test_three_modes_keep_the_exact_same_script_text(self):
        plan = plan_experiment(_input(), output_root="experiments/luna_quality/test", candidate_budget=6, repo_root=self.repo)
        modes = plan["scripts"][0]["modes"]
        for mode in MODES:
            rebuilt = "".join(segment["text"] for segment in modes[mode]["segments"])
            self.assertEqual("".join(rebuilt.split()), "".join(_input()["scripts"][0]["text"].split()))

    def test_long_hybrid_sentence_uses_semantic_clauses(self):
        clauses = [
            "첫 번째 조건의 원인과 결과를 충분히 자세하게 설명하지만,",
            "두 번째 조건의 예외와 적용 범위도 빠짐없이 확인하고 ",
            "세 번째 조건의 데이터와 측정 기준을 다시 비교해서 ",
            "마지막 결론의 근거와 남은 한계를 차분하고 분명하게 전달합니다.",
        ]
        text = "".join(clauses)
        plan = plan_experiment(_input(text, clauses), output_root="experiments/luna_quality/test", candidate_budget=8, repo_root=self.repo)
        segments = plan["scripts"][0]["modes"]["hybrid"]["segments"]
        self.assertGreater(len(segments), 1)
        self.assertEqual({row["strategy"] for row in segments}, {"sentence_or_semantic_clause"})

    def test_unsafe_long_hybrid_falls_back_but_sentence_records_mode_failure(self):
        phrase = "가" * 70
        text = phrase + phrase
        plan = plan_experiment(_input(text, [phrase, phrase]), output_root="experiments/luna_quality/test", candidate_budget=4, repo_root=self.repo)
        modes = plan["scripts"][0]["modes"]
        self.assertEqual(modes["sentence"]["status"], "fail")
        self.assertEqual(modes["hybrid"]["status"], "pass")
        self.assertEqual({row["strategy"] for row in modes["hybrid"]["segments"]}, {"existing_phrase_fallback"})

    def test_input_rejects_frozen_project_and_nonmatching_existing_text(self):
        frozen = _input()
        frozen["frozen_project"] = True
        with self.assertRaisesRegex(ValueError, "frozen_project"):
            plan_experiment(frozen, output_root="experiments/luna_quality/test", repo_root=self.repo)
        known_frozen = _input()
        known_frozen["source_project_id"] = "SPIDER-001"
        with self.assertRaisesRegex(ValueError, "frozen project"):
            plan_experiment(known_frozen, output_root="experiments/luna_quality/test", repo_root=self.repo)
        mismatch = _input()
        mismatch["scripts"][0]["existing_phrases"][0]["text"] = "다른 문장입니다."
        with self.assertRaisesRegex(ValueError, "same script text"):
            plan_experiment(mismatch, output_root="experiments/luna_quality/test", repo_root=self.repo)

    def test_candidate_budget_must_be_positive(self):
        with self.assertRaisesRegex(ValueError, "positive"):
            plan_experiment(_input(), output_root="experiments/luna_quality/test", candidate_budget=0, repo_root=self.repo)

    def test_plan_root_must_be_new_and_isolated(self):
        outside = self.repo / "projects" / "unsafe"
        with self.assertRaisesRegex(ValueError, "experiments/luna_quality"):
            write_plan_bundle(_input(), outside, repo_root=self.repo)
        plan_path, root = self.plan()
        self.assertTrue(plan_path.is_file())
        with self.assertRaises(FileExistsError):
            write_plan_bundle(_input(), root, repo_root=self.repo)

    def test_dry_run_checks_every_path_and_preserves_external_cache_byte_for_byte(self):
        cache = self.repo / "projects" / "existing" / "cache.bin"
        cache.parent.mkdir(parents=True)
        cache.write_bytes(b"production-cache\x00unchanged")
        before = cache.read_bytes()
        plan_path, _ = self.plan()
        report = dry_run_plan(plan_path, repo_root=self.repo)
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["planned_candidate_count"], 18)
        self.assertEqual(report["planned_generation_job_count"], 36)
        self.assertEqual(report["planned_output_count"], 112)
        self.assertFalse(report["model_loaded"])
        self.assertFalse(report["audio_generated"])
        self.assertEqual(cache.read_bytes(), before)

    def test_dry_run_detects_collision_and_forbidden_names(self):
        plan_path, root = self.plan()
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        jobs_path = root / plan["job_manifests"]["existing_phrase"]
        jobs = json.loads(jobs_path.read_text(encoding="utf-8"))
        collision = root / jobs["jobs"][0]["audio_relative_path"]
        collision.parent.mkdir(parents=True)
        collision.write_bytes(b"existing")
        report = dry_run_plan(plan_path, repo_root=self.repo)
        self.assertEqual(report["status"], "fail")
        self.assertEqual(report["collision_count"], 1)
        self.assertTrue(any("output_collision" in error for error in report["errors"]))

    def test_actual_generation_requires_explicit_acknowledgement(self):
        plan_path, _ = self.plan()
        with self.assertRaisesRegex(PermissionError, "acknowledge"):
            execute_generation(plan_path, acknowledge_isolated_experiment=False, repo_root=self.repo)

    def test_sentence_plan_requires_post_generation_boundary_alignment(self):
        plan = plan_experiment(_input(), output_root="experiments/luna_quality/test", candidate_budget=2, repo_root=self.repo)
        extraction = plan["scripts"][0]["modes"]["sentence"]["post_generation_boundary_extraction"]
        self.assertTrue(extraction["required"])
        self.assertEqual(extraction["methods"], ["asr", "forced_alignment"])
        self.assertEqual(extraction["default_status"], "not_run")

    def test_cli_hybrid_run_is_dry_by_default(self):
        input_path = self.repo / "fixture-input.json"
        input_path.write_text(json.dumps(_input(), ensure_ascii=False), encoding="utf-8")
        output = self.repo / "experiments" / "luna_quality" / "cli-run"
        with patch("scripts.luna_quality.cli._repo_root", return_value=self.repo):
            self.assertEqual(
                main(["hybrid-plan", "--input", str(input_path), "--output-root", str(output), "--candidate-budget", "2"]),
                0,
            )
            self.assertEqual(main(["hybrid-run", "--plan", str(output / "segmentation_plan.json")]), 0)
        report = json.loads((output / "dry_run_report.json").read_text(encoding="utf-8"))
        self.assertFalse(report["model_loaded"])
        self.assertFalse(report["audio_generated"])
        self.assertFalse(any(output.rglob("*.wav")))

    def test_actual_runner_loads_one_generator_and_writes_mode_validator_bundles(self):
        plan_path, root = self.plan(budget=2)
        counters = {"factory": 0, "generate": 0}

        class DummyGenerator:
            def generate(self, job, audio_path):
                counters["generate"] += 1
                _write_wav(audio_path)
                return {"duration_seconds": 0.4, "actual_text_tokens": 12, "sample_rate_hz": 24000}

        def factory(_plan, _repo):
            counters["factory"] += 1
            return DummyGenerator()

        result_path = execute_generation(
            plan_path,
            acknowledge_isolated_experiment=True,
            repo_root=self.repo,
            generator_factory=factory,
        )
        payload = json.loads(result_path.read_text(encoding="utf-8"))
        self.assertEqual(counters, {"factory": 1, "generate": 12})
        self.assertEqual(len(payload["results"]), 6)
        self.assertFalse(payload["promotion_performed"])
        self.assertFalse(any(str(path).lower().endswith("_luna.wav") for path in root.rglob("*.wav")))
        self.assertEqual({path.stem for path in (root / "validator_results").glob("*.json")}, set(MODES))

    def test_evaluator_separates_modes_and_counts_repetition_as_mode_failure(self):
        bundle = evaluate_results(_results_fixture())
        modes = bundle["analysis"]["modes"]
        self.assertEqual(list(bundle["analysis"]["mode_order"]), list(MODES))
        self.assertEqual(modes["existing_phrase"]["failed_candidate_count"], 0)
        self.assertEqual(modes["sentence"]["failed_candidate_count"], 0)
        self.assertEqual(modes["hybrid"]["failed_candidate_count"], 1)
        self.assertEqual(modes["hybrid"]["mode_failure_reasons"]["signal:repetition"], 1)
        self.assertEqual(bundle["analysis"]["promotion_recommendation"], "not_permitted_in_s09")
        self.assertEqual(bundle["analysis"]["fairness_check"]["status"], "pass")

    def test_blind_manifest_hides_mode_and_defines_preference_import(self):
        bundle = evaluate_results(_results_fixture())
        public = bundle["blind_manifest"]
        self.assertFalse(public["mode_labels_exposed"])
        self.assertTrue(public["entries"])
        self.assertTrue(all("mode" not in row and "candidate_id" not in row for row in public["entries"]))
        self.assertTrue(all(row["package_relative_path"].startswith("blind_audio/B") for row in public["entries"]))
        self.assertIn("preferred_blind_id", bundle["analysis"]["human_preference_import"]["required_fields"])
        self.assertTrue(all("mode" in row for row in bundle["blind_answer_key"]["entries"]))

    def test_analysis_bundle_writes_json_csv_timing_blind_and_evidence_report(self):
        output = self.repo / "experiments" / "luna_quality" / "analysis"
        path = write_analysis_bundle(_results_fixture(), output, repo_root=self.repo)
        self.assertTrue(path.is_file())
        expected = {
            "analysis.json",
            "analysis.csv",
            "timing.json",
            "blind_listening_manifest.json",
            "blind_answer_key.json",
            "EVIDENCE_REPORT.md",
        }
        self.assertEqual({item.name for item in output.iterdir()}, expected)
        self.assertIn("not permitted in S09", (output / "EVIDENCE_REPORT.md").read_text(encoding="utf-8"))


def _write_wav(path):
    rate = 24000
    frames = 9600
    samples = []
    for index in range(frames):
        envelope = min(1.0, index / 200, (frames - index - 1) / 200)
        value = 0.08 * envelope * math.sin(2 * math.pi * 220 * index / rate)
        samples.append(int(value * 32767).to_bytes(2, "little", signed=True))
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        writer.writeframes(b"".join(samples))


if __name__ == "__main__":
    unittest.main()
