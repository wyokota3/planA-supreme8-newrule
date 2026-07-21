# 監査プロンプトビルダー(provider 非依存)
#
# 既存監査の "唯一のプロンプト源" を再利用するための関数群。
# auditor サブエージェント(.claude/agents/auditor.md)の本文 = 監査役の役割・規約・出力形式 を
# そのまま流用し、機能ごとのコンテキスト(対象機能ID・SPEC該当節の場所)だけを足す。
# これにより provider ごとにプロンプトを複製して劣化させない。
#
# dot-source して使う:  . "$PSScriptRoot/prompt.ps1"

# auditor.md / audit.md から YAML フロントマター(先頭の --- ... ---)を除いた本文を返す。
function Get-MarkdownBody {
    param([Parameter(Mandatory)][string]$Path)
    if (-not (Test-Path $Path)) { return "" }
    $text = Get-Content -Path $Path -Raw -Encoding utf8
    # 先頭が --- で始まる場合のみフロントマターとして除去する
    if ($text -match '^\s*---\s*\r?\n') {
        $parts = [regex]::Split($text, '(?m)^---\s*$')
        # parts[0]="" parts[1]=frontmatter parts[2..]=body
        if ($parts.Count -ge 3) { return ($parts[2..($parts.Count-1)] -join "---").TrimStart("`r","`n") }
    }
    return $text
}

# specs/SPEC.md から該当機能の節(## F-XXX ... 次の同レベル見出しまで)をベストエフォートで切り出す。
# 取り出せなければ空文字を返す(copilot 側に「自分で SPEC.md を読め」と指示してフォールバックする)。
function Get-SpecSection {
    param(
        [Parameter(Mandatory)][string]$RepoRoot,
        [Parameter(Mandatory)][string]$Feature
    )
    $spec = Join-Path $RepoRoot "specs/SPEC.md"
    if (-not (Test-Path $spec)) { return "" }
    $lines = Get-Content -Path $spec -Encoding utf8
    $featureEsc = [regex]::Escape($Feature)
    $start = -1
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match "^#{1,6}\s+.*$featureEsc(?!\d)") { $start = $i; break }   # 直後に数字が続く場合は除外(F-001 と F-0011 の混同防止)
    }
    if ($start -lt 0) { return "" }
    # 見出しレベルを取得
    $level = ($lines[$start] -replace '^(#{1,6}).*$', '$1').Length
    $end = $lines.Count
    for ($j = $start + 1; $j -lt $lines.Count; $j++) {
        if ($lines[$j] -match "^(#{1,$level})\s+") { $end = $j; break }
    }
    return ($lines[$start..($end-1)] -join "`n").Trim()
}

# 外部 provider(copilot 等)にそのまま渡せる、自己完結した監査プロンプト文字列を組み立てる。
function Build-AuditPrompt {
    param(
        [Parameter(Mandatory)][string]$RepoRoot,
        [Parameter(Mandatory)][string]$Feature
    )

    $auditorBody = Get-MarkdownBody (Join-Path $RepoRoot ".claude/agents/auditor.md")
    if (-not $auditorBody) {
        # 既存の監査役定義が見つからない場合の最小フォールバック
        $auditorBody = "あなたは監査専門のエージェントです。仕様と実装を突き合わせ、各受け入れ条件の実現箇所をファイル名と行番号で引用し、未実装・オーバー実装・テスト不足を指摘してください。コードは変更しないこと。"
    }

    $specSection = Get-SpecSection -RepoRoot $RepoRoot -Feature $Feature
    if ($specSection) {
        $specBlock = @"
対象機能 $Feature の SPEC 該当節(specs/SPEC.md より抜粋):

$specSection
"@
    } else {
        $specBlock = "対象機能 $Feature の仕様は specs/SPEC.md にある。まず specs/SPEC.md を読み、$Feature の節と受け入れ条件を特定すること。"
    }

    # auditor サブエージェントの役割・規約・出力形式を本文ごと再利用し、外部CLI向けの実行コンテキストを足す。
    $prompt = @"
$auditorBody

----------------------------------------------------------------
## 今回の監査タスク(このリポジトリで実行)

- 対象機能: $Feature
- 仕様書: specs/SPEC.md
- テスト: tests/ 配下
- 実装コード: リポジトリ内の該当ソース(Grep で特定してよい)

$specBlock

## 厳守事項(provider 実行モード)

- あなたは **read-only** の監査役である。ファイルの作成・変更・削除を一切行わないこと。
  - レポートを自分でファイルに書き出さない。**標準出力(stdout)にのみ** Markdown レポートを出力する。
  - ファイル書き込みは呼び出し側スクリプトが行う。
- 出力は上記「出力形式」の Markdown レポート 1 本のみ。前置きや後書きの雑談を付けない。
- 受け入れ条件ごとに、実装箇所をファイル名と行番号で**必ず引用**する。引用できないものは「未実装」と明記する。
- 最後の行に、機械可読の総合判定を **次の形式ちょうどで** 出力する(レポート本文とは別の最終行):
  AUDIT_VERDICT: <pass | needs_fix | block>
  - pass      = 受け入れ条件をすべて満たし、重大な指摘なし
  - needs_fix = 未実装/不足/オーバー実装があり要修正
  - block     = 仕様やテストとの矛盾など、先に進めない重大問題
"@

    return $prompt
}
