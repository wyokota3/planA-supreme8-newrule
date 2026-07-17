"""F-011 判定規則(計測根拠ケース): supreme.quality.classify が ADR 0014 決定3 の
v1.4 quality_regime 規則を満たすこと。テストは挙動 (h_q, vol) → v1.4 ラベルを契約とし、
内部分岐の保持/簡約は実装裁量(挙動等価なら通る)。

契約の最終根拠:
  - decisions/0014-f011-quality-recalibration.md(手法の正・計測根拠)
      決定2: 再較正 = GOOD ゲート h_q≥0.94 → h_q≥0.93(vol 条件据え置き)。
             計測: GOOD→PASS 23件のうち h_q∈[0.93,0.94) の 8件が GOOD に復帰、
             副作用0件(真 PASS 群の最大 h_q=0.925 < 0.93 のため巻き込みなし)。
      決定3: v1.4 3クラス規則(優先順位チェーン):
        1) h_q < 0.25                  → BLOCK
        2) h_q < 0.40 ∧ vol > 0.05     → BLOCK     # 本データ不作動・構造保持
        3) h_q < 0.55                  → BLOCK
        4) h_q ≥ 0.93 ∧ vol < 0.01     → GOOD      # 再較正 0.94→0.93
        5) その他                       → DEGRADED
        挙動等価な最小形: h_q<0.55→BLOCK / h_q≥0.93∧vol<0.01→GOOD / その他→DEGRADED。
      計測: vol は全210フレームで 0.0058〜0.0099(0.01 も 0.05 も超えない)。
  - specs/SPEC.md F-011 / decisions/0006(v1.4 語彙)/ decisions/0013(quality=ルール改良)。

本ファイルの各ケースは ADR 0014 の**計測根拠ケース**(境界・再較正効果・副作用ゼロ・
BLOCK 域・vol 条件)を固定する。h_q/vol の生成はスコープ外のため (h_q, vol) を直接与える。
既存 F-004 と同様の「分類の完全一致採点」流儀を踏襲する。
"""

import pytest

from supreme import quality


# ---------------------------------------------------------------------------
# GOOD ゲート再較正の境界(ADR 0014 決定2・決定3 の branch4)
# ---------------------------------------------------------------------------

def test_F011_good_gate_recalibrated_lower_bound_is_good():
    """F-011(ADR 0014 決定2・計測根拠): h_q=0.93, vol=0.009 → GOOD。

    再較正後の GOOD ゲート下端(h_q≥0.93 ∧ vol<0.01)ちょうど。旧 0.94 ゲートでは
    DEGRADED だったフレームが GOOD に復帰する境界。
    """
    assert quality.classify(0.93, 0.009) == quality.GOOD


def test_F011_good_gate_just_below_recalibrated_bound_is_degraded():
    """F-011(ADR 0014 決定3・計測根拠): h_q=0.929, vol=0.009 → DEGRADED。

    再較正後の GOOD ゲート(h_q≥0.93)の直下。0.55≤h_q<0.93 の DEGRADED 域に入る。
    """
    assert quality.classify(0.929, 0.009) == quality.DEGRADED


def test_F011_good_gate_original_pass_value_is_good():
    """F-011(ADR 0014 決定3): h_q=0.94, vol=0.009 → GOOD(元から GOOD)。

    再較正前の旧ゲート h_q≥0.94 でも GOOD だった値。再較正が既存 GOOD を壊さない。
    """
    assert quality.classify(0.94, 0.009) == quality.GOOD


# ---------------------------------------------------------------------------
# 再較正の効果(+8件相当: h_q∈[0.93,0.94) ∧ vol<0.01 が GOOD に復帰)
# ---------------------------------------------------------------------------

def test_F011_recalibration_gain_representative_value_is_good():
    """F-011(ADR 0014 決定2・計測根拠 +8件): h_q=0.935, vol=0.009 → GOOD。

    h_q∈[0.93,0.94) ∧ vol<0.01 の代表値。旧 0.94 ゲートでは DEGRADED だったが、
    再較正(GOOD ゲート h_q≥0.93)により GOOD になる(復帰 8件相当の代表)。
    """
    assert quality.classify(0.935, 0.009) == quality.GOOD


# ---------------------------------------------------------------------------
# 副作用ゼロの担保(真 PASS 群の最大 h_q=0.925 < 0.93 → GOOD に巻き込まれない)
# ---------------------------------------------------------------------------

def test_F011_no_side_effect_true_pass_max_stays_degraded():
    """F-011(ADR 0014 決定2・計測根拠 副作用0): h_q=0.925, vol=0.009 → DEGRADED。

    真 PASS 群の最大 h_q=0.925 は再較正後ゲート 0.93 の下。GOOD に巻き込まれず
    DEGRADED のまま(副作用0件の根拠ケース)。
    """
    assert quality.classify(0.925, 0.009) == quality.DEGRADED


# ---------------------------------------------------------------------------
# BLOCK 域(branch1/branch3: h_q<0.55 → BLOCK)
# ---------------------------------------------------------------------------

def test_F011_block_extreme_low_h_q_is_block():
    """F-011(ADR 0014 決定3 branch1): h_q=0.001, vol=0.009 → BLOCK。

    DEGRADED→BLOCK の悲観群相当(計測 h_q≈0.0014)。ルール1 (h_q<0.25) で BLOCK。
    """
    assert quality.classify(0.001, 0.009) == quality.BLOCK


def test_F011_block_h_q_point_three_is_block():
    """F-011(ADR 0014 決定3 branch3): h_q=0.3, vol=0.009 → BLOCK。

    0.25≤h_q<0.55 はルール3 (h_q<0.55) で BLOCK(旧 DEGRADED → v1.4 BLOCK)。
    """
    assert quality.classify(0.3, 0.009) == quality.BLOCK


def test_F011_block_just_below_degraded_boundary_is_block():
    """F-011(ADR 0014 決定3 branch3・境界): h_q=0.549, vol=0.009 → BLOCK。

    h_q<0.55 の上端側。ルール3 で BLOCK(BLOCK/DEGRADED 境界の下側)。
    """
    assert quality.classify(0.549, 0.009) == quality.BLOCK


# ---------------------------------------------------------------------------
# BLOCK/DEGRADED 境界(branch3 の閾値 0.55 は「<」: 0.55 ちょうどは抜ける)
# ---------------------------------------------------------------------------

def test_F011_degraded_at_block_boundary_is_degraded():
    """F-011(ADR 0014 決定3 境界): h_q=0.55, vol=0.009 → DEGRADED。

    branch3 は h_q<0.55(厳密小なり)なので 0.55 ちょうどは BLOCK を抜け、
    GOOD ゲート(h_q≥0.93)も満たさず DEGRADED になる。
    """
    assert quality.classify(0.55, 0.009) == quality.DEGRADED


# ---------------------------------------------------------------------------
# DEGRADED 中域(0.55≤h_q<0.93)
# ---------------------------------------------------------------------------

def test_F011_degraded_mid_range_is_degraded():
    """F-011(ADR 0014 決定3 branch5): h_q=0.70, vol=0.009 → DEGRADED。

    0.55≤h_q<0.93(BLOCK でも GOOD でもない中域)は DEGRADED。
    """
    assert quality.classify(0.70, 0.009) == quality.DEGRADED


# ---------------------------------------------------------------------------
# vol 条件(構造・本データ不作動だが規則として固定: GOOD ゲートの vol<0.01)
# ---------------------------------------------------------------------------

def test_F011_high_h_q_high_vol_misses_good_gate_is_degraded():
    """F-011(ADR 0014 決定3 branch4 vol 条件): h_q=0.95, vol=0.02 → DEGRADED。

    h_q は GOOD ゲート(≥0.93)を満たすが vol≥0.01 で vol<0.01 条件を外れるため
    GOOD にならず DEGRADED。vol 条件は本データ不作動だが規則として固定する。
    """
    assert quality.classify(0.95, 0.02) == quality.DEGRADED


def test_F011_high_h_q_low_vol_passes_good_gate_is_good():
    """F-011(ADR 0014 決定3 branch4): h_q=0.95, vol=0.005 → GOOD。

    h_q≥0.93 ∧ vol<0.01 をともに満たし GOOD。
    """
    assert quality.classify(0.95, 0.005) == quality.GOOD


# ---------------------------------------------------------------------------
# 決定性(F-004-1 の流儀: 同入力で2回呼んで同一・乱数で揺れない)
# ---------------------------------------------------------------------------

def test_F011_classify_is_deterministic_same_label_twice():
    """F-011(決定性): 同じ (h_q, vol) で2回呼ぶと同一ラベル(乱数で揺れない)。

    quality_regime はルール判定であり学習・乱数を含まない(ADR 0013: 学習はしない)。
    再較正の境界(GOOD ゲート)と BLOCK 域・vol 条件を含む代表点で完全一致を確認する。
    """
    cases = [
        (0.93, 0.009),
        (0.929, 0.009),
        (0.935, 0.009),
        (0.925, 0.009),
        (0.001, 0.009),
        (0.55, 0.009),
        (0.549, 0.009),
        (0.95, 0.02),
        (0.95, 0.005),
    ]
    for h_q, vol in cases:
        first = quality.classify(h_q, vol)
        second = quality.classify(h_q, vol)
        assert first == second, (
            f"classify({h_q}, {vol}) が2回呼び出しで一致しない: {first!r} != {second!r}"
        )
