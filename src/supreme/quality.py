"""F-011: Quality regime 判定規則（quality）。

supreme 独自の quality_regime 判定規則。入力 (h_q, vol) を v1.4 統制語彙の
3クラス {GOOD, DEGRADED, BLOCK} に写す純関数を供給する。h_q/vol の生成
(観測式+HGF)は F-011 スコープ外の上流共有基盤であり、本モジュールでは扱わない
(ADR 0014 決定1)。

契約の最終根拠は specs/SPEC.md「F-011」節、decisions/0014-f011-quality-recalibration.md
(手法の正・計測根拠)、decisions/0006(v1.4 語彙)/0013(quality=ルール改良)、
および tests/test_F011_*.py。

判定規則(ADR 0014 決定3・優先順位チェーン):
  1) h_q < 0.25                  → BLOCK     # 旧 BLOCK
  2) h_q < 0.40 ∧ vol > 0.05     → BLOCK     # 旧 早期BLOCK(本データ不作動・構造保持)
  3) h_q < 0.55                  → BLOCK     # 旧 DEGRADED → v1.4 BLOCK
  4) h_q ≥ 0.93 ∧ vol < 0.01     → GOOD      # 旧 GOOD・再較正 0.94→0.93
  5) その他                       → DEGRADED  # 旧 PASS → v1.4 DEGRADED

決定的(乱数・時刻なし)な純関数。入力範囲外(h_q∉[0,1] 等)の特別扱いは
持たない(契約に明文なし・ADR 0014 スコープ外)。本モジュールは stdlib のみに
依存し、datagov/sealset/augment/guard/harness を改修しない。
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# v1.4 統制語彙(ADR 0006 順位シフト後)のラベル定数。値は自身の文字列。
# ---------------------------------------------------------------------------

GOOD = "GOOD"
DEGRADED = "DEGRADED"
BLOCK = "BLOCK"


def classify(h_q, vol) -> str:
    """(h_q, vol) を v1.4 quality_regime ラベルに分類する(ADR 0014 決定3)。

    優先順位チェーンを上から評価し、最初に該当した規則のラベルを返す純関数。
    branch2(vol>0.05)・GOOD ゲートの vol<0.01 は本データでは不作動だが、
    faithfulness のため規則として保持する(ADR 0014 決定2・決定3)。

    境界(テスト契約):
      h_q=0.55          → DEGRADED  (branch3 は厳密 `<`・0.55 ちょうどは抜ける)
      h_q=0.549         → BLOCK     (branch3)
      h_q=0.93, vol<0.01→ GOOD      (再較正 0.94→0.93・ゲート下端)
      h_q=0.929         → DEGRADED  (GOOD ゲート直下)
      h_q≥0.93, vol≥0.01→ DEGRADED  (vol<0.01 を外す)
    """
    if h_q < 0.25:
        return BLOCK
    if h_q < 0.40 and vol > 0.05:
        return BLOCK
    if h_q < 0.55:
        return BLOCK
    if h_q >= 0.93 and vol < 0.01:
        return GOOD
    return DEGRADED
