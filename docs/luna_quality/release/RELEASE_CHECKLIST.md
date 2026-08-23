# Luna quality release checklist

Current decision: `SHADOW_ONLY_APPROVED`

## Required for the current local shadow release

- [x] Active stage and protected hashes verified.
- [x] Production entry point remains singular.
- [x] Candidate B hash matches the protected value.
- [x] All six pinned Chatterbox checkpoint hashes match S00.
- [x] All 17 frozen final WAV and two timing hashes match S00.
- [x] Production generation parameters and output names match S00.
- [x] All feature flags default to `off`.
- [x] Default-off completed-block resume leaves the block report unchanged.
- [x] Shadow reports are outside production `OUTDIR` and inputs remain byte-identical.
- [x] Hard failures cannot be compensated by ranker/MOS scores.
- [x] `pass`, `fail`, `unknown`, and `not_run` remain distinct.
- [x] V3 loads on Windows CPU at 24 kHz without generating audio.
- [x] Candidate B conditionals actual save/load round-trip passes.
- [x] Unit and release regression suites pass.
- [x] Rollback instructions exist and use feature flags first.
- [x] Prosody Bank backup/restore and ranker retrain procedures are documented.
- [x] Skill changes are proposal-only; project skill is unmodified.

## Explicitly unavailable in this release

- [ ] Production `select` approval.
- [ ] Real preference ranker artifact and grouped human-data evaluation.
- [ ] Real speaker calibration artifact.
- [ ] WhisperX Korean transcription/alignment integration pass.
- [ ] Pinned SpeechBrain package/model integration pass.
- [ ] MOS adapter or MOS-based release gate.
- [ ] Real hybrid synthesis/blind-listening evidence.
- [ ] Reproducible root dependency lock.
- [ ] Complete redistributable third-party LICENSE/NOTICE bundle.
- [ ] Candidate B redistribution authority stored outside the private workflow.

Unchecked items are intentional blockers, not waived tests. They must remain
visible in every release decision.

## Operator preflight

```powershell
python -X utf8 tools\stage_gate.py verify
python -X utf8 tools\stage_gate.py check-scope
& .\engine\chatterbox-v3\venv\Scripts\python.exe -X utf8 -m unittest discover -s tests\luna_quality\unit -p test_*.py
& .\engine\chatterbox-v3\venv\Scripts\python.exe -X utf8 -m unittest discover -s tests\luna_quality\regression -p test_*.py
```

For ordinary production-compatible operation, explicitly keep all flags off.
For approved read-only evaluation, enable only `LUNA_QUALITY_MODE=shadow` and
the optional validators whose pinned local dependencies have been reviewed.

## Promotion review gate

Before creating a production select approval manifest, attach all of the
following to a new review:

1. Prosody Bank backup and schema version.
2. Export/data SHA-256 and source hashes.
3. Ranker artifact SHA-256, feature schema, grouped evaluation and calibration.
4. Speaker calibration artifact SHA-256 and dataset provenance.
5. Exact optional package/model revisions and licenses.
6. Integration results on an approved non-private fixture.
7. Pin precedence, unknown/not-run, empty-survivor and rollback results.
8. Human approval identifying the exact feature-config SHA-256.

Do not infer approval from this checklist or from synthetic fixture scores.
