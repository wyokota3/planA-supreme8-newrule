---
description: 開発の規模・スケジュール・制限到達を集計し、プラン昇格の根拠になるエフォートレポートを生成する
---

`reports/worklog.jsonl` と `git log` と `specs/status.json` を集計して、`reports/effort-YYYYMMDD.md` を生成してください。

## 目的

「どれくらいの規模を、どんなスケジュールで作り、どこで制限に当たったか」を可視化する。Pro プランの人が「だから Max に上げてほしい」と言うときのエビデンスになる。あわせて「ここまで頑張った」成果も示す。

## 集計内容

### 1. 規模
- 完了機能数 / 全機能数(status.json)
- 変更ファイル数・テストファイル数(リポジトリを走査)
- LOC 差分(`git log` / `git diff --stat` から概算)

### 2. スケジュール
- 開始日〜直近の作業日、稼働日数(worklog の ts レンジ)
- 機能ごとの所要時間(status.json の startedAt / completedAt、無ければ worklog のイベント間隔から概算)

### 3. 制限到達(最重要エビデンス)
- `worklog.jsonl` の `event:"limit_hit"` を集計:回数・発生時刻・種類(5h/weekly)・そのとき止まっていた機能/ステップ
- 「制限による待ち時間の累計」を概算し、**「Max プランなら、この待ち累計 約X時間が発生しなかった」**というナラティブを添える

### 4. 頑張った統計(成果)
- 完了機能数・テスト通過率・監査パス率(reports/ の監査レポートから)
- アーキテクチャ進捗%(status.json の done ノード割合)
- 使用モデルの内訳(worklog の model 集計)

## 出力

- `reports/effort-YYYYMMDD.md` に上記をまとめる。
- 同じ集計を `specs/status.json` の表示用に使えるよう、`/dashboard` 実行時に拾える形(featureCount / testPassRate / auditPassRate / archProgress / activeDays / limitHits / narrative)も併記する。
- 最後に `/dashboard` を実行してダッシュボードのエフォート欄にも反映する。

## 完了後

- レポートのサマリ(規模・制限到達回数・「Maxなら短縮できた時間」)を3〜5行で報告する。
