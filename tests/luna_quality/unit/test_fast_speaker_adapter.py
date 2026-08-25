from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from scripts.luna_quality.fast_speaker.contracts import FastPhrase
from scripts.luna_quality.fast_speaker.fast_adapter import LunaFastBackend, waveform_to_pcm_s16le
from scripts.luna_quality.voice_runtime.runtime import LunaVoiceRuntime, SYNTHESIS_PARAMETERS


class FakeWave:
    def __init__(self, values) -> None:
        self.values = values

    def abs(self):
        return self

    def max(self):
        return max(abs(value) for value in self.values)

    def __mul__(self, factor):
        return FakeWave([value * factor for value in self.values])

    def detach(self):
        return self

    def cpu(self):
        return self

    def reshape(self, _):
        return self

    def tolist(self):
        return list(self.values)


class FakeModel:
    sr = 24000
    device = "cpu"
    conds = object()

    def __init__(self) -> None:
        self.generate_calls = []

    def generate(self, text, **kwargs):
        self.generate_calls.append((text, kwargs))
        return FakeWave([0.0, 1.0, -1.0])


class FakeConditioner:
    prepare_count = 0

    def prepare(self, model, conditionals_cls):
        self.prepare_count += 1
        return {"status": "hit"}


class FastSpeakerAdapterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.model = FakeModel()
        self.seeds = []
        self.runtime = LunaVoiceRuntime(
            Path(self.temporary.name),
            model_factory=lambda: self.model,
            conditioner=FakeConditioner(),
            seed_setter=self.seeds.append,
        )
        self.backend = LunaFastBackend(self.runtime)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_adapter_initializes_once_and_uses_exact_fast_generation_contract(self) -> None:
        self.assertEqual(self.backend.initialize_once()["status"], "ready")
        phrase = FastPhrase("P00", "끊어진 부분입니다?", True, False)
        result = self.backend.synthesize_fast_phrase(phrase, 23)
        self.assertEqual(self.seeds, [23])
        self.assertEqual(self.model.generate_calls[0][0], "끄너진 부분입니다.")
        kwargs = self.model.generate_calls[0][1]
        self.assertIsNone(kwargs.pop("audio_prompt_path"))
        self.assertEqual(kwargs, SYNTHESIS_PARAMETERS)
        self.assertEqual(result.spoken_text, "끄너진 부분입니다.")
        self.assertEqual(result.pcm_s16le, b"\x00\x00\xebq\x14\x8e")
        self.assertEqual(result.sample_rate, 24000)

    def test_adapter_uses_current_luna_phrase_splitter(self) -> None:
        phrases = self.backend.split_fast_text("거미줄은 유연한 부분과 단단한 부분이 함께 구조를 지탱합니다.")
        self.assertEqual(
            [(item.phrase_id, item.text, item.sentence_final, item.forced) for item in phrases],
            [
                ("P00", "거미줄은 유연한 부분과", False, True),
                ("P01", "단단한 부분이 함께 구조를 지탱합니다.", True, False),
            ],
        )

    def test_pcm_conversion_is_little_endian_and_clamped(self) -> None:
        self.assertEqual(waveform_to_pcm_s16le([0.0, 0.5, -0.5, 1.2, -1.2]), b"\x00\x00\x00@\x00\xc0\xff\x7f\x00\x80")


if __name__ == "__main__":
    unittest.main()
