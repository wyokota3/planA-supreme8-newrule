---
description: 全サブエージェントを最上位モデル fable に切り替える全力モード(デーモンモード)。Max5 の5時間/週を最速で消費するので注意。
---

引数: $ARGUMENTS （`on` / `off` / `status` のいずれか。未指定なら現在の状態を表示して終了）

## デーモンモードとは

制限消費を度外視して、**全エージェントを `fable`(最新最上位モデル)で回す全力モード**。
品質最優先・短期決戦向け。`/set-plan` の「役割ごとに節約する」思想とは正反対で、
**Max5 の5時間/週を最速で食い尽くす**点を必ずユーザーに警告すること。

## モデル名の注意(最初に確認)

フロントマターに書く値は `fable` を使う。ただし **Claude Code が `fable` というエイリアスを受理しない場合がある**。
受理されないときは、`/model`(対話)等で確認した**正式なモデルID/エイリアスに置換**すること
(実IDは `fable` と一致するとは限らない)。置換が必要なら、このコマンドの `fable` を1箇所の定数として扱い、全ファイルで同じ値に揃える。

## `on` のときやること

1. 以下4ファイルのフロントマター `model:` 行を **すべて `fable`** に書き換える:
   - `.claude/agents/spec-reviewer.md`
   - `.claude/agents/test-writer.md`
   - `.claude/agents/implementer.md`
   - `.claude/agents/auditor.md`
2. `specs/status.json` が存在すれば `daemon` を `true`、`oreryu` を `false` に更新する(オレ流モードが有効だった場合は解除)。**`plan` の値は変更しない**(`off` で復元するため温存する)。無ければスキップ。
3. オーケストレーター(メインセッション)のモデルはこのコマンドでは変えられない。`/model fable` を実行するようユーザーに案内する。
4. **警告を必ず出す**:「これは Max5 の5時間/週を最速で消費する全力モードです。`reports/worklog.jsonl` / `/report-effort` で消費を監視し、制限に当たったら `/log-limit` で記録、`/daemon-mode off` で即座に戻せます」。

## `off` のときやること

1. `specs/status.json` の `plan` を読む(無ければ `max5` を既定として、念のためユーザーに確認)。
2. `/set-plan` のプリセット表に従って4ファイルの `model:` を**そのプランの値に復元**する:

   | 役割 | pro | max5 | max20 |
   | --- | --- | --- | --- |
   | spec-reviewer | sonnet | opus | opus |
   | test-writer | haiku | sonnet | opus |
   | implementer | sonnet | opus | opus |
   | auditor | sonnet | opus | opus |

3. `specs/status.json` があれば `daemon` を `false` に更新する。
4. オーケストレーターを `/model <plan の推奨>`(pro=haiku / max5=sonnet / max20=opus)に戻すようユーザーに案内する。

## `status`(または引数なし)のときやること

- 現在 `daemon` が on / off か(`specs/status.json` の `daemon` 値。無ければ「未初期化」)。
- 4エージェントが今どの `model:` になっているかを一覧表示。
- on のままなら「全力モード継続中。消費に注意」と添える。

## `/set-plan` / `/oreryu-mode` との関係(重要)

- `/daemon-mode on` は plan より優先される(全役割を `fable` で上書きする)。
- **`/daemon-mode on` と `/oreryu-mode on` は排他**。daemon on にするとオレ流モードは解除される(`oreryu=false`)。逆に `/oreryu-mode on` を打つと daemon は解除される。
- **`/set-plan` を実行すると daemon も oreryu も自動解除される**(plan プリセットが主導権を取り、`daemon=false` / `oreryu=false` になる)。
  そのため `/daemon-mode on` の状態で `/set-plan` を打つと fable は外れる。意図せず外したくない場合は注意するようユーザーに伝える。
- 3つとも `specs/status.json` を真実の源にしており、最後に実行したコマンドの状態(`daemon` / `oreryu` / `plan`)が記録される。
- 全部 Fable は重すぎるが品質は欲しい、という中間が欲しいときは `/oreryu-mode on`(Fable監督 + 重い推論だけ Opus/Sonnet)を検討する。

## 完了後の報告

- どのエージェントが今どのモデルになったかを一覧で表示。
- `on` の場合:メインセッションへ `/model fable` を案内し、5時間/週の消費警告と `/daemon-mode off` での戻し方を明示。
- `off` の場合:復元したプランと、メインセッションへの推奨 `/model` を明示。
