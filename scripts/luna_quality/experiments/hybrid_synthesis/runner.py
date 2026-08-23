"""Dry-run and explicitly opted-in integration runner for S09."""

from __future__ import annotations

import json
import math
import os
import random
import struct
import sys
import time
import wave
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping

from ...contracts import ValidationResult, ValidationStatus
from ...hashing import sha256_file
from ...validators.audio_sanity import AudioSanityValidator
from .planner import (
    ASSEMBLY_POLICY,
    EXPERIMENT_MAX_ESTIMATED_AUDIO_SECONDS,
    FIXED_GENERATION_PARAMETERS,
    MODEL_MAX_TEXT_TOKENS,
    MODES,
    PLAN_SCHEMA_VERSION,
    REFERENCE_RELATIVE_PATH,
    REFERENCE_SHA256,
    assert_isolated_experiment_root,
    load_plan_bundle,
)

DRY_RUN_SCHEMA_VERSION = "luna-hybrid-dry-run/1"
RESULT_SCHEMA_VERSION = "luna-hybrid-generation-results/1"
VALIDATOR_BUNDLE_SCHEMA_VERSION = "luna-hybrid-validator-results/1"


def dry_run_plan(
    plan_or_path: Mapping[str, Any] | str | Path,
    *,
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    """Validate every job and output collision without importing the TTS runtime."""
    repository = (Path(repo_root) if repo_root is not None else _repo_root()).resolve()
    plan, plan_root = _load_plan(plan_or_path, repository)
    errors: list[str] = []
    if plan.get("schema_version") != PLAN_SCHEMA_VERSION:
        errors.append("unsupported_plan_schema")
    expected_root = assert_isolated_experiment_root(plan.get("output_root", ""), repository)
    if expected_root != plan_root.resolve():
        errors.append("plan_output_root_mismatch")
    isolation = plan.get("production_isolation") or {}
    if isolation.get("frozen_project_excluded") is not True:
        errors.append("frozen_project_exclusion_missing")
    if isolation.get("promotion_permitted") is not False:
        errors.append("automatic_promotion_not_disabled")

    job_ids: set[str] = set()
    candidate_ids: set[str] = set()
    output_paths: set[str] = set()
    candidate_counts: dict[tuple[str, str], int] = Counter()
    mode_details: dict[str, dict[str, Any]] = {}
    planned_collisions: list[str] = []
    ineligible: list[str] = []
    for mode in MODES:
        jobs = list((plan.get("jobs") or {}).get(mode) or [])
        for job in jobs:
            job_id = str(job.get("job_id") or "")
            candidate_id = str(job.get("candidate_id") or "")
            if not job_id or job_id in job_ids:
                errors.append(f"duplicate_or_empty_job_id:{job_id}")
            job_ids.add(job_id)
            if not candidate_id:
                errors.append(f"empty_candidate_id:{job_id}")
            if job.get("mode") != mode:
                errors.append(f"mode_mismatch:{job_id}")
            if job.get("execution_eligible") is not True:
                ineligible.append(job_id)
            for key, suffix in (("audio_relative_path", ".wav"), ("metadata_relative_path", ".json")):
                relative = _safe_relative_path(job.get(key), suffix)
                if relative is None:
                    errors.append(f"unsafe_output_path:{job_id}:{key}")
                    continue
                normalized = relative.as_posix()
                lowered = normalized.lower()
                if key == "audio_relative_path" and not normalized.startswith(f"segments/{mode}/"):
                    errors.append(f"segment_path_outside_mode_namespace:{normalized}")
                if lowered.endswith("_luna.wav") or lowered.endswith("pins.json"):
                    errors.append(f"forbidden_production_name:{normalized}")
                if normalized in output_paths:
                    errors.append(f"duplicate_output_path:{normalized}")
                output_paths.add(normalized)
                if (plan_root / Path(*relative.parts)).exists():
                    planned_collisions.append(normalized)
        candidates = list((plan.get("candidates") or {}).get(mode) or [])
        for candidate in candidates:
            candidate_id = str(candidate.get("candidate_id") or "")
            if not candidate_id or candidate_id in candidate_ids:
                errors.append(f"duplicate_or_empty_candidate_id:{candidate_id}")
            candidate_ids.add(candidate_id)
            if candidate.get("mode") != mode:
                errors.append(f"candidate_mode_mismatch:{candidate_id}")
            candidate_counts[(str(candidate.get("script_id") or ""), mode)] += 1
            referenced_jobs = list(candidate.get("segment_job_ids") or [])
            if not referenced_jobs or any(job_id not in job_ids for job_id in referenced_jobs):
                errors.append(f"candidate_job_reference_invalid:{candidate_id}")
            for key, suffix in (("audio_relative_path", ".wav"), ("metadata_relative_path", ".json")):
                relative = _safe_relative_path(candidate.get(key), suffix)
                if relative is None:
                    errors.append(f"unsafe_candidate_output_path:{candidate_id}:{key}")
                    continue
                normalized = relative.as_posix()
                lowered = normalized.lower()
                if key == "audio_relative_path" and not normalized.startswith(f"candidates/{mode}/"):
                    errors.append(f"candidate_path_outside_mode_namespace:{normalized}")
                if lowered.endswith("_luna.wav") or lowered.endswith("pins.json"):
                    errors.append(f"forbidden_production_name:{normalized}")
                if normalized in output_paths:
                    errors.append(f"duplicate_output_path:{normalized}")
                output_paths.add(normalized)
                if (plan_root / Path(*relative.parts)).exists():
                    planned_collisions.append(normalized)
        mode_details[mode] = {
            "candidate_count": len(candidates),
            "generation_job_count": len(jobs),
            "execution_eligible_job_count": sum(job.get("execution_eligible") is True for job in jobs),
            "status": "pass" if candidates and jobs and all(job.get("execution_eligible") is True for job in jobs) else "fail",
        }

    budget = int((plan.get("fairness") or {}).get("same_candidate_budget_per_script_and_mode") or 0)
    script_ids = [str(row.get("script_id") or "") for row in plan.get("scripts") or []]
    for script_id in script_ids:
        for mode in MODES:
            if candidate_counts[(script_id, mode)] != budget:
                errors.append(f"candidate_budget_mismatch:{script_id}:{mode}")
    reserved_outputs = ["generation_results.json", *(f"validator_results/{mode}.json" for mode in MODES)]
    for relative in reserved_outputs:
        output_paths.add(relative)
        if (plan_root / Path(*PurePosixPath(relative).parts)).exists():
            planned_collisions.append(relative)
    if planned_collisions:
        errors.extend(f"output_collision:{path}" for path in sorted(planned_collisions))
    if ineligible:
        errors.extend(f"safety_ineligible:{candidate_id}" for candidate_id in sorted(ineligible))
    status = "pass" if not errors else "fail"
    return {
        "schema_version": DRY_RUN_SCHEMA_VERSION,
        "experiment_id": plan.get("experiment_id"),
        "status": status,
        "errors": errors,
        "mode_results": mode_details,
        "planned_candidate_count": len(candidate_ids),
        "planned_generation_job_count": len(job_ids),
        "planned_output_count": len(output_paths),
        "collision_count": len(planned_collisions),
        "model_loaded": False,
        "audio_generated": False,
        "production_pipeline_changed": False,
        "production_cache_changed": False,
        "production_selection_changed": False,
        "promotion_performed": False,
    }


def write_dry_run_report(
    plan_path: str | Path,
    report_path: str | Path | None = None,
    *,
    repo_root: str | Path | None = None,
) -> Path:
    path = Path(plan_path).resolve()
    report = dry_run_plan(path, repo_root=repo_root)
    destination = Path(report_path).resolve() if report_path is not None else path.parent / "dry_run_report.json"
    try:
        destination.relative_to(path.parent)
    except ValueError as exc:
        raise ValueError("dry-run report must stay inside the isolated experiment root") from exc
    _write_exclusive_json(destination, report)
    return destination


def execute_generation(
    plan_path: str | Path,
    *,
    acknowledge_isolated_experiment: bool,
    repo_root: str | Path | None = None,
    generator_factory: Callable[[Mapping[str, Any], Path], Any] | None = None,
) -> Path:
    """Generate experiment candidates only after an explicit acknowledgement.

    The factory hook exists for deterministic tests.  The default generator is
    lazy and imports the pinned Chatterbox runtime only after all safety and
    collision checks pass.
    """
    if acknowledge_isolated_experiment is not True:
        raise PermissionError("actual generation requires --acknowledge-isolated-experiment")
    repository = (Path(repo_root) if repo_root is not None else _repo_root()).resolve()
    plan_file = Path(plan_path).resolve()
    plan, plan_root = _load_plan(plan_file, repository)
    dry = dry_run_plan(plan_file, repo_root=repository)
    if dry["status"] != "pass":
        raise ValueError("dry-run failed; actual generation is blocked")
    _verify_reference(repository)

    factory = generator_factory or _default_generator_factory
    generator = factory(plan, repository)  # Exactly one model/generator load per execution.
    segment_results: list[dict[str, Any]] = []
    segment_by_job_id: dict[str, dict[str, Any]] = {}
    results: list[dict[str, Any]] = []
    validators_by_mode: dict[str, list[dict[str, Any]]] = {mode: [] for mode in MODES}
    for mode in MODES:
        for job in plan["jobs"][mode]:
            audio_path = plan_root / Path(*PurePosixPath(job["audio_relative_path"]).parts)
            metadata_path = plan_root / Path(*PurePosixPath(job["metadata_relative_path"]).parts)
            audio_path.parent.mkdir(parents=True, exist_ok=True)
            started = time.perf_counter()
            try:
                generated = dict(generator.generate(job, audio_path))
                elapsed = time.perf_counter() - started
                duration = float(generated["duration_seconds"])
                actual_tokens = int(generated["actual_text_tokens"])
                reasons: list[str] = []
                if actual_tokens > MODEL_MAX_TEXT_TOKENS:
                    reasons.append("actual_text_token_limit_exceeded")
                if duration > EXPERIMENT_MAX_ESTIMATED_AUDIO_SECONDS:
                    reasons.append("duration_exceeds_experiment_safety_margin")
                if not audio_path.is_file():
                    reasons.append("generator_did_not_create_audio")
                status = "fail" if reasons else "pass"
                row = {
                    **_job_identity(job),
                    "status": status,
                    "failure_reasons": reasons,
                    "audio_relative_path": job["audio_relative_path"],
                    "audio_sha256": sha256_file(audio_path) if audio_path.is_file() else None,
                    "duration_seconds": duration,
                    "generation_seconds": round(elapsed, 6),
                    "actual_text_tokens": actual_tokens,
                    "sample_rate_hz": int(generated.get("sample_rate_hz", 24000)),
                }
            except Exception as exc:
                elapsed = time.perf_counter() - started
                row = {
                    **_job_identity(job),
                    "status": "fail",
                    "failure_reasons": [f"generation_exception:{type(exc).__name__}"],
                    "audio_relative_path": job["audio_relative_path"] if audio_path.is_file() else None,
                    "audio_sha256": sha256_file(audio_path) if audio_path.is_file() else None,
                    "duration_seconds": None,
                    "generation_seconds": round(elapsed, 6),
                    "actual_text_tokens": None,
                    "sample_rate_hz": None,
                }
            _write_exclusive_json(metadata_path, row)
            segment_results.append(row)
            segment_by_job_id[row["job_id"]] = row

        segment_specs = {row["segment_id"]: row for script in plan["scripts"] for row in script["modes"][mode]["segments"]}
        for candidate in plan["candidates"][mode]:
            audio_path = plan_root / Path(*PurePosixPath(candidate["audio_relative_path"]).parts)
            metadata_path = plan_root / Path(*PurePosixPath(candidate["metadata_relative_path"]).parts)
            audio_path.parent.mkdir(parents=True, exist_ok=True)
            parts = [segment_by_job_id[job_id] for job_id in candidate["segment_job_ids"]]
            failed_parts = [part["job_id"] for part in parts if part["status"] != "pass"]
            reasons = [f"segment_failed:{job_id}" for job_id in failed_parts]
            assembly_seconds = 0.0
            timeline: list[dict[str, Any]] = []
            if not failed_parts:
                assembly_started = time.perf_counter()
                try:
                    duration, timeline = _assemble_candidate(
                        parts,
                        segment_specs,
                        audio_path,
                        plan_root=plan_root,
                        seed=int(candidate["seed"]),
                    )
                except Exception as exc:
                    duration = None
                    reasons.append(f"assembly_exception:{type(exc).__name__}")
                assembly_seconds = time.perf_counter() - assembly_started
            else:
                duration = None
            status = "fail" if reasons else "pass"
            validations = _validator_rows(audio_path if audio_path.is_file() else None, mode=mode)
            row = {
                "candidate_id": candidate["candidate_id"],
                "script_id": candidate["script_id"],
                "mode": mode,
                "seed": candidate["seed"],
                "status": status,
                "failure_reasons": reasons,
                "audio_relative_path": candidate["audio_relative_path"] if audio_path.is_file() else None,
                "audio_sha256": sha256_file(audio_path) if audio_path.is_file() else None,
                "duration_seconds": duration,
                "generation_seconds": round(sum(float(part["generation_seconds"]) for part in parts), 6),
                "assembly_seconds": round(assembly_seconds, 6),
                "actual_text_tokens": sum(int(part["actual_text_tokens"] or 0) for part in parts),
                "segment_job_ids": list(candidate["segment_job_ids"]),
                "timeline": timeline,
                "signals": {
                    "hallucination": "not_run",
                    "repetition": "not_run",
                    "speaker_drift": "not_run",
                    "abnormal_silence": "not_run",
                },
                "validations": validations,
            }
            _write_exclusive_json(metadata_path, row)
            results.append(row)
            validators_by_mode[mode].append(
                {
                    "candidate_id": row["candidate_id"],
                    "generation_status": row["status"],
                    "validations": row["validations"],
                }
            )

    payload = {
        "schema_version": RESULT_SCHEMA_VERSION,
        "experiment_id": plan["experiment_id"],
        "plan_sha256": sha256_file(plan_file),
        "generation": plan["generation"],
        "production_pipeline_changed": False,
        "production_cache_changed": False,
        "production_selection_changed": False,
        "promotion_performed": False,
        "segment_results": segment_results,
        "results": results,
    }
    result_path = plan_root / "generation_results.json"
    _write_exclusive_json(result_path, payload)
    validator_root = plan_root / "validator_results"
    validator_root.mkdir(exist_ok=False)
    for mode in MODES:
        _write_exclusive_json(
            validator_root / f"{mode}.json",
            {
                "schema_version": VALIDATOR_BUNDLE_SCHEMA_VERSION,
                "experiment_id": plan["experiment_id"],
                "mode": mode,
                "results": validators_by_mode[mode],
            },
        )
    return result_path


class _ChatterboxGenerator:
    def __init__(self, plan: Mapping[str, Any], repository: Path) -> None:
        runtime_src = repository / "engine" / "chatterbox-v3" / "chatterbox" / "src"
        if str(runtime_src) not in sys.path:
            sys.path.insert(0, str(runtime_src))
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        import torch
        import torchaudio
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS, punc_norm

        self._torch = torch
        self._torchaudio = torchaudio
        self._punc_norm = punc_norm
        self._model = ChatterboxMultilingualTTS.from_pretrained(device="cpu", t3_model="v3")
        self._reference = repository / REFERENCE_RELATIVE_PATH
        self._model.prepare_conditionals(str(self._reference), exaggeration=0.5)
        if plan["generation"]["parameters"] != FIXED_GENERATION_PARAMETERS:
            raise ValueError("fixed generation parameters changed")

    def generate(self, job: Mapping[str, Any], audio_path: Path) -> dict[str, Any]:
        text = str(job["text"])
        normalized = self._punc_norm(text)
        tokens = self._model.tokenizer.text_to_tokens(normalized, language_id="ko")
        actual_text_tokens = int(tokens.numel()) + 2
        if actual_text_tokens > MODEL_MAX_TEXT_TOKENS:
            raise ValueError("actual tokenizer count exceeds pinned model limit")
        self._torch.manual_seed(int(job["seed"]))
        params = FIXED_GENERATION_PARAMETERS
        wav = self._model.generate(
            text,
            language_id=params["language_id"],
            exaggeration=params["exaggeration"],
            cfg_weight=params["cfg_weight"],
            temperature=params["temperature"],
            repetition_penalty=params["repetition_penalty"],
            min_p=params["min_p"],
            top_p=params["top_p"],
        )
        sample_rate = int(self._model.sr)
        duration = float(wav.shape[-1]) / sample_rate
        partial = audio_path.with_name(f".{audio_path.name}.partial.wav")
        if audio_path.exists() or partial.exists():
            raise FileExistsError(f"candidate path already exists: {audio_path}")
        try:
            self._torchaudio.save(
                str(partial),
                wav.detach().cpu(),
                sample_rate,
                encoding="PCM_S",
                bits_per_sample=16,
            )
            partial.replace(audio_path)
        except Exception:
            partial.unlink(missing_ok=True)
            raise
        return {
            "duration_seconds": duration,
            "actual_text_tokens": actual_text_tokens,
            "sample_rate_hz": sample_rate,
        }


def _default_generator_factory(plan: Mapping[str, Any], repository: Path) -> _ChatterboxGenerator:
    return _ChatterboxGenerator(plan, repository)


def _assemble_candidate(
    parts: list[Mapping[str, Any]],
    segment_specs: Mapping[str, Mapping[str, Any]],
    output_path: Path,
    *,
    plan_root: Path,
    seed: int,
) -> tuple[float, list[dict[str, Any]]]:
    """Assemble PCM16 segments with the current production pause/fade constants."""
    if output_path.exists():
        raise FileExistsError(f"candidate assembly already exists: {output_path}")
    rng = random.Random(seed)
    combined: list[float] = []
    timeline: list[dict[str, Any]] = []
    sample_rate: int | None = None
    for index, part in enumerate(parts):
        source = plan_root / Path(*PurePosixPath(str(part["audio_relative_path"])).parts)
        with wave.open(str(source), "rb") as reader:
            if reader.getnchannels() != 1 or reader.getsampwidth() != 2 or reader.getcomptype() != "NONE":
                raise ValueError("assembly requires mono PCM16 WAV segments")
            current_rate = reader.getframerate()
            raw = reader.readframes(reader.getnframes())
        if sample_rate is None:
            sample_rate = current_rate
        elif current_rate != sample_rate:
            raise ValueError("segment sample rates must match")
        values = [sample / 32768.0 for sample in struct.unpack(f"<{len(raw) // 2}h", raw)]
        fade_frames = min(len(values) // 2, max(1, round(ASSEMBLY_POLICY["fade_seconds"] * sample_rate)))
        for frame in range(fade_frames):
            gain = frame / max(1, fade_frames - 1)
            values[frame] *= gain
            values[-frame - 1] *= gain
        rms = math.sqrt(sum(value * value for value in values) / len(values)) if values else 0.0
        target_rms = 10 ** (float(ASSEMBLY_POLICY["target_rms_dbfs"]) / 20.0)
        if rms > 0:
            scale = target_rms / rms
            values = [value * scale for value in values]
        start_seconds = len(combined) / sample_rate
        combined.extend(values)
        spec = segment_specs[str(part["segment_id"])]
        timeline.append(
            {
                "segment_id": part["segment_id"],
                "text": part["text"],
                "start_seconds": round(start_seconds, 6),
                "duration_seconds": round(len(values) / sample_rate, 6),
                "sentence_final": bool(spec.get("sentence_final")),
                "forced": bool(spec.get("forced")),
            }
        )
        if index < len(parts) - 1:
            if spec.get("sentence_final"):
                low, high = ASSEMBLY_POLICY["sentence_final_pause_seconds"]
            elif spec.get("forced"):
                low, high = ASSEMBLY_POLICY["forced_clause_pause_seconds"]
            else:
                low, high = ASSEMBLY_POLICY["continuation_pause_seconds"]
            pause_frames = round(rng.uniform(float(low), float(high)) * sample_rate)
            combined.extend([0.0] * pause_frames)
    if sample_rate is None or not combined:
        raise ValueError("candidate assembly has no audio")
    peak = max(abs(value) for value in combined)
    peak_guard = float(ASSEMBLY_POLICY["peak_guard"])
    if peak > peak_guard:
        combined = [value * peak_guard / peak for value in combined]
    pcm = b"".join(struct.pack("<h", max(-32768, min(32767, round(value * 32767)))) for value in combined)
    partial = output_path.with_name(f".{output_path.name}.partial.wav")
    if partial.exists():
        raise FileExistsError(f"candidate assembly partial already exists: {partial}")
    try:
        with wave.open(str(partial), "wb") as writer:
            writer.setnchannels(1)
            writer.setsampwidth(2)
            writer.setframerate(sample_rate)
            writer.writeframes(pcm)
        partial.replace(output_path)
    except Exception:
        partial.unlink(missing_ok=True)
        raise
    return round(len(combined) / sample_rate, 6), timeline


def _validator_rows(audio_path: Path | None, *, mode: str) -> list[dict[str, Any]]:
    rows: list[ValidationResult] = []
    if audio_path is not None:
        rows.append(AudioSanityValidator().validate(audio_path))
    else:
        rows.append(
            ValidationResult(
                "audio_sanity",
                "audio-sanity/not-run/1",
                ValidationStatus.NOT_RUN,
                True,
                reasons=["audio_not_available"],
            )
        )
    for name, hard_gate in (
        ("content_accuracy", True),
        ("speaker_similarity", True),
        ("existing_prosody_gates", True),
        ("phrase_transition", False),
        ("boundary_alignment", False),
    ):
        reason = (
            "validator_requires_explicit_post_generation_integration"
            if name != "boundary_alignment" or mode == "sentence"
            else "not_applicable_outside_sentence_mode"
        )
        rows.append(
            ValidationResult(
                name,
                f"{name}/integration-not-run/1",
                ValidationStatus.NOT_RUN,
                hard_gate,
                reasons=[reason],
            )
        )
    return [row.to_dict() for row in rows]


def _job_identity(job: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "job_id": job["job_id"],
        "candidate_id": job["candidate_id"],
        "script_id": job["script_id"],
        "mode": job["mode"],
        "segment_id": job["segment_id"],
        "seed": job["seed"],
        "text": job["text"],
    }


def _load_plan(plan_or_path: Mapping[str, Any] | str | Path, repository: Path) -> tuple[dict[str, Any], Path]:
    if isinstance(plan_or_path, Mapping):
        plan = dict(plan_or_path)
        plan_root = assert_isolated_experiment_root(plan.get("output_root", ""), repository)
        return plan, plan_root
    plan_path = Path(plan_or_path).resolve()
    return load_plan_bundle(plan_path), plan_path.parent


def _safe_relative_path(value: Any, suffix: str) -> PurePosixPath | None:
    text = str(value or "").replace("\\", "/")
    path = PurePosixPath(text)
    if not text or path.is_absolute() or ".." in path.parts or path.suffix.lower() != suffix:
        return None
    return path


def _verify_reference(repository: Path) -> None:
    path = repository / REFERENCE_RELATIVE_PATH
    if not path.is_file() or sha256_file(path).lower() != REFERENCE_SHA256:
        raise ValueError("Candidate B reference path or hash mismatch")


def _write_exclusive_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(encoded)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]
