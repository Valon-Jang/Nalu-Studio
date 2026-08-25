# Luna FAST Speaker v1 — S03 Manual UI and Audio

## Scope

S03 provides the manual Tkinter speaker only. Batch parsing/persistence,
issue/retest, rule reload, and production changes are excluded.

## Runtime design

`scripts/luna_fast_speaker.py` opens a Tkinter window and starts the S02
canonical-Python worker on a background thread. The Tk event thread never loads
the model or waits for synthesis. The window provides multiline input,
`Ctrl+Enter`/Speak, Stop, Pause, Continue, and cached phrase/sentence replay.

`FastSpeakerController` submits current Luna phrases one at a time. Once a
phrase begins audio output, it requests the next phrase on its background
worker executor. Later manual submissions remain queued behind the active run.

## Windows audio path

`WinmmAudioSink` opens one persistent Windows-default `waveOut` stream and
writes mono PCM16LE from memory. It does not create, reopen, or play a WAV.
The controller records warm TTFA only when a frame containing a non-silent PCM
sample is handed to that active stream. It records the S02 phrase metrics and
a rolling RTF separately; no UI metric claims audio-device latency beyond that
defined handoff point.

## Stop, pause, and replay

- **Stop** clears pending manual runs, stops the active `waveOut` buffer,
  creates a new generation ID, and sends `invalidate`. A non-preemptible model
  request may finish, but its prior generation is locally marked stale and is
  never handed to the sink.
- **Pause** allows the active frame to finish, then holds the next frame.
  **Continue** resumes the queued PCM without re-synthesis.
- **Replay Last Phrase** and **Replay Current Sentence** consume only RAM PCM
  cache; they never issue another worker synthesize command.

## Verification boundary

The S03 tests use a fake worker and fake RAM audio sink to prove phrase-first
prefetch, pause-after-current-frame, cached replay, and late-result Stop
invalidation. A Windows `waveOut` smoke check successfully opened the default
device, wrote memory PCM, received completion, and closed the persistent
stream. The Tk window is intentionally not auto-launched in unattended tests.
