# Luna narration skill change proposal

Status: proposal only — not applied
Target if separately approved: `.agents/skills/luna-narration/SKILL.md`

## Reason

The current skill correctly fixes the Luna voice, entry point and production
prosody rules, but it predates the default-off quality integration. Operators
could discover the new environment variables without seeing the S11
shadow-only release boundary or the cold-start tokenizer download risk.

## Proposed addition

Add a short section after “유일한 진입점” with the following meaning:

1. All quality flags default to `off`; ordinary narration keeps them off.
2. Current release status is `SHADOW_ONLY_APPROVED`.
3. `LUNA_QUALITY_MODE=shadow` may write a separate read-only report outside
   production `OUTDIR`; it never changes selected takes.
4. Production `select` is forbidden until an exact USER approval manifest,
   real ranker artifact, real speaker calibration and integration evidence are
   supplied.
5. `unknown`/`not_run` never means pass and no external score can compensate a
   hard gate.
6. Candidate B conditionals cache is optional and may be used only after exact
   source/checkpoint/reference hash validation.
7. A cold Windows machine may let `spacy-pkuseg` download tokenizer data to
   `%USERPROFILE%\.pkuseg`; provision and audit this cache deliberately when a
   network-free run is required.
8. Immediate rollback is setting all seven feature flags to `off` and
   restarting the process. Production audio/checkpoints must not be deleted.
9. Link operators to `docs/luna_quality/release/ROLLBACK.md` and
   `RELEASE_CHECKLIST.md`.

## Proposed flag block

```text
LUNA_QUALITY_MODE=off|shadow|select
LUNA_CONDITIONALS_CACHE=off|on
LUNA_ASR_VALIDATOR=off|on
LUNA_SPEAKER_VALIDATOR=off|on
LUNA_MOS_VALIDATOR=off|on
LUNA_PREFERENCE_RANKER=off|shadow|select
LUNA_HYBRID_SYNTHESIS=off|experiment
```

The skill should state that these are operational controls, not permission to
enable unapproved modes.

## Non-changes

- Do not alter Chatterbox Multilingual V3, Candidate B, hashes or parameters.
- Do not weaken any split, rate, pitch, tail, curl, pause or pin rule.
- Do not add another TTS/VC engine.
- Do not represent WhisperX, SpeechBrain or MOS as Luna naturalness judges.
- Do not apply this proposal automatically as part of S11.

## Approval requested later

A separate user decision should review this wording after the release audit is
closed. If approved, update the skill and its protected hash in a separately
authorised maintenance workflow, never by editing the stage guard.
