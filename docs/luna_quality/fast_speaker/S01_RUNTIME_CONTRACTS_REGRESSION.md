# Luna FAST Speaker v1 — S01 Runtime Contracts and Regression

## Scope

S01 establishes a narrow, in-process seam around the current FAST synthesis
primitive. It does not create IPC, a worker process, PCM playback, a UI, or
new Luna pronunciation/prosody rules.

## Contract

`scripts.luna_quality.fast_speaker.contracts.FastBackend` exposes four
operations:

1. `initialize_once()` loads or reports the resident runtime.
2. `split_fast_text()` uses the existing production `respell()` and
   `build_phrase_list()` helpers; it does not copy or alter their rules.
3. `synthesize_fast_phrase()` makes exactly one current-FAST take for one
   phrase and returns the peak-limited waveform, respelled text, seed,
   model-only generation time, metadata, and in-memory mono PCM16LE.
4. `postprocess_to_pcm_s16le()` converts the already peak-limited result to
   an explicit little-endian PCM contract.

`FakeFastBackend` provides known PCM bytes and deterministic request recording
for controller and transport tests in later stages without loading a model.

## Compatibility boundary

`LunaVoiceRuntime._run_fast()` remains unchanged and writes the same PCM16 WAV
through the existing `torchaudio` writer. `LunaFastBackend` reuses the runtime's
resident model, serialization lock, seed setter, and fixed synthesis constants
to expose the same one-take sequence as an in-memory adapter:

```text
seed -> respell -> one fixed-parameter V3 generate(audio_prompt_path=None)
     -> current 0.89 peak guard -> WAV writer (existing FAST CLI only)
```

Candidate B, its hash and conditionals cache, V3 model selection, all fixed
FAST parameters, the production narration pipeline, existing FAST CLI,
transport, and output names are unchanged.

## Regression evidence and bitwise policy

The deterministic fixture freezes seven current Luna split/normalization cases
and the fixed FAST generation configuration. Unit tests also verify the real
adapter's exact generate keyword arguments with a model double.

On this Windows environment, two real V3 calls for the same phrase and seed
produced byte-identical in-memory PCM16LE. The existing `torchaudio` PCM16 WAV
writer uses a quantization detail that is not byte-identical to the direct
in-memory conversion: one real measured output had equal sample counts
(`51,840`) and a maximum absolute difference of one PCM least-significant bit
across `24,878` samples. This is an encoder representation difference, not a
generation difference.

Accordingly, S01 does **not** claim bitwise identity between its in-memory PCM
and the legacy WAV bytes. The opt-in real regression requires both:

- byte-identical in-memory PCM across same-seed generations; and
- equal WAV/PCM sample count with a maximum writer difference of at most one
  LSB.

The current FAST CLI continues to use `torchaudio` for its compatibility WAV;
the future in-memory worker transport is deliberately deferred to S02.

## Commands

```powershell
& .\engine\chatterbox-v3\venv\Scripts\python.exe -X utf8 -m unittest discover -s tests\luna_quality\unit -p 'test_*.py' -v
& .\engine\chatterbox-v3\venv\Scripts\python.exe -X utf8 -m unittest discover -s tests\luna_quality\regression -p 'test_*.py' -v
$env:RUN_LUNA_FAST_SPEAKER_REAL='1'
& .\engine\chatterbox-v3\venv\Scripts\python.exe -X utf8 -m unittest tests.luna_quality.regression.test_fast_speaker_baseline.FastSpeakerBaselineRegressionTest.test_real_fast_pcm_is_repeatable_and_within_one_lsb_of_current_wav_writer -v
```
