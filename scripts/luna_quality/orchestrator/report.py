"""Safe, deterministic serialization for shadow reports only."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from .engine import ShadowRunResult


def write_shadow_report(result: ShadowRunResult, report_path: str | Path, source_outdir: str | Path) -> Path:
    destination = Path(report_path).resolve()
    source = Path(source_outdir).resolve()
    if _is_within(destination, source):
        raise ValueError("shadow report must be outside the read-only outdir")
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = _json_safe(result.report)
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return destination


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _json_safe(value: Any) -> Any:
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value
