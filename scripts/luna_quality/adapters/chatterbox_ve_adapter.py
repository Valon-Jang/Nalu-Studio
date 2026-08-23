"""Chatterbox V3 Voice Encoder adapter with hash-keyed local embeddings."""
from __future__ import annotations
import json
import math
import wave
from pathlib import Path
from typing import Any
from ..hashing import sha256_file

class ChatterboxVEAdapter:
    model_id = "chatterbox-v3-voice-encoder"
    model_revision = "production-v3"
    def __init__(self, voice_encoder: Any | None = None, cache_dir: str | Path = "artifacts/luna_quality/private_embeddings"):
        self.voice_encoder, self.cache_dir = voice_encoder, Path(cache_dir)
    def embed(self, wav_path: str | Path) -> tuple[list[float] | None, str, bool]:
        path = Path(wav_path); digest = sha256_file(path); cache = self.cache_dir / f"ve-{digest}.json"
        if cache.exists(): return json.loads(cache.read_text(encoding="utf-8"))["embedding"], digest, True
        if self.voice_encoder is None: return None, digest, False
        samples, rate = _mono_pcm(path)
        embedding = self.voice_encoder.embeds_from_wavs([samples], sample_rate=rate, as_spk=True)
        values = [float(x) for x in embedding.tolist()]
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"audio_sha256": digest, "model_id": self.model_id, "model_revision": self.model_revision, "embedding": values}), encoding="utf-8")
        return values, digest, False
    @staticmethod
    def cosine(left: list[float], right: list[float]) -> float:
        denominator = math.sqrt(sum(x*x for x in left) * sum(x*x for x in right))
        return sum(x*y for x, y in zip(left, right)) / denominator if denominator else 0.0

def _mono_pcm(path: Path):
    import numpy as np
    with wave.open(str(path), "rb") as reader:
        if reader.getcomptype() != "NONE" or reader.getsampwidth() != 2: raise ValueError("requires PCM16 WAV")
        raw, channels, rate = reader.readframes(reader.getnframes()), reader.getnchannels(), reader.getframerate()
    values = np.frombuffer(raw, dtype="<i2").astype("float32") / 32768.0
    return values.reshape(-1, channels).mean(axis=1), rate
