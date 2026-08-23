"""Optional SpeechBrain ECAPA adapter; no import or model load at module import."""
from __future__ import annotations
from pathlib import Path
from ..capability import optional_dependency
from ..contracts import CapabilityStatus, ValidationStatus

class SpeechBrainAdapter:
    model_id = "speechbrain/spkrec-ecapa-voxceleb"; model_revision = "unresolved"
    def __init__(self, model: object | None = None, package_name: str = "speechbrain"): self.model, self.package_name = model, package_name
    def capability(self) -> CapabilityStatus: return optional_dependency(self.package_name)
    def score(self, left: str | Path, right: str | Path) -> float | None:
        if self.model is None: return None
        score, _ = self.model.verify_files(str(left), str(right)); return float(score)
