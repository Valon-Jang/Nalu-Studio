"""Opt-in WhisperX smoke test; never downloads models during normal test runs."""
import os
import unittest
from pathlib import Path
import sys

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.luna_quality.adapters.whisperx_adapter import WhisperXAdapter
from scripts.luna_quality.contracts import ValidationStatus


@unittest.skipUnless(os.environ.get("LUNA_RUN_WHISPERX_INTEGRATION") == "1", "set LUNA_RUN_WHISPERX_INTEGRATION=1 with a non-private test WAV")
class WhisperXIntegrationTest(unittest.TestCase):
    def test_korean_transcription_and_alignment(self):
        path = Path(os.environ["LUNA_WHISPERX_INTEGRATION_WAV"])
        output = WhisperXAdapter().transcribe(path)
        self.assertEqual(output.status, ValidationStatus.PASS, output.reason)
        aligned = WhisperXAdapter().align(path, output)
        self.assertEqual(aligned.status, ValidationStatus.PASS, aligned.reason)
        self.assertTrue(aligned.words)


if __name__ == "__main__": unittest.main()
