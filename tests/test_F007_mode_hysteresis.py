"""F-007 mode 改良(計測根拠ケース): supreme.mode の局所ヒステリシス層が
ADR 0015 決定2 の「安全優先の局所ヒステリシス」を満たすこと。テストは挙動
(logits, prev_mode) → v1.4 mode ラベルを契約とし、内部実装は裁量(挙動等価なら通る)。

契約の最終根拠:
  - decisions/0015-f007-mode-hysteresis.md(手法の正・計測根拠)
      決定1: F-007 のスコープ = 局所ヒステリシス層。入力 = フレームの mode logit 群
             + 前フレーム argmax mode、出力 = ヒステリシス適用後の v1.4 mode。
             証拠→logit 生成(baseline t2.py の段1-2)は上流の共有基盤=スコープ外。
      決定2: 安全優先の局所ヒステリシス:
        1) prev_mode == quiet_standby のとき、各「遷移先 mode(≠quiet_standby)」の
           logit を block=2.6 減衰してから argmax(単一フレームの弱い証拠での過剰遷移抑制)。
        2) ただし安全クリティカル mode(emergency / alert_required)は減衰しない
           =即発火(ハザード警報を遅延させない)。
        3) prev_mode != quiet_standby のときは減衰しない(ヒステリシス不作動)。
        計測根拠: baseline mode acc 0.6238 基準で 是正13・副作用8・純増+5・acc→0.648。
      決定3: 隣接境界群(side_rear 9・siren 7)はラベル意味論の別課題=スコープ外。
  - specs/SPEC.md F-007 / decisions/0013(U1: mode=ルール改良)/ decisions/0006(v1.4 mode 語彙)
  - v1.4 mode 統制語彙(10クラス・ADR 0006 / specs/GT_SCHEMA.md):
      conv_request, conv_ongoing, surround_activity, forward_caution,
      side_rear_caution, alert_required, emergency, quiet_standby, env_change, uncertain

本ファイルの各ケースは ADR 0015 の**計測根拠ケース**(過剰遷移抑制・強い証拠の通過・
安全 mode 即発火・prev≠quiet 不作動・block 境界の tie-break・複数遷移先・決定性)を
固定する。証拠→logit の生成はスコープ外のため logits を直接与える。
既存 F-011(supreme.quality.classify)と同様の「分類の完全一致採点」流儀を踏襲する。

tie-break の明示(ADR 0015 決定2 の式「block 減算後に他mode が quiet 以下なら quiet」):
  差 == block ちょうど(減衰後に遷移先 logit == quiet logit)の場合は遷移先を**選ばず
  quiet_standby のまま**にする。これは ADR 0015 が「強い証拠(差 ≥ block 超過)で遷移を
  許す」と「過剰遷移を抑制する」を両立させる解釈であり、本テストで挙動を1つに固定する。
"""

import pytest

from supreme import mode


# ADR 0015 決定2: block 減衰量(baseline/planA 計測値)。
BLOCK = 2.6


# ---------------------------------------------------------------------------
# 過剰遷移の抑制(prev=quiet_standby・差 < block → quiet のまま)
# ADR 0015 決定2-1: new_entity→env_change(10件) 等の過剰遷移を抑える主機構
# ---------------------------------------------------------------------------

def test_F007_prev_quiet_weak_transition_suppressed_stays_quiet():
    """F-007(ADR 0015 決定2-1・計測根拠 過剰遷移抑制): prev=quiet_standby で
    env_change の logit が quiet より僅かに高い(差 2.0 < block 2.6)なら、block 減衰後
    env_change=2.0-2.6=-0.6 < quiet 0.0 となり quiet_standby のまま(過剰遷移を抑制)。
    """
    logits = {"quiet_standby": 0.0, "env_change": 2.0}
    assert mode.hysteresis(logits, "quiet_standby") == "quiet_standby"


# ---------------------------------------------------------------------------
# 強い証拠は遷移を許す(prev=quiet・差 > block → 遷移)
# ADR 0015 決定2-1: 過剰遷移抑制と真の遷移許容の両立
# ---------------------------------------------------------------------------

def test_F007_prev_quiet_strong_evidence_transitions():
    """F-007(ADR 0015 決定2-1・計測根拠 強い証拠): prev=quiet_standby で env_change の
    logit が quiet+block を超える(差 3.0 > block 2.6)なら、block 減衰後
    env_change=3.0-2.6=0.4 > quiet 0.0 となり env_change へ遷移する。
    """
    logits = {"quiet_standby": 0.0, "env_change": 3.0}
    assert mode.hysteresis(logits, "quiet_standby") == "env_change"


# ---------------------------------------------------------------------------
# 安全クリティカル mode は即発火(emergency / alert_required は減衰しない)
# ADR 0015 決定2-2: ハザード警報を遅延させない(siren→emergency 等を吸収しない)
# ---------------------------------------------------------------------------

def test_F007_prev_quiet_emergency_not_decayed_fires_immediately():
    """F-007(ADR 0015 決定2-2・計測根拠 安全優先): prev=quiet_standby で emergency の
    logit が quiet より僅かに高い(差 1.0 < block 2.6)でも、emergency は減衰されず
    emergency=1.0 > quiet 0.0 のまま argmax され emergency になる(即発火)。
    """
    logits = {"quiet_standby": 0.0, "emergency": 1.0}
    assert mode.hysteresis(logits, "quiet_standby") == "emergency"


def test_F007_prev_quiet_alert_required_not_decayed_fires_immediately():
    """F-007(ADR 0015 決定2-2・計測根拠 安全優先): prev=quiet_standby で alert_required の
    logit が quiet より僅かに高い(差 1.0 < block 2.6)でも、alert_required は安全クリティカル
    mode として減衰されず alert_required=1.0 > quiet 0.0 のまま argmax され alert_required になる。
    """
    logits = {"quiet_standby": 0.0, "alert_required": 1.0}
    assert mode.hysteresis(logits, "quiet_standby") == "alert_required"


def test_F007_prev_quiet_non_safety_mode_is_decayed_same_logit():
    """F-007(ADR 0015 決定2-1/2-2・対比): 安全 mode と同じ logit(差 1.0 < block)でも、
    非安全 mode(env_change)は減衰され quiet_standby のまま。これにより
    「emergency/alert_required だけが即発火し、他の遷移先は抑制される」差を固定する。
    """
    logits = {"quiet_standby": 0.0, "env_change": 1.0}
    assert mode.hysteresis(logits, "quiet_standby") == "quiet_standby"


# ---------------------------------------------------------------------------
# prev != quiet_standby では不作動(ヒステリシスは quiet からの過剰遷移抑制に限定)
# ADR 0015 決定2-3: 計測した機構は quiet 起点のみ
# ---------------------------------------------------------------------------

def test_F007_prev_not_quiet_weak_transition_not_suppressed():
    """F-007(ADR 0015 決定2-3・計測根拠 不作動): prev=forward_caution で env_change の
    logit が僅かに高い(差 0.5)なら、減衰されず env_change=0.5 > forward_caution 0.0 の
    まま env_change へ遷移する(ヒステリシスは prev≠quiet では効かない)。
    """
    logits = {"forward_caution": 0.0, "env_change": 0.5}
    assert mode.hysteresis(logits, "forward_caution") == "env_change"


def test_F007_prev_not_quiet_argmax_unchanged_stays():
    """F-007(ADR 0015 決定2-3): prev=forward_caution で forward_caution が最大なら、
    減衰なしの素の argmax で forward_caution のまま(遷移しない)。
    """
    logits = {"forward_caution": 1.0, "env_change": 0.5, "conv_ongoing": -0.3}
    assert mode.hysteresis(logits, "forward_caution") == "forward_caution"


# ---------------------------------------------------------------------------
# 境界: 差 == block ちょうどの tie-break(減衰後に遷移先 == quiet → quiet)
# ADR 0015 決定2 の式「block 減算後に他mode が quiet 以下なら quiet」を一意に固定
# ---------------------------------------------------------------------------

def test_F007_prev_quiet_difference_exactly_block_stays_quiet():
    """F-007(ADR 0015 決定2・境界 tie-break): prev=quiet_standby で env_change の logit が
    quiet+block ちょうど(差 2.6 == block)なら、block 減衰後 env_change=2.6-2.6=0.0 で
    quiet 0.0 と同値になる。ADR の式「block 減算後に他mode が quiet 以下なら quiet」に従い、
    tie(同値)では遷移先を選ばず quiet_standby のままにする(挙動を1つに固定)。
    """
    logits = {"quiet_standby": 0.0, "env_change": 2.6}
    assert mode.hysteresis(logits, "quiet_standby") == "quiet_standby"


def test_F007_prev_quiet_difference_just_over_block_transitions():
    """F-007(ADR 0015 決定2・境界): prev=quiet_standby で差が block を僅かに超える
    (差 2.7 > block 2.6)なら、block 減衰後 env_change=2.7-2.6=0.1 > quiet 0.0 で
    env_change へ遷移する(tie の上側=遷移する側を固定)。
    """
    logits = {"quiet_standby": 0.0, "env_change": 2.7}
    assert mode.hysteresis(logits, "quiet_standby") == "env_change"


# ---------------------------------------------------------------------------
# 複数遷移先(prev=quiet・全て弱ければ quiet / 1つでも block 超えならそれへ)
# ADR 0015 決定2-1: 複数の弱い遷移先が同時にあっても全て減衰される
# ---------------------------------------------------------------------------

def test_F007_prev_quiet_multiple_weak_transitions_all_suppressed_stays_quiet():
    """F-007(ADR 0015 決定2-1・計測根拠 複数遷移先): prev=quiet_standby で複数の遷移先が
    いずれも弱い(env_change 2.0 / conv_ongoing 1.5 / surround_activity 1.0 が全て差 < block)
    なら、全て減衰されて quiet を超えず quiet_standby のまま。
    """
    logits = {
        "quiet_standby": 0.0,
        "env_change": 2.0,
        "conv_ongoing": 1.5,
        "surround_activity": 1.0,
    }
    assert mode.hysteresis(logits, "quiet_standby") == "quiet_standby"


def test_F007_prev_quiet_one_strong_among_weak_transitions_to_strong():
    """F-007(ADR 0015 決定2-1・計測根拠 複数遷移先): prev=quiet_standby で弱い遷移先に
    交じって1つだけ強い遷移先(conv_ongoing 3.5: 差 ≥ block)があれば、減衰後も
    conv_ongoing=3.5-2.6=0.9 が最大となり conv_ongoing へ遷移する。
    """
    logits = {
        "quiet_standby": 0.0,
        "env_change": 2.0,
        "conv_ongoing": 3.5,
        "surround_activity": 1.0,
    }
    assert mode.hysteresis(logits, "quiet_standby") == "conv_ongoing"


def test_F007_prev_quiet_weak_non_safety_but_safety_present_fires_safety():
    """F-007(ADR 0015 決定2-1/2-2・複数遷移先 + 安全優先): prev=quiet_standby で
    非安全遷移先は全て弱く(env_change 2.0: 差 < block で減衰)、安全 mode emergency が
    弱いながら存在(1.0)するなら、emergency は減衰されず emergency=1.0 が最大となり
    emergency へ即発火する(弱い証拠でも安全 mode を取りこぼさない)。
    """
    logits = {
        "quiet_standby": 0.0,
        "env_change": 2.0,
        "emergency": 1.0,
    }
    assert mode.hysteresis(logits, "quiet_standby") == "emergency"


# ---------------------------------------------------------------------------
# 出力は v1.4 mode 統制語彙のラベル(ADR 0006)
# ---------------------------------------------------------------------------

def test_F007_output_is_v14_mode_vocabulary_label():
    """F-007(ADR 0015 決定1 + ADR 0006 語彙): 出力は argmax で選ばれた v1.4 mode ラベル
    そのもの(quiet_standby を含む10クラスの統制語彙)。代表ケースで語彙集合に閉じることを確認。
    """
    v14_modes = {
        "conv_request",
        "conv_ongoing",
        "surround_activity",
        "forward_caution",
        "side_rear_caution",
        "alert_required",
        "emergency",
        "quiet_standby",
        "env_change",
        "uncertain",
    }
    samples = [
        ({"quiet_standby": 0.0, "env_change": 2.0}, "quiet_standby"),
        ({"quiet_standby": 0.0, "env_change": 3.0}, "quiet_standby"),
        ({"quiet_standby": 0.0, "emergency": 1.0}, "quiet_standby"),
        ({"forward_caution": 0.0, "env_change": 0.5}, "forward_caution"),
        ({"side_rear_caution": 1.0, "uncertain": 0.5}, "side_rear_caution"),
    ]
    for logits, prev in samples:
        result = mode.hysteresis(logits, prev)
        assert result in v14_modes, (
            f"hysteresis({logits!r}, {prev!r}) が v1.4 語彙外のラベルを返した: {result!r}"
        )


# ---------------------------------------------------------------------------
# 決定性(F-004-1 / F-011 の流儀: 同入力で2回呼んで同一・乱数で揺れない)
# ---------------------------------------------------------------------------

def test_F007_hysteresis_is_deterministic_same_label_twice():
    """F-007(決定性): 同じ (logits, prev_mode) で2回呼ぶと同一ラベル(乱数で揺れない)。

    局所ヒステリシスはルール判定であり学習・乱数を含まない(ADR 0015: 学習はしない)。
    過剰遷移抑制・強い証拠・安全 mode 即発火・境界 tie・prev≠quiet を含む代表点で
    完全一致を確認する。
    """
    cases = [
        ({"quiet_standby": 0.0, "env_change": 2.0}, "quiet_standby"),
        ({"quiet_standby": 0.0, "env_change": 3.0}, "quiet_standby"),
        ({"quiet_standby": 0.0, "emergency": 1.0}, "quiet_standby"),
        ({"quiet_standby": 0.0, "alert_required": 1.0}, "quiet_standby"),
        ({"quiet_standby": 0.0, "env_change": 2.6}, "quiet_standby"),
        ({"forward_caution": 0.0, "env_change": 0.5}, "forward_caution"),
        (
            {
                "quiet_standby": 0.0,
                "env_change": 2.0,
                "conv_ongoing": 3.5,
                "surround_activity": 1.0,
            },
            "quiet_standby",
        ),
    ]
    for logits, prev in cases:
        first = mode.hysteresis(logits, prev)
        second = mode.hysteresis(logits, prev)
        assert first == second, (
            f"hysteresis({logits!r}, {prev!r}) が2回呼び出しで一致しない: "
            f"{first!r} != {second!r}"
        )
