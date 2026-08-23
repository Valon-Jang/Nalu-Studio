"""Mode-separated evidence analysis and blind-listening manifests for S09."""

from __future__ import annotations

import csv
import io
import json
import math
from collections import defaultdict
from pathlib import Path
from statistics import fmean
from typing import Any, Mapping, Sequence

from ...hashing import sha256_file, sha256_text
from .planner import MODES, assert_isolated_experiment_root
from .runner import RESULT_SCHEMA_VERSION

ANALYSIS_SCHEMA_VERSION = "luna-hybrid-analysis/1"
BLIND_SCHEMA_VERSION = "luna-hybrid-blind-package/1"
BLIND_KEY_SCHEMA_VERSION = "luna-hybrid-blind-answer-key/1"
TIMING_SCHEMA_VERSION = "luna-hybrid-timing/1"

_VALIDATOR_NAMES = (
    "content_accuracy",
    "audio_sanity",
    "speaker_similarity",
    "existing_prosody_gates",
    "phrase_transition",
    "boundary_alignment",
)


def evaluate_results(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Aggregate generation/validator evidence without choosing a winner."""
    if payload.get("schema_version") != RESULT_SCHEMA_VERSION:
        raise ValueError(f"results schema must be {RESULT_SCHEMA_VERSION}")
    experiment_id = str(payload.get("experiment_id") or "")
    rows = payload.get("results")
    if not experiment_id or not isinstance(rows, list):
        raise ValueError("experiment_id and results are required")
    grouped: dict[str, list[Mapping[str, Any]]] = {mode: [] for mode in MODES}
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping) or row.get("mode") not in MODES:
            raise ValueError("each result requires a supported mode")
        candidate_id = str(row.get("candidate_id") or "")
        if not candidate_id or candidate_id in seen or not str(row.get("script_id") or ""):
            raise ValueError("candidate_id values must be unique and candidate/script IDs must be non-empty")
        seen.add(candidate_id)
        grouped[str(row["mode"])].append(row)

    mode_analysis = {mode: _mode_analysis(grouped[mode]) for mode in MODES}
    blind, answer_key = _blind_manifests(experiment_id, rows)
    timing = {
        "schema_version": TIMING_SCHEMA_VERSION,
        "experiment_id": experiment_id,
        "modes": {
            mode: {
                "candidate_count": mode_analysis[mode]["candidate_count"],
                "total_generation_seconds": mode_analysis[mode]["total_generation_seconds"],
                "mean_generation_seconds": mode_analysis[mode]["mean_generation_seconds"],
                "total_assembly_seconds": mode_analysis[mode]["total_assembly_seconds"],
                "mean_assembly_seconds": mode_analysis[mode]["mean_assembly_seconds"],
                "total_processing_seconds": mode_analysis[mode]["total_processing_seconds"],
                "total_audio_seconds": mode_analysis[mode]["total_duration_seconds"],
                "real_time_factor": mode_analysis[mode]["real_time_factor"],
            }
            for mode in MODES
        },
    }
    canonical_results = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    fairness = _fairness_check(rows)
    analysis = {
        "schema_version": ANALYSIS_SCHEMA_VERSION,
        "experiment_id": experiment_id,
        "source_results_sha256": sha256_text(canonical_results),
        "modes": mode_analysis,
        "mode_order": list(MODES),
        "fairness_check": fairness,
        "evaluated_dimensions": [
            "content_accuracy",
            "abnormal_silence_or_repetition",
            "speaker_similarity_or_drift",
            "existing_prosody_gates",
            "phrase_transition",
            "sentence_boundary_alignment",
            "duration",
            "generation_timing",
            "failure_rate",
            "human_blind_preference",
        ],
        "human_preference_import": {
            "schema_version": "luna-hybrid-human-preference/1",
            "required_fields": ["comparison_id", "listener_id", "preferred_blind_id"],
            "optional_fields": ["rejected_blind_ids", "notes"],
            "allowed_preference": "one blind_id from the referenced comparison",
        },
        "promotion_recommendation": "not_permitted_in_s09",
        "automatic_promotion_performed": False,
        "production_selection_changed": False,
    }
    return {"analysis": analysis, "timing": timing, "blind_manifest": blind, "blind_answer_key": answer_key}


def write_analysis_bundle(
    results_or_path: Mapping[str, Any] | str | Path,
    output_root: str | Path,
    *,
    repo_root: str | Path | None = None,
) -> Path:
    repository = (Path(repo_root) if repo_root is not None else _repo_root()).resolve()
    if isinstance(results_or_path, Mapping):
        payload = dict(results_or_path)
        source_file_hash = None
    else:
        source = Path(results_or_path).resolve()
        payload = json.loads(source.read_text(encoding="utf-8"))
        source_file_hash = sha256_file(source)
    root = assert_isolated_experiment_root(output_root, repository)
    if root.exists():
        raise FileExistsError(f"analysis output already exists: {root}")
    bundle = evaluate_results(payload)
    if source_file_hash:
        bundle["analysis"]["source_results_file_sha256"] = source_file_hash
    root.mkdir(parents=True, exist_ok=False)
    _write_exclusive_json(root / "analysis.json", bundle["analysis"])
    _write_exclusive_text(root / "analysis.csv", _analysis_csv(bundle["analysis"]))
    _write_exclusive_json(root / "timing.json", bundle["timing"])
    _write_exclusive_json(root / "blind_listening_manifest.json", bundle["blind_manifest"])
    _write_exclusive_json(root / "blind_answer_key.json", bundle["blind_answer_key"])
    _write_exclusive_text(root / "EVIDENCE_REPORT.md", _evidence_report(bundle["analysis"]))
    return root / "analysis.json"


def _mode_analysis(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    failures = [_failure_reasons(row) for row in rows]
    failed_count = sum(bool(reasons) for reasons in failures)
    durations = _numbers(row.get("duration_seconds") for row in rows)
    generation_times = _numbers(row.get("generation_seconds") for row in rows)
    assembly_times = _numbers(row.get("assembly_seconds") for row in rows)
    validator_statuses: dict[str, dict[str, int]] = {}
    validator_failure_reasons: dict[str, int] = defaultdict(int)
    for name in _VALIDATOR_NAMES:
        counts = {status: 0 for status in ("pass", "fail", "unknown", "not_run")}
        for row in rows:
            validation = _validation(row, name)
            status = str((validation or {}).get("status") or "not_run")
            counts[status if status in counts else "unknown"] += 1
            if validation and status == "fail":
                for reason in validation.get("reasons") or ["unspecified"]:
                    validator_failure_reasons[f"{name}:{reason}"] += 1
        validator_statuses[name] = counts

    content_scores = _validator_scores(rows, "content_accuracy", ("content_score", "score"), invert="normalized_edit_distance")
    speaker_scores = _validator_scores(
        rows,
        "speaker_similarity",
        ("primary_chatterbox_similarity", "speaker_similarity", "score"),
    )
    prosody_scores = _validator_scores(rows, "existing_prosody_gates", ("score",))
    transition_scores = _validator_scores(rows, "phrase_transition", ("transition_score", "score"))
    signal_counts = {
        name: sum(_signal_is_failure((row.get("signals") or {}).get(name)) for row in rows)
        for name in ("hallucination", "repetition", "speaker_drift", "abnormal_silence")
    }
    total_generation = sum(generation_times)
    total_assembly = sum(assembly_times)
    total_processing = total_generation + total_assembly
    total_duration = sum(durations)
    return {
        "candidate_count": len(rows),
        "successful_candidate_count": len(rows) - failed_count,
        "failed_candidate_count": failed_count,
        "failure_rate": _ratio(failed_count, len(rows)),
        "mode_failure_reasons": dict(sorted(_reason_counts(failures).items())),
        "validator_status_counts": validator_statuses,
        "validator_failure_reasons": dict(sorted(validator_failure_reasons.items())),
        "mean_content_accuracy": _mean_or_none(content_scores),
        "mean_speaker_similarity": _mean_or_none(speaker_scores),
        "mean_existing_prosody_score": _mean_or_none(prosody_scores),
        "mean_phrase_transition_score": _mean_or_none(transition_scores),
        "signal_failure_counts": signal_counts,
        "mean_duration_seconds": _mean_or_none(durations),
        "total_duration_seconds": round(total_duration, 6),
        "mean_generation_seconds": _mean_or_none(generation_times),
        "total_generation_seconds": round(total_generation, 6),
        "mean_assembly_seconds": _mean_or_none(assembly_times),
        "total_assembly_seconds": round(total_assembly, 6),
        "total_processing_seconds": round(total_processing, 6),
        "real_time_factor": round(total_processing / total_duration, 6) if total_duration else None,
    }


def _failure_reasons(row: Mapping[str, Any]) -> list[str]:
    reasons = [str(reason) for reason in row.get("failure_reasons") or []]
    if row.get("status") != "pass" and not reasons:
        reasons.append("generation_status_not_pass")
    for name, value in (row.get("signals") or {}).items():
        if _signal_is_failure(value):
            reasons.append(f"signal:{name}")
    for validation in row.get("validations") or []:
        if validation.get("hard_gate") is True and validation.get("status") == "fail":
            reasons.append(f"hard_gate:{validation.get('validator_name', 'unknown')}")
    return sorted(set(reasons))


def _blind_manifests(experiment_id: str, rows: Sequence[Mapping[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    eligible = [row for row in rows if not _failure_reasons(row) and row.get("audio_relative_path")]
    ordered = sorted(
        eligible,
        key=lambda row: sha256_text(f"{experiment_id}|{row['candidate_id']}|blind-order"),
    )
    public_entries: list[dict[str, Any]] = []
    key_entries: list[dict[str, Any]] = []
    comparisons: dict[str, list[str]] = defaultdict(list)
    for index, row in enumerate(ordered, 1):
        blind_id = f"B{index:04d}"
        script_id = str(row.get("script_id") or "")
        public_entries.append(
            {
                "blind_id": blind_id,
                "script_id": script_id,
                "package_relative_path": f"blind_audio/{blind_id}.wav",
            }
        )
        key_entries.append(
            {
                "blind_id": blind_id,
                "candidate_id": row["candidate_id"],
                "mode": row["mode"],
                "source_audio_relative_path": row["audio_relative_path"],
            }
        )
        comparisons[script_id].append(blind_id)
    blind = {
        "schema_version": BLIND_SCHEMA_VERSION,
        "experiment_id": experiment_id,
        "mode_labels_exposed": False,
        "entries": public_entries,
        "comparisons": [
            {"comparison_id": f"{experiment_id}.{script_id}", "script_id": script_id, "blind_ids": ids}
            for script_id, ids in sorted(comparisons.items())
        ],
        "preference_import_schema_version": "luna-hybrid-human-preference/1",
    }
    answer_key = {
        "schema_version": BLIND_KEY_SCHEMA_VERSION,
        "experiment_id": experiment_id,
        "keep_separate_from_listeners": True,
        "entries": key_entries,
    }
    return blind, answer_key


def _fairness_check(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    counts: dict[str, dict[str, int]] = defaultdict(lambda: {mode: 0 for mode in MODES})
    for row in rows:
        counts[str(row.get("script_id") or "")][str(row["mode"])] += 1
    per_script = {script_id: dict(mode_counts) for script_id, mode_counts in sorted(counts.items())}
    violations = [
        script_id
        for script_id, mode_counts in per_script.items()
        if len(set(mode_counts.values())) != 1 or next(iter(mode_counts.values()), 0) == 0
    ]
    return {
        "status": "pass" if not violations else "fail",
        "candidate_unit": "complete_script_assembly",
        "per_script_mode_candidate_counts": per_script,
        "violating_script_ids": violations,
    }


def _analysis_csv(analysis: Mapping[str, Any]) -> str:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["mode", "metric", "value"])
    metrics = (
        "candidate_count",
        "successful_candidate_count",
        "failed_candidate_count",
        "failure_rate",
        "mean_content_accuracy",
        "mean_speaker_similarity",
        "mean_existing_prosody_score",
        "mean_phrase_transition_score",
        "mean_duration_seconds",
        "mean_generation_seconds",
        "mean_assembly_seconds",
        "total_processing_seconds",
        "real_time_factor",
    )
    for mode in MODES:
        for metric in metrics:
            writer.writerow([mode, metric, analysis["modes"][mode][metric]])
    return output.getvalue()


def _evidence_report(analysis: Mapping[str, Any]) -> str:
    lines = [
        "# S09 Hybrid Synthesis Evidence Report",
        "",
        f"Experiment: `{analysis['experiment_id']}`",
        "",
        "This is comparison evidence only. S09 does not recommend or perform production promotion.",
        "",
        "| Mode | Candidates | Failures | Failure rate | Content | Speaker | Transition |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for mode in MODES:
        row = analysis["modes"][mode]
        lines.append(
            "| {mode} | {candidate_count} | {failed_candidate_count} | {failure_rate} | {content} | {speaker} | {transition} |".format(
                mode=mode,
                candidate_count=row["candidate_count"],
                failed_candidate_count=row["failed_candidate_count"],
                failure_rate=_display(row["failure_rate"]),
                content=_display(row["mean_content_accuracy"]),
                speaker=_display(row["mean_speaker_similarity"]),
                transition=_display(row["mean_phrase_transition_score"]),
            )
        )
    lines.extend(
        [
            "",
            "Human preference rows must use `luna-hybrid-human-preference/1` and blind IDs from the public manifest.",
            "",
            "Promotion recommendation: **not permitted in S09**.",
            "",
        ]
    )
    return "\n".join(lines)


def _validation(row: Mapping[str, Any], name: str) -> Mapping[str, Any] | None:
    return next((item for item in row.get("validations") or [] if item.get("validator_name") == name), None)


def _validator_scores(
    rows: Sequence[Mapping[str, Any]],
    validator_name: str,
    keys: Sequence[str],
    *,
    invert: str | None = None,
) -> list[float]:
    scores: list[float] = []
    for row in rows:
        validation = _validation(row, validator_name)
        if not validation:
            continue
        sources = [validation, validation.get("metrics") or {}]
        value = next((_finite(source.get(key)) for source in sources for key in keys if _finite(source.get(key)) is not None), None)
        if value is None and invert:
            raw = next((_finite(source.get(invert)) for source in sources if _finite(source.get(invert)) is not None), None)
            value = max(0.0, 1.0 - raw) if raw is not None else None
        if value is not None:
            scores.append(value)
    return scores


def _reason_counts(groups: Sequence[Sequence[str]]) -> dict[str, int]:
    result: dict[str, int] = defaultdict(int)
    for reasons in groups:
        for reason in reasons:
            result[reason] += 1
    return dict(result)


def _signal_is_failure(value: Any) -> bool:
    return value is True or str(value).lower() in {"fail", "failed", "detected"}


def _numbers(values) -> list[float]:
    return [number for value in values if (number := _finite(value)) is not None]


def _finite(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _mean_or_none(values: Sequence[float]) -> float | None:
    return round(fmean(values), 6) if values else None


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def _display(value: Any) -> str:
    return "not_run" if value is None else str(value)


def _write_exclusive_json(path: Path, payload: Mapping[str, Any]) -> None:
    _write_exclusive_text(path, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _write_exclusive_text(path: Path, text: str) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]
