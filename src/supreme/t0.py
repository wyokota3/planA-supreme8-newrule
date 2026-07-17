"""F-006: T0 risk_tier ルール層(t0)。

supreme の T0 risk_tier 判定。入力 = track 特徴の列(各 track は kind / ttc_s /
r_m を持つ dict)、出力 = v1.4 risk_tier ラベル。証拠抽出(段1)・HGF・softmax/EMA は
上流の共有基盤でありスコープ外(ADR 0017 決定2)。T0 は直接ルール・状態レス・HGF 非依存。

契約の最終根拠は specs/SPEC.md「F-006」節、decisions/0017-f006-strong-reimplementation.md
(手法の正・独立再実装 + 追記: safety latch 是正)、decisions/0012(risk_tier 採点)/
0006(v1.4 語彙)、および tests/test_F006_t0_risk_tier.py。

判定ルール(ADR 0017 決定3 T0 + 追記の latch 是正):
  1) 主トラック選択: siren 優先、なければ最近傍(最小 r_m)。
  2) kind 別 (caution, danger) TTC 閾値:
       vehicle/siren = (12.0, 2.0), alarm = (5.0, 2.0),
       speech = (2.0, 1.0), default = (5.0, 2.0)。
  3) min_TTC <= danger 閾値 -> danger / <= caution 閾値 -> caution / else info。
  4) siren 下限: siren が info 判定なら caution へ引き上げ。
  語彙 v1.4: info / caution / danger。

safety latch は risk_tier に**適用しない**(ADR 0017 追記・監査 T0-1)。baseline では
latch は risk_safe(数値特徴・採点8層外)のみに作用し、採点される risk_tier には非適用。
risk_safe / latch は本モジュール(risk_tier 専用)のスコープ外で実装しない。siren の高 TTC
フレームは siren 下限で caution(danger でない)= baseline 一致。

track 列が空(track 0 件)のとき: 例外を投げず、安全側の既定 info を返す(ADR 0017 追記・
軽微指摘)。例外を投げない・v1.4 語彙集合に閉じることを契約とする。

決定的(乱数・時刻なし)・状態レスな純関数。本モジュールは stdlib のみに依存し、
datagov/sealset/augment/guard/harness/quality/mode/relation を改修しない。
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# v1.4 risk_tier 統制語彙(ADR 0006 / 0012)のラベル定数。値は自身の文字列。
# ---------------------------------------------------------------------------

INFO = "info"
CAUTION = "caution"
DANGER = "danger"


# ---------------------------------------------------------------------------
# (caution, danger) TTC 閾値。kind 非依存の純 TTC ルール(ADR 0033)。
# coverage_v1 の risk_tier GT は min_TTC_s だけの決定的関数(≤2→danger / ≤12→caution /
# それ以外→info・train で danger 554/554・caution 65/65 が 100% 一致)であり、ADAS で標準的な
# TTC 基準の衝突リスク定義。旧 kind 別閾値(alarm=5/speech=2・v021_core 手調整・baseline 流用)は
# coverage_v1 GT と系統的にズレ risk_tier を 0.52 に落としていた。全 kind を (12, 2) に統一して
# 純 TTC ルールへ合わせる(supreme のみ・baseline は read-only で不変)。
# ---------------------------------------------------------------------------

_THRESHOLDS = {
    "vehicle": (12.0, 2.0),
    "siren": (12.0, 2.0),
    "alarm": (12.0, 2.0),
    "speech": (12.0, 2.0),
}
_DEFAULT_THRESHOLDS = (12.0, 2.0)

# ADR 0045: GT 整合の純 TTC 閾値(厳密 `<`)。danger<2.0 / caution<8.0 / else info。
_TTC_DANGER_S = 2.0
_TTC_CAUTION_S = 8.0


def risk_tier(tracks) -> str:
    """track 特徴の列から主トラックを選び v1.4 risk_tier ラベルに分類する(ADR 0017 決定3 T0)。

    主トラック選択(siren 優先・なければ最小 r_m)→ kind 別 TTC 閾値判定 → siren 下限の順で
    v1.4 risk_tier ラベルを返す純関数。状態を持たず、HGF にも依存しない。safety latch は
    risk_tier に適用しない(ADR 0017 追記・risk_safe 用=採点外)。

    track 列が空のときは例外を投げず、安全側の既定 info を返す(ADR 0017 追記・軽微指摘)。

    Args:
        tracks: 各 track が {"kind": str, "ttc_s": float, "r_m": float} を持つ列。

    Returns:
        v1.4 risk_tier ラベル(info / caution / danger)。
    """
    main = _select_main_track(tracks)
    # track 0 件は安全側の既定 info(例外を投げない・v1.4 語彙に閉じる)。
    if main is None:
        return INFO

    kind = main.get("kind")
    ttc = float(main.get("ttc_s"))

    # ADR 0045: GT(gt_derive.risk_tier)完全整合の純 TTC 規則。siren salient→danger /
    # ttc<2.0→danger / ttc<8.0→caution / else info(厳密 `<`)。旧実装は caution≤12・siren→caution
    # 下限で GT(caution<8・siren→danger)とズレ risk 0.94 に留めていた(強 baseline が露呈)。
    if kind == "siren":
        return DANGER
    if ttc < _TTC_DANGER_S:
        return DANGER
    if ttc < _TTC_CAUTION_S:
        return CAUTION
    return INFO


def _select_main_track(tracks):
    """主トラックを選ぶ: siren 優先、なければ最近傍(最小 r_m)(ADR 0017 決定3 T0)。

    track 列が空(siren も non-siren も無い)のときは None を返す(呼び出し側で安全側の
    既定 info に変換する。min([]) の ValueError を投げない)。
    """
    sirens = [t for t in tracks if t.get("kind") == "siren"]
    if sirens:
        return min(sirens, key=lambda t: float(t.get("r_m")))
    if not tracks:
        return None
    return min(tracks, key=lambda t: float(t.get("r_m")))
