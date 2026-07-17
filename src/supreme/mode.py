"""F-007: mode 局所ヒステリシス層（mode）。

supreme mode の局所ヒステリシス層。入力 = フレームの mode logit 群 + 前フレーム
argmax mode、出力 = ヒステリシス適用後の v1.4 mode ラベル。証拠抽出→ルール logit の
生成（baseline t2.py の段1-2 相当）・温度 softmax・EMA は上流の共有基盤であり、本
モジュールでは扱わない（ADR 0015 決定1）。

契約の最終根拠は specs/SPEC.md「F-007」節、decisions/0015-f007-mode-hysteresis.md
（手法の正・計測根拠）、decisions/0013（U1: mode=ルール改良）/0006（v1.4 mode 語彙）、
および tests/test_F007_mode_hysteresis.py。

機構（ADR 0015 決定2・安全優先の局所ヒステリシス）:
  1) prev_mode == quiet_standby のとき、各「遷移先 mode（≠quiet_standby）」の logit を
     block=2.6 減衰してから argmax（単一フレームの弱い証拠での過剰遷移抑制）。
  2) ただし安全クリティカル mode（emergency / alert_required）は減衰しない＝即発火
     （ハザード警報を遅延させない）。
  3) prev_mode != quiet_standby のときは減衰しない（ヒステリシス不作動・素の argmax）。
  4) tie-break: 減衰後に遷移先 logit が quiet_standby と同値（差ちょうど block）になる
     場合は quiet_standby を選ぶ＝遷移しない（ADR 0015 決定2 の式「block 減算後に他mode
     が quiet 以下なら quiet」）。

前フレーム argmax のみ参照する局所機構（エピソード状態を持たない）。決定的（乱数・
時刻なし）な純関数。本モジュールは stdlib のみに依存し、datagov/sealset/augment/
guard/harness/quality を改修しない。
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# 機構定数（ADR 0015 決定2）。
# ---------------------------------------------------------------------------

#: 遷移先 logit から減算する block 量（baseline/planA 計測値）。
BLOCK = 2.6

#: 無証拠既定 mode（quiet からの過剰遷移を抑制する起点）。
QUIET = "quiet_standby"

#: 安全クリティカル mode（減衰しない＝即発火）。
SAFETY_MODES = frozenset({"emergency", "alert_required"})


def hysteresis(logits, prev_mode) -> str:
    """mode logit 群と前フレーム argmax mode から局所ヒステリシスを適用する（ADR 0015 決定2）。

    prev_mode == quiet_standby の場合のみ、非安全の遷移先 logit を block 減衰してから
    argmax。安全 mode（emergency / alert_required）は減衰しない。prev_mode が quiet 以外
    なら素の argmax。tie（減衰後に遷移先が quiet と同値）では quiet_standby を選ぶ。

    Args:
        logits: {mode_label: float} のフレーム mode logit 群。
        prev_mode: 前フレーム argmax mode ラベル（str）。

    Returns:
        ヒステリシス適用後の v1.4 mode ラベル（logits のキーのいずれか）。
    """
    if prev_mode == QUIET:
        effective = {}
        for label, value in logits.items():
            if label != QUIET and label not in SAFETY_MODES:
                effective[label] = value - BLOCK
            else:
                effective[label] = value
    else:
        effective = logits

    # argmax。最大値が複数（tie）ある場合は quiet_standby（非遷移側）を優先する。
    best_label = None
    best_value = None
    for label, value in effective.items():
        if best_value is None or value > best_value:
            best_label = label
            best_value = value
        elif value == best_value and label == QUIET:
            best_label = label
    return best_label
