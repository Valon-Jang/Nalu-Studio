# Luna FAST Speaker v1 — S04 Batch and Persistence

S04 adds newline-first batch parsing, explicit sentence states, and atomic
JSON session snapshots. Newlines are processed before punctuation within a
line; original non-empty order is retained.

States are `PENDING`, `PLAYING`, `PASS`, `ISSUE`, `PAUSED`, and
`RETEST_PENDING`. A clean completed sentence becomes PASS only when the batch
is not paused. Snapshots use write-then-atomic-replace. On recovery, a saved
`PLAYING` item becomes `PENDING`, active index is cleared, and the app never
starts speech automatically; the next user action resumes that entire sentence.

The Tk UI offers Manual/Batch mode, `.txt`/`.md` import, editable timestamp
session name, progress state, and automatic next-sentence submission after a
clean controller completion. Session persistence stores text/state only, not
audio; normal audio remains in-memory PCM.
