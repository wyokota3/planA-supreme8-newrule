"""F-010 scene 改良(ADR 0019)— 3クラス分類(STABLE/CHANGING/DEGRADING)の構造契約。

学習モジュールゆえ、fit で決まる**実際の閾値**は F-013 の成功目標であり契約にしない。本ファイルは
「**この閾値(param)ならこの regime**」という**判定構造**を、テストが与える具体的な閾値 param で
固定する(=構造の決定的写像 features+params → regime)。

契約の最終根拠:
  - decisions/0019-f010-scene-hgf-learning.md:
      決定1: 3クラス分類 = (HGF 水準 μ1, HGF ボラティリティ, 持続性)を入力に
             **STABLE / CHANGING / DEGRADING** を判定。DEGRADING を3クラス目標に含める
             (deg 検出も同時最適化)。
      決定3: 決定的(乱数なし)。
  - specs/SPEC.md F-010 / decisions/0006(v1.4 scene 語彙 = STABLE/CHANGING/DEGRADING)/
    decisions/0002(ε=U5a)。

スコープ外(ADR 0019・推測でテスト化しない):
  - **実際の学習閾値**(fit 後の境界値)は F-013 で測定する成功目標。本ファイルは閾値を
    テスト側が param として**与え**、その閾値での判定構造のみを固定する(「学習値が正しいか」は
    対象外)。
  - 閾値の優先順位(DEGRADING と CHANGING の競合時どちらを優先するか)の厳密規定は ADR 0019 が
    一意に与えない。本ファイルは各 regime を**単独で明確に成立させる**feature 値でテストし、
    競合させる人工ケースは作らない(推測でテスト化しない)。

テストが前提とする supreme.scene の公開 API(設計裁量・指示で委任):
  scene.classify_scene(features, params) -> str
      features = {"level": float, "volatility": float, "persistence": float}
                 level=HGF μ1(潜在水準)、volatility=HGF 層2、persistence=持続逸脱量。
      params   = 判定の閾値/境界(dict)。テストが具体値を与える(=「この閾値ならこの regime」)。
                 例: {"vol_high": 0.05, "persist_high": 0.2, "level_low": 0.3}
      返り値は v1.4 scene 語彙 STABLE / CHANGING / DEGRADING のいずれか(str)。
  scene.STABLE / scene.CHANGING / scene.DEGRADING -> str
      v1.4 統制語彙のラベル定数。
"""

import pytest

from supreme import scene


# テストが与える具体的な閾値 param(=「この閾値ならこの regime」を固定するための値)。
# fit 後の実際値ではない(それは F-013 の成功目標)。判定構造を見るための代表閾値。
THRESH = {
    "vol_high": 0.05,      # これを超えるボラティリティは CHANGING 側
    "persist_high": 0.20,  # これを超える持続逸脱は CHANGING 側
    "level_low": 0.30,     # これを下回る水準は DEGRADING 側(低水準/下降)
}


def _features(level, volatility, persistence):
    return {"level": level, "volatility": volatility, "persistence": persistence}


# ===========================================================================
# 公開語彙(v1.4 scene = STABLE / CHANGING / DEGRADING・ADR 0006)
# ===========================================================================

def test_F010_exposes_v14_scene_label_constants():
    """F-010(ADR 0006/0019・語彙公開): scene は v1.4 scene 語彙
    STABLE/CHANGING/DEGRADING をラベル定数として公開し、その値が各文字列であること。

    DEGRADING を3クラス目標に含める(ADR 0019 決定1)。
    """
    expected = {
        "STABLE": "STABLE",
        "CHANGING": "CHANGING",
        "DEGRADING": "DEGRADING",
    }
    for name, value in expected.items():
        assert hasattr(scene, name), f"scene.{name} が公開されていない"
        assert getattr(scene, name) == value, (
            f"scene.{name} の値が '{value}' でない(v1.4 scene 語彙違反)"
        )


# ===========================================================================
# 構造: 安定・nominal・低ボラ・低持続 → STABLE
# ===========================================================================

def test_F010_classify_stable_when_low_vol_low_persist_nominal_level():
    """F-010(ADR 0019 決定1・構造 STABLE): 低ボラ ∧ 低持続逸脱 ∧ nominal 水準 → STABLE。

    与えた閾値(vol_high=0.05, persist_high=0.20, level_low=0.30)に対し、ボラティリティ
    0.01(<0.05)・持続逸脱 0.02(<0.20)・水準 0.7(≥0.30=非低水準)なら、変化兆候も
    下降兆候も無いので STABLE。
    """
    f = _features(level=0.7, volatility=0.01, persistence=0.02)
    assert scene.classify_scene(f, THRESH) == scene.STABLE


# ===========================================================================
# 構造: 高ボラ or 持続逸脱大 → CHANGING
# ===========================================================================

def test_F010_classify_changing_when_high_volatility():
    """F-010(ADR 0019 決定1・構造 CHANGING・高ボラ): 高ボラティリティ → CHANGING。

    ボラティリティ 0.12(>0.05=vol_high)。水準は nominal(0.7・非低)・持続逸脱は低でも、
    HGF 層2が持続的変化を捉えた=CHANGING(過敏でなく持続的変化の検出)。
    """
    f = _features(level=0.7, volatility=0.12, persistence=0.02)
    assert scene.classify_scene(f, THRESH) == scene.CHANGING


def test_F010_classify_changing_when_high_persistence():
    """F-010(ADR 0019 決定1・構造 CHANGING・持続逸脱大): 持続逸脱が大 → CHANGING。

    持続逸脱 0.35(>0.20=persist_high)。ボラティリティが低くても(平坦・非nominal に
    張り付いた見逃しケース相当)、持続逸脱が閾値超で CHANGING に寄る(baseline の
    『平坦・中水準』見逃しを CHANGING 側へ救う=ADR 0019 の機構)。水準は非低(0.6)。
    """
    f = _features(level=0.6, volatility=0.01, persistence=0.35)
    assert scene.classify_scene(f, THRESH) == scene.CHANGING


# ===========================================================================
# 構造: 低水準/下降 → DEGRADING(DEGRADING が3クラス目標に含まれる)
# ===========================================================================

def test_F010_classify_degrading_when_low_level():
    """F-010(ADR 0019 決定1・構造 DEGRADING): 低水準 → DEGRADING。

    水準 0.15(<0.30=level_low)。健全度が低水準に落ちた=劣化。baseline は GT=DEGRADING
    30件中 3件しか当てられていない(ADR 0019 計測)ため、deg 検出を3クラス目標に含める。
    低水準を DEGRADING と判定する構造を固定する。
    """
    f = _features(level=0.15, volatility=0.01, persistence=0.02)
    assert scene.classify_scene(f, THRESH) == scene.DEGRADING


def test_F010_classify_degrading_low_level_is_distinct_from_stable():
    """F-010(ADR 0019 決定1・構造 DEGRADING vs STABLE): 低水準は STABLE にならない。

    水準が level_low を下回れば、ボラティリティ・持続逸脱が低くても(=安定的に低い)
    STABLE ではなく DEGRADING。『安定して劣化している』を STABLE と取り違えない構造。
    """
    f = _features(level=0.10, volatility=0.005, persistence=0.005)
    label = scene.classify_scene(f, THRESH)
    assert label == scene.DEGRADING
    assert label != scene.STABLE, "低水準・安定を STABLE と誤判定した"


# ===========================================================================
# 構造: 閾値の向き(境界の片側ずつ)
# ===========================================================================

def test_F010_classify_just_below_vol_threshold_not_changing_by_vol():
    """F-010(ADR 0019 決定1・境界・ボラ): ボラティリティが vol_high をわずかに下回るなら
    ボラ起因の CHANGING にはならない(他要因が無ければ STABLE)。

    ボラティリティ 0.049(<0.05)・持続逸脱低・水準 nominal → ボラでは CHANGING にならず
    STABLE。閾値の向き(vol > vol_high で CHANGING)を境界の下側で固定する。
    """
    f = _features(level=0.7, volatility=0.049, persistence=0.02)
    assert scene.classify_scene(f, THRESH) == scene.STABLE


def test_F010_classify_just_above_vol_threshold_is_changing():
    """F-010(ADR 0019 決定1・境界・ボラ): ボラティリティが vol_high をわずかに上回ると
    CHANGING(他要因なくてもボラ単独で)。

    ボラティリティ 0.051(>0.05)。閾値の向きを境界の上側で固定する(下側の STABLE と対)。
    """
    f = _features(level=0.7, volatility=0.051, persistence=0.02)
    assert scene.classify_scene(f, THRESH) == scene.CHANGING


def test_F010_classify_just_above_persist_threshold_is_changing():
    """F-010(ADR 0019 決定1・境界・持続): 持続逸脱が persist_high をわずかに上回ると
    CHANGING。

    持続逸脱 0.21(>0.20)・ボラ低・水準 nominal → 持続逸脱起因で CHANGING。
    平坦・非nominal の見逃しを CHANGING 側へ救う境界を上側で固定する。
    """
    f = _features(level=0.6, volatility=0.01, persistence=0.21)
    assert scene.classify_scene(f, THRESH) == scene.CHANGING


# ===========================================================================
# 出力語彙は v1.4 3クラスに閉じる + 決定性
# ===========================================================================

def test_F010_classify_output_in_v14_vocabulary():
    """F-010(ADR 0006/0019・語彙閉包): classify_scene の出力は v1.4 3クラス
    {STABLE, CHANGING, DEGRADING} のいずれかのみ。

    各 regime を成立させる代表 feature で語彙集合に閉じることを固定する。
    """
    v14_scene = {scene.STABLE, scene.CHANGING, scene.DEGRADING}
    cases = [
        _features(0.7, 0.01, 0.02),    # STABLE 域
        _features(0.7, 0.12, 0.02),    # CHANGING(ボラ)
        _features(0.6, 0.01, 0.35),    # CHANGING(持続)
        _features(0.15, 0.01, 0.02),   # DEGRADING(低水準)
    ]
    for f in cases:
        label = scene.classify_scene(f, THRESH)
        assert label in v14_scene, (
            f"classify_scene({f}) が v1.4 scene 語彙外: {label!r}"
        )


def test_F010_classify_is_deterministic_same_label_twice():
    """F-010(ADR 0019 決定3・決定性): 同じ features + 同じ params で2回 classify すると
    同一ラベル(乱数・時刻なし)。

    各 regime の代表点で完全一致を固定する(F-004-1 の流儀)。
    """
    cases = [
        _features(0.7, 0.01, 0.02),
        _features(0.7, 0.12, 0.02),
        _features(0.6, 0.01, 0.35),
        _features(0.15, 0.01, 0.02),
        _features(0.049, 0.049, 0.19),
    ]
    for f in cases:
        first = scene.classify_scene(f, THRESH)
        second = scene.classify_scene(f, THRESH)
        assert first == second, (
            f"classify_scene({f}) が2回で不一致: {first!r} != {second!r}"
        )
