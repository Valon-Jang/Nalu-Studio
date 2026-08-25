# FAST Speaker v1 S00 Completion Report

## Outcome

Repository audit and current FAST baseline are complete. The detailed deliverable is:

- `docs/luna_quality/baseline/fast_speaker_v1/S00_REPO_AUDIT.md`

The audit found a safe, narrow path to S01. No material production architecture change is required.

## Key findings

- Current FAST is `scripts/luna_voice.py` backed by `scripts/luna_quality/voice_runtime/`.
- The model and trusted Candidate B condition are already resident and reused.
- Current FAST applies respell but does not split phrases; it generates the entire request once and writes a WAV.
- FAST Speaker v1 will preserve that per-phrase generation primitive while adding app-level Luna splitting and in-memory PCM.
- The existing S12 CLI remains whole-request and WAV-compatible.
- The desktop app should use a separate canonical-Python worker over Windows AF_PIPE, not turn the S12 TCP service into the app transport.
- No suitable in-memory playback package is currently installed; S03 should add a UI-only dependency in a separate venv.
- Production pipeline, voice assets, model runtime, approved audio, caches, and rules were not changed.

## Verification

```text
103 unit tests PASS (14.510 s)
6 release regression tests PASS (7.617 s)
compileall PASS
real Korean FAST integration PASS (two requests, 130.011 s wall)
model_load_count=1
condition_prepare_count=1
```

The real integration used temporary outputs that were automatically removed.

## Stage boundary

S01 has not started. The next stage may only begin after explicit user approval of this S00 report.

## Repository-state note

The worktree was already dirty before S00 with the uncommitted S12 implementation and stage-gate-removal changes. S00 preserved those user-owned changes and added only its namespaced audit/report/completion request. The legacy `.codex/stage_state.json` was not directly edited.

## Verdict

`READY_FOR_S01_AFTER_USER_APPROVAL`
