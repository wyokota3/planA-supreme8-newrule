"""F-010 scene 改良(ADR 0019)— 持続性特徴の性質契約。

学習モジュールゆえ、fit 後の厳密な学習値は F-013 の成功目標であり契約にしない。本ファイルは
持続性特徴(slow nominal EMA + 逸脱の持続度)の**機構・性質**を契約化する。

契約の最終根拠:
  - decisions/0019-f010-scene-hgf-learning.md:
      決定1: 持続性特徴 = nominal 水準からの逸脱(遅い nominal EMA + 逸脱の持続度)を併用。
      計測背景: baseline の見逃しは「平坦・中水準 H_post」の別領域にある。1ステップ drift が
                平坦に張り付くと drift→0 に減衰して持続的逸脱を表せない。持続性特徴が
                『平坦だが nominal でない水準に張り付く』ケースを CHANGING 側へ寄せる根拠。
  - specs/SPEC.md F-010 / decisions/0006(v1.4 scene 語彙)/ decisions/0002(ε=U5a)。

スコープ外(ADR 0019・推測でテスト化しない):
  - nominal EMA の α・逸脱の集約式の具体形は ADR 0019 が一意に規定しない。本ファイルは
    persistence の符号・大小関係(平坦・非nominal → 正 / 平坦・nominal → ≈0 / 逸脱が長く
    続くほど大)だけを固定し、厳密値・更新式には踏み込まない。
  - 診断抽出(6診断 → health_raw)はスコープ外。signal を直接与える。

テストが前提とする supreme.scene の公開 API(設計裁量・指示で委任):
  scene.persistence(signal_sequence, params) -> persistence_trajectory
      signal_sequence = float の列(scene 診断信号)。
      params          = 持続性特徴のパラメータ(nominal EMA α・nominal 水準・集約等)。dict。
      返り値は各ステップの持続逸脱量を取り出せる列で、.value -> list[float]。
        持続逸脱量 = nominal 水準からの逸脱がどれだけ「持続して」蓄積したかの非負スカラ。
        平坦・nominal に張り付けば ≈0、平坦・非nominal に張り付けば正(蓄積)。
      len(.value) == len(signal_sequence)。
  scene.default_persistence_params() -> dict
      決定的な既定パラメータ(nominal 水準を含む)。テストはこれを与える。
      .nominal -> float でこの param が表す nominal 水準を取り出せる(平坦テスト用)。

ε(U5a・ADR 0002)で「≈0」「正」の判定マージンを取る。
"""

import pytest

from supreme import scene

EPS_ABS = 1e-9
EPS_REL = 1e-6


def _isclose(a, b):
    return abs(a - b) <= EPS_ABS + EPS_REL * max(abs(a), abs(b))


def _params():
    return scene.default_persistence_params()


def _terminal_persistence(seq, params=None):
    """系列の末尾の持続逸脱量(蓄積が落ち着いた値)。"""
    p = params if params is not None else _params()
    traj = scene.persistence(seq, p)
    return list(traj.value)[-1]


# ===========================================================================
# 決定性 + 構造
# ===========================================================================

def test_F010_persistence_is_deterministic():
    """F-010(ADR 0019 決定1/決定3・決定性): 同じ入力列 + 同じ params で persistence を
    2回計算すると持続逸脱列が完全一致(乱数・時刻なし)。
    """
    seq = [0.3, 0.5, 0.5, 0.5, 0.5, 0.2, 0.2]
    params = _params()
    a = scene.persistence(seq, params)
    b = scene.persistence(seq, params)
    assert list(a.value) == list(b.value), "持続逸脱列が非決定(2回で不一致)"


def test_F010_persistence_length_matches_input():
    """F-010(ADR 0019 決定1・構造): 持続逸脱列の長さが入力列長と一致する。"""
    seq = [0.3, 0.31, 0.30, 0.29, 0.32, 0.33]
    traj = scene.persistence(seq, _params())
    assert len(list(traj.value)) == len(seq)


def test_F010_persistence_is_nonnegative():
    """F-010(ADR 0019 決定1・構造): 持続逸脱量は各ステップで非負(蓄積量・大きさ)。"""
    nominal = _params().nominal
    for seq in (
        [nominal] * 10,                          # 平坦・nominal
        [nominal + 0.3] * 10,                    # 平坦・非nominal
        [nominal + 0.1 * i for i in range(10)],  # 漸増
    ):
        traj = scene.persistence(seq, _params())
        for v in traj.value:
            assert v >= 0.0, f"持続逸脱量が負: {v}(列={seq})"


# ===========================================================================
# 機構: 平坦・非nominal → 持続逸脱が正 / 平坦・nominal → 持続逸脱 ≈ 0
# (baseline の見逃し=平坦・中水準を CHANGING 側へ寄せる根拠)
# ===========================================================================

def test_F010_persistence_flat_at_nominal_is_near_zero():
    """F-010(ADR 0019 決定1・機構): 入力が nominal 水準に平坦に張り付くと持続逸脱 ≈ 0。

    nominal そのものに張り付けば逸脱が無く、持続逸脱は蓄積されない(≈0)。
    この『平坦・nominal は持続逸脱≈0』が、安定 nominal を STABLE 側へ置く根拠。
    """
    nominal = _params().nominal
    seq = [nominal] * 30
    val = _terminal_persistence(seq)
    assert _isclose(val, 0.0) or val < 1e-3, (
        f"平坦・nominal 列の末尾持続逸脱が ≈0 でない: {val}"
    )


def test_F010_persistence_flat_off_nominal_is_positive():
    """F-010(ADR 0019 決定1・機構・核心): 入力が『平坦だが nominal でない水準』に
    張り付くと持続逸脱が**正**に蓄積される。

    baseline の1ステップ drift は平坦列で 0 に減衰し、この『平坦・中水準 H_post に張り付く
    見逃し群』を表せない。持続性特徴は nominal からの逸脱が続く限り蓄積するため、
    平坦・非nominal 列で末尾持続逸脱 > 0 になる(見逃しを CHANGING 側へ寄せる根拠)。
    """
    nominal = _params().nominal
    off = nominal + 0.3  # nominal から明確に外れた水準に張り付く
    seq = [off] * 30
    val = _terminal_persistence(seq)
    assert val > 0.0 and not _isclose(val, 0.0), (
        f"平坦・非nominal({off})列の末尾持続逸脱が正でない: {val}"
        "(baseline 見逃し群=平坦・中水準を捉える機構が働いていない)"
    )


def test_F010_persistence_off_nominal_exceeds_at_nominal():
    """F-010(ADR 0019 決定1・機構・対比): 平坦・非nominal の持続逸脱 > 平坦・nominal の
    持続逸脱(同じ長さ・同じ param)。

    nominal に居続ける列(STABLE 側)と、nominal でない水準に居続ける列(見逃し=CHANGING 側)を
    持続逸脱で分離できることを大小関係で固定する。
    """
    nominal = _params().nominal
    n = 30
    at_nominal = [nominal] * n
    off_nominal = [nominal + 0.3] * n
    assert _terminal_persistence(off_nominal) > _terminal_persistence(at_nominal), (
        "平坦・非nominal の持続逸脱が 平坦・nominal を上回らない(分離不能)"
    )


# ===========================================================================
# 機構: 逸脱が「持続するほど」蓄積する(持続度=時間文脈)
# ===========================================================================

def test_F010_persistence_accumulates_with_sustained_deviation():
    """F-010(ADR 0019 決定1・持続度): 同じ非nominal 水準への逸脱でも、**長く持続するほど**
    持続逸脱量が大きくなる。

    逸脱が短い列と長い列を比べ、長く続く逸脱の方が蓄積が大きいことを固定する。
    『瞬間差分(1ステップ)』でなく『持続(時間文脈)』を測る特徴であることの核心。
    """
    nominal = _params().nominal
    off = nominal + 0.3
    short_dev = [nominal] * 20 + [off] * 3   # 逸脱が短い(3ステップ)
    long_dev = [nominal] * 3 + [off] * 20    # 逸脱が長い(20ステップ)
    assert _terminal_persistence(long_dev) > _terminal_persistence(short_dev), (
        "長く持続した逸脱の持続逸脱量が、短い逸脱を上回らない(持続度=時間文脈が"
        "効いていない)"
    )


def test_F010_persistence_single_spike_less_than_sustained():
    """F-010(ADR 0019 決定1・1ステップ vs 持続): 単発スパイク(1ステップだけ逸脱して戻る)の
    持続逸脱は、持続的逸脱の持続逸脱より小さい。

    1ステップだけ外れて nominal に戻る列は持続逸脱が蓄積しにくく、同水準に張り付き続ける列
    より末尾持続逸脱が小さい(過敏=単発スパイクで CHANGING にしない側の性質)。
    """
    nominal = _params().nominal
    off = nominal + 0.3
    n = 30
    spike = [nominal] * (n - 1) + [off]            # 末尾で1回だけ逸脱
    sustained = [nominal] * 5 + [off] * (n - 5)    # 逸脱が持続
    assert _terminal_persistence(sustained) > _terminal_persistence(spike), (
        "持続的逸脱の持続逸脱が、単発スパイクを上回らない(持続性が効いていない)"
    )
