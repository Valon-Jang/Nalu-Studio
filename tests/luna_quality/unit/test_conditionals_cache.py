from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from scripts.luna_quality.conditionals.cache import CacheMissReason, ConditionalsCache
from scripts.luna_quality.conditionals.manifest import CANDIDATE_B_REFERENCE_PATH, ConditionalsCacheInputs


class FakeConditionals:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def save(self, path: Path) -> None:
        Path(path).write_bytes(b"fake-conditionals:" + self.payload)

    @classmethod
    def load(cls, path: Path, map_location: str = "cpu") -> "FakeConditionals":
        assert map_location == "cpu"
        contents = Path(path).read_bytes()
        if not contents.startswith(b"fake-conditionals:"):
            raise ValueError("not a fake conditionals artifact")
        return cls(contents.removeprefix(b"fake-conditionals:"))


class FailingConditionals:
    def save(self, path: Path) -> None:
        Path(path).write_bytes(b"partial")
        raise RuntimeError("interrupted save")


class ConditionalsCacheTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.assets = self.root / "assets" / "voice_ref"
        self.assets.mkdir(parents=True)
        self.reference = self.assets / "B_voiced_spectral_micro_smooth.wav"
        self.reference.write_bytes(b"private-candidate-b-wav")
        self.model = self.root / "model"
        self.model.mkdir()
        self.files = {}
        for name, contents in {"t3.safetensors": b"t3", "s3gen.pt": b"s3", "ve.pt": b"ve", "tokenizer.json": b"tokens"}.items():
            path = self.model / name
            path.write_bytes(contents)
            self.files[name] = path
        self.inputs = self.make_inputs()
        self.cache = ConditionalsCache(self.root / ".luna_quality_cache" / "conditionals")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def make_inputs(self, **changes: object) -> ConditionalsCacheInputs:
        values = dict(
            repo_root=self.root,
            chatterbox_source_version="local-5de7a54",
            t3_checkpoint=self.files["t3.safetensors"],
            s3gen=self.files["s3gen.pt"],
            voice_encoder=self.files["ve.pt"],
            tokenizer=self.files["tokenizer.json"],
            reference_wav=self.reference,
            language_id="ko",
            exaggeration=0.5,
        )
        values.update(changes)
        return ConditionalsCacheInputs.from_files(**values)

    def test_round_trip_uses_deterministic_key_and_never_embeds_reference_wav(self) -> None:
        manifest = self.cache.store(self.inputs, FakeConditionals(b"prepared-values"))
        self.assertEqual(manifest.cache_key, self.inputs.cache_key())
        self.assertEqual(self.inputs.reference_wav_path, CANDIDATE_B_REFERENCE_PATH)
        self.assertNotIn(self.reference.read_bytes(), self.cache.artifact_path.read_bytes())
        self.assertEqual(json.loads(self.cache.manifest_path.read_text(encoding="utf-8"))["inputs"]["reference_wav_path"], CANDIDATE_B_REFERENCE_PATH)
        result = self.cache.load(self.inputs, FakeConditionals)
        self.assertTrue(result.hit)
        self.assertEqual(result.conditionals.payload, b"prepared-values")

    def test_source_change_is_a_structured_cache_miss(self) -> None:
        self.cache.store(self.inputs, FakeConditionals(b"prepared-values"))
        changed = self.make_inputs(exaggeration=0.6)
        result = self.cache.load(changed, FakeConditionals)
        self.assertFalse(result.hit)
        self.assertEqual(result.reason, CacheMissReason.SOURCE_MISMATCH)
        self.assertIn("expected_cache_key", result.details)

    def test_corrupt_artifact_is_a_cache_miss(self) -> None:
        self.cache.store(self.inputs, FakeConditionals(b"prepared-values"))
        self.cache.artifact_path.write_bytes(b"corrupt")
        result = self.cache.load(self.inputs, FakeConditionals)
        self.assertFalse(result.hit)
        self.assertEqual(result.reason, CacheMissReason.ARTIFACT_HASH_MISMATCH)

    def test_deserialization_error_is_a_cache_miss_after_valid_hash(self) -> None:
        manifest = self.cache.store(self.inputs, FakeConditionals(b"prepared-values"))
        self.cache.artifact_path.write_bytes(b"not-fake-conditionals")
        payload = json.loads(self.cache.manifest_path.read_text(encoding="utf-8"))
        from scripts.luna_quality.hashing import sha256_file
        payload["artifact_sha256"] = sha256_file(self.cache.artifact_path)
        self.cache.manifest_path.write_text(json.dumps(payload), encoding="utf-8")
        result = self.cache.load(self.inputs, FakeConditionals)
        self.assertFalse(result.hit)
        self.assertEqual(result.reason, CacheMissReason.DESERIALIZATION_ERROR)

    def test_atomic_write_leaves_no_temporary_files(self) -> None:
        self.cache.store(self.inputs, FakeConditionals(b"prepared-values"))
        self.assertEqual(list(self.cache.cache_dir.glob("*.tmp")), [])
        self.assertTrue(self.cache.artifact_path.is_file())
        self.assertTrue(self.cache.manifest_path.is_file())

    def test_interrupted_save_leaves_no_named_or_temporary_artifact(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "interrupted save"):
            self.cache.store(self.inputs, FailingConditionals())
        self.assertFalse(self.cache.artifact_path.exists())
        self.assertFalse(self.cache.manifest_path.exists())
        self.assertEqual(list(self.cache.cache_dir.glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
