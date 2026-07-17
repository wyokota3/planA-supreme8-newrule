# オレ流モードの動的ルーティング(ダイナミックフロー)

`/oreryu-mode on` のとき、オーケストレーター(監督役の Fable)が従うルーティング規約。
**ベースライン preset を下限(floor)**としつつ、Fable が**タスクごとに**推論重量を見て、サブエージェントのモデルを昇格/降格する。

> このモードの全体像・on/off の手順は `.claude/commands/oreryu-mode.md` を参照。ここは「動的に上下させるときの判断ルール」だけを定める。

## 大原則

1. **Fable は手を動かさない**。コードを書くのは implementer、テストは test-writer、レビュー/監査は専門エージェント。Fable は分解・ルーティング・統合・人間への確認に専念する。
2. **floor を下回らない**。下表の floor 未満には落とさない(品質の床)。
3. **昇格/降格したら必ず1行で理由を述べる**。例:「単純CRUD なので implementer を sonnet に降格」。透明性のため。
4. **判定は呼ぶ直前、復帰は呼んだ直後**。サブエージェントを呼ぶ直前に、そのタスク固有の重量を見て当該エージェントの `model:` フロントマターを書き換えてから呼ぶ。タスクが終わったら floor に戻す(次のタスクに引きずらない)。

## ベースライン(floor)と上下のレンジ

| 役割 | floor | 降格先(軽いタスク) | 昇格先(重いタスク) |
| --- | --- | --- | --- |
| spec-reviewer | opus | sonnet(自明な小機能) | fable(全体設計に関わる仕様の要) |
| test-writer | sonnet | (据え置き) | opus(境界・並行・異常系が多い) |
| implementer | opus | sonnet(単純CRUD/定型) | fable(2回詰まった難所) |
| auditor | opus | sonnet(自明な小機能) | fable(安全性/整合性が致命的な機能) |

> オーケストレーター(メインセッション)は常に fable。これは「監督役」であり、上表の対象外。`/model fable` で設定する。

## 推論重量の判定ヒント(何を見て決めるか)

**重い(昇格を検討)**:

- 仕様にアルゴリズム / 状態機械 / 並行処理 / 数値計算が絡む
- 受け入れ条件が多い・相互依存している
- 過去にこの機能・周辺で監査指摘や手戻りがあった
- WORKFLOW ステップ6で implementer が**2回失敗**した(→ 3回目の前に fable へ昇格。WORKFLOW.md の昇格提案の Oreryu 版)
- 安全性・データ整合性・課金など、失敗コストが高い

**軽い(降格を検討)**:

- 単純な CRUD・定型的な入出力・設定読み込み等
- 受け入れ条件が少なく独立している
- 既存パターンの横展開(類似実装がすでにある)

迷ったら floor を使う。**降格は保守的に、昇格は必要なときに**。

## WORKFLOW.md との接続

- **ステップ2(テスト設計)**:境界 / 並行 / 異常系が多い機能なら test-writer を opus に昇格。
- **ステップ5(実装)**:機能の重量で implementer を sonnet↔opus。
- **ステップ6(再実行)**:2回失敗が続いたら、3回目の前に implementer を **fable** に一時昇格(WORKFLOW.md の「モデル昇格を提案」の Oreryu 版。floor がすでに opus なので、昇格先は fable)。突破したら opus(floor)に戻す。
- **ステップ7(監査)**:失敗コストが高い機能は auditor を fable に昇格、自明な小機能は sonnet に降格。

## 消費の目安

- 全 Fable の `/daemon-mode` よりは軽いが、`/set-plan max5` よりは重い(implementer / auditor / spec-reviewer が常時 opus 以上、要所で fable)。
- 監視は `reports/worklog.jsonl` / `/report-effort`。制限に当たったら `/log-limit`、戻すなら `/oreryu-mode off`。

## なぜこの設計か(daemon との対比)

| | daemon(全力モード) | oreryu(オレ流モード) |
| --- | --- | --- |
| オーケストレーター | fable | fable |
| サブエージェント | 全部 fable | 重量級 opus / 機械的 sonnet(動的に上下) |
| 思想 | 全部 Fable で殴る短期決戦 | Fable が指揮、要所だけ重いモデル |
| 消費 | 最速で食い尽くす | daemon より軽く、max5 より重い |
| 向く場面 | ここぞの難機能を一気に | 品質は欲しいが daemon は重すぎるとき |
