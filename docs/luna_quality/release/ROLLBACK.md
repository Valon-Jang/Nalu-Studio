# Luna quality rollback and recovery

## Immediate rollback: flags only

This is the first response to any quality-integration problem. It preserves all
production outputs and checkpoints.

```powershell
$env:LUNA_QUALITY_MODE = 'off'
$env:LUNA_CONDITIONALS_CACHE = 'off'
$env:LUNA_ASR_VALIDATOR = 'off'
$env:LUNA_SPEAKER_VALIDATOR = 'off'
$env:LUNA_MOS_VALIDATOR = 'off'
$env:LUNA_PREFERENCE_RANKER = 'off'
$env:LUNA_HYBRID_SYNTHESIS = 'off'
```

Restart the narration process after changing flags. A process that already
loaded optional models or conditionals must not be assumed to have unloaded
them merely because its environment changed.

Do not delete production `P##_t*.wav/json`, `*_pins.json`, block reports,
`*_luna.wav`, or `pipeline_report.json` as part of this rollback.

## Quarantine optional artifacts

Stop all Luna processes first. Move suspect artifacts instead of deleting them
so the operation is recoverable.

```powershell
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$quarantine = Join-Path (Resolve-Path '.').Path ".luna_quality_quarantine\$stamp"
New-Item -ItemType Directory -Path $quarantine -Force | Out-Null

if (Test-Path -LiteralPath '.\.luna_quality_cache\conditionals') {
    Move-Item -LiteralPath '.\.luna_quality_cache\conditionals' -Destination $quarantine
}
```

Quality reports normally live beside `OUTDIR` as
`<OUTDIR>.luna_quality_reports`. Preserve them for diagnosis; they are not read
by the default-off production path.

Restore a quarantined artifact only after checking its manifest, source hashes
and the current Candidate B hash. Otherwise leave the feature off and allow an
explicit future cache build.

## Prosody Bank backup

Close every process holding the SQLite database before copying it.

```powershell
$bank = Resolve-Path '.\path\to\prosody_bank.sqlite'
$backup = "$($bank.Path).backup-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
Copy-Item -LiteralPath $bank.Path -Destination $backup
```

The backup is complete only when its SHA-256 is recorded:

```powershell
Get-FileHash -Algorithm SHA256 -LiteralPath $backup
```

## Prosody Bank restore

Restoration replaces the active database, so it is destructive unless the
current file is quarantined first.

```powershell
$bank = Resolve-Path '.\path\to\prosody_bank.sqlite'
$backup = Resolve-Path '.\path\to\prosody_bank.sqlite.backup-YYYYMMDD-HHMMSS'
$quarantined = "$($bank.Path).before-restore-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
Move-Item -LiteralPath $bank.Path -Destination $quarantined
Copy-Item -LiteralPath $backup.Path -Destination $bank.Path
```

Open the restored bank through `ProsodyBankStore`, run `migration_plan()` and
require an empty plan for the current schema. Never hand-edit
`schema_migrations` or auto-upgrade a backup without review.

## Ranker rollback and retrain

Set `LUNA_PREFERENCE_RANKER=off`, retain the suspect artifact/evaluation, and
record both SHA-256 values. Retrain only from a reviewed JSON export:

```powershell
& .\engine\chatterbox-v3\venv\Scripts\python.exe -X utf8 -m scripts.luna_quality.ranking.train `
  --input .\reviewed\candidates.json `
  --artifact .\reviewed\ranker.json `
  --evaluation .\reviewed\evaluation.json `
  --seed 407
```

`insufficient_data` is a valid stopped outcome, not a model. A new artifact
invalidates every old select approval because its artifact/config hash changes.

## Code rollback

Feature flags are the preferred rollback. If code rollback is still required,
create a new revert commit after preserving reports and confirming the exact
S10 integration commit:

```powershell
git show --stat 2c434854799ccbca3844fcf5c917e7fab15703a3
git revert 2c434854799ccbca3844fcf5c917e7fab15703a3
```

Do not use `git reset --hard` or delete ignored project/runtime trees.

## Audit-created `spacy-pkuseg` cache

The S11 Windows smoke test caused Chatterbox to download public tokenizer data
to `C:\Users\tequi\.pkuseg`. It is outside the repository and contains no Luna
audio. It can be retained to avoid another cold-start download.

If removal is desired, first verify that exact resolved path and stop all Luna
processes. The following deletion is non-recoverable but the public files can
be downloaded again:

```powershell
$target = [System.IO.Path]::GetFullPath('C:\Users\tequi\.pkuseg')
if ($target -ne 'C:\Users\tequi\.pkuseg') { throw 'Unexpected target' }
Remove-Item -LiteralPath $target -Recurse -Force
```
