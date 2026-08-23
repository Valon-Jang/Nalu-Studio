"""Atomic, local-only storage for Chatterbox Multilingual ``Conditionals``.

This module intentionally does not import Chatterbox.  Callers supply the
official ``Conditionals`` class (or a compatible fake in unit tests), keeping
model loading as an integration-only concern and production untouched.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping

from ..hashing import sha256_file
from .manifest import ConditionalsCacheInputs, ConditionalsCacheManifest


class CacheMissReason(str, Enum):
    ARTIFACT_MISSING = "artifact_missing"
    MANIFEST_MISSING = "manifest_missing"
    MANIFEST_INVALID = "manifest_invalid"
    SOURCE_MISMATCH = "source_mismatch"
    ARTIFACT_HASH_MISMATCH = "artifact_hash_mismatch"
    DESERIALIZATION_ERROR = "deserialization_error"


@dataclass(frozen=True)
class CacheLookupResult:
    hit: bool
    conditionals: Any | None = None
    reason: CacheMissReason | None = None
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.hit and (self.conditionals is None or self.reason is not None):
            raise ValueError("a cache hit requires conditionals and no miss reason")
        if not self.hit and self.reason is None:
            raise ValueError("a cache miss requires an explicit reason")


class ConditionalsCache:
    """One fixed Candidate B slot, safe to discard whenever validation misses."""

    ARTIFACT_NAME = "candidate_b.conditionals.pt"
    MANIFEST_NAME = "candidate_b.conditionals.manifest.json"

    def __init__(self, cache_dir: str | Path = ".luna_quality_cache/conditionals") -> None:
        self.cache_dir = Path(cache_dir)

    @property
    def artifact_path(self) -> Path:
        return self.cache_dir / self.ARTIFACT_NAME

    @property
    def manifest_path(self) -> Path:
        return self.cache_dir / self.MANIFEST_NAME

    def load(self, inputs: ConditionalsCacheInputs, conditionals_cls: type[Any]) -> CacheLookupResult:
        """Load only when every source fingerprint and artifact checksum match."""
        if not self.manifest_path.exists():
            return CacheLookupResult(False, reason=CacheMissReason.MANIFEST_MISSING)
        try:
            manifest = ConditionalsCacheManifest.from_dict(json.loads(self.manifest_path.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
            return CacheLookupResult(False, reason=CacheMissReason.MANIFEST_INVALID, details={"error": type(error).__name__})
        if manifest.inputs != inputs or manifest.cache_key != inputs.cache_key():
            return CacheLookupResult(
                False,
                reason=CacheMissReason.SOURCE_MISMATCH,
                details={"expected_cache_key": inputs.cache_key(), "cached_cache_key": manifest.cache_key},
            )
        if not self.artifact_path.is_file():
            return CacheLookupResult(False, reason=CacheMissReason.ARTIFACT_MISSING)
        try:
            actual_hash = sha256_file(self.artifact_path)
        except OSError as error:
            return CacheLookupResult(False, reason=CacheMissReason.ARTIFACT_MISSING, details={"error": type(error).__name__})
        if actual_hash != manifest.artifact_sha256:
            return CacheLookupResult(
                False,
                reason=CacheMissReason.ARTIFACT_HASH_MISMATCH,
                details={"expected_sha256": manifest.artifact_sha256, "actual_sha256": actual_hash},
            )
        try:
            conditionals = conditionals_cls.load(self.artifact_path, map_location="cpu")
        except Exception as error:  # Third-party deserialization errors are cache misses, never success.
            return CacheLookupResult(False, reason=CacheMissReason.DESERIALIZATION_ERROR, details={"error": type(error).__name__})
        return CacheLookupResult(True, conditionals=conditionals)

    def store(self, inputs: ConditionalsCacheInputs, conditionals: Any) -> ConditionalsCacheManifest:
        """Use the official ``Conditionals.save(Path)`` contract and atomic replaces."""
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        artifact_temp = self._temporary_path(self.ARTIFACT_NAME)
        try:
            conditionals.save(artifact_temp)
            artifact_hash = sha256_file(artifact_temp)
            manifest = ConditionalsCacheManifest.create(inputs, artifact_hash)
            os.replace(artifact_temp, self.artifact_path)
            self._atomic_write_text(self.manifest_path, json.dumps(manifest.to_dict(), ensure_ascii=True, sort_keys=True, indent=2) + "\n")
            return manifest
        finally:
            artifact_temp.unlink(missing_ok=True)

    def _temporary_path(self, target_name: str) -> Path:
        descriptor, raw_path = tempfile.mkstemp(prefix=f".{target_name}.", suffix=".tmp", dir=self.cache_dir)
        os.close(descriptor)
        return Path(raw_path)

    def _atomic_write_text(self, destination: Path, content: str) -> None:
        temporary = self._temporary_path(destination.name)
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
