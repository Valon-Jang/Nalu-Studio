"""Lazy optional-package capability detection; never imports the package itself."""
from __future__ import annotations
from importlib.util import find_spec
from .contracts import CapabilityStatus, ValidationStatus

def optional_dependency(package: str) -> CapabilityStatus:
    if not package: raise ValueError("package is required")
    available = find_spec(package) is not None
    return CapabilityStatus(package, ValidationStatus.PASS if available else ValidationStatus.NOT_RUN, package=package, detail="available" if available else "not installed")
