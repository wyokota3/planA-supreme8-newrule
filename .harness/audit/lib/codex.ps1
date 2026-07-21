# OpenAI Codex CLI 監査 provider
#
# 役割:
#   1. capability check  : codex CLI が使えるか / ログイン済みか / モデル指定が通るかを事前判定し、原因を区別する
#   2. invoke            : 既存監査プロンプトを codex exec(非対話モード)に渡して監査を実行する
#   3. normalize         : codex の最終応答から Markdown レポート本文と AUDIT_VERDICT を分離する
#
# ChatGPT アカウントログイン(Plus/Pro/Business 等のプラン枠)で動く。API キー・従量課金は不要。
# Codex は必須ではない(optional provider)。使えない環境では呼び出し側が existing にフォールバックする。
# dot-source して使う:  . "$PSScriptRoot/codex.ps1"

# codex exec を1回呼ぶ低レベルラッパ。
# プロンプトは引数ではなく stdin で渡す(Windows のコマンドライン長制限 ~32K 文字を回避)。
# 最終応答は --output-last-message の一時ファイルから回収する(stdout は進捗・MCP起動ログ等で汚れるため)。
function Invoke-CodexRaw {
    param(
        [Parameter(Mandatory)][string]$Prompt,
        [string]$Model,
        [string]$WorkDir
    )
    $lastMsgFile = Join-Path ([IO.Path]::GetTempPath()) ("codex-audit-" + [IO.Path]::GetRandomFileName() + ".txt")
    # read-only sandbox: 監査役にファイルを書かせない(レポート書き込みは呼び出し側スクリプトが行う)
    $cliArgs = @('exec', '-', '--sandbox', 'read-only', '--skip-git-repo-check', '--color', 'never', '--ephemeral', '-o', $lastMsgFile)
    if ($Model) { $cliArgs += @('--model', $Model) }     # モデル未指定なら --model を付けない(利用者の config.toml 既定モデルを尊重)
    if ($WorkDir) { $cliArgs += @('--cd', $WorkDir) }    # 呼び出し元 cwd に依存せずリポジトリルートで監査させる

    $output = ""
    $lastMessage = ""
    $code = 0
    $prevEnc = $OutputEncoding
    try {
        $OutputEncoding = [System.Text.UTF8Encoding]::new($false)   # 日本語プロンプトを stdin 経由で壊さない
        $output = ($Prompt | & codex @cliArgs 2>&1 | Out-String)
        $code = $LASTEXITCODE
        if ($null -eq $code) { $code = 0 }
        if (Test-Path $lastMsgFile) { $lastMessage = [string](Get-Content $lastMsgFile -Raw -Encoding utf8) }
    } catch {
        $output = $_.Exception.Message
        $code = 127
    } finally {
        $OutputEncoding = $prevEnc
        Remove-Item $lastMsgFile -Force -ErrorAction SilentlyContinue
    }
    return [pscustomobject]@{ ExitCode = $code; Output = $output; LastMessage = $lastMessage }
}

# エラー詳細の整形: MCP起動ログ等のノイズを落とし、末尾の意味のある行だけ返す。
function Get-CodexDetail {
    param([string]$Text)
    $lines = ($Text -split "`r?`n") | Where-Object { $_.Trim() }
    return (($lines | Select-Object -Last 6) -join "`n").Trim()
}

# codex 出力テキストから失敗理由を分類する。cli_outdated / usage_limit / auth / model / generic を区別。
function Get-CodexFailureReason {
    param([string]$Text, [switch]$ModelPhase)
    $t = ($Text | Out-String).ToLowerInvariant()

    # 実測済み: 古い CLI で新モデルを指定すると "requires a newer version of Codex. Please upgrade ..." が返る
    $outdated = @('newer version of codex', 'upgrade to the latest')
    $limit    = @('usage limit', 'rate limit', 'too many requests', 'http 429', ' 429', 'quota', 'limit reached')
    $auth     = @('not logged in', 'not authenticated', 'unauthenticated', 'please log in', 'please login',
                  'codex login', 'sign in', 'http 401', ' 401', 'unauthorized', 'no credentials', 'authentication')
    $model    = @('unknown model', 'invalid model', 'no such model', 'model not found', 'unsupported model',
                  'unavailable model', 'model is not available', 'no access to model')

    foreach ($k in $outdated) { if ($t.Contains($k)) { return 'cli_outdated' } }
    foreach ($k in $limit)    { if ($t.Contains($k)) { return 'usage_limit' } }
    if ($ModelPhase) {
        foreach ($k in $model) { if ($t.Contains($k)) { return 'model_unavailable' } }
    }
    foreach ($k in $auth)     { if ($t.Contains($k)) { return 'auth' } }
    if ($ModelPhase) { return 'model_unavailable' }
    return 'smoke_failed'
}

# Codex provider の事前チェック。順に:
#   1. codex コマンドの存在
#   2. codex login status(トークンを消費しない)
#   3. 最小プロンプトでの疎通(モデル指定があればそのモデルで。metered な呼び出しはこの1回だけ)
# 返り値: Ok(bool), Reason(string), Detail(string)
function Test-CodexCapability {
    param([string]$Model)

    # 1. コマンド存在
    $cmd = Get-Command codex -ErrorAction SilentlyContinue
    if (-not $cmd) {
        return [pscustomobject]@{ Ok = $false; Reason = 'cli_missing'; Detail = 'codex command not found on PATH' }
    }

    # 2. ログイン状態
    $loginOut = ""
    $loginCode = 0
    try {
        $loginOut = (& codex login status 2>&1 | Out-String)
        $loginCode = $LASTEXITCODE
        if ($null -eq $loginCode) { $loginCode = 0 }
    } catch { $loginOut = $_.Exception.Message; $loginCode = 127 }
    if ($loginCode -ne 0 -or $loginOut -match '(?i)not\s+logged\s+in') {
        return [pscustomobject]@{ Ok = $false; Reason = 'auth'; Detail = (Get-CodexDetail $loginOut) }
    }

    # 3. 疎通確認(モデル指定込み)
    $smoke = Invoke-CodexRaw -Prompt 'Respond with just: OK' -Model $Model
    if ($smoke.ExitCode -ne 0) {
        $reason = Get-CodexFailureReason -Text $smoke.Output -ModelPhase:([bool]$Model)
        return [pscustomobject]@{ Ok = $false; Reason = $reason; Detail = (Get-CodexDetail $smoke.Output) }
    }

    return [pscustomobject]@{ Ok = $true; Reason = 'ok'; Detail = '' }
}

# 監査プロンプトを codex exec に渡して実行し、Markdown レポート本文と verdict を返す。
# 返り値: Ok(bool), Report(string=Markdown本文), Verdict(string), ExitCode, Detail, Reason
function Invoke-CodexAudit {
    param(
        [Parameter(Mandatory)][string]$Prompt,
        [string]$Model,
        [string]$WorkDir
    )
    $res = Invoke-CodexRaw -Prompt $Prompt -Model $Model -WorkDir $WorkDir
    if ($res.ExitCode -ne 0) {
        $reason = Get-CodexFailureReason -Text $res.Output -ModelPhase:([bool]$Model)
        return [pscustomobject]@{ Ok = $false; Report = ''; Verdict = ''; ExitCode = $res.ExitCode; Detail = (Get-CodexDetail $res.Output); Reason = $reason }
    }
    if (-not $res.LastMessage.Trim()) {
        return [pscustomobject]@{ Ok = $false; Report = ''; Verdict = ''; ExitCode = 0; Detail = 'codex exec succeeded but returned an empty final message'; Reason = 'empty_output' }
    }

    $norm = ConvertFrom-CodexOutput -Text $res.LastMessage
    return [pscustomobject]@{ Ok = $true; Report = $norm.Report; Verdict = $norm.Verdict; ExitCode = 0; Detail = ''; Reason = 'ok' }
}

# codex の最終応答から、末尾の "AUDIT_VERDICT: xxx" 行を verdict として分離し、
# レポート本文(Markdown)からは取り除く。既存 Markdown レポート schema をそのまま保つための正規化。
function ConvertFrom-CodexOutput {
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
