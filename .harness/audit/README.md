# `.harness/audit/` — 監査 provider ランナー

既存監査(Claude Code の `auditor` サブエージェント)を**壊さずに**、監査に使う
LLM provider / model を差し替え可能にするための薄い実行層。

> **既定では何も変わらない。** `HARNESS_AUDIT_PROVIDER` を設定しなければ、監査は従来どおり
> `/audit` → `auditor` サブエージェントで実行される。このランナーは opt-in。

## 構成

```
.harness/audit/
  run-audit.ps1     provider runner 本体(provider 解決 / strict / auto fallback / exit code / メタログ)
  lib/prompt.ps1    prompt builder(.claude/agents/auditor.md を再利用して監査プロンプトを組み立てる)
  lib/copilot.ps1   copilot provider(capability check / invoke / 出力正規化)
  lib/codex.ps1     codex provider(OpenAI Codex CLI。ChatGPT プラン枠で GPT-5.6 Sol 等を使う)
```

## 使い方

```powershell
pwsh -NoProfile -File .harness/audit/run-audit.ps1 -Feature F-001
```

provider / model は環境変数で選ぶ:

| 環境変数 | 役割 |
| --- | --- |
| `HARNESS_AUDIT_PROVIDER` | `existing`(既定) / `copilot` / `codex` / `claude` / `auto` |
| `HARNESS_AUDIT_MODEL` | provider 共通のモデルID(任意) |
| `HARNESS_AUDIT_COPILOT_MODEL` | copilot 専用モデルID(copilot 時はこちらが優先) |
| `HARNESS_AUDIT_CODEX_MODEL` | codex 専用モデルID(codex 時はこちらが優先。例: `gpt-5.6-sol`) |
| `HARNESS_AUDIT_STRICT_PROVIDER` | `1` で「指定provider不可なら fail。auto は existing に fallback しない」 |

モデル解決の優先順位(copilot / codex 共通の形): `HARNESS_AUDIT_<PROVIDER>_MODEL` > `HARNESS_AUDIT_MODEL` > 未指定(=`--model` を付けない=利用者の既定モデル)。

## exit code(呼び出し側の契約)

| code | 意味 | 呼び出し側の動作 |
| --- | --- | --- |
| `0` | 外部provider(copilot / codex)が監査レポートを生成した | `reports/audit-*.md` を提示 |
| `10` | DELEGATE。既存 `auditor` サブエージェントで実行すべき | サブエージェントを起動(従来フロー) |
| `2` | 指定provider不可 & フォールバック不可(明示指定 or strict) | エラーをそのまま提示して停止 |
| `3` | (予約)未実装provider が明示選択された(現在は該当なし) | エラーを提示して停止 |
| `1` | 使い方/想定外エラー | エラーを提示 |

標準出力の先頭行に機械可読マーカーを出す:
`AUDIT_RUNNER_RESULT: delegate|completed|error ...`

## provider 別の挙動

- **existing / claude** — 既存方式に委譲(exit 10)。現在の挙動を一切変えない。`claude` は既存 Claude Code 監査役の別名。
- **copilot** — `copilot -s --no-ask-user [--model <model>] -p "<audit prompt>"` で監査。capability check に失敗したら **silent fallback せず分かりやすく fail**(exit 2)。
- **codex** — OpenAI Codex CLI で監査: プロンプトを stdin で `codex exec - --sandbox read-only --skip-git-repo-check --color never --ephemeral -o <一時ファイル> [--model <model>]` に渡し、最終応答(--output-last-message)をレポートとして回収する。ChatGPT アカウントログイン(Plus/Pro 等のプラン枠)で動き、API キー不要。capability check(CLI 存在 → `codex login status` → 最小プロンプト疎通)に失敗したら **silent fallback せず分かりやすく fail**(exit 2。原因: cli_missing / auth / cli_outdated / usage_limit / model_unavailable を区別)。
- **auto** — 外部provider を copilot → codex の順に試し、どちらも使えなければ existing へフォールバック(exit 10)。`HARNESS_AUDIT_STRICT_PROVIDER=1` のときは existing にフォールバックせず fail(exit 2)。

## 出力(既存schemaを壊さない)

- 監査レポートは**既存と同じ Markdown** `reports/audit-YYYYMMDD-HHMM-<Feature>.md`。schema は変更しない。
- provider / model / verdict / fallback などの**メタは別ファイル**に出す:
  - `.harness/audit/provider.json` — 実行ごとの provenance
  - `.harness/audit/report.json` — 正規化した結果ポインタ
  - `reports/worklog.jsonl` — 既存ログsinkへ1行追記(`event=audit_provider`)
- これら実行時出力は `.gitignore` 済み(コミットされない)。

## read-only 厳守

外部provider は監査役にファイルを書かせない。copilot にはレポートを **stdout に出力**させ、
codex は **read-only sandbox** で実行して最終応答だけを回収する。ファイル書き込みは
`run-audit.ps1` が行う。監査provider側はリポジトリのファイルを変更しない。

詳細・トラブルシュート: [`../../docs/AUDIT_PROVIDERS.md`](../../docs/AUDIT_PROVIDERS.md)
