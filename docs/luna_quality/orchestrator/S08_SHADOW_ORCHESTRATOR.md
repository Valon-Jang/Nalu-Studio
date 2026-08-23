# S08 Shadow Quality Orchestrator

## Purpose

`scripts.luna_quality.orchestrator` reads an existing Luna output directory,
evaluates individual takes, and writes a new shadow report outside that input
directory. It never changes production selection, `pins.json`, take JSON/WAV,
or the production pipeline.

## Command

```powershell
python -X utf8 -m scripts.luna_quality.cli shadow-evaluate `
  --outdir <EXISTING_OUTDIR> `
  --report <NEW_REPORT_OUTSIDE_OUTDIR>
```

`--enable-asr` explicitly enables the optional lazy WhisperX path. Without it,
content ASR remains `not_run`; it is not treated as a successful check.
`--ranker-artifact <PATH>` loads an S07 artifact only if its schema is valid.

The CLI rejects a report location inside `--outdir`. A SHA-256 manifest of the
entire input directory is calculated before and after evaluation; the report
records `read_only_verified`.

## Evaluation order and policy

1. Discover `P##_t#.json` and sibling WAV files.
2. Audio sanity hard gate.
3. Content/ASR result.
4. Speaker result.
5. Import persisted `ok`/`why` from the take JSON as the existing prosody gate.
6. Optional MOS result.
7. Build the hard-gate survivor set.
8. Use an active preference ranker, or a transparent persisted-metrics quality
   fallback when the ranker is missing or disabled.
9. Compare shadow top-1/top-3 with the actual selection from `*_pins.json` or
   `*_report.json`.

Hard-gate `fail` excludes a candidate. `unknown` and `not_run` remain visible
in the report and are never converted to `pass`. A validator exception becomes
an explicit `unknown` result rather than terminating the complete shadow run.

## Report contract

The JSON report is schema `luna-shadow-report/1` and includes:

- input source-manifest hash and read-only verification;
- policy config hash and ranker artifact/model provenance when supplied;
- capability state for every optional component;
- block/phrase/take validation results and source hashes;
- hard-gate survivors, rank score, shadow top-1/top-3;
- actual selected take, agreement, and feature/score reasons on disagreement;
- `production_selection_changed: false`.

The fallback quality score is a documented shadow calculation from persisted
duration, syllable count, end slope, pitch level, and final curl metrics. It
does not import, re-run, or modify the production beam/pin logic.
