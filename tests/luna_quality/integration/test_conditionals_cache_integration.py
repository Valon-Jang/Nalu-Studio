"""Opt-in real-model test for the official Chatterbox Conditionals file format."""
from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.luna_quality.conditionals.cache import ConditionalsCache
from scripts.luna_quality.conditionals.manifest import ConditionalsCacheInputs


@unittest.skipUnless(os.getenv("RUN_LUNA_CONDITIONALS_INTEGRATION") == "1", "set RUN_LUNA_CONDITIONALS_INTEGRATION=1")
class ConditionalsCacheIntegrationTest(unittest.TestCase):
    def test_candidate_b_conditionals_save_and_load(self) -> None:
        if not os.getenv("PKUSEG_HOME"):
            self.skipTest("requires a pre-populated PKUSEG_HOME; do not write the user-profile default cache")
        root = REPOSITORY_ROOT
        runtime = root / "engine" / "chatterbox-v3"
        hf_cache = runtime / "hf-cache"
        os.environ.update({
            "HF_HOME": str(hf_cache),
            "HF_HUB_CACHE": str(hf_cache / "hub"),
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
        })
        sys.path.insert(0, str(runtime / "chatterbox" / "src"))
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS, Conditionals

        snapshot = next((hf_cache / "hub").glob("models--ResembleAI--chatterbox/snapshots/*"))
        inputs = ConditionalsCacheInputs.from_files(
            repo_root=root,
            chatterbox_source_version="5de7a54aa4e5e2baadb0182dde554908b48b85c2",
            t3_checkpoint=snapshot / "t3_mtl23ls_v3.safetensors",
            s3gen=snapshot / "s3gen.pt",
            voice_encoder=snapshot / "ve.pt",
            tokenizer=snapshot / "grapheme_mtl_merged_expanded_v1.json",
            reference_wav=root / "assets" / "voice_ref" / "B_voiced_spectral_micro_smooth.wav",
        )
        model = ChatterboxMultilingualTTS.from_pretrained(device="cpu", t3_model="v3")
        model.prepare_conditionals(root / "assets" / "voice_ref" / "B_voiced_spectral_micro_smooth.wav", exaggeration=0.5)
        with tempfile.TemporaryDirectory() as directory:
            cache = ConditionalsCache(Path(directory) / "conditionals")
            cache.store(inputs, model.conds)
            result = cache.load(inputs, Conditionals)
        self.assertTrue(result.hit)
        self.assertEqual(float(result.conditionals.t3.emotion_adv[0, 0, 0].item()), 0.5)


if __name__ == "__main__":
    unittest.main()
