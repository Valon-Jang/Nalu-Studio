import unittest
from scripts.luna_quality.capability import optional_dependency
from scripts.luna_quality.contracts import CapabilityStatus, TakeEvaluation, TakeIdentity, ValidationResult, ValidationStatus
from scripts.luna_quality.hashing import sha256_text

class ContractsTest(unittest.TestCase):
    def test_round_trip_and_windows_paths(self):
        identity = TakeIdentity("B01", "P01", 1, 7, "한글 UTF-8", sha256_text("한글 UTF-8"), r"projects\P\take.wav", r"projects\P\take.json")
        result = ValidationResult("fixture", "1", "unknown", True, artifacts={"report": r"artifacts\r.json"})
        original = TakeEvaluation(identity, [result], hard_gate_pass=False)
        restored = TakeEvaluation.from_dict(original.to_dict())
        self.assertEqual(restored, original)
        self.assertEqual(identity.source_wav_path, "projects/P/take.wav")
    def test_invalid_status_is_rejected(self):
        with self.assertRaises(ValueError): ValidationResult("x", "1", "invalid", False)
        with self.assertRaises(ValueError): CapabilityStatus("x", ValidationStatus.FAIL)
    def test_hash_is_deterministic(self): self.assertEqual(sha256_text("한글"), sha256_text("한글"))
    def test_missing_optional_dependency_is_not_run(self):
        result = optional_dependency("package_that_does_not_exist_luna")
        self.assertEqual(result.status, ValidationStatus.NOT_RUN)
        self.assertEqual(CapabilityStatus.from_dict(result.to_dict()), result)

if __name__ == "__main__": unittest.main()
