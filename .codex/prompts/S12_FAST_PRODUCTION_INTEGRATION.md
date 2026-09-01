# S12 — FAST Production Integration

## User-approved objective

Expose one local Luna Voice interface whose user input is dialogue text and whose output is a Luna WAV plus a JSON result. Keep Chatterbox Multilingual V3 resident when possible and prepare the fixed Candidate B condition once for reuse.

## Required behavior

- `FAST` is the default mode and generates exactly one take.
- Repeated FAST requests in one resident process do not reload the model or re-analyze Candidate B.
- `PRODUCTION` reuses the resident model and invokes the existing best-of-N pipeline and Quality System integration.
- Until the user listens and approves, PRODUCTION quality selection remains shadow/fallback-safe; it must not silently enable a new production selector.
- Both modes use the same versioned JSON request/response contract and return a WAV path.
- The service is local-only and never uploads private audio.
- The canonical production Python is `engine/chatterbox-v3/venv/Scripts/python.exe`.

## Voice invariants

- Engine: Chatterbox Multilingual V3 only.
- Reference: `assets/voice_ref/B_voiced_spectral_micro_smooth.wav` with SHA-256 `30c6d3405f46684af467c7d26ff40a2fb57dd48cc84cd24cf7403d9aa00a2bb9`.
- Language `ko`; exaggeration `0.5`; cfg weight `0.5`; temperature `0.72`; repetition penalty `1.2`; min-p `0.05`; top-p `1.0`.
- Existing phrase splitting, best-of-N, pins, gates, approved output audio, and production entry point behavior remain unchanged.
- Do not modify the production virtual environment or the pinned Torch stack.

## Verification

- Deterministic unit tests with a fake model prove single load/single condition preparation and repeated one-take FAST generation.
- Contract, transport, FAST/PRODUCTION dispatch, default-mode, and safe quality-mode tests pass.
- An opt-in real Korean FAST integration test loads the actual model, loads or creates the Candidate B conditionals cache, produces a non-empty PCM WAV, and proves a second request reuses the resident state.
- Existing Luna quality unit/regression tests pass.
- Production Torch, torchaudio, and NumPy remain `2.6.0+cpu`, `2.6.0+cpu`, and `1.26.4`.

## Stop condition

Write `.codex/reports/S12_REPORT.md`, mark S12 complete, and stop with `STAGE_COMPLETE_AWAITING_USER_APPROVAL`. Do not begin another stage.
