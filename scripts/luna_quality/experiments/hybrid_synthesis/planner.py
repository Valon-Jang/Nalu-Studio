"""Deterministic, production-isolated planning for the S09 comparison.

The planner intentionally does not import Chatterbox or create audio.  Its
conservative UTF-8 token upper bound is checked against the limits read from
the pinned runtime.  The integration runner repeats the check with the real
tokenizer before any model call.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from ...hashing import sha256_file, sha256_text

INPUT_SCHEMA_VERSION = "luna-hybrid-input/1"
PLAN_SCHEMA_VERSION = "luna-hybrid-plan/1"
JOB_SCHEMA_VERSION = "luna-hybrid-jobs/1"
MODES = ("existing_phrase", "sentence", "hybrid")

REFERENCE_RELATIVE_PATH = "assets/voice_ref/B_voiced_spectral_micro_smooth.wav"
REFERENCE_SHA256 = "30c6d3405f46684af467c7d26ff40a2fb57dd48cc84cd24cf7403d9aa00a2bb9"
FIXED_GENERATION_PARAMETERS = {
    "engine": "Chatterbox Multilingual V3",
    "t3_model": "v3",
    "candidate": "B",
    "language_id": "ko",
    "exaggeration": 0.5,
    "cfg_weight": 0.5,
    "temperature": 0.72,
    "repetition_penalty": 1.2,
    "min_p": 0.05,
    "top_p": 1.0,
}
ASSEMBLY_POLICY = {
    "policy_version": "s09-production-pause-mirror/1",
    "fade_seconds": 0.012,
    "target_rms_dbfs": -20.0,
    "peak_guard": 0.89,
    "continuation_pause_seconds": [0.0, 0.02],
    "forced_clause_pause_seconds": [0.05, 0.10],
    "sentence_final_pause_seconds": [0.38, 0.60],
    "source": "scripts/luna_narration_pipeline_v1.py:53-57,547-582",
}

# Values verified from the repository-pinned Chatterbox runtime in S09.
MODEL_MAX_TEXT_TOKENS = 2048
TEXT_FRAMING_TOKENS = 2
RUNTIME_MAX_NEW_SPEECH_TOKENS = 1000
MODEL_MAX_SPEECH_TOKENS = 4096
SPEECH_TOKEN_RATE_HZ = 25
RUNTIME_MAX_AUDIO_SECONDS = (RUNTIME_MAX_NEW_SPEECH_TOKENS - 1) / SPEECH_TOKEN_RATE_HZ
EXPERIMENT_MAX_ESTIMATED_AUDIO_SECONDS = 32.0
CONSERVATIVE_MIN_AUDIBLE_CHARS_PER_SECOND = 4.0
HYBRID_SOFT_AUDIBLE_CHAR_LIMIT = 80

RUNTIME_LIMIT_SOURCES = (
    "engine/chatterbox-v3/chatterbox/src/chatterbox/mtl_tts.py",
    "engine/chatterbox-v3/chatterbox/src/chatterbox/models/t3/modules/t3_config.py",
    "engine/chatterbox-v3/chatterbox/src/chatterbox/models/s3tokenizer/s3tokenizer.py",
)
ASSEMBLY_POLICY_SOURCE = "scripts/luna_narration_pipeline_v1.py"
KNOWN_FROZEN_PROJECT_IDS = ("SPIDER-001", "SUBSEA-001")

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
_SENTENCE = re.compile(r"[^.!?。！？\n]+(?:[.!?。！？]+|$)")
_CLAUSE_BOUNDARY = re.compile(r"[,;:，；：]\s*|(?:지만|는데|으며|하고|해서|라서|하면|다면)\s+")


def plan_experiment(
    payload: Mapping[str, Any],
    *,
    output_root: str,
    candidate_budget: int = 4,
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    """Return a deterministic three-mode plan without touching the filesystem."""
    _validate_input(payload)
    if not isinstance(candidate_budget, int) or isinstance(candidate_budget, bool) or candidate_budget < 1:
        raise ValueError("candidate_budget must be a positive integer")
    repository = Path(repo_root) if repo_root is not None else _repo_root()
    experiment_id = str(payload["experiment_id"])
    scripts: list[dict[str, Any]] = []
    mode_jobs: dict[str, list[dict[str, Any]]] = {mode: [] for mode in MODES}
    mode_candidates: dict[str, list[dict[str, Any]]] = {mode: [] for mode in MODES}

    for source in payload["scripts"]:
        prepared = _prepare_script(source)
        segments_by_mode = {
            "existing_phrase": _existing_segments(prepared),
            "sentence": _sentence_segments(prepared),
            "hybrid": _hybrid_segments(prepared),
        }
        script_plan = {
            "script_id": prepared["script_id"],
            "source_text": prepared["text"],
            "source_text_sha256": sha256_text(prepared["text"]),
            "base_seed": prepared["seed"],
            "modes": {},
        }
        for mode in MODES:
            segments = segments_by_mode[mode]
            jobs: list[dict[str, Any]] = []
            candidates: list[dict[str, Any]] = []
            for candidate_index in range(candidate_budget):
                candidate_id = f"{prepared['script_id']}.{mode}.c{candidate_index:03d}"
                job_ids: list[str] = []
                for segment_index, segment in enumerate(segments):
                    job_id = f"{candidate_id}.s{segment_index:03d}"
                    wav_path = f"segments/{mode}/{prepared['script_id']}/{candidate_id}/{job_id}.wav"
                    jobs.append(
                        {
                            "job_id": job_id,
                            "candidate_id": candidate_id,
                            "candidate_index": candidate_index,
                            "script_id": prepared["script_id"],
                            "mode": mode,
                            "segment_id": segment["segment_id"],
                            "segment_index": segment_index,
                            "text": segment["text"],
                            "seed": derive_seed(prepared["seed"], candidate_index, segment_index),
                            "execution_eligible": segment["safety_status"] == "pass",
                            "audio_relative_path": wav_path,
                            "metadata_relative_path": wav_path[:-4] + ".json",
                        }
                    )
                    job_ids.append(job_id)
                candidate_wav = f"candidates/{mode}/{prepared['script_id']}/{candidate_id}.wav"
                candidates.append(
                    {
                        "candidate_id": candidate_id,
                        "candidate_index": candidate_index,
                        "script_id": prepared["script_id"],
                        "mode": mode,
                        "seed": derive_seed(prepared["seed"], candidate_index, 0),
                        "segment_job_ids": job_ids,
                        "audio_relative_path": candidate_wav,
                        "metadata_relative_path": candidate_wav[:-4] + ".json",
                    }
                )
            mode_jobs[mode].extend(jobs)
            mode_candidates[mode].extend(candidates)
            script_plan["modes"][mode] = {
                "segments": segments,
                "candidate_budget": candidate_budget,
                "candidate_count": len(candidates),
                "generation_job_count": len(jobs),
                "status": "pass" if all(s["safety_status"] == "pass" for s in segments) else "fail",
            }
            if mode == "sentence":
                script_plan["modes"][mode]["post_generation_boundary_extraction"] = {
                    "required": True,
                    "methods": ["asr", "forced_alignment"],
                    "target_phrase_texts": [str(item["text"]).strip() for item in prepared["existing_phrases"]],
                    "default_status": "not_run",
                }
        scripts.append(script_plan)

    canonical_input = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    provenance = _runtime_provenance(repository)
    return {
        "schema_version": PLAN_SCHEMA_VERSION,
        "experiment_id": experiment_id,
        "input_schema_version": payload["schema_version"],
        "input_sha256": sha256_text(canonical_input),
        "output_root": str(output_root).replace("\\", "/").rstrip("/"),
        "production_isolation": {
            "frozen_project_excluded": True,
            "production_pipeline_changed": False,
            "production_cache_changed": False,
            "promotion_permitted": False,
        },
        "fairness": {
            "same_script_set": True,
            "same_candidate_reference": True,
            "same_fixed_generation_parameters": True,
            "same_candidate_budget_per_script_and_mode": candidate_budget,
            "candidate_unit": "complete_script_assembly",
            "generation_job_count_varies_only_with_mode_segmentation": True,
            "same_seed_derivation": "base+104729*candidate_index+7919*segment_index modulo 2147483647",
        },
        "generation": {
            "reference_voice": {"path": REFERENCE_RELATIVE_PATH, "sha256": REFERENCE_SHA256},
            "parameters": dict(FIXED_GENERATION_PARAMETERS),
            "assembly_policy": dict(ASSEMBLY_POLICY),
        },
        "safety_limits": _safety_limits(),
        "runtime_provenance": provenance,
        "scripts": scripts,
        "job_manifests": {mode: f"jobs/{mode}.jobs.json" for mode in MODES},
        "jobs": mode_jobs,
        "candidates": mode_candidates,
    }


def write_plan_bundle(
    payload: Mapping[str, Any],
    output_root: str | Path,
    *,
    candidate_budget: int = 4,
    repo_root: str | Path | None = None,
) -> Path:
    """Create a new isolated experiment root and write plan plus per-mode jobs."""
    repository = (Path(repo_root) if repo_root is not None else _repo_root()).resolve()
    root = assert_isolated_experiment_root(output_root, repository)
    if root.exists():
        raise FileExistsError(f"experiment output already exists: {root}")
    relative_root = root.relative_to(repository).as_posix()
    plan = plan_experiment(payload, output_root=relative_root, candidate_budget=candidate_budget, repo_root=repository)
    root.mkdir(parents=True, exist_ok=False)
    jobs_dir = root / "jobs"
    jobs_dir.mkdir()
    _write_exclusive_json(root / "segmentation_plan.json", _plan_without_inline_jobs(plan))
    for mode in MODES:
        _write_exclusive_json(
            jobs_dir / f"{mode}.jobs.json",
            {
                "schema_version": JOB_SCHEMA_VERSION,
                "plan_schema_version": PLAN_SCHEMA_VERSION,
                "experiment_id": plan["experiment_id"],
                "mode": mode,
                "candidate_budget_per_script": candidate_budget,
                "generation": plan["generation"],
                "safety_limits": plan["safety_limits"],
                "jobs": plan["jobs"][mode],
                "candidates": plan["candidates"][mode],
            },
        )
    return root / "segmentation_plan.json"


def load_plan_bundle(plan_path: str | Path) -> dict[str, Any]:
    path = Path(plan_path)
    plan = json.loads(path.read_text(encoding="utf-8"))
    if plan.get("schema_version") != PLAN_SCHEMA_VERSION:
        raise ValueError("unsupported hybrid plan schema")
    jobs: dict[str, list[dict[str, Any]]] = {}
    candidates: dict[str, list[dict[str, Any]]] = {}
    for mode in MODES:
        relative = plan.get("job_manifests", {}).get(mode)
        if not relative:
            raise ValueError(f"missing job manifest for {mode}")
        manifest = json.loads((path.parent / relative).read_text(encoding="utf-8"))
        if manifest.get("schema_version") != JOB_SCHEMA_VERSION or manifest.get("mode") != mode:
            raise ValueError(f"invalid job manifest for {mode}")
        jobs[mode] = list(manifest.get("jobs") or [])
        candidates[mode] = list(manifest.get("candidates") or [])
    plan["jobs"] = jobs
    plan["candidates"] = candidates
    return plan


def assert_isolated_experiment_root(output_root: str | Path, repo_root: str | Path) -> Path:
    repository = Path(repo_root).resolve()
    root = Path(output_root)
    if not root.is_absolute():
        root = repository / root
    root = root.resolve()
    anchor = (repository / "experiments" / "luna_quality").resolve()
    try:
        relative = root.relative_to(anchor)
    except ValueError as exc:
        raise ValueError("output root must stay under experiments/luna_quality") from exc
    if relative == Path(".") or not relative.parts:
        raise ValueError("output root must be a child experiment directory")
    return root


def derive_seed(base_seed: int, segment_index: int, take_index: int) -> int:
    return (int(base_seed) + 104729 * int(segment_index) + 7919 * int(take_index)) % 2147483647


def _validate_input(payload: Mapping[str, Any]) -> None:
    if payload.get("schema_version") != INPUT_SCHEMA_VERSION:
        raise ValueError(f"schema_version must be {INPUT_SCHEMA_VERSION}")
    experiment_id = str(payload.get("experiment_id") or "")
    if not _SAFE_ID.fullmatch(experiment_id):
        raise ValueError("experiment_id must be filesystem-safe")
    if payload.get("frozen_project") is not False:
        raise ValueError("frozen_project must explicitly be false")
    source_project_id = str(payload.get("source_project_id") or "").upper()
    if source_project_id in KNOWN_FROZEN_PROJECT_IDS:
        raise ValueError(f"frozen project is excluded from S09: {source_project_id}")
    scripts = payload.get("scripts")
    if not isinstance(scripts, list) or not scripts:
        raise ValueError("scripts must be a non-empty list")
    seen: set[str] = set()
    for row in scripts:
        if not isinstance(row, Mapping):
            raise ValueError("each script must be an object")
        script_id = str(row.get("script_id") or "")
        if not _SAFE_ID.fullmatch(script_id) or script_id in seen:
            raise ValueError("script_id values must be unique and filesystem-safe")
        seen.add(script_id)
        text = str(row.get("text") or "").strip()
        phrases = row.get("existing_phrases")
        if not text or not isinstance(phrases, list) or not phrases:
            raise ValueError(f"{script_id} requires text and existing_phrases")
        if isinstance(row.get("seed"), bool) or not isinstance(row.get("seed"), int):
            raise ValueError(f"{script_id} requires an integer seed")
        phrase_texts = [str(item.get("text") or "").strip() for item in phrases if isinstance(item, Mapping)]
        if len(phrase_texts) != len(phrases) or any(not item for item in phrase_texts):
            raise ValueError(f"{script_id} existing phrases require non-empty text")
        if _compact("".join(phrase_texts)) != _compact(text):
            raise ValueError(f"{script_id} existing phrases must cover exactly the same script text")


def _prepare_script(source: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "script_id": str(source["script_id"]),
        "text": str(source["text"]).strip(),
        "seed": int(source["seed"]),
        "existing_phrases": [dict(item) for item in source["existing_phrases"]],
    }


def _existing_segments(script: Mapping[str, Any]) -> list[dict[str, Any]]:
    result = _segments(
        script["script_id"],
        "existing_phrase",
        [str(item["text"]).strip() for item in script["existing_phrases"]],
        strategy="provided_existing_phrase",
    )
    for segment, source in zip(result, script["existing_phrases"]):
        segment["forced"] = bool(source.get("forced", False))
        if "sentence_final" in source:
            segment["sentence_final"] = bool(source["sentence_final"])
    return result


def _sentence_segments(script: Mapping[str, Any]) -> list[dict[str, Any]]:
    texts = _split_sentences(script["text"])
    return _segments(script["script_id"], "sentence", texts, strategy="whole_sentence")


def _hybrid_segments(script: Mapping[str, Any]) -> list[dict[str, Any]]:
    texts: list[str] = []
    fallback_reason: str | None = None
    for sentence in _split_sentences(script["text"]):
        if _audible_chars(sentence) <= HYBRID_SOFT_AUDIBLE_CHAR_LIMIT and _safety(sentence)[0] == "pass":
            texts.append(sentence)
            continue
        clauses = _semantic_clauses(sentence)
        if len(clauses) < 2 or any(_safety(clause)[0] != "pass" for clause in clauses):
            fallback_reason = "semantic_split_unavailable_or_safety_limit"
            break
        texts.extend(clauses)
    if fallback_reason:
        result = _existing_segments(script)
        for row in result:
            row["mode"] = "hybrid"
            row["segment_id"] = row["segment_id"].replace(".existing_phrase.", ".hybrid.")
            row["strategy"] = "existing_phrase_fallback"
            row["fallback_reason"] = fallback_reason
        return result
    return _segments(script["script_id"], "hybrid", texts, strategy="sentence_or_semantic_clause")


def _segments(script_id: str, mode: str, texts: Sequence[str], *, strategy: str) -> list[dict[str, Any]]:
    result = []
    for index, text in enumerate(texts):
        status, reasons, token_upper, estimated_seconds = _safety(text)
        result.append(
            {
                "segment_id": f"{script_id}.{mode}.s{index:03d}",
                "script_id": script_id,
                "mode": mode,
                "segment_index": index,
                "text": text,
                "text_sha256": sha256_text(text),
                "strategy": strategy,
                "sentence_final": bool(re.search(r"[.!?。！？]+$", text.strip())),
                "forced": strategy == "sentence_or_semantic_clause" and not bool(re.search(r"[.!?。！？]+$", text.strip())),
                "conservative_text_token_upper_bound": token_upper,
                "estimated_audio_seconds": estimated_seconds,
                "safety_status": status,
                "safety_reasons": reasons,
            }
        )
    return result


def _safety(text: str) -> tuple[str, list[str], int, float]:
    token_upper = len(text.encode("utf-8")) + TEXT_FRAMING_TOKENS
    estimated_seconds = round(max(0.25, _audible_chars(text) / CONSERVATIVE_MIN_AUDIBLE_CHARS_PER_SECOND), 3)
    reasons: list[str] = []
    if token_upper > MODEL_MAX_TEXT_TOKENS:
        reasons.append("conservative_text_token_upper_bound_exceeded")
    if estimated_seconds > EXPERIMENT_MAX_ESTIMATED_AUDIO_SECONDS:
        reasons.append("experiment_audio_safety_margin_exceeded")
    return ("fail" if reasons else "pass", reasons, token_upper, estimated_seconds)


def _split_sentences(text: str) -> list[str]:
    result = [match.group(0).strip() for match in _SENTENCE.finditer(text) if match.group(0).strip()]
    if not result or _compact("".join(result)) != _compact(text):
        return [text.strip()]
    return result


def _semantic_clauses(sentence: str) -> list[str]:
    pieces: list[str] = []
    start = 0
    for match in _CLAUSE_BOUNDARY.finditer(sentence):
        piece = sentence[start : match.end()].strip()
        if piece:
            pieces.append(piece)
        start = match.end()
    tail = sentence[start:].strip()
    if tail:
        pieces.append(tail)
    if len(pieces) < 2:
        return [sentence.strip()]
    grouped: list[str] = []
    current = ""
    for piece in pieces:
        combined = f"{current} {piece}".strip()
        if current and _audible_chars(combined) > HYBRID_SOFT_AUDIBLE_CHAR_LIMIT:
            grouped.append(current)
            current = piece
        else:
            current = combined
    if current:
        grouped.append(current)
    return grouped if _compact("".join(grouped)) == _compact(sentence) else [sentence.strip()]


def _safety_limits() -> dict[str, Any]:
    return {
        "model_max_text_tokens": MODEL_MAX_TEXT_TOKENS,
        "text_framing_tokens": TEXT_FRAMING_TOKENS,
        "runtime_max_new_speech_tokens": RUNTIME_MAX_NEW_SPEECH_TOKENS,
        "model_config_max_speech_tokens": MODEL_MAX_SPEECH_TOKENS,
        "speech_token_rate_hz": SPEECH_TOKEN_RATE_HZ,
        "runtime_max_audio_seconds_after_terminal_token_drop": RUNTIME_MAX_AUDIO_SECONDS,
        "experiment_max_estimated_audio_seconds": EXPERIMENT_MAX_ESTIMATED_AUDIO_SECONDS,
        "dry_run_token_method": "utf8_byte_count_plus_framing_conservative_upper_bound",
        "integration_token_method": "actual_pinned_chatterbox_tokenizer_plus_framing",
        "integration_overflow_policy": "fail_without_generation",
    }


def _runtime_provenance(repository: Path) -> dict[str, Any]:
    reference = repository / REFERENCE_RELATIVE_PATH
    if not reference.is_file():
        raise FileNotFoundError(f"Candidate B reference missing: {reference}")
    actual_reference_hash = sha256_file(reference)
    if actual_reference_hash.lower() != REFERENCE_SHA256:
        raise ValueError("Candidate B reference hash mismatch")
    hashes: dict[str, str] = {REFERENCE_RELATIVE_PATH: actual_reference_hash.lower()}
    for relative in RUNTIME_LIMIT_SOURCES:
        path = repository / relative
        if not path.is_file():
            raise FileNotFoundError(f"runtime limit source missing: {path}")
        hashes[relative] = sha256_file(path)
    assembly_source = repository / ASSEMBLY_POLICY_SOURCE
    if not assembly_source.is_file():
        raise FileNotFoundError(f"assembly policy source missing: {assembly_source}")
    hashes[ASSEMBLY_POLICY_SOURCE] = sha256_file(assembly_source)
    return {"source_hashes": hashes, "limits_verified_from_pinned_runtime": True}


def _plan_without_inline_jobs(plan: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in plan.items() if key not in {"jobs", "candidates"}}


def _write_exclusive_json(path: Path, payload: Mapping[str, Any]) -> None:
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(encoded)


def _audible_chars(text: str) -> int:
    return len(re.sub(r"[\s\W_]", "", text, flags=re.UNICODE))


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]
