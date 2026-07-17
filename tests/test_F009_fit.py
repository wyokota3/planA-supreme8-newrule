"""F-009 T3(ADR 0020)— 学習(fit)の決定性と end-to-end 決定性の契約。

学習モジュールゆえ **fit 後の厳密な学習値(重み/バイアス)は契約にしない**(F-013 の成功目標)。
本ファイルは fit の**決定性**(同じ練習データで2回 fit すると同一 params・再現性 F-004-2 の精神)、
fit した params での **end-to-end 決定性**(同じ入力系列+同じ reset 列+同じ fit params で T3 列が
2回とも同一)、および fit が**予算内の param 数**を返すことを固定する。

契約の最終根拠:
  - decisions/0020-f009-t3-episode-learning.md:
      決定3 / 残件: fit は決定的手順(乱数なし・grid/座標降下)。同じ練習データで2回 fit すると
             同一 params。実際の学習値は実装の学習実験で決まる(step1 では構造・特徴・学習対象を確定)。
      決定2: 学習可能 param ~7-21 ≪ 予算 100。
  - decisions/0002(F-004-2 再現性・ε=U5a)/ decisions/0018(U24・k=0.5・data=練習用件数)/
    decisions/0006(v1.4 T3 語彙)/ specs/SPEC.md F-009-1。

スコープ外(ADR 0020・推測でテスト化しない):
  - fit の具体手順(grid か座標降下か)・目的関数・収束した param の値は ADR 0020 が一意に
    規定しない(実装の学習実験で決定)。本ファイルは『同じ練習データ → 同じ params』
    『fit param が予算内』『fit param で end-to-end 決定的』のみを固定し、値・手順には踏み込まない。
  - 実際の T3 acc 改善(baseline 超え)・ns016群の分離成否は F-013 の成功目標(本ファイル対象外)。

テストが前提とする supreme.t3 の公開 API(設計裁量・指示で委任・F-010 fit 流儀):
  t3.fit(practice_data) -> learned_params
      practice_data = 練習用の (mode 系列, reset 系列, gt hypothesis 系列) サンプルの列。
                      [{"mode_seq": [...], "reset_seq": [...], "gt": ["quiet_stable",...]}, ...]。
      learned_params = fit で決まった params(dict 風)。決定的(乱数なし)。
        t3.run_t3_sequence / classify_t3 に渡せる形。
        learned_params.learnable_param_count() -> int で学習可能 param 数を取り出せる
        (== t3.learnable_param_count() と同数=学習対象は固定)。
  t3.run_t3_sequence(mode_seq, reset_seq, params) -> list[str]  (test_F009_state.py 参照)
"""

import pytest

from supreme import guard, t3

K = 0.5
PRACTICE_DATA_COUNT_FOR_BUDGET = 200


def _mode(label, posterior=0.5):
    return {"mode": label, "posterior": posterior}


def _conv(posterior=0.7):
    return _mode("conv_strong", posterior)


def _quiet(posterior=0.2):
    return _mode("quiet", posterior)


def _traffic(posterior=0.5):
    return _mode("traffic", posterior)


def _practice_data():
    """決定的な練習用サンプル(mode 系列 + reset 系列 + gt hypothesis)。fit 入力。

    内容は固定(乱数なし)。持続conv(conv 寄り)/ 切替不安定(traffic 寄り)/ 安定(quiet 寄り)の
    3系統を含む小さな練習集合。fit の決定性・予算・end-to-end 決定性を見るためのもので、
    学習値そのものは検証しない。gt ラベルは v1.4 T3 語彙。
    """
    return [
        {  # 持続conv エピソード(conv 寄り)
            "mode_seq": [_conv(0.7), _conv(0.72), _conv(0.71), _conv(0.73)],
            "reset_seq": [False, False, False, False],
            "gt": ["conv_participating"] * 4,
        },
        {  # 切替不安定エピソード(traffic 寄り)
            "mode_seq": [_traffic(0.5), _quiet(0.3), _traffic(0.55), _quiet(0.28)],
            "reset_seq": [False, False, False, False],
            "gt": ["traffic_unstable"] * 4,
        },
        {  # 安定エピソード(quiet 寄り)
            "mode_seq": [_quiet(0.2), _quiet(0.21), _quiet(0.2), _quiet(0.22)],
            "reset_seq": [False, False, False, False],
            "gt": ["quiet_stable"] * 4,
        },
        {  # reset を含むエピソード(境界後に conv)
            "mode_seq": [_traffic(0.5), _quiet(0.3), _conv(0.7), _conv(0.72)],
            "reset_seq": [False, False, True, False],
            "gt": ["traffic_unstable", "traffic_unstable",
                   "conv_participating", "conv_participating"],
        },
    ]


# ===========================================================================
# G) fit の決定性: 同じ練習データで2回 fit すると同一 params(F-004-2 の精神)
# ===========================================================================

def test_F009_fit_is_deterministic_same_params_twice():
    """F-009(ADR 0020 決定3・fit 決定性): 同じ練習データで2回 fit すると同一 params。

    学習も決定的(乱数なし・grid/座標降下)。再現性(F-004-2)の精神を学習に適用する。
    学習値そのものは検証しない(F-013 の成功目標)が、2回の fit が**同一**であることを
    固定する(end-to-end の決定性の土台)。等価性は観測可能な end-to-end 出力で比較する
    (内部表現に踏み込まない)。
    """
    data = _practice_data()
    p1 = t3.fit(data)
    p2 = t3.fit(data)
    # 学習 params を end-to-end の出力で比較する。
    mode_seq = [_conv(0.7), _conv(0.7), _traffic(0.5), _quiet(0.2), _quiet(0.2)]
    reset_seq = [False, False, False, False, False]
    out1 = list(t3.run_t3_sequence(mode_seq, reset_seq, p1))
    out2 = list(t3.run_t3_sequence(mode_seq, reset_seq, p2))
    assert out1 == out2, (
        f"同じ練習データで2回 fit した params の T3 列が不一致(fit 非決定): "
        f"{out1} != {out2}"
    )


def test_F009_fit_param_count_matches_learnable_budget():
    """F-009(ADR 0020 決定2/決定3・fit 予算): fit が返す params の学習可能 param 数が、
    t3.learnable_param_count() と一致する(学習対象は固定)。

    fit は学習対象(ロジスティック重み+バイアス)だけを更新する。fit 後も学習可能 param 数は
    宣言された固定リストと同数(fit が param を増やさない=予算を後から食い破らない)。
    """
    p = t3.fit(_practice_data())
    assert p.learnable_param_count() == t3.learnable_param_count(), (
        f"fit 後の学習可能 param 数 {p.learnable_param_count()} が "
        f"宣言された {t3.learnable_param_count()} と異なる(学習対象が変動)"
    )


def test_F009_fit_param_count_within_budget():
    """F-009(ADR 0020 決定2/決定3 / F-014-1・fit 予算内): fit が返す param 数が予算 data×0.5 を
    厳密に下回り、過学習ガード(F-014-1)に合格する。

    fit param 数を guard.check_param_budget(param, 200, 0.5) に通すと合格(< 100)。学習(fit)が
    予算内の param 数を返すことを固定する(既存 guard 再利用)。
    """
    p = t3.fit(_practice_data())
    r = guard.check_param_budget(
        param_count=p.learnable_param_count(),
        data_count=PRACTICE_DATA_COUNT_FOR_BUDGET,
        k=K,
    )
    assert r.passed is True, (
        f"fit param 数 {p.learnable_param_count()} が予算 "
        f"{PRACTICE_DATA_COUNT_FOR_BUDGET}×{K} を超過: {r.reason}"
    )


# ===========================================================================
# F-009-1: end-to-end 決定性 — fit した params で同じ入力系列+同じ reset 列を
#          2回流すと同一の T3 hypothesis 列
# ===========================================================================

def test_F009_end_to_end_sequence_is_deterministic():
    """F-009-1(ADR 0020 決定3 / F-004-2・end-to-end 決定性): fit した params で同じ mode 系列+
    同じ reset 列を2回 run_t3_sequence すると同一の T3 hypothesis 列(乱数・時刻なし)。

    集約状態機構→ロジスティック分類の全経路が決定的。同一入力・同一 reset・同一 fit params で
    T3 列が完全一致することを固定する(再現性 F-004-2 の精神を end-to-end に適用)。
    """
    params = t3.fit(_practice_data())
    mode_seq = [_conv(0.7), _conv(0.7), _traffic(0.5), _quiet(0.2),
                _quiet(0.2), _conv(0.7), _conv(0.72)]
    reset_seq = [False, False, False, True, False, False, False]
    out_a = list(t3.run_t3_sequence(mode_seq, reset_seq, params))
    out_b = list(t3.run_t3_sequence(mode_seq, reset_seq, params))
    assert out_a == out_b, (
        f"同一入力・同一 reset・同一 fit params で T3 列が2回で不一致(end-to-end 非決定): "
        f"{out_a} != {out_b}"
    )


def test_F009_end_to_end_output_length_matches_input():
    """F-009(ADR 0020・構造): fit した params で run_t3_sequence した出力 T3 列の長さが
    入力 mode 列長と一致する(各フレームに1つの T3 hypothesis)。
    """
    params = t3.fit(_practice_data())
    mode_seq = [_conv(0.7), _traffic(0.5), _quiet(0.2), _conv(0.7), _quiet(0.2)]
    reset_seq = [False] * len(mode_seq)
    out = list(t3.run_t3_sequence(mode_seq, reset_seq, params))
    assert len(out) == len(mode_seq)


def test_F009_end_to_end_output_in_v14_vocabulary():
    """F-009(ADR 0006/0020・語彙閉包): fit した params で run_t3_sequence した出力が v1.4 T3
    10語彙のみで構成される。

    end-to-end でも出力語彙が v1.4 に閉じることを固定する。
    """
    params = t3.fit(_practice_data())
    v14_t3 = {
        "quiet_stable", "conv_participating", "sustained_alert", "env_shift",
        "env_start", "crowd_tendency", "traffic_unstable", "hazard_declining",
        "uncertain_context", "alert_required",
    }
    mode_seq = [_conv(0.7), _conv(0.7), _traffic(0.5), _quiet(0.2),
                _quiet(0.2), _conv(0.7)]
    reset_seq = [False, False, False, True, False, False]
    out = t3.run_t3_sequence(mode_seq, reset_seq, params)
    for label in out:
        assert label in v14_t3, (
            f"run_t3_sequence 出力に v1.4 T3 語彙外のラベル: {label!r}"
        )
