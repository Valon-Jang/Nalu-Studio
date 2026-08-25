from __future__ import annotations

import unittest

from scripts.luna_quality.fast_speaker.contracts import FastBackend, FastPhrase, FastSynthesisResult
from scripts.luna_quality.fast_speaker.fast_adapter import FakeFastBackend


class FastSpeakerContractsTest(unittest.TestCase):
    def test_fake_backend_satisfies_contract_and_returns_known_pcm(self) -> None:
        backend = FakeFastBackend()
        self.assertIsInstance(backend, FastBackend)
        self.assertEqual(backend.initialize_once()["status"], "ready")
        phrase = backend.split_fast_text("테스트 대사입니다.")[0]
        result = backend.synthesize_fast_phrase(phrase, 17)
        self.assertEqual(result.pcm_s16le, b"\x00\x00\x00@\x00\xc0\xff\x7f")
        self.assertEqual(result.sample_rate, 24000)
        self.assertEqual(result.metadata["backend"], "fake")
        self.assertEqual(backend.requests, [(phrase, 17)])

    def test_contract_rejects_invalid_phrase_and_result(self) -> None:
        with self.assertRaisesRegex(ValueError, "phrase_id"):
            FastPhrase("", "대사", True, False)
        phrase = FastPhrase("P00", "대사", True, False)
        with self.assertRaisesRegex(ValueError, "pcm_s16le"):
            FastSynthesisResult(phrase, "대사", 1, (), b"", 24000, 0.0)
        with self.assertRaisesRegex(ValueError, "whole 16-bit"):
            FastSynthesisResult(phrase, "대사", 1, (), b"x", 24000, 0.0)


if __name__ == "__main__":
    unittest.main()
