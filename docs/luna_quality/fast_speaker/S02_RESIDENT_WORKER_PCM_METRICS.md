# Luna FAST Speaker v1 — S02 Resident Worker, PCM, and Metrics

## Scope

S02 adds a local, restartable Windows named-pipe worker around the S01 FAST
adapter. It has no Tkinter UI, audio-device output, playback queue, batch
state, persistence, or issue workflow.

## Local worker protocol

The worker listens only through `multiprocessing.connection` with Windows
`AF_PIPE`. Each connection carries one authenticated mapping under schema
`luna-fast-speaker-ipc/1`; it is not a TCP or external network API.

Commands are:

- `health` — return READY state and one-time backend initialization details.
- `synthesize` — accept request/session/generation IDs, a `FastPhrase`, and a
  seed; return PCM, phrase metadata, and worker metrics.
- `invalidate` — move a session to a new generation ID.
- `shutdown` — close the listener and exit the worker process.

The `WorkerProcess` launcher always defaults to
`engine/chatterbox-v3/venv/Scripts/python.exe`. The model/Candidate B is
initialized once per worker process and phrase calls are serialized.

## PCM and metrics contracts

`PcmFrame` schema `luna-fast-speaker-pcm/1` contains only mono signed-16-bit
little-endian PCM bytes, sample rate, channels, and sample count. Ordinary
worker synthesis has no `output_wav` field and does not create a WAV.

`PhraseMetrics` schema `luna-fast-speaker-metrics/1` records worker READY
time, synthesis start/end, PCM-ready time, audio duration, model generation
time, and RTF. `playback_ttfa` is explicitly `not_run`: S03 owns audio callback
timing and must not treat S02 PCM readiness as audible playback.

## Stop / stale-result semantics

Chatterbox generation remains non-preemptible. A concurrent `invalidate`
command updates the session generation ID while an earlier serialized model
call may still finish. When that call returns, the worker marks its result
`stale: true`; a future controller must discard it rather than play it.

This is invalidation, not a claim that in-flight model computation was safely
cancelled.

## Verification

The fake-backend tests cover pipe IPC, resident reuse, exact in-memory PCM,
restart into a fresh process, and invalidation while a call is in flight. The
opt-in real test starts the canonical V3/Candidate B worker, synthesizes one
phrase in memory, verifies PCM/RTF fields and absent WAV output, then performs
clean shutdown.
