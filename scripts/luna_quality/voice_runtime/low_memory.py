"""4 GiB-safe FAST synthesis for Luna Candidate B.

The resident worker remains the preferred backend when memory permits.  On a
small Linux cgroup this module keeps the exact Chatterbox V3 weights, Candidate
B conditionals, fixed sampling parameters, and PCM output contract while
loading T3 and S3Gen in separate OS processes so their peak memory does not
stack.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import time
from typing import Any, Mapping
import wave

from .conditioner import CANDIDATE_B_SHA256, CandidateBConditioner
from .contract import RESPONSE_SCHEMA_VERSION, VoiceMode, VoiceRequest
from .runtime import SYNTHESIS_PARAMETERS

LOW_MEMORY_THRESHOLD_BYTES = 4 * 1024**3
DEFAULT_PHASE_TIMEOUT_SECONDS = 240.0
MODEL_SIZES = {
    "t3_mtl23ls_v3.safetensors": 2_143_989_928,
    "s3gen.pt": 1_057_165_844,
    "ve.pt": 5_698_626,
    "conds.pt": 107_374,
    "grapheme_mtl_merged_expanded_v1.json": 69_989,
    "Cangjie5_TC.json": 1_920_163,
}


def cgroup_memory_limit_bytes(path: str | Path = "/sys/fs/cgroup/memory.max") -> int | None:
    try:
        raw = Path(path).read_text(encoding="ascii").strip()
    except OSError:
        return None
    if raw == "max":
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def should_use_low_memory_backend(*, mode: str | VoiceMode = VoiceMode.FAST, limit_bytes: int | None = None) -> bool:
    voice_mode = mode if isinstance(mode, VoiceMode) else VoiceMode(str(mode))
    if voice_mode is not VoiceMode.FAST:
        return False
    if limit_bytes is None:
        limit_bytes = cgroup_memory_limit_bytes()
    return limit_bytes is not None and limit_bytes <= LOW_MEMORY_THRESHOLD_BYTES


def run_low_memory_fast(
    repo_root: str | Path,
    payload: Mapping[str, Any] | VoiceRequest,
    *,
    phase_timeout_seconds: float = DEFAULT_PHASE_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    request = payload if isinstance(payload, VoiceRequest) else VoiceRequest.from_mapping(payload)
    if request.mode is not VoiceMode.FAST:
        raise ValueError("low-memory backend supports FAST mode only")

    root = Path(repo_root).resolve()
    runtime = root / "engine" / "chatterbox-v3"
    python = runtime / "venv" / "Scripts" / "python.exe"
    snapshot = _find_snapshot(runtime)
    reference = root / "assets" / "voice_ref" / "B_voiced_spectral_micro_smooth.wav"
    cache_dir = root / ".luna_quality_cache" / "conditionals"
    conditionals = cache_dir / "candidate_b.conditionals.pt"
    work_dir = root / ".luna_quality_cache" / "voice_runtime"
    work_dir.mkdir(parents=True, exist_ok=True)
    tokens = work_dir / "lowmem_speech_tokens.pt"
    output = _resolve(root, request.output_wav)
    output.parent.mkdir(parents=True, exist_ok=True)

    _validate_fixed_assets(snapshot, reference, python)
    _ensure_conditionals(root, conditionals, phase_timeout_seconds)

    env = os.environ.copy()
    env.update({
        "PYTHONPATH": str(root),
        "HF_HOME": str(runtime / "hf-cache"),
        "HF_HUB_CACHE": str(runtime / "hf-cache" / "hub"),
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "HF_DATASETS_OFFLINE": "1",
        "TOKENIZERS_PARALLELISM": "false",
        "OMP_NUM_THREADS": "2",
        "MKL_NUM_THREADS": "2",
        "OPENBLAS_NUM_THREADS": "2",
        "PYTHONUTF8": "1",
    })

    started = time.perf_counter()
    oom_before = _oom_kill_count()
    _evict_clean_pages(snapshot / "t3_mtl23ls_v3.safetensors", snapshot / "s3gen.pt")
    t3 = _run_phase(
        python,
        root,
        ["t3", "--repo-root", str(root), "--conditionals", str(conditionals), "--tokens", str(tokens), "--seed", str(request.seed), request.text],
        env,
        phase_timeout_seconds,
        retry_on_oom=True,
    )
    _evict_clean_pages(snapshot / "s3gen.pt")
    s3 = _run_phase(
        python,
        root,
        ["s3", "--repo-root", str(root), "--conditionals", str(conditionals), "--tokens", str(tokens), "--output", str(output)],
        env,
        phase_timeout_seconds,
        retry_on_oom=True,
    )
    _evict_clean_pages(snapshot / "t3_mtl23ls_v3.safetensors", snapshot / "s3gen.pt")
    wav = _wav_info(output)
    generation_seconds = time.perf_counter() - started
    return {
        "schema_version": RESPONSE_SCHEMA_VERSION,
        "status": "ok",
        "request_id": request.request_id,
        "mode": request.mode.value,
        "output_wav": str(output),
        "sample_rate": 24_000,
        "seed": request.seed,
        "take_count": 1,
        "generation_seconds": round(generation_seconds, 3),
        "model_load_count": 2,
        "condition_prepare_count": None,
        "engine": "Chatterbox Multilingual V3",
        "voice": "Candidate B",
        "candidate_b_sha256": CANDIDATE_B_SHA256,
        "synthesis_parameters": dict(SYNTHESIS_PARAMETERS),
        "quality": {"mode": "not_run", "reason": "FAST low-memory mode returns the single generated take"},
        "local_only": True,
        "runtime_backend": "lowmem",
        "memory_limit_bytes": cgroup_memory_limit_bytes(),
        "oom_kill_before": oom_before,
        "oom_kill_after": _oom_kill_count(),
        "phases": {"t3": t3, "s3": s3},
        "wav": wav,
    }


def _ensure_conditionals(root: Path, artifact: Path, timeout: float) -> None:
    runtime = root / "engine" / "chatterbox-v3"
    source = runtime / "chatterbox" / "src"
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))
    from chatterbox.mtl_tts import Conditionals

    conditioner = CandidateBConditioner(root)
    inputs = conditioner._inputs()  # Same canonical fingerprints as the resident conditioner.
    lookup = conditioner.cache.load(inputs, Conditionals)
    if lookup.hit:
        return
    if conditioner.cache.manifest_path.exists() or conditioner.cache.artifact_path.exists():
        reason = lookup.reason.value if lookup.reason is not None else "unknown"
        raise RuntimeError(f"Candidate B conditionals cache is not trusted: {reason}")
    env = os.environ.copy()
    env.update({"PYTHONPATH": str(root), "TOKENIZERS_PARALLELISM": "false", "PYTHONUTF8": "1"})
    _run_phase(
        runtime / "venv" / "Scripts" / "python.exe",
        root,
        ["condition", "--repo-root", str(root), "--output", str(artifact)],
        env,
        timeout,
        retry_on_oom=True,
    )
    lookup = conditioner.cache.load(inputs, Conditionals)
    if not lookup.hit:
        reason = lookup.reason.value if lookup.reason is not None else "unknown"
        raise RuntimeError(f"low-memory Candidate B cache verification failed: {reason}")


def _run_phase(
    python: Path,
    root: Path,
    args: list[str],
    env: Mapping[str, str],
    timeout: float,
    *,
    retry_on_oom: bool,
) -> dict[str, Any]:
    cmd = [str(python), "-X", "utf8", "-m", "scripts.luna_quality.voice_runtime.low_memory", *args]
    attempts = 2 if retry_on_oom else 1
    for attempt in range(attempts):
        try:
            completed = subprocess.run(cmd, cwd=str(root), env=dict(env), text=True, capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired as error:
            raise TimeoutError(f"low-memory phase {args[0]} exceeded {timeout:.0f}s") from error
        if completed.returncode == 0:
            for line in reversed(completed.stdout.splitlines()):
                line = line.strip()
                if line.startswith("{"):
                    return json.loads(line)
            return {"status": "ok", "phase": args[0]}
        if retry_on_oom and attempt == 0 and completed.returncode in (-9, 137):
            runtime = root / "engine" / "chatterbox-v3"
            snapshot = _find_snapshot(runtime)
            _evict_clean_pages(snapshot / "t3_mtl23ls_v3.safetensors", snapshot / "s3gen.pt")
            continue
        detail = (completed.stderr or completed.stdout)[-4000:]
        raise RuntimeError(f"low-memory phase {args[0]} failed rc={completed.returncode}: {detail}")
    raise RuntimeError(f"low-memory phase {args[0]} failed")


def _validate_fixed_assets(snapshot: Path, reference: Path, python: Path) -> None:
    if not python.is_file():
        raise FileNotFoundError(f"canonical production Python not found: {python}")
    if not reference.is_file() or hashlib.sha256(reference.read_bytes()).hexdigest().lower() != CANDIDATE_B_SHA256:
        raise RuntimeError("fixed Candidate B SHA-256 mismatch")
    for name, expected_size in MODEL_SIZES.items():
        path = snapshot / name
        if not path.is_file() or path.stat().st_size != expected_size:
            raise RuntimeError(f"model asset mismatch: {path} expected_size={expected_size}")


def _find_snapshot(runtime: Path) -> Path:
    root = runtime / "hf-cache" / "hub" / "models--ResembleAI--chatterbox" / "snapshots"
    valid = [path for path in sorted(root.glob("*")) if (path / "t3_mtl23ls_v3.safetensors").is_file()]
    if len(valid) != 1:
        raise RuntimeError(f"expected exactly one cached Chatterbox snapshot, found {len(valid)}")
    return valid[0]


def _evict_clean_pages(*paths: Path) -> None:
    if not hasattr(os, "posix_fadvise") or not hasattr(os, "POSIX_FADV_DONTNEED"):
        return
    for path in paths:
        try:
            fd = os.open(path, os.O_RDONLY)
            try:
                os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
            finally:
                os.close(fd)
        except OSError:
            pass
    time.sleep(0.08)


def _oom_kill_count() -> int | None:
    try:
        values = dict(line.split() for line in Path("/sys/fs/cgroup/memory.events").read_text(encoding="ascii").splitlines())
        return int(values.get("oom_kill", 0))
    except (OSError, ValueError):
        return None


def _resolve(root: Path, value: str | Path) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _wav_info(path: Path) -> dict[str, Any]:
    with wave.open(str(path), "rb") as handle:
        channels = handle.getnchannels()
        rate = handle.getframerate()
        width = handle.getsampwidth()
        frames = handle.getnframes()
    if (channels, rate, width) != (1, 24_000, 2) or frames <= 0:
        raise RuntimeError(f"invalid low-memory WAV: channels={channels} rate={rate} width={width} frames={frames}")
    return {
        "channels": channels,
        "sample_rate": rate,
        "sample_width": width,
        "frames": frames,
        "duration_seconds": round(frames / rate, 3),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _phase_condition(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(args.repo_root).resolve()
    runtime = root / "engine" / "chatterbox-v3"
    snapshot = _find_snapshot(runtime)
    source = runtime / "chatterbox" / "src"
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))
    os.environ["PKUSEG_HOME"] = str(runtime / "pkuseg")
    import librosa
    import torch
    from chatterbox.mtl_tts import Conditionals
    from chatterbox.models.s3gen import S3GEN_SR, S3Gen
    from chatterbox.models.s3tokenizer import S3_SR
    from chatterbox.models.voice_encoder import VoiceEncoder
    from chatterbox.models.t3.modules.cond_enc import T3Cond
    from chatterbox.models.t3.modules.t3_config import T3Config

    reference = root / "assets" / "voice_ref" / "B_voiced_spectral_micro_smooth.wav"
    if hashlib.sha256(reference.read_bytes()).hexdigest().lower() != CANDIDATE_B_SHA256:
        raise RuntimeError("fixed Candidate B SHA-256 mismatch")
    started = time.perf_counter()
    s3 = S3Gen()
    s3.load_state_dict(torch.load(snapshot / "s3gen.pt", map_location="cpu", weights_only=True))
    s3.eval()
    ve = VoiceEncoder()
    ve.load_state_dict(torch.load(snapshot / "ve.pt", map_location="cpu", weights_only=True))
    ve.eval()
    wav, _ = librosa.load(str(reference), sr=S3GEN_SR)
    wav16 = librosa.resample(wav, orig_sr=S3GEN_SR, target_sr=S3_SR)
    gen = s3.embed_ref(wav[: 10 * S3GEN_SR], S3GEN_SR, device="cpu")
    prompt_len = T3Config.multilingual().speech_cond_prompt_len
    prompt_tokens, _ = s3.tokenizer.forward([wav16[: 6 * S3_SR]], max_len=prompt_len)
    prompt_tokens = torch.atleast_2d(prompt_tokens)
    speaker_emb = torch.from_numpy(ve.embeds_from_wavs([wav16], sample_rate=S3_SR)).mean(axis=0, keepdim=True)
    t3_cond = T3Cond(
        speaker_emb=speaker_emb,
        cond_prompt_speech_tokens=prompt_tokens,
        emotion_adv=0.5 * torch.ones(1, 1, 1),
    ).to(device="cpu")
    conds = Conditionals(t3_cond, gen)
    conditioner = CandidateBConditioner(root)
    manifest = conditioner.cache.store(conditioner._inputs(), conds)
    return {"status": "ok", "phase": "condition", "seconds": round(time.perf_counter() - started, 3), "cache_key": manifest.cache_key}


def _phase_t3(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(args.repo_root).resolve()
    runtime = root / "engine" / "chatterbox-v3"
    snapshot = _find_snapshot(runtime)
    source = runtime / "chatterbox" / "src"
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))
    os.environ["PKUSEG_HOME"] = str(runtime / "pkuseg")
    import numpy as np
    import torch
    import torch.nn.functional as F
    from safetensors.torch import load_file as load_safetensors
    from chatterbox.models.t3 import T3
    from chatterbox.models.t3.modules.t3_config import T3Config
    from chatterbox.models.t3.modules.cond_enc import T3Cond
    from chatterbox.models.tokenizers import MTLTokenizer
    from chatterbox.mtl_tts import punc_norm
    from chatterbox.models.s3tokenizer import drop_invalid_tokens
    from scripts import luna_narration_pipeline_v1 as pipeline

    started = time.perf_counter()
    raw = torch.load(args.conditionals, map_location="cpu", weights_only=True)
    cond = T3Cond(**raw["t3"]).to(device="cpu")
    model = T3(T3Config.multilingual())
    weight = snapshot / "t3_mtl23ls_v3.safetensors"
    state = load_safetensors(weight)
    missing, unexpected = model.load_state_dict(state, strict=False)
    if missing or unexpected:
        raise RuntimeError(f"T3 weight mismatch missing={missing[:8]} unexpected={unexpected[:8]}")
    del state
    _evict_clean_pages(weight)
    model.eval()
    tokenizer = MTLTokenizer(str(snapshot / "grapheme_mtl_merged_expanded_v1.json"))
    spoken_text = punc_norm(pipeline.respell(args.text))
    text_tokens = tokenizer.text_to_tokens(spoken_text, language_id="ko")
    text_tokens = torch.cat([text_tokens, text_tokens], 0)
    text_tokens = F.pad(text_tokens, (1, 0), value=model.hp.start_text_token)
    text_tokens = F.pad(text_tokens, (0, 1), value=model.hp.stop_text_token)
    random.seed(args.seed)
    np.random.seed(args.seed % (2**32 - 1))
    torch.manual_seed(args.seed)
    inference_started = time.perf_counter()
    with torch.inference_mode():
        speech_tokens = model.inference(
            t3_cond=cond,
            text_tokens=text_tokens,
            max_new_tokens=1000,
            temperature=SYNTHESIS_PARAMETERS["temperature"],
            cfg_weight=SYNTHESIS_PARAMETERS["cfg_weight"],
            repetition_penalty=SYNTHESIS_PARAMETERS["repetition_penalty"],
            min_p=SYNTHESIS_PARAMETERS["min_p"],
            top_p=SYNTHESIS_PARAMETERS["top_p"],
        )[0]
    inference_seconds = time.perf_counter() - inference_started
    speech_tokens = drop_invalid_tokens(speech_tokens).to("cpu")
    destination = Path(args.tokens)
    destination.parent.mkdir(parents=True, exist_ok=True)
    torch.save({"speech_tokens": speech_tokens, "torch_rng_state": torch.get_rng_state(), "text": spoken_text, "seed": args.seed}, destination)
    return {"status": "ok", "phase": "t3", "seconds": round(time.perf_counter() - started, 3), "inference_seconds": round(inference_seconds, 3), "tokens": int(speech_tokens.shape[-1])}


def _phase_s3(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(args.repo_root).resolve()
    runtime = root / "engine" / "chatterbox-v3"
    snapshot = _find_snapshot(runtime)
    source = runtime / "chatterbox" / "src"
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))
    os.environ["PKUSEG_HOME"] = str(runtime / "pkuseg")
    import numpy as np
    import perth
    import torch
    import torchaudio as ta
    from chatterbox.models.s3gen import S3GEN_SR, S3Gen
    from chatterbox.models.s3tokenizer import S3_TOKEN_RATE

    started = time.perf_counter()
    weight = snapshot / "s3gen.pt"
    model = S3Gen()
    state = torch.load(weight, map_location="cpu", weights_only=True)
    model.load_state_dict(state)
    del state
    _evict_clean_pages(weight)
    model.eval()
    raw = torch.load(args.conditionals, map_location="cpu", weights_only=True)
    packet = torch.load(args.tokens, map_location="cpu", weights_only=True)
    speech_tokens = packet["speech_tokens"]
    torch.set_rng_state(packet["torch_rng_state"])
    inference_started = time.perf_counter()
    with torch.inference_mode():
        wav, _ = model.inference(speech_tokens=speech_tokens, ref_dict=raw["gen"])
    inference_seconds = time.perf_counter() - inference_started
    wav = wav.squeeze(0).detach().cpu().numpy()
    wav = wav[: max(1, int(speech_tokens.shape[-1]) - 1) * (S3GEN_SR // S3_TOKEN_RATE)]
    watermarked = perth.PerthImplicitWatermarker().apply_watermark(wav, sample_rate=S3GEN_SR)
    tensor = torch.from_numpy(watermarked).unsqueeze(0) if watermarked.ndim == 1 else torch.from_numpy(watermarked)
    peak = float(tensor.abs().max())
    if peak > 0.89:
        tensor = tensor * (0.89 / peak)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    ta.save(str(output), tensor, S3GEN_SR, encoding="PCM_S", bits_per_sample=16)
    return {"status": "ok", "phase": "s3", "seconds": round(time.perf_counter() - started, 3), "inference_seconds": round(inference_seconds, 3), "duration": round(tensor.shape[-1] / S3GEN_SR, 3), "wav_sha256": hashlib.sha256(output.read_bytes()).hexdigest()}


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="phase", required=True)
    condition = sub.add_parser("condition")
    condition.add_argument("--repo-root", required=True)
    condition.add_argument("--output", required=True)
    t3 = sub.add_parser("t3")
    t3.add_argument("--repo-root", required=True)
    t3.add_argument("--conditionals", required=True)
    t3.add_argument("--tokens", required=True)
    t3.add_argument("--seed", type=int, required=True)
    t3.add_argument("text")
    s3 = sub.add_parser("s3")
    s3.add_argument("--repo-root", required=True)
    s3.add_argument("--conditionals", required=True)
    s3.add_argument("--tokens", required=True)
    s3.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    result = {"condition": _phase_condition, "t3": _phase_t3, "s3": _phase_s3}[args.phase](args)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
