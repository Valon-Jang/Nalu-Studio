import unittest
import sys
from types import SimpleNamespace
from unittest.mock import patch

from scripts.luna_quality.adapters.whisperx_adapter import AsrOutput, WhisperXAdapter, WordTimestamp, _alignment_segments
from scripts.luna_quality.contracts import CapabilityStatus, ValidationStatus
from scripts.luna_quality.text_normalization import normalize_expected_pronunciation
from scripts.luna_quality.validators.content_asr import ContentAsrValidator, compare_content


class ContentAsrTest(unittest.TestCase):
    def setUp(self): self.validator = ContentAsrValidator()
    def test_identical_sentence_passes(self):
        result = self.validator.validate("루나는 오늘 출발합니다.", AsrOutput(ValidationStatus.PASS, "루나는 오늘 출발합니다"))
        self.assertEqual(result.status, ValidationStatus.PASS); self.assertEqual(result.metrics["normalized_edit_distance"], 0.0)
    def test_deletion_and_critical_term_are_explicit(self):
        result = self.validator.validate("루나는 오늘 서울에서 출발합니다", AsrOutput(ValidationStatus.PASS, "루나는 오늘 출발합니다"), ["서울"])
        self.assertEqual(result.status, ValidationStatus.FAIL); self.assertEqual(result.metrics["deletions"], 1); self.assertIn("critical_term_missing", result.reasons)
    def test_insertion_and_unexpected_continuation_are_explicit(self):
        result = self.validator.validate("루나는 출발합니다", AsrOutput(ValidationStatus.PASS, "루나는 출발합니다 지금"))
        self.assertEqual(result.metrics["insertions"], 1); self.assertTrue(result.metrics["unexpected_continuation"])
    def test_repetition_is_explicit(self):
        result = self.validator.validate("루나는 출발합니다", AsrOutput(ValidationStatus.PASS, "루나는 출발합니다 출발합니다"))
        self.assertIn("unexpected_repetition", result.reasons)
    def test_number_and_percent_pronunciation_compare_equal(self):
        compared = compare_content("3.5% 증가", "삼 점 오 퍼센트 증가")
        self.assertEqual(compared.edit_distance, 0)
    def test_english_abbreviation_pronunciation_compares_equal(self):
        compared = compare_content("GPU 성능", "지 피 유 성능")
        self.assertEqual(compared.edit_distance, 0)
    def test_uppercase_acronym_attached_to_hangul_compares_equal(self):
        compared = compare_content("GPU기반 설계", "지 피 유 기반 설계")
        self.assertEqual(compared.edit_distance, 0)
    def test_timing_is_separate_from_content(self):
        output = AsrOutput(ValidationStatus.PASS, "루나", [WordTimestamp("루나", 0.0, 0.3, 0.9)])
        self.assertEqual(self.validator.extract_timing(output)[0].word, "루나")
    def test_alignment_unavailable_is_not_pass(self):
        adapter = WhisperXAdapter(package_name="luna_missing_whisperx")
        self.assertEqual(adapter.alignment_capability().status, ValidationStatus.NOT_RUN)
        output = adapter.transcribe("missing.wav")
        self.assertEqual(output.status, ValidationStatus.NOT_RUN)
    def test_asr_exception_is_unknown(self):
        result = self.validator.validate("루나", AsrOutput(ValidationStatus.UNKNOWN, reason="asr_exception:RuntimeError"))
        self.assertEqual(result.status, ValidationStatus.UNKNOWN); self.assertIn("asr_exception:RuntimeError", result.reasons)
    def test_alignment_keeps_original_asr_segment_bounds(self):
        captured = {}
        fake_whisperx = SimpleNamespace(
            load_align_model=lambda **kwargs: (object(), {}),
            align=lambda segments, *args, **kwargs: captured.setdefault("result", {"segments": segments}) or {"segments": []},
        )
        class AvailableAdapter(WhisperXAdapter):
            def capability(self): return CapabilityStatus("whisperx", ValidationStatus.PASS, package="whisperx")
        output = AsrOutput(ValidationStatus.PASS, "루나 출발", segments=[{"text": "루나 출발", "start": 1.25, "end": 2.75}])
        with patch.dict(sys.modules, {"whisperx": fake_whisperx}):
            result = AvailableAdapter().align("fixture.wav", output)
        self.assertEqual(captured["result"]["segments"][0]["start"], 1.25)
        self.assertEqual(captured["result"]["segments"][0]["end"], 2.75)
        self.assertEqual(result.status, ValidationStatus.UNKNOWN)
        self.assertEqual(result.reason, "alignment_words_unavailable")
    def test_alignment_requires_real_asr_segments(self):
        class AvailableAdapter(WhisperXAdapter):
            def capability(self): return CapabilityStatus("whisperx", ValidationStatus.PASS, package="whisperx")
        result = AvailableAdapter().align("fixture.wav", AsrOutput(ValidationStatus.PASS, "루나"))
        self.assertEqual(result.status, ValidationStatus.UNKNOWN)
        self.assertEqual(result.reason, "asr_segments_unavailable")
    def test_invalid_asr_segments_are_dropped(self):
        self.assertEqual(_alignment_segments({"segments": [{"text": "루나", "start": 2, "end": 1}]}), [])
    def test_supported_normalization_is_documented_and_deterministic(self):
        self.assertEqual(normalize_expected_pronunciation("2024년, 10kg"), "이천이십사 년 십 킬로그램")


if __name__ == "__main__": unittest.main()
