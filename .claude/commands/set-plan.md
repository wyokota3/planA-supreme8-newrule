---
description: 利用中のClaudeプラン(pro/max5/max20)に合わせて各サブエージェントのモデルを一括設定する
---

引数で渡されたプランに従って、サブエージェントの使用モデルを設定してください。

プラン: $ARGUMENTS （`pro` / `max5` / `max20` のいずれか。未指定や不正なら、現在の `specs/status.json` の `plan` 値を表示して、3択を提示して終了）

## なぜプラン別に設定するのか

全エージェントを Opus で回すと、Pro プランの人は5時間/週の制限を即消費してしまう。一方、見落としが一番高くつくのは**独立した監査役**(spec-reviewer / auditor)なので、節約するときもそこには良いモデルを残す。手を動かす test-writer と、調整役のオーケストレーターから安いモデルに落とす。

## プリセット

| 役割 | pro | max5 | max20 |
| --- | --- | --- | --- |
| オーケストレーター(メインセッション。`/model` で手動設定) | haiku | sonnet | opus |
| spec-reviewer | sonnet | opus | opus |
| test-writer | haiku | sonnet | opus |
| implementer | sonnet | opus | opus |
| auditor | sonnet | opus | opus |

> implementer は推論勝負(テストを通す)なので、pro でも haiku に落とさず sonnet を保つ。安いモデルで失敗を繰り返す方がかえって制限を消費するため。

## やること

1. 引数のプランを判定(`pro`/`max5`/`max20`)。
2. 上表に従って、以下4ファイルのフロントマター `model:` 行を書き換える:
   - `.claude/agents/spec-reviewer.md`
   - `.claude/agents/test-writer.md`
   - `.claude/agents/implementer.md`
   - `.claude/agents/auditor.md`
3. `specs/status.json` が存在すれば、`plan` の値を引数のプランに更新する(無ければスキップ)。
4. `specs/status.json` の `daemon` / `oreryu` が `true` の場合は `false` に戻す(プリセット適用により全力モード/オレ流モードは解除される)。解除したことをユーザーに明示する。
5. オーケストレーター(メインセッション)の推奨モデルを表から伝え、`/model <推奨>` を実行するようユーザーに案内する(メインセッションのモデルはこのコマンドでは変えられないため)。

> `/daemon-mode on`(全エージェント fable の全力モード)や `/oreryu-mode on`(Fable監督 + Opus/Sonnet の動的ルーティング)が有効なときに本コマンドを実行すると、上記4の通り **その設定は解除され**、プリセットのモデルに戻る。維持したい場合は `/set-plan` を実行しないこと。

## 完了後の報告

- 各エージェントが今どのモデルになったかを一覧で表示。
- メインセッションに推奨する `/model` を明示。
- pro の場合:「implementer が2回失敗を続けたら、WORKFLOW.md ステップ6に従って一時的に implementer を一段上げる手もある」と添える。
