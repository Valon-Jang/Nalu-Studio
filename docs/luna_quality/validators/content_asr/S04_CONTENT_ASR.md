# S04 Content/ASR Validator

`ContentAsrValidator` compares an expected script with ASR text in an
independent shadow path.  It reports edit distance and deletion, insertion,
substitution, critical-term, repetition, and continuation signals separately.
No S04 threshold changes production selection.

`normalize_expected_pronunciation` has deliberately limited support for
Arabic integers, years (1800–2099 followed by `년`), decimals, percent, kg,
km, Hz, ms, and upper-case Latin abbreviations.  Other mixed terms are kept
literal instead of assigning an unverified pronunciation.

`WhisperXAdapter` is optional and lazy: importing the package or checking
capability never loads or downloads a model.  Explicit transcription and
alignment calls can load WhisperX.  Alignment word timestamps are returned
separately from content comparison, and unavailable or failed ASR/alignment is
`not_run` or `unknown`, never `pass`.

The opt-in integration smoke test is
`tests/luna_quality/integration/test_whisperx_integration.py`.  It runs only
when `LUNA_RUN_WHISPERX_INTEGRATION=1` and requires the caller to supply a
permitted non-private WAV path in `LUNA_WHISPERX_INTEGRATION_WAV`.
