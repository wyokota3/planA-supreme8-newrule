<#
.SYNOPSIS
  監査 provider ランナー。既存監査(auditor サブエージェント)を壊さずに、監査に使う
  LLM provider / model を差し替え可能にするための薄い実行層。

.DESCRIPTION
  provider は環境変数で選ぶ(既定は existing = 現在の Claude Code auditor サブエージェント)。

    HARNESS_AUDIT_PROVIDER          existing(既定) | copilot | codex | claude | auto
    HARNESS_AUDIT_MODEL             provider 共通のモデルID(任意)
    HARNESS_AUDIT_COPILOT_MODEL     copilot 専用モデルID(copilot 時はこちらが優先)
    HARNESS_AUDIT_STRICT_PROVIDER   1 のとき: 指定provider不可なら fail。auto fallback しない。

  このスクリプトは外部CLI(copilot)を叩く provider のみ自前で監査を実行する。
  existing / claude や auto のフォールバック先は、従来どおり Claude Code の auditor サブエージェントに
  委譲する(exit 10 を返し、呼び出し側 = /audit コマンドがサブエージェントを起動する)。

.PARAMETER Feature
  監査対象の機能ID(例: F-001)。

.OUTPUTS / EXIT CODES
  0   外部provider(copilot)が監査レポートを生成した(reports/ に書き込み済み)
  10  DELEGATE: 呼び出し側で既存 auditor サブエージェントを実行すべき(existing/claude/auto-fallback)
  2   指定provider(copilot)が使えない & フォールバック不可(明示copilot or strict)→ 失敗
  3   未実装provider(codex 等)が明示選択された → 失敗
  1   使い方/想定外エラー

  メタ情報(provider/model/fallback/policy)は標準出力を汚さず別ファイルへ:
    .harness/audit/provider.json   実行ごとの provenance
    .harness/audit/report.json     正規化した結果ポインタ(provider/model/verdict/report_path)
    reports/worklog.jsonl          既存ログsinkへ1行追記(event=audit_provider)
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Feature,
    [string]$Provider,
    [string]$Model
)

$ErrorActionPreference = 'Stop'

# ---- リポジトリルート解決 ------------------------------------------------------
$RepoRoot = $env:CLAUDE_PROJECT_DIR
if (-not $RepoRoot) { $RepoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent }
$harnessDir = Join-Path $RepoRoot ".harness/audit"
$reportsDir = Join-Path $RepoRoot "reports"

. (Join-Path $PSScriptRoot "lib/prompt.ps1")
. (Join-Path $PSScriptRoot "lib/copilot.ps1")

# ---- provider / model 解決 ----------------------------------------------------
function Resolve-Provider {
    param([string]$Override)
    $p = if ($Override) { $Override } elseif ($env:HARNESS_AUDIT_PROVIDER) { $env:HARNESS_AUDIT_PROVIDER } else { 'existing' }
    return $p.Trim().ToLowerInvariant()
}

# copilot 用モデル解決: HARNESS_AUDIT_COPILOT_MODEL > HARNESS_AUDIT_MODEL > なし
function Resolve-CopilotModel {
    param([string]$Override)
    if ($Override)                        { return @{ Model = $Override;                      Source = 'parameter';                  Explicit = $true } }
    if ($env:HARNESS_AUDIT_COPILOT_MODEL) { return @{ Model = $env:HARNESS_AUDIT_COPILOT_MODEL; Source = 'HARNESS_AUDIT_COPILOT_MODEL'; Explicit = $true } }
    if ($env:HARNESS_AUDIT_MODEL)         { return @{ Model = $env:HARNESS_AUDIT_MODEL;         Source = 'HARNESS_AUDIT_MODEL';         Explicit = $true } }
    return @{ Model = ''; Source = 'copilot-default'; Explicit = $false }   # 未指定 → --model を付けず利用者の既定モデルを尊重
}

$strict = ($env:HARNESS_AUDIT_STRICT_PROVIDER -eq '1')
$provider = Resolve-Provider -Override $Provider

# ---- メタ書き出し --------------------------------------------------------------
function Write-AuditMeta {
    param(
        [string]$SelectedProvider, [string]$SelectedModel, [string]$ModelSource,
        [bool]$ModelExplicit, [bool]$FallbackUsed, [string]$FallbackReason,
        [bool]$PolicyDenied, [string]$Verdict, [int]$ExitCode, [string]$ReportPath
    )
    if (-not (Test-Path $harnessDir)) { New-Item -ItemType Directory -Force $harnessDir | Out-Null }
    $ts = (Get-Date).ToString("o")

    $providerMeta = [ordered]@{
        ts               = $ts
        feature          = $Feature
        selected_provider = $SelectedProvider
        selected_model   = $SelectedModel
        model_source     = $ModelSource
        model_explicit   = $ModelExplicit
        strict           = $strict
        fallback_used    = $FallbackUsed
        fallback_reason  = $FallbackReason
        policy_denied    = $PolicyDenied
        exit_code        = $ExitCode
    }
    $reportMeta = [ordered]@{
        ts          = $ts
        feature     = $Feature
        provider    = $SelectedProvider
        model       = $SelectedModel
        verdict     = $Verdict
        report_path = $ReportPath
    }
    try { ($providerMeta | ConvertTo-Json -Depth 5) | Set-Content -Path (Join-Path $harnessDir "provider.json") -Encoding utf8 } catch {}
    try { ($reportMeta   | ConvertTo-Json -Depth 5) | Set-Content -Path (Join-Path $harnessDir "report.json")   -Encoding utf8 } catch {}

    # 既存ログsink(worklog.jsonl)へも1行追記。既存フィールド(ts/event/model)互換 + provider 情報を付加。
    try {
        if (-not (Test-Path $reportsDir)) { New-Item -ItemType Directory -Force $reportsDir | Out-Null }
        $rec = [ordered]@{
            ts               = $ts
            event            = "audit_provider"
            agent            = "auditor"
            model            = $SelectedModel
            selected_provider = $SelectedProvider
            model_source     = $ModelSource
            fallback_used    = $FallbackUsed
            policy_denied    = $PolicyDenied
            feature          = $Feature
        }
        ($rec | ConvertTo-Json -Compress) | Add-Content -Path (Join-Path $reportsDir "worklog.jsonl") -Encoding utf8
    } catch {}
}

# capability の失敗理由 → 利用者向けメッセージ
function Get-CapabilityMessage {
    param([string]$Reason, [string]$Detail)
    switch ($Reason) {
        'cli_missing' {
            return @"
Copilot audit provider is selected, but Copilot CLI is not available.
Install and login with GitHub Copilot CLI, or set HARNESS_AUDIT_PROVIDER=existing.
"@
        }
        'auth' {
            return @"
Copilot audit provider is selected, but Copilot CLI is not available.
Install and login with GitHub Copilot CLI, or set HARNESS_AUDIT_PROVIDER=existing.
(detail: $Detail)
"@
        }
        'policy' {
            return @"
Copilot audit provider is selected, but model access was denied by Copilot policy.
Check your Organization Copilot CLI policy and model availability, or unset HARNESS_AUDIT_COPILOT_MODEL.
(detail: $Detail)
"@
        }
        'model_unavailable' {
            return @"
Copilot audit provider is selected, but the requested model is unavailable.
Run `copilot /model` interactively and set HARNESS_AUDIT_COPILOT_MODEL to an available model ID.
(detail: $Detail)
"@
        }
        default {
            return @"
Copilot audit provider is selected, but the smoke check failed.
Verify GitHub Copilot CLI works in this environment, or set HARNESS_AUDIT_PROVIDER=existing.
(detail: $Detail)
"@
        }
    }
}

# copilot で実際に監査を実行し、レポートを reports/ に書く共通処理。
# 成功: exit 0 を呼び出し側に返すためのオブジェクトを返す。失敗時は $null を返し、$script:CopilotError に詳細を入れる。
function Invoke-CopilotProvider {
    param([hashtable]$ModelInfo)
    $model = $ModelInfo.Model
    $prompt = Build-AuditPrompt -RepoRoot $RepoRoot -Feature $Feature
    $audit = Invoke-CopilotAudit -Prompt $prompt -Model $model
    if (-not $audit.Ok) {
        $script:CopilotError = [pscustomobject]@{ Reason = $audit.Reason; Detail = $audit.Detail }
        return $null
    }

    if (-not (Test-Path $reportsDir)) { New-Item -ItemType Directory -Force $reportsDir | Out-Null }
    $stamp = (Get-Date).ToString("yyyyMMdd-HHmm")
    $reportPath = Join-Path $reportsDir "audit-$stamp-$Feature.md"
    # 既存 Markdown レポート schema をそのまま使う(provider 側はファイルを触らない=ここで書く)
    Set-Content -Path $reportPath -Value $audit.Report -Encoding utf8

    $rel = $reportPath.Substring($RepoRoot.Length).TrimStart('\','/')
    return [pscustomobject]@{ ReportPath = $rel; Verdict = $audit.Verdict; Model = $model }
}

# ================================ メイン分岐 ===================================
switch ($provider) {

    { $_ -in 'existing', 'claude' } {
        # 既存方式: Claude Code の auditor サブエージェントに委譲(現在の挙動を一切変えない)
        Write-AuditMeta -SelectedProvider $provider -SelectedModel '' -ModelSource 'n/a' `
            -ModelExplicit $false -FallbackUsed $false -FallbackReason '' -PolicyDenied $false `
            -Verdict '' -ExitCode 10 -ReportPath ''
        Write-Output "AUDIT_RUNNER_RESULT: delegate provider=$provider feature=$Feature"
        Write-Output "既存の auditor サブエージェントで監査を実行してください(provider=$provider)。"
        exit 10
    }

    'copilot' {
        $mi = Resolve-CopilotModel -Override $Model
        $cap = Test-CopilotCapability -Model $mi.Model
        if (-not $cap.Ok) {
            # 明示的に copilot を選んだ場合は分かりやすく失敗する(silent fallback しない)
            $msg = Get-CapabilityMessage -Reason $cap.Reason -Detail $cap.Detail
            [Console]::Error.WriteLine($msg)
            Write-AuditMeta -SelectedProvider 'copilot' -SelectedModel $mi.Model -ModelSource $mi.Source `
                -ModelExplicit $mi.Explicit -FallbackUsed $false -FallbackReason $cap.Reason `
                -PolicyDenied ($cap.Reason -eq 'policy') -Verdict '' -ExitCode 2 -ReportPath ''
            Write-Output "AUDIT_RUNNER_RESULT: error provider=copilot reason=$($cap.Reason)"
            exit 2
        }
        $script:CopilotError = $null
        $r = Invoke-CopilotProvider -ModelInfo $mi
        if (-not $r) {
            $msg = Get-CapabilityMessage -Reason $script:CopilotError.Reason -Detail $script:CopilotError.Detail
            [Console]::Error.WriteLine($msg)
            Write-AuditMeta -SelectedProvider 'copilot' -SelectedModel $mi.Model -ModelSource $mi.Source `
                -ModelExplicit $mi.Explicit -FallbackUsed $false -FallbackReason $script:CopilotError.Reason `
                -PolicyDenied ($script:CopilotError.Reason -eq 'policy') -Verdict '' -ExitCode 2 -ReportPath ''
            Write-Output "AUDIT_RUNNER_RESULT: error provider=copilot reason=$($script:CopilotError.Reason)"
            exit 2
        }
        Write-AuditMeta -SelectedProvider 'copilot' -SelectedModel $r.Model -ModelSource $mi.Source `
            -ModelExplicit $mi.Explicit -FallbackUsed $false -FallbackReason '' -PolicyDenied $false `
            -Verdict $r.Verdict -ExitCode 0 -ReportPath $r.ReportPath
        $shownModel = if ($mi.Model) { $mi.Model } else { '(copilot default)' }
        Write-Output "AUDIT_RUNNER_RESULT: completed provider=copilot model=$shownModel verdict=$($r.Verdict) report=$($r.ReportPath)"
        Write-Output "Copilot 監査完了。レポート: $($r.ReportPath)  判定: $($r.Verdict)"
        exit 0
    }

    'auto' {
        # copilot が使えれば copilot、ダメなら既存へフォールバック(strict のときはフォールバックしない)
        $mi = Resolve-CopilotModel -Override $Model
        $cap = Test-CopilotCapability -Model $mi.Model
        if ($cap.Ok) {
            $script:CopilotError = $null
            $r = Invoke-CopilotProvider -ModelInfo $mi
            if ($r) {
                Write-AuditMeta -SelectedProvider 'copilot' -SelectedModel $r.Model -ModelSource $mi.Source `
                    -ModelExplicit $mi.Explicit -FallbackUsed $false -FallbackReason '' -PolicyDenied $false `
                    -Verdict $r.Verdict -ExitCode 0 -ReportPath $r.ReportPath
                $shownModel = if ($mi.Model) { $mi.Model } else { '(copilot default)' }
                Write-Output "AUDIT_RUNNER_RESULT: completed provider=copilot model=$shownModel verdict=$($r.Verdict) report=$($r.ReportPath)"
                Write-Output "auto: Copilot 監査完了。レポート: $($r.ReportPath)  判定: $($r.Verdict)"
                exit 0
            }
            # 実行途中で失敗
            if ($strict) {
                $msg = Get-CapabilityMessage -Reason $script:CopilotError.Reason -Detail $script:CopilotError.Detail
                [Console]::Error.WriteLine($msg)
                Write-AuditMeta -SelectedProvider 'copilot' -SelectedModel $mi.Model -ModelSource $mi.Source `
                    -ModelExplicit $mi.Explicit -FallbackUsed $false -FallbackReason $script:CopilotError.Reason `
                    -PolicyDenied ($script:CopilotError.Reason -eq 'policy') -Verdict '' -ExitCode 2 -ReportPath ''
                Write-Output "AUDIT_RUNNER_RESULT: error provider=copilot reason=$($script:CopilotError.Reason) strict=1"
                exit 2
            }
            $reason = "copilot_invoke_failed:$($script:CopilotError.Reason)"
        }
        else {
            if ($strict) {
                $msg = Get-CapabilityMessage -Reason $cap.Reason -Detail $cap.Detail
                [Console]::Error.WriteLine($msg)
                Write-AuditMeta -SelectedProvider 'copilot' -SelectedModel $mi.Model -ModelSource $mi.Source `
                    -ModelExplicit $mi.Explicit -FallbackUsed $false -FallbackReason $cap.Reason `
                    -PolicyDenied ($cap.Reason -eq 'policy') -Verdict '' -ExitCode 2 -ReportPath ''
                Write-Output "AUDIT_RUNNER_RESULT: error provider=copilot reason=$($cap.Reason) strict=1"
                exit 2
            }
            $reason = "copilot_unavailable:$($cap.Reason)"
        }

        # 既存へフォールバック
        Write-AuditMeta -SelectedProvider 'existing' -SelectedModel '' -ModelSource 'n/a' `
            -ModelExplicit $false -FallbackUsed $true -FallbackReason $reason `
            -PolicyDenied ($reason -like '*policy*') -Verdict '' -ExitCode 10 -ReportPath ''
        Write-Output "AUDIT_RUNNER_RESULT: delegate provider=existing fallback_from=copilot reason=$reason"
        Write-Output "auto: Copilot を使えないため既存 auditor サブエージェントにフォールバックします(理由: $reason)。"
        exit 10
    }

    'codex' {
        # codex は将来用の予約枠。このテンプレートでは未実装。明示選択時は分かりやすく失敗する。
        $msg = @"
Codex audit provider is not configured in this template.
Use HARNESS_AUDIT_PROVIDER=copilot (GitHub Copilot CLI) or HARNESS_AUDIT_PROVIDER=existing.
"@
        [Console]::Error.WriteLine($msg)
        Write-AuditMeta -SelectedProvider 'codex' -SelectedModel ($env:HARNESS_AUDIT_MODEL) -ModelSource 'HARNESS_AUDIT_MODEL' `
            -ModelExplicit ([bool]$env:HARNESS_AUDIT_MODEL) -FallbackUsed $false -FallbackReason 'not_implemented' `
            -PolicyDenied $false -Verdict '' -ExitCode 3 -ReportPath ''
        Write-Output "AUDIT_RUNNER_RESULT: error provider=codex reason=not_implemented"
        exit 3
    }

    default {
        [Console]::Error.WriteLine("Unknown HARNESS_AUDIT_PROVIDER: '$provider'. Use existing | copilot | codex | claude | auto.")
        Write-Output "AUDIT_RUNNER_RESULT: error reason=unknown_provider value=$provider"
        exit 1
    }
}
