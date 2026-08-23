"""Explicit shadow-only gate and baseline-ranking policy."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from typing import Any

from ..contracts import ValidationResult, ValidationStatus

POLICY_VERSION = "luna-shadow-policy/1"


@dataclass(frozen=True)
class ShadowPolicy:
    rate_target: float = 6.54
    level_anchor_hz: float = 235.0
    level_weight: float = 6.0
    rate_weight: float = 8.0
    slope_weight: float = 0.5
    final_rebound_minimum: float = 2.5
    final_glide_minimum: float = 4.0

    @property
    def config_hash(self) -> str:
        encoded = json.dumps(asdict(self), sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


def imported_prosody_result(row: Mapping[str, Any]) -> ValidationResult:
    """Represent the existing take JSON gate without re-gating or mutating it."""
    if row.get("ok") is True:
        status, reasons = ValidationStatus.PASS, []
    elif row.get("ok") is False:
        status, reasons = ValidationStatus.FAIL, [str(reason) for reason in row.get("why", [])] or ["existing_gate_rejected"]
    else:
        status, reasons = ValidationStatus.UNKNOWN, ["existing_gate_status_missing"]
    metrics = {key: value for key, value in (row.get("metrics") or {}).items() if _scalar(value)}
    return ValidationResult(
        validator_name="existing_prosody_gate",
        validator_version="production-take-json/1",
        status=status,
        hard_gate=True,
        reasons=reasons,
        metrics=metrics,
    )


def not_run_result(validator_name: str, reason: str, hard_gate: bool = False) -> ValidationResult:
    return ValidationResult(
        validator_name=validator_name,
        validator_version=f"{validator_name}/shadow-not-run/1",
        status=ValidationStatus.NOT_RUN,
        hard_gate=hard_gate,
        reasons=[reason],
    )


def exception_result(validator_name: str, exc: Exception, hard_gate: bool) -> ValidationResult:
    return ValidationResult(
        validator_name=validator_name,
        validator_version=f"{validator_name}/shadow-exception/1",
        status=ValidationStatus.UNKNOWN,
        hard_gate=hard_gate,
        reasons=[f"validator_exception:{type(exc).__name__}"],
    )


def hard_gate_survives(validations: Iterable[ValidationResult]) -> bool:
    """Unknown/not-run remains visible but is never represented as a pass."""
    return not any(item.hard_gate and item.status is ValidationStatus.FAIL for item in validations)


def ranking_features(row: Mapping[str, Any], validations: Iterable[ValidationResult]) -> dict[str, float]:
    metrics = dict(row.get("metrics") or {})
    result: dict[str, float] = {}
    _copy_number(metrics, result, "median_hz", "pitch_median_hz")
    _copy_number(metrics, result, "range_st", "pitch_range_st")
    _copy_number(metrics, result, "tail_delta", "tail_delta_st")
    _copy_number(metrics, result, "final_glide", "final_glide_st_per_s")
    _copy_number(metrics, result, "final_rebound", "final_rebound_st")
    duration = _number(metrics.get("dur"))
    syllables = _number(row.get("n_syl"))
    if duration and syllables is not None:
        result["syllables_per_second"] = syllables / duration
    tail, pitch_range = _number(metrics.get("tail_delta")), _number(metrics.get("range_st"))
    if tail is not None and pitch_range not in (None, 0.0):
        result["relative_tail"] = tail / pitch_range
    median = _number(metrics.get("median_hz"))
    if median is not None and median > 0:
        result["level_deviation_db"] = 12.0 * math.log2(median / 235.0)
    for validation in validations:
        if validation.validator_name == "speaker_identity":
            _copy_number(validation.metrics, result, "primary_chatterbox_similarity", "speaker_similarity_chatterbox")
            _copy_number(validation.metrics, result, "secondary_speechbrain_similarity", "speaker_similarity_speechbrain")
        elif validation.validator_name == "content_asr":
            error_rate = _number(validation.metrics.get("normalized_edit_distance"))
            if error_rate is not None:
                result["content_error_rate"] = error_rate
                result["content_score"] = max(0.0, 1.0 - error_rate)
        elif validation.validator_name == "mos":
            _copy_number(validation.metrics, result, "mos_score", "mos_score")
    return result


def existing_quality_score(
    row: Mapping[str, Any], *, sentence_final: bool, forced: bool = False, policy: ShadowPolicy | None = None
) -> float | None:
    """A transparent mirror of the persisted-take quality ingredients.

    This score is only a shadow fallback. It does not import production code,
    re-run a gate, or alter its beam/pin behavior.
    """
    settings = policy or ShadowPolicy()
    metrics = row.get("metrics") or {}
    duration, syllables = _number(metrics.get("dur")), _number(row.get("n_syl"))
    slope, median = _number(metrics.get("end_slope")), _number(metrics.get("median_hz"))
    if duration in (None, 0.0) or syllables is None or slope is None or median in (None, 0.0):
        return None
    text = str(row.get("text") or "")
    question = _is_question(text)
    prior, bonus = (-6.5, (-10.0, -5.0)) if question else ((-2.0, (-8.0, 4.0)) if forced else (-12.0, (-35.0, 0.0)))
    score = -abs(syllables / duration - settings.rate_target) * settings.rate_weight
    score -= min(abs(slope - prior), 25.0) * settings.slope_weight
    if bonus[0] <= slope <= bonus[1]:
        score += 5.0
    score -= abs(12.0 * math.log2(median / settings.level_anchor_hz)) * settings.level_weight
    if sentence_final:
        rebound, glide = _number(metrics.get("final_rebound")), _number(metrics.get("final_glide"))
        if rebound is not None and rebound < settings.final_rebound_minimum:
            score -= (settings.final_rebound_minimum - rebound) * 4.0
        if glide is not None and glide < settings.final_glide_minimum:
            score -= (settings.final_glide_minimum - glide) * 0.3
    return score


def disagreement_reasons(actual: Mapping[str, Any] | None, recommended: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    if actual is None or recommended is None:
        return []
    reasons: list[dict[str, Any]] = []
    if actual.get("hard_gate_pass") != recommended.get("hard_gate_pass"):
        reasons.append({"kind": "hard_gate_survival", "actual": actual.get("hard_gate_pass"), "shadow": recommended.get("hard_gate_pass")})
    for name in sorted(set(actual.get("ranking_features", {})) | set(recommended.get("ranking_features", {}))):
        left, right = actual.get("ranking_features", {}).get(name), recommended.get("ranking_features", {}).get(name)
        if _number(left) is not None and _number(right) is not None and left != right:
            reasons.append({"kind": "feature_delta", "feature": name, "actual": left, "shadow": right, "shadow_minus_actual": right - left})
    if actual.get("rank_score") != recommended.get("rank_score"):
        reasons.append({"kind": "rank_score", "actual": actual.get("rank_score"), "shadow": recommended.get("rank_score")})
    return reasons


def _is_question(text: str) -> bool:
    compact = text.strip().rstrip(".?!…")
    return text.strip().endswith("?") or compact.endswith(("까요", "나요", "가요"))


def _copy_number(source: Mapping[str, Any], destination: dict[str, float], source_key: str, destination_key: str) -> None:
    value = _number(source.get(source_key))
    if value is not None:
        destination[destination_key] = value


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _scalar(value: Any) -> bool:
    if isinstance(value, float):
        return math.isfinite(value)
    return isinstance(value, (str, int, bool))
