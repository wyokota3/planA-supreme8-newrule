"""F-004 評価ハーネス用フィクスチャ(決定的・手計算可能)。

方針(指示・TEST_STRATEGY「テストデータ管理」):
- 依存は stdlib + pytest のみ。trace は dict リテラルで決定的に合成する。
- データ形状は baseline trace.json に接地(ADR 0005): フレーム列・各フレームは
  層別 view(予測ラベル)+ gt(正解ラベル)を持つ。分類は string、NA は None。
- 採点仕様は ADR 0012(8層 micro acc・完全一致・NA分母除外・risk_tier 210規約・
  Anomaly採点外・t1_state 4クラス)に従い、手計算した期待値をコメントに明記する。

trace 形式(fixtures_gt.make_trace_frame と同形):
  { "<scenario>": [ {"ts": float, "view": {8層}, "gt": {8層}}, ... ], ... }

8層キー: risk_tier / t1_state / t2_mode / t2_role / t2_relation /
          t3_hypothesis / quality_regime / scene_regime
"""

import copy


# 8層の既定ラベル(全層 view==gt の「全正解」基準)。fixtures_gt と同一の値域。
_DEFAULTS = {
    "risk_tier":      "tier0",
    "t1_state":       "idle",          # ADR 0012 決定E: idle/approach/pass/depart
    "t2_mode":        "conv_request",
    "t2_role":        "source_speech",
    "t2_relation":    "addressing_user",
    "t3_hypothesis":  "indoor_quiet",
    "quality_regime": "GOOD",
    "scene_regime":   "STABLE",
}


def frame(ts, *, view_overrides=None, gt_overrides=None):
    """1フレームを作る。view/gt の任意の層を上書きできる。

    gt の層を None にすると「その層は NA(分母除外)」を表現する(ADR 0012)。
    """
    view = copy.copy(_DEFAULTS)
    gt = copy.copy(_DEFAULTS)
    if view_overrides:
        view.update(view_overrides)
    if gt_overrides:
        gt.update(gt_overrides)
    return {"ts": float(ts), "view": view, "gt": gt}


def trace_all_correct():
    """2シナリオ×2フレーム、全層 view==gt(全層 acc=1.0、総合=1.0)。"""
    return {
        "sc1": [frame(0.0), frame(1.0)],
        "sc2": [frame(0.0), frame(1.0)],
    }


def trace_micro_pooling_t2_mode():
    """micro(global pooling)を検証する trace。

    t2_mode を全10フレームで合成し、うち非null=10・正答=6 → 層 acc=6/10=0.6。
    ADR 0012 決定A: 層スコア = Σ正答 / Σ非null(全シナリオ×全フレームでプール)。

    内訳(t2_mode のみ操作・他層は全フレーム正解):
      sc_a: 5フレーム → 正答3 / 誤り2
      sc_b: 5フレーム → 正答3 / 誤り2
      合算 = 正答6 / 非null10 = 0.6
    macro(per-scenario平均)でも 0.6 になるが、micro と区別するため
    別フィクスチャ(trace_micro_vs_macro)で両者を分離検証する。
    """
    def mode_frame(ts, correct):
        # gt は常に conv_request。correct=False のとき view を別クラスにする。
        v = "conv_request" if correct else "conv_ongoing"
        return frame(ts, view_overrides={"t2_mode": v})

    return {
        "sc_a": [
            mode_frame(0.0, True), mode_frame(1.0, True), mode_frame(2.0, True),
            mode_frame(3.0, False), mode_frame(4.0, False),
        ],
        "sc_b": [
            mode_frame(0.0, True), mode_frame(1.0, True), mode_frame(2.0, True),
            mode_frame(3.0, False), mode_frame(4.0, False),
        ],
    }


def trace_micro_vs_macro():
    """micro と macro が**異なる値**になる trace(global pooling の証明)。

    t2_mode のみ操作。シナリオ長が不均等:
      sc_long : 8フレーム、正答4 / 誤り4
      sc_short: 2フレーム、正答2 / 誤り0
    micro(global): (4+2)正答 / (8+2)非null = 6/10 = 0.6
    macro(per-scenario平均): (4/8 + 2/2)/2 = (0.5 + 1.0)/2 = 0.75
    ADR 0012 決定A/G は micro(0.6)を公式採点とする。両者が異なるので
    実装が macro を返すと検出できる。
    """
    def mf(ts, correct):
        v = "conv_request" if correct else "conv_ongoing"
        return frame(ts, view_overrides={"t2_mode": v})

    return {
        "sc_long": [
            mf(0.0, True), mf(1.0, True), mf(2.0, True), mf(3.0, True),
            mf(4.0, False), mf(5.0, False), mf(6.0, False), mf(7.0, False),
        ],
        "sc_short": [
            mf(0.0, True), mf(1.0, True),
        ],
    }


# micro/macro の手計算期待値(テストから参照)
MICRO_VS_MACRO_T2_MODE_MICRO = 6 / 10  # = 0.6 (公式)
MICRO_VS_MACRO_T2_MODE_MACRO = (4 / 8 + 2 / 2) / 2  # = 0.75 (補助・公式でない)


def trace_na_excluded_t3():
    """NA分母除外を検証する trace(t3_hypothesis)。

    ADR 0012 決定A: gt=null のフレームはその層の分母に入らない。
    t3_hypothesis を操作:
      sc1: 4フレーム
        ts=0.0 gt=indoor_quiet  view=indoor_quiet   → 非null・正答
        ts=1.0 gt=None          view=indoor_quiet   → NA(分母外)
        ts=2.0 gt=None          view=outdoor_busy   → NA(分母外)
        ts=3.0 gt=indoor_quiet  view=outdoor_busy   → 非null・誤り
    非null=2、正答=1 → 層 acc = 1/2 = 0.5
    (もし NA を分母に入れてしまうと 1/4=0.25 / 2/4=0.5 などになり一致しない)
    """
    return {
        "sc1": [
            frame(0.0),  # 全層正解(t3_hypothesis=indoor_quiet)
            frame(1.0, gt_overrides={"t3_hypothesis": None}),
            frame(2.0, view_overrides={"t3_hypothesis": "outdoor_busy"},
                  gt_overrides={"t3_hypothesis": None}),
            frame(3.0, view_overrides={"t3_hypothesis": "outdoor_busy"}),
        ],
    }


# NA除外の手計算期待値
NA_EXCLUDED_T3_NONNULL = 2
NA_EXCLUDED_T3_CORRECT = 1
NA_EXCLUDED_T3_ACC = 1 / 2  # = 0.5


def trace_na_all_null_layer():
    """ある層の gt が全フレーム null(その層は分母0)。

    ADR 0012 の NA 除外を素直に進めると分母0。harness は「分母0の層」を
    どう表現するか(NaN/None/採点対象から外す)を実装裁量とするが、
    少なくとも**0除算で落ちない**ことと、他層は非nullで採点されることを要求する。
    quality_regime を全null・他層は全正解にする。
    """
    return {
        "sc1": [
            frame(0.0, gt_overrides={"quality_regime": None}),
            frame(1.0, gt_overrides={"quality_regime": None}),
        ],
    }


def trace_risk_tier_no_short_t0_special():
    """risk_tier 210規約(決定B): 短尺T0の特例NA除外を**しない**。

    ADR 0012 決定B: planA evaluate.py 規約で risk_tier は非null全件を分母に。
    短尺(=フレーム数が少ない)シナリオでも risk_tier の非nullを除外しない。
    ここでは「risk_tier の gt が非null のフレームは全て分母に入る」ことを
    短尺シナリオ込みで検証する。
      sc_short(2フレーム): risk_tier gt 全て非null・1正答1誤り
      sc_long (3フレーム): risk_tier gt 全て非null・全正答
    非null=5、正答=4 → risk_tier acc = 4/5 = 0.8
    (もし短尺特例で sc_short を除外すると 3/3=1.0 になり一致しない)
    """
    def rt(ts, correct):
        v = "tier0" if correct else "tier1"
        return frame(ts, view_overrides={"risk_tier": v})

    return {
        "sc_short": [rt(0.0, True), rt(1.0, False)],
        "sc_long": [rt(0.0, True), rt(1.0, True), rt(2.0, True)],
    }


RISK_TIER_210_NONNULL = 5
RISK_TIER_210_CORRECT = 4
RISK_TIER_210_ACC = 4 / 5  # = 0.8


def trace_overall_average():
    """総合 = 8層 global acc の単純平均(層 macro)を検証する trace。

    ADR 0012 決定A: 総合 = 8層 global acc の単純平均。
    操作: 1シナリオ×2フレーム。
      t2_mode のみ ts=1.0 で誤り(他フレーム/他層は全正解)。
    各層 acc:
      t2_mode = 1/2 = 0.5、それ以外7層 = 1.0
    総合 = (0.5 + 1.0×7) / 8 = 7.5/8 = 0.9375
    """
    return {
        "sc1": [
            frame(0.0),
            frame(1.0, view_overrides={"t2_mode": "conv_ongoing"}),
        ],
    }


OVERALL_AVERAGE_T2_MODE_ACC = 0.5
OVERALL_AVERAGE_OVERALL = (0.5 + 1.0 * 7) / 8  # = 0.9375


def trace_t1_state_four_classes():
    """t1_state 採点語彙 = idle/approach/pass/depart(ADR 0012 決定E)。

    GT 出現4クラスで完全一致採点。
      ts=0.0 gt=idle     view=idle     → 正答
      ts=1.0 gt=approach view=approach → 正答
      ts=2.0 gt=pass     view=depart   → 誤り
      ts=3.0 gt=depart   view=depart   → 正答
    非null=4、正答=3 → t1_state acc = 3/4 = 0.75
    """
    return {
        "sc1": [
            frame(0.0, view_overrides={"t1_state": "idle"},
                  gt_overrides={"t1_state": "idle"}),
            frame(1.0, view_overrides={"t1_state": "approach"},
                  gt_overrides={"t1_state": "approach"}),
            frame(2.0, view_overrides={"t1_state": "depart"},
                  gt_overrides={"t1_state": "pass"}),
            frame(3.0, view_overrides={"t1_state": "depart"},
                  gt_overrides={"t1_state": "depart"}),
        ],
    }


T1_STATE_FOUR_CLASS_ACC = 3 / 4  # = 0.75


# ---------------------------------------------------------------------------
# F-004-2: T3 再現判定用の「2回流した出力」フィクスチャ
#
# 形状(設計裁量・指示で委任): supreme を実行せず、2回分の出力(run)を受け取る。
#   1 run = フレーム列。各フレームは
#     {"ts": float,
#      "continuous": {"<項目>": float, ...},   # T3 posterior 等(ε 許容判定)
#      "categorical": {"<項目>": str, ...}}     # t3_hypothesis 等(完全一致判定)
#   harness.check_reproduction(run_a, run_b, eps_abs=..., eps_rel=...) が
#   両 run を突合し再現可否を返す。
# ---------------------------------------------------------------------------

def repro_run(*, t3_posterior, stability, hypothesis, ts=0.0):
    """再現判定用の1フレームだけの run を作る(連続値+分類)。"""
    return [{
        "ts": float(ts),
        "continuous": {"t3_posterior": float(t3_posterior),
                       "stability": float(stability)},
        "categorical": {"t3_hypothesis": hypothesis},
    }]
