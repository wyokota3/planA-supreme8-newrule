---
description: specs/status.json から進捗ダッシュボード(dashboard.html)を生成してブラウザで開けるようにする
---

`specs/status.json` を読み、`docs/dashboard.template.html` をベースに、プロジェクトルートの `dashboard.html` を生成してください。

## 手順

1. `specs/status.json` を読み込む。存在しなければ「先に /setup-env を実行してください」と伝えて終了。
2. `docs/dashboard.template.html` を読み込む。
3. テンプレート内の `<script id="status-data" type="application/json"> ... </script>` の**中身だけ**を、`specs/status.json` の内容で置き換える。
   - JSON 内に `_comment` 等の `_` で始まるキーがあれば取り除く(表示に不要)。
   - 可能なら `effort` キーを付与する(`reports/worklog.jsonl` や直近の `reports/effort-*.md` があれば、そこから featureCount / testPassRate / auditPassRate / archProgress / activeDays / limitHits / narrative を埋める)。無ければ `"effort": null` のままでよい。
   - `<script src="./docs/vendor/mermaid.min.js">` の行は**変更しない**(オフライン参照を保つ)。
4. 結果をプロジェクトルートの `dashboard.html` として書き出す(テンプレートは上書きしない)。

## 完了後

- ノード数・機能数・全体進捗% を一行で報告する。
- `start dashboard.html`(Windows)でブラウザで開けることを案内する。
- `docs/vendor/mermaid.min.js` が無い場合は警告し、オフライン版が未取得である旨を伝える。

## 注意

- `dashboard.html` は生成物。手編集しない(次回 /dashboard で上書きされる)。
- 真実の源は常に `specs/status.json`。表示がおかしいときは status.json を直す。
