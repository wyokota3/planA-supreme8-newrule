---
description: 指定機能の監査だけを OpenAI Codex CLI 経由の GPT-5.6 Sol(ChatGPT Plus/Pro プラン)で実行する(実装や他工程は Claude のまま)
---

引数の機能IDについて、**監査ステップだけを OpenAI Codex CLI(GPT-5.6 Sol)** で実行してください。
実装・テスト・オーケストレーションは従来どおり Claude のまま。監査の「判定役(judge)」だけ別勢力(OpenAI)のモデルに
替えることで、自己採点バイアスをさらに減らすのが狙いです。

GitHub Copilot 経由ではありません。**ChatGPT アカウント(Plus/Pro 等)のプラン枠**で動くため、
API キーも従量課金も不要です(headless 実行もプランの 5 時間ローリングウィンドウを消費します)。

機能ID: $ARGUMENTS

## 実行

provider と model は**環境変数ではなくパラメータで渡す**(セッションの環境変数を汚さない=後続の通常 `/audit` の挙動を変えない):

```powershell
$model = if ($env:HARNESS_AUDIT_CODEX_MODEL) { $env:HARNESS_AUDIT_CODEX_MODEL } else { "gpt-5.6-sol" }
pwsh -NoProfile -File .harness/audit/run-audit.ps1 -Feature <機能ID> -Provider codex -Model $model
```

> 明示 `-Provider codex` はランナー仕様によりフォールバックしない(GPT-5.6 Sol で監査できなければ Claude に落とさず失敗する)ため、strict 指定は不要。

> **モデルIDについて:** 既定は `gpt-5.6-sol`(GPT-5.6 の最上位。`gpt-5.6` は Sol へのエイリアス)。
> 別のモデル(gpt-5.6-terra / luna 等)を使いたい場合は `$env:HARNESS_AUDIT_CODEX_MODEL="<モデルID>"` を設定してから実行する。

## exit code での分岐

- **`0`**: 成功。標準出力の `report=<パス>` の監査レポートを読み、サマリ・判定(pass / needs_fix / block)・注意点を提示する
- **`2`**: Codex / GPT-5.6 Sol が使えない(CLI 未導入 / 未ログイン / CLI が古い / 利用枠切れ / モデル不明)。**標準エラーのメッセージをそのままユーザーに提示して停止**する。
  このコマンドは「GPT-5.6 Sol で監査する」ことが目的なので、**勝手に Claude 監査へ切り替えない**。下の「セットアップ」を案内する
- **その他(`1` / `3`)**: 想定外。メッセージを提示して停止

## セットアップ(初回 / exit 2 のとき)

1. Codex CLI をインストール: `npm install -g @openai/codex@latest`
   (**gpt-5.6-sol は新しめの CLI が必要**。古いと「requires a newer version of Codex」で失敗する → `@latest` で更新)
2. ログイン: `codex login`(ブラウザが開くので **ChatGPT アカウント**でサインイン。Plus/Pro/Business プランで Codex が使える)
3. 疎通確認: `codex exec --sandbox read-only --skip-git-repo-check -m gpt-5.6-sol "Respond with just: OK"`
4. `usage_limit` で失敗する場合は ChatGPT プランの 5 時間ウィンドウが切れている。回復を待つか、今回は通常の `/audit` を使う

> Codex が使えないときに「今回だけ Claude 監査で妥協してよい」なら、代わりに通常の `/audit <機能ID>` を使う。
> 「使えれば外部モデル(copilot → codex の順)、ダメなら Claude に自動フォールバック」がよいなら `HARNESS_AUDIT_PROVIDER=auto`(strict なし)。

## 監査後

- レポートは `reports/audit-YYYYMMDD-HHMM-<機能ID>.md`(スキーマは Claude 監査と同一)
- provider / model の記録は `.harness/audit/provider.json` に残る。完了報告時に「provider=codex model=<id>」を一言添える
- 判定に応じて次アクションを提案する(未実装ありなら WORKFLOW ステップ5へ、オーバー実装なら SPEC 追記/削除の判断、など)

---
末尾に「📍現在地 / ✅完了 / 🔍完了条件 / 👉次アクション」ブロックを付ける(CLAUDE.md「応答の締め方」)。
