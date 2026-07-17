---
description: Fable をオーケストレータ(監督役)に据え、重い推論を Opus/Sonnet に動的ルーティングする「オレ流モード」。daemon の全Fableとは逆に、Fableは指揮に専念しコストを抑えつつ品質を出す。
---

引数: $ARGUMENTS （`on` / `off` / `status` のいずれか。未指定なら現在の状態を表示して終了）

## オレ流モード(Oreryu mode)とは

`/daemon-mode`(全力モード)が**全エージェントを `fable` で回す**のに対し、
オレ流モードは **Fable をオーケストレータ(監督役)に固定し、重い推論はサブエージェント側の Opus/Sonnet に振り分ける**。

- **速い監督役**:全体把握・タスク分解・ルーティング・人間への確認は Fable が高速にさばく。Fable は手を動かさない。
- **深い推論は Opus/Sonnet**:実装・監査・仕様レビューといった「推論勝負」の作業は Opus(機械的な作業は Sonnet)に任せる。
- **動的フロー(ダイナミックフロー)**:固定 preset を下限(floor)としつつ、Fable がタスクごとに推論重量を見て opus↔sonnet を昇格/降格する。詳細ルールは `docs/ORERYU_ROUTING.md`。

daemon が「全部 Fable で殴る短期決戦」なら、オレ流は「Fable が指揮し、要所だけ重いモデルを当てる、省力かつ高品質」路線。

## ベースライン preset(下限 floor)

| 役割 | モデル | 意図 |
| --- | --- | --- |
| オーケストレーター(メインセッション。`/model` で手動設定) | fable | 監督・分解・動的ルーティング(速い・全体把握) |
| spec-reviewer | opus | 見落としが最も高コスト=深い推論 |
| test-writer | sonnet | 仕様→テスト変換=機械的 |
| implementer | opus | テストを通す=推論勝負(最重量) |
| auditor | opus | 仕様↔実装の突合=深い検証 |

> これは「下限」。Fable は `docs/ORERYU_ROUTING.md` のルールに従い、タスクごとにこの値から上下させてよい(例:単純CRUD なら implementer を sonnet に降格、opus でも2回詰まったら fable に昇格)。

## モデル名の注意(最初に確認)

フロントマターに書く値は `fable` / `opus` / `sonnet`。ただし **Claude Code がこれらのエイリアスを受理しない場合がある**。
受理されないときは、`/model`(対話)等で確認した**正式なモデルID/エイリアスに置換**すること(実IDは一致するとは限らない)。置換が必要なら、全ファイルで同じ値に揃える。

## `on` のときやること

1. 以下4ファイルのフロントマター `model:` 行を **ベースライン preset** に書き換える:
   - `.claude/agents/spec-reviewer.md` → `opus`
   - `.claude/agents/test-writer.md` → `sonnet`
   - `.claude/agents/implementer.md` → `opus`
   - `.claude/agents/auditor.md` → `opus`
2. `specs/status.json` が存在すれば `oreryu` を `true`、`daemon` を `false` に更新する。**`plan` の値は変更しない**(`off` で復元するため温存する)。無ければスキップ。
3. オーケストレーター(メインセッション)のモデルはこのコマンドでは変えられない。`/model fable` を実行するようユーザーに案内する(**監督役を Fable にするのがこのモードの肝**)。
4. **動的ルーティングを有効化**:このセッション以降、`docs/ORERYU_ROUTING.md` のルールに従う。サブエージェントを呼ぶ**直前**に、そのタスクの推論重量を判定し、必要なら当該エージェントの `model:` を一時的に昇格/降格してから呼ぶ。タスクが終わったら floor に戻す(次のタスクに引きずらない)。昇格/降格したら、その理由を1行でユーザーに伝える。
5. **注意喚起を必ず出す**:「これは Fable を監督役に常駐させ、要所で Opus/fable を使うモードです。全 Fable の `/daemon-mode` ほどではないが、`/set-plan max5` より消費は大きめ。`reports/worklog.jsonl` / `/report-effort` で監視し、戻すときは `/oreryu-mode off`」。

## `off` のときやること

1. `specs/status.json` の `plan` を読む(無ければ `max5` を既定として、念のためユーザーに確認)。
2. `/set-plan` のプリセット表に従って4ファイルの `model:` を**そのプランの値に復元**する:

   | 役割 | pro | max5 | max20 |
   | --- | --- | --- | --- |
   | spec-reviewer | sonnet | opus | opus |
   | test-writer | haiku | sonnet | opus |
   | implementer | sonnet | opus | opus |
   | auditor | sonnet | opus | opus |

3. `specs/status.json` があれば `oreryu` を `false` に更新する(`daemon` は触らない=既に false)。
4. オーケストレーターを `/model <plan の推奨>`(pro=haiku / max5=sonnet / max20=opus)に戻すようユーザーに案内する。

## `status`(または引数なし)のときやること

- 現在のモードを表示:`specs/status.json` の `oreryu` / `daemon` / `plan` を読み、`oreryu` / `daemon` / `plan` のどれが支配状態かを示す(無ければ「未初期化」)。
- 4エージェントが今どの `model:` になっているかを一覧表示。
- `oreryu` が true なら「オレ流モード継続中。Fable が監督、重い推論は Opus/Sonnet に動的ルーティング。`docs/ORERYU_ROUTING.md` のルールが効いている」と添える。メインセッションが `fable` でなければ `/model fable` を促す。

## 他モードとの関係(重要・排他)

- `/oreryu-mode on` / `/daemon-mode on` / `/set-plan` は**互いに排他**。最後に実行したものが支配権を取る。
  - `/oreryu-mode on` は `daemon=false`(全 Fable を解除)にし、`plan` は温存する。
  - `/daemon-mode on` を打つと **oreryu は解除**され、全エージェントが fable になる。
  - `/set-plan` を打つと **oreryu も daemon も解除**され、plan preset に戻る。
- いずれも `specs/status.json` を真実の源にしており、`oreryu` / `daemon` / `plan` のいずれかが現在の支配状態を示す。

## 完了後の報告

- どのエージェントが今どのモデルになったかを一覧で表示。
- `on` の場合:メインセッションへ `/model fable` を案内し、動的ルーティングが有効になったこと、`/oreryu-mode off` での戻し方を明示。
- `off` の場合:復元したプランと、メインセッションへの推奨 `/model` を明示。
