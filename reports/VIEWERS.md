# フレームビューア一覧・命名規約・生成手順

監査（2026-07-02）の推奨対応。ビューアはアドホック生成のコミット済み成果物であり
生成スクリプトが存在しないため、本書が「何を・どこから・どう作ったか」の記録を担う。

## 命名規約

```
frame-viewer-<対象>-<データ>.html
```

- **対象**: `supreme` / `baseline` / `3way`（GT・supreme・f_blind の三者比較）
- **データ**: `seal`（coverage の seal split・86 シナリオ）/ `fresh`（独立生成器 g_blind_xl の新分布）
- 旧名称からの改名（2026-07-03）: `frame-viewer.html` → `frame-viewer-supreme-seal.html`、
  `frame-viewer-baseline.html` → `frame-viewer-baseline-seal.html`、
  `frame-viewer-fresh.html` → `frame-viewer-3way-fresh.html`

## 一覧

| ファイル | 内容 | データ | 初出コミット |
|---|---|---|---|
| `frame-viewer-supreme-seal.html` | GT vs pred（考察対象: supreme）。俯瞰レーダー＋層×フレーム正誤グリッド＋f_blind 三者オーバーレイ・層別「循環のみ率」 | seal split 86 シナリオ | 1cf3edb → 8b5e253（視覚版）→ c765ffe（撤回整合版） |
| `frame-viewer-baseline-seal.html` | 同上（考察対象: baseline）。**⚠️ baseline 予測列は全 86 シナリオ・3264 セルで欠測（data-bval="·"）** — 2026-07-03 の考察監査で判明。評価には baseline 実走出力（seal split）を取り込んだ再生成が必要（旧考察の「3者一致」は虚偽につき「判定不能」表記へ置換済み） | 同上（GT / f_blind のみ実データ） | 同系譜 |
| `frame-viewer-3way-fresh.html` | 三者リッチビュー（GT(gt_derive) / supreme / f_blind） | g_blind_xl 110 シナリオ / 879 フレーム | 7ee6fc7 → e09fefa（リッチ版復元） |

baseline リポジトリ側の対応物は `planA-baseline/results/trace/error_explorer.html`
（F-016・`scripts/trace_pipeline.py` が生成。名称は F-016 成果物として固定）。

## データ出所

- **seal 系**: coverage の seal split（86 シナリオ）に対する supreme / baseline の実走出力と GT の突合。
  f_blind ラベルは `N04-scenario-contract` の `experiments/blind-labeler`（規則 f を見ていない独立ラベラ）由来。
- **fresh 系**: `experiments/blind-corpus` の独立生成器 `g_blind_xl`（110 シナリオ / 879 フレーム）の新世界。
  native GT が無いため gt_derive（=参照 f）を新観測に適用して GT 列とした（分析用途・supreme は凍結版）。

## 生成手順（再生成時の規律）

1. 生成はオーケストレーター（Claude セッション）によるアドホック構築（実走出力 JSON を HTML に埋め込む
   自己完結・単一ファイル形式）。専用スクリプトは無い。再生成した場合はコミットメッセージに
   **データ（split・シナリオ数・供給元 run）と日付**を必ず記録する。
2. **ADR 0049 の撤回バナーと「層別 循環のみ率」を必ず維持する**（rule_derived 層の GT 一致は仕様適合で
   あって能力でない、の明示。除去は撤回の再汚染にあたる）。
3. strict ゲート（ADR 0050 `strict_gt_conformance`）を OFF にした出力でビューアを作る場合は、
   タイトルと本文にその旨を明記し、既定 ON の成果物と別ファイル名（例: `-nostrict` サフィックス）にする。
4. **考察（`div.anal`）の規律（2026-07-03 監査で全面書き直し済み）**: 定型文は冒頭の「読み方」ブロック
   1箇所に集約し、各シナリオは (a) 失敗の内訳（真の残差／規約依存／一致 の実数）、(b) 真の残差の
   **全件列挙**（原因タグ【intent天井】【優先順位規約】【変化量閾値規約】【線引き規約】【入力契約限界】
   【実装残差】＋観測値＋対策）、(c) 規約依存の層別件数＋代表例、のみを書く。**件数・列挙はグリッドの
   data-* 属性から機械生成・assert 検証すること**（手書きの件数主張は 2026-07-03 監査で supreme 15.4%・
   fresh 22件の不正確が出た前例あり）。数値主張（TTC 等）はページ内データで検証できるものに限る。
