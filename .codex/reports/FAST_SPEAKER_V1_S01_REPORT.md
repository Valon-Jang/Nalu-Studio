# FAST Speaker v1 S01 Completion Report

## Outcome

S01 is complete. The current FAST one-take primitive is now available through
a small in-memory adapter contract while the existing `scripts/luna_voice.py`
FAST WAV path remains intact.

The detailed contract and quantization evidence are in
`docs/luna_quality/fast_speaker/S01_RUNTIME_CONTRACTS_REGRESSION.md`.

## Delivered

- Added a transport-free `FastBackend` contract, `FastPhrase`, and
  `FastSynthesisResult` with schema/version and explicit seed/sample metadata.
- Added `LunaFastBackend` that reuses the existing resident V3/Candidate B
  runtime, production `respell`, and `build_phrase_list` helpers without
  changing their rules.
- Added a deterministic fake backend with known PCM16LE bytes for later
  worker/controller/UI tests.
- Added an adapter-only in-memory invocation that reuses the resident runtime
  model, lock, seed setter, current `respell`, fixed V3 parameters, and current
  0.89 peak guard. `_run_fast()` and its legacy PCM16 WAV writer are unchanged.
- Added a seven-case phrase/configuration baseline fixture and deterministic
  adapter, contract, and regression coverage.

## Frozen compatibility

- Candidate B reference and hash, V3 engine, prepared conditionals, fixed FAST
  generation parameters, production pipeline, current CLI, TCP transport, and
  existing output naming were not changed.
- No UI, IPC, worker process, raw PCM transport, playback dependency, queue,
  batch feature, issue workflow, rule overlay, or production selection change
  was introduced.
- The ordinary current FAST route still writes a PCM16 WAV through
  `torchaudio`; the in-memory result itself writes no WAV.

## Verification

```text
compileall PASS
108 unit tests PASS (9.052 s)
10 regression tests PASS, 1 opt-in real test skipped by default (7.504 s)
S01 opt-in real V3 PCM repeatability / WAV quantization test PASS (108.328 s)
S12 opt-in real Korean FAST resident-reuse integration PASS (107.126 s)
git diff --check PASS for S01 paths
```

The S01 real test confirmed byte-identical in-memory PCM16LE for two same-seed
generations. Direct PCM conversion and the current `torchaudio` WAV encoding
had equal sample counts and at most one LSB difference; S01 records that exact
limit instead of making an unsupported bitwise-WAV claim.

## Stage boundary

S02 has not started. This report is a manual approval handoff only.

## Repository-state note

The worktree contains pre-existing uncommitted S12 and stage-gate-removal
changes. S01 preserves them and commits only its namespaced contract, adapter,
fixture, tests, and documentation.

## Verdict

`READY_FOR_S02_AFTER_USER_APPROVAL`
