"""CLI for read-only Luna-quality shadow evaluation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .adapters.whisperx_adapter import WhisperXAdapter
from .contracts import ValidationResult
from .orchestrator.engine import DiscoveredTake, ShadowOrchestrator
from .orchestrator.policy import exception_result
from .orchestrator.report import write_shadow_report
from .validators.content_asr import ContentAsrValidator


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only Luna quality utilities")
    commands = parser.add_subparsers(dest="command", required=True)
    shadow = commands.add_parser("shadow-evaluate", help="evaluate an existing take directory without changing it")
    shadow.add_argument("--outdir", required=True, help="existing Luna output directory (read-only)")
    shadow.add_argument("--report", required=True, help="new report path outside --outdir")
    shadow.add_argument("--ranker-artifact", help="optional S07 ranker artifact")
    shadow.add_argument("--enable-asr", action="store_true", help="explicitly enable lazy WhisperX transcription")
    args = parser.parse_args(argv)

    if args.command == "shadow-evaluate":
        content_runner = _content_runner() if args.enable_asr else None
        orchestrator = ShadowOrchestrator(content_runner=content_runner, ranker_artifact=args.ranker_artifact)
        result = orchestrator.evaluate(args.outdir)
        report = write_shadow_report(result, args.report, args.outdir)
        print(json.dumps({"report": str(report), "read_only_verified": result.read_only_verified, "production_selection_changed": False}, sort_keys=True))
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


if __name__ == "__main__":
    raise SystemExit(main())
