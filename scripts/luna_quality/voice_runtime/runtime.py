"""In-process resident Chatterbox V3 runtime for FAST and PRODUCTION modes."""

from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
import random
import shutil
import sys
import threading
import time
from typing import Any, Callable, Mapping

from .conditioner import CANDIDATE_B_SHA256, CandidateBConditioner
from .contract import RESPONSE_SCHEMA_VERSION, VoiceMode, VoiceRequest


SYNTHESIS_PARAMETERS = {
    "language_id": "ko",
    "exaggeration": 0.5,
    "cfg_weight": 0.5,
    "temperature": 0.72,
    "repetition_penalty": 1.2,
    "min_p": 0.05,
    "top_p": 1.0,
}


class LunaVoiceRuntime:
    """Own one model and one Candidate B condition for its whole process lifetime."""

    def __init__(
        self,
        repo_root: str | Path,
        *,
        model_factory: Callable[[], Any] | None = None,
        conditioner: Any | None = None,
        audio_writer: Callable[[Path, Any, int], None] | None = None,
        production_runner: Callable[[VoiceRequest, Any], Mapping[str, Any]] | None = None,
        seed_setter: Callable[[int], None] | None = None,
    ) -> None:
        self.repo_root = Path(repo_root).resolve()
        self._model_factory = model_factory or self._default_model_factory
        self._conditioner = conditioner or CandidateBConditioner(self.repo_root)
        self._audio_writer = audio_writer or self._default_audio_writer
        self._production_runner = production_runner or self._run_production
        self._seed_setter = seed_setter or self._default_seed_setter
        self._lock = threading.Lock()
        self.model: Any | None = None
        self.model_load_count = 0
        self.conditionals_status: dict[str, Any] | None = None
        self.started_at: float | None = None
        self.startup_seconds: float | None = None

    def start(self) -> dict[str, Any]:
        with self._lock:
            if self.model is not None:
                return self.health()
            started = time.perf_counter()
            model = self._model_factory()
            self.model_load_count += 1
            conditionals_cls = type(model.conds) if getattr(model, "conds", None) is not None else self._conditionals_class()
            self.conditionals_status = dict(self._conditioner.prepare(model, conditionals_cls))
            self.model = model
            self.started_at = time.time()
            self.startup_seconds = time.perf_counter() - started
            return self.health()

    def health(self) -> dict[str, Any]:
        return {
            "schema_version": RESPONSE_SCHEMA_VERSION,
            "status": "ready" if self.model is not None else "starting",
            "engine": "Chatterbox Multilingual V3",
            "voice": "Candidate B",
            "candidate_b_sha256": CANDIDATE_B_SHA256,
            "model_load_count": self.model_load_count,
            "conditionals": self.conditionals_status,
            "startup_seconds": round(self.startup_seconds, 3) if self.startup_seconds is not None else None,
            "local_only": True,
        }

    def handle(self, payload: Mapping[str, Any] | VoiceRequest) -> dict[str, Any]:
        request = payload if isinstance(payload, VoiceRequest) else VoiceRequest.from_mapping(payload)
        self.start()
        with self._lock:
            if request.mode is VoiceMode.FAST:
                response = self._run_fast(request)
            else:
                response = dict(self._production_runner(request, self.model))
            if request.output_json is not None:
                _atomic_write_json(self._resolve(request.output_json), response)
            return response

    def _run_fast(self, request: VoiceRequest) -> dict[str, Any]:
        assert self.model is not None
        self._seed_setter(request.seed)
        pipeline = importlib.import_module("scripts.luna_narration_pipeline_v1")
        spoken_text = pipeline.respell(request.text)
        started = time.perf_counter()
        wav = self.model.generate(spoken_text, audio_prompt_path=None, **SYNTHESIS_PARAMETERS)
        generation_seconds = time.perf_counter() - started
        output = self._resolve(request.output_wav)
        self._audio_writer(output, wav, int(self.model.sr))
        return self._response(
            request,
            output,
            generation_seconds,
            take_count=1,
            quality={"mode": "not_run", "reason": "FAST mode returns the single generated take"},
        )

    def _run_production(self, request: VoiceRequest, model: Any) -> Mapping[str, Any]:
        import numpy as np
        import torch
        import torchaudio as ta

        pipeline = importlib.import_module("scripts.luna_narration_pipeline_v1")
        from scripts.luna_quality.production_integration import FeatureFlags, ProductionQualitySession

        output = self._resolve(request.output_wav)
        outdir = self._resolve(
            request.production_outdir
            or output.parent / f"{output.stem}.production"
        )
        outdir.mkdir(parents=True, exist_ok=True)
        flags = FeatureFlags(quality_mode="shadow", conditionals_cache="on")
        quality_session = ProductionQualitySession(self.repo_root, outdir, model, flags)
        block = {"id": request.block_id, "text": request.text, "seed": request.seed}
        started = time.perf_counter()
        report = pipeline.synthesize_block(model, int(model.sr), block, outdir, np, torch, ta, quality_session)
        generation_seconds = time.perf_counter() - started
        source_wav = outdir / f"{request.block_id}_luna.wav"
        if source_wav.resolve() != output.resolve():
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_wav, output)
        _atomic_write_json(outdir / "pipeline_report.json", [report])
        response = self._response(
            request,
            output,
            generation_seconds,
            take_count=None,
            quality={
                "mode": "shadow",
                "production_selection_default_on": False,
                "report_dir": str(quality_session.report_root),
                "conditionals_cache": quality_session.conditionals_status,
            },
        )
        response["production"] = {
            "outdir": str(outdir),
            "pipeline_report": str(outdir / "pipeline_report.json"),
            "block_report": report,
        }
        return response

    def _response(
        self,
        request: VoiceRequest,
        output: Path,
        generation_seconds: float,
        *,
        take_count: int | None,
        quality: Mapping[str, Any],
    ) -> dict[str, Any]:
        response: dict[str, Any] = {
            "schema_version": RESPONSE_SCHEMA_VERSION,
            "status": "ok",
            "request_id": request.request_id,
            "mode": request.mode.value,
            "output_wav": str(output),
            "sample_rate": int(self.model.sr),
            "seed": request.seed,
            "take_count": take_count,
            "generation_seconds": round(generation_seconds, 3),
            "model_load_count": self.model_load_count,
            "condition_prepare_count": getattr(self._conditioner, "prepare_count", None),
            "engine": "Chatterbox Multilingual V3",
            "voice": "Candidate B",
            "candidate_b_sha256": CANDIDATE_B_SHA256,
            "synthesis_parameters": dict(SYNTHESIS_PARAMETERS),
            "quality": dict(quality),
            "local_only": True,
        }
        return response

    def _default_model_factory(self) -> Any:
        runtime = self.repo_root / "engine" / "chatterbox-v3"
        cache = runtime / "hf-cache"
        os.environ.update(
            {
                "HF_HOME": str(cache),
                "HF_HUB_CACHE": str(cache / "hub"),
                "HF_HUB_OFFLINE": "1",
                "TRANSFORMERS_OFFLINE": "1",
                "HF_DATASETS_OFFLINE": "1",
                "TOKENIZERS_PARALLELISM": "false",
                "PYTHONUTF8": "1",
            }
        )
        source = runtime / "chatterbox" / "src"
        if str(source) not in sys.path:
            sys.path.insert(0, str(source))
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS

        return ChatterboxMultilingualTTS.from_pretrained(device="cpu", t3_model="v3")

    @staticmethod
    def _conditionals_class() -> type[Any]:
        from chatterbox.mtl_tts import Conditionals

        return Conditionals

    @staticmethod
    def _default_audio_writer(path: Path, wav: Any, sample_rate: int) -> None:
        import torchaudio as ta

        path.parent.mkdir(parents=True, exist_ok=True)
        peak = float(wav.abs().max())
        if peak > 0.89:
            wav = wav * (0.89 / peak)
        ta.save(str(path), wav.cpu(), sample_rate, encoding="PCM_S", bits_per_sample=16)

    @staticmethod
    def _default_seed_setter(seed: int) -> None:
        import numpy as np
        import torch

        random.seed(seed)
        np.random.seed(seed % (2**32 - 1))
        torch.manual_seed(seed)

    def _resolve(self, path: str | Path) -> Path:
        value = Path(path)
        return value.resolve() if value.is_absolute() else (self.repo_root / value).resolve()


def _atomic_write_json(destination: Path, payload: Any) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp-{os.getpid()}")
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
