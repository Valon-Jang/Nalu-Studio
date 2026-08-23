# S11 release audit

Audit date: 2026-08-23
Stage start: `2c434854799ccbca3844fcf5c917e7fab15703a3`
Decision: `SHADOW_ONLY_APPROVED`

## Decision boundary

The existing Luna production path and the default-off quality integration are
acceptable for local use. Read-only `shadow` evaluation is also acceptable
when unavailable validators remain visibly `unknown` or `not_run`.

Production `select` is not approved. Public redistribution of a packaged
runtime is not approved by this audit. Those decisions require real Luna
preference data, an approved ranker, calibrated speaker thresholds, pinned and
tested optional model revisions, a complete third-party notice bundle, and
documented authority to redistribute Candidate B.

## Evidence summary

| Area | Result | Evidence |
| --- | --- | --- |
| Production entry point | Pass | `scripts/luna_narration_pipeline_v1.py`; S00 manifest; release regression tests |
| Candidate B and V3 checkpoints | Pass | S00 hashes rechecked byte-for-byte by `tests/luna_quality/regression/test_release_baseline.py` |
| Frozen output audio/timing | Pass | All 17 final WAV and two timing hashes match `BASELINE_MANIFEST.json` |
| Feature defaults | Pass | Seven production integration flags are all `off`; default execution does not request integration |
| Checkpoint/resume | Pass | Completed block report remains byte-identical; no block audio is generated; pipeline report contract remains intact |
| Shadow immutability | Pass | S08/S10 tests compare input tree hashes and production files before/after |
| Conditionals cache | Pass with operational risk | Exact manifest create/hit/corruption tests pass; actual V3 Candidate B save/load passed |
| Windows CPU model load | Pass with operational risk | Pinned V3 loaded on CPU at 24 kHz without audio generation; `spacy-pkuseg` performed an undeclared network download |
| Performance/load count | Bounded evidence only | CPU model load took 68.130 s and actual conditionals round-trip took 52.053 s on this workstation; hybrid actual-run test requires one generator instance |
| Content/ASR | Not release-qualified | Deterministic validator tests pass; WhisperX and Korean alignment integration was not run |
| Speaker identity | Not release-qualified | Contract tests pass; no real calibration dataset; SpeechBrain is absent and its adapter revision is unresolved |
| MOS | Not implemented | Flag reports unavailable/`not_run`; MOS cannot enter select |
| Prosody Bank | Pass for local shadow data | Schema v1 migration, provenance, revision and idempotency tests pass; no real bank is shipped |
| Preference ranker | Contract only | Grouped synthetic tests pass; actual evidence is `insufficient_data`; no real artifact exists |
| Hybrid synthesis | Isolated experiment only | Dry-run and synthetic evaluator pass; no real generated comparison or listening evidence |
| Private data | Pass for tracked changes | No WAV, checkpoint, embedding, SQLite DB, or private voice copy is tracked by S01-S11 changes |
| Dependency reproducibility | Risk | No root lock/requirements file; optional packages and model revisions are not pinned |
| Distribution licensing | Documented risk | Core licenses identified, but no assembled NOTICE/license bundle or Candidate B redistribution grant exists |

## Code and architecture audit

- `scripts/luna_narration_pipeline_v1.py` remains the single entry point and
  still loads `ChatterboxMultilingualTTS.from_pretrained(device="cpu",
  t3_model="v3")`.
- Candidate B path, fixed generation parameters, escalation temperatures,
  prosody gates, pauses, output names and pin precedence remain unchanged.
- S01-S09 code stays under `scripts/luna_quality/`; S10 adds one default-off
  integration session and a final production-side safety guard.
- Optional external packages are lazily detected/imported. Ordinary unit tests
  do not download or load their models.
- Invalid flags, missing artifacts, validator exceptions, unknown/not-run
  validators, insufficient survivors, and output-report failures retain the
  existing selector. No exception becomes a silent pass.
- A select proposal requires exact ranker/calibration/config hashes, a USER
  approval manifest, approved validator scope, hard-gate pass, coverage,
  confidence, at least two eligible survivors, pin preservation, block median
  and reset continuity.
- Rollback is immediate by setting all flags to `off`; code rollback is
  documented separately.

## Supported installation and operation

This audit approves only the existing local Windows checkout and its canonical
runtime:

```powershell
Test-Path -LiteralPath '.\engine\chatterbox-v3\venv\Scripts\python.exe'
Test-Path -LiteralPath '.\engine\chatterbox-v3\hf-cache'
& .\engine\chatterbox-v3\venv\Scripts\python.exe -X utf8 -m pip check
```

Do not reconstruct a release environment from unconstrained `pip install`
commands: the repository has no root lock file. Keep WhisperX, SpeechBrain and
SpeechMOS disabled unless a separately reviewed install manifest pins their
package and model revisions. The only supported narration invocation remains:

```powershell
& .\engine\chatterbox-v3\venv\Scripts\python.exe -X utf8 .\scripts\luna_narration_pipeline_v1.py JOBS.json OUTDIR
```

## Data and privacy audit

- Candidate B is ignored by Git and referenced by path/hash. New cache
  manifests contain hashes and filenames, not audio samples.
- Embedding caches are private local artifacts outside production `OUTDIR` and
  are not committed.
- Prosody Bank stores source paths, hashes, scalar features and selection
  provenance. It does not store audio binary.
- Schema migration is explicit and versioned. Automatic destructive schema
  repair is absent.
- Ranker artifacts record feature schema, dataset/source hashes,
  standardisation, coefficients, seed and grouped evaluation. No real ranker
  artifact was created because eligible human data is absent.
- No Candidate B consent or redistribution document exists in this repository.
  Candidate B must therefore remain private and must not be included in a
  public bundle without separate authority.

## Evaluation audit

| Command class | Observed result |
| --- | --- |
| Unit discovery | 96 passed |
| Release baseline regression | 6 passed |
| Default integration discovery | 3 explicitly skipped by opt-in guards |
| V3 Windows CPU/Hugging Face-offline model load | 1 passed; no audio generated |
| Actual Candidate B conditionals save/load | 1 passed; temporary conditionals artifact removed by test |
| WhisperX Korean transcription/alignment | Not run: package, pinned weights and approved non-private fixture absent |

The two wall-clock observations above are smoke-test measurements, not a
performance benchmark or release SLA. The deterministic
`test_actual_runner_loads_one_generator_and_writes_mode_validator_bundles`
test verifies that an actual hybrid multi-mode run constructs one generator
instance. No real hybrid audio run was performed in S11.

The model-load smoke exposed that `spacy-pkuseg` ignores the Hugging Face
offline variables and downloaded `spacy_ontonotes` to
`C:\Users\tequi\.pkuseg`. This is public tokenizer data, not Luna audio, but it
means a cold machine is not truly offline/reproducible. Shadow approval assumes
that this dependency cache is provisioned deliberately or network access is
controlled externally.

No new narration audio, hybrid candidate, pin, approved ranker, speaker
calibration, or human preference record was produced during S11.

## License audit

This is an engineering inventory, not legal advice. Licenses were checked
against local package metadata and the upstream source/model pages below.

| Component | Current use/status | Declared license | Release requirement/risk |
| --- | --- | --- | --- |
| Chatterbox source `5de7a54...` | Production, locally pinned | MIT | Preserve MIT text/copyright in redistribution. Local source is clean. |
| `ResembleAI/chatterbox` weights snapshot `5bb1f6e...` | Production, hashes pinned | MIT model card | Preserve model license/card; do not confuse with `chatterbox-hf`, a different repository. |
| WhisperX | Optional, not installed | BSD-2-Clause | Pin package revision before enabling; preserve BSD notice. |
| Whisper large-v3 | Optional ASR, not cached/tested | Apache-2.0 | Pin exact model revision and include Apache license/NOTICE obligations. |
| `kresnik/wav2vec2-large-xlsr-korean` | WhisperX default Korean alignment, not cached/tested | Apache-2.0 | Pin exact revision; current adapter relies on WhisperX's moving default map. |
| SpeechBrain | Optional, not installed | Apache-2.0 | Preserve license/NOTICE; pin package before enablement. |
| `speechbrain/spkrec-ecapa-voxceleb` | Named but not downloaded/tested | Apache-2.0 | Adapter currently records revision `unresolved`; must pin and audit model card before enablement. |
| SpeechMOS | No adapter; flag is unavailable | MIT | Not part of the release runtime. Do not add through unpinned `torch.hub`. |
| UTMOS22 | Not installed/used | MIT | Model/data provenance must be separately recorded if later enabled. |
| scikit-learn 1.9.0 | Installed transitively through librosa; Luna ranker does not import it | BSD-3-Clause | Preserve BSD notice if redistributed in the environment. |

Primary sources:

- Chatterbox code: https://github.com/resemble-ai/chatterbox/blob/master/LICENSE
- Chatterbox model, pinned snapshot:
  https://huggingface.co/ResembleAI/chatterbox/tree/5bb1f6ee58e50c3b8d408bc82a6d3740c2db6e18
- WhisperX code and Korean model map:
  https://github.com/m-bain/whisperX/blob/main/LICENSE and
  https://github.com/m-bain/whisperX/blob/main/whisperx/alignment.py
- Whisper large-v3: https://huggingface.co/openai/whisper-large-v3
- Korean alignment model:
  https://huggingface.co/kresnik/wav2vec2-large-xlsr-korean
- SpeechBrain code/model: https://github.com/speechbrain/speechbrain/blob/develop/LICENSE
  and https://huggingface.co/speechbrain/spkrec-ecapa-voxceleb
- SpeechMOS/UTMOS22: https://github.com/tarepan/SpeechMOS/blob/main/LICENSE
  and https://github.com/sarulab-speech/UTMOS22/blob/master/LICENSE
- scikit-learn:
  https://github.com/scikit-learn/scikit-learn/blob/main/COPYING

## Blocking conditions for production select

1. Collect at least the S07 minimum real pin history with explicit hard-gate
   evidence, then train and evaluate a real grouped ranker.
2. Calibrate Chatterbox VE speaker threshold on approved Luna, rejected Luna
   and Candidate B data; approve the exact artifact hash.
3. Pin and license-audit WhisperX, Whisper large-v3, Korean alignment and any
   SpeechBrain revision; run approved non-private integration fixtures.
4. Resolve the cold-start `spacy-pkuseg` download and create a reproducible
   environment lock plus third-party notice bundle.
5. Conduct real hybrid audio evaluation and blind listening before any hybrid
   promotion.
6. Create an explicit USER select approval manifest only after the above
   evidence is reviewed.

Until all six are satisfied, keep `LUNA_QUALITY_MODE` at `off` or `shadow` and
keep `LUNA_PREFERENCE_RANKER` away from `select`.

## Final decision

`SHADOW_ONLY_APPROVED`

The decision approves the current existing selector and read-only diagnostics,
not automated take selection, optional model downloads, hybrid production, or
public distribution of private/model artifacts.
