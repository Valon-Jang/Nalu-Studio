"""Conservative text canonicalisation for offline ASR-content comparison.

The normaliser compares *expected pronunciations*, not spelling preferences.
It deliberately handles only the explicitly supported Korean number, unit, and
Latin-abbreviation forms.  Unknown mixed terms remain literal rather than
being assigned an unverified pronunciation.
"""
from __future__ import annotations

import re
import unicodedata

_DIGITS = ("영", "일", "이", "삼", "사", "오", "육", "칠", "팔", "구")
_SMALL_UNITS = ((1000, "천"), (100, "백"), (10, "십"))
_UNIT_WORDS = {"%": "퍼센트", "kg": "킬로그램", "km": "킬로미터", "hz": "헤르츠", "ms": "밀리초"}
_LETTER_NAMES = {
    "A": "에이", "B": "비", "C": "씨", "D": "디", "E": "이", "F": "에프", "G": "지",
    "H": "에이치", "I": "아이", "J": "제이", "K": "케이", "L": "엘", "M": "엠", "N": "엔",
    "O": "오", "P": "피", "Q": "큐", "R": "알", "S": "에스", "T": "티", "U": "유", "V": "브이",
    "W": "더블유", "X": "엑스", "Y": "와이", "Z": "지",
}
_PUNCTUATION = re.compile(r"[\.,!?;:\(\)\[\]\{\}\"'“”‘’·/\\_\-]+")


def normalize_expected_pronunciation(text: str) -> str:
    """Return a whitespace-tokenised comparison form for supported inputs."""
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    value = unicodedata.normalize("NFKC", text).strip()
    value = _replace_numbers_and_units(value)
    value = _replace_latin_abbreviations(value)
    value = _PUNCTUATION.sub(" ", value)
    return " ".join(value.lower().split())


def normalized_tokens(text: str) -> list[str]:
    return normalize_expected_pronunciation(text).split()


def _replace_numbers_and_units(text: str) -> str:
    # Explicit units are normalized before generic alphabet handling.
    pattern = re.compile(r"(?<![\w])([+-]?\d+(?:\.\d+)?)(%|kg|km|hz|ms)(?![A-Za-z])", re.IGNORECASE)
    text = pattern.sub(lambda match: f"{_spoken_number(match.group(1))} {_UNIT_WORDS[match.group(2).lower()]}", text)
    text = re.sub(r"(?<!\d)(1[89]\d{2}|20\d{2})년", lambda m: f"{_spoken_number(m.group(1))} 년", text)
    return re.sub(r"(?<![\w])([+-]?\d+(?:\.\d+)?)(?![\w])", lambda m: _spoken_number(m.group(1)), text)


def _replace_latin_abbreviations(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        token = match.group(0)
        # Lower-case words and mixed identifiers are intentionally left literal.
        return " ".join(_LETTER_NAMES[letter] for letter in token) if token.isupper() else token
    return re.sub(r"\b[A-Za-z]{2,}\b", replace, text)


def _spoken_number(value: str) -> str:
    sign = "마이너스 " if value.startswith("-") else ""
    value = value.lstrip("+-").replace(",", "")
    if "." in value:
        whole, fraction = value.split(".", 1)
        return f"{sign}{_sino_integer(int(whole))} 점 {' '.join(_DIGITS[int(d)] for d in fraction)}"
    return sign + _sino_integer(int(value))


def _sino_integer(value: int) -> str:
    if value == 0: return _DIGITS[0]
    large_units = ((10**12, "조"), (10**8, "억"), (10**4, "만"))
    parts: list[str] = []
    for divisor, label in large_units:
        amount, value = divmod(value, divisor)
        if amount: parts.append(_under_ten_thousand(amount) + label)
    if value: parts.append(_under_ten_thousand(value))
    return " ".join(parts)


def _under_ten_thousand(value: int) -> str:
    parts: list[str] = []
    for divisor, label in _SMALL_UNITS:
        amount, value = divmod(value, divisor)
        if amount: parts.append(("" if amount == 1 else _DIGITS[amount]) + label)
    if value: parts.append(_DIGITS[value])
    return "".join(parts)
