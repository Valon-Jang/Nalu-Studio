"""Small deterministic pairwise logistic model and read-only inference API."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Mapping

from .data import PairwiseExample
from .features import FEATURE_NAMES, extract_feature_map, feature_schema_hash

MODEL_VERSION = "luna-pairwise-logistic/1"


@dataclass(frozen=True)
class RankResult:
    status: str
    take_id: int | None
    score: float | None
    confidence: float | None
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PairwiseLogisticRanker:
    feature_names: tuple[str, ...]
    means: tuple[float, ...]
    scales: tuple[float, ...]
    weights: tuple[float, ...]
    intercept: float
    seed: int
    model_version: str = MODEL_VERSION

    def __post_init__(self) -> None:
        length = len(self.feature_names)
        if not length or any(len(values) != length for values in (self.means, self.scales, self.weights)):
            raise ValueError("model vectors must match the feature schema")
        if any(scale <= 0 or not math.isfinite(scale) for scale in self.scales):
            raise ValueError("feature scales must be finite and positive")

    @property
    def schema_hash(self) -> str:
        return feature_schema_hash(self.feature_names)

    def utility(self, features: Mapping[str, Any]) -> float:
        values = extract_feature_map(features)
        standardized = [
            ((values[name] if values[name] is not None else self.means[index]) - self.means[index]) / self.scales[index]
            for index, name in enumerate(self.feature_names)
        ]
        return sum(weight * value for weight, value in zip(self.weights, standardized))

    def preference_probability(self, preferred: Mapping[str, Any], other: Mapping[str, Any]) -> float:
        return _sigmoid(self.intercept + self.utility(preferred) - self.utility(other))

    def rank_candidates(
        self, candidates: list[Mapping[str, Any]], confidence_threshold: float = 0.20
    ) -> dict[str, Any]:
        """Rank only explicit hard-gate passes; never mutate or select production output."""
        results: list[RankResult] = []
        eligible: list[tuple[Mapping[str, Any], float]] = []
        for candidate in candidates:
            take_id = _take_id(candidate)
            if not (candidate.get("hard_gate_pass") is True or str(candidate.get("hard_gate_status", "")).lower() == "pass"):
                results.append(RankResult("excluded", take_id, None, None, "hard_gate_not_pass"))
                continue
            score = self.utility(candidate)
            eligible.append((candidate, score))

        eligible.sort(key=lambda item: (-item[1], _take_id(item[0]) if _take_id(item[0]) is not None else -1))
        if eligible:
            top_score = eligible[0][1]
            second_score = eligible[1][1] if len(eligible) > 1 else top_score
            top_confidence = abs(_sigmoid(top_score - second_score) - 0.5) * 2.0 if len(eligible) > 1 else 0.0
            for index, (candidate, score) in enumerate(eligible):
                confidence = top_confidence if index == 0 else None
                results.append(RankResult("ranked", _take_id(candidate), score, confidence))
        else:
            top_confidence = 0.0

        ranked = sorted(results, key=lambda item: (item.status != "ranked", -(item.score or 0.0), item.take_id or -1))
        return {
            "status": "ranked" if eligible else "no_eligible_candidates",
            "results": [result.to_dict() for result in ranked],
            "top_confidence": top_confidence,
            # S08 may display ranking evidence, but low confidence cannot prune.
            "candidate_reduction_allowed": bool(eligible) and top_confidence >= confidence_threshold,
            "production_selection_changed": False,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_version": self.model_version,
            "feature_names": list(self.feature_names),
            "feature_schema_hash": self.schema_hash,
            "means": list(self.means),
            "scales": list(self.scales),
            "weights": list(self.weights),
            "intercept": self.intercept,
            "seed": self.seed,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PairwiseLogisticRanker":
        return cls(
            feature_names=tuple(value["feature_names"]),
            means=tuple(float(item) for item in value["means"]),
            scales=tuple(float(item) for item in value["scales"]),
            weights=tuple(float(item) for item in value["weights"]),
            intercept=float(value["intercept"]),
            seed=int(value["seed"]),
            model_version=str(value.get("model_version", MODEL_VERSION)),
        )


def fit_pairwise_logistic(
    pairs: list[PairwiseExample],
    *,
    feature_names: tuple[str, ...] = FEATURE_NAMES,
    seed: int = 407,
    iterations: int = 800,
    learning_rate: float = 0.12,
    l2: float = 0.02,
) -> PairwiseLogisticRanker:
    if not pairs:
        raise ValueError("at least one training pair is required")

    candidates = [candidate for pair in pairs for candidate in (pair.winner, pair.loser)]
    columns = [[candidate["features"].get(name) for candidate in candidates] for name in feature_names]
    means = tuple(_mean([value for value in column if value is not None]) for column in columns)
    scales = tuple(_scale([value for value in column if value is not None], mean) for column, mean in zip(columns, means))

    examples: list[tuple[list[float], float]] = []
    for pair in pairs:
        difference = []
        for index, name in enumerate(feature_names):
            winner = pair.winner["features"].get(name)
            loser = pair.loser["features"].get(name)
            winner_value = means[index] if winner is None else float(winner)
            loser_value = means[index] if loser is None else float(loser)
            difference.append((winner_value - loser_value) / scales[index])
        # Symmetry prevents an all-positive intercept from becoming a trivial fit.
        examples.append((difference, 1.0))
        examples.append(([-value for value in difference], 0.0))

    weights = [0.0] * len(feature_names)
    intercept = 0.0
    penalty = [8.0 if name == "mos_score" else 1.0 for name in feature_names]
    for _ in range(iterations):
        weight_gradient = [0.0] * len(weights)
        intercept_gradient = 0.0
        for vector, label in examples:
            prediction = _sigmoid(intercept + sum(weight * value for weight, value in zip(weights, vector)))
            error = prediction - label
            intercept_gradient += error
            for index, value in enumerate(vector):
                weight_gradient[index] += error * value
        count = float(len(examples))
        intercept -= learning_rate * intercept_gradient / count
        for index in range(len(weights)):
            gradient = weight_gradient[index] / count + l2 * penalty[index] * weights[index]
            weights[index] -= learning_rate * gradient

    return PairwiseLogisticRanker(
        feature_names=feature_names,
        means=means,
        scales=scales,
        weights=tuple(weights),
        intercept=intercept,
        seed=seed,
    )


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _scale(values: list[float], mean: float) -> float:
    if len(values) < 2:
        return 1.0
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    scale = math.sqrt(variance)
    return scale if scale > 1e-12 else 1.0


def _sigmoid(value: float) -> float:
    if value >= 0:
        exponent = math.exp(-min(value, 700.0))
        return 1.0 / (1.0 + exponent)
    exponent = math.exp(max(value, -700.0))
    return exponent / (1.0 + exponent)


def _take_id(candidate: Mapping[str, Any]) -> int | None:
    try:
        return int(candidate.get("take_id"))
    except (TypeError, ValueError):
        return None
