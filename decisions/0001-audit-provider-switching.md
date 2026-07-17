# ADR 0001: 監査の LLM provider / model を差し替え可能にする

- 日付: 2026-06-09
- ステータス: 採用
- 関連: `.harness/audit/`, `docs/AUDIT_PROVIDERS.md`, `.claude/commands/audit.md`, `.claude/agents/auditor.md`

## 背景

このテンプレートは複数人で使い、利用者の環境差(Claude Code のみ / Copilot CLI も使える /
組織ポリシーで Copilot 不可 / 将来 BYOK・OpenAI互換)が大きい。Copilot CLI 経由で GPT-5.5 系が
使える人だけが、既存監査のモデルとしてそれを選べるようにしたい。一方で Copilot / GPT-5.5 を**必須化しない**。

調査の結果、この監査は「実行スクリプト」ではなく **Claude Code の `auditor` サブエージェント**で動いている:

- エントリポイント: `/audit <F-XXX>` コマンド + WORKFLOW ステップ7
- 出力: Markdown レポート `reports/audit-YYYYMMDD-HHMM-<F>.md`(JSON schema は無い)
- exit code / CI / Makefile / package.json / pre-commit / settings.json は**いずれも無い**
- 監査役は既に read-only(`./reports/` にのみ Write)

つまり「外部LLMを叩く実行層」が存在しないため、そこを最小追加するのが切替の挿入点になる。

## 決定

既存の `/audit` + `auditor` サブエージェントを**既定(`existing`)として温存**し、外部CLIを叩く薄い
opt-in 実行層 `.harness/audit/run-audit.ps1` を追加する。provider / model は環境変数で選ぶ。

- `HARNESS_AUDIT_PROVIDER` = `existing`(既定) / `copilot` / `codex` / `claude` / `auto`
- `HARNESS_AUDIT_MODEL` / `HARNESS_AUDIT_COPILOT_MODEL`(copilot 優先)。未指定なら `--model` を付けない
- `HARNESS_AUDIT_STRICT_PROVIDER=1` で「指定provider不可なら fail。auto fallback しない」

provider runner は existing/claude/auto-fallback では exit 10 を返して**従来のサブエージェントに委譲**する。
copilot のみ自前で `copilot -s --no-ask-user [--model] -p "<prompt>"` を実行する。

## 互換性の方針

- 監査レポートは**既存と同じ Markdown schema**のまま `reports/audit-*.md` に出す(schema 不変)。
- 既存レポートに `provider`/`model` 欄が無いため、メタ情報は**別ファイル**(`.harness/audit/provider.json` /
  `report.json`)+ 既存 `reports/worklog.jsonl` へ出す。これらランタイム出力は `.gitignore` 済み。
- provider 未指定時の挙動・エントリポイント・出力形式・ログ保存先を変えない。

## 設計上の判断

1. **プロンプトを複製しない**: `.claude/agents/auditor.md` の本文(役割・規約・出力形式)を
   `lib/prompt.ps1` で再利用し、機能固有コンテキストだけを足す。provider ごとの prompt 劣化を防ぐ。
2. **read-only 厳守**: copilot にはレポートを stdout に出させ、ファイル書き込みは runner が行う。
   監査provider側はリポジトリのファイルを変更しない。
3. **曖昧フォールバック回避**: 明示 `copilot` は使えなければ silent fallback せず fail。fallback は `auto` のみ。
   CI / 品質ゲート向けに `HARNESS_AUDIT_STRICT_PROVIDER=1` で fallback を禁止できる。
4. **capability check で原因を区別**: cli_missing / auth / policy / model_unavailable を分けて報告する。
5. **モデルIDを固定しない**: GPT-5.5 のIDはテンプレートに埋め込まず、利用者が `copilot /model` で確認して指定。
6. **codex は予約枠**: 将来の BYOK/OpenAI互換用。現状は明示選択時に exit 3 で明確に fail。

## 代替案と却下理由

- **監査を完全にスクリプト化して existing もCLI(`claude -p`)で回す**: 既存のサブエージェント駆動・
  プラン別モデル設定(`/set-plan`)・フックログと二重管理になり、既定挙動を変えてしまうため却下。
- **Copilot 出力を JSON schema に変換**: 既存レポートが Markdown のため、既存互換を優先しメタは別ファイルにした。
- **MCP 経由で provider 追加**: Third-party MCP 依存を避ける方針のため却下。

## 影響

- 追加: `.harness/audit/*`(scripts + README)、`docs/AUDIT_PROVIDERS.md`、本ADR
- 変更(追記のみ): `.claude/commands/audit.md`、`WORKFLOW.md`、`README.md`、`CLAUDE.md`、`.gitignore`
- 既存テスト・既存監査フローへの破壊的変更なし。
