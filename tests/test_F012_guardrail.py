"""F-012(ガードレール違反候補の不採用): param 予算違反・強い項目 δ_strong 違反候補は選定されない。

specs/SPEC.md F-012 / F-014:
  F-014-1: 学習可能 param 総数 < 練習用データ数 × k(過学習ガード)。
  F-006-1: 強い項目の低下が δ_strong(U5b: 絶対値 0.02)以内。
decisions/0021-u8-u18-f012-search.md:
  「各候補は param 予算(F-014-1・学習可能パラメータ < data×0.5・U24)と強い項目の
   δ_strong 維持(F-006-1)を満たすこと。違反候補は不採用(SearchGate.request_continue が
   aggregate 不合格で False を返す経路)。」
decisions/0018-u4-u24-learning-prerequisites.md(U24): k=0.5・param=学習可能パラメータのみ。
decisions/0002-tolerances-and-seal-access.md(U5b): δ_strong=絶対値 0.02。
specs/GUARD_IF.md:
  combine_guards で集約 → SearchGate.request_continue(aggregate) が不合格なら False。

このファイルは「高い練習スコアでも guard 違反候補は採用されず、合格候補が選ばれる」ことを
固定する。候補ごとの guard 判定は candidate_guards(callable)で search に注入する。

------------------------------------------------------------------------------
このファイルが用いる supreme.search の前提 API(test_F012_contract_surface.py と同一):
  search.search(axes, scorer, *, search_gate, candidate_guards=None,
                cap=50, patience=10) -> SearchResult
    - candidate_guards(candidate) -> list[GuardResult]:
        その候補の guard 結果列(param 予算・δ_strong 等)。search は combine_guards で
        集約し search_gate.request_continue にかける。集約不合格の候補は不採用。
"""

import pytest

from supreme import guard
from supreme import search


def _axes():
    return {
        "mode":     [False, True],
        "relation": [False, True],
        "quality":  [False, True],
        "scene":    [False, True],
        "t3":       ["lo", "mid", "hi"],
    }


def _passing_gate():
    return guard.SearchGate(guard.SealGuard(production=False))


# ---------------------------------------------------------------------------
# param 予算違反候補の不採用(F-014-1・U24)
# ---------------------------------------------------------------------------

def test_F012_param_budget_violator_not_selected_even_if_high_score():
    """F-012: 高練習スコアでも param 予算違反(学習 param > data×0.5)の候補は不採用。

    全 ON が最高スコアだが「全 ON は学習可能 param が予算超過」とする candidate_guards を
    与え、全 ON が選ばれない(合格構成が選ばれる)ことを固定する。U24: k=0.5。
    """
    def scorer(c):
        # 全 ON が最高スコア(本来 greedy が向かう先)。
        return sum(1.0 for v in (c.get("mode"), c.get("relation"),
                                 c.get("quality"), c.get("scene")) if v)

    def candidate_guards(c):
        # ON 数が多いほど学習 param が増える前提。全部 ON(=4)は予算超過とする。
        on = sum(1 for v in (c.get("mode"), c.get("relation"),
                             c.get("quality"), c.get("scene")) if v)
        param = on * 60            # ON 1個 = 60 param(仮の計数)
        # data=200, k=0.5 → budget=100。param>=120(ON>=2)で不合格になる構成。
        return [guard.check_param_budget(param_count=param, data_count=200, k=0.5)]

    result = search.search(_axes(), scorer, search_gate=_passing_gate(),
                           candidate_guards=candidate_guards)

    # 採用構成は param 予算合格でなければならない。
    on = sum(1 for v in (result.best_config.get("mode"),
                         result.best_config.get("relation"),
                         result.best_config.get("quality"),
                         result.best_config.get("scene")) if v)
    g = guard.check_param_budget(param_count=on * 60, data_count=200, k=0.5)
    assert g.passed is True, \
        f"param 予算違反の構成が採用された: best={result.best_config}"


def test_F012_param_budget_pass_candidate_selected_over_violator():
    """F-012: 予算合格の中で最高練習スコアの候補が選ばれる(違反候補をスキップ)。

    ON=1 までは予算合格・ON>=2 は違反、という構成で、合格集合内の最高スコア
    (ON ちょうど1個の最良)が選ばれることを固定する。
    """
    def scorer(c):
        # mode の寄与が最大。合格集合内なら mode 単独 ON がベスト。
        s = 0.0
        s += 0.5 if c.get("mode") else 0.0
        s += 0.3 if c.get("relation") else 0.0
        s += 0.2 if c.get("quality") else 0.0
        return s

    def candidate_guards(c):
        on = sum(1 for v in (c.get("mode"), c.get("relation"),
                             c.get("quality"), c.get("scene")) if v)
        param = on * 60   # ON>=2 → param>=120 > budget(100) → 不合格。
        return [guard.check_param_budget(param_count=param, data_count=200, k=0.5)]

    result = search.search(_axes(), scorer, search_gate=_passing_gate(),
                           candidate_guards=candidate_guards)
    # 合格集合(ON<=1)で最高スコアは mode 単独。
    assert result.best_config["mode"] is True
    assert result.best_config["relation"] is False
    assert result.best_config["quality"] is False
    assert result.best_config["scene"] is False


# ---------------------------------------------------------------------------
# 強い項目 δ_strong 違反候補の不採用(F-006-1・U5b)
# ---------------------------------------------------------------------------

def test_F012_strong_item_delta_violator_not_selected():
    """F-012: 強い項目が δ_strong(0.02)超で低下する候補は、練習スコアが高くても不採用。

    δ_strong 違反を表す GuardResult(不合格)を candidate_guards が返す候補を作り、
    SearchGate.request_continue が aggregate 不合格で False → その候補が選ばれない
    ことを固定する。δ_strong 違反は guard の合否で表現(ADR 0021)。
    """
    def scorer(c):
        # scene を ON にすると練習スコアは最大(本来 greedy が選ぶ)。
        return 1.0 if c.get("scene") else 0.0

    def _delta_strong_result(passed, reason):
        # 強い項目 δ_strong 維持の判定を GuardResult として表現する。
        # combine_guards が checked=True の不合格を見て aggregate 不合格にする。
        return guard.GuardResult(
            passed=passed, guard_id="F-006-1", checked=True, reason=reason,
        )

    def candidate_guards(c):
        # scene ON は強い項目を 0.05(>0.02)低下させる = δ_strong 違反。
        if c.get("scene"):
            return [_delta_strong_result(False, "強い項目が δ_strong 超で低下")]
        return [_delta_strong_result(True, "強い項目 δ_strong 内")]

    result = search.search(_axes(), scorer, search_gate=_passing_gate(),
                           candidate_guards=candidate_guards)
    assert result.best_config["scene"] is False, \
        f"δ_strong 違反の scene=ON が採用された: best={result.best_config}"


def test_F012_request_continue_false_blocks_candidate():
    """F-012(因果): aggregate 不合格 → SearchGate.request_continue=False → 候補不採用。

    全候補を guard 不合格にする candidate_guards を与えると、基準構成から1歩も
    動かない(どの変更候補も request_continue=False でブロックされる)ことを固定する。
    """
    def scorer(c):
        # 何かを ON にすると高スコア(本来動きたい)。
        return float(sum(1 for v in c.values() if v is True))

    def all_block(c):
        # 基準(全 OFF)以外は全て param 予算違反にする。
        on = sum(1 for v in c.values() if v is True)
        if on == 0:
            return [guard.check_param_budget(param_count=10, data_count=200, k=0.5)]  # 合格
        return [guard.check_param_budget(param_count=9999, data_count=200, k=0.5)]    # 不合格

    result = search.search(_axes(), scorer, search_gate=_passing_gate(),
                           candidate_guards=all_block)
    # 全変更候補がブロックされるので基準構成(各軸先頭)に留まる。
    assert result.best_config == {
        "mode": False, "relation": False, "quality": False,
        "scene": False, "t3": "lo",
    }


def test_F012_selected_config_passes_all_candidate_guards():
    """F-012(不変条件): 採用された best_config は candidate_guards 集約に合格している。

    探索が「合格候補からのみ選ぶ」規律を、採用構成を guard に通し直して固定する。
    """
    def scorer(c):
        return float(sum(1 for v in (c.get("mode"), c.get("relation")) if v))

    def candidate_guards(c):
        on = sum(1 for v in (c.get("mode"), c.get("relation"),
                             c.get("quality"), c.get("scene")) if v)
        return [guard.check_param_budget(param_count=on * 60, data_count=200, k=0.5)]

    result = search.search(_axes(), scorer, search_gate=_passing_gate(),
                           candidate_guards=candidate_guards)
    agg = guard.combine_guards(candidate_guards(result.best_config))
    assert agg.passed is True, \
        f"採用構成が guard 不合格(合格候補から選んでいない): {result.best_config}"
