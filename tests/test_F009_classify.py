"""F-009 T3(ADR 0020)— 局所ロジスティック分類器の構造契約。

学習モジュールゆえ、fit で決まる**実際の重み/バイアス**は F-013 の成功目標であり契約にしない。
本ファイルは「**この params(重み/バイアス)ならこの hypothesis**」という**判定構造**を、テストが
与える具体的な params で固定する(=集約特徴+params → hypothesis の決定的写像・F-010 classify 流儀)。

契約の最終根拠:
  - decisions/0020-f009-t3-episode-learning.md:
      決定2: 学習器 = 局所ロジスティック。エピソード集約特徴に学習可能な重み+バイアスで、
             誤りの集中する **conv/traffic/quiet の影響境界(~3)** を同時最適化する。
             **学習が触るのは conv/traffic/quiet 境界(誤りの震源)。他クラスは規則/fallback**。
      決定3: 決定的(乱数なし)。
  - 計測背景(ADR 0020): 持続conv比率↑→conv 寄り / 切替率・flip累積↑→traffic 寄り /
      どちらも低い→quiet 寄り。学習器はこの3境界を同時最適化する。
  - specs/SPEC.md F-009 / decisions/0006(v1.4 T3 10語彙)/ decisions/0002(ε=U5a)。

スコープ外(ADR 0020 から一意に決まらない点・推測でテスト化しない):
  - **実際の学習重み/バイアスの値**は F-013 で測定する成功目標。本ファイルは重み/バイアスを
    テスト側が params として**与え**、その params での判定構造のみを固定する。
  - **v1.4 10語彙のうち conv系/traffic系/quiet系の代表ラベルが具体的にどれか**(conv系=
    conv_participating か crowd_tendency か等)は ADR 0020 が一意に与えない。学習が触るのは
    「conv/traffic/quiet の3境界」であり、ラベル名への割付は規則層(他クラス fallback)に属する。
    本ファイルは:
      (1) classify_t3 の出力が v1.4 10語彙に閉じる(語彙閉包)、
      (2) params(重み/バイアス)で**境界の向き**が決まる(持続conv比率を上げると conv 側ラベルへ、
          切替率/flip累積を上げると traffic 側ラベルへ寄る)、
      (3) **代表 params を与えたとき conv/traffic/quiet 各域で出力ラベルが互いに異なる**
          (3境界が分離されている)
    を固定する。具体的にどのラベル文字列が出るかは params が決める(=テストが params で固定する)。
  - 他クラス(7語彙)の規則/fallback の具体規定は ADR 0020 がスコープ外(本ファイルは触れない)。

テストが前提とする supreme.t3 の公開 API(設計裁量・指示で委任・F-010 classify 流儀):
  t3.classify_t3(features, params) -> str
      features = エピソード集約特徴(test_F009_aggregate.py の episode_features 相当)。
                 {"conv_ratio": float, "switch_rate": float, "flip_accum": float,
                  "posterior_mean": float, "posterior_var": float, "posterior_trend": float}
      params   = 局所ロジスティックの重み+バイアス(+他クラス規則の閾値)。dict。テストが具体値を
                 与える(=「この重みならこの境界」)。
      返り値は v1.4 T3 10語彙のいずれか(str)。
  t3.classify_t3 が参照する代表ラベル定数(conv/traffic/quiet 境界の代表・params が割り付ける):
      params に "conv_label" / "traffic_label" / "quiet_label" を渡すと、その境界で勝った
      クラスに割り付けられる v1.4 ラベルをテストが指定できる(=ラベル名割付は規則層・params 供給)。
"""

import pytest

from supreme import t3


# v1.4 T3 統制語彙(10クラス・decisions/0006・ADR 0020 決定4 / 指示)。
V14_T3_LABELS = {
    "quiet_stable",
    "conv_participating",
    "sustained_alert",
    "env_shift",
    "env_start",
    "crowd_tendency",
    "traffic_unstable",
    "hazard_declining",
    "uncertain_context",
    "alert_required",
}


# テストが与える具体的な params(=「この重み/バイアスならこの境界」を固定するための値)。
# fit 後の実際値ではない(それは F-013 の成功目標)。conv/traffic/quiet の3境界を分離する
# 代表的な線形重み: 持続conv比率↑→conv、切替率/flip累積↑→traffic、どちらも低→quiet。
# ラベル名の割付(どの v1.4 語彙へ)は params が指定する(規則層・割付はスコープ外なので供給)。
PARAMS = {
    # 局所ロジスティックの重み(集約特徴 → 各境界スコア)。
    "w_conv_ratio": 6.0,      # 持続conv比率は conv 境界スコアを上げる
    "w_switch_rate": 5.0,     # 切替率は traffic 境界スコアを上げる
    "w_flip_accum": 4.0,      # flip累積は traffic 境界スコアを上げる
    "bias_conv": -2.0,
    "bias_traffic": -2.0,
    "bias_quiet": 0.5,        # どちらも低いとき quiet が勝つ既定バイアス
    # conv/traffic/quiet の3境界が勝ったときに割り付ける v1.4 ラベル(規則層・テスト供給)。
    "conv_label": "conv_participating",
    "traffic_label": "traffic_unstable",
    "quiet_label": "quiet_stable",
}


def _features(conv_ratio=0.0, switch_rate=0.0, flip_accum=0.0,
              posterior_mean=0.5, posterior_var=0.0, posterior_trend=0.0):
    return {
        "conv_ratio": conv_ratio,
        "switch_rate": switch_rate,
        "flip_accum": flip_accum,
        "posterior_mean": posterior_mean,
        "posterior_var": posterior_var,
        "posterior_trend": posterior_trend,
    }


# ===========================================================================
# 公開シンボルの存在
# ===========================================================================

def test_F009_t3_exposes_classify_t3():
    """F-009(契約面・ADR 0020 決定2): t3 は局所ロジスティック分類の入口 classify_t3() を
    公開する。

    classify_t3(features, params) -> str。集約特徴 + 学習可能な重み/バイアス(params)で
    conv/traffic/quiet 境界を判定する入口。
    """
    assert hasattr(t3, "classify_t3"), "t3.classify_t3 が公開されていない"
    assert callable(t3.classify_t3)


# ===========================================================================
# 語彙閉包: classify_t3 の出力は v1.4 T3 10語彙に閉じる
# ===========================================================================

def test_F009_classify_t3_output_in_v14_vocabulary():
    """F-009(ADR 0006/0020・語彙閉包): classify_t3 の出力は v1.4 T3 10語彙のいずれかのみ。

    conv 域 / traffic 域 / quiet 域 の代表 feature で、出力が常に v1.4 10語彙に閉じることを
    固定する(開いた辞書にしない)。
    """
    cases = [
        _features(conv_ratio=0.9),                         # conv 域
        _features(switch_rate=0.6, flip_accum=4.0),        # traffic 域
        _features(),                                        # quiet 域(どちらも低)
        _features(conv_ratio=0.4, switch_rate=0.3, flip_accum=2.0),  # 混在
    ]
    for f in cases:
        label = t3.classify_t3(f, PARAMS)
        assert label in V14_T3_LABELS, (
            f"classify_t3({f}) が v1.4 T3 語彙外: {label!r}"
        )


# ===========================================================================
# 構造: 与えた params で conv/traffic/quiet 各域が互いに異なるラベルへ分離される
# (3境界が分離されている=ADR 0020 決定2「conv/traffic/quiet 境界を同時最適化」)
# ===========================================================================

def test_F009_classify_t3_sustained_conv_is_conv_label():
    """F-009(ADR 0020 決定2・構造 conv 境界): 持続conv比率が高く切替/flip が低い feature は、
    params が指定した conv 境界ラベル(conv_participating)になる。

    『持続的に conv が続く → conv 寄り』(計測背景)。持続conv比率 0.9・切替 0・flip 0 で
    conv 境界が勝つことを、テスト供給の params(w_conv_ratio=6.0)で固定する。
    """
    f = _features(conv_ratio=0.9, switch_rate=0.0, flip_accum=0.0)
    assert t3.classify_t3(f, PARAMS) == PARAMS["conv_label"]


def test_F009_classify_t3_unstable_is_traffic_label():
    """F-009(ADR 0020 決定2・構造 traffic 境界): 切替率/flip累積が高く持続conv比率が低い
    feature は、params が指定した traffic 境界ラベル(traffic_unstable)になる。

    『mode 頻繁切替・flip 累積 → traffic 寄り』(計測背景: traffic 見逃し是正)。切替率 0.6・
    flip累積 4.0・conv比率 0 で traffic 境界が勝つことを params(w_switch_rate=5.0,
    w_flip_accum=4.0)で固定する。
    """
    f = _features(conv_ratio=0.0, switch_rate=0.6, flip_accum=4.0)
    assert t3.classify_t3(f, PARAMS) == PARAMS["traffic_label"]


def test_F009_classify_t3_calm_is_quiet_label():
    """F-009(ADR 0020 決定2・構造 quiet 境界): 持続conv比率も切替/flip も低い feature は、
    params が指定した quiet 境界ラベル(quiet_stable)になる。

    『どちらの不安定指標も低い → quiet 寄り』。conv比率 0・切替 0・flip 0 で quiet 境界が
    勝つことを params(bias_quiet=0.5)で固定する。
    """
    f = _features(conv_ratio=0.0, switch_rate=0.0, flip_accum=0.0)
    assert t3.classify_t3(f, PARAMS) == PARAMS["quiet_label"]


def test_F009_classify_t3_three_boundaries_are_distinct():
    """F-009(ADR 0020 決定2・構造・3境界分離): conv 域 / traffic 域 / quiet 域 の代表 feature が
    互いに異なるラベルへ分離される(3境界が同時最適化で分かれている)。

    同じ params の下で、conv 代表・traffic 代表・quiet 代表が3つとも異なるラベルになることを
    固定する(conv 飛びつきと traffic 見逃しの衝突を学習器が分離する=ADR 0020 決定2 の核心)。
    """
    conv = t3.classify_t3(_features(conv_ratio=0.9), PARAMS)
    traffic = t3.classify_t3(_features(switch_rate=0.6, flip_accum=4.0), PARAMS)
    quiet = t3.classify_t3(_features(), PARAMS)
    assert conv != traffic, f"conv 域と traffic 域が同じラベル: {conv!r}"
    assert conv != quiet, f"conv 域と quiet 域が同じラベル: {conv!r}"
    assert traffic != quiet, f"traffic 域と quiet 域が同じラベル: {traffic!r}"


# ===========================================================================
# 境界の向き: params の重みを上げると境界が移動する(学習可能性の構造)
# ===========================================================================

def test_F009_classify_t3_conv_ratio_pushes_toward_conv():
    """F-009(ADR 0020 決定2・境界の向き・conv): 持続conv比率を上げていくと、ある点で quiet から
    conv 境界ラベルへ切り替わる(conv境界が持続conv比率に対して単調=重みが正)。

    切替/flip を 0 に固定し、conv比率だけを 0.0 → 0.95 へ上げる。低い conv比率では quiet、高い
    conv比率では conv になり、出力が quiet→conv の向きに変わる(重み w_conv_ratio>0 の効果)。
    """
    low = t3.classify_t3(_features(conv_ratio=0.05), PARAMS)
    high = t3.classify_t3(_features(conv_ratio=0.95), PARAMS)
    assert low == PARAMS["quiet_label"], (
        f"低 conv比率(0.05)が quiet にならない: {low!r}"
    )
    assert high == PARAMS["conv_label"], (
        f"高 conv比率(0.95)が conv にならない: {high!r}"
    )
    assert low != high, "conv比率を上げても conv 境界ラベルへ切り替わらない(重みが効いていない)"


def test_F009_classify_t3_switch_and_flip_push_toward_traffic():
    """F-009(ADR 0020 決定2・境界の向き・traffic): 切替率/flip累積を上げていくと、ある点で
    quiet から traffic 境界ラベルへ切り替わる(traffic 境界が不安定指標に対して単調)。

    conv比率を 0 に固定し、切替率/flip累積を上げる。低い不安定では quiet、高い不安定では
    traffic になり、出力が quiet→traffic の向きに変わる(重み w_switch_rate, w_flip_accum>0)。
    """
    low = t3.classify_t3(_features(switch_rate=0.02, flip_accum=0.1), PARAMS)
    high = t3.classify_t3(_features(switch_rate=0.7, flip_accum=5.0), PARAMS)
    assert low == PARAMS["quiet_label"], (
        f"低不安定(切替0.02/flip0.1)が quiet にならない: {low!r}"
    )
    assert high == PARAMS["traffic_label"], (
        f"高不安定(切替0.7/flip5.0)が traffic にならない: {high!r}"
    )
    assert low != high, "不安定を上げても traffic 境界ラベルへ切り替わらない(重みが効いていない)"


def test_F009_classify_t3_single_conv_spike_not_conv_with_low_ratio():
    """F-009(ADR 0020 決定2・飛びつき是正): 持続conv比率が低い(単一スパイク相当)feature は、
    posterior が高くても conv 境界ラベルにならない(持続を要求する)。

    baseline は単一スパイクの高 posterior で conv へ飛びついた。学習器の入力は『持続conv比率』
    なので、conv比率 0.15(まばら)では posterior_mean=0.9 でも conv にならない(quiet/他のまま)。
    持続を要求し飛びつかない構造を固定する。
    """
    f = _features(conv_ratio=0.15, posterior_mean=0.9)
    label = t3.classify_t3(f, PARAMS)
    assert label != PARAMS["conv_label"], (
        f"低い持続conv比率(0.15)+高 posterior で conv に飛びついた: {label!r}"
        "(持続を要求していない=baseline の飛びつきを是正できていない)"
    )


# ===========================================================================
# 決定性
# ===========================================================================

def test_F009_classify_t3_is_deterministic():
    """F-009(ADR 0020 決定3・決定性): 同じ features + 同じ params で2回 classify_t3 すると
    同一ラベル(乱数・時刻なし)。
    """
    cases = [
        _features(conv_ratio=0.9),
        _features(switch_rate=0.6, flip_accum=4.0),
        _features(),
        _features(conv_ratio=0.4, switch_rate=0.3, flip_accum=2.0),
    ]
    for f in cases:
        first = t3.classify_t3(f, PARAMS)
        second = t3.classify_t3(f, PARAMS)
        assert first == second, (
            f"classify_t3({f}) が2回で不一致(非決定): {first!r} != {second!r}"
        )
