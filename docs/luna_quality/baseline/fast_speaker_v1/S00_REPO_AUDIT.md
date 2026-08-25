# Luna FAST Speaker v1 — S00 Repository Audit

- Stage: `FAST_SPEAKER_V1/S00`
- Audit date: `2026-08-25` (Asia/Seoul)
- Repository root: `C:\Users\tequi\Gongdaeluna-Studio`
- Git branch / HEAD: `main` / `4cec4a8175687d278d0f1c3f35cbf284c1e16114`
- Source package: `references/LUNA_FAST_SPEAKER_V1_CODEX_PACKAGE.zip`
- Source package SHA-256: `69912385216b868183e8e90ab5c507030335d00fef0ea4056d76002cfc78a678`
- Verdict: `READY_FOR_S01_AFTER_USER_APPROVAL`

## 1. Scope and authority

This audit applies the following precedence:

1. `.agents/skills/luna-narration/SKILL.md`
2. `LUNA_FAST_SPEAKER_V1_CODEX_PACKAGE/00_LUNA_FAST_SPEAKER_V1_MASTER_HANDOFF.md`
3. Current repository code and tests
4. Approved prior-stage reports

S00 changed no synthesis code, voice rule, model/runtime file, dependency, cache, or audio. It did not build the UI or begin S01.

The legacy validator/ranker stage state still records `S12 / COMPLETE_AWAITING_USER_APPROVAL`; the user explicitly approved S12 and requested this independent FAST Speaker v1 S00 on 2026-08-25. The removed stage-gate files and the existing dirty worktree were treated as pre-existing user-owned state and were not altered.

## 2. Current repository map

### Current FAST user path

| Role | Physical path | Current behavior |
|---|---|---|
| User CLI | `scripts/luna_voice.py` | Text input defaults to `fast`; auto-starts the resident worker and returns WAV + JSON. |
| Request contract | `scripts/luna_quality/voice_runtime/contract.py` | `luna-voice-request/1`; `fast|production`; 2,000-character request limit; default seed `20260823`. |
| Resident runtime | `scripts/luna_quality/voice_runtime/runtime.py` | Owns one model and one Candidate B condition for the process lifetime; serializes synthesis with a lock. |
| Candidate B conditioning | `scripts/luna_quality/voice_runtime/conditioner.py` | Verifies Candidate B hash; loads or creates the trusted official `Conditionals` cache. |
| Current transport | `scripts/luna_quality/voice_runtime/transport.py` | Single-process localhost TCP server on `127.0.0.1:18765`. |
| S12 unit regression | `tests/luna_quality/unit/test_s12_fast_production_integration.py` | Covers contract, one-take FAST, fixed parameters, resident reuse, CLI, transport, and safe production dispatch. |
| S12 real integration | `tests/luna_quality/integration/test_s12_resident_korean_fast.py` | Generates two real Korean FAST WAVs in one runtime and verifies model/condition reuse. |

These S12 implementation files currently exist only in the working tree and are not present in Git HEAD `4cec4a8`. They are nevertheless the exact current FAST implementation described by the completed S12 report and exercised by the current tests.

### Production path

| Role | Physical path | Contract |
|---|---|---|
| Production entry point | `scripts/luna_narration_pipeline_v1.py` | `JOBS.json + OUTDIR`; best-of-N, gates, pins, beam assembly, WAV/report outputs. |
| Quality integration | `scripts/luna_quality/production_integration.py` | Default-off integration; S12 PRODUCTION explicitly uses shadow mode. |
| Runtime | `engine/chatterbox-v3` | Canonical Chatterbox Multilingual V3 CPU runtime. |
| Canonical Python | `engine/chatterbox-v3/venv/Scripts/python.exe` | Python 3.12.10, 64-bit Windows build. |
| Chatterbox source | `engine/chatterbox-v3/chatterbox/src/chatterbox/mtl_tts.py` | Loads `t3_model="v3"`; prepares/uses `Conditionals`; produces 24 kHz audio. |
| Offline model cache | `engine/chatterbox-v3/hf-cache` | `HF_HUB_OFFLINE=1` and related offline settings. |

## 3. Frozen identity and assets

| Item | Path | Current SHA-256 |
|---|---|---|
| Candidate B | `assets/voice_ref/B_voiced_spectral_micro_smooth.wav` | `30c6d3405f46684af467c7d26ff40a2fb57dd48cc84cd24cf7403d9aa00a2bb9` |
| Prosody target | `assets/voice_ref/LUNA_PROSODY_TARGET.json` | `267e79ec088933c9c43b6584e90bd04b2b4e77eaba3134a669d151c464458bae` |
| Production pipeline | `scripts/luna_narration_pipeline_v1.py` | `781fd5d74b7b8f427d1ee229e8e9d9d43ec0c145eef8f1abddf296fcc93bc5bf` |
| Chatterbox V3 source | `engine/chatterbox-v3/chatterbox/src/chatterbox/mtl_tts.py` | `96fd2dfbd947d3b617fdada8721264bc6597799e81ebf8e43603f083f72fe433` |
| Current FAST CLI | `scripts/luna_voice.py` | `8f915112f971c56919ade2e639436867fa73bc649937b488bb3ee6eb04666d6f` |

Fixed FAST generation parameters are:

```text
language_id=ko
exaggeration=0.5
cfg_weight=0.5
temperature=0.72
repetition_penalty=1.2
min_p=0.05
top_p=1.0
```

The Candidate B conditionals cache is present at `.luna_quality_cache/conditionals/` with cache key `191eba963b0e2451046a157c314e8c672b84b484ccbea9401224b070cef6c097`. Its manifest binds the V3 source, T3/S3Gen/VE/tokenizer hashes, reference hash, language, and exaggeration. The cache is read-only input to FAST Speaker work; S00 did not rewrite it.

## 4. Exact current FAST flow

```text
scripts/luna_voice.py
  -> ensure_worker()
     -> canonical production Python
     -> LunaVoiceRuntime.start()
        -> ChatterboxMultilingualTTS.from_pretrained(device="cpu", t3_model="v3")
        -> CandidateBConditioner.prepare()
           -> validate Candidate B SHA-256
           -> load trusted official Conditionals cache, or create only on clean manifest absence
  -> VoiceRequest.from_mapping()
  -> LunaVoiceRuntime.handle() under one process lock
     -> pipeline.respell(text)
     -> set Python / NumPy / Torch seed
     -> model.generate(spoken_text, audio_prompt_path=None, fixed parameters)
     -> peak guard at 0.89
     -> torchaudio PCM16 WAV write
     -> JSON response
```

### Model load and conditioning

- `LunaVoiceRuntime.start()` loads the model once.
- `CandidateBConditioner.prepare()` runs once per runtime and installs `model.conds`.
- FAST then passes `audio_prompt_path=None`, so Chatterbox reuses the prepared condition instead of re-analyzing Candidate B.
- Chatterbox `generate()` asserts that `self.conds` exists when no audio prompt path is supplied.

### Seed path

FAST uses the request seed directly and sets:

```text
random.seed(seed)
numpy.random.seed(seed mod (2^32 - 1))
torch.manual_seed(seed)
```

Production instead derives take seeds as:

```text
(block_seed + phrase_index * 104729 + take_index * 7919) mod 2^31
```

The FAST Speaker app must preserve the current direct seed semantics per generated phrase and define phrase-seed derivation explicitly in S01. It must not silently borrow production best-of-N take derivation.

### Text normalization and phrase splitting

Current FAST applies only `pipeline.respell(text)`. It does **not** call `split_sentences`, `split_phrases`, or `build_phrase_list`; a request is one `model.generate` call even when it contains multiple sentences.

The production Luna splitter already provides the authoritative current Luna phrase rules:

- `respell`
- `split_sentences`
- `split_phrases`
- `force_split`
- `build_phrase_list`

The desktop app requires phrase-first playback, so it must orchestrate these existing rules before issuing per-phrase FAST calls. The compatibility interpretation for v1 is:

- preserve the current FAST synthesis primitive exactly for each phrase;
- preserve `scripts/luna_voice.py` whole-request behavior and output contract;
- add app-level phrase orchestration without modifying the production splitter;
- regression-test both paths separately.

This is a controlled adapter boundary, not a reason to rewrite production.

### Current FAST postprocessing and output

Current FAST postprocessing is limited to:

1. use the model's returned 24 kHz mono tensor;
2. if peak exceeds `0.89`, scale to `0.89`;
3. write PCM16 WAV with `torchaudio.save`.

It does not apply the production trim, 30 ms pad, 12 ms fade, -20 dBFS RMS normalization, phrase pause insertion, prosody measurement, gate, rank, or beam assembly. S01 must freeze this distinction.

Current FAST always writes a WAV. No raw/in-memory PCM return surface exists yet.

### Existing timing/report functions

Available now:

- runtime cold startup seconds;
- per-request model generation seconds;
- model load count;
- condition preparation count;
- output sample rate and provenance.

Missing for FAST Speaker v1:

- PCM/audio duration;
- phrase RTF;
- UI-accepted request timestamp;
- first non-silent sample handed to audio callback;
- warm TTFA;
- inter-phrase underrun/gap;
- rolling RTF;
- playback state metrics.

Production `measure_take()` computes trimmed duration and prosody metrics, but it is intentionally excluded from the normal FAST playback critical path.

## 5. Deterministic phrase baseline

The following current splitter observations were recorded without audio generation:

| Case | Input result |
|---|---|
| Short statement | `공대루나입니다.` -> one final phrase |
| Longer statement | `아이언맨 슈트에는 냉각 기술이 반드시 필요합니다.` -> one final phrase |
| Question | `이제 바닷속 케이블을 건널까요?` -> respelled punctuation `.`; one final phrase; question ending remains detectable after trimming punctuation |
| Number | `천팔백오십팔년에는 새로운 기술이 등장했습니다.` -> one final phrase |
| Multi-phrase | `거미줄은 유연한 부분과` (forced continuation) + `단단한 부분이 함께 구조를 지탱합니다.` (final) |
| Modifier edge | `아주 유연한 부분이 충격을 흡수합니다.` remains one phrase; no cut after `유연한` |
| Locative edge | `손목에서 거미줄을 발사합니다.` remains one phrase; no cut after `손목에서` |

These strings form the minimum S01 regression fixture. They do not establish subjective audio acceptance.

## 6. Real baseline and test results

### Fresh S00 verification

| Check | Result |
|---|---|
| All deterministic Luna quality unit tests | `103 PASS`, `14.510 s` |
| Release regression suite | `6 PASS`, `7.617 s` |
| Compile current FAST runtime/CLI/tests | PASS |
| Real Korean FAST integration | `1 PASS`, two requests, `130.011 s` total wall time |
| Model reused across two real requests | PASS, `model_load_count=1` |
| Candidate B condition reused | PASS, `condition_prepare_count=1` |
| Both real outputs | PASS, non-empty mono PCM WAV at 24 kHz; test temp data auto-removed |

The fresh real test measures model startup plus two full CPU generations. Its current test does not print per-request timing, so the total must not be misreported as TTFA or individual generation latency.

### Existing S12 measured evidence

The approved S12 report records:

- resident startup: `26.966 s`;
- one short FAST generation (`상주 워커 검증입니다.`): `33.742 s`;
- output: 24 kHz PCM WAV, `84,524` bytes;
- earlier two-request real integration wall time: `162.243 s`.

These are machine/load-specific observations, not acceptance targets. They confirm that resident conditioning removes repeated setup but CPU synthesis remains much slower than immediate playback.

## 7. Dependency and Windows inventory

Canonical worker environment:

```text
Python 3.12.10 (64-bit)
Windows 11 build 26200
Tk 8.6
torch 2.6.0
torchaudio 2.6.0
numpy 1.26.4
librosa 0.11.0
soundfile 0.14.0
scipy 1.17.1
chatterbox-tts 0.1.7
huggingface-hub 1.26.0
safetensors 0.5.3
resemble-perth 1.0.1
```

Audio playback inventory:

- `winsound`: available, but its file-oriented playback is unsuitable for the required in-memory PCM callback path;
- `sounddevice`: not installed;
- `simpleaudio`: not installed;
- `pyaudio`: not installed;
- `pygame`: not installed;
- no repository playback implementation exists;
- Tkinter is available.

The unqualified `python` command resolves to 32-bit Python 3.9.13 and must not run the model. The production worker must always use `engine/chatterbox-v3/venv/Scripts/python.exe`.

Recommended environment boundary:

- keep the production TTS venv unchanged;
- create a separate ignored UI venv at `fast_speaker/.venv/` from a supported 64-bit Python;
- install the future Windows PCM playback dependency only there;
- launch the model worker with the canonical production Python;
- use a Windows named pipe (`multiprocessing.connection` / `AF_PIPE`) for app IPC, not the S12 localhost TCP service.

`sounddevice` is the current preferred S03 candidate because a callback stream can consume in-memory PCM and mark the specified first-sample timing point. Its install and real default-device smoke test belong to S03, not S00.

Windows constraints to preserve:

- never run inference on the Tk event thread;
- use spawn-safe top-level worker entry points and `if __name__ == "__main__"` guards;
- do not print Korean from the production worker to a CP949 console;
- use atomic replace for persisted JSON;
- Stop invalidates stale generation results rather than killing the worker for every request;
- device enumeration was not available to this restricted audit process, so S03 must verify the real default output device interactively.

## 8. Architecture compatibility assessment

### Compatible without production rewrite

The current runtime already provides the two highest-cost reusable objects: the loaded V3 model and prepared Candidate B condition. A narrow S01 extraction can expose the current FAST tensor before WAV writing, while the existing CLI continues to write exactly the same WAV/JSON.

The app can then add:

```text
Tkinter UI process
  -> controller / phrase queue
  -> AF_PIPE IPC
  -> canonical-Python worker
     -> existing model + Candidate B condition
     -> existing FAST per-phrase generation primitive
     -> PCM16 bytes + metadata
  -> callback audio sink
```

No change is required to `scripts/luna_narration_pipeline_v1.py`, Candidate B, the production venv, or production outputs.

### Explicit compatibility constraints

1. **Whole-request FAST versus phrase-first app:** the existing CLI remains whole-request; only the app adds Luna phrase orchestration. Baseline tests must prevent accidental CLI behavior drift.
2. **Current TCP worker versus product non-goal:** the S12 TCP service remains for the existing CLI, but the desktop app must not become a network API server. Use an app-specific named pipe.
3. **Disk WAV versus memory PCM:** S01 extracts a shared in-memory result; the current CLI still calls the existing WAV writer. Ordinary Speaker playback must never route through a temporary WAV.
4. **Model cancellation:** Chatterbox generation is not safely preemptible. Stop must clear playback/queues and invalidate the run token; an in-flight result may finish but must be discarded.
5. **Serial inference:** one model is shared and current runtime locking is serial. Phrase generation can overlap playback, but two model calls must not run concurrently.

None of these requires an unapproved material production architecture change. S00 therefore does not return `BLOCKED_ARCHITECTURE_CHANGE`.

## 9. Exact proposed physical layout

```text
scripts/luna_fast_speaker.py                         # S03 desktop entry point
scripts/luna_quality/fast_speaker/
  __init__.py                                        # S01
  contracts.py                                       # S01 app/backend contracts
  fast_adapter.py                                    # S01 split + unchanged FAST primitive adapter
  pcm.py                                             # S02 versioned in-memory PCM contract
  metrics.py                                         # S02 synth/duration/RTF timing
  ipc.py                                             # S02 Windows AF_PIPE protocol
  worker.py                                          # S02 canonical-Python resident worker
  controller.py                                      # S03 queue/state/stale-token controller
  audio_sink.py                                      # S03 default-device callback playback
  ui.py                                              # S03 Tkinter UI
  batch.py                                           # S04 newline-first sentence parser/state
  session_store.py                                   # S04 atomic persistence/recovery
  issues.py                                          # S05 issue/revision evidence
  codex_request.py                                   # S05 standalone request generator
  rules.py                                           # S06 transactional FAST-test overlay reload

tests/luna_quality/fixtures/fast_speaker_benchmark.json
tests/luna_quality/unit/test_fast_speaker_contracts.py
tests/luna_quality/unit/test_fast_speaker_adapter.py
tests/luna_quality/unit/test_fast_speaker_worker.py
tests/luna_quality/unit/test_fast_speaker_controller.py
tests/luna_quality/unit/test_fast_speaker_audio.py
tests/luna_quality/unit/test_fast_speaker_batch.py
tests/luna_quality/unit/test_fast_speaker_persistence.py
tests/luna_quality/unit/test_fast_speaker_issues.py
tests/luna_quality/unit/test_fast_speaker_rules.py
tests/luna_quality/integration/test_fast_speaker_real_worker.py
tests/luna_quality/integration/test_fast_speaker_real_audio.py
tests/luna_quality/regression/test_fast_speaker_baseline.py

requirements-luna-fast-speaker.txt                   # UI-only dependencies
scripts/Start-LunaFastSpeaker.ps1                    # S03 Windows launcher
fast_speaker/.gitignore                              # ignore runtime/private data
fast_speaker/rules/fast_test_rules.json              # S06 no-op initial overlay
fast_speaker/sessions/**                             # ignored runtime data
fast_speaker/issues/**                               # ignored private issue evidence
fast_speaker/state/**                                # ignored recovery state
fast_speaker/logs/**                                 # ignored local logs

docs/luna_quality/fast_speaker/S01_*.md ... S07_*.md
```

The source package stays under `scripts/luna_quality/` because it is a listening-QA tool built around the existing resident voice runtime and current test conventions. Runtime/session evidence stays in project-local `fast_speaker/` so copied Codex requests can reference accessible paths; private/generated content must be ignored by Git.

## 10. Proposed stage write scopes

All stages may write their own `docs/luna_quality/fast_speaker/<STAGE>_*.md` and `.codex/reports/FAST_SPEAKER_V1_<STAGE>_REPORT.md` only.

### S01 — contracts, baseline regression, safe FAST extraction

Allowed:

```text
scripts/luna_quality/fast_speaker/__init__.py
scripts/luna_quality/fast_speaker/contracts.py
scripts/luna_quality/fast_speaker/fast_adapter.py
scripts/luna_quality/voice_runtime/runtime.py
tests/luna_quality/fixtures/fast_speaker_benchmark.json
tests/luna_quality/unit/test_fast_speaker_contracts.py
tests/luna_quality/unit/test_fast_speaker_adapter.py
tests/luna_quality/regression/test_fast_speaker_baseline.py
docs/luna_quality/fast_speaker/S01_*.md
```

`scripts/luna_quality/voice_runtime/runtime.py` may only extract an in-memory FAST primitive and route the existing `_run_fast` through it. The S12 CLI response, WAV bytes/format, seed, parameters, conditioning, and PRODUCTION dispatch must remain compatible.

### S02 — resident app worker, PCM, metrics, IPC

Allowed:

```text
scripts/luna_quality/fast_speaker/contracts.py
scripts/luna_quality/fast_speaker/fast_adapter.py
scripts/luna_quality/fast_speaker/pcm.py
scripts/luna_quality/fast_speaker/metrics.py
scripts/luna_quality/fast_speaker/ipc.py
scripts/luna_quality/fast_speaker/worker.py
tests/luna_quality/unit/test_fast_speaker_worker.py
tests/luna_quality/integration/test_fast_speaker_real_worker.py
docs/luna_quality/fast_speaker/S02_*.md
```

### S03 — Tkinter manual speaker, callback audio, Stop/Pause

Allowed:

```text
scripts/luna_fast_speaker.py
scripts/Start-LunaFastSpeaker.ps1
scripts/luna_quality/fast_speaker/contracts.py
scripts/luna_quality/fast_speaker/controller.py
scripts/luna_quality/fast_speaker/audio_sink.py
scripts/luna_quality/fast_speaker/ui.py
tests/luna_quality/unit/test_fast_speaker_controller.py
tests/luna_quality/unit/test_fast_speaker_audio.py
tests/luna_quality/integration/test_fast_speaker_real_audio.py
requirements-luna-fast-speaker.txt
fast_speaker/.gitignore
docs/luna_quality/fast_speaker/S03_*.md
```

### S04 — batch mode and persistence

Allowed:

```text
scripts/luna_quality/fast_speaker/contracts.py
scripts/luna_quality/fast_speaker/controller.py
scripts/luna_quality/fast_speaker/ui.py
scripts/luna_quality/fast_speaker/batch.py
scripts/luna_quality/fast_speaker/session_store.py
tests/luna_quality/unit/test_fast_speaker_batch.py
tests/luna_quality/unit/test_fast_speaker_persistence.py
fast_speaker/.gitignore
docs/luna_quality/fast_speaker/S04_*.md
```

### S05 — issue capture, evidence, Codex request, revisions

Allowed:

```text
scripts/luna_quality/fast_speaker/contracts.py
scripts/luna_quality/fast_speaker/controller.py
scripts/luna_quality/fast_speaker/ui.py
scripts/luna_quality/fast_speaker/issues.py
scripts/luna_quality/fast_speaker/codex_request.py
tests/luna_quality/unit/test_fast_speaker_issues.py
fast_speaker/.gitignore
docs/luna_quality/fast_speaker/S05_*.md
```

### S06 — transactional rule reload and worker recovery

Allowed:

```text
scripts/luna_quality/fast_speaker/contracts.py
scripts/luna_quality/fast_speaker/controller.py
scripts/luna_quality/fast_speaker/worker.py
scripts/luna_quality/fast_speaker/ipc.py
scripts/luna_quality/fast_speaker/ui.py
scripts/luna_quality/fast_speaker/rules.py
tests/luna_quality/unit/test_fast_speaker_rules.py
tests/luna_quality/unit/test_fast_speaker_restart.py
fast_speaker/rules/fast_test_rules.json
docs/luna_quality/fast_speaker/S06_*.md
```

### S07 — final review only

Allowed:

```text
docs/luna_quality/fast_speaker/S07_FINAL_REVIEW.md
.codex/reports/FAST_SPEAKER_V1_S07_REPORT.md
```

If S07 finds a code defect, it must report FAIL and request a bounded repair stage rather than silently altering reviewed code.

### Forbidden in every FAST Speaker v1 stage

```text
.agents/skills/luna-narration/SKILL.md
.claude/skills/luna-narration/SKILL.md
assets/voice_ref/**
engine/chatterbox-v3/**
projects/**/audio/**
projects/**/*_pins.json
scripts/luna_narration_pipeline_v1.py
scripts/luna_quality/production_integration.py
scripts/luna_quality/voice_runtime/conditioner.py
scripts/luna_quality/voice_runtime/contract.py
scripts/luna_quality/voice_runtime/transport.py
scripts/luna_voice.py
requirements-luna-quality-v2.txt
.codex/stage_plan.json
.codex/stage_state.json
.github/workflows/**
tools/stage_gate.py
references/LUNA_FAST_SPEAKER_V1_CODEX_PACKAGE.zip
```

Existing production cache, final audio, and frozen project outputs must not be regenerated, deleted, or invalidated.

## 11. Risks and blockers

| Risk | Status / mitigation |
|---|---|
| Current FAST files are untracked relative to HEAD | High process risk. Preserve them; establish a clean approved repository baseline before S01 commit/acceptance. |
| Existing FAST accepts whole text, but Speaker must stream phrases | Resolved by explicit app-orchestration interpretation and separate regression paths. User approval of this S00 approves that boundary. |
| No in-memory PCM API | S01 narrow extraction; current CLI continues its existing WAV writer. |
| No suitable callback playback dependency | S03 adds a UI-only dependency in a separate venv; production venv remains unchanged. |
| Current S12 transport is TCP while v1 excludes network API server | Preserve S12 CLI; use Windows AF_PIPE only for the desktop app. |
| CPU generation is slower than playback for observed short phrases | Measure honestly; v1 does not change quality/parameters to chase RTF. Underruns are reported, not hidden. |
| In-flight generation cannot be safely cancelled | Use run/generation tokens; stale PCM is discarded and never played. |
| Private issue audio could be committed | Project-local runtime directories must be ignored before issue capture exists. |
| Default audio device was not inspectable in the restricted audit | S03 requires interactive real-device verification. |
| Legacy stage state still names S12 | Namespace all FAST Speaker reports and use manual user approvals; do not directly edit the legacy state file. |

No current fact requires `BLOCKED_ARCHITECTURE_CHANGE`.

## 12. Recommended S01 approach

1. Add the benchmark fixture and regression tests before refactoring.
2. Freeze current FAST request defaults, direct seed behavior, respell behavior, fixed generation kwargs, `audio_prompt_path=None`, peak guard, PCM16/24 kHz WAV, and S12 JSON response.
3. Extract one in-memory FAST primitive from `LunaVoiceRuntime` that returns the generated tensor plus sample rate and synthesis timing.
4. Keep `_run_fast()` as the compatibility adapter that invokes that primitive and the existing WAV writer.
5. Add `fast_adapter.py` with two explicit surfaces:
   - app-level `split_for_speaker()` importing the unchanged Luna splitter;
   - per-phrase `synthesize_fast_phrase()` invoking the unchanged FAST primitive.
6. Use a fake backend for deterministic extraction tests and one opt-in real before/after regression.
7. Run all current unit/release tests and the S12 real integration.
8. Stop after S01; do not add worker, audio, or UI code.

## 13. S00 completion checklist

- [x] Authoritative skill and package handoff read fully
- [x] Current FAST and production paths located
- [x] Model, Candidate B conditioning, seed, text, generation, postprocess, output, and metrics mapped
- [x] Playback dependency and Windows constraints inventoried
- [x] Current test coverage identified
- [x] Deterministic splitter baseline recorded
- [x] Fresh unit, release, compile, and real FAST verification passed
- [x] Exact module layout proposed
- [x] S01-S07 write scopes and global forbidden paths proposed
- [x] Production code, voice assets, runtime, cache, and audio unchanged
- [x] No S01 implementation created

S00 is ready for user review. S01 must not start until explicitly approved in a new request.
