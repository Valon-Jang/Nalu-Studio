"""Offline grouped ranking metrics, baseline comparison, and ablations."""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Callable

from .data import PairwiseExample
from .pairwise import PairwiseLogisticRanker


def evaluate_ranker(ranker: PairwiseLogisticRanker, pairs: list[PairwiseExample]) -> dict[str, Any]:
    if not pairs:
        raise ValueError("evaluation requires at least one pair")
    model_metrics = _ranking_metrics(pairs, ranker.utility, ranker.preference_probability)
    baseline_metrics = _ranking_metrics(pairs, _baseline_utility, _baseline_probability)
    by_class: dict[str, Any] = {}
    for sentence_class in sorted({pair.sentence_class for pair in pairs}):
        subset = [pair for pair in pairs if pair.sentence_class == sentence_class]
        by_class[sentence_class] = _ranking_metrics(subset, ranker.utility, ranker.preference_probability)

    ablation: dict[str, float] = {}
    full_accuracy = model_metrics["pairwise_accuracy"]
    for index, name in enumerate(ranker.feature_names):
        weights = list(ranker.weights)
        weights[index] = 0.0
        ablated = PairwiseLogisticRanker(
            ranker.feature_names,
            ranker.means,
            ranker.scales,
            tuple(weights),
            ranker.intercept,
            ranker.seed,
            ranker.model_version,
        )
        accuracy = _ranking_metrics(pairs, ablated.utility, ablated.preference_probability)["pairwise_accuracy"]
        ablation[name] = accuracy - full_accuracy

    return {
        "model": model_metrics,
        "baseline": baseline_metrics,
        "baseline_pairwise_accuracy_delta": model_metrics["pairwise_accuracy"] - baseline_metrics["pairwise_accuracy"],
        "by_sentence_class": by_class,
        "ablation_pairwise_accuracy_delta": ablation,
        "evaluation_pair_count": len(pairs),
        "evaluation_group_count": len({pair.group_id for pair in pairs}),
    }


def _ranking_metrics(
    pairs: list[PairwiseExample],
    utility: Callable[[dict[str, Any]], float],
    probability: Callable[[dict[str, Any], dict[str, Any]], float],
) -> dict[str, float]:
    probabilities = [probability(pair.winner, pair.loser) for pair in pairs]
    pairwise_accuracy = sum(value > 0.5 for value in probabilities) / len(probabilities)
    brier = sum((value - 1.0) ** 2 for value in probabilities) / len(probabilities)
    ece = _expected_calibration_error(probabilities)
    uncertain = sum(abs(value - 0.5) * 2.0 < 0.20 for value in probabilities) / len(probabilities)

    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    winners: dict[str, int] = {}
    for pair in pairs:
        groups[pair.group_id].extend((pair.winner, pair.loser))
        winners[pair.group_id] = pair.winner["take_id"]

    ranks: list[int] = []
    for group_id, repeated in groups.items():
        unique = {candidate["take_id"]: candidate for candidate in repeated}
        ordered = sorted(unique.values(), key=lambda row: (-utility(row), row["take_id"]))
        ranks.append(next(index for index, row in enumerate(ordered, 1) if row["take_id"] == winners[group_id]))

    return {
        "pairwise_accuracy": pairwise_accuracy,
        "pin_top1_accuracy": sum(rank == 1 for rank in ranks) / len(ranks),
        "pin_top3_recall": sum(rank <= 3 for rank in ranks) / len(ranks),
        "mrr": sum(1.0 / rank for rank in ranks) / len(ranks),
        "ndcg": sum(1.0 / math.log2(rank + 1.0) for rank in ranks) / len(ranks),
        "brier_score": brier,
        "expected_calibration_error": ece,
        "low_confidence_fraction": uncertain,
    }


def _baseline_utility(candidate: dict[str, Any]) -> float:
    value = candidate.get("baseline_score")
    return float(value) if value is not None else 0.0


def _baseline_probability(preferred: dict[str, Any], other: dict[str, Any]) -> float:
    difference = max(-40.0, min(40.0, _baseline_utility(preferred) - _baseline_utility(other)))
    return 1.0 / (1.0 + math.exp(-difference))


def _expected_calibration_error(probabilities: list[float], bins: int = 5) -> float:
    total = len(probabilities)
    error = 0.0
    for index in range(bins):
        lower, upper = index / bins, (index + 1) / bins
        values = [value for value in probabilities if lower <= value < upper or (index == bins - 1 and value == 1.0)]
        if values:
            confidence = sum(values) / len(values)
            error += len(values) / total * abs(1.0 - confidence)
    return error
