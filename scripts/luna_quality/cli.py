"""CLI for shadow evaluation and production-isolated Luna experiments."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .adapters.whisperx_adapter import WhisperXAdapter
from .contracts import ValidationResult
from .experiments.hybrid_synthesis.evaluator import write_analysis_bundle
from .experiments.hybrid_synthesis.planner import write_plan_bundle
from .experiments.hybrid_synthesis.runner import execute_generation, write_dry_run_report
from .orchestrator.engine import DiscoveredTake, ShadowOrchestrator
from .orchestrator.policy import exception_result
from .orchestrator.report import write_shadow_report
from .validators.content_asr import ContentAsrValidator


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Production-safe Luna quality utilities")
    commands = parser.add_subparsers(dest="command", required=True)
    shadow = commands.add_parser("shadow-evaluate", help="evaluate an existing take directory without changing it")
    shadow.add_argument("--outdir", required=True, help="existing Luna output directory (read-only)")
    shadow.add_argument("--report", required=True, help="new report path outside --outdir")
    shadow.add_argument("--ranker-artifact", help="optional S07 ranker artifact")
    shadow.add_argument("--enable-asr", action="store_true", help="explicitly enable lazy WhisperX transcription")
    hybrid_plan = commands.add_parser("hybrid-plan", help="create an isolated phrase/sentence/hybrid plan")
    hybrid_plan.add_argument("--input", required=True, help="S09 input JSON")
    hybrid_plan.add_argument("--output-root", required=True, help="new child directory under experiments/luna_quality")
    hybrid_plan.add_argument("--candidate-budget", type=int, default=4, help="equal complete-script candidates per script and mode")
    hybrid_run = commands.add_parser("hybrid-run", help="dry-run an S09 plan; generation requires both opt-in flags")
    hybrid_run.add_argument("--plan", required=True, help="segmentation_plan.json")
    hybrid_run.add_argument("--report", help="optional dry-run report path inside the experiment root")
    hybrid_run.add_argument("--execute-generation", action="store_true", help="explicitly request real Chatterbox generation")
    hybrid_run.add_argument(
        "--acknowledge-isolated-experiment",
        action="store_true",
        help="confirm that generated audio is experiment-only and cannot be promoted by S09",
    )
    hybrid_evaluate = commands.add_parser("hybrid-evaluate", help="write mode-separated S09 evidence artifacts")
    hybrid_evaluate.add_argument("--results", required=True, help="generation_results.json or fixture equivalent")
    hybrid_evaluate.add_argument("--output-root", required=True, help="new analysis directory under experiments/luna_quality")
    args = parser.parse_args(argv)

    if args.command == "shadow-evaluate":
        content_runner = _content_runner() if args.enable_asr else None
        orchestrator = ShadowOrchestrator(content_runner=content_runner, ranker_artifact=args.ranker_artifact)
        result = orchestrator.evaluate(args.outdir)
        report = write_shadow_report(result, args.report, args.outdir)
        print(json.dumps({"report": str(report), "read_only_verified": result.read_only_verified, "production_selection_changed": False}, sort_keys=True))
        return 0
    if args.command == "hybrid-plan":
        input_path = Path(args.input)
        payload = json.loads(input_path.read_text(encoding="utf-8"))
        plan = write_plan_bundle(
            payload,
            args.output_root,
            candidate_budget=args.candidate_budget,
            repo_root=_repo_root(),
        )
        print(json.dumps({"plan": str(plan), "audio_generated": False, "production_selection_changed": False}, sort_keys=True))
        return 0
    if args.command == "hybrid-run":
        if args.execute_generation:
            result = execute_generation(
                args.plan,
                acknowledge_isolated_experiment=args.acknowledge_isolated_experiment,
                repo_root=_repo_root(),
            )
            print(json.dumps({"results": str(result), "promotion_performed": False, "production_selection_changed": False}, sort_keys=True))
            return 0
        if args.acknowledge_isolated_experiment:
            parser.error("--acknowledge-isolated-experiment is only valid with --execute-generation")
        report = write_dry_run_report(args.plan, args.report, repo_root=_repo_root())
        print(json.dumps({"dry_run_report": str(report), "audio_generated": False, "production_selection_changed": False}, sort_keys=True))
        return 0
    if args.command == "hybrid-evaluate":
        analysis = write_analysis_bundle(args.results, args.output_root, repo_root=_repo_root())
        print(json.dumps({"analysis": str(analysis), "promotion_performed": False, "production_selection_changed": False}, sort_keys=True))
        return 0
    raise AssertionError("unreachable")


def _content_runner():
    adapter = WhisperXAdapter()
    validator = ContentAsrValidator()

    def run(take: DiscoveredTake) -> ValidationResult:
        try:
            transcript = adapter.transcribe(take.wav_path)
            return validator.validate(str(take.row.get("text") or ""), transcript)
        except Exception as exc:
            return exception_result("content_asr", exc, hard_gate=True)

    return run


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


if __name__ == "__main__":
    raise SystemExit(main())
