"""Opt-in Windows CPU/Hugging Face cache smoke test; never generates audio."""
from __future__ import annotations

import os
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[3]


@unittest.skipUnless(os.getenv("RUN_LUNA_MODEL_LOAD_SMOKE") == "1", "set RUN_LUNA_MODEL_LOAD_SMOKE=1")
class ChatterboxModelLoadIntegrationTest(unittest.TestCase):
    def test_pinned_multilingual_v3_loads_from_hf_cache_on_cpu(self):
        runtime = ROOT / "engine" / "chatterbox-v3"
        cache = runtime / "hf-cache"
        os.environ.update(
            {
                "HF_HOME": str(cache),
                "HF_HUB_CACHE": str(cache / "hub"),
                "HF_HUB_OFFLINE": "1",
                "TRANSFORMERS_OFFLINE": "1",
                "HF_DATASETS_OFFLINE": "1",
                "TOKENIZERS_PARALLELISM": "false",
            }
        )
        sys.path.insert(0, str(runtime / "chatterbox" / "src"))
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS

        model = ChatterboxMultilingualTTS.from_pretrained(device="cpu", t3_model="v3")
        self.assertEqual(model.sr, 24000)
        self.assertEqual(str(model.device), "cpu")
        self.assertIsNotNone(model.t3)
        self.assertIsNotNone(model.s3gen)
        self.assertIsNotNone(model.ve)


if __name__ == "__main__":
    unittest.main()
