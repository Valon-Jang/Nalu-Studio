"""Default-off S10 bridge between the Luna production entry point and S08.

This module never changes production files by itself.  The entry point calls a
single session hook only when at least one explicit ``LUNA_*`` integration
setting is non-default.  Shadow reports live outside the production output
directory, and select mode requires a user approval manifest plus exact
artifact hashes before it can propose a take.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .adapters.chatterbox_ve_adapter import ChatterboxVEAdapter
from .adapters.whisperx_adapter import WhisperXAdapter
from .conditionals.cache import CacheMissReason, ConditionalsCache
from .conditionals.manifest import ConditionalsCacheInputs
from .contracts import ValidationResult
from .hashing import sha256_file, sha256_text
from .orchestrator.engine import DiscoveredTake, ShadowOrchestrator
from .ranking.artifact import load_artifact
from .ranking.features import FEATURE_NAMES
from .validators.content_asr import ContentAsrValidator
from .validators.speaker_identity import SpeakerIdentityValidator

INTEGRATION_SCHEMA_VERSION = "luna-production-integration/1"
SELECT_APPROVAL_SCHEMA_VERSION = "luna-production-select-approval/1"
CANDIDATE_B_SHA256 = "30c6d3405f46684af467c7d26ff40a2fb57dd48cc84cd24cf7403d9aa00a2bb9"

FEATURE_ENV_DEFAULTS = {
    "LUNA_QUALITY_MODE": "off",
    "LUNA_CONDITIONALS_CACHE": "off",
    "LUNA_ASR_VALIDATOR": "off",
    "LUNA_SPEAKER_VALIDATOR": "off",
    "LUNA_MOS_VALIDATOR": "off",
    "LUNA_PREFERENCE_RANKER": "off",
    "LUNA_HYBRID_SYNTHESIS": "off",
}
SETTING_ENV_NAMES = (
    "LUNA_QUALITY_REPORT_DIR",
    "LUNA_CONDITIONALS_CACHE_DIR",
    "LUNA_RANKER_ARTIFACT",
    "LUNA_SPEAKER_CALIBRATION_ARTIFACT",
    "LUNA_SELECT_APPROVAL_MANIFEST",
)
_ALLOWED = {
    "LUNA_QUALITY_MODE": {"off", "shadow", "select"},
    "LUNA_CONDITIONALS_CACHE": {"off", "on"},
    "LUNA_ASR_VALIDATOR": {"off", "on"},
    "LUNA_SPEAKER_VALIDATOR": {"off", "on"},
    "LUNA_MOS_VALIDATOR": {"off", "on"},
    "LUNA_PREFERENCE_RANKER": {"off", "shadow", "select"},
    "LUNA_HYBRID_SYNTHESIS": {"off", "experiment"},
}


@dataclass(frozen=True)
class FeatureFlags:
    quality_mode: str = "off"
    conditionals_cache: str = "off"
    asr_validator: str = "off"
    speaker_validator: str = "off"
    mos_validator: str = "off"
    preference_ranker: str = "off"
    hybrid_synthesis: str = "off"
    report_dir: str | None = None
    conditionals_cache_dir: str | None = None
    ranker_artifact: str | None = None
    speaker_calibration_artifact: str | None = None
    select_approval_manifest: str | None = None

    @classmethod
    def from_environment(cls, environ: Mapping[str, str] | None = None) -> "FeatureFlags":
        source = os.environ if environ is None else environ
        values: dict[str, str] = {}
        for name, default in FEATURE_ENV_DEFAULTS.items():
            value = str(source.get(name, default)).strip().lower()
            if value not in _ALLOWED[name]:
                raise ValueError(f"invalid {name}; expected one of {sorted(_ALLOWED[name])}")
            values[name] = value
        setting = lambda name: str(source[name]).strip() if source.get(name) else None
        return cls(
            quality_mode=values["LUNA_QUALITY_MODE"],
            conditionals_cache=values["LUNA_CONDITIONALS_CACHE"],
            asr_validator=values["LUNA_ASR_VALIDATOR"],
            speaker_validator=values["LUNA_SPEAKER_VALIDATOR"],
            mos_validator=values["LUNA_MOS_VALIDATOR"],
            preference_ranker=values["LUNA_PREFERENCE_RANKER"],
            hybrid_synthesis=values["LUNA_HYBRID_SYNTHESIS"],
            report_dir=setting("LUNA_QUALITY_REPORT_DIR"),
            conditionals_cache_dir=setting("LUNA_CONDITIONALS_CACHE_DIR"),
            ranker_artifact=setting("LUNA_RANKER_ARTIFACT"),
            speaker_calibration_artifact=setting("LUNA_SPEAKER_CALIBRATION_ARTIFACT"),
            select_approval_manifest=setting("LUNA_SELECT_APPROVAL_MANIFEST"),
        )

    def feature_dict(self) -> dict[str, str]:
        return {
            "LUNA_QUALITY_MODE": self.quality_mode,
            "LUNA_CONDITIONALS_CACHE": self.conditionals_cache,
            "LUNA_ASR_VALIDATOR": self.asr_validator,
            "LUNA_SPEAKER_VALIDATOR": self.speaker_validator,
            "LUNA_MOS_VALIDATOR": self.mos_validator,
            "LUNA_PREFERENCE_RANKER": self.preference_ranker,
            "LUNA_HYBRID_SYNTHESIS": self.hybrid_synthesis,
        }

    def to_report_dict(self) -> dict[str, Any]:
        return {
            "features": self.feature_dict(),
            "ranker_artifact_configured": bool(self.ranker_artifact),
            "speaker_calibration_configured": bool(self.speaker_calibration_artifact),
            "select_approval_configured": bool(self.select_approval_manifest),
        }


def integration_requested(environ: Mapping[str, str] | None = None) -> bool:
    source = os.environ if environ is None else environ
    for name, default in FEATURE_ENV_DEFAULTS.items():
        if str(source.get(name, default)).strip().lower() != default:
            return True
    return any(bool(str(source.get(name, "")).strip()) for name in SETTING_ENV_NAMES)


def selection_config_hash(flags: FeatureFlags, ranker_sha256: str | None, calibration_sha256: str | None) -> str:
    payload = {
        "schema_version": INTEGRATION_SCHEMA_VERSION,
        "features": flags.feature_dict(),
        "ranker_artifact_sha256": ranker_sha256,
        "speaker_calibration_sha256": calibration_sha256,
    }
    return sha256_text(json.dumps(payload, sort_keys=True, separators=(",", ":")))


class ProductionQualitySession:
    """One production-process integration session; default behaviour is off."""

    def __init__(
        self,
        repo_root: str | Path,
        outdir: str | Path,
        model: Any,
        flags: FeatureFlags,
    ) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.outdir = Path(outdir).resolve()
        self.model = model
        self.flags = flags
        self.report_root = self._report_root()
        self.conditionals_cache_active = False
        self.conditionals_status: dict[str, Any] = {"status": "off"}
        self.diagnostics: list[str] = []
        self._block_reports: dict[str, Path] = {}

        if flags.conditionals_cache == "on":
            self.conditionals_cache_active, self.conditionals_status = self._configure_conditionals_cache()
        if flags.hybrid_synthesis == "experiment":
            self.diagnostics.append("hybrid_experiment_not_promoted_s09_has_no_real_audio_evidence")
        if flags.mos_validator == "on":
            self.diagnostics.append("mos_adapter_not_available_in_verified_s03_s08_scope")
        if flags.quality_mode == "off" and any(
            value != "off" for value in (flags.asr_validator, flags.speaker_validator, flags.mos_validator, flags.preference_ranker)
        ):
            self.diagnostics.append("quality_subflags_ignored_while_quality_mode_off")
        self._write_session_report()

    @classmethod
    def from_environment(
        cls,
        repo_root: str | Path,
        outdir: str | Path,
        model: Any,
        environ: Mapping[str, str] | None = None,
    ) -> "ProductionQualitySession":
        return cls(repo_root, outdir, model, FeatureFlags.from_environment(environ))

    def audio_prompt_path(self, candidate_b_path: str | Path) -> str | None:
        return None if self.conditionals_cache_active else str(candidate_b_path)

    def evaluate_block(self, block_id: str) -> dict[int, int]:
        if self.flags.quality_mode == "off":
            return {}
        safe_id = _safe_id(block_id)
        report_path = self.report_root / f"{safe_id}.quality.json"
        try:
            orchestrator = self._orchestrator()
            shadow = orchestrator.evaluate(self.outdir, block_ids={block_id})
            selection = self._selection_assessment(shadow.report, block_id)
            payload = {
                "schema_version": INTEGRATION_SCHEMA_VERSION,
                "block_id": block_id,
                "requested_mode": self.flags.quality_mode,
                "flags": self.flags.to_report_dict(),
                "conditionals_cache": self.conditionals_status,
                "diagnostics": list(self.diagnostics),
                "shadow": shadow.report,
                "selection": selection,
                "production_selection_changed": False,
                "fallback_to_existing_selector": selection["status"] != "approved",
            }
            _atomic_write_json(report_path, payload)
            self._block_reports[block_id] = report_path
            return {int(key): int(value) for key, value in selection.get("proposals", {}).items()} if selection["status"] == "approved" else {}
        except Exception as exc:
            payload = {
                "schema_version": INTEGRATION_SCHEMA_VERSION,
                "block_id": block_id,
                "requested_mode": self.flags.quality_mode,
                "status": "fallback",
                "fallback_reason": f"integration_exception:{type(exc).__name__}",
                "production_selection_changed": False,
                "fallback_to_existing_selector": True,
            }
            _atomic_write_json(report_path, payload)
            self._block_reports[block_id] = report_path
            return {}

    def finalize_block(
        self,
        block_id: str,
        *,
        baseline_picks: list[int],
        final_picks: list[int],
        guard: Mapping[str, Any],
    ) -> None:
        path = self._block_reports.get(block_id)
        if path is None or not path.is_file():
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            changed = list(baseline_picks) != list(final_picks)
            payload["selection_outcome"] = {
                "baseline_picks": list(baseline_picks),
                "final_picks": list(final_picks),
                "guard": dict(guard),
            }
            payload["production_selection_changed"] = changed
            payload["fallback_to_existing_selector"] = not changed
            _atomic_write_json(path, payload)
        except Exception:
            # A report update can never invalidate already-safe production picks.
            return

    def _report_root(self) -> Path:
        if self.flags.report_dir:
            root = _resolve_path(self.repo_root, self.flags.report_dir)
        else:
            root = self.outdir.parent / f"{self.outdir.name}.luna_quality_reports"
        root = root.resolve()
        if _is_within(root, self.outdir):
            raise ValueError("LUNA_QUALITY_REPORT_DIR must be outside production OUTDIR")
        return root

    def _write_session_report(self) -> None:
        _atomic_write_json(
            self.report_root / "session.json",
            {
                "schema_version": INTEGRATION_SCHEMA_VERSION,
                "flags": self.flags.to_report_dict(),
                "conditionals_cache": self.conditionals_status,
                "diagnostics": list(self.diagnostics),
                "production_selection_changed": False,
                "rollback": "set every required LUNA feature flag to off",
            },
        )

    def _orchestrator(self) -> ShadowOrchestrator:
        content_runner = self._content_runner() if self.flags.asr_validator == "on" else None
        speaker_runner = self._speaker_runner() if self.flags.speaker_validator == "on" else None
        ranker_path = None
        if self.flags.preference_ranker in {"shadow", "select"} and self.flags.ranker_artifact:
            ranker_path = _resolve_path(self.repo_root, self.flags.ranker_artifact)
        return ShadowOrchestrator(
            content_runner=content_runner,
            speaker_runner=speaker_runner,
            mos_runner=None,
            ranker_artifact=ranker_path,
        )

    @staticmethod
    def _content_runner():
        adapter = WhisperXAdapter()
        validator = ContentAsrValidator()

        def run(take: DiscoveredTake) -> ValidationResult:
            return validator.validate(str(take.row.get("text") or ""), adapter.transcribe(take.wav_path))

        return run

    def _speaker_runner(self):
        calibration = self._calibration_payload()
        cache_dir = self.report_root / ".private_embeddings"
        primary = ChatterboxVEAdapter(getattr(self.model, "ve", None), cache_dir)
        validator = SpeakerIdentityValidator(primary, calibration=calibration)
        reference = self.repo_root / "assets" / "voice_ref" / "B_voiced_spectral_micro_smooth.wav"

        def run(take: DiscoveredTake) -> ValidationResult:
            return validator.validate(take.wav_path, reference)

        return run

    def _calibration_payload(self) -> dict[str, Any] | None:
        if not self.flags.speaker_calibration_artifact:
            return None
        path = _resolve_path(self.repo_root, self.flags.speaker_calibration_artifact)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return dict(payload) if isinstance(payload, dict) else None
        except (OSError, ValueError, TypeError):
            return None

    def _selection_assessment(self, shadow_report: Mapping[str, Any], block_id: str) -> dict[str, Any]:
        assessment: dict[str, Any] = {"status": "fallback", "reasons": [], "proposals": {}}
        reasons: list[str] = assessment["reasons"]
        if self.flags.quality_mode != "select":
            reasons.append("quality_mode_not_select")
            return assessment
        if self.flags.preference_ranker != "select":
            reasons.append("preference_ranker_not_select")
        if self.flags.hybrid_synthesis != "off":
            reasons.append("hybrid_not_approved_for_production_select")
        if self.flags.mos_validator != "off":
            reasons.append("mos_select_not_supported")

        ranker_path = _optional_path(self.repo_root, self.flags.ranker_artifact)
        calibration_path = _optional_path(self.repo_root, self.flags.speaker_calibration_artifact)
        approval_path = _optional_path(self.repo_root, self.flags.select_approval_manifest)
        ranker_hash = sha256_file(ranker_path) if ranker_path and ranker_path.is_file() else None
        calibration_hash = sha256_file(calibration_path) if calibration_path and calibration_path.is_file() else None
        if ranker_hash is None:
            reasons.append("ranker_artifact_missing")
        if calibration_hash is None:
            reasons.append("calibration_artifact_missing")
        ranker_loaded = load_artifact(ranker_path) if ranker_path else None
        if ranker_loaded is None or ranker_loaded.ranker is None:
            reasons.append(f"ranker_disabled:{ranker_loaded.reason if ranker_loaded else 'not_configured'}")
        calibration = _read_json_object(calibration_path)
        calibration_threshold = _finite(
            calibration.get("recommended_threshold_candidate") if calibration else None)
        if (
            not calibration
            or calibration.get("status") != "calibrated_candidate"
            or calibration_threshold is None
            or not -1.0 <= calibration_threshold <= 1.0
        ):
            reasons.append("calibration_not_approved_candidate")
        approval = _read_json_object(approval_path)
        if not approval or approval.get("schema_version") != SELECT_APPROVAL_SCHEMA_VERSION:
            reasons.append("select_approval_missing_or_schema_mismatch")
        if reasons:
            return assessment

        config_hash = selection_config_hash(self.flags, ranker_hash, calibration_hash)
        assessment["feature_config_sha256"] = config_hash
        if approval.get("approved_by") != "USER" or approval.get("approved_for_production_select") is not True:
            reasons.append("select_not_user_approved")
        if approval.get("ranker_artifact_sha256") != ranker_hash:
            reasons.append("approved_ranker_hash_mismatch")
        if approval.get("speaker_calibration_sha256") != calibration_hash:
            reasons.append("approved_calibration_hash_mismatch")
        if approval.get("feature_config_sha256") != config_hash:
            reasons.append("approved_feature_config_hash_mismatch")
        required = {str(item) for item in approval.get("approved_validators") or []}
        minimum_required = {"audio_sanity", "existing_prosody_gate"}
        if self.flags.asr_validator == "on":
            minimum_required.add("content_asr")
        if self.flags.speaker_validator == "on":
            minimum_required.add("speaker_identity")
        if not minimum_required.issubset(required):
            reasons.append("approved_validator_scope_incomplete")
        confidence = _unit_interval(approval.get("minimum_top_confidence"), "minimum_top_confidence", reasons)
        coverage = _unit_interval(approval.get("minimum_feature_coverage"), "minimum_feature_coverage", reasons)
        if reasons:
            return assessment

        block = next((row for row in shadow_report.get("blocks", []) if row.get("block_id") == block_id), None)
        if block is None:
            reasons.append("shadow_block_missing")
            return assessment
        proposals: dict[str, int] = {}
        unpinned = 0
        phrase_details: list[dict[str, Any]] = []
        for phrase in block.get("phrases", []):
            phrase_id = str(phrase.get("phrase_id") or "")
            phrase_index = int(phrase_id[1:]) if re.fullmatch(r"P\d+", phrase_id) else -1
            actual = phrase.get("actual_selection") or {}
            if actual.get("source") == "pins":
                phrase_details.append({"phrase_id": phrase_id, "status": "pin_preserved"})
                continue
            unpinned += 1
            eligible = [take for take in phrase.get("takes", []) if _select_eligible(take, required, coverage)]
            if len(eligible) < 2:
                phrase_details.append({"phrase_id": phrase_id, "status": "fallback", "reason": "fewer_than_two_eligible_survivors"})
                continue
            ranked = ranker_loaded.ranker.rank_candidates(eligible, confidence_threshold=confidence)
            ranked_rows = [row for row in ranked["results"] if row["status"] == "ranked"]
            if not ranked["candidate_reduction_allowed"] or not ranked_rows:
                phrase_details.append({"phrase_id": phrase_id, "status": "fallback", "reason": "confidence_or_coverage_below_threshold"})
                continue
            proposals[str(phrase_index)] = int(ranked_rows[0]["take_id"])
            phrase_details.append(
                {
                    "phrase_id": phrase_id,
                    "status": "approved_proposal",
                    "take_id": int(ranked_rows[0]["take_id"]),
                    "top_confidence": ranked["top_confidence"],
                }
            )
        assessment["phrase_details"] = phrase_details
        if unpinned == 0:
            reasons.append("all_phrases_pinned")
        elif len(proposals) != unpinned:
            reasons.append("not_all_unpinned_phrases_met_select_policy")
        if reasons:
            return assessment
        assessment["status"] = "approved"
        assessment["proposals"] = proposals
        return assessment

    def _configure_conditionals_cache(self) -> tuple[bool, dict[str, Any]]:
        try:
            reference = self.repo_root / "assets" / "voice_ref" / "B_voiced_spectral_micro_smooth.wav"
            if sha256_file(reference).lower() != CANDIDATE_B_SHA256:
                return False, {"status": "fallback", "reason": "candidate_b_hash_mismatch"}
            snapshot = _find_snapshot(self.repo_root / "engine" / "chatterbox-v3")
            source = self.repo_root / "engine" / "chatterbox-v3" / "chatterbox" / "src" / "chatterbox" / "mtl_tts.py"
            inputs = ConditionalsCacheInputs.from_files(
                repo_root=self.repo_root,
                chatterbox_source_version=f"mtl_tts_sha256:{sha256_file(source)}",
                t3_checkpoint=snapshot / "t3_mtl23ls_v3.safetensors",
                s3gen=snapshot / "s3gen.pt",
                voice_encoder=snapshot / "ve.pt",
                tokenizer=snapshot / "grapheme_mtl_merged_expanded_v1.json",
                reference_wav=reference,
                language_id="ko",
                exaggeration=0.5,
            )
            cache_dir = (
                _resolve_path(self.repo_root, self.flags.conditionals_cache_dir)
                if self.flags.conditionals_cache_dir
                else self.repo_root / ".luna_quality_cache" / "conditionals"
            )
            cache = ConditionalsCache(cache_dir)
            conditionals_cls = type(self.model.conds) if getattr(self.model, "conds", None) is not None else _conditionals_class()
            lookup = cache.load(inputs, conditionals_cls)
            if lookup.hit:
                conditionals = lookup.conditionals.to("cpu") if hasattr(lookup.conditionals, "to") else lookup.conditionals
                self.model.conds = conditionals
                return True, {"status": "hit", "cache_key": inputs.cache_key()}
            if lookup.reason is not CacheMissReason.MANIFEST_MISSING:
                return False, {"status": "fallback", "reason": lookup.reason.value, "cache_key": inputs.cache_key()}
            if cache.artifact_path.exists():
                return False, {
                    "status": "fallback",
                    "reason": "untrusted_artifact_without_manifest",
                    "cache_key": inputs.cache_key(),
                }
            self.model.prepare_conditionals(str(reference), exaggeration=0.5)
            manifest = cache.store(inputs, self.model.conds)
            return True, {"status": "created", "cache_key": manifest.cache_key}
        except Exception as exc:
            return False, {"status": "fallback", "reason": f"cache_exception:{type(exc).__name__}"}


def write_startup_fallback_report(
    repo_root: str | Path,
    outdir: str | Path,
    error: Exception,
    environ: Mapping[str, str] | None = None,
) -> Path | None:
    """Best-effort report for a session-construction failure; never re-raise."""
    try:
        root = Path(repo_root).resolve()
        output = Path(outdir).resolve()
        source = os.environ if environ is None else environ
        configured = source.get("LUNA_QUALITY_REPORT_DIR")
        report_root = _resolve_path(root, configured) if configured else output.parent / f"{output.name}.luna_quality_reports"
        if _is_within(report_root.resolve(), output):
            report_root = output.parent / f"{output.name}.luna_quality_reports"
        path = report_root / "startup_fallback.json"
        _atomic_write_json(
            path,
            {
                "schema_version": INTEGRATION_SCHEMA_VERSION,
                "status": "fallback",
                "reason": f"session_exception:{type(error).__name__}",
                "production_selection_changed": False,
            },
        )
        return path
    except Exception:
        return None


def _select_eligible(take: Mapping[str, Any], required_validators: set[str], minimum_coverage: float) -> bool:
    if take.get("hard_gate_pass") is not True:
        return False
    statuses = {str(row.get("validator_name")): str(row.get("status")) for row in take.get("validations") or []}
    if any(statuses.get(name) != "pass" for name in required_validators):
        return False
    features = take.get("ranking_features") or {}
    available = sum(_finite(features.get(name)) is not None for name in FEATURE_NAMES)
    return available / len(FEATURE_NAMES) >= minimum_coverage


def _unit_interval(value: Any, name: str, reasons: list[str]) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        reasons.append(f"invalid_{name}")
        return 1.0
    if not math.isfinite(number) or not 0.0 <= number <= 1.0:
        reasons.append(f"invalid_{name}")
    return number


def _finite(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _find_snapshot(runtime: Path) -> Path:
    snapshots = runtime / "hf-cache" / "hub" / "models--ResembleAI--chatterbox" / "snapshots"
    required = {"t3_mtl23ls_v3.safetensors", "s3gen.pt", "ve.pt", "grapheme_mtl_merged_expanded_v1.json"}
    matches = [path for path in snapshots.iterdir() if path.is_dir() and all((path / name).is_file() for name in required)]
    if len(matches) != 1:
        raise ValueError("expected exactly one complete pinned Chatterbox snapshot")
    return matches[0]


def _conditionals_class():
    from chatterbox.mtl_tts import Conditionals

    return Conditionals


def _read_json_object(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return dict(value) if isinstance(value, dict) else None
    except (OSError, ValueError, TypeError):
        return None


def _optional_path(root: Path, value: str | None) -> Path | None:
    return _resolve_path(root, value) if value else None


def _resolve_path(root: Path, value: str | Path) -> Path:
    path = Path(value)
    return (path if path.is_absolute() else root / path).resolve()


def _safe_id(value: str) -> str:
    raw = str(value)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", raw)
    if safe != raw or not safe:
        safe = f"{safe[:60] or 'block'}-{digest}"
    return safe[:80]


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    encoded = json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
