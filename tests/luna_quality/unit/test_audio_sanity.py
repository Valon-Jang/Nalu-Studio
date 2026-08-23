import math
import tempfile
import unittest
import wave
from pathlib import Path

from scripts.luna_quality.contracts import ValidationStatus
from scripts.luna_quality.validators.audio_sanity import AudioSanityConfig, AudioSanityValidator


RATE = 24000


def write_wav(path, samples, rate=RATE):
    frames = bytearray()
    for sample in samples:
        value = max(-1.0, min(1.0, sample))
        frames.extend(int(value * 32767).to_bytes(2, "little", signed=True))
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1); output.setsampwidth(2); output.setframerate(rate); output.writeframes(bytes(frames))


def voiced(seconds=0.5, amplitude=0.2):
    return [amplitude * math.sin(2 * math.pi * 220 * index / RATE) for index in range(round(seconds * RATE))]


class AudioSanityTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.validator = AudioSanityValidator()
    def tearDown(self): self.temp.cleanup()
    def result(self, name, samples, rate=RATE):
        path = self.root / name; write_wav(path, samples, rate); return self.validator.validate(path)
    def test_normal_voice_like_envelope_passes(self):
        samples = [0.0] * 240 + voiced() + [0.0] * 240
        result = self.result("normal.wav", samples)
        self.assertEqual(result.status, ValidationStatus.PASS); self.assertTrue(result.hard_gate)
        self.assertIn("source_wav_sha256", result.source_hashes); self.assertEqual(result.metrics["sample_rate_hz"], RATE)
    def test_zero_waveform_fails(self):
        result = self.result("zero.wav", [0.0] * RATE)
        self.assertEqual(result.status, ValidationStatus.FAIL); self.assertIn("zero_waveform", result.reasons)
    def test_missing_file_fails_explicitly(self):
        result = self.validator.validate(self.root / "missing.wav")
        self.assertEqual(result.status, ValidationStatus.FAIL); self.assertEqual(result.reasons, ["file_missing"])
    def test_invalid_wav_fails_explicitly(self):
        path = self.root / "invalid.wav"; path.write_bytes(b"not a wav")
        result = self.validator.validate(path)
        self.assertEqual(result.status, ValidationStatus.FAIL); self.assertEqual(result.reasons, ["decode_error"])
    def test_nonfinite_pcm_decode_is_not_silently_accepted(self):
        # PCM WAV cannot represent NaN; exercise the metric path directly as a deterministic decoder guard.
        from scripts.luna_quality.validators.audio_sanity import _metrics, _failures
        metrics = _metrics([float("nan")], RATE, 1, 2, self.validator.config)
        self.assertIn("non_finite_samples", _failures(metrics, self.validator.config))
    def test_clipping_fails(self):
        result = self.result("clip.wav", [1.0] * RATE)
        self.assertIn("clipping_ratio_exceeded", result.reasons); self.assertEqual(result.status, ValidationStatus.FAIL)
    def test_long_edge_silence_fails(self):
        result = self.result("edge.wav", [0.0] * (RATE * 2) + voiced())
        self.assertIn("leading_silence_too_long", result.reasons)
    def test_internal_silence_fails(self):
        result = self.result("internal.wav", voiced() + [0.0] * RATE + voiced())
        self.assertIn("internal_silence_too_long", result.reasons)
    def test_short_file_fails(self):
        result = self.result("short.wav", voiced(0.02))
        self.assertIn("file_too_short", result.reasons)
    def test_abrupt_cut_fails(self):
        result = self.result("abrupt.wav", voiced(0.5))
        self.assertIn("abrupt_end", result.reasons)
    def test_expected_rate_is_hard_gate(self):
        result = self.result("rate.wav", voiced(), rate=16000)
        self.assertIn("unexpected_sample_rate", result.reasons)
    def test_config_change_changes_validator_version(self):
        updated = AudioSanityValidator(AudioSanityConfig(maximum_dc_offset=0.01))
        self.assertNotEqual(self.validator.validator_version, updated.validator_version)


if __name__ == "__main__": unittest.main()
