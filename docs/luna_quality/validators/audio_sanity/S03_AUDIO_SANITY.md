# S03 Audio Sanity Validator

`AudioSanityValidator` is a production-off hard gate for existing WAV files.
It uses only the Python standard library and returns `ValidationResult` with a
SHA-256 source hash, explicit pass/fail status, reasons, metrics, and a
version derived from the complete threshold configuration.

The baseline output contract is mono PCM16 at 24,000 Hz, RMS -20 dBFS and a
0.89 peak guard.  The validator treats an unexpected sample rate, unreadable
or empty WAV, zero waveform, clipping, excessive DC offset, abnormal silence,
peak-guard breach, and abrupt ending as hard-gate failures.  It never edits
audio and is not connected to production selection.

Thresholds live in `AudioSanityConfig`; its canonical JSON SHA-256 is recorded
in every result and changes the validator version when a threshold changes.
