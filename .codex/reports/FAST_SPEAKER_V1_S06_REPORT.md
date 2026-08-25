# Luna FAST Speaker v1 — S06 Reload, Restart, Recovery Report

## Scope completed

- Added a FAST-test-only JSON text overlay at `scripts/luna_quality/fast_speaker/rules/fast_test_rules.json`.
  - The initial overlay is a no-op.
  - Only `text_replacements` is reloadable.
  - Model, Candidate B reference, and generation settings are rejected as unsupported keys and are never loaded by the reload path.
  - Reload is transactional: parse and validate a candidate first, then swap the active overlay only on success.
- Added `Reload Rules`, `Restart Luna Worker`, `Retest Issue Sentence`, and `Resume Issue Context` controls.
- Restart now stops only volatile playback, saves a paused batch with any interrupted sentence reset to `PENDING`, and keeps UI-owned issue and session state intact. A successful worker health check is required before the controller accepts the replacement requester.
- The saved issue sentence can be retested with its original seed. A `RESOLVED` outcome resumes the containing batch from the beginning of the problem sentence.
- Added the persistent FAST Speaker verification protocol in `docs/luna_quality/fast_speaker/VERIFICATION_PROTOCOL.md`.

## Invariants

- Production `scripts/luna_narration_pipeline_v1.py` was not changed. SHA-256 verified: `781FD5D74B7B8F427D1EE229E8E9D9D43EC0C145EEF8F1ABDDF296FCC93BC5BF`.
- Candidate B was not changed. SHA-256 verified: `30C6D3405F46684AF467C7D26FF40A2FB57DD48CC84CD24CF7403D9AA00A2BB9`.
- Reload has no engine/model/reference access and reports that source-code changes require `Restart Luna Worker`.

## Verification loop

### Pass 1

Command:

```powershell
& .\engine\chatterbox-v3\venv\Scripts\python.exe -X utf8 -m unittest tests.luna_quality.unit.test_fast_speaker_rules tests.luna_quality.unit.test_fast_speaker_controller tests.luna_quality.unit.test_fast_speaker_batch tests.luna_quality.unit.test_fast_speaker_issues tests.luna_quality.unit.test_fast_speaker_worker -v
```

Result: 15 tests passed.

Finding: while a worker restart was in progress, the controller could still retain volatile work for the old requester. This would not change persisted data, but it could leave a failed restart pointing at a stopped worker.

Correction: stop volatile playback before restarting, convert the active batch sentence to `PENDING`, atomically save that state, and test its recovery.

### Pass 2

Focused command above after the correction: 16 tests passed.

Expanded command:

```powershell
& .\engine\chatterbox-v3\venv\Scripts\python.exe -X utf8 -m unittest discover -s tests/luna_quality/unit -p 'test_fast_speaker_*.py' -v
```

Result: 21 tests passed.

Finding: a `RESOLVED` retest still required a separate manual context-resume click.

Correction: `RESOLVED` now invokes the saved issue-context resume path automatically when a batch is active.

### Final pass

```powershell
& .\engine\chatterbox-v3\venv\Scripts\python.exe -X utf8 -m py_compile scripts/luna_quality/fast_speaker/rules.py scripts/luna_quality/fast_speaker/controller.py scripts/luna_quality/fast_speaker/batch.py scripts/luna_quality/fast_speaker/ui.py
& .\engine\chatterbox-v3\venv\Scripts\python.exe -X utf8 -m unittest discover -s tests/luna_quality/unit -p 'test_fast_speaker_*.py' -v
```

Result: syntax check passed; 21 tests passed. No remaining in-scope issue was found.

## Not run

- Real Chatterbox model/GPU integration was not run in this stage. The external-process restart gate was exercised with the deterministic FAST test backend so no production audio or model state was altered.
