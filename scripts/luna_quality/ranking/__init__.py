"""Shadow-only, interpretable preference ranking for approved Luna takes."""

from .artifact import ArtifactLoadResult, load_artifact, save_artifact
from .data import (
    DEFAULT_MINIMUM_DATA,
    DataSufficiency,
    MinimumDataCriteria,
    PairwiseExample,
    assess_data_sufficiency,
    build_pairwise_examples,
    grouped_split,
)
from .features import FEATURE_NAMES, FEATURE_VERSION, feature_schema_hash
from .pairwise import PairwiseLogisticRanker, RankResult

__all__ = [
    "ArtifactLoadResult",
    "DEFAULT_MINIMUM_DATA",
    "DataSufficiency",
    "FEATURE_NAMES",
    "FEATURE_VERSION",
    "MinimumDataCriteria",
    "PairwiseExample",
    "PairwiseLogisticRanker",
    "RankResult",
    "assess_data_sufficiency",
    "build_pairwise_examples",
    "feature_schema_hash",
    "grouped_split",
    "load_artifact",
    "save_artifact",
    "train_ranker",
]


def train_ranker(*args, **kwargs):
    """Lazy public wrapper that keeps ``python -m ...ranking.train`` warning-free."""
    from .train import train_ranker as implementation

    return implementation(*args, **kwargs)
