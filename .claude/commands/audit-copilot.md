---
description: 指定機能の監査だけを GitHub Copilot CLI 経由の GPT-5.5 で実行する(実装や他工程は Claude のまま)
---

引数の機能IDについて、**監査ステップだけを GitHub Copilot(GPT-5.5)** で実行してください。
実装・テスト・オーケストレーションは従来どおり Claude のまま。監査の「判定役(judge)」だけ別モデルに替えることで、
自己採点バイアスをさらに減らすのが狙いです。

機能ID: $ARGUMENTS

## 実行

provider と model は**環境変数ではなくパラメータで渡す**(セッションの環境変数を汚さない=後続の通常 `/audit` の挙動を変えない):

```powershell
$model = if ($env:HARNESS_AUDIT_GPT_MODEL) { $env:HARNESS_AUDIT_GPT_MODEL } else { "gpt-5.5" }
pwsh -NoProfile -File .harness/audit/run-audit.ps1 -Feature <機能ID> -Provider copilot -Model $model
```

> 明示 `-Provider copilot` はランナー仕様によりフォールバックしない(GPT-5.5 で監査できなければ Claude に落とさず失敗する)ため、strict 指定は不要。

> **モデルIDの確認:** `gpt-5.5` は既定の仮ID。組織で実際に使えるIDは `copilot /model`(対話)で確認し、
> 違っていたら先に `$env:HARNESS_AUDIT_GPT_MODEL="<実ID>"` を設定してから上を実行する。

## exit code での分岐

- **`0`**: 成功。標準出力の `report=<パス>` の監査レポートを読み、サマリ・判定(pass / needs_fix / block)・注意点を提示する
- **`2`**: Copilot / GPT-5.5 が使えない(未ログイン / policy 拒否 / モデル不明)。**標準エラーのメッセージをそのままユーザーに提示して停止**する。
  このコマンドは「GPT-5.5 で監査する」ことが目的なので、**勝手に Claude 監査へ切り替えない**。下の「セットアップ」を案内する
- **その他(`1` / `3`)**: 想定外。メッセージを提示して停止

## セットアップ(初回 / exit 2 のとき)

1. GitHub Copilot CLI をインストールしてログイン(`copilot` を起動して `/login`)
2. 組織の **GitHub Copilot CLI ポリシーが有効**で、GPT-5.5 系モデルにアクセスできること
3. 使えるモデルIDを `copilot /model` で確認し、`$env:HARNESS_AUDIT_GPT_MODEL` に設定する
4. 毎回設定したくなければ、`HARNESS_AUDIT_GPT_MODEL` をシェルのプロファイルか `.claude/settings.json` の env に置いて恒久化する

> Copilot が使えないときに「今回だけ Claude 監査で妥協してよい」なら、代わりに通常の `/audit <機能ID>` を使う。
> 「使えれば Copilot、ダメなら Claude に自動フォールバック」がよいなら `HARNESS_AUDIT_PROVIDER=auto`(strict なし)。

## 監査後

- レポートは `reports/audit-YYYYMMDD-HHMM-<機能ID>.md`(スキーマは Claude 監査と同一)
- provider / model の記録は `.harness/audit/provider.json` に残る。完了報告時に「provider=copilot model=<id>」を一言添える
- 判定に応じて次アクションを提案する(未実装ありなら WORKFLOW ステップ5へ、オーバー実装なら SPEC 追記/削除の判断、など)

---
末尾に「📍現在地 / ✅完了 / 🔍完了条件 / 👉次アクション」ブロックを付ける(CLAUDE.md「応答の締め方」)。
