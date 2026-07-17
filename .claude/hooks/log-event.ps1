# worklog ロガー: フック(settings.json)から呼ばれ、reports/worklog.jsonl に1行追記する。
# 使い方: pwsh -NoProfile -File .claude/hooks/log-event.ps1 <event名>
# stdin に Claude Code フックの JSON ペイロードが渡される前提。取れないフィールドは空で記録する。
param([string]$Event = "event")
$ErrorActionPreference = "SilentlyContinue"

$raw = [Console]::In.ReadToEnd()
$payload = $null
if ($raw) { try { $payload = $raw | ConvertFrom-Json } catch {} }

$root = $env:CLAUDE_PROJECT_DIR
if (-not $root) { $root = (Get-Location).Path }
$logDir = Join-Path $root "reports"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Force $logDir | Out-Null }
$log = Join-Path $logDir "worklog.jsonl"

$agent = ""
$model = ""
$session = ""
if ($payload) {
  $session = $payload.session_id
  if ($payload.tool_input) {
    $agent = $payload.tool_input.subagent_type
    $model = $payload.tool_input.model
  }
}

$rec = [ordered]@{
  ts      = (Get-Date).ToString("o")
  event   = $Event
  agent   = $agent
  model   = $model
  session = $session
}
try { ($rec | ConvertTo-Json -Compress) | Add-Content -Path $log -Encoding utf8 } catch {}

# フックを失敗させない(ログ失敗で本来の作業を止めない)
exit 0
