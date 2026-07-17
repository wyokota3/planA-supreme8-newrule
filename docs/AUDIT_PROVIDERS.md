# 監査 provider の選択(LLM provider / model の差し替え)

このテンプレートの監査(`/audit` → `auditor` サブエージェント)は、**既定では今までどおり Claude Code 上で動く**。
そのうえで、Copilot CLI 経由の GPT-5.5 系などを**使える人だけが**、監査モデルとしてそれを選べるようにしてある。

> **重要:** Copilot / GPT-5.5 は必須ではない(optional)。Copilot CLI が使えない環境でも、
> 既存監査はそのまま動き続ける。組織ポリシーで Copilot CLI を使えない人は、何も設定しなければよい。

## 仕組み(どこに切替が入っているか)

監査は元々「実行スクリプト」ではなく Claude Code の `auditor` サブエージェントで動いている。
そこへ、外部CLIを叩く薄い実行層 `.harness/audit/run-audit.ps1` を**追加**した(opt-in)。

- 既定 / `existing` / `claude`: 従来どおり `auditor` サブエージェントが監査する(挙動は不変)。
- `copilot`: 既存の監査プロンプトを **GitHub Copilot CLI** に渡して監査する。
- `auto`: Copilot が使えれば Copilot、ダメなら既存へ自動フォールバック。

プロンプトは provider ごとに複製していない。`.claude/agents/auditor.md` の本文(役割・規約・**出力形式**)を
再利用し、機能固有のコンテキストだけを足している(`.harness/audit/lib/prompt.ps1`)。

## 環境変数

| 変数 | 既定 | 説明 |
| --- | --- | --- |
| `HARNESS_AUDIT_PROVIDER` | `existing` | `existing` / `copilot` / `codex` / `claude` / `auto` |
| `HARNESS_AUDIT_MODEL` | (なし) | provider 共通のモデルID |
| `HARNESS_AUDIT_COPILOT_MODEL` | (なし) | Copilot 専用モデルID。copilot 時はこちらが優先 |
| `HARNESS_AUDIT_STRICT_PROVIDER` | (なし) | `1` で「指定provider不可なら fail。auto fallback しない」 |

モデル解決の優先順位(copilot): `HARNESS_AUDIT_COPILOT_MODEL` > `HARNESS_AUDIT_MODEL` > **未指定なら `--model` を付けない**(= 利用者の Copilot CLI 既定モデルを尊重)。

> モデルIDをテンプレートに固定していない。GPT-5.5 を使いたい人は、**自分の環境で実際に使えるモデルID**を
> 確認して指定する。実際のIDは `gpt-5.5` とは限らない。`copilot /model`(対話)または `copilot help` で
> 利用可能なモデルIDを確認すること。

## 使い方(PowerShell)

既定(現在の監査方式。何も設定しない):

```powershell
/audit F-001                                  # Claude Code 内
# またはランナー経由:
pwsh -NoProfile -File .harness/audit/run-audit.ps1 -Feature F-001
```

既存providerを明示:

```powershell
$env:HARNESS_AUDIT_PROVIDER="existing"
pwsh -NoProfile -File .harness/audit/run-audit.ps1 -Feature F-001
```

Copilot CLI を使う(既定モデル):

```powershell
$env:HARNESS_AUDIT_PROVIDER="copilot"
pwsh -NoProfile -File .harness/audit/run-audit.ps1 -Feature F-001
```

Copilot CLI + GPT-5.5 系モデルを使う:

```powershell
$env:HARNESS_AUDIT_PROVIDER="copilot"
$env:HARNESS_AUDIT_COPILOT_MODEL="<copilot で利用可能な GPT-5.5 のモデルID>"   # 例。実IDは /model で確認
pwsh -NoProfile -File .harness/audit/run-audit.ps1 -Feature F-001
```

auto(使えれば Copilot、ダメなら既存にフォールバック):

```powershell
$env:HARNESS_AUDIT_PROVIDER="auto"
pwsh -NoProfile -File .harness/audit/run-audit.ps1 -Feature F-001
```

厳密に Copilot を要求(フォールバックさせない。CI / 品質ゲート向け):

```powershell
$env:HARNESS_AUDIT_PROVIDER="copilot"
$env:HARNESS_AUDIT_STRICT_PROVIDER="1"
pwsh -NoProfile -File .harness/audit/run-audit.ps1 -Feature F-001
```

`/audit F-XXX` からこのランナーを使う場合の分岐は `.claude/commands/audit.md` を参照(provider が未指定/existing/claude のときは従来どおりサブエージェントが動く)。

## exit code

| code | 意味 |
| --- | --- |
| `0` | 外部provider(copilot)が監査レポートを生成 |
| `10` | DELEGATE(既存 `auditor` サブエージェントで実行すべき。existing / claude / auto-fallback) |
| `2` | 指定provider不可 & フォールバック不可(明示copilot or strict)→ 失敗 |
| `3` | 未実装provider(codex)が明示選択された → 失敗 |
| `1` | 使い方/想定外エラー |

## capability check と失敗の区別

Copilot provider は実行前に軽量な事前チェックを行い、原因を区別して報告する:

1. `copilot` コマンドが存在するか
2. `copilot -s --no-ask-user -p "Respond with just: OK"` が成功するか(未ログイン / policy 拒否を区別)
3. モデル指定がある場合、そのモデルで最小プロンプトが成功するか

代表的なエラーメッセージ:

```text
Copilot audit provider is selected, but Copilot CLI is not available.
Install and login with GitHub Copilot CLI, or set HARNESS_AUDIT_PROVIDER=existing.
```

```text
Copilot audit provider is selected, but model access was denied by Copilot policy.
Check your Organization Copilot CLI policy and model availability, or unset HARNESS_AUDIT_COPILOT_MODEL.
```

```text
Copilot audit provider is selected, but the requested model is unavailable.
Run `copilot /model` interactively and set HARNESS_AUDIT_COPILOT_MODEL to an available model ID.
```

## ログ(実行ごとに必ず残る)

| ファイル | 内容 |
| --- | --- |
| `.harness/audit/provider.json` | selected_provider / selected_model / model_source / model_explicit / strict / fallback_used / fallback_reason / policy_denied / exit_code |
| `.harness/audit/report.json` | provider / model / verdict / report_path(正規化した結果ポインタ) |
| `reports/worklog.jsonl` | 既存ログsinkへ `event=audit_provider` を1行追記 |

これら実行時出力は `.gitignore` 済み。監査レポート本体(`reports/audit-*.md`)は従来どおり蓄積・コミットする。

## 互換性(既存を壊さない)

- 監査レポートは**既存と同じ Markdown schema**。`reports/audit-YYYYMMDD-HHMM-<Feature>.md` に出す。
- 既存レポートには `provider` / `model` 欄が無いため、メタ情報は**別ファイル**(`provider.json` / `report.json`)に出す。
- 既定挙動(provider 未指定)は現在の監査方式のまま。エントリポイント・出力形式・ログ保存先を変えない。

## 注意事項

- Copilot CLI を使うには、**GitHub Copilot CLI policy が Organization で有効**である必要がある。
- `/login` に成功しても、`/model` や `copilot -p` が**policy で拒否**される場合がある。
- 利用可能なモデルIDは**組織契約やポリシーに依存**する。
- このテンプレートは **Copilot を必須としない**。Copilot を使えない人は既存provider のまま監査できる。
- GPT-5.5 を使いたい人は、**実際のモデルIDを自分の環境で確認して**設定する(`copilot /model` / `copilot help`)。
- 監査役は **read-only** 前提。Copilot provider はレポートを stdout に出すだけで、リポジトリのファイルは変更しない。
