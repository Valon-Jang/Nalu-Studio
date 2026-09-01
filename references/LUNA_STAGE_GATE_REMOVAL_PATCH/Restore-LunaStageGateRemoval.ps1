[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)]
  [string]$BackupPath
)

$ErrorActionPreference = 'Stop'
$root = (Get-Location).Path
$backup = (Resolve-Path -LiteralPath $BackupPath).Path
if (-not (Test-Path -LiteralPath (Join-Path $backup 'AGENTS.md')) -and -not (Test-Path -LiteralPath (Join-Path $backup '.codex'))) {
  throw 'The selected folder does not look like a Luna Stage Gate backup.'
}

Get-ChildItem -LiteralPath $backup -Recurse -File | ForEach-Object {
  $relative = $_.FullName.Substring($backup.Length).TrimStart('\\')
  $destination = Join-Path $root $relative
  New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
  Copy-Item -LiteralPath $_.FullName -Destination $destination -Force
}
Write-Host "Files restored from $backup. Re-enable any GitHub ruleset manually if needed."
