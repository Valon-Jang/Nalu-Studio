[CmdletBinding()]
param(
  [switch]$Force
)

$ErrorActionPreference = 'Stop'
$root = (Get-Location).Path
$indicators = @('.codex/stage_plan.json', '.codex/stage_state.json', 'tools/stage_gate.py', '.github/workflows/luna-stage-gate.yml') |
  ForEach-Object { Join-Path $root $_ } |
  Where-Object { Test-Path -LiteralPath $_ }
if (-not $indicators -and -not $Force) {
  throw 'No Luna Stage Pack indicator found. Run from the Stage Pack root, or use -Force after verifying the location.'
}

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backup = Join-Path $root ".luna-stage-gate-backups\\$stamp"
New-Item -ItemType Directory -Path $backup -Force | Out-Null
$report = [System.Collections.Generic.List[string]]::new()
$report.Add('# Luna Stage Gate removal report')
$report.Add('')
$report.Add("Backup: ``$backup``")
$report.Add('')

function Backup-ThenRemove([string]$relative) {
  $source = Join-Path $root $relative
  if (Test-Path -LiteralPath $source) {
    $destination = Join-Path $backup $relative
    New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
    Copy-Item -LiteralPath $source -Destination $destination -Force
    Remove-Item -LiteralPath $source -Force
    $report.Add("- Removed live ``$relative``; backup created.")
  }
}

function Backup-ThenWrite([string]$relative, [string]$content) {
  $path = Join-Path $root $relative
  if (Test-Path -LiteralPath $path) {
    $destination = Join-Path $backup $relative
    New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
    Copy-Item -LiteralPath $path -Destination $destination -Force
  }
  New-Item -ItemType Directory -Path (Split-Path -Parent $path) -Force | Out-Null
  [System.IO.File]::WriteAllText($path, $content, [System.Text.UTF8Encoding]::new($false))
  $report.Add("- Updated ``$relative``; original backed up when present.")
}

function Remove-GateProperties($value) {
  if ($null -eq $value) { return }
  if ($value -is [System.Collections.IEnumerable] -and -not ($value -is [string]) -and -not ($value -is [pscustomobject])) {
    foreach ($item in $value) { Remove-GateProperties $item }
    return
  }
  if ($value -is [pscustomobject]) {
    foreach ($property in @($value.PSObject.Properties)) {
      if ($property.Name -match '(^|_)(approval|required_approval|user_approval|signature|signing|key|gate|stage_gate|locked|lock|unlocked|unlock|required_status_check)(_|$)') {
        $value.PSObject.Properties.Remove($property.Name)
      } else {
        Remove-GateProperties $property.Value
      }
    }
  }
}

Backup-ThenRemove 'tools/stage_gate.py'
Backup-ThenRemove '.github/workflows/luna-stage-gate.yml'

$statePath = Join-Path $root '.codex/stage_state.json'
if (Test-Path -LiteralPath $statePath) {
  $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
  Remove-GateProperties $state
  Backup-ThenWrite '.codex/stage_state.json' (($state | ConvertTo-Json -Depth 100) + [Environment]::NewLine)
}

$planPath = Join-Path $root '.codex/stage_plan.json'
if (Test-Path -LiteralPath $planPath) {
  $plan = Get-Content -LiteralPath $planPath -Raw | ConvertFrom-Json
  Remove-GateProperties $plan
  Backup-ThenWrite '.codex/stage_plan.json' (($plan | ConvertTo-Json -Depth 100) + [Environment]::NewLine)
}

$agentsPath = Join-Path $root 'AGENTS.md'
if (Test-Path -LiteralPath $agentsPath) {
  $agents = [System.IO.File]::ReadAllText($agentsPath, [System.Text.UTF8Encoding]::new($false))
  # Keep this pattern ASCII-only: Windows PowerShell can otherwise misdecode
  # Korean literals in a script that was extracted without a BOM.
  $agents = [regex]::Replace($agents, '(?im)^.*(stage_gate|LUNA_STAGE_GATE_KEY|signature|required status check).*(?:\r?\n|$)', '')
  $manualRule = @"

## Luna Stage progression (manual stop)

- An agent performs only its assigned Stage, runs the required checks, writes its report, and then stops.
- Completion status is `STAGE_COMPLETE_AWAITING_USER_APPROVAL`; this is a handoff status only and has no key, signature, or automatic unlock mechanism.
- Never start the next Stage automatically. Start it only when the user explicitly requests the next Stage in a new task/thread.
- This rule does not authorize changes to Luna production narration rules.
"@
  if ($agents -notmatch 'Luna Stage progression \(manual stop\)') { $agents = $agents.TrimEnd() + "`n" + $manualRule }
  Backup-ThenWrite 'AGENTS.md' $agents
}

$ownersPath = Join-Path $root '.github/CODEOWNERS'
if (Test-Path -LiteralPath $ownersPath) {
  $owners = Get-Content -LiteralPath $ownersPath
  $kept = $owners | Where-Object { $_ -notmatch '(stage_gate\.py|luna-stage-gate\.yml|stage_plan\.json.*stage.?gate|stage_state\.json.*stage.?gate)' }
  Backup-ThenWrite '.github/CODEOWNERS' (($kept -join [Environment]::NewLine) + [Environment]::NewLine)
}

$envExample = Join-Path $root '.env.example'
if (Test-Path -LiteralPath $envExample) {
  $envText = Get-Content -LiteralPath $envExample -Raw
  if ($envText -match '(?m)^LUNA_STAGE_GATE_KEY=') {
    $envText = [regex]::Replace($envText, '(?m)^LUNA_STAGE_GATE_KEY=.*$', 'LUNA_STAGE_GATE_KEY=REMOVE')
    Backup-ThenWrite '.env.example' $envText
  }
}

$report.Add('')
$report.Add('## Remaining manual action')
$report.Add('Remove `luna-stage-gate` from GitHub required status checks / rulesets. This local patch cannot change hosted GitHub settings.')
[System.IO.File]::WriteAllLines((Join-Path $root 'LUNA_STAGE_GATE_REMOVAL_REPORT.md'), $report, [System.Text.UTF8Encoding]::new($false))
Write-Host "Patch applied. Review LUNA_STAGE_GATE_REMOVAL_REPORT.md. Backup: $backup"
