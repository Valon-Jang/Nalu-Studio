# Luna FAST low-memory backend

Status: verified 2026-09-04 for the Chat CPU environment with a 4 GiB cgroup limit.

## Why it exists

The S12 resident worker intentionally keeps the complete Chatterbox Multilingual V3 model in one process. That remains the preferred path when memory permits. A 4 GiB cgroup can OOM because T3 and S3Gen allocations/page cache overlap.

`luna_voice.py` therefore selects a low-memory FAST backend automatically when Linux cgroup `memory.max` is at or below 4 GiB. Production mode remains on the resident worker.

Override only when diagnosing:

```text
LUNA_VOICE_BACKEND=auto      # default
LUNA_VOICE_BACKEND=resident
LUNA_VOICE_BACKEND=lowmem    # FAST only
```

## ChatGPT Chat: why the first attempt failed, and what changed

This backend was not designed only from a desktop benchmark. It was debugged inside a ChatGPT Chat execution environment while trying to make Luna speak from the chat itself and return the generated WAV to the conversation.

The first approach was the obvious S12 design: start the resident worker, keep the full Chatterbox Multilingual V3 model loaded, prepare Candidate B once, and reuse that state for later sentences. That worked on the original Windows CPU environment, but it was unreliable in Chat.

The failure story was useful:

1. The host-level memory display suggested roughly 5.8 GiB was available, so the resident path initially looked feasible.
2. The actual process limit was discovered in Linux cgroup `memory.max`: exactly `4,294,967,296` bytes (4 GiB). The host memory display was therefore the wrong capacity signal for this runtime.
3. T3 and S3Gen resident allocations, plus clean model-file page cache charged to the same cgroup, could overlap and push the process over the 4 GiB ceiling. The observed failure was an OOM kill (`-9` / `137` class failure), not a bad voice model.
4. Releasing clean model pages before the next phase removed a large amount of charged cache immediately. Wrapping inference in `torch.inference_mode()` removed unnecessary autograd state.
5. A more aggressive file-backed/meta loading experiment was also tried, but it produced page-fault/thrashing stalls in this constrained environment, so it was rejected rather than shipped.
6. The stable solution was to stop trying to keep both synthesis halves resident: preserve the exact model and voice, but run T3 and S3Gen in separate OS processes so memory from one phase is released before the next phase starts.

The result is a Chat-compatible execution path without changing Luna's voice identity or sampling contract. The optimization is memory orchestration, not a smaller model, quantization, alternate TTS engine, or prerecorded sentence lookup.

## Using Luna from ChatGPT Chat

This is **not a built-in ChatGPT TTS feature**. It is the Nalu Studio Luna program running inside a ChatGPT Chat-attached execution environment when that environment exposes the local filesystem and Python process execution needed by the repository.

The intended Chat flow is:

```text
user dialogue in Chat
→ Chat-side tool/runtime invokes Nalu Studio `scripts/luna_voice.py`
→ backend auto-detects the 4 GiB cgroup
→ trusted Candidate B conditionals cache
→ T3 child process
→ process exit / memory release
→ S3Gen child process
→ 24 kHz mono PCM16 WAV
→ WAV returned to the Chat conversation
```

Typical direct invocation from the repository root is:

```bash
./engine/chatterbox-v3/venv/Scripts/python.exe -X utf8 scripts/luna_voice.py \
  "오늘의 이야기는 냉장고가 말한다 입니다" \
  --output /mnt/data/LUNA_chat.wav
```

`LUNA_VOICE_BACKEND=auto` is the normal Chat setting. On a Linux cgroup at or below 4 GiB, FAST automatically selects `lowmem`; no resident worker needs to be started first. On a larger-memory machine the same entry point keeps the original resident behavior. PRODUCTION continues to use the resident production path.

For an assistant integration, the minimal user experience can therefore be as small as:

```text
User: "즉시 발화 오늘의 이야기는 냉장고가 말한다 입니다"
Assistant: run the local FAST command, then return the resulting WAV.
```

The voice hot path should avoid unrelated repository/library/cloud searches once the local runtime is already ready. Re-reading remote documentation, reinstalling dependencies, or recomputing full multi-gigabyte hashes on every sentence defeats the purpose of the Chat path. Recovery checks belong only to a real missing/corrupt-runtime case.

CPU synthesis is still neural generation, so "즉시 발화" means immediate dispatch to the known-good path, not zero-second audio generation. The measured Chat CPU timings below are environment observations rather than a latency guarantee.

## Memory-safe execution

The low-memory backend keeps all voice invariants unchanged:

- Chatterbox Multilingual V3
- Candidate B reference and SHA-256
- language `ko`
- exaggeration `0.5`
- cfg `0.5`
- temperature `0.72`
- repetition penalty `1.2`
- min-p `0.05`
- top-p `1.0`
- seed contract unchanged
- 24 kHz mono PCM16 WAV

Execution is:

```text
trusted Candidate B conditionals cache
→ T3-only child process
→ process exit / memory release
→ S3Gen-only child process
→ PCM WAV
```

Additional 4 GiB safeguards:

- `torch.inference_mode()` for T3/S3 inference.
- two CPU threads for T3/S3 in the verified path.
- `POSIX_FADV_DONTNEED` only on the fixed T3/S3 weight files; no recursive cache scan.
- OOM exit (`-9`/`137`) gets one cache-release retry.
- phase timeout is 240 seconds and is not retried.
- full 3.2 GB model hashing is not done on every request; fixed sizes plus Candidate B SHA and the existing trusted conditionals manifest are used.

## Verification anchor

Input: `오늘의 이야기는 냉장고가 말한다 입니다`

- full T3 → S3 → WAV succeeded under the 4 GiB cgroup.
- no new `oom_kill` was observed in the verified run.
- 2-thread T3 produced the same 68 speech tokens as the earlier successful fixed-seed path.
- final verified low-memory launcher wall time: 67.054 seconds on the measured Chat CPU environment.
- T3 helper: 22.423 s (10.481 s inference).
- S3 helper: 24.917 s (18.559 s inference).
- output: 2.680 s, 24 kHz, mono, PCM16.
- WAV SHA-256: `f51f8e9c050946ee110057495c36f14fc6f219a7299ce41bc93fe2eccdc38c37`.

The timing is an environment measurement, not an SLA.
