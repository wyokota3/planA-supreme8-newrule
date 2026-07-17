"""F-009 T3(ADR 0020)— エピソード集約特徴の機構・性質契約。

学習モジュールゆえ、fit 後の厳密な学習値は F-013 の成功目標であり契約にしない。本ファイルは
エピソード集約特徴(持続conv比率・切替率・flip累積・posterior 集約)の**機構・性質**を契約化する
(F-010 persistence の流儀=符号・大小関係を固定し、厳密な式・値には踏み込まない)。

契約の最終根拠:
  - decisions/0020-f009-t3-episode-learning.md:
      決定1: 集約特徴 = 持続conv比率(エピソード先頭〜現在で conv系 argmax だった割合)、
             切替率(mode 変化数/フレーム数)、flip累積(flip の平均/累積)、posterior 集約
             (平均・分散・トレンド)。トレンド等で ns016群の分離を試みる。
      機構(タスク D): 「持続的に conv が続く系列 → 持続conv比率 上昇」「不安定(mode 頻繁切替)
             な系列 → 切替率/flip累積 上昇」。reset でこれらが初期化(test_F009_reset.py と連動)。
  - 計測背景(ADR 0020): baseline は1ステップ flip のみで「エピw渡る不安定さの累積状態が無い」
      → conv 飛びつき(単一スパイクで6平均超え)/ traffic 見逃し(その tick で flip=0 だとゲート
      落ち)。集約特徴は「持続」を測ることでこれを是正する。
  - specs/SPEC.md F-009 / decisions/0018(有界窓+集約・無限累積なし)/ decisions/0002(ε=U5a)。

スコープ外(ADR 0020・推測でテスト化しない):
  - 各集約特徴の**厳密な式**(conv 比率の重み付け・flip 累積を平均にするか総和にするか・
    トレンドの定義)は ADR 0020 が一意に規定しない。本ファイルは符号・大小関係・単調性だけを
    固定し、厳密値には踏み込まない(F-010 persistence と同じ流儀)。
  - 証拠抽出・T2(上流共有基盤)。mode/posterior を直接与える。
  - ns016群の分離成否(トレンド特徴が実際に分離できるか)は F-013 の成功目標(本ファイル対象外)。
    本ファイルは「posterior トレンド特徴が *存在し* 上昇/下降系列で符号が変わる」機構のみ固定する。

テストが前提とする supreme.t3 の公開 API(設計裁量・指示で委任):
  t3.step(mode, reset, state) -> (hypothesis, next_state)  (test_F009_state.py 参照)
  t3.initial_state() -> state
  t3.episode_features(state) -> features
      現在のエピソード状態の集約特徴を取り出すアクセサ。以下を持つ:
        .conv_ratio   -> float  持続conv比率(エピソード先頭〜現在で conv系だった割合・[0,1])。
        .switch_rate  -> float  切替率(mode 変化数/フレーム数・非負)。
        .flip_accum   -> float  flip 累積(mode が前フレームと変わった度合いの蓄積・非負)。
        .posterior_mean -> float   posterior 集約・平均。
        .posterior_var  -> float   posterior 集約・分散(非負)。
        .posterior_trend -> float  posterior 集約・トレンド(上昇で正・下降で負・平坦で≈0)。
"""

import pytest

from supreme import t3

EPS_ABS = 1e-9
EPS_REL = 1e-6


def _isclose(a, b):
    return abs(a - b) <= EPS_ABS + EPS_REL * max(abs(a), abs(b))


def _mode(label, posterior=0.5):
    return {"mode": label, "posterior": posterior}


def _conv(posterior=0.7):
    return _mode("conv_strong", posterior)


def _quiet(posterior=0.2):
    return _mode("quiet", posterior)


def _traffic(posterior=0.5):
    return _mode("traffic", posterior)


def _run(modes, resets=None):
    """mode 列を初期状態から step で流し、末尾の状態の集約特徴を返す。"""
    if resets is None:
        resets = [False] * len(modes)
    state = t3.initial_state()
    for m, r in zip(modes, resets):
        _h, state = t3.step(m, r, state)
    return t3.episode_features(state)


# ===========================================================================
# 公開アクセサ + 決定性 + 構造(非負・[0,1])
# ===========================================================================

def test_F009_episode_features_exposes_aggregate_accessors():
    """F-009(契約面・ADR 0020 決定1): episode_features は集約特徴アクセサを公開する。

    持続conv比率・切替率・flip累積・posterior 集約(平均/分散/トレンド)を取り出せること
    (これらが学習器=局所ロジスティックの入力特徴になる)。
    """
    feats = _run([_conv(), _conv(), _traffic()])
    for attr in (
        "conv_ratio", "switch_rate", "flip_accum",
        "posterior_mean", "posterior_var", "posterior_trend",
    ):
        assert hasattr(feats, attr), f"episode_features.{attr} が公開されていない"
        assert isinstance(getattr(feats, attr), (int, float)), (
            f"episode_features.{attr} が数値でない: {getattr(feats, attr)!r}"
        )


def test_F009_episode_features_is_deterministic():
    """F-009(ADR 0020 決定3・決定性): 同じ mode 列で2回集約すると集約特徴が完全一致
    (乱数・時刻なし)。
    """
    modes = [_conv(0.7), _traffic(0.5), _conv(0.72), _quiet(0.2)]
    a = _run(modes)
    b = _run(modes)
    for attr in ("conv_ratio", "switch_rate", "flip_accum",
                 "posterior_mean", "posterior_var", "posterior_trend"):
        assert getattr(a, attr) == getattr(b, attr), (
            f"集約特徴 {attr} が2回で不一致(非決定): "
            f"{getattr(a, attr)} != {getattr(b, attr)}"
        )


def test_F009_conv_ratio_in_unit_interval():
    """F-009(ADR 0020 決定1・構造): 持続conv比率は [0,1](conv系だった割合)。"""
    for modes in (
        [_conv()] * 5,
        [_quiet()] * 5,
        [_conv(), _quiet(), _conv(), _traffic(), _conv()],
    ):
        ratio = _run(modes).conv_ratio
        assert 0.0 <= ratio <= 1.0, f"持続conv比率が [0,1] 外: {ratio}(列={modes})"


def test_F009_switch_rate_and_flip_accum_nonnegative():
    """F-009(ADR 0020 決定1・構造): 切替率・flip累積は非負(変化数/フレーム・累積量)。"""
    for modes in (
        [_conv()] * 5,
        [_conv(), _traffic(), _conv(), _traffic()],
        [_quiet(), _conv(), _quiet()],
    ):
        feats = _run(modes)
        assert feats.switch_rate >= 0.0, f"切替率が負: {feats.switch_rate}"
        assert feats.flip_accum >= 0.0, f"flip累積が負: {feats.flip_accum}"


def test_F009_posterior_var_nonnegative():
    """F-009(ADR 0020 決定1・構造): posterior 分散は非負。"""
    feats = _run([_conv(0.3), _conv(0.7), _conv(0.5)])
    assert feats.posterior_var >= 0.0, f"posterior 分散が負: {feats.posterior_var}"


# ===========================================================================
# 機構: 持続的に conv → 持続conv比率 上昇 / 持続的に非conv → 低い
# (baseline の conv 飛びつき=単一スパイクで6平均超えを是正する根拠)
# ===========================================================================

def test_F009_sustained_conv_raises_conv_ratio_to_one():
    """F-009(ADR 0020 決定1・機構・持続conv): エピソード全体で conv が続くと持続conv比率が
    最大(=1.0)に近づく。

    conv のみのエピソードでは conv系 argmax の割合が 1.0。『持続的に conv が続く系列 → 持続conv
    比率 上昇』(タスク D・ADR 0020 機構)を固定する。
    """
    ratio = _run([_conv()] * 8).conv_ratio
    assert _isclose(ratio, 1.0) or ratio > 0.95, (
        f"conv 持続エピソードの持続conv比率が 1.0 近傍でない: {ratio}"
    )


def test_F009_single_conv_spike_does_not_dominate_conv_ratio():
    """F-009(ADR 0020 決定1・機構・飛びつき是正の核心): 非conv が大半のエピソードに conv が
    1回だけ混じっても、持続conv比率は低いまま(持続を要求する=単一スパイクで飛びつかない)。

    baseline は単一スパイク1個で6平均が conv 閾値を超えて『conv 飛びつき』した。持続conv比率は
    『conv系だった割合』なので、1/N の混入では低い。非conv 7 + conv 1 のエピソードで持続conv比率
    が低い(< 0.5)ことを固定する(=持続を要求し飛びつかない)。
    """
    modes = [_quiet()] * 7 + [_conv()]   # conv は最後の1フレームだけ
    ratio = _run(modes).conv_ratio
    assert ratio < 0.5, (
        f"単一 conv スパイク混入で持続conv比率が高すぎる: {ratio}"
        "(持続を要求せず conv に飛びついている=baseline の誤りを是正できていない)"
    )


def test_F009_sustained_conv_ratio_exceeds_sparse_conv():
    """F-009(ADR 0020 決定1・機構・対比): 持続的に conv が続くエピソードの持続conv比率は、
    conv がまばらなエピソードのそれより高い(同じ長さ)。

    ns016群(真に持続=持続conv比率 0.83-0.91)と ns007群(瞬間=0.00-0.20)を分離する根拠。
    持続 conv と まばら conv を持続conv比率で分離できることを大小関係で固定する。
    """
    n = 10
    sustained = [_conv()] * n
    sparse = [_conv(), _quiet(), _quiet(), _quiet(), _quiet(),
              _quiet(), _quiet(), _quiet(), _quiet(), _conv()]  # conv は2/10
    assert _run(sustained).conv_ratio > _run(sparse).conv_ratio, (
        "持続 conv の持続conv比率が まばら conv を上回らない(ns016/ns007 分離不能)"
    )


# ===========================================================================
# 機構: mode 頻繁切替 → 切替率/flip累積 上昇 / 安定 → 低い
# (baseline の traffic 見逃し=その tick で flip=0 だとゲート落ちを是正する根拠)
# ===========================================================================

def test_F009_frequent_switching_raises_switch_rate():
    """F-009(ADR 0020 決定1・機構・不安定): mode が頻繁に切り替わるエピソードの切替率が、
    安定したエピソードのそれより高い。

    『不安定(mode が頻繁に切替)な系列 → 切替率 上昇』(タスク D・ADR 0020 機構)。交互切替列と
    一定列を比べ、交互列の切替率が高いことを固定する(traffic 見逃し是正の根拠)。
    """
    n = 10
    unstable = [_traffic(), _quiet()] * (n // 2)   # 毎フレーム切替
    stable = [_quiet()] * n                          # 切替なし
    assert _run(unstable).switch_rate > _run(stable).switch_rate, (
        "頻繁切替の切替率が安定列を上回らない(不安定を捉えられていない)"
    )


def test_F009_frequent_switching_raises_flip_accum():
    """F-009(ADR 0020 決定1・機構・flip累積): mode が頻繁に切り替わるほど flip累積が大きい。

    baseline は『その tick の1ステップ変化フラグ』のみで累積状態が無いため、flip=0 の tick で
    traffic を見逃した。flip累積はエピソードに渡る不安定さを蓄積する。交互切替列の flip累積 >
    一定列の flip累積 を固定する。
    """
    n = 10
    unstable = [_traffic(), _quiet()] * (n // 2)
    stable = [_quiet()] * n
    assert _run(unstable).flip_accum > _run(stable).flip_accum, (
        "頻繁切替の flip累積が安定列を上回らない(エピソードに渡る不安定さを蓄積できていない)"
    )


def test_F009_stable_episode_has_low_switch_and_flip():
    """F-009(ADR 0020 決定1・機構・安定側): 一定 mode の安定エピソードでは切替率・flip累積が
    ≈0(切替が無い)。

    『持続的に同じ mode → 不安定指標は立たない』(過敏でない側)。一定列の切替率・flip累積が
    ≈0 であることを固定する(頻繁切替の対)。
    """
    feats = _run([_quiet()] * 8)
    assert _isclose(feats.switch_rate, 0.0) or feats.switch_rate < 1e-3, (
        f"安定エピソードの切替率が ≈0 でない: {feats.switch_rate}"
    )
    assert _isclose(feats.flip_accum, 0.0) or feats.flip_accum < 1e-3, (
        f"安定エピソードの flip累積が ≈0 でない: {feats.flip_accum}"
    )


# ===========================================================================
# 機構: posterior 集約(平均・トレンド)
# トレンドは ns016群分離のための追加特徴(ADR 0020 決定1・ユーザー決定)
# ===========================================================================

def test_F009_posterior_mean_tracks_input_posteriors():
    """F-009(ADR 0020 決定1・機構・posterior 平均): 高い posterior が続くエピソードの
    posterior 平均は、低い posterior が続くエピソードのそれより高い。

    posterior 集約・平均が入力 posterior を反映することを大小で固定する(集約の素材が
    効いている)。
    """
    high = [_conv(0.9)] * 6
    low = [_conv(0.1)] * 6
    assert _run(high).posterior_mean > _run(low).posterior_mean, (
        "高 posterior 列の posterior 平均が低 posterior 列を上回らない(集約が効いていない)"
    )


def test_F009_posterior_trend_positive_for_rising_negative_for_falling():
    """F-009(ADR 0020 決定1・機構・トレンド・核心): posterior が上昇し続けるエピソードの
    トレンドは正、下降し続けるエピソードのトレンドは負。

    ADR 0020 はトレンド等の追加集約特徴で ns016群(持続比率では分離不可な6件)の分離を試みると
    決定(ユーザー決定)。トレンド特徴が『上昇/下降の向き』を符号で捉えることを固定する
    (実際に ns016群を分離できるかは F-013 の成功目標=対象外)。
    """
    rising = [_conv(0.1 + 0.1 * i) for i in range(7)]   # posterior 0.1→0.7
    falling = [_conv(0.7 - 0.1 * i) for i in range(7)]   # posterior 0.7→0.1
    trend_up = _run(rising).posterior_trend
    trend_down = _run(falling).posterior_trend
    assert trend_up > 0.0, f"上昇 posterior 列のトレンドが正でない: {trend_up}"
    assert trend_down < 0.0, f"下降 posterior 列のトレンドが負でない: {trend_down}"
    assert trend_up > trend_down, "上昇トレンドが下降トレンドを上回らない(向きを捉えていない)"


def test_F009_posterior_trend_near_zero_for_flat():
    """F-009(ADR 0020 決定1・機構・トレンド平坦): posterior が平坦なエピソードのトレンドは ≈0。

    変化が無ければトレンドは立たない(上昇=正/下降=負の対・平坦=0)。一定 posterior 列で
    トレンド ≈0 を固定する。
    """
    flat = [_conv(0.5)] * 7
    trend = _run(flat).posterior_trend
    assert _isclose(trend, 0.0) or abs(trend) < 1e-2, (
        f"平坦 posterior 列のトレンドが ≈0 でない: {trend}"
    )
