"""F-012-2: 選定は練習用スコアのみに基づく(注入 fake スコアラが返す値だけで選ぶ)。

specs/SPEC.md F-012-2: 「選定は練習用スコアのみに基づく。」
decisions/0021-u8-u18-f012-search.md:
  「選定は練習用スコアのみ(F-012-2)。…各軸を順に走査して練習スコアを最も改善する
   変更を採用、改善が無くなる(収束)か試行上限に達するまで反復。」
  手法 = 決定的 greedy 座標上昇(基準構成=各軸先頭から開始)。

このファイルは「fake scorer(練習スコア)が返す値だけで選定される」ことを固定する。
最高練習スコアの(ガードレール合格)候補が選ばれる。scorer に渡される候補が練習用評価
であり封印でないことは test_F012_seal_isolation.py が担保(本ファイルは選定論理に集中)。

------------------------------------------------------------------------------
このファイルが用いる supreme.search の前提 API(test_F012_contract_surface.py と同一):
  search.search(axes, scorer, *, search_gate, candidate_guards=None,
                cap=50, patience=10) -> SearchResult
  SearchResult: .best_config / .best_score / .trial_count / .provenance / .trials
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
# 最高練習スコアの候補が選ばれる(scorer の値だけで決まる)
# ---------------------------------------------------------------------------

def test_F012_2_selects_config_with_highest_practice_score():
    """F-012-2: 各軸 ON ほど高スコアの scorer では、全 ON 構成が選ばれる。

    scorer が返す練習スコアの大小だけで選定されることを固定する。
    """
    def scorer(c):
        s = 0.0
        s += 0.10 if c.get("mode") else 0.0
        s += 0.09 if c.get("relation") else 0.0
        s += 0.05 if c.get("quality") else 0.0
        s += 0.04 if c.get("scene") else 0.0
        s += {"lo": 0.0, "mid": 0.03, "hi": 0.06}[c.get("t3", "lo")]
        return s

    result = search.search(_axes(), scorer, search_gate=_passing_gate())

    # 全 ON + t3=hi が最高スコア構成。greedy が単調改善でそこに到達する。
    assert result.best_config["mode"] is True
    assert result.best_config["relation"] is True
    assert result.best_config["quality"] is True
    assert result.best_config["scene"] is True
    assert result.best_config["t3"] == "hi"
    assert result.best_score == pytest.approx(0.10 + 0.09 + 0.05 + 0.04 + 0.06)


def test_F012_2_best_score_equals_scorer_of_best_config():
    """F-012-2: 報告される best_score は scorer(best_config) と一致する。

    選定根拠が練習スコアそのものであり、別の量(封印スコア等)で上書きされていない。
    """
    def scorer(c):
        return (1.0 if c.get("mode") else 0.0) + (0.5 if c.get("scene") else 0.0)

    result = search.search(_axes(), scorer, search_gate=_passing_gate())
    assert result.best_score == pytest.approx(scorer(result.best_config))


def test_F012_2_picks_specific_axis_value_by_practice_score():
    """F-012-2: 離散ハイパラ軸(t3)で、練習スコア最大の値が選ばれる。

    t3 だけがスコアに効く scorer を与え、mid が最大なら mid が選ばれることを固定する。
    """
    def scorer(c):
        return {"lo": 0.1, "mid": 0.9, "hi": 0.3}[c.get("t3", "lo")]

    result = search.search(_axes(), scorer, search_gate=_passing_gate())
    assert result.best_config["t3"] == "mid"
    assert result.best_score == pytest.approx(0.9)


def test_F012_2_off_better_than_on_selects_off():
    """F-012-2(逆向き): OFF の方が高スコアの軸は OFF が選ばれる。

    「常時 ON が正解」ではなく、純粋に練習スコアで決まることを固定する。
    relation を ON にすると下がる scorer では relation=OFF が選ばれる。
    """
    def scorer(c):
        s = 0.5
        s -= 0.3 if c.get("relation") else 0.0   # relation ON は損
        s += 0.2 if c.get("mode") else 0.0
        return s

    result = search.search(_axes(), scorer, search_gate=_passing_gate())
    assert result.best_config["relation"] is False
    assert result.best_config["mode"] is True


def test_F012_2_baseline_kept_when_no_change_improves():
    """F-012-2(収束): どの軸変更も改善しない scorer では基準構成が選ばれる。

    全候補同点の scorer なら、基準構成(各軸先頭 = greedy 開始点)から動かない。
    改善がある変更だけを採用する(「最も改善する変更」の選定論理)。
    """
    def scorer(c):
        return 0.42  # 常に一定 = どの変更も改善しない

    result = search.search(_axes(), scorer, search_gate=_passing_gate())
    # 各軸先頭(基準構成)= mode/relation/quality/scene=False, t3="lo"。
    assert result.best_config == {
        "mode": False, "relation": False, "quality": False,
        "scene": False, "t3": "lo",
    }
    assert result.best_score == pytest.approx(0.42)


# ---------------------------------------------------------------------------
# 選定来歴(練習用評価の記録)
# ---------------------------------------------------------------------------

def test_F012_2_provenance_records_practice_scores():
    """F-012-2: 選定来歴に練習用スコアが記録され、全て split=train。

    SelectionProvenanceRecord(GUARD_IF・F-012 が生成)が練習評価を残し、
    封印スコアを混ぜていない(全 train)ことを固定する。
    """
    def scorer(c):
        return 0.7 if c.get("mode") else 0.1

    result = search.search(_axes(), scorer, search_gate=_passing_gate())
    assert result.provenance
    for rec in result.provenance:
        assert rec["split"] == "train"
        assert isinstance(rec["score"], float)
    # guard の純度検査(F-014-3)に通る。
    assert guard.check_selection_purity(result.provenance).passed is True
