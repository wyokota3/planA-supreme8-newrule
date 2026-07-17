"""F-010 scene 改良(ADR 0019)— 学習可能パラメータ予算(U24・F-014 連携)の契約。

学習モジュールゆえ厳密な学習値は契約にしないが、**学習可能 param 数の予算(過学習ガード)**は
方法論検証層の第一級契約(TEST_STRATEGY)であり、固定する。

契約の最終根拠:
  - decisions/0019-f010-scene-hgf-learning.md:
      決定2: 学習対象 = HGF パラメータ 6個(κ1,κ2,ω1,ω2,ω3,obs_noise)+ regime 閾値/境界
             (~3-5個)。計 ~9-11 個 ≪ 予算 100。
      **固定の集約重み・EMA α 等を学習に含めても予算内**だが、固定ルール閾値(学習しない定数)は
      学習可能 param に計上しない(U24: 学習可能パラメータのみ計数)。
  - decisions/0018-u4-u24-learning-prerequisites.md(U24):
      決定5: パラメータ数 = 学習可能パラメータのみ。固定ルール閾値定数は数えない。
      決定6: 係数 k = 0.5。param総数 < データ数 × 0.5。データ数=練習用シナリオ件数 ~200 → ~100。
  - specs/GUARD_IF.md: check_param_budget(param_count, data_count, k) は厳密 < で合否、
                        k=None は fail-closed。F-014 完了済み(コード変更不要)。
  - specs/TEST_STRATEGY.md F-014: 過学習ガードは方法論検証層・分岐網羅必須。

スコープ外(ADR 0019・推測でテスト化しない):
  - 学習可能 param の**厳密な個数**(9 か 11 か等)は実装時に確定(EMA α・集約重みを学習に
    含めるか裁量)。本ファイルは『公開された学習可能 param 数が予算 data×0.5 を厳密に下回る』
    という**予算性質**を固定し、個数の厳密値は固定しない(範囲のみ: 1 件以上・予算内)。

テストが前提とする supreme.scene の公開 API(設計裁量・指示で委任):
  scene.learnable_param_names() -> list[str]
      学習可能(fit で更新される連続値)パラメータの名前リスト。固定ルール閾値定数は含めない
      (U24: 学習可能のみ計数)。HGF param + 学習する regime 閾値。
  scene.learnable_param_count() -> int
      上記の個数(== len(learnable_param_names()))。F-014 の param_count に渡す値。
"""

import pytest

from supreme import guard, scene

# U24(ADR 0018 決定6): k=0.5・data=練習用シナリオ件数 ~200。
K = 0.5
PRACTICE_DATA_COUNT = 200  # 練習用シナリオ件数(ADR 0018: ~200)。


# ===========================================================================
# 学習可能 param の公開(U24: 学習可能パラメータのみ計数)
# ===========================================================================

def test_F010_exposes_learnable_param_list():
    """F-010(ADR 0019 決定2 / U24・学習可能 param 公開): scene は学習可能パラメータの
    名前リストを公開し、count がその長さと一致する。

    過学習ガード(F-014-1)に渡す param_count を得る手段。固定ルール閾値定数でなく
    『学習で更新される連続値』のみを数える(U24 決定5)。
    """
    names = scene.learnable_param_names()
    assert isinstance(names, (list, tuple)), "learnable_param_names は列を返すべき"
    count = scene.learnable_param_count()
    assert count == len(names), (
        f"learnable_param_count({count}) が names の長さ({len(names)})と一致しない"
    )


def test_F010_learnable_param_count_is_positive():
    """F-010(ADR 0019 決定2・学習対象が存在): 学習可能 param が1個以上ある
    (HGF 6 + 閾値 ~3-5 で計 ~9-11)。

    scene は学習モジュール(fit で param が決まる)なので学習可能 param は0でない。
    厳密値(9/11 等)は実装裁量のため固定しないが、正であることを固定する。
    """
    assert scene.learnable_param_count() >= 1, (
        "学習可能 param が0(scene は学習モジュールのはず)"
    )


def test_F010_learnable_param_names_are_unique():
    """F-010(ADR 0019 決定2・計数の健全性): 学習可能 param 名に重複が無い
    (二重計数で予算検査を歪めない)。
    """
    names = list(scene.learnable_param_names())
    assert len(names) == len(set(names)), (
        f"学習可能 param 名に重複がある: {names!r}(二重計数の疑い)"
    )


# ===========================================================================
# 予算検査(F-014-1 連携・k=0.5): 学習可能 param 数 < data×0.5 が合格
# ===========================================================================

def test_F010_param_budget_passes_under_practice_data():
    """F-010(ADR 0019 決定2 / U24 / F-014-1・予算検査): scene の学習可能 param 数を
    guard.check_param_budget(param, data=200, k=0.5) に通すと**合格**する。

    予算 = 200×0.5 = 100。scene の学習可能 param(~9-11)≪ 100 なので合格。学習可能 param が
    予算内に収まる(過学習ガードを通る)ことを固定する。data=練習用シナリオ件数(ADR 0018)。
    """
    param_count = scene.learnable_param_count()
    r = guard.check_param_budget(
        param_count=param_count, data_count=PRACTICE_DATA_COUNT, k=K
    )
    assert r.passed is True, (
        f"scene 学習可能 param={param_count} が予算 {PRACTICE_DATA_COUNT}×{K}="
        f"{PRACTICE_DATA_COUNT * K} を超えて不合格: {r.reason}"
    )
    assert r.checked is True
    assert r.guard_id == "F-014-1"


def test_F010_param_budget_representative_nine_passes():
    """F-010(ADR 0019 決定2・予算境界の代表値): param=9, data=200, k=0.5 → 合格
    (9 < 100)。

    ADR 0019 が挙げる代表値(HGF 6 + 閾値 3 = 9)が予算 100 に収まることを固定する
    (この閾値ならこの合否=判定構造)。
    """
    r = guard.check_param_budget(param_count=9, data_count=200, k=0.5)
    assert r.passed is True


def test_F010_param_budget_eleven_passes():
    """F-010(ADR 0019 決定2・予算上端の代表値): param=11, data=200, k=0.5 → 合格
    (11 < 100)。

    ADR 0019 が挙げる上端(~11)でも予算 100 に余裕で収まる(予算は binding でない)。
    """
    r = guard.check_param_budget(param_count=11, data_count=200, k=0.5)
    assert r.passed is True


def test_F010_param_budget_fail_closed_without_k():
    """F-010(U24 / F-014-1・fail-closed): k 未供給では scene の param 数でも不合格
    (安全側・ADR 0007)。

    予算検査は k を供給して初めて合格しうる。学習モジュールでも k 無しでは過学習ガードを
    通さない(方法論検証層の fail-closed)。
    """
    param_count = scene.learnable_param_count()
    r = guard.check_param_budget(
        param_count=param_count, data_count=PRACTICE_DATA_COUNT, k=None
    )
    assert r.passed is False
    assert r.checked is True


# ===========================================================================
# 陰性: 学習可能 param を過大に偽ると予算を超えてブロックされる
# (過学習構成をわざと作って合格を出さない・TEST_STRATEGY 必須陰性)
# ===========================================================================

def test_F010_param_budget_blocks_overfit_construction():
    """F-010(U24 / F-014-1・陰性): 学習可能 param 数が予算 data×0.5 を超える過学習構成は
    ブロックされる(合格を出さない)。

    param=100, data=200, k=0.5 → 予算=100、param=100 は等号(厳密 < でない)で不合格。
    『学習可能 param が予算を食い切る』構成をわざと作り、ガードが合格を出さないことを固定する
    (TEST_STRATEGY: 過学習構成の陰性テスト必須)。
    """
    r = guard.check_param_budget(param_count=100, data_count=200, k=0.5)
    assert r.passed is False, "予算ちょうど(過学習境界)を合格と誤判定"

    r2 = guard.check_param_budget(param_count=150, data_count=200, k=0.5)
    assert r2.passed is False, "予算超過(過学習)を合格と誤判定"
