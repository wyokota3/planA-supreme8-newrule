"""F-010 scene 改良(ADR 0019)— HGF 3層カーネルの性質契約。

これは「学習モジュール」のテストである。固定ルール(mode/relation/quality)と違い、
F-010 は学習(fit)で param が決まるため、**fit 後の厳密な学習値(HGF param・regime 閾値)は
F-013 で測定する成功目標であり、ユニットテストの契約にしない**。本ファイルは HGF カーネルの
**性質・構造・決定性**(与えた param での挙動)を契約化する。

契約の最終根拠:
  - decisions/0019-f010-scene-hgf-learning.md(手法の正):
      決定1: アプローチ = 持続性特徴 + HGF 階層ボラティリティ学習分類器。
             **HGF 3層カーネル**(階層 Gaussian filter)で scene 診断信号から潜在水準 μ1 と
             その変化率・ボラティリティ(層2: log-volatility / 精度 σ)を階層推定する。
             **層2のボラティリティが「持続的変化」(1ステップ drift が見逃す sustained
             non-stationarity)を捉える**=見逃しの根本対処。
      決定3: 学習(fit)は決定的手順(乱数なし)。再現性(F-004-2)のため。
      決定4: supreme が HGF カーネルを独立再実装(baseline/external を import しない・
             F-006 と同じ独立性の流儀)。
  - specs/SPEC.md F-010 / decisions/0018(U24: 学習可能 param のみ・k=0.5)/
    decisions/0006(v1.4 scene 語彙 STABLE/CHANGING/DEGRADING)/
    decisions/0002(ε=U5a・連続値の許容比較)。

スコープ外(ADR 0019・推測でテスト化しない):
  - 診断抽出(6診断 → health_raw)。テストは signal/features を直接与える(上流共有基盤)。
  - fit 後の厳密な学習値・実際の scene acc 改善(F-013 で測定する成功目標)。
  - HGF の更新式の具体形・初期 belief・層2/層3 の内部表現は ADR 0019 が一意に規定しない。
    本ファイルは belief_trajectory から μ1(潜在水準)とボラティリティ推定を取り出す
    アクセサ(.mu1 / .volatility)のみを契約とし、内部更新式には踏み込まず、性質
    (決定性・水準追従・変化列のボラティリティ > 定常列のボラティリティ)だけを固定する。

テストが前提とする supreme.scene の公開 API(設計裁量・指示で委任・既存の流儀に合わせる):
  scene.hgf_filter(signal_sequence, params) -> belief_trajectory
      signal_sequence = float の列(scene 診断信号 health_raw / H_post の系列)。
      params          = HGF パラメータ(κ1,κ2,ω1,ω2,ω3,obs_noise 等)。dict で与える。
      belief_trajectory は各ステップの belief を持つ列で、以下を取り出せる:
        .mu1        -> list[float]   各ステップの潜在水準推定(層1)。
        .volatility -> list[float]   各ステップのボラティリティ推定(層2・非負)。
      len(.mu1) == len(.volatility) == len(signal_sequence)。
  scene.default_hgf_params() -> dict
      決定的な既定 HGF パラメータ(fit 前の初期値)。テストはこれを与えてカーネル挙動を見る。

ε(U5a・ADR 0002)で連続値を許容比較する(GPU 非決定性ではなく、決定的カーネルの
完全一致は ε=0 相当だが、性質の大小比較には ε マージンを使う)。
"""

import pytest

from supreme import scene

# ε(U5a・ADR 0002): |a−b| ≤ ε_abs + ε_rel·max(|a|,|b|)。
EPS_ABS = 1e-9
EPS_REL = 1e-6


def _isclose(a, b):
    return abs(a - b) <= EPS_ABS + EPS_REL * max(abs(a), abs(b))


def _params():
    """既定 HGF パラメータ(決定的・fit 前初期値)。"""
    return scene.default_hgf_params()


# ===========================================================================
# A) 決定性: 同じ入力列 + 同じ params で2回流すと belief 軌跡が完全一致
# (乱数・時刻なし・ADR 0019 決定3 再現性)
# ===========================================================================

def test_F010_hgf_filter_is_deterministic_identical_trajectory():
    """F-010(ADR 0019 決定1/決定3・決定性): 同じ入力列 + 同じ params で hgf_filter を
    2回流すと belief 軌跡(μ1・ボラティリティ)が完全一致する(乱数・時刻なし)。

    HGF カーネルは決定的フィルタ。再現性(F-004-2 の精神)のため、同一入力・同一 param で
    μ1 列・volatility 列が完全一致(ε=0 相当の厳密一致)であることを固定する。
    """
    seq = [0.1, 0.2, 0.15, 0.4, 0.42, 0.41, 0.9, 0.3, 0.31, 0.30]
    params = _params()
    a = scene.hgf_filter(seq, params)
    b = scene.hgf_filter(seq, params)
    assert list(a.mu1) == list(b.mu1), "同一入力・同一 param で μ1 列が一致しない(非決定)"
    assert list(a.volatility) == list(b.volatility), (
        "同一入力・同一 param で volatility 列が一致しない(非決定)"
    )


def test_F010_hgf_trajectory_length_matches_input():
    """F-010(ADR 0019 決定1・構造): belief 軌跡の長さが入力列長と一致する。

    各ステップに対し潜在水準 μ1 とボラティリティ推定が1つずつ出る(階層フィルタの
    逐次更新)。μ1 列・volatility 列の長さが入力長と等しいことを固定する。
    """
    seq = [0.3, 0.31, 0.30, 0.29, 0.32]
    traj = scene.hgf_filter(seq, _params())
    assert len(list(traj.mu1)) == len(seq)
    assert len(list(traj.volatility)) == len(seq)


def test_F010_hgf_volatility_is_nonnegative():
    """F-010(ADR 0019 決定1・構造): ボラティリティ推定(層2)は各ステップで非負。

    ボラティリティ(分散/精度の逆数相当)は負にならない。定常・変化どちらの列でも
    全ステップで >= 0 であることを固定する。
    """
    for seq in (
        [0.3, 0.3, 0.3, 0.3, 0.3],                  # 定常
        [0.1, 0.3, 0.5, 0.7, 0.9],                  # 持続変化
    ):
        traj = scene.hgf_filter(seq, _params())
        for v in traj.volatility:
            assert v >= 0.0, f"ボラティリティ推定が負: {v}(列={seq})"


# ===========================================================================
# A) 水準追従: 入力が一定水準に収束すると μ1 がその水準に追従(単調に近づく)
# ===========================================================================

def test_F010_hgf_mu1_tracks_constant_level():
    """F-010(ADR 0019 決定1・水準追従): 入力が一定水準 L に収束すると μ1(潜在水準推定)が
    その水準 L に追従する(末尾の μ1 が L に近づく)。

    一定入力列 L=0.7 を十分長く流したとき、最終 μ1 が初期 μ1 より L に近いことを固定する
    (潜在水準推定が観測水準を追う=HGF 層1の役割)。
    """
    L = 0.7
    seq = [L] * 30
    traj = scene.hgf_filter(seq, _params())
    mu1 = list(traj.mu1)
    first_gap = abs(mu1[0] - L)
    last_gap = abs(mu1[-1] - L)
    assert last_gap < first_gap or _isclose(last_gap, 0.0), (
        f"一定水準 L={L} に μ1 が追従していない: 初期差 {first_gap} → 末尾差 {last_gap}"
    )


def test_F010_hgf_mu1_moves_toward_level_monotone_enough():
    """F-010(ADR 0019 決定1・水準追従・単調に近づく): 一定水準入力で μ1 と水準 L の差が
    末尾に向けて(概ね)縮む。差の最大値が初期差以下であること。

    厳密な単調性は更新式(裁量)依存のため要求しないが、「初期差を超えて発散しない・
    最終的に縮む」=水準追従の性質を固定する(初期差 > 末尾差)。
    """
    L = 0.2
    seq = [0.9] + [L] * 40  # 高い初期値から L へ収束させる
    traj = scene.hgf_filter(seq, _params())
    mu1 = list(traj.mu1)
    # ジャンプ直後(index 1)の差より末尾の差が小さい=L へ寄った。
    gap_after_jump = abs(mu1[1] - L)
    last_gap = abs(mu1[-1] - L)
    assert last_gap < gap_after_jump, (
        f"L={L} への収束で末尾の差 {last_gap} が直後の差 {gap_after_jump} を下回らない"
    )


# ===========================================================================
# A) ボラティリティ応答(核心・見逃し是正の機構):
#   持続的に変化する入力列 → 層2ボラティリティが上昇
#   定常入力列 → 低下/低位に留まる
#   性質(変化列の vol > 定常列の vol)を大小関係で固定(厳密値でなく)
# ===========================================================================

def _terminal_volatility(seq):
    """系列を流したときの末尾ボラティリティ推定(層2が落ち着いた値)。"""
    traj = scene.hgf_filter(seq, _params())
    return list(traj.volatility)[-1]


def test_F010_hgf_volatility_higher_for_changing_than_stationary():
    """F-010(ADR 0019 決定1・ボラティリティ応答・核心): 持続的に変化する入力列の層2
    ボラティリティ推定が、定常入力列のそれより**高い**。

    これが baseline の1ステップ drift が見逃す「持続的非定常」を捉える機構。
    定常列(同水準を維持)と持続変化列(単調にずれ続ける)を同じ長さ・同じ param で流し、
    変化列の末尾ボラティリティ > 定常列の末尾ボラティリティ を固定する(厳密値でなく大小)。
    """
    n = 30
    stationary = [0.5] * n
    changing = [0.5 + 0.02 * i for i in range(n)]  # 持続的に上昇し続ける
    vol_stationary = _terminal_volatility(stationary)
    vol_changing = _terminal_volatility(changing)
    assert vol_changing > vol_stationary, (
        f"持続変化列のボラティリティ {vol_changing} が定常列 {vol_stationary} を"
        "上回らない(層2が持続的非定常を捉える機構が働いていない)"
    )


def test_F010_hgf_volatility_low_for_stationary_input():
    """F-010(ADR 0019 決定1・ボラティリティ応答・定常側): 定常入力列では層2ボラティリティ
    推定が低位に留まる(変化列より明確に低い)。

    完全な定常列を流すと、ボラティリティ推定の末尾値が「微小変動だけの準定常列」よりも
    低い(=定常を定常と認識する)ことを固定する。ノイズの無い定常で過大なボラティリティを
    出さない=過敏(STABLE→CHANGING)を抑える側の性質。
    """
    n = 30
    flat = [0.5] * n
    drifting = [0.5 + 0.03 * i for i in range(n)]
    assert _terminal_volatility(flat) < _terminal_volatility(drifting), (
        "定常列のボラティリティが drift 列以上(定常を定常と認識できていない)"
    )


def test_F010_hgf_volatility_responds_to_sustained_not_single_step():
    """F-010(ADR 0019 決定1・核心・1ステップ drift との差別化): 単発の1ステップ変化より、
    同じ総変化量を**持続的に**分配した列の方が、層2ボラティリティ推定が高い。

    baseline は隣接2フレーム差(1ステップ drift)で判定し、平坦に張り付くと drift→0 に減衰
    して持続的変化を見逃す。HGF 層2は「持続性」を蓄積するので、総変化量が同じでも
    『持続的に変化する列』の末尾ボラティリティ > 『1回だけ跳ねて平坦に戻る列』の末尾
    ボラティリティ になる(持続性を捉える機構)。
    """
    n = 30
    base = 0.4
    total = 0.6
    # 持続的に総変化量 total を分配して上昇し続ける列。
    sustained = [base + (total / (n - 1)) * i for i in range(n)]
    # 同じ総変化量を最初の1ステップで跳ね、その後は平坦に張り付く列。
    single_step = [base] + [base + total] * (n - 1)
    vol_sustained = _terminal_volatility(sustained)
    vol_single = _terminal_volatility(single_step)
    assert vol_sustained > vol_single, (
        f"持続変化列のボラティリティ {vol_sustained} が、1ステップで跳ねて平坦化した列の"
        f"末尾ボラティリティ {vol_single} を上回らない(持続的非定常の捕捉=見逃し是正の"
        "核心が働いていない)"
    )
