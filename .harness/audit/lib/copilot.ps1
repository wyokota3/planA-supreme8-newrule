# Copilot CLI 監査 provider
#
# 役割:
#   1. capability check  : copilot CLI が使えるか / モデル指定が通るかを事前判定し、原因を区別する
#   2. invoke            : 既存監査プロンプトを copilot CLI に渡して監査を実行する
#   3. normalize         : copilot の出力から Markdown レポート本文と AUDIT_VERDICT を分離する
#
# Copilot は必須ではない(optional provider)。使えない環境では呼び出し側が existing にフォールバックする。
# dot-source して使う:  . "$PSScriptRoot/copilot.ps1"

# copilot CLI を1回呼ぶ低レベルラッパ。stdout/stderr をまとめて文字列で返す。
function Invoke-CopilotRaw {
    param(
        [Parameter(Mandatory)][string]$Prompt,
        [string]$Model
    )
    $cliArgs = @('-s', '--no-ask-user')
    if ($Model) { $cliArgs += @('--model', $Model) }   # モデル未指定なら --model を付けない(利用者の既定モデルを尊重)
    $cliArgs += @('-p', $Prompt)

    $output = ""
    $code = 0
    try {
        $output = (& copilot @cliArgs 2>&1 | Out-String)
        $code = $LASTEXITCODE
        if ($null -eq $code) { $code = 0 }
    } catch {
        $output = $_.Exception.Message
        $code = 127
    }
    return [pscustomobject]@{ ExitCode = $code; Output = $output }
}

# copilot 出力テキストから失敗理由を分類する。auth / policy / model / generic を区別。
function Get-CopilotFailureReason {
    param([string]$Text, [switch]$ModelPhase)
    $t = ($Text | Out-String).ToLowerInvariant()

    $policy = @('policy', 'not allowed', 'denied', 'forbidden', 'disabled by your organization',
                'access to this model', 'not permitted', 'blocked', 'http 403', ' 403')
    $auth   = @('not logged in', 'not authenticated', 'unauthenticated', 'please log in', 'please login',
                'sign in', 'run /login', 'http 401', ' 401', 'no credentials', 'authentication')
    $model  = @('unknown model', 'invalid model', 'no such model', 'model not found', 'unsupported model',
                'unavailable model', 'model is not available', 'no access to model')

    foreach ($k in $policy) { if ($t.Contains($k)) { return 'policy' } }
    if ($ModelPhase) {
        foreach ($k in $model) { if ($t.Contains($k)) { return 'model_unavailable' } }
    }
    foreach ($k in $auth)  { if ($t.Contains($k)) { return 'auth' } }
    if ($ModelPhase) { return 'model_unavailable' }
    return 'smoke_failed'
}

# Copilot provider の事前チェック。順に:
#   1. copilot コマンドの存在
#   2. 最小プロンプトの成功(未ログイン/policy 拒否を区別)
#   3. モデル指定がある場合、そのモデルで最小プロンプトが成功するか
# 返り値: Ok(bool), Reason(string), Detail(string)
function Test-CopilotCapability {
    param([string]$Model)

    # 1. コマンド存在
    $cmd = Get-Command copilot -ErrorAction SilentlyContinue
    if (-not $cmd) {
        return [pscustomobject]@{ Ok = $false; Reason = 'cli_missing'; Detail = 'copilot command not found on PATH' }
    }

    # 2. 既定モデルでの疎通(モデル指定なし = 利用者の既定モデル)
    $smoke = Invoke-CopilotRaw -Prompt 'Respond with just: OK'
    if ($smoke.ExitCode -ne 0) {
        $reason = Get-CopilotFailureReason -Text $smoke.Output
        return [pscustomobject]@{ Ok = $false; Reason = $reason; Detail = $smoke.Output.Trim() }
    }

    # 3. モデル指定がある場合のみ、そのモデルで疎通確認
    if ($Model) {
        $smokeM = Invoke-CopilotRaw -Prompt 'Respond with just: OK' -Model $Model
        if ($smokeM.ExitCode -ne 0) {
            $reason = Get-CopilotFailureReason -Text $smokeM.Output -ModelPhase
            return [pscustomobject]@{ Ok = $false; Reason = $reason; Detail = $smokeM.Output.Trim() }
        }
    }

    return [pscustomobject]@{ Ok = $true; Reason = 'ok'; Detail = '' }
}

# 監査プロンプトを copilot に渡して実行し、Markdown レポート本文と verdict を返す。
# 返り値: Ok(bool), Report(string=Markdown本文), Verdict(string), ExitCode, Detail
function Invoke-CopilotAudit {
    param(
        [Parameter(Mandatory)][string]$Prompt,
        [string]$Model
    )
    $res = Invoke-CopilotRaw -Prompt $Prompt -Model $Model
    if ($res.ExitCode -ne 0) {
        $reason = Get-CopilotFailureReason -Text $res.Output -ModelPhase:([bool]$Model)
        return [pscustomobject]@{ Ok = $false; Report = ''; Verdict = ''; ExitCode = $res.ExitCode; Detail = $res.Output.Trim(); Reason = $reason }
    }

    $norm = ConvertFrom-CopilotOutput -Text $res.Output
    return [pscustomobject]@{ Ok = $true; Report = $norm.Report; Verdict = $norm.Verdict; ExitCode = 0; Detail = ''; Reason = 'ok' }
}

# copilot の生出力から、末尾の "AUDIT_VERDICT: xxx" 行を verdict として分離し、
# レポート本文(Markdown)からは取り除く。既存 Markdown レポート schema をそのまま保つための正規化。
function ConvertFrom-CopilotOutput {
    param([Parameter(Mandatory)][string]$Text)
    $lines = $Text -split "`r?`n"
    $verdict = ''
    $keep = New-Object System.Collections.Generic.List[string]
    foreach ($line in $lines) {
        $m = [regex]::Match($line, '^\s*AUDIT_VERDICT:\s*(pass|needs_fix|block)\s*$', 'IgnoreCase')
        if ($m.Success) { $verdict = $m.Groups[1].Value.ToLowerInvariant(); continue }
        $keep.Add($line)
    }
    return [pscustomobject]@{ Report = ($keep -join "`n").Trim(); Verdict = $verdict }
}
