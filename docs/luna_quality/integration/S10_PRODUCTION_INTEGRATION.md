# S10 production integration

## Safety boundary

`scripts/luna_narration_pipeline_v1.py` remains the only production narration
entry point. With every feature flag at its default `off` value, it does not
import or run the S08 shadow integration and preserves the existing Candidate B
generation, take cache, pins, beam search, pauses, output names, and report
schema.

Quality reports are written outside the production `OUTDIR`. The default is a
sibling directory named `<OUTDIR>.luna_quality_reports`; it can be overridden
with `LUNA_QUALITY_REPORT_DIR`, but a path inside `OUTDIR` is rejected.

## Feature flags

| Environment variable | Accepted values | Default | Effect |
| --- | --- | --- | --- |
| `LUNA_QUALITY_MODE` | `off`, `shadow`, `select` | `off` | Runs no quality integration, read-only evaluation, or approved selection. |
| `LUNA_CONDITIONALS_CACHE` | `off`, `on` | `off` | Reuses only an exactly fingerprinted Candidate B Chatterbox conditionals artifact. |
| `LUNA_ASR_VALIDATOR` | `off`, `on` | `off` | Enables the WhisperX content validator when its optional dependency is available. |
| `LUNA_SPEAKER_VALIDATOR` | `off`, `on` | `off` | Enables Candidate B speaker comparison with an explicit calibration artifact. |
| `LUNA_MOS_VALIDATOR` | `off`, `on` | `off` | Records `not_run`; no verified MOS adapter is promoted by S10. |
| `LUNA_PREFERENCE_RANKER` | `off`, `shadow`, `select` | `off` | Loads a compatible ranker for reporting or approved selection. |
| `LUNA_HYBRID_SYNTHESIS` | `off`, `experiment` | `off` | Records the experiment request only; S09 produced no real-audio evidence, so it cannot enter production selection. |

Optional path settings are `LUNA_QUALITY_REPORT_DIR`,
`LUNA_CONDITIONALS_CACHE_DIR`, `LUNA_RANKER_ARTIFACT`,
`LUNA_SPEAKER_CALIBRATION_ARTIFACT`, and
`LUNA_SELECT_APPROVAL_MANIFEST`.

An invalid flag value disables the integration session and leaves the existing
selector active. An unavailable optional model or validator is reported as
`unknown` or `not_run`; it is never silently represented as a pass.

## Modes

### Shadow

```powershell
$env:LUNA_QUALITY_MODE = 'shadow'
$env:LUNA_PREFERENCE_RANKER = 'shadow'
engine\chatterbox-v3\venv\Scripts\python.exe -X utf8 scripts\luna_narration_pipeline_v1.py JOBS.json OUTDIR
```

Shadow mode reads persisted takes after the existing measurement and gate step.
It never changes pins, picks, block audio, take audio, or production reports.
Missing optional dependencies remain visible in the separate quality report.

### Select

Select mode is fail-closed. It can propose a take only when all of the following
are true:

1. `LUNA_QUALITY_MODE=select` and `LUNA_PREFERENCE_RANKER=select`.
2. Hybrid and MOS flags are `off`.
3. The ranker artifact loads successfully, and the speaker calibration artifact
   has `status: calibrated_candidate` plus a finite
   `recommended_threshold_candidate` in the cosine range `[-1, 1]`.
4. A user-authored approval manifest uses schema
   `luna-production-select-approval/1`, contains `approved_by: USER` and
   `approved_for_production_select: true`, and matches the exact ranker,
   calibration, and feature-configuration SHA-256 values.
5. Every enabled hard validator is listed in `approved_validators` and returns
   `pass`; `unknown` and `not_run` cannot qualify.
6. Every unpinned phrase has at least two hard-gate survivors with the approved
   feature coverage and ranker confidence.
7. The complete proposed block still satisfies the existing take gate, block
   median band, pitch reset gate, and pin priority.

Any missing, stale, malformed, low-confidence, low-coverage, unknown, failed, or
empty condition rejects the entire proposal and uses the existing selector.
S10 ships no production approval manifest because S05/S07 did not establish
real calibrated production artifacts.

## Conditionals cache

The cache is restricted to Chatterbox Multilingual V3, Korean, exaggeration
`0.5`, and the fixed Candidate B reference hash. Its manifest fingerprints the
Chatterbox source, V3 T3 checkpoint, S3Gen checkpoint, voice encoder, tokenizer,
and reference audio. A missing manifest creates the cache once; a malformed or
mismatched manifest, missing artifact, checksum mismatch, or deserialization
failure falls back to the existing `audio_prompt_path` flow without overwriting
the suspect cache.

## Rollback and recovery

Set every feature flag to `off` to restore the pre-S10 path:

```powershell
$env:LUNA_QUALITY_MODE = 'off'
$env:LUNA_CONDITIONALS_CACHE = 'off'
$env:LUNA_ASR_VALIDATOR = 'off'
$env:LUNA_SPEAKER_VALIDATOR = 'off'
$env:LUNA_MOS_VALIDATOR = 'off'
$env:LUNA_PREFERENCE_RANKER = 'off'
$env:LUNA_HYBRID_SYNTHESIS = 'off'
```

The separate quality-report directory and conditionals-cache directory may be
retained for diagnosis or removed after the process exits. Neither is part of
the production output contract. Existing take checkpoints and completed block
reports keep their original resume behavior.
