# Luna FAST Speaker v1 — S05 Issues and Retest

Only a user-triggered Mark Issue exports a selected completed RAM phrase as
issue evidence WAV. Normal playback remains memory-only. Each revision stores
`issue.json`, `issue.md`, `codex_request.md`, and the issue-only WAV under one
issue ID. Pronunciation issues require problem word, heard-as, and desired
pronunciation. Retest creates the next revision and records only an explicit
IMPROVED/SAME/WORSE/RESOLVED outcome; resolution is never inferred.

The generated Codex request preserves V3/Candidate B/fixed-parameter and
production invariants. It requires numeric comparison for intonation and asks
whether a pronunciation defect is repeatable before a global respell change.
