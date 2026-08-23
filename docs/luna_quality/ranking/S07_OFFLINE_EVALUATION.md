# S07 Preference Ranker offline evaluation

## Current data decision

The repository does not contain preserved historical project jobs, pins, or
prosody measurements. The S06 Prosody Bank therefore has no real selection
history to train from in this checkout. S07 does **not** create a real model
artifact or claim an offline quality improvement.

| Required inventory | Observed |
|---|---:|
| Pinned phrases | 0 |
| Explicit selected-vs-alternative pairs | 0 |
| Blocks | 0 |
| Projects | 0 |
| Sentence-class distribution | unavailable |
| Feature missing rate | not measurable (no eligible candidates) |
| Largest-project concentration | not measurable (no pinned phrases) |

The machine-readable result is `S07_INSUFFICIENT_DATA.json`. Its empty-dataset
hash is recorded so a later real export cannot be confused with this audit.

## Minimum collection proposal

Training is enabled only after all blocking thresholds are met:

- at least 50 phrases with exactly one explicit pin;
- at least 150 selected-vs-alternative pairs from those pin groups;
- at least 5 independent blocks;
- explicit `hard_gate_pass=true` evidence for both sides of every pair.

Two projects are recommended for a project-level holdout. One sufficiently
large project may pass the blocking count thresholds, but the artifact records
`project_holdout_unavailable` and must not be presented as cross-project
evidence. Sentence-class balance and project concentration remain visible in
every sufficiency result rather than being hidden by aggregate counts.

## Leakage and label policy

Only a `selected` take and a `not_selected` take in the same phrase group with
one explicit pin become a pair. `unknown`, `rejected`, ambiguous multi-pin, and
hard-gate-unverified rows are excluded. This prevents all ordinary unselected
takes from silently becoming strong negatives.

The offline split uses connected components of `(project, block)` and normalized
sentence hash. If the same sentence appears in multiple blocks, all connected
blocks stay on one side. A random row split is not available. When two or more
projects exist, a separate project holdout is evaluated.

## Synthetic contract evaluation

The deterministic test fixture contains 50 pinned phrases, 150 pairs, 10
blocks, 2 projects, and three sentence classes. It is deliberately separable
and exists only to verify the statistical and serialization contracts.

| Synthetic result | Value |
|---|---:|
| Connected-group train/test pairs | 120 / 30 |
| Connected-group train/test groups | 8 / 2 |
| Pairwise accuracy | 1.000 |
| Pin top-1 accuracy | 1.000 |
| Pin top-3 recall | 1.000 |
| MRR / NDCG | 1.000 / 1.000 |
| Brier score | 0.0000123 |
| Expected calibration error | 0.00277 |
| Synthetic baseline pairwise accuracy | 0.000 |
| Project-holdout train/test pairs | 75 / 75 |

All three sentence classes score 1.000 on this artificial signal. Single-feature
ablations have zero pairwise-accuracy delta because the fixture intentionally
contains many redundant aligned signals. Neither result is evidence for real
Luna promotion; real metrics and ablations remain `not_run` until sufficient
human data exists.

## Model and inference contract

The first model is a standardized pairwise logistic regression with fixed seed
`407`, no text embeddings, and stronger L2 regularization for MOS. A valid
artifact records model/feature versions, ordered feature names, feature schema
hash, training dataset hash, standardization values, coefficients, sufficiency,
and grouped evaluation.

`load_artifact()` fails closed on artifact or feature-schema mismatch.
`rank_candidates()` excludes candidates without an explicit hard-gate pass,
reports confidence, never changes production selection, and disallows candidate
reduction below the confidence threshold. This is the read-only S08 boundary.

## Reproduction

Unit and grouped synthetic evaluation:

```powershell
python -X utf8 -m unittest tests.luna_quality.unit.test_preference_ranker -v
```

Training from a future Prosody Bank JSON export:

```powershell
python -X utf8 -m scripts.luna_quality.ranking.train `
  --input <candidates.json> `
  --artifact <ranker.json> `
  --evaluation <evaluation.json> `
  --seed 407
```

If the minimum is not met, the same command writes an `insufficient_data`
artifact and an evaluation file with `not_run`; it never fabricates a model.
