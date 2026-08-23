"""Shadow-only speaker evidence and calibration; no default Luna threshold."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable
from ..adapters.chatterbox_ve_adapter import ChatterboxVEAdapter
from ..adapters.speechbrain_adapter import SpeechBrainAdapter
from ..contracts import ValidationResult, ValidationStatus

@dataclass(frozen=True)
class CalibrationSample:
    group: str; primary_score: float; secondary_score: float | None = None

def calibrate(samples: Iterable[CalibrationSample]) -> dict:
    rows = list(samples); groups = {name: [r.primary_score for r in rows if r.group == name] for name in ("candidate_b", "approved_luna", "drift_rejected", "same_speaker_low_quality")}
    if any(not groups[name] for name in ("candidate_b", "approved_luna", "drift_rejected")):
        return {"status": "insufficient_data", "sample_count": len(rows), "groups": {k: len(v) for k,v in groups.items()}}
    positive = groups["candidate_b"] + groups["approved_luna"]; negative = groups["drift_rejected"]
    threshold = (min(positive) + max(negative)) / 2
    return {"status": "calibrated_candidate", "sample_count": len(rows), "recommended_threshold_candidate": threshold, "false_accept_count": sum(x >= threshold for x in negative), "false_reject_count": sum(x < threshold for x in positive), "groups": {k: {"count": len(v), "min": min(v) if v else None, "max": max(v) if v else None} for k,v in groups.items()}}

class SpeakerIdentityValidator:
    validator_name = "speaker_identity"; validator_version = "speaker-identity/1"
    def __init__(self, primary: ChatterboxVEAdapter, secondary: SpeechBrainAdapter | None = None, calibration: dict | None = None): self.primary, self.secondary, self.calibration = primary, secondary, calibration
    def validate(self, candidate_wav, reference_wav) -> ValidationResult:
        started = _now(); candidate, candidate_hash, candidate_cached = self.primary.embed(candidate_wav); reference, reference_hash, reference_cached = self.primary.embed(reference_wav)
        if candidate is None or reference is None:
            return ValidationResult(self.validator_name, self.validator_version, ValidationStatus.NOT_RUN, False, reasons=["chatterbox_ve_not_bound"], metrics={"primary_cache_hit": candidate_cached or reference_cached}, source_hashes={"candidate": candidate_hash, "reference": reference_hash}, started_at=started, finished_at=_now())
        primary_score = self.primary.cosine(candidate, reference); secondary_score = self.secondary.score(candidate_wav, reference_wav) if self.secondary else None
        calibrated = bool(self.calibration and self.calibration.get("status") == "calibrated_candidate")
        metrics = {"primary_chatterbox_similarity": primary_score, "primary_cache_hit": candidate_cached and reference_cached, "secondary_speechbrain_status": "not_run" if secondary_score is None else "pass", "model_revision": self.primary.model_revision, "calibrated": calibrated}
        if secondary_score is not None: metrics["secondary_speechbrain_similarity"] = secondary_score
        return ValidationResult(self.validator_name, self.validator_version, ValidationStatus.UNKNOWN if not calibrated else ValidationStatus.PASS, calibrated, score=primary_score, reasons=[] if calibrated else ["insufficient_calibration"], metrics=metrics, source_hashes={"candidate": candidate_hash, "reference": reference_hash}, started_at=started, finished_at=_now())
def _now(): return datetime.now(timezone.utc).isoformat()
