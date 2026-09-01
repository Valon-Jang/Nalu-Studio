# LUNA Stage Gate Removal Patch

## Purpose

This patch removes the key, signature, deterministic gate, and forced-approval mechanisms from an existing `LUNA_CODEX_STAGE_PACK` installation. It retains the operational boundary: a completed Stage must stop, report completion, and must not begin its next Stage automatically.

It does **not** alter Luna production narration rules, including the production voice engine, Candidate B reference, synthesis parameters, prosody targets, phrase-splitting rules, or narration pipeline.

## What is removed

- `tools/stage_gate.py` (archived, then removed from the live tree)
- `.github/workflows/luna-stage-gate.yml` (archived, then removed)
- key/signature/approval-lock fields in `.codex/stage_state.json`
- forced gate fields in `.codex/stage_plan.json`
- Stage-Gate/CODEOWNERS and ruleset guidance blocks in `AGENTS.md`
- direct `LUNA_STAGE_GATE_KEY` references in the Stage Pack text/configuration files scanned by the patch

The script also writes `LUNA_STAGE_GATE_KEY=REMOVE` to a local `.env.example` only if such a placeholder already exists. It never reads, prints, or records any secret value.

## What remains

- Stage order, agent/model assignments, prompts, allowed-path scope, tests, reports, and escalation guidance
- The rule that an agent performs its assigned Stage only
- The rule that a Stage completion ends with `STAGE_COMPLETE_AWAITING_USER_APPROVAL`
- The manual operating rule: the next Stage starts only after the user explicitly asks to start it in a new task/thread
- Every Luna production narration rule

`STAGE_COMPLETE_AWAITING_USER_APPROVAL` is now an operational handoff status, not a key-verified or signature-verified lock.

## Apply

1. Extract this ZIP at the root of the existing `LUNA_CODEX_STAGE_PACK` repository.
2. Review `REMOVAL_TARGETS.md`.
3. From that repository root, run:

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\LUNA_STAGE_GATE_REMOVAL_PATCH\Apply-LunaStageGateRemoval.ps1
   ```

4. Inspect `LUNA_STAGE_GATE_REMOVAL_REPORT.md` and the backup folder named in it.
5. In GitHub, manually remove the `luna-stage-gate` required status check from any branch rule/ruleset. GitHub-hosted rules cannot be changed by this local patch.
6. Commit the resulting changes after review.

The script stops before changing files if it cannot find a Stage Pack indicator (`.codex/stage_plan.json`, `.codex/stage_state.json`, `tools/stage_gate.py`, or the gate workflow). Use `-Force` only when you have confirmed the extraction location.

## Verify

- `tools/stage_gate.py` and `.github/workflows/luna-stage-gate.yml` are absent from the live tree.
- `.codex/stage_state.json` has no `approval`, `signature`, `key`, `lock`, or `unlock` fields.
- `.codex/stage_plan.json` has no forced gate/security fields listed in the report.
- `AGENTS.md` contains the manual-stop rule and no Stage-Gate security block.
- A completed Stage still ends without starting the following Stage.

## Restore

Each run makes a timestamped, complete backup under `.luna-stage-gate-backups\<timestamp>`. To restore the exact pre-patch files:

```powershell
powershell -ExecutionPolicy Bypass -File .\LUNA_STAGE_GATE_REMOVAL_PATCH\Restore-LunaStageGateRemoval.ps1 -BackupPath .\.luna-stage-gate-backups\<timestamp>
```

Restoration only returns local files. If you removed the GitHub required status check, re-enable it separately in GitHub rules/rulesets.

## Safety notes

- The patch moves protected files to the backup instead of permanently deleting them.
- It preserves any unrelated `CODEOWNERS` entries; it removes only lines that reference the Luna Stage Gate paths.
- It does not alter protected Luna production narration material.
