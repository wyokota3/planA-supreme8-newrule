"""F-004-1: 同一入力・同一指標定義で測定が決定的(ハーネス自体が乱数で揺れない)+
ADR 0012 の8層採点仕様が正しく効くこと。

specs/SPEC.md F-004-1:
  「同一入力・同一指標定義で測定結果が決定的(ハーネス自体が乱数で揺れない)」
decisions/0012-u10-evaluation-metrics.md(採点仕様の正):
  - 決定A: micro(global pooling: Σ正答/Σ非null)・完全一致(分類)・NA分母除外。
           層スコア=8層 global acc、総合=8層 global acc の単純平均(層 macro)。
  - 決定B: risk_tier 分母=210全採点に統一(短尺T0のNA除外特例をしない)。
  - 決定C: Anomaly = 採点対象外(8層のみ)。
  - 決定E: t1_state 採点語彙 = idle/approach/pass/depart(GT出現4クラス)。
  - 決定D: 補助21メトリクス = 参考(公式採点・勝敗は8層 acc のみ)。

テストが前提とする supreme.harness の公開 API(設計裁量・指示で委任):
  harness.canonical_metric_spec() -> MetricSpec
  harness.score(trace, metric_spec) -> ScoreResult
    .layer_score(layer: str) -> float   各層 global acc [0,1]
    .overall() -> float                 8層 global acc の単純平均
    .layers -> list[str]                採点した8層名
"""

import pytest

import fixtures_harness as fxh
from supreme import harness


def _spec():
    return harness.canonical_metric_spec()


# ---------------------------------------------------------------------------
# F-004-1: 決定性(2回呼んで完全に同一)
# ---------------------------------------------------------------------------

def test_F004_1_score_is_deterministic_layer_scores():
    """F-004-1: 同じ trace・同じ指標定義で score を2回呼ぶと層スコアが完全一致。

    ADR 0012: ハーネス自体は乱数で揺れない。微小許容ではなく**完全一致**を要求する
    (採点は分類完全一致・整数カウント由来で bit 同一であるべき)。
    """
    spec = _spec()
    trace = fxh.trace_micro_pooling_t2_mode()

    r1 = harness.score(trace, spec)
    r2 = harness.score(trace, spec)

    for layer in r1.layers:
        assert r1.layer_score(layer) == r2.layer_score(layer), (
            f"{layer}: 2回の score 呼び出しで層スコアが一致しない"
        )


def test_F004_1_score_is_deterministic_overall():
    """F-004-1: 同じ入力で総合スコアも2回呼んで完全一致。"""
    spec = _spec()
    trace = fxh.trace_overall_average()

    r1 = harness.score(trace, spec)
    r2 = harness.score(trace, spec)

    assert r1.overall() == r2.overall(), "総合スコアが2回の呼び出しで一致しない"


def test_F004_1_distinct_spec_instances_give_same_result():
    """F-004-1: canonical_metric_spec() を別々に2回構築しても同じ採点になる。

    指標定義の構築自体が決定的(乱数で揺れない)であることを担保する。
    """
    trace = fxh.trace_overall_average()
    r1 = harness.score(trace, harness.canonical_metric_spec())
    r2 = harness.score(trace, harness.canonical_metric_spec())

    assert r1.overall() == r2.overall()
    for layer in r1.layers:
        assert r1.layer_score(layer) == r2.layer_score(layer)


# ---------------------------------------------------------------------------
# F-004-1: micro(global pooling)= Σ正答 / Σ非null
# ---------------------------------------------------------------------------

def test_F004_1_micro_pooling_t2_mode_hand_calculated():
    """F-004-1(ADR 0012 決定A): micro pooling の層スコアが手計算値と一致。

    fixtures_harness.trace_micro_pooling_t2_mode:
      t2_mode 非null=10、正答=6 → 層 acc = 6/10 = 0.6。
    """
    result = harness.score(fxh.trace_micro_pooling_t2_mode(), _spec())
    assert result.layer_score("t2_mode") == pytest.approx(0.6), (
        f"t2_mode micro acc が 0.6 でない: {result.layer_score('t2_mode')}"
    )


def test_F004_1_micro_not_macro_global_pooling():
    """F-004-1(ADR 0012 決定A/G): 不均等長シナリオで micro(global)を採用している。

    trace_micro_vs_macro: シナリオ長 8/2。
      micro(公式) = 6/10 = 0.6
      macro(補助) = (0.5 + 1.0)/2 = 0.75
    層スコアが micro(0.6)であり macro(0.75)でないことを確認する
    (実装が誤って per-scenario 平均=macro を返すと検出される)。
    """
    result = harness.score(fxh.trace_micro_vs_macro(), _spec())
    acc = result.layer_score("t2_mode")
    assert acc == pytest.approx(fxh.MICRO_VS_MACRO_T2_MODE_MICRO), (
        f"t2_mode が micro(0.6)でない: {acc}"
    )
    assert acc != pytest.approx(fxh.MICRO_VS_MACRO_T2_MODE_MACRO), (
        f"t2_mode が macro(0.75)になっている(global pooling でない): {acc}"
    )


# ---------------------------------------------------------------------------
# F-004-1: 完全一致(分類)
# ---------------------------------------------------------------------------

def test_F004_1_exact_match_all_correct_is_one():
    """F-004-1(ADR 0012 決定A): view==gt の全正解 trace は全層 acc=1.0・総合=1.0。"""
    result = harness.score(fxh.trace_all_correct(), _spec())
    for layer in result.layers:
        assert result.layer_score(layer) == pytest.approx(1.0), (
            f"{layer}: 全正解 trace で acc が 1.0 でない"
        )
    assert result.overall() == pytest.approx(1.0)


def test_F004_1_exact_match_mismatch_is_error():
    """F-004-1(ADR 0012 決定A): view != gt は誤答(完全一致採点)。

    trace_overall_average の t2_mode は2フレーム中1誤り → acc=0.5。
    完全一致(類似度や部分点でない)で採点していることを確認する。
    """
    result = harness.score(fxh.trace_overall_average(), _spec())
    assert result.layer_score("t2_mode") == pytest.approx(
        fxh.OVERALL_AVERAGE_T2_MODE_ACC
    )


# ---------------------------------------------------------------------------
# F-004-1: NA分母除外(gt=null はその層の分母に入らない)
# ---------------------------------------------------------------------------

def test_F004_1_na_excluded_from_denominator():
    """F-004-1(ADR 0012 決定A): gt=null フレームはその層の分母から除外される。

    trace_na_excluded_t3: t3_hypothesis 非null=2(正答1/誤り1)→ acc = 1/2 = 0.5。
    NA を分母に入れる実装(1/4=0.25 等)では一致しない。
    """
    result = harness.score(fxh.trace_na_excluded_t3(), _spec())
    assert result.layer_score("t3_hypothesis") == pytest.approx(
        fxh.NA_EXCLUDED_T3_ACC
    ), (
        f"t3_hypothesis NA除外後の acc が 0.5 でない: "
        f"{result.layer_score('t3_hypothesis')}"
    )


def test_F004_1_na_does_not_affect_other_layers():
    """F-004-1: ある層の NA は他層の採点に影響しない。

    trace_na_excluded_t3 では t3_hypothesis 以外の7層は全フレーム正解 → acc=1.0。
    """
    result = harness.score(fxh.trace_na_excluded_t3(), _spec())
    for layer in result.layers:
        if layer == "t3_hypothesis":
            continue
        assert result.layer_score(layer) == pytest.approx(1.0), (
            f"{layer}: t3_hypothesis の NA が他層の採点に波及している"
        )


def test_F004_1_all_null_layer_does_not_crash():
    """F-004-1(NA境界): ある層の gt が全フレーム null でも 0除算で落ちない。

    trace_na_all_null_layer: quality_regime 全null・他層全正解。
    分母0の層の表現は実装裁量(NaN/None/採点除外)だが、score 呼び出しが
    例外で落ちず、他層が正しく採点されることを要求する。
    """
    result = harness.score(fxh.trace_na_all_null_layer(), _spec())
    # 他層(quality_regime 以外)は全正解
    for layer in result.layers:
        if layer == "quality_regime":
            continue
        assert result.layer_score(layer) == pytest.approx(1.0), (
            f"{layer}: 全null層の存在が他層採点に波及している"
        )


# ---------------------------------------------------------------------------
# F-004-1: risk_tier 210規約(短尺T0の特例NA除外をしない・決定B)
# ---------------------------------------------------------------------------

def test_F004_1_risk_tier_no_short_t0_special_exclusion():
    """F-004-1(ADR 0012 決定B): risk_tier は短尺T0特例のNA除外をしない。

    trace_risk_tier_no_short_t0_special:
      短尺シナリオ込みで risk_tier 非null=5・正答=4 → acc = 4/5 = 0.8。
    短尺特例で短尺シナリオを除外すると 3/3=1.0 になり一致しない。
    supreme ハーネスに short-T0 特例を実装しないことを固定する。
    """
    result = harness.score(fxh.trace_risk_tier_no_short_t0_special(), _spec())
    assert result.layer_score("risk_tier") == pytest.approx(
        fxh.RISK_TIER_210_ACC
    ), (
        f"risk_tier に短尺T0特例が入っている疑い(acc={result.layer_score('risk_tier')}, "
        f"期待 0.8)"
    )


# ---------------------------------------------------------------------------
# F-004-1: Anomaly 採点外(決定C)
# ---------------------------------------------------------------------------

def test_F004_1_anomaly_not_in_scored_layers():
    """F-004-1(ADR 0012 決定C): Anomaly 層は採点対象に含まれない(8層のみ)。

    入力 trace に Anomaly フィールドを足しても採点層は8層のまま・Anomaly は
    スコアを作らない(値を埋めない=F-004 異常系の精神)。
    """
    trace = fxh.trace_all_correct()
    # 全フレームに Anomaly フィールドを混入させる
    for frames in trace.values():
        for fr in frames:
            fr["view"]["Anomaly"] = "anomaly_a"
            fr["gt"]["Anomaly"] = "anomaly_b"  # 不一致でも採点されないはず

    result = harness.score(trace, _spec())
    assert "Anomaly" not in result.layers, "Anomaly が採点層に混入している(決定C 違反)"
    # Anomaly を採点していたら不一致で総合が下がる。8層は全正解なので総合=1.0 のまま。
    assert result.overall() == pytest.approx(1.0), (
        "Anomaly が採点に影響している(総合が 1.0 でない)"
    )


# ---------------------------------------------------------------------------
# F-004-1: t1_state 4クラス(決定E)
# ---------------------------------------------------------------------------

def test_F004_1_t1_state_four_classes_scored():
    """F-004-1(ADR 0012 決定E): t1_state は idle/approach/pass/depart で完全一致採点。

    trace_t1_state_four_classes: 非null=4・正答=3 → acc = 3/4 = 0.75。
    """
    result = harness.score(fxh.trace_t1_state_four_classes(), _spec())
    assert result.layer_score("t1_state") == pytest.approx(
        fxh.T1_STATE_FOUR_CLASS_ACC
    ), f"t1_state acc が 0.75 でない: {result.layer_score('t1_state')}"


# ---------------------------------------------------------------------------
# F-004-1: 総合 = 8層 global acc の単純平均(層 macro)
# ---------------------------------------------------------------------------

def test_F004_1_overall_is_simple_average_of_eight_layers():
    """F-004-1(ADR 0012 決定A): 総合 = 8層 global acc の単純平均。

    trace_overall_average: t2_mode=0.5・他7層=1.0
    → 総合 = (0.5 + 1.0×7)/8 = 0.9375。
    """
    result = harness.score(fxh.trace_overall_average(), _spec())
    assert result.overall() == pytest.approx(fxh.OVERALL_AVERAGE_OVERALL), (
        f"総合が 8層単純平均(0.9375)でない: {result.overall()}"
    )


def test_F004_1_overall_equals_mean_of_layer_scores():
    """F-004-1(ADR 0012 決定A): overall() が layer_score 群の算術平均と一致する。

    全null層を含まない素直な trace で、overall == mean(layer_score) を直接検証する。
    """
    result = harness.score(fxh.trace_overall_average(), _spec())
    layer_scores = [result.layer_score(l) for l in result.layers]
    expected = sum(layer_scores) / len(layer_scores)
    assert result.overall() == pytest.approx(expected), (
        "overall() が層スコアの単純平均と一致しない(層 macro でない)"
    )
