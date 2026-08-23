"""Read existing Luna take directories and produce a shadow-only recommendation."""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections import defaultdict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..contracts import ValidationResult, ValidationStatus
from ..hashing import sha256_file, sha256_text
from ..ranking.artifact import ArtifactLoadResult, load_artifact
from ..validators.audio_sanity import AudioSanityValidator
from .policy import (
    POLICY_VERSION,
    ShadowPolicy,
    disagreement_reasons,
    exception_result,
    existing_quality_score,
    hard_gate_survives,
    imported_prosody_result,
    not_run_result,
    ranking_features,
)

TAKE_NAME = re.compile(r"P(?P<phrase>\d+)_t(?P<take>\d+)\.json$", re.IGNORECASE)
REPORT_SCHEMA_VERSION = "luna-shadow-report/1"
Runner = Callable[["DiscoveredTake"], ValidationResult]


@dataclass(frozen=True)
class DiscoveredTake:
    block_id: str
    phrase_index: int
    take_id: int
    row: dict[str, Any]
    json_path: Path
    wav_path: Path
    phrase_metadata: dict[str, Any]


@dataclass(frozen=True)
class ShadowRunResult:
    report: dict[str, Any]
    read_only_verified: bool


class ShadowOrchestrator:
    """Runs validators independently; never writes to the source take directory."""

    def __init__(
        self,
        *,
        audio_validator: AudioSanityValidator | None = None,
        content_runner: Runner | None = None,
        speaker_runner: Runner | None = None,
        mos_runner: Runner | None = None,
        ranker_artifact: str | Path | None = None,
        policy: ShadowPolicy | None = None,
    ) -> None:
        self.audio_validator = audio_validator or AudioSanityValidator()
        self.content_runner = content_runner
        self.speaker_runner = speaker_runner
        self.mos_runner = mos_runner
        self.ranker_artifact = Path(ranker_artifact) if ranker_artifact else None
        self.policy = policy or ShadowPolicy()

    def evaluate(self, outdir: str | Path) -> ShadowRunResult:
        source = Path(outdir).resolve()
        if not source.is_dir():
            raise ValueError("outdir must be an existing directory")
        before = _tree_manifest(source)
        started = time.perf_counter()
        discovered, discovery_errors, selection_map = _discover(source)
        ranker = self._load_ranker()
        grouped: dict[tuple[str, int], list[DiscoveredTake]] = defaultdict(list)
        for take in discovered:
            grouped[(take.block_id, take.phrase_index)].append(take)

        blocks: list[dict[str, Any]] = []
        for block_id in sorted({block for block, _ in grouped}):
            phrase_reports: list[dict[str, Any]] = []
            for _, phrase_index in sorted((key for key in grouped if key[0] == block_id), key=lambda item: item[1]):
                phrase_reports.append(
                    self._evaluate_phrase(
                        block_id,
                        phrase_index,
                        sorted(grouped[(block_id, phrase_index)], key=lambda take: take.take_id),
                        selection_map.get((block_id, phrase_index)),
                        ranker,
                    )
                )
            blocks.append({"block_id": block_id, "phrases": phrase_reports})

        after = _tree_manifest(source)
        read_only_verified = before == after
        report = {
            "schema_version": REPORT_SCHEMA_VERSION,
            "mode": "shadow",
            "production_selection_changed": False,
            "input": {
                "outdir": str(source),
                "file_count": before["file_count"],
                "source_manifest_sha256": before["manifest_sha256"],
                "read_only_verified": read_only_verified,
            },
            "policy": {"version": POLICY_VERSION, "config_hash": self.policy.config_hash},
            "capabilities": self._capabilities(ranker),
            "discovery_errors": discovery_errors,
            "blocks": blocks,
            "execution_duration_seconds": round(time.perf_counter() - started, 6),
        }
        return ShadowRunResult(report, read_only_verified)

    def _evaluate_phrase(
        self,
        block_id: str,
        phrase_index: int,
        takes: list[DiscoveredTake],
        actual_selection: dict[str, Any] | None,
        ranker: ArtifactLoadResult,
    ) -> dict[str, Any]:
        candidates = [self._evaluate_take(take) for take in takes]
        survivors = [candidate for candidate in candidates if candidate["hard_gate_pass"]]
        ranking_mode = "preference_ranker" if ranker.ranker else "existing_quality_score"
        if ranker.ranker:
            raw = ranker.ranker.rank_candidates(survivors)
            scored = {item["take_id"]: item for item in raw["results"] if item["status"] == "ranked"}
            for candidate in candidates:
                result = scored.get(candidate["take_id"])
                candidate["rank_score"] = result["score"] if result else None
                candidate["rank_model_version"] = ranker.ranker.model_version if result else None
            ordered_survivors = sorted(survivors, key=lambda item: (-_sort_score(item["rank_score"]), item["take_id"]))
            ranker_detail = {"status": raw["status"], "top_confidence": raw["top_confidence"], "candidate_reduction_allowed": raw["candidate_reduction_allowed"]}
        else:
            for candidate in candidates:
                candidate["rank_score"] = candidate["existing_quality_score"] if candidate["hard_gate_pass"] else None
                candidate["rank_model_version"] = None
            ordered_survivors = sorted(survivors, key=lambda item: (-_sort_score(item["rank_score"]), item["take_id"]))
            ranker_detail = {"status": "disabled", "reason": ranker.reason}

        for position, candidate in enumerate(ordered_survivors, 1):
            candidate["shadow_rank"] = position
        selected_take = actual_selection.get("take_id") if actual_selection else None
        actual = next((candidate for candidate in candidates if candidate["take_id"] == selected_take), None)
        recommendation = ordered_survivors[0] if ordered_survivors else None
        agreement = actual is not None and recommendation is not None and actual["take_id"] == recommendation["take_id"]
        return {
            "phrase_id": f"P{phrase_index:02d}",
            "actual_selection": actual_selection,
            "actual_selected_take": selected_take,
            "ranking_mode": ranking_mode,
            "ranker": ranker_detail,
            "hard_gate_survivor_take_ids": [candidate["take_id"] for candidate in ordered_survivors],
            "shadow_top_1": recommendation["take_id"] if recommendation else None,
            "shadow_top_3": [candidate["take_id"] for candidate in ordered_survivors[:3]],
            "agreement": agreement if actual_selection else None,
            "disagreement_reasons": [] if agreement else disagreement_reasons(actual, recommendation),
            "takes": candidates,
        }

    def _evaluate_take(self, take: DiscoveredTake) -> dict[str, Any]:
        validations = [
            self._safe_audio(take),
            self._safe_runner("content_asr", self.content_runner, take, hard_gate=True, unavailable_reason="asr_not_configured"),
            self._safe_runner("speaker_identity", self.speaker_runner, take, hard_gate=True, unavailable_reason="speaker_not_configured"),
            imported_prosody_result(take.row),
            self._safe_runner("mos", self.mos_runner, take, hard_gate=False, unavailable_reason="mos_not_configured"),
        ]
        survives = hard_gate_survives(validations)
        features = ranking_features(take.row, validations)
        score = existing_quality_score(
            take.row,
            sentence_final=bool(take.phrase_metadata.get("sentence_final", False)),
            forced=bool(take.phrase_metadata.get("forced", False)),
            policy=self.policy,
        )
        return {
            "take_id": take.take_id,
            "seed": take.row.get("seed"),
            "text": take.row.get("text", ""),
            "text_sha256": sha256_text(str(take.row.get("text") or "")),
            "source": {"take_json_sha256": sha256_file(take.json_path), "take_wav_path": str(take.wav_path)},
            "validations": [_validation_dict(item) for item in validations],
            "hard_gate_pass": survives,
            "hard_gate_status": "survives" if survives else "fail",
            "existing_prosody_metrics": dict(take.row.get("metrics") or {}),
            "ranking_features": features,
            "existing_quality_score": score,
            "rank_score": None,
            "rank_model_version": None,
            "shadow_rank": None,
        }

    def _safe_audio(self, take: DiscoveredTake) -> ValidationResult:
        try:
            return self.audio_validator.validate(take.wav_path)
        except Exception as exc:  # an input-specific validator error remains explicit
            return exception_result("audio_sanity", exc, hard_gate=True)

    @staticmethod
    def _safe_runner(
        validator_name: str, runner: Runner | None, take: DiscoveredTake, *, hard_gate: bool, unavailable_reason: str
    ) -> ValidationResult:
        if runner is None:
            return not_run_result(validator_name, unavailable_reason, hard_gate)
        try:
            result = runner(take)
        except Exception as exc:
            return exception_result(validator_name, exc, hard_gate)
        if not isinstance(result, ValidationResult):
            return exception_result(validator_name, TypeError("runner must return ValidationResult"), hard_gate)
        return result

    def _load_ranker(self) -> ArtifactLoadResult:
        if self.ranker_artifact is None:
            return ArtifactLoadResult("disabled", None, {}, "ranker_not_configured")
        return load_artifact(self.ranker_artifact)

    def _capabilities(self, ranker: ArtifactLoadResult) -> dict[str, Any]:
        artifact_hash = sha256_file(self.ranker_artifact) if self.ranker_artifact and self.ranker_artifact.is_file() else None
        return {
            "audio_sanity": {"status": "pass", "validator_version": self.audio_validator.validator_version},
            "content_asr": {"status": "configured" if self.content_runner else "not_run"},
            "speaker_identity": {"status": "configured" if self.speaker_runner else "not_run"},
            "mos": {"status": "configured" if self.mos_runner else "not_run"},
            "preference_ranker": {
                "status": ranker.status,
                "reason": ranker.reason,
                "artifact_sha256": artifact_hash,
                "model_id": ranker.metadata.get("metadata", {}).get("model_id") if ranker.metadata else None,
            },
        }


def _discover(source: Path) -> tuple[list[DiscoveredTake], list[dict[str, str]], dict[tuple[str, int], dict[str, Any]]]:
    errors: list[dict[str, str]] = []
    metadata_by_block: dict[str, dict[int, dict[str, Any]]] = {}
    selections = _actual_selections(source, errors)
    discovered: list[DiscoveredTake] = []
    for json_path in sorted(source.rglob("P*_t*.json"), key=lambda path: path.as_posix()):
        match = TAKE_NAME.match(json_path.name)
        if not match:
            continue
        block_id = json_path.parent.name
        phrase_index, take_id = int(match.group("phrase")), int(match.group("take"))
        if block_id not in metadata_by_block:
            metadata_by_block[block_id] = _phrase_metadata(json_path.parent, errors)
        try:
            row = json.loads(json_path.read_text(encoding="utf-8"))
            if not isinstance(row, dict):
                raise ValueError("take JSON must be an object")
        except (OSError, ValueError, TypeError) as exc:
            errors.append({"path": str(json_path), "error": f"take_json_error:{type(exc).__name__}"})
            continue
        discovered.append(
            DiscoveredTake(
                block_id,
                phrase_index,
                take_id,
                row,
                json_path,
                json_path.with_suffix(".wav"),
                metadata_by_block[block_id].get(phrase_index, {}),
            )
        )
    return discovered, sorted(errors, key=lambda item: (item["path"], item["error"])), selections


def _actual_selections(source: Path, errors: list[dict[str, str]]) -> dict[tuple[str, int], dict[str, Any]]:
    selected: dict[tuple[str, int], dict[str, Any]] = {}
    for path in sorted(source.glob("*_report.json"), key=lambda item: item.name):
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
            block_id = str(report["id"])
            for phrase_index, take_id in enumerate(report.get("picks", [])):
                selected[(block_id, phrase_index)] = {"take_id": int(take_id), "source": "block_report", "source_path": str(path)}
        except (OSError, ValueError, KeyError, TypeError) as exc:
            errors.append({"path": str(path), "error": f"block_report_error:{type(exc).__name__}"})
    for path in sorted(source.glob("*_pins.json"), key=lambda item: item.name):
        block_id = path.stem[:-5]
        try:
            pins = json.loads(path.read_text(encoding="utf-8"))
            for phrase, take_id in pins.items():
                match = re.fullmatch(r"P(\d+)", str(phrase))
                if match:
                    selected[(block_id, int(match.group(1)))] = {"take_id": int(take_id), "source": "pins", "source_path": str(path)}
        except (OSError, ValueError, TypeError) as exc:
            errors.append({"path": str(path), "error": f"pins_error:{type(exc).__name__}"})
    return selected


def _phrase_metadata(block_dir: Path, errors: list[dict[str, str]]) -> dict[int, dict[str, Any]]:
    path = block_dir / "phrases.json"
    if not path.is_file():
        return {}
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
        return {index: dict(row) for index, row in enumerate(rows) if isinstance(row, dict)}
    except (OSError, ValueError, TypeError) as exc:
        errors.append({"path": str(path), "error": f"phrases_error:{type(exc).__name__}"})
        return {}


def _tree_manifest(root: Path) -> dict[str, Any]:
    entries: list[str] = []
    for path in sorted((item for item in root.rglob("*") if item.is_file()), key=lambda item: item.as_posix()):
        relative = path.relative_to(root).as_posix()
        entries.append(f"{relative}:{sha256_file(path)}")
    digest = hashlib.sha256("\n".join(entries).encode("utf-8")).hexdigest()
    return {"file_count": len(entries), "manifest_sha256": digest}


def _validation_dict(result: ValidationResult) -> dict[str, Any]:
    value = result.to_dict()
    return value


def _sort_score(value: Any) -> float:
    return float(value) if isinstance(value, (int, float)) else float("-inf")
