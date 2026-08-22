"""Versioned JSON contracts shared by future Luna-quality modules."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Mapping

SCHEMA_VERSION = "1.0"


def repo_relative_path(value: str) -> str:
    """Normalise a repository-relative path without resolving it on disk."""
    text = str(value).replace("\\", "/")
    if not text or text.startswith("/") or PureWindowsPath(text).drive:
        raise ValueError("path must be non-empty and repository-relative")
    normalized = str(PurePosixPath(text))
    if normalized == "." or normalized == ".." or normalized.startswith("../"):
        raise ValueError("path must stay within the repository")
    return normalized


class ValidationStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    UNKNOWN = "unknown"
    NOT_RUN = "not_run"


@dataclass(frozen=True)
class TakeIdentity:
    block_id: str
    phrase_id: str
    take_id: int
    seed: int
    text: str
    text_hash: str
    source_wav_path: str
    source_json_path: str
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.block_id or not self.phrase_id or self.take_id < 0:
            raise ValueError("block_id, phrase_id, and non-negative take_id are required")
        object.__setattr__(self, "source_wav_path", repo_relative_path(self.source_wav_path))
        object.__setattr__(self, "source_json_path", repo_relative_path(self.source_json_path))

    def to_dict(self) -> dict[str, Any]: return self.__dict__.copy()
    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TakeIdentity": return cls(**dict(value))


@dataclass(frozen=True)
class SourceHashManifest:
    hashes: dict[str, str]
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        normal = {repo_relative_path(p): str(h).lower() for p, h in self.hashes.items()}
        if any(len(h) != 64 for h in normal.values()):
            raise ValueError("source hashes must be SHA-256 hex strings")
        object.__setattr__(self, "hashes", normal)

    def to_dict(self) -> dict[str, Any]: return {"schema_version": self.schema_version, "hashes": self.hashes}
    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SourceHashManifest": return cls(**dict(value))


@dataclass(frozen=True)
class ValidationResult:
    validator_name: str
    validator_version: str
    status: ValidationStatus
    hard_gate: bool
    score: float | None = None
    threshold: float | None = None
    reasons: list[str] = field(default_factory=list)
    metrics: dict[str, float | int | str | bool] = field(default_factory=dict)
    artifacts: dict[str, str] = field(default_factory=dict)
    source_hashes: dict[str, str] = field(default_factory=dict)
    started_at: str | None = None
    finished_at: str | None = None
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.validator_name or not self.validator_version:
            raise ValueError("validator name and version are required")
        if not isinstance(self.status, ValidationStatus):
            object.__setattr__(self, "status", ValidationStatus(self.status))
        object.__setattr__(self, "artifacts", {k: repo_relative_path(v) for k, v in self.artifacts.items()})

    def to_dict(self) -> dict[str, Any]:
        value = self.__dict__.copy(); value["status"] = self.status.value; return value
    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ValidationResult": return cls(**dict(value))


@dataclass(frozen=True)
class TakeEvaluation:
    identity: TakeIdentity
    validations: list[ValidationResult]
    existing_prosody_metrics: dict[str, float | int | str | bool] = field(default_factory=dict)
    ranking_features: dict[str, float] = field(default_factory=dict)
    hard_gate_pass: bool = False
    rank_score: float | None = None
    rank_model_version: str | None = None
    recommended: bool = False
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        value = self.__dict__.copy(); value["identity"] = self.identity.to_dict(); value["validations"] = [v.to_dict() for v in self.validations]; return value
    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TakeEvaluation":
        data = dict(value); data["identity"] = TakeIdentity.from_dict(data["identity"]); data["validations"] = [ValidationResult.from_dict(v) for v in data["validations"]]; return cls(**data)


@dataclass(frozen=True)
class CapabilityStatus:
    capability: str
    status: ValidationStatus
    package: str | None = None
    detail: str | None = None
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.status, ValidationStatus):
            object.__setattr__(self, "status", ValidationStatus(self.status))
        if self.status not in (ValidationStatus.PASS, ValidationStatus.UNKNOWN, ValidationStatus.NOT_RUN):
            raise ValueError("capability status must be pass, unknown, or not_run")
    def to_dict(self) -> dict[str, Any]:
        value = self.__dict__.copy(); value["status"] = self.status.value; return value
    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CapabilityStatus": return cls(**dict(value))
