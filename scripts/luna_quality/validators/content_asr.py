"""Deterministic content comparison, separate from optional WhisperX timing."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Iterable

from ..adapters.whisperx_adapter import AsrOutput, WordTimestamp
from ..contracts import ValidationResult, ValidationStatus
from ..hashing import sha256_text
from ..text_normalization import normalized_tokens


@dataclass(frozen=True)
class ContentComparison:
    normalized_expected: str
    normalized_actual: str
    edit_distance: int
    normalized_edit_distance: float
    deletions: int
    insertions: int
    substitutions: int
    critical_terms_missing: list[str]
    repetitions: list[str]
    unexpected_continuation: bool


def compare_content(expected_text: str, asr_text: str, critical_terms: Iterable[str] = ()) -> ContentComparison:
    expected, actual = normalized_tokens(expected_text), normalized_tokens(asr_text)
    distance, deletes, inserts, substitutes = _levenshtein(expected, actual)
    missing = [term for term in critical_terms if not _contains(actual, normalized_tokens(term))]
    repetitions = _unexpected_repetitions(expected, actual)
    continuation = bool(actual[len(expected):]) if actual[: len(expected)] == expected else False
    return ContentComparison(" ".join(expected), " ".join(actual), distance, distance / max(1, len(expected)), deletes, inserts, substitutes, missing, repetitions, continuation)


class ContentAsrValidator:
    validator_name = "content_asr"
    validator_version = "content-asr/1"

    def validate(self, expected_text: str, asr_output: AsrOutput, critical_terms: Iterable[str] = ()) -> ValidationResult:
        started = _now()
        source_hashes = {"expected_text_sha256": sha256_text(expected_text)}
        if asr_output.status is not ValidationStatus.PASS:
            return ValidationResult(self.validator_name, self.validator_version, asr_output.status, True, reasons=[asr_output.reason or "asr_not_available"], metrics={"timing_status": asr_output.status.value}, source_hashes=source_hashes, started_at=started, finished_at=_now())
        comparison = compare_content(expected_text, asr_output.text, critical_terms)
        reasons = []
        if comparison.edit_distance: reasons.append("content_mismatch")
        if comparison.critical_terms_missing: reasons.append("critical_term_missing")
        if comparison.repetitions: reasons.append("unexpected_repetition")
        if comparison.unexpected_continuation: reasons.append("unexpected_continuation")
        metrics = {
            "normalized_edit_distance": comparison.normalized_edit_distance, "edit_distance": comparison.edit_distance,
            "deletions": comparison.deletions, "insertions": comparison.insertions, "substitutions": comparison.substitutions,
            "critical_term_match": not comparison.critical_terms_missing, "repetition_detected": bool(comparison.repetitions),
            "unexpected_continuation": comparison.unexpected_continuation, "timing_word_count": len(asr_output.words),
        }
        return ValidationResult(self.validator_name, self.validator_version, ValidationStatus.FAIL if reasons else ValidationStatus.PASS, True, reasons=reasons, metrics=metrics, artifacts={}, source_hashes=source_hashes, started_at=started, finished_at=_now())

    def extract_timing(self, asr_output: AsrOutput) -> list[WordTimestamp] | None:
        """Return timing independently; unavailable alignment is never content success."""
        return list(asr_output.words) if asr_output.status is ValidationStatus.PASS and asr_output.words else None


def _levenshtein(expected: list[str], actual: list[str]) -> tuple[int, int, int, int]:
    rows = [[(0, index, 0, 0) for index in range(len(actual) + 1)]]
    for index in range(1, len(expected) + 1): rows.append([(index, 0, index, 0)])
    for i, left in enumerate(expected, 1):
        for j, right in enumerate(actual, 1):
            candidates = [
                (rows[i - 1][j][0] + 1, rows[i - 1][j][1], rows[i - 1][j][2] + 1, rows[i - 1][j][3]),
                (rows[i][j - 1][0] + 1, rows[i][j - 1][1] + 1, rows[i][j - 1][2], rows[i][j - 1][3]),
                (rows[i - 1][j - 1][0] + (left != right), rows[i - 1][j - 1][1], rows[i - 1][j - 1][2], rows[i - 1][j - 1][3] + (left != right)),
            ]
            rows[i].append(min(candidates, key=lambda item: item[0]))
    distance, insertions, deletions, substitutions = rows[-1][-1]
    return distance, deletions, insertions, substitutions


def _contains(tokens: list[str], needle: list[str]) -> bool:
    return bool(needle) and any(tokens[index : index + len(needle)] == needle for index in range(len(tokens) - len(needle) + 1))


def _unexpected_repetitions(expected: list[str], actual: list[str]) -> list[str]:
    repeated = []
    for index in range(1, len(actual)):
        if actual[index] == actual[index - 1] and actual[index:index + 1] != expected[index:index + 1]: repeated.append(actual[index])
    return repeated


def _now() -> str: return datetime.now(timezone.utc).isoformat()
