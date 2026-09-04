# S12 FAST Production Integration

## Outcome

`scripts/luna_voice.py` is the single user-facing Luna Voice interface. A dialogue string is enough; the command starts the canonical production worker when needed, sends a local JSON request, and returns a Candidate B Luna WAV plus a JSON result.

This does **not** retrieve a prerecorded sentence. New dialogue still requires neural speech synthesis. The resident worker removes repeated model loading and repeated Candidate B reference analysis; it does not remove CPU generation time.

Observed on the S12 Windows CPU smoke test:

- first worker startup, including Chatterbox V3 load and cached Candidate B condition load: `26.966 s`
- short FAST dialogue `상주 워커 검증입니다.`: `33.742 s`
- actual output: 24 kHz PCM WAV, 84,524 bytes
- model load count after synthesis: `1`
- Candidate B condition prepare/load count after synthesis: `1`

Timing varies with text length and machine load. After the worker is ready, requests avoid the startup cost but still pay synthesis time.

## ChatGPT Chat execution path

The same user-facing entry point is also verified in a constrained ChatGPT Chat execution environment. This is not a ChatGPT built-in voice feature: Chat invokes Nalu Studio in its attached local execution environment and returns the generated WAV to the conversation.

The original resident design did not fit reliably because the effective Linux cgroup limit was 4 GiB even though host-level memory reporting looked larger. T3/S3Gen allocations and charged model-file page cache could overlap and trigger OOM. The 2026-09-04 follow-up therefore added an automatic FAST-only low-memory backend that preserves the exact Chatterbox V3 + Candidate B voice while executing T3 and S3Gen in separate processes.

Chat usage can be as simple as `dialogue → scripts/luna_voice.py → WAV → attach WAV to the conversation`. `LUNA_VOICE_BACKEND=auto` selects the low-memory path automatically at `memory.max <= 4 GiB`; larger-memory and PRODUCTION workflows retain the original resident behavior. The full development story, rejected approaches, memory safeguards, and Chat invocation example are in [`LOW_MEMORY_FAST.md`](LOW_MEMORY_FAST.md).

## Simple use

FAST is the default and generates exactly one take:

```powershell
python scripts/luna_voice.py "아이언맨 슈트에는 냉각 기술이 반드시 필요합니다."
```

An explicit output path can be supplied:

```powershell
python scripts/luna_voice.py "새 대사입니다." --output C:\Temp\luna.wav
```

PRODUCTION mode uses the same resident model, the existing phrase splitter and best-of-N pipeline, pins and hard gates, and the S10 Quality System integration:

```powershell
python scripts/luna_voice.py synthesize "정밀 제작용 대사입니다." --mode production --output C:\Temp\luna-production.wav
```

S12 fixes the PRODUCTION quality mode to `shadow`. It records quality evidence and retains the existing selector. A new quality selector is not made production-default before user listening approval.

## Worker lifecycle

The simple synthesis command starts the local worker automatically. It can also be controlled explicitly:

```powershell
python scripts/luna_voice.py start
python scripts/luna_voice.py status
python scripts/luna_voice.py stop
```

The worker binds only to `127.0.0.1:18765`. It does not expose a network service beyond the local machine and does not upload text, Candidate B, or generated audio.

## Shared JSON request contract

Both modes use `luna-voice-request/1`:

```json
{
  "schema_version": "luna-voice-request/1",
  "request_id": "example-001",
  "mode": "fast",
  "text": "대사만 입력하면 됩니다.",
  "output_wav": "C:\\Temp\\luna.wav",
  "output_json": "C:\\Temp\\luna.json",
  "seed": 20260823,
  "block_id": "B01"
}
```

Send a request file with:

```powershell
python scripts/luna_voice.py request --input C:\Temp\request.json --response C:\Temp\response.json
```

The `luna-voice-response/1` response records the output WAV, mode, sample rate, seed, take count, generation time, model/condition reuse counters, immutable engine/voice identity, fixed synthesis parameters, and Quality System mode.

## Fixed voice and runtime

- engine: Chatterbox Multilingual V3 (`t3_model="v3"`)
- Python: `engine/chatterbox-v3/venv/Scripts/python.exe`
- reference: `assets/voice_ref/B_voiced_spectral_micro_smooth.wav`
- Candidate B SHA-256: `30c6d3405f46684af467c7d26ff40a2fb57dd48cc84cd24cf7403d9aa00a2bb9`
- language: `ko`
- exaggeration: `0.5`
- CFG weight: `0.5`
- temperature: `0.72`
- repetition penalty: `1.2`
- min-p: `0.05`
- top-p: `1.0`

The production venv is read-only to this feature. No package installation or version change is performed by the worker.

## Failure behavior

- A Candidate B hash mismatch stops startup.
- A missing or untrusted conditionals artifact is never silently used.
- Invalid requests return a structured error and do not create an empty success WAV.
- Requests are serialized under a process lock because the resident model is shared.
- PRODUCTION quality failures retain the existing selector/fallback behavior.
