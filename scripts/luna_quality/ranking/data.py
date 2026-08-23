"""Leakage-resistant pair construction and data-sufficiency accounting."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from typing import Any

from .features import FEATURE_NAMES, extract_feature_map


@dataclass(frozen=True)
class MinimumDataCriteria:
    pinned_phrases: int = 50
    pairs: int = 150
    blocks: int = 5
    recommended_projects: int = 2


DEFAULT_MINIMUM_DATA = MinimumDataCriteria()


@dataclass(frozen=True)
class PairwiseExample:
    winner: dict[str, Any]
    loser: dict[str, Any]
    project_id: str
    block_id: str
    phrase_id: str
    sentence_class: str
    sentence_key: str
    split_group: str = ""

    @property
    def group_id(self) -> str:
        return f"{self.project_id}/{self.block_id}/{self.phrase_id}"


@dataclass(frozen=True)
class DataSufficiency:
    status: str
    pinned_phrase_count: int
    pair_count: int
    block_count: int
    project_count: int
    sentence_class_distribution: dict[str, int]
    feature_missing_rate: float | None
    project_concentration: float | None
    reasons: tuple[str, ...]
    warnings: tuple[str, ...]
    minimum_requirements: dict[str, int]
    dataset_hash: str

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["reasons"] = list(self.reasons)
        value["warnings"] = list(self.warnings)
        return value


def normalise_candidate(row: Mapping[str, Any]) -> dict[str, Any]:
    decision = str(row.get("decision", "unknown")).lower()
    hard_gate_pass = row.get("hard_gate_pass") is True or str(row.get("hard_gate_status", "")).lower() == "pass"
    text = str(row.get("text") or "").strip()
    text_hash = str(row.get("text_hash") or _text_hash(text, row))
    return {
        "project_id": str(row.get("project_id") or ""),
        "block_id": str(row.get("block_id") or ""),
        "phrase_id": str(row.get("phrase_id") or ""),
        "take_id": int(row.get("take_id", -1)),
        "text": text,
        "text_hash": text_hash,
        "sentence_class": str(row.get("sentence_class") or "unknown"),
        "decision": decision,
        "hard_gate_pass": hard_gate_pass,
        "features": extract_feature_map(row),
        "baseline_score": _finite_or_none(row.get("baseline_score", row.get("existing_quality_score"))),
    }


def build_pairwise_examples(rows: Iterable[Mapping[str, Any]]) -> list[PairwiseExample]:
    """Pair one explicit pin only with its verified, gate-passing alternatives."""
    candidates = [normalise_candidate(row) for row in rows]
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for candidate in candidates:
        identity = (candidate["project_id"], candidate["block_id"], candidate["phrase_id"])
        if all(identity):
            grouped[identity].append(candidate)

    pairs: list[PairwiseExample] = []
    for (project, block, phrase), group in sorted(grouped.items()):
        selected = [row for row in group if row["decision"] == "selected" and row["hard_gate_pass"]]
        if len(selected) != 1:
            continue
        winner = selected[0]
        # `not_selected` is meaningful only here: this group has exactly one
        # explicit pin. Unknown/rejected takes are never inferred negatives.
        alternatives = [
            row
            for row in group
            if row["decision"] == "not_selected" and row["hard_gate_pass"] and row["take_id"] != winner["take_id"]
        ]
        for loser in sorted(alternatives, key=lambda item: item["take_id"]):
            sentence_key = winner["text_hash"] or loser["text_hash"]
            pairs.append(
                PairwiseExample(
                    winner=winner,
                    loser=loser,
                    project_id=project,
                    block_id=block,
                    phrase_id=phrase,
                    sentence_class=winner["sentence_class"],
                    sentence_key=sentence_key,
                )
            )
    return _attach_leakage_groups(pairs)


def assess_data_sufficiency(
    rows: Iterable[Mapping[str, Any]], criteria: MinimumDataCriteria = DEFAULT_MINIMUM_DATA
) -> DataSufficiency:
    normalised = [normalise_candidate(row) for row in rows]
    pairs = build_pairwise_examples(normalised)
    winners = {pair.group_id: pair.winner for pair in pairs}
    blocks = {(pair.project_id, pair.block_id) for pair in pairs}
    projects = Counter(pair.project_id for pair in pairs)
    classes = Counter(row["sentence_class"] for row in winners.values())
    eligible = [row for row in normalised if row["hard_gate_pass"] and row["decision"] in {"selected", "not_selected"}]
    missing = sum(row["features"][name] is None for row in eligible for name in FEATURE_NAMES)
    cells = len(eligible) * len(FEATURE_NAMES)
    missing_rate = missing / cells if cells else None
    pinned = len(winners)
    concentration = max((sum(1 for row in winners.values() if row["project_id"] == project) for project in projects), default=0)
    project_concentration = concentration / pinned if pinned else None

    reasons: list[str] = []
    if pinned < criteria.pinned_phrases:
        reasons.append("pinned_phrases_below_minimum")
    if len(pairs) < criteria.pairs:
        reasons.append("pairs_below_minimum")
    if len(blocks) < criteria.blocks:
        reasons.append("blocks_below_minimum")
    warnings: list[str] = []
    if len(projects) < criteria.recommended_projects:
        warnings.append("project_holdout_unavailable")
    if missing_rate is None:
        warnings.append("feature_missing_rate_not_measurable")

    minimum = asdict(criteria)
    return DataSufficiency(
        status="sufficient" if not reasons else "insufficient_data",
        pinned_phrase_count=pinned,
        pair_count=len(pairs),
        block_count=len(blocks),
        project_count=len(projects),
        sentence_class_distribution=dict(sorted(classes.items())),
        feature_missing_rate=missing_rate,
        project_concentration=project_concentration,
        reasons=tuple(reasons),
        warnings=tuple(warnings),
        minimum_requirements=minimum,
        dataset_hash=dataset_hash(normalised),
    )


def grouped_split(
    pairs: Iterable[PairwiseExample], test_fraction: float = 0.25, seed: int = 407
) -> tuple[list[PairwiseExample], list[PairwiseExample]]:
    """Split connected block/sentence groups; never split individual rows."""
    rows = list(pairs)
    groups = sorted({pair.split_group for pair in rows})
    if len(groups) < 2:
        raise ValueError("at least two independent block/sentence groups are required")
    if not 0.0 < test_fraction < 1.0:
        raise ValueError("test_fraction must be between zero and one")
    ordered = sorted(groups, key=lambda group: hashlib.sha256(f"{seed}:{group}".encode()).hexdigest())
    test_count = max(1, min(len(groups) - 1, round(len(groups) * test_fraction)))
    test_groups = set(ordered[:test_count])
    train = [pair for pair in rows if pair.split_group not in test_groups]
    test = [pair for pair in rows if pair.split_group in test_groups]
    return train, test


def project_holdout_split(
    pairs: Iterable[PairwiseExample], holdout_project: str | None = None, seed: int = 407
) -> tuple[list[PairwiseExample], list[PairwiseExample]]:
    rows = list(pairs)
    projects = sorted({pair.project_id for pair in rows})
    if len(projects) < 2:
        raise ValueError("project holdout requires at least two projects")
    selected = holdout_project or min(projects, key=lambda value: hashlib.sha256(f"{seed}:{value}".encode()).hexdigest())
    if selected not in projects:
        raise ValueError("holdout project is absent from the dataset")
    return [row for row in rows if row.project_id != selected], [row for row in rows if row.project_id == selected]


def dataset_hash(rows: Iterable[Mapping[str, Any]]) -> str:
    stable = []
    for source in rows:
        row = normalise_candidate(source) if "features" not in source else dict(source)
        stable.append(
            {
                "identity": [row.get("project_id"), row.get("block_id"), row.get("phrase_id"), row.get("take_id")],
                "decision": row.get("decision"),
                "hard_gate_pass": row.get("hard_gate_pass") is True,
                "text_hash": row.get("text_hash"),
                "features": row.get("features"),
            }
        )
    stable.sort(key=lambda item: json.dumps(item["identity"], ensure_ascii=False))
    encoded = json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def assert_no_group_leakage(train: Iterable[PairwiseExample], test: Iterable[PairwiseExample]) -> None:
    train_rows, test_rows = list(train), list(test)
    train_groups = {row.split_group for row in train_rows}
    test_groups = {row.split_group for row in test_rows}
    if train_groups & test_groups:
        raise ValueError("block/sentence split-group leakage detected")
    train_blocks = {(row.project_id, row.block_id) for row in train_rows}
    test_blocks = {(row.project_id, row.block_id) for row in test_rows}
    train_sentences = {row.sentence_key for row in train_rows}
    test_sentences = {row.sentence_key for row in test_rows}
    if train_blocks & test_blocks or train_sentences & test_sentences:
        raise ValueError("block or sentence leakage detected")


def _attach_leakage_groups(pairs: list[PairwiseExample]) -> list[PairwiseExample]:
    parent: dict[str, str] = {}

    def find(value: str) -> str:
        parent.setdefault(value, value)
        if parent[value] != value:
            parent[value] = find(parent[value])
        return parent[value]

    def union(left: str, right: str) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[max(left_root, right_root)] = min(left_root, right_root)

    tokens: list[tuple[str, str]] = []
    for pair in pairs:
        block = f"block:{pair.project_id}:{pair.block_id}"
        sentence = f"sentence:{pair.sentence_key}"
        union(block, sentence)
        tokens.append((block, sentence))

    return [
        PairwiseExample(**{**asdict(pair), "split_group": find(tokens[index][0])})
        for index, pair in enumerate(pairs)
    ]


def _text_hash(text: str, row: Mapping[str, Any]) -> str:
    if text:
        return hashlib.sha256(" ".join(text.split()).encode("utf-8")).hexdigest()
    fallback = f"{row.get('project_id', '')}/{row.get('block_id', '')}/{row.get('phrase_id', '')}"
    return hashlib.sha256(fallback.encode("utf-8")).hexdigest()


def _finite_or_none(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None
