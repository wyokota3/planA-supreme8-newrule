---
description: 指定した機能IDについて、auditor サブエージェントで単独監査を実行する
---

引数として渡された機能ID(例: F-001)について監査を実行してください。

機能ID: $ARGUMENTS

## 監査 provider の決定(最初に行う)

監査に使う LLM provider は環境変数 `HARNESS_AUDIT_PROVIDER` で切り替えられる(既定は `existing`)。
詳細は `docs/AUDIT_PROVIDERS.md` と `.harness/audit/README.md` を参照。

1. `$env:HARNESS_AUDIT_PROVIDER` を確認する。
2. **未指定 / `existing` / `claude` の場合**: 下の「依頼内容」のとおり、従来どおり `auditor` サブエージェントを呼んで監査する(現在の挙動を変えない)。ランナーを使う必要はない。
3. **`copilot` / `codex` / `auto` の場合**: 次のランナーを実行し、exit code で分岐する。

   ```powershell
   pwsh -NoProfile -File .harness/audit/run-audit.ps1 -Feature <機能ID>
   ```

   - exit `0`: 外部provider(copilot)が監査レポートを `reports/audit-*.md` に生成済み。標準出力の `report=` パスのレポートを読み、サマリと注意点を提示する。
   - exit `10`: DELEGATE。**下の「依頼内容」のとおり `auditor` サブエージェントを呼んで監査する**(existing への委譲 / auto のフォールバック)。
   - exit `2` / `3`: provider が使えない。標準エラーのメッセージを**そのままユーザーに提示して停止**する(勝手に provider を変えない)。`auto` の場合は exit 10 になるのでここには来ない。

> どの provider を使ったか・モデル・フォールバック有無は `.harness/audit/provider.json` に記録される。完了報告時に provider と model を一言添える。

## 依頼内容

auditor に以下を渡す:

- `./specs/SPEC.md` の該当機能の節
- 該当機能を実装しているコード(該当ファイルを Grep で特定して渡す)
- 関連するテストコード `./tests/`

## 期待する出力

- `./reports/audit-YYYYMMDD-HHMM-{機能ID}.md` に監査レポートが保存される
- 監査レポートのサマリと、特に注意すべき箇所を私に提示する

## 監査後のアクション提案

監査結果に応じて、以下のいずれかを私に提案してください:

- 未実装項目がある場合: 該当機能で WORKFLOW のステップ5(実装)に戻る
- オーバー実装がある場合: 削除すべきか、SPEC.md に追記すべきかの判断を仰ぐ
- テストカバレッジ不足: ステップ2(テスト設計)に戻る
- 問題なし: 次の機能に進む承認を仰ぐ
