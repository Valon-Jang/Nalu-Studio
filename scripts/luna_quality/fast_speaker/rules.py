"""Hot-reloadable, FAST-test-only text overlay.

This module deliberately owns only optional text substitutions. It never
loads a model, reference audio, or Chatterbox generation settings.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping


RULE_SCHEMA_VERSION = "luna-fast-speaker-rules/1"
_ALLOWED_KEYS = frozenset({"schema_version", "rules_version", "text_replacements"})


@dataclass(frozen=True)
class FastTestRules:
    """The entire supported rule surface for a live FAST-test reload."""

    rules_version: str
    text_replacements: Mapping[str, str]

    def apply(self, text: str) -> str:
        result = text
        for source, replacement in self.text_replacements.items():
            result = result.replace(source, replacement)
        return result


@dataclass(frozen=True)
class ReloadResult:
    ok: bool
    message: str
    active_rules_version: str
    requires_worker_restart: bool = False


class FastTestRuleOverlay:
    """Transactional rule loader; a bad candidate can never replace active rules."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._active = FastTestRules("built-in-noop", {})

    @property
    def active(self) -> FastTestRules:
        return self._active

    def apply(self, text: str) -> str:
        return self._active.apply(text)

    def reload(self) -> ReloadResult:
        try:
            candidate = self._load_candidate()
        except (OSError, ValueError, json.JSONDecodeError) as error:
            return ReloadResult(False, f"Rules unchanged: {type(error).__name__}: {error}", self._active.rules_version)
        self._active = candidate
        return ReloadResult(True, f"Rules reloaded: {candidate.rules_version}", candidate.rules_version)

    def _load_candidate(self) -> FastTestRules:
        value: Any = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(value, Mapping):
            raise ValueError("rule file must contain a JSON object")
        unknown = set(value) - _ALLOWED_KEYS
        if unknown:
            raise ValueError(f"unsupported reload keys: {', '.join(sorted(unknown))}")
        if value.get("schema_version") != RULE_SCHEMA_VERSION:
            raise ValueError(f"unsupported rule schema: {value.get('schema_version')!r}")
        version = value.get("rules_version")
        replacements = value.get("text_replacements")
        if not isinstance(version, str) or not version.strip():
            raise ValueError("rules_version must be a non-empty string")
        if not isinstance(replacements, Mapping):
            raise ValueError("text_replacements must be an object")
        validated: dict[str, str] = {}
        for source, replacement in replacements.items():
            if not isinstance(source, str) or not source:
                raise ValueError("text replacement sources must be non-empty strings")
            if not isinstance(replacement, str):
                raise ValueError("text replacement values must be strings")
            validated[source] = replacement
        return FastTestRules(version.strip(), validated)
