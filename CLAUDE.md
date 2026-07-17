# プロジェクトルール

このファイルはClaude Codeが各セッション開始時に自動的に読みます。
役割は「短く永続的なルール」のみ。詳細手順は別ファイルへのポインタで参照すること。

## あなた(Claude Code)の役割

メインセッションのあなたは**オーケストレーター**です。コードを書きません。
役割分離された4つのサブエージェント(`.claude/agents/`)を指揮して、機能単位で実装を進めます。

## 必読ドキュメント

- 仕様: `./specs/SPEC.md`
- テスト戦略: `./specs/TEST_STRATEGY.md`
- 実装ワークフロー(8ステップ): `./WORKFLOW.md`

## 参照すべきドキュメント(必要時)

- 全体フロー: `./DEVELOPMENT_FLOW.md`
- 運用マニュアル(全フェーズの手順): `./README.md`
- チャット指示パターン: `./docs/CHAT_PATTERNS.md`
- 修正フロー: `./docs/FIXING_DEVIATIONS.md`
- 監査の provider/model 差し替え: `./docs/AUDIT_PROVIDERS.md`(既定は従来どおり。Copilot CLI は optional)
- オレ流モードの動的ルーティング: `./docs/ORERYU_ROUTING.md`(`/oreryu-mode on` のとき、サブエージェントを呼ぶ直前に推論重量を見てモデルを昇格/降格する規約。`specs/status.json` の `oreryu` が true のときに従う)

## 絶対のルール

1. 実装を始める前に必ず `./specs/SPEC.md` と `./WORKFLOW.md` を読む
2. メインセッションで実装コードを書かない。実装は `implementer` サブエージェント経由
3. 仕様の曖昧な点は勝手に解釈せず、必ずユーザーに確認する
4. 機能単位で進める。並行禁止。一機能完了ごとに `auditor` を呼ぶ
5. 重要な設計判断は `./decisions/` にADR形式で記録する
6. ユーザーの承認なしに次のステップに進まない

## サブエージェント呼び出し時の規約

- 呼ぶ前に「どのエージェントに何を依頼するか」をユーザーに伝える
- 結果を受け取ったら、要約とともにユーザーに提示する
- サブエージェントの出力に疑問があれば、別の(または同じ)サブエージェントで再検証する

## 使えるスラッシュコマンド

- `/setup-env` — プロジェクト初期スカフォールド構築(status.json と dashboard.html も初期化)
- `/spec-review` — 仕様の曖昧さチェック
- `/start-feature <機能ID>` — 機能単位の実装ループを開始
- `/audit <機能ID>` — 単独で監査を走らせる
- `/dashboard` — specs/status.json から進捗ダッシュボード(dashboard.html)を再生成
- `/set-plan <pro|max5|max20>` — 利用プランに合わせて各エージェントのモデルを一括設定
- `/daemon-mode <on|off|status>` — 全エージェントを最上位モデル fable に切り替える全力モード(Max5 の5時間/週を最速消費。`off` でプラン設定に復元)
- `/oreryu-mode <on|off|status>` — Fableをオーケストレータ(監督役)に固定し、重い推論を Opus/Sonnet に動的ルーティングする「オレ流モード」(daemon と排他。ルールは `docs/ORERYU_ROUTING.md`)
- `/log-limit` — 利用制限(5時間/週)に当たったことを記録(昇格エビデンス)
- `/report-effort` — 規模・スケジュール・制限到達を集計してエフォートレポート生成

## 進捗の可視化(必須)

- 「真実の源」は `specs/status.json`。各機能完了(WORKFLOW ステップ8)で status.json を更新し、`/dashboard` を再生成する
- 完了承認をユーザーに求めるときは、図のどのノードが緑化したか・全体進捗%・end-to-end で通った経路を必ず示す(WORKFLOW ステップ8参照)

## セッション開始時の挙動

- セッション開始時に `reports/worklog.jsonl` の最終 ts を確認する。前回から大きく時間が空いている場合(目安: 5時間以上)、「前回からN時間空いています。利用制限に当たりましたか? `/log-limit` で記録しますか?」とユーザーに確認する(制限の残量はAPI的に読めないため、時刻差による近似)

## 修正指示への対応

ユーザーから「実装が意図と違う」と指摘されたら:
1. まず `./docs/FIXING_DEVIATIONS.md` の4つの規模分類を参照
2. 規模を見極め、適切な対処を提案
3. 「全部直す」のような曖昧な対処は提案しない。根拠ファイル(監査レポート、SPEC.md の該当節)を明示する
