<#
.SYNOPSIS
  監査 provider ランナー。既存監査(auditor サブエージェント)を壊さずに、監査に使う
  LLM provider / model を差し替え可能にするための薄い実行層。

.DESCRIPTION
  provider は環境変数で選ぶ(既定は existing = 現在の Claude Code auditor サブエージェント)。

    HARNESS_AUDIT_PROVIDER          existing(既定) | copilot | codex | claude | auto
    HARNESS_AUDIT_MODEL             provider 共通のモデルID(任意)
    HARNESS_AUDIT_COPILOT_MODEL     copilot 専用モデルID(copilot 時はこちらが優先)
    HARNESS_AUDIT_CODEX_MODEL       codex 専用モデルID(codex 時はこちらが優先。例: gpt-5.6-sol)
    HARNESS_AUDIT_STRICT_PROVIDER   1 のとき: 指定provider不可なら fail。auto は existing に fallback しない。

  このスクリプトは外部CLI(copilot / codex)を叩く provider のみ自前で監査を実行する。
  existing / claude や auto のフォールバック先は、従来どおり Claude Code の auditor サブエージェントに
  委譲する(exit 10 を返し、呼び出し側 = /audit コマンドがサブエージェントを起動する)。

  codex provider は OpenAI Codex CLI(codex exec)経由。ChatGPT アカウントログイン(Plus/Pro 等の
  プラン枠)で動くため API キーは不要。監査は read-only sandbox で実行される。

.PARAMETER Feature
  監査対象の機能ID(例: F-001)。

.OUTPUTS / EXIT CODES
  0   外部provider(copilot / codex)が監査レポートを生成した(reports/ に書き込み済み)
  10  DELEGATE: 呼び出し側で既存 auditor サブエージェントを実行すべき(existing/claude/auto-fallback)
  2   指定provider(copilot / codex)が使えない & フォールバック不可(明示指定 or strict)→ 失敗
  3   (予約)未実装provider が明示選択された → 失敗(現在は該当providerなし)
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
. (Join-Path $PSScriptRoot "lib/codex.ps1")

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

# codex 用モデル解決: HARNESS_AUDIT_CODEX_MODEL > HARNESS_AUDIT_MODEL > なし
function Resolve-CodexModel {
    param([string]$Override)
    if ($Override)                      { return @{ Model = $Override;                    Source = 'parameter';                Explicit = $true } }
    if ($env:HARNESS_AUDIT_CODEX_MODEL) { return @{ Model = $env:HARNESS_AUDIT_CODEX_MODEL; Source = 'HARNESS_AUDIT_CODEX_MODEL'; Explicit = $true } }
    if ($env:HARNESS_AUDIT_MODEL)       { return @{ Model = $env:HARNESS_AUDIT_MODEL;       Source = 'HARNESS_AUDIT_MODEL';       Explicit = $true } }
    return @{ Model = ''; Source = 'codex-default'; Explicit = $false }   # 未指定 → --model を付けず利用者の config.toml 既定モデルを尊重
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

# codex の capability 失敗理由 → 利用者向けメッセージ
function Get-CodexCapabilityMessage {
    param([string]$Reason, [string]$Detail)
    switch ($Reason) {
        'cli_missing' {
            return @"
Codex audit provider is selected, but Codex CLI is not available.
Install with: npm install -g @openai/codex   then login: codex login
Or set HARNESS_AUDIT_PROVIDER=existing.
"@
        }
        'auth' {
            return @"
Codex audit provider is selected, but you are not logged in to Codex CLI.
Run: codex login   (sign in with your ChatGPT account. Plus/Pro plan includes Codex)
Or set HARNESS_AUDIT_PROVIDER=existing.
(detail: $Detail)
"@
        }
        'cli_outdated' {
            return @"
Codex audit provider is selected, but the installed Codex CLI is too old for the requested model.
Upgrade with: npm install -g @openai/codex@latest   and retry.
(detail: $Detail)
"@
        }
        'usage_limit' {
            return @"
Codex audit provider is selected, but your ChatGPT plan usage limit appears to be reached.
Wait for the rolling window to reset, or use the normal /audit (Claude auditor) for now.
(detail: $Detail)
"@
        }
        'model_unavailable' {
            return @"
Codex audit provider is selected, but the requested model is unavailable.
Check the model ID (e.g. gpt-5.6-sol) and your ChatGPT plan, or set HARNESS_AUDIT_CODEX_MODEL to an available model ID.
(detail: $Detail)
"@
        }
        default {
            return @"
Codex audit provider is selected, but the smoke check failed.
Verify that codex exec works in this environment, or set HARNESS_AUDIT_PROVIDER=existing.
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

# codex で実際に監査を実行し、レポートを reports/ に書く共通処理。
# 成功: exit 0 を呼び出し側に返すためのオブジェクトを返す。失敗時は $null を返し、$script:CodexError に詳細を入れる。
function Invoke-CodexProvider {
    param([hashtable]$ModelInfo)
    $model = $ModelInfo.Model
    $prompt = Build-AuditPrompt -RepoRoot $RepoRoot -Feature $Feature
    $audit = Invoke-CodexAudit -Prompt $prompt -Model $model -WorkDir $RepoRoot
    if (-not $audit.Ok) {
        $script:CodexError = [pscustomobject]@{ Reason = $audit.Reason; Detail = $audit.Detail }
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
        # 外部provider を copilot → codex の順に試し、どちらも使えなければ既存へフォールバック。
        # strict のときは existing へフォールバックせず fail する(外部judgeを必須にする CI / 品質ゲート向け)。
        $failParts = @()

        # 1) copilot
        $miC = Resolve-CopilotModel -Override $Model
        $capC = Test-CopilotCapability -Model $miC.Model
        if ($capC.Ok) {
            $script:CopilotError = $null
            $r = Invoke-CopilotProvider -ModelInfo $miC
            if ($r) {
                Write-AuditMeta -SelectedProvider 'copilot' -SelectedModel $r.Model -ModelSource $miC.Source `
                    -ModelExplicit $miC.Explicit -FallbackUsed $false -FallbackReason '' -PolicyDenied $false `
                    -Verdict $r.Verdict -ExitCode 0 -ReportPath $r.ReportPath
                $shownModel = if ($miC.Model) { $miC.Model } else { '(copilot default)' }
                Write-Output "AUDIT_RUNNER_RESULT: completed provider=copilot model=$shownModel verdict=$($r.Verdict) report=$($r.ReportPath)"
                Write-Output "auto: Copilot 監査完了。レポート: $($r.ReportPath)  判定: $($r.Verdict)"
                exit 0
            }
            $failParts += "copilot_invoke_failed:$($script:CopilotError.Reason)"
        }
        else {
            $failParts += "copilot_unavailable:$($capC.Reason)"
        }

        # 2) codex
        $miX = Resolve-CodexModel -Override $Model
        $capX = Test-CodexCapability -Model $miX.Model
        if ($capX.Ok) {
            $script:CodexError = $null
            $r = Invoke-CodexProvider -ModelInfo $miX
            if ($r) {
                Write-AuditMeta -SelectedProvider 'codex' -SelectedModel $r.Model -ModelSource $miX.Source `
                    -ModelExplicit $miX.Explicit -FallbackUsed $true -FallbackReason ($failParts -join '; ') -PolicyDenied $false `
                    -Verdict $r.Verdict -ExitCode 0 -ReportPath $r.ReportPath
                $shownModel = if ($miX.Model) { $miX.Model } else { '(codex default)' }
                Write-Output "AUDIT_RUNNER_RESULT: completed provider=codex model=$shownModel verdict=$($r.Verdict) report=$($r.ReportPath)"
                Write-Output "auto: Codex 監査完了(copilot 不可のため切替)。レポート: $($r.ReportPath)  判定: $($r.Verdict)"
                exit 0
            }
            $failParts += "codex_invoke_failed:$($script:CodexError.Reason)"
        }
        else {
            $failParts += "codex_unavailable:$($capX.Reason)"
        }

        $reason = $failParts -join '; '
        if ($strict) {
            [Console]::Error.WriteLine("auto(strict): no external audit provider is available. reasons: $reason")
            Write-AuditMeta -SelectedProvider 'auto' -SelectedModel '' -ModelSource 'n/a' `
                -ModelExplicit $false -FallbackUsed $false -FallbackReason $reason `
                -PolicyDenied ($reason -like '*policy*') -Verdict '' -ExitCode 2 -ReportPath ''
            Write-Output "AUDIT_RUNNER_RESULT: error provider=auto reason=$reason strict=1"
            exit 2
        }

        # 既存へフォールバック
        Write-AuditMeta -SelectedProvider 'existing' -SelectedModel '' -ModelSource 'n/a' `
            -ModelExplicit $false -FallbackUsed $true -FallbackReason $reason `
            -PolicyDenied ($reason -like '*policy*') -Verdict '' -ExitCode 10 -ReportPath ''
        Write-Output "AUDIT_RUNNER_RESULT: delegate provider=existing fallback_from=auto reason=$reason"
        Write-Output "auto: 外部provider(copilot / codex)を使えないため既存 auditor サブエージェントにフォールバックします(理由: $reason)。"
        exit 10
    }

    'codex' {
        $mi = Resolve-CodexModel -Override $Model
        $cap = Test-CodexCapability -Model $mi.Model
        if (-not $cap.Ok) {
            # 明示的に codex を選んだ場合は分かりやすく失敗する(silent fallback しない)
            $msg = Get-CodexCapabilityMessage -Reason $cap.Reason -Detail $cap.Detail
            [Console]::Error.WriteLine($msg)
            Write-AuditMeta -SelectedProvider 'codex' -SelectedModel $mi.Model -ModelSource $mi.Source `
                -ModelExplicit $mi.Explicit -FallbackUsed $false -FallbackReason $cap.Reason `
                -PolicyDenied $false -Verdict '' -ExitCode 2 -ReportPath ''
            Write-Output "AUDIT_RUNNER_RESULT: error provider=codex reason=$($cap.Reason)"
            exit 2
        }
        $script:CodexError = $null
        $r = Invoke-CodexProvider -ModelInfo $mi
        if (-not $r) {
            $msg = Get-CodexCapabilityMessage -Reason $script:CodexError.Reason -Detail $script:CodexError.Detail
            [Console]::Error.WriteLine($msg)
            Write-AuditMeta -SelectedProvider 'codex' -SelectedModel $mi.Model -ModelSource $mi.Source `
                -ModelExplicit $mi.Explicit -FallbackUsed $false -FallbackReason $script:CodexError.Reason `
                -PolicyDenied $false -Verdict '' -ExitCode 2 -ReportPath ''
            Write-Output "AUDIT_RUNNER_RESULT: error provider=codex reason=$($script:CodexError.Reason)"
            exit 2
        }
        Write-AuditMeta -SelectedProvider 'codex' -SelectedModel $r.Model -ModelSource $mi.Source `
            -ModelExplicit $mi.Explicit -FallbackUsed $false -FallbackReason '' -PolicyDenied $false `
            -Verdict $r.Verdict -ExitCode 0 -ReportPath $r.ReportPath
        $shownModel = if ($mi.Model) { $mi.Model } else { '(codex default)' }
        Write-Output "AUDIT_RUNNER_RESULT: completed provider=codex model=$shownModel verdict=$($r.Verdict) report=$($r.ReportPath)"
        Write-Output "Codex 監査完了。レポート: $($r.ReportPath)  判定: $($r.Verdict)"
        exit 0
    }

    default {
        [Console]::Error.WriteLine("Unknown HARNESS_AUDIT_PROVIDER: '$provider'. Use existing | copilot | codex | claude | auto.")
        Write-Output "AUDIT_RUNNER_RESULT: error reason=unknown_provider value=$provider"
        exit 1
    }
}
