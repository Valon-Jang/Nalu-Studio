"""Versioned JSON artifact with fail-closed schema and integrity checks."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .features import FEATURE_NAMES, FEATURE_VERSION, feature_schema_hash
from .pairwise import MODEL_VERSION, PairwiseLogisticRanker

ARTIFACT_SCHEMA_VERSION = "luna-ranker-artifact/1"


@dataclass(frozen=True)
class ArtifactLoadResult:
    status: str
    ranker: PairwiseLogisticRanker | None
    metadata: dict[str, Any]
    reason: str | None = None


def artifact_payload(
    ranker: PairwiseLogisticRanker,
    *,
    dataset_hash: str,
    source_hashes: list[str],
    data_sufficiency: Mapping[str, Any],
    evaluation: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
        "feature_version": FEATURE_VERSION,
        "feature_schema_hash": ranker.schema_hash,
        "training_dataset_hash": dataset_hash,
        "metadata": {
            "model_id": ranker.model_version,
            "fixed_seed": ranker.seed,
            "source_hashes": source_hashes,
            "standardization": "training-candidate mean/population-std; missing values use training mean",
            "confidence_threshold": 0.2,
            "mos_l2_multiplier": 8.0,
        },
        "model": ranker.to_dict(),
        "data_sufficiency": dict(data_sufficiency),
        "evaluation": dict(evaluation),
        "safety": {
            "production_integration": "off",
            "hard_gate_failures_excluded": True,
            "low_confidence_candidate_reduction": False,
        },
    }


def insufficient_data_payload(
    data_sufficiency: Mapping[str, Any], source_hashes: list[str] | None = None
) -> dict[str, Any]:
    return {
        "artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
        "status": "insufficient_data",
        "feature_version": FEATURE_VERSION,
        "feature_schema_hash": feature_schema_hash(),
        "model": None,
        "metadata": {"model_id": MODEL_VERSION, "source_hashes": source_hashes or []},
        "data_sufficiency": dict(data_sufficiency),
        "safety": {"production_integration": "off", "ranker_enabled": False},
    }


def save_artifact(path: str | Path, payload: Mapping[str, Any]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_artifact(
    path: str | Path, expected_feature_names: tuple[str, ...] = FEATURE_NAMES
) -> ArtifactLoadResult:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        return ArtifactLoadResult("disabled", None, {}, f"artifact_unreadable:{type(exc).__name__}")
    if payload.get("artifact_schema_version") != ARTIFACT_SCHEMA_VERSION:
        return ArtifactLoadResult("disabled", None, payload, "artifact_schema_mismatch")
    if payload.get("status") == "insufficient_data" or payload.get("model") is None:
        return ArtifactLoadResult("disabled", None, payload, "insufficient_data")
    expected_hash = feature_schema_hash(expected_feature_names)
    if payload.get("feature_schema_hash") != expected_hash:
        return ArtifactLoadResult("disabled", None, payload, "feature_schema_mismatch")
    try:
        ranker = PairwiseLogisticRanker.from_dict(payload["model"])
    except (KeyError, TypeError, ValueError) as exc:
        return ArtifactLoadResult("disabled", None, payload, f"invalid_model:{type(exc).__name__}")
    if ranker.schema_hash != expected_hash or tuple(ranker.feature_names) != tuple(expected_feature_names):
        return ArtifactLoadResult("disabled", None, payload, "model_feature_schema_mismatch")
    if ranker.model_version != MODEL_VERSION:
        return ArtifactLoadResult("disabled", None, payload, "model_version_mismatch")
    return ArtifactLoadResult("active", ranker, payload)
