"""Verified Candidate B condition loading for the resident worker."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..conditionals.cache import CacheMissReason, ConditionalsCache
from ..conditionals.manifest import ConditionalsCacheInputs
from ..hashing import sha256_file


CANDIDATE_B_SHA256 = "30c6d3405f46684af467c7d26ff40a2fb57dd48cc84cd24cf7403d9aa00a2bb9"
LANGUAGE_ID = "ko"
EXAGGERATION = 0.5


class CandidateBConditioner:
    """Load or create one trusted official Chatterbox ``Conditionals`` artifact."""

    def __init__(self, repo_root: str | Path, cache_dir: str | Path | None = None) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.runtime_root = self.repo_root / "engine" / "chatterbox-v3"
        self.reference = self.repo_root / "assets" / "voice_ref" / "B_voiced_spectral_micro_smooth.wav"
        self.cache = ConditionalsCache(cache_dir or self.repo_root / ".luna_quality_cache" / "conditionals")
        self.prepare_count = 0

    def prepare(self, model: Any, conditionals_cls: type[Any]) -> dict[str, Any]:
        actual_reference_hash = sha256_file(self.reference).lower()
        if actual_reference_hash != CANDIDATE_B_SHA256:
            raise RuntimeError("fixed Candidate B SHA-256 mismatch")
        inputs = self._inputs()
        lookup = self.cache.load(inputs, conditionals_cls)
        if lookup.hit:
            conditionals = lookup.conditionals
            if hasattr(conditionals, "to"):
                conditionals = conditionals.to(getattr(model, "device", "cpu"))
            model.conds = conditionals
            self.prepare_count += 1
            return {
                "status": "hit",
                "cache_key": inputs.cache_key(),
                "reference_sha256": actual_reference_hash,
                "condition_prepare_count": self.prepare_count,
            }
        if lookup.reason is not CacheMissReason.MANIFEST_MISSING or self.cache.artifact_path.exists():
            reason = lookup.reason.value if lookup.reason is not None else "unknown"
            raise RuntimeError(f"Candidate B conditionals cache is not trusted: {reason}")
        model.prepare_conditionals(str(self.reference), exaggeration=EXAGGERATION)
        manifest = self.cache.store(inputs, model.conds)
        self.prepare_count += 1
        return {
            "status": "created",
            "cache_key": manifest.cache_key,
            "reference_sha256": actual_reference_hash,
            "condition_prepare_count": self.prepare_count,
        }

    def _inputs(self) -> ConditionalsCacheInputs:
        snapshot = _find_snapshot(self.runtime_root)
        source = self.runtime_root / "chatterbox" / "src" / "chatterbox" / "mtl_tts.py"
        return ConditionalsCacheInputs.from_files(
            repo_root=self.repo_root,
            chatterbox_source_version=f"mtl_tts_sha256:{sha256_file(source)}",
            t3_checkpoint=snapshot / "t3_mtl23ls_v3.safetensors",
            s3gen=snapshot / "s3gen.pt",
            voice_encoder=snapshot / "ve.pt",
            tokenizer=snapshot / "grapheme_mtl_merged_expanded_v1.json",
            reference_wav=self.reference,
            language_id=LANGUAGE_ID,
            exaggeration=EXAGGERATION,
        )


def _find_snapshot(runtime_root: Path) -> Path:
    snapshots = sorted((runtime_root / "hf-cache" / "hub" / "models--ResembleAI--chatterbox" / "snapshots").glob("*"))
    valid = [path for path in snapshots if (path / "t3_mtl23ls_v3.safetensors").is_file()]
    if len(valid) != 1:
        raise RuntimeError(f"expected exactly one cached Chatterbox snapshot, found {len(valid)}")
    return valid[0]
