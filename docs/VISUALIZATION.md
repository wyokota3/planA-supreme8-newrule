# 可視化とエフォートログ

このテンプレートは「何がどこまでできたか」を直感的に見えるようにし、開発の規模・スケジュール・制限到達を記録する仕組みを持つ。

## 3層構造(可視化)

| 層 | ファイル | 役割 | 誰が触るか |
| --- | --- | --- | --- |
| 真実の源(機械可読) | `specs/status.json` | 機能・コンポーネント・データフロー・状態・実装箇所の唯一の正 | オーケストレーターが WORKFLOW ステップ8で更新 |
| 人が見る(直感) | `dashboard.html` | ブラウザで開く進捗ダッシュボード(オフライン動作) | `/dashboard` が生成。手編集しない |
| git差分(履歴) | `specs/ARCHITECTURE.md` | Mermaid のアーキテクチャ図。レビュー・履歴用 | フェーズ1で生成 |

### パイプライン

```
フェーズ1(外部チャット)
  └─ ARCHITECTURE.md(Mermaid図)を生成
        ↓
/setup-env
  └─ SPEC.md + ARCHITECTURE.md → specs/status.json を生成
        ↓
/dashboard
  └─ status.json + docs/dashboard.template.html → dashboard.html を生成
        ↓
各機能完了(WORKFLOW ステップ8)
  └─ status.json を更新 → /dashboard で再生成(ノードが緑化)
```

ポイント: **フェーズ1で描いた設計図が、そのまま実装の進捗マップに育つ**。図のノードIDと status.json の `nodes[].id` を一致させること。

### dashboard.html を開く

```powershell
start dashboard.html
```

ノードをクリックすると、担当機能・実装ファイル・監査レポートが右パネルに出る。完了ノードは緑、作業中は黄、未着手は灰。

### オフライン動作

`dashboard.html` は描画に mermaid を使うが、`docs/vendor/mermaid.min.js` をローカル参照するため**インターネット接続不要**。社内/オフライン環境でもそのまま開ける。`docs/vendor/mermaid.min.js` はリポジトリに同梱済み。

> 万一 vendor ファイルが欠けている場合は、`Invoke-WebRequest -Uri "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js" -OutFile "docs/vendor/mermaid.min.js"` で取得し直せる(取得時のみネット必要)。

## プラン別モデル設定

全エージェントを Opus で回すと Pro プランの制限を即消費する。`/set-plan <pro|max5|max20>` で、プランに応じて各サブエージェントのモデルを一括設定する。詳細は `.claude/commands/set-plan.md` のプリセット表を参照。

- 既定は `max5`(reviewer系=Opus / 実装系=Sonnet)。
- `pro` は test-writer とオーケストレーターを Haiku に落とし、独立監査役(spec-reviewer/auditor)と implementer は Sonnet を保つ。

`/set-plan` の固定preset とは別に、消費を度外視した全力モード `/daemon-mode on`(全エージェント fable)と、その中間の `/oreryu-mode on`(Fableを監督役に固定し、重い推論だけ Opus/Sonnet に動的ルーティング)がある。3つは互いに排他で、状態は `specs/status.json` の `plan` / `daemon` / `oreryu` に記録される。オレ流モードの動的ルーティング規約は `docs/ORERYU_ROUTING.md`。

## エフォートログ(昇格エビデンス)

### worklog

`reports/worklog.jsonl` に、サブエージェント起動/終了・セッション終了・制限到達が1行JSONで蓄積される。

- サブエージェント起動/終了・セッション終了は**フック**で自動記録(下記セットアップ)。
- 利用制限(5時間/週)に当たったら `/log-limit` で記録する(自動検知はできないため手動)。

### フックのセットアップ(自動ログを有効化する)

自動ログはフックで実現する。フックは clone した人の環境で**スクリプトを自動実行する**ため、各自が明示的に有効化する方式にしている。`.claude/settings.json` に以下を追加する(`update-config` スキル、または手動編集):

```json
{
  "hooks": {
    "PreToolUse": [
      { "matcher": "Task",
        "hooks": [ { "type": "command", "command": "pwsh -NoProfile -File .claude/hooks/log-event.ps1 subagent_start" } ] }
    ],
    "SubagentStop": [
      { "hooks": [ { "type": "command", "command": "pwsh -NoProfile -File .claude/hooks/log-event.ps1 subagent_stop" } ] }
    ],
    "Stop": [
      { "hooks": [ { "type": "command", "command": "pwsh -NoProfile -File .claude/hooks/log-event.ps1 session_stop" } ] }
    ]
  }
}
```

ロガー本体は `.claude/hooks/log-event.ps1`(同梱済み)。取得できないフィールドは空で記録され、ログ失敗で本来の作業は止めない設計。フックを設定しなくても `/log-limit` と `/report-effort` の手動記録は動く。

### レポート生成

`/report-effort` で `worklog.jsonl` + `git log` + `status.json` を集計し、`reports/effort-YYYYMMDD.md` を生成する:

- 規模(機能数・ファイル数・LOC差分)
- スケジュール(稼働日数・機能ごとの所要時間)
- 制限到達(回数・時刻・「Maxなら短縮できた累計時間」)
- 頑張った統計(完了機能数・テスト通過率・監査パス率・アーキ進捗%)

集計結果はダッシュボードのエフォート欄にも反映される。
