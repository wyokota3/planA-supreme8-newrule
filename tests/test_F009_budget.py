"""F-009 T3(ADR 0020)— 学習可能パラメータ予算(U24・F-014 連携)の契約。

学習モジュールゆえ厳密な学習値は契約にしないが、**学習可能 param 数の予算(過学習ガード)**は
方法論検証層の第一級契約(TEST_STRATEGY)であり、固定する。既存の guard を再利用する(独自再実装
しない・指示 F)。

契約の最終根拠:
  - decisions/0020-f009-t3-episode-learning.md:
      決定2: 学習可能 param ~7-21(ロジスティックの重み+バイアス)≪ 予算 100(U24・k=0.5・
             data~200)。学習が触るのは conv/traffic/quiet 境界。固定の規則閾値・集約係数は非計上。
  - decisions/0018-u4-u24-learning-prerequisites.md(U24):
      決定5: パラメータ数 = 学習可能パラメータのみ。固定ルール閾値定数は数えない。
      決定6: 係数 k = 0.5。param総数 < データ数 × 0.5。データ数=練習用シナリオ件数 ~200 → ~100。
  - specs/GUARD_IF.md / src/supreme/guard.py: check_param_budget(param_count, data_count, k) は
      厳密 < で合否(等号は不合格)、k=None は fail-closed(GuardResult.passed/checked/guard_id)。
      F-014 完了済み(コード変更不要)。
  - specs/TEST_STRATEGY.md F-014: 過学習ガードは方法論検証層・分岐網羅必須。

スコープ外(ADR 0020・推測でテスト化しない):
  - 学習可能 param の**厳密な個数**(7 か 21 か等)は実装時に確定(ロジスティック重みの本数・
    他クラス規則閾値を tune するか裁量)。本ファイルは『公開された学習可能 param 数が予算 data×0.5 を
    厳密に下回る』予算性質と『1個以上・~7-21 のオーダー』を固定し、厳密値は固定しない。

テストが前提とする supreme.t3 の公開 API(設計裁量・指示で委任・F-010 budget 流儀):
  t3.learnable_param_names() -> list[str]
      学習可能(fit で更新される連続値)パラメータの名前リスト。固定の規則閾値・集約係数は
      含めない(U24: 学習可能のみ計数)。ロジスティックの重み+バイアス。
  t3.learnable_param_count() -> int
      上記の個数(== len(learnable_param_names()))。F-014 の param_count に渡す値。
"""

import pytest

from supreme import guard, t3

# U24(ADR 0018 決定6): k=0.5・data=練習用シナリオ件数 ~200。
K = 0.5
PRACTICE_DATA_COUNT = 200  # 練習用シナリオ件数(ADR 0018: ~200)。


# ===========================================================================
# 学習可能 param の公開(U24: 学習可能パラメータのみ計数)
# ===========================================================================

def test_F009_exposes_learnable_param_list():
    """F-009(ADR 0020 決定2 / U24・学習可能 param 公開): t3 は学習可能パラメータの名前リストを
    公開し、count がその長さと一致する。

    過学習ガード(F-014-1)に渡す param_count を得る手段。固定ルール閾値・集約係数でなく
    『学習で更新される連続値(ロジスティック重み+バイアス)』のみを数える(U24 決定5)。
    """
    names = t3.learnable_param_names()
    assert isinstance(names, (list, tuple)), "learnable_param_names は列を返すべき"
    count = t3.learnable_param_count()
    assert count == len(names), (
        f"learnable_param_count({count}) が names の長さ({len(names)})と一致しない"
    )


def test_F009_learnable_param_count_is_positive():
    """F-009(ADR 0020 決定2・学習対象が存在): 学習可能 param が1個以上ある
    (ロジスティック重み+バイアスで ~7-21)。

    T3 は学習モジュール(fit で重み/バイアスが決まる)なので学習可能 param は0でない。
    厳密値は実装裁量のため固定しないが、正であることを固定する。
    """
    assert t3.learnable_param_count() >= 1, (
        "学習可能 param が0(T3 は局所ロジスティック学習モジュールのはず)"
    )


def test_F009_learnable_param_count_in_adr_order_of_magnitude():
    """F-009(ADR 0020 決定2・オーダー): 学習可能 param 数が ADR 0020 の見積もり ~7-21 の
    オーダーに収まる(≪ 予算 100)。

    厳密値(7/21 等)は実装裁量だが、ADR 0020 が示す『~7-21』のオーダーから大きく外れない
    (1 以上・予算 100 未満で、過学習側=数十以上に膨らんでいない)ことを緩く固定する。
    集約特徴 ~6 × 3境界 + バイアス ~3 程度が目安。
    """
    count = t3.learnable_param_count()
    assert 1 <= count <= 50, (
        f"学習可能 param 数 {count} が ADR 0020 の ~7-21 オーダー(≪100)から大きく外れる"
    )


def test_F009_learnable_param_names_are_unique():
    """F-009(ADR 0020 決定2・計数の健全性): 学習可能 param 名に重複が無い
    (二重計数で予算検査を歪めない)。
    """
    names = list(t3.learnable_param_names())
    assert len(names) == len(set(names)), (
        f"学習可能 param 名に重複がある: {names!r}(二重計数の疑い)"
    )


# ===========================================================================
# 予算検査(F-014-1 連携・k=0.5): 学習可能 param 数 < data×0.5 が合格
# ===========================================================================

def test_F009_param_budget_passes_under_practice_data():
    """F-009(ADR 0020 決定2 / U24 / F-014-1・予算検査): t3 の学習可能 param 数を
    guard.check_param_budget(param, data=200, k=0.5) に通すと**合格**する。

    予算 = 200×0.5 = 100。t3 の学習可能 param(~7-21)≪ 100 なので合格。学習可能 param が
    予算内に収まる(過学習ガードを通る)ことを固定する。data=練習用シナリオ件数(ADR 0018)。
    既存 guard を再利用する(独自再実装しない)。
    """
    param_count = t3.learnable_param_count()
    r = guard.check_param_budget(
        param_count=param_count, data_count=PRACTICE_DATA_COUNT, k=K
    )
    assert r.passed is True, (
        f"t3 学習可能 param={param_count} が予算 {PRACTICE_DATA_COUNT}×{K}="
        f"{PRACTICE_DATA_COUNT * K} を超えて不合格: {r.reason}"
    )
    assert r.checked is True
    assert r.guard_id == "F-014-1"


def test_F009_param_budget_representative_seven_passes():
    """F-009(ADR 0020 決定2・予算下端の代表値): param=7, data=200, k=0.5 → 合格(7 < 100)。

    ADR 0020 が挙げる下端(~7)が予算 100 に収まることを固定する(この param ならこの合否)。
    """
    r = guard.check_param_budget(param_count=7, data_count=200, k=0.5)
    assert r.passed is True


def test_F009_param_budget_representative_twentyone_passes():
    """F-009(ADR 0020 決定2・予算上端の代表値): param=21, data=200, k=0.5 → 合格(21 < 100)。

    ADR 0020 が挙げる上端(~21)でも予算 100 に余裕で収まる(予算は binding でない)。
    """
    r = guard.check_param_budget(param_count=21, data_count=200, k=0.5)
    assert r.passed is True


def test_F009_param_budget_fail_closed_without_k():
    """F-009(U24 / F-014-1・fail-closed): k 未供給では t3 の param 数でも不合格(安全側・ADR 0007)。

    予算検査は k を供給して初めて合格しうる。学習モジュールでも k 無しでは過学習ガードを
    通さない(方法論検証層の fail-closed)。
    """
    param_count = t3.learnable_param_count()
    r = guard.check_param_budget(
        param_count=param_count, data_count=PRACTICE_DATA_COUNT, k=None
    )
    assert r.passed is False
    assert r.checked is True


# ===========================================================================
# 陰性: 学習可能 param を過大に偽ると予算を超えてブロックされる
# (過学習構成をわざと作って合格を出さない・TEST_STRATEGY 必須陰性)
# ===========================================================================

def test_F009_param_budget_blocks_overfit_construction():
    """F-009(U24 / F-014-1・陰性): 学習可能 param 数が予算 data×0.5 を超える過学習構成は
    ブロックされる(合格を出さない)。

    param=100, data=200, k=0.5 → 予算=100、param=100 は等号(厳密 < でない)で不合格。
    param=150 は予算超過で不合格。『学習可能 param が予算を食い切る/超える』構成をわざと作り、
    ガードが合格を出さないことを固定する(TEST_STRATEGY: 過学習構成の陰性テスト必須)。
    """
    r = guard.check_param_budget(param_count=100, data_count=200, k=0.5)
    assert r.passed is False, "予算ちょうど(過学習境界)を合格と誤判定"

    r2 = guard.check_param_budget(param_count=150, data_count=200, k=0.5)
    assert r2.passed is False, "予算超過(過学習)を合格と誤判定"
