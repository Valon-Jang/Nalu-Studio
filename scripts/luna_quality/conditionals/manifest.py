"""Versioned provenance manifest for a Candidate B conditionals artifact.

The manifest deliberately contains hashes and repository-relative metadata only.
It never serializes the Candidate B WAV or any model checkpoint into JSON.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Any, Mapping

from ..contracts import repo_relative_path
from ..hashing import sha256_file, sha256_text


CONDITIONALS_CACHE_SCHEMA_VERSION = "1.0"
CANDIDATE_B_REFERENCE_PATH = "assets/voice_ref/B_voiced_spectral_micro_smooth.wav"


def _require_sha256(value: str, field_name: str) -> str:
    normalized = str(value).lower()
    if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
        raise ValueError(f"{field_name} must be a SHA-256 hex string")
    return normalized


@dataclass(frozen=True)
class FileFingerprint:
    """A model input represented only by its filename and content hash."""

    filename: str
    sha256: str

    def __post_init__(self) -> None:
        if not self.filename or Path(self.filename).name != self.filename:
            raise ValueError("filename must be a basename")
        object.__setattr__(self, "sha256", _require_sha256(self.sha256, "sha256"))

    def to_dict(self) -> dict[str, str]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FileFingerprint":
        return cls(**dict(value))


@dataclass(frozen=True)
class ConditionalsCacheInputs:
    """All source inputs which must match before a cache artifact is reusable."""

    chatterbox_source_version: str
    t3_checkpoint: FileFingerprint
    s3gen: FileFingerprint
    voice_encoder: FileFingerprint
    tokenizer: FileFingerprint
    reference_wav_path: str
    reference_wav_sha256: str
    language_id: str
    exaggeration: float
    schema_version: str = CONDITIONALS_CACHE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.chatterbox_source_version:
            raise ValueError("chatterbox_source_version is required")
        if self.schema_version != CONDITIONALS_CACHE_SCHEMA_VERSION:
            raise ValueError("unsupported conditionals cache schema version")
        reference_path = repo_relative_path(self.reference_wav_path)
        if reference_path != CANDIDATE_B_REFERENCE_PATH:
            raise ValueError("conditionals cache is restricted to the fixed Candidate B reference")
        if not self.language_id:
            raise ValueError("language_id is required")
        if not math.isfinite(self.exaggeration) or self.exaggeration < 0:
            raise ValueError("exaggeration must be a finite, non-negative number")
        object.__setattr__(self, "reference_wav_path", reference_path)
        object.__setattr__(self, "reference_wav_sha256", _require_sha256(self.reference_wav_sha256, "reference_wav_sha256"))

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        for name in ("t3_checkpoint", "s3gen", "voice_encoder", "tokenizer"):
            value[name] = getattr(self, name).to_dict()
        return value

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ConditionalsCacheInputs":
        data = dict(value)
        for name in ("t3_checkpoint", "s3gen", "voice_encoder", "tokenizer"):
            data[name] = FileFingerprint.from_dict(data[name])
        return cls(**data)

    def cache_key(self) -> str:
        """Return a stable key that excludes timestamps and cache-artifact bytes."""
        return sha256_text(json.dumps(self.to_dict(), ensure_ascii=True, sort_keys=True, separators=(",", ":")))

    @classmethod
    def from_files(
        cls,
        *,
        repo_root: str | Path,
        chatterbox_source_version: str,
        t3_checkpoint: str | Path,
        s3gen: str | Path,
        voice_encoder: str | Path,
        tokenizer: str | Path,
        reference_wav: str | Path,
        language_id: str = "ko",
        exaggeration: float = 0.5,
    ) -> "ConditionalsCacheInputs":
        """Fingerprint local V3 sources without copying their contents anywhere."""
        root = Path(repo_root).resolve()
        reference = Path(reference_wav).resolve()
        try:
            reference_relative = reference.relative_to(root).as_posix()
        except ValueError as error:
            raise ValueError("reference_wav must be inside repo_root") from error

        def fingerprint(path: str | Path) -> FileFingerprint:
            item = Path(path)
            if not item.is_file():
                raise FileNotFoundError(item)
            return FileFingerprint(item.name, sha256_file(item))

        if not reference.is_file():
            raise FileNotFoundError(reference)
        return cls(
            chatterbox_source_version=chatterbox_source_version,
            t3_checkpoint=fingerprint(t3_checkpoint),
            s3gen=fingerprint(s3gen),
            voice_encoder=fingerprint(voice_encoder),
            tokenizer=fingerprint(tokenizer),
            reference_wav_path=reference_relative,
            reference_wav_sha256=sha256_file(reference),
            language_id=language_id,
            exaggeration=exaggeration,
        )


@dataclass(frozen=True)
class ConditionalsCacheManifest:
    """The persisted artifact checksum and the complete inputs that produced it."""

    inputs: ConditionalsCacheInputs
    artifact_sha256: str
    created_at: str
    cache_key: str
    schema_version: str = CONDITIONALS_CACHE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != CONDITIONALS_CACHE_SCHEMA_VERSION:
            raise ValueError("unsupported conditionals cache schema version")
        object.__setattr__(self, "artifact_sha256", _require_sha256(self.artifact_sha256, "artifact_sha256"))
        if self.cache_key != self.inputs.cache_key():
            raise ValueError("cache_key does not match manifest inputs")
        datetime.fromisoformat(self.created_at.replace("Z", "+00:00"))

    @classmethod
    def create(cls, inputs: ConditionalsCacheInputs, artifact_sha256: str) -> "ConditionalsCacheManifest":
        return cls(
            inputs=inputs,
            artifact_sha256=artifact_sha256,
            created_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            cache_key=inputs.cache_key(),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "cache_key": self.cache_key,
            "created_at": self.created_at,
            "artifact_sha256": self.artifact_sha256,
            "inputs": self.inputs.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ConditionalsCacheManifest":
        data = dict(value)
        data["inputs"] = ConditionalsCacheInputs.from_dict(data["inputs"])
        return cls(**data)
