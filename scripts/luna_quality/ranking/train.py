"""Reproducible training entry point for the shadow-only preference ranker.

Example:
    python -m scripts.luna_quality.ranking.train --input candidates.json \
        --artifact ranker.json --evaluation evaluation.json
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .artifact import artifact_payload, insufficient_data_payload, save_artifact
from .data import (
    DEFAULT_MINIMUM_DATA,
    DataSufficiency,
    MinimumDataCriteria,
    assert_no_group_leakage,
    assess_data_sufficiency,
    build_pairwise_examples,
    grouped_split,
    project_holdout_split,
)
from .evaluate import evaluate_ranker
from .pairwise import PairwiseLogisticRanker, fit_pairwise_logistic


@dataclass(frozen=True)
class TrainingResult:
    status: str
    ranker: PairwiseLogisticRanker | None
    artifact: dict[str, Any]
    evaluation: dict[str, Any]
    data_sufficiency: DataSufficiency


def train_ranker(
    rows: list[Mapping[str, Any]],
    *,
    criteria: MinimumDataCriteria = DEFAULT_MINIMUM_DATA,
    seed: int = 407,
    test_fraction: float = 0.25,
) -> TrainingResult:
    source_hashes = _source_hashes(rows)
    sufficiency = assess_data_sufficiency(rows, criteria)
    if sufficiency.status != "sufficient":
        evaluation = {
            "status": "insufficient_data",
            "offline_grouped_evaluation": "not_run",
            "baseline_comparison": "not_run",
            "reason": list(sufficiency.reasons),
        }
        artifact = insufficient_data_payload(sufficiency.to_dict(), source_hashes)
        return TrainingResult("insufficient_data", None, artifact, evaluation, sufficiency)

    pairs = build_pairwise_examples(rows)
    train_pairs, test_pairs = grouped_split(pairs, test_fraction=test_fraction, seed=seed)
    assert_no_group_leakage(train_pairs, test_pairs)
    evaluation_model = fit_pairwise_logistic(train_pairs, seed=seed)
    evaluation = {
        "status": "evaluated",
        "split": {
            "strategy": "connected_block_sentence_group",
            "seed": seed,
            "train_pairs": len(train_pairs),
            "test_pairs": len(test_pairs),
            "train_groups": len({pair.split_group for pair in train_pairs}),
            "test_groups": len({pair.split_group for pair in test_pairs}),
        },
        "grouped_holdout": evaluate_ranker(evaluation_model, test_pairs),
    }

    if sufficiency.project_count >= 2:
        project_train, project_test = project_holdout_split(pairs, seed=seed)
        project_model = fit_pairwise_logistic(project_train, seed=seed)
        evaluation["project_holdout"] = {
            "holdout_project": project_test[0].project_id,
            "train_pairs": len(project_train),
            "test_pairs": len(project_test),
            "metrics": evaluate_ranker(project_model, project_test),
        }
    else:
        evaluation["project_holdout"] = {"status": "not_run", "reason": "requires_two_projects"}

    final_ranker = fit_pairwise_logistic(pairs, seed=seed)
    artifact = artifact_payload(
        final_ranker,
        dataset_hash=sufficiency.dataset_hash,
        source_hashes=source_hashes,
        data_sufficiency=sufficiency.to_dict(),
        evaluation=evaluation,
    )
    return TrainingResult("trained", final_ranker, artifact, evaluation, sufficiency)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Train or document insufficiency for the Luna pairwise ranker")
    parser.add_argument("--input", required=True, help="UTF-8 JSON list, or object with a candidates list")
    parser.add_argument("--artifact", required=True, help="Output model/insufficient-data JSON")
    parser.add_argument("--evaluation", required=True, help="Output offline evaluation JSON")
    parser.add_argument("--seed", type=int, default=407)
    args = parser.parse_args(argv)

    source = json.loads(Path(args.input).read_text(encoding="utf-8"))
    rows = source.get("candidates") if isinstance(source, dict) else source
    if not isinstance(rows, list):
        raise ValueError("input must be a JSON list or contain a candidates list")
    result = train_ranker(rows, seed=args.seed)
    save_artifact(args.artifact, result.artifact)
    save_artifact(
        args.evaluation,
        {
            "status": result.status,
            "data_sufficiency": result.data_sufficiency.to_dict(),
            "evaluation": result.evaluation,
        },
    )
    print(json.dumps({"status": result.status, "artifact": args.artifact, "evaluation": args.evaluation}, sort_keys=True))
    return 0


def _source_hashes(rows: list[Mapping[str, Any]]) -> list[str]:
    hashes = set()
    for row in rows:
        for key in ("source_sha256", "selection_source_sha256", "audio_sha256"):
            value = str(row.get(key) or "").lower()
            if len(value) == 64 and all(character in "0123456789abcdef" for character in value):
                hashes.add(value)
    return sorted(hashes)


if __name__ == "__main__":
    raise SystemExit(main())
