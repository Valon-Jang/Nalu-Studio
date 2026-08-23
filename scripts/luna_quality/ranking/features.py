"""Pinned, text-free feature schema for the first Luna preference ranker."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from typing import Any

FEATURE_VERSION = "luna-preference-features/1"

# Ordering is part of the model contract. MOS remains last so its stronger
# regularisation can be reviewed explicitly in the linear model.
FEATURE_NAMES = (
    "syllables_per_second",
    "pitch_median_hz",
    "pitch_range_st",
    "tail_delta_st",
    "relative_tail",
    "final_glide_st_per_s",
    "final_rebound_st",
    "level_deviation_db",
    "phrase_reset_st",
    "speaker_similarity_chatterbox",
    "speaker_similarity_speechbrain",
    "content_score",
    "content_error_rate",
    "mos_score",
)

ALIASES = {
    "syllables_per_second": ("syllables_per_second", "syllables_per_sec", "rate"),
    "pitch_median_hz": ("pitch_median_hz", "median_hz"),
    "pitch_range_st": ("pitch_range_st", "range_st"),
    "tail_delta_st": ("tail_delta_st", "tail_delta"),
    "relative_tail": ("relative_tail",),
    "final_glide_st_per_s": ("final_glide_st_per_s", "final_glide"),
    "final_rebound_st": ("final_rebound_st", "final_rebound"),
    "level_deviation_db": ("level_deviation_db", "level_deviation"),
    "phrase_reset_st": ("phrase_reset_st", "phrase_reset"),
    "speaker_similarity_chatterbox": ("speaker_similarity_chatterbox", "speaker_primary_score"),
    "speaker_similarity_speechbrain": ("speaker_similarity_speechbrain", "speaker_secondary_score"),
    "content_score": ("content_score", "content_similarity"),
    "content_error_rate": ("content_error_rate", "cer"),
    "mos_score": ("mos_score", "speechmos", "mos"),
}


def feature_schema_hash(feature_names: tuple[str, ...] = FEATURE_NAMES) -> str:
    payload = {"feature_version": FEATURE_VERSION, "feature_names": list(feature_names)}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def extract_feature_map(row: Mapping[str, Any]) -> dict[str, float | None]:
    """Read only finite numeric evidence; absent validators stay missing."""
    sources: list[Mapping[str, Any]] = [row]
    for key in ("features", "metrics", "ranking_features", "existing_prosody_metrics"):
        nested = row.get(key)
        if isinstance(nested, Mapping):
            sources.append(nested)

    result: dict[str, float | None] = {}
    for name in FEATURE_NAMES:
        result[name] = _first_finite(sources, ALIASES[name])
    return result


def _first_finite(sources: list[Mapping[str, Any]], aliases: tuple[str, ...]) -> float | None:
    for source in sources:
        for alias in aliases:
            value = source.get(alias)
            if isinstance(value, bool):
                continue
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if math.isfinite(number):
                return number
    return None
