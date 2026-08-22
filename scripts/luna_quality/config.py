"""Production-off settings for later shadow-only Luna-quality modules."""
from __future__ import annotations
from dataclasses import dataclass
from .contracts import SCHEMA_VERSION

@dataclass(frozen=True)
class QualityConfig:
    schema_version: str = SCHEMA_VERSION
    mode: str = "off"
    output_root: str = "artifacts/luna_quality"
    allow_optional_dependencies: bool = True
    def __post_init__(self) -> None:
        if self.mode != "off": raise ValueError("S01 supports only production-off mode")
