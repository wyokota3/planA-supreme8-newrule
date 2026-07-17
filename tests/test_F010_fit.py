"""F-010 scene 改良(ADR 0019)— 学習(fit)の決定性と end-to-end 決定性の契約。

学習モジュールゆえ **fit 後の厳密な学習値は契約にしない**(F-013 の成功目標)。本ファイルは
fit の**決定性**(同じ練習データで2回 fit すると同一 params・再現性 F-004-2 の精神)と、
fit した params での **end-to-end 決定性**(同じ入力+同じ params で scene 列が2回とも同一)、
および fit が**予算内の param 数**を返すことを固定する。

契約の最終根拠:
  - decisions/0019-f010-scene-hgf-learning.md:
      決定3: 学習(fit)は決定的手順(grid / 座標降下等・乱数なし)。再現性(F-004-2)のため
             学習も決定的。実際の学習値は実装の学習実験で決まる(step1 では構造・特徴・学習対象を
             確定)。
      決定2: 学習可能 param ~9-11 ≪ 予算 100。
  - decisions/0002(F-004-2 再現性・ε=U5a)/ decisions/0018(U24・k=0.5・data=練習用件数)/
    decisions/0006(v1.4 scene 語彙)/ specs/SPEC.md F-010。

スコープ外(ADR 0019・推測でテスト化しない):
  - fit の具体手順(grid か座標降下か)・目的関数・収束した param の値は ADR 0019 が一意に
    規定しない(実装の学習実験で決定)。本ファイルは『同じ練習データ → 同じ params』
    『fit param が予算内』『fit param で end-to-end 決定的』のみを固定し、値・手順には踏み込まない。
  - 実際の scene acc 改善(baseline 超え)は F-013 で測定する成功目標(本ファイル対象外)。

テストが前提とする supreme.scene の公開 API(設計裁量・指示で委任):
  scene.fit(practice_data) -> learned_params
      practice_data = 練習用の (signal_sequence, gt_regime_列) サンプルの列
                      [{"signal": [float,...], "gt": ["STABLE",...]}, ...]。
      learned_params = fit で決まった params(dict 風)。決定的(乱数なし)。
        scene.classify_sequence / hgf_filter / classify_scene に渡せる形。
        learned_params.learnable_param_count() -> int で学習可能 param 数を取り出せる
        (== scene.learnable_param_count() と同数=学習対象は固定)。
  scene.classify_sequence(signal_sequence, params) -> list[str]
      signal 列を HGF→特徴→分類して各ステップの v1.4 scene 列を返す(end-to-end)。
      params は fit の返り値(learned_params)を渡せる。
"""

import pytest

from supreme import guard, scene

K = 0.5
PRACTICE_DATA_COUNT_FOR_BUDGET = 200


def _practice_data():
    """決定的な練習用サンプル(signal + gt regime)。fit 入力。

    内容は固定(乱数なし)。STABLE(平坦 nominal)/ CHANGING(持続変化)/ DEGRADING(低水準)の
    3クラスを含む小さな練習集合。fit の決定性・予算・end-to-end 決定性を見るためのもので、
    学習値そのものは検証しない。
    """
    return [
        {"signal": [0.7, 0.7, 0.7, 0.7, 0.7, 0.7],
         "gt": ["STABLE", "STABLE", "STABLE", "STABLE", "STABLE", "STABLE"]},
        {"signal": [0.5, 0.55, 0.6, 0.65, 0.7, 0.75],
         "gt": ["STABLE", "CHANGING", "CHANGING", "CHANGING", "CHANGING", "CHANGING"]},
        {"signal": [0.6, 0.5, 0.4, 0.3, 0.2, 0.1],
         "gt": ["STABLE", "STABLE", "DEGRADING", "DEGRADING", "DEGRADING", "DEGRADING"]},
        {"signal": [0.5, 0.5, 0.5, 0.5, 0.5, 0.5],
         "gt": ["STABLE", "STABLE", "STABLE", "STABLE", "STABLE", "STABLE"]},
    ]


# ===========================================================================
# E) fit の決定性: 同じ練習データで2回 fit すると同一 params(F-004-2 の精神)
# ===========================================================================

def test_F010_fit_is_deterministic_same_params_twice():
    """F-010(ADR 0019 決定3・fit 決定性): 同じ練習データで2回 fit すると同一 params。

    学習も決定的(乱数なし・grid/座標降下)。再現性(F-004-2)の精神を学習に適用する。
    学習値そのものは検証しない(F-013 の成功目標)が、2回の fit が**同一**であることを
    固定する(end-to-end の決定性の土台)。
    """
    data = _practice_data()
    p1 = scene.fit(data)
    p2 = scene.fit(data)
    # 学習 param を end-to-end の出力で比較する(内部表現に踏み込まず、観測可能な等価性で固定)。
    seq = [0.6, 0.62, 0.5, 0.5, 0.2, 0.2, 0.7]
    out1 = list(scene.classify_sequence(seq, p1))
    out2 = list(scene.classify_sequence(seq, p2))
    assert out1 == out2, (
        f"同じ練習データで2回 fit した params の分類結果が不一致(fit 非決定): "
        f"{out1} != {out2}"
    )


def test_F010_fit_param_count_matches_learnable_budget():
    """F-010(ADR 0019 決定2/決定3・fit 予算): fit が返す params の学習可能 param 数が、
    scene.learnable_param_count() と一致する(学習対象は固定)。

    fit は学習対象(HGF param + 学習する閾値)だけを更新する。fit 後も学習可能 param 数は
    固定リストと同数(fit が param を増やさない=予算を後から食い破らない)。
    """
    p = scene.fit(_practice_data())
    assert p.learnable_param_count() == scene.learnable_param_count(), (
        f"fit 後の学習可能 param 数 {p.learnable_param_count()} が "
        f"宣言された {scene.learnable_param_count()} と異なる(学習対象が変動)"
    )


def test_F010_fit_param_count_within_budget():
    """F-010(ADR 0019 決定2/決定3 / F-014-1・fit 予算内): fit が返す param 数が予算
    data×0.5 を厳密に下回り、過学習ガード(F-014-1)に合格する。

    fit param 数を guard.check_param_budget(param, 200, 0.5) に通すと合格(< 100)。
    学習(fit)が予算内の param 数を返すことを固定する(ADR 0019 決定3「fit が予算内の
    param 数を返す」)。
    """
    p = scene.fit(_practice_data())
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
# F) end-to-end 決定性: fit した params で scene 列を分類すると、同じ入力+同じ
#    params で2回とも同一 regime 列
# ===========================================================================

def test_F010_end_to_end_classify_sequence_is_deterministic():
    """F-010(ADR 0019 決定3 / F-004-2・end-to-end 決定性): fit した params で同じ入力列を
    2回 classify_sequence すると同一の regime 列(乱数・時刻なし)。

    HGF→特徴→分類の全経路が決定的。同一入力・同一 params で scene 列が完全一致することを
    固定する(再現性 F-004-2 の精神を end-to-end に適用)。
    """
    params = scene.fit(_practice_data())
    seq = [0.7, 0.7, 0.6, 0.5, 0.45, 0.4, 0.2, 0.2, 0.5, 0.55, 0.6]
    out_a = list(scene.classify_sequence(seq, params))
    out_b = list(scene.classify_sequence(seq, params))
    assert out_a == out_b, (
        f"同一入力・同一 fit params で scene 列が2回で不一致(end-to-end 非決定): "
        f"{out_a} != {out_b}"
    )


def test_F010_end_to_end_output_length_matches_input():
    """F-010(ADR 0019・構造): classify_sequence の出力 regime 列の長さが入力列長と一致する。

    各ステップに1つの scene regime が出る(逐次分類)。
    """
    params = scene.fit(_practice_data())
    seq = [0.6, 0.6, 0.5, 0.4, 0.3]
    out = list(scene.classify_sequence(seq, params))
    assert len(out) == len(seq)


def test_F010_end_to_end_output_in_v14_vocabulary():
    """F-010(ADR 0006/0019・語彙閉包): classify_sequence の出力が v1.4 scene 3クラス
    {STABLE, CHANGING, DEGRADING} のみで構成される。

    end-to-end でも出力語彙が v1.4 に閉じることを固定する(DEGRADING を含む3クラス)。
    """
    params = scene.fit(_practice_data())
    v14_scene = {scene.STABLE, scene.CHANGING, scene.DEGRADING}
    seq = [0.7, 0.7, 0.55, 0.4, 0.3, 0.2, 0.1, 0.5, 0.6, 0.65]
    out = scene.classify_sequence(seq, params)
    for label in out:
        assert label in v14_scene, (
            f"classify_sequence 出力に v1.4 scene 語彙外のラベル: {label!r}"
        )
