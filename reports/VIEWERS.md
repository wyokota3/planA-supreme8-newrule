# フレームビューア一覧・命名規約・生成手順

監査（2026-07-02）の推奨対応。ビューアはアドホック生成のコミット済み成果物であり
生成スクリプトが存在しないため、本書が「何を・どこから・どう作ったか」の記録を担う。

## 命名規約

```
frame-viewer-<対象>-<データ>.html
```

- **対象**: `supreme` / `supreme8` / `baseline` / `3way`（GT・supreme・f_blind の三者比較）
- **データ**: `seal`（coverage の seal split・86 シナリオ）/ `fresh`（独立生成器 g_blind_xl の新分布）/
  `situations`（world-first 生成の能力評価土俵 situations_v1・別土俵）
- 旧名称からの改名（2026-07-03）: `frame-viewer.html` → `frame-viewer-supreme-seal.html`、
  `frame-viewer-baseline.html` → `frame-viewer-baseline-seal.html`、
  `frame-viewer-fresh.html` → `frame-viewer-3way-fresh.html`

### strict サフィックスの扱い（重要）

生成手順 §3 のとおり strict ゲート（ADR 0050 `strict_gt_conformance`）を **OFF** にした出力は原則
`-nostrict` サフィックスで既定 ON 成果物と区別する。ただし **situations 系は strict OFF が正規実行**
（能力評価は循環回避のため strict OFF 必須・ADR 0049/0050）であり、ON 版という対概念が存在しない。
よって situations 系ビューアには `-nostrict` サフィックスを付けず、代わりに **ページ冒頭バナーで
「strict OFF が正規・coverage 系と別土俵」を明示する**ことを必須とする。

## 一覧

| ファイル | 内容 | データ | 初出コミット |
|---|---|---|---|
| `frame-viewer-supreme-seal.html` | GT vs pred（考察対象: supreme）。俯瞰レーダー＋層×フレーム正誤グリッド＋f_blind 三者オーバーレイ・層別「循環のみ率」 | seal split 86 シナリオ | 1cf3edb → 8b5e253（視覚版）→ c765ffe（撤回整合版） |
| `frame-viewer-baseline-seal.html` | 同上（考察対象: baseline）。**⚠️ baseline 予測列は全 86 シナリオ・3264 セルで欠測（data-bval="·"）** — 2026-07-03 の考察監査で判明。評価には baseline 実走出力（seal split）を取り込んだ再生成が必要（旧考察の「3者一致」は虚偽につき「判定不能」表記へ置換済み） | 同上（GT / f_blind のみ実データ） | 同系譜 |
| `frame-viewer-3way-fresh.html` | 三者リッチビュー（GT(gt_derive) / supreme / f_blind） | g_blind_xl 110 シナリオ / 879 フレーム | 7ee6fc7 → e09fefa（リッチ版復元） |
| `frame-viewer-supreme8-situations.html` | GT vs pred（supreme8/NeuPSL・N3 レシピ）。suite/pooled KPI ＋ 8層×フレーム正誤グリッド（235 シナリオ）＋ 契約違反 5 件の rejection カード。**専用生成器あり** | situations_v1 eval / 非違反 235 シナリオ・4,057 フレーム（strict OFF） | feat/situations-v1-eval（本コミット） |

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

## supreme8 situations_v1 ビューア（F-015・別土俵・専用生成器あり）

seal/fresh 系のアドホック生成とは異なり、`frame-viewer-supreme8-situations.html` には
**コミット済みの専用生成器**があり、数値は全て機械計算・assert 検証される。

- **生成器**: `reports/situations_v1-eval-20260722/build_frame_viewer.py`
  （標準ライブラリのみ・supreme エンジンは import しない）。
- **入力**: `reports/situations_v1-eval-20260722/frames-N3.json`（`dump_frames.py` の出力。
  N3 手配線レシピの enumeration/preflight/prepare_snaps/gt_view/fit と全く同じコードパスを再利用し、
  スキーマ `{meta, scenarios:{sid:{suite, motif, frames:[[ts, gt8, pred8], ...]}}, violations:[...]}` で出力）＋
  `results.json`（公式測定値）。
- **機械生成数値の規律**: ページに出る数値・件数・グリッドは全て生成器が frames-N3.json / results.json から
  計算し埋め込む（**手書き数値は禁止**）。グリッドセルは match=dim green+✓ / mismatch=red+✗+pred 値表示
  （`data-gt`/`data-pred` ＋ ツールチップ `pred → GT`）。
- **INTEGRITY ASSERTION**: frames から再計算した pooled 8 層 acc（層別・overall）が results.json の
  N3 pooled と 1e-9 以内で一致することを assert（不一致なら停止・数値を丸めない）。per-suite overall も同様に照合。
  ビルド時に **235 シナリオ block・5 rejection カード・セル数 == 4,057×8** と出力サイズ <7MB を assert する。
- **strict OFF が正規 → `-nostrict` 適用外**: situations 系は strict OFF が正規実行（ADR 0049/0050）。
  よってサフィックスは付けず、**バナーで「strict OFF が正規・coverage 系と別土俵・測定日・engine/data HEAD」を明示**する（必須）。
- **provenance**: system supreme8 / config N3 / strict false /
  data HEAD `079e430952cdf3f5b784dd2adecd6b7a43ef5462`（otokankyo-scenario-contract @ situations-v1-physics）/
  engine HEAD（results.json N3）`6928408990c2ce5350fcbad6fee91fa4cdf7eb0f`（supreme8 @ feat/situations-v1-eval）/ 測定日 2026-07-22。
- **再生成**:
  ```
  python reports/situations_v1-eval-20260722/dump_frames.py         # frames-N3.json 再生成
  python reports/situations_v1-eval-20260722/build_frame_viewer.py  # 本ビューア再生成
  ```

## アーキテクチャ解説ページ

`docs/architecture-explainer.html` は supreme8 の設計解説（ビューアではない）。クリック可能な mermaid 俯瞰図
（`docs/vendor/mermaid.min.js` をローカル参照・dashboard.html パターン）＋ 8 層対応表 ＋ 本来型 NeuPSL の 3 要素図解 ＋
学習レシピ ＋ s2→s8 系譜 ＋ situations_v1 の KPI で構成。**表示数値は全てページ内埋め込みデータから JS 計算**
（手書き数値なし）。situations_v1 の KPI には coverage 系との比較禁止バナーを付す。
