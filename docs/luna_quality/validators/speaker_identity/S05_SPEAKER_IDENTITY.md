# S05 Speaker Identity Validator

The primary Chatterbox V3 Voice Encoder adapter creates SHA-256-keyed local
embedding caches and reports cosine similarity.  SpeechBrain is an optional
secondary signal with its model identifier recorded separately.  Neither score
has a default Luna threshold.

Calibration requires Candidate B, approved Luna, and drift-rejected examples.
Missing groups return `insufficient_data`; without a calibrated dataset the
validator returns `unknown` and never enables a hard gate.
