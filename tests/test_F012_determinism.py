"""F-012(決定性・F-004-2 再現性): 同じ axes + 同じ scorer で2回 search すると
同一のベスト構成・同一試行列(乱数・時刻なし・固定順走査)。

specs/SPEC.md F-004-2(再現性の精神) / F-012:
decisions/0021-u8-u18-f012-search.md:
  「手法 = 決定的 greedy 座標上昇。基準構成から各軸を順に走査して練習スコアを最も
   改善する変更を採用…決定的(乱数・時刻なし・固定順走査)= 再現的(F-004-2)。」

このファイルは「同一入力で best_config / best_score / trial_count / 試行列が完全一致」
を固定する。決定的アルゴリズム(乱数・時刻非依存・固定順走査)であることの契約。

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


def _scorer(c):
    s = 0.0
    s += 0.10 if c.get("mode") else 0.0
    s += 0.09 if c.get("relation") else 0.0
    s += 0.05 if c.get("quality") else 0.0
    s += 0.04 if c.get("scene") else 0.0
    s += {"lo": 0.0, "mid": 0.03, "hi": 0.06}[c.get("t3", "lo")]
    return s


# ---------------------------------------------------------------------------
# 同一入力で結果が完全一致(ベスト構成・スコア・試行回数)
# ---------------------------------------------------------------------------

def test_F012_determinism_same_best_config_on_two_runs():
    """F-012(決定性): 同一 axes + scorer で2回探索 → best_config が完全一致。"""
    a = search.search(_axes(), _scorer, search_gate=_passing_gate())
    b = search.search(_axes(), _scorer, search_gate=_passing_gate())
    assert a.best_config == b.best_config


def test_F012_determinism_same_best_score_on_two_runs():
    """F-012(決定性): 2回探索で best_score が一致(浮動小数も同一演算順=厳密一致)。"""
    a = search.search(_axes(), _scorer, search_gate=_passing_gate())
    b = search.search(_axes(), _scorer, search_gate=_passing_gate())
    assert a.best_score == b.best_score


def test_F012_determinism_same_trial_count_on_two_runs():
    """F-012(決定性): 2回探索で試行回数が一致(走査順・停止判定が決定的)。"""
    a = search.search(_axes(), _scorer, search_gate=_passing_gate())
    b = search.search(_axes(), _scorer, search_gate=_passing_gate())
    assert a.trial_count == b.trial_count


# ---------------------------------------------------------------------------
# 試行列(評価した候補列)が完全一致 = 固定順走査
# ---------------------------------------------------------------------------

def test_F012_determinism_same_trial_sequence_on_two_runs():
    """F-012(決定性・固定順走査): 2回探索で試行列(trials)が要素単位で完全一致。

    乱数や時刻に依存しない固定順走査なら、評価した候補・スコアの列が一字一句同じになる。
    試行列の同一性が「決定的アルゴリズム」の最も強い証拠。
    """
    a = search.search(_axes(), _scorer, search_gate=_passing_gate())
    b = search.search(_axes(), _scorer, search_gate=_passing_gate())
    assert a.trials == b.trials, "試行列が2回で一致しない(非決定的走査の疑い)"


def test_F012_determinism_provenance_identical_on_two_runs():
    """F-012(決定性): 選定来歴(provenance)も2回で完全一致。"""
    a = search.search(_axes(), _scorer, search_gate=_passing_gate())
    b = search.search(_axes(), _scorer, search_gate=_passing_gate())
    assert a.provenance == b.provenance


# ---------------------------------------------------------------------------
# 候補評価順序が固定(scorer 呼び出し順が2回で一致)
# ---------------------------------------------------------------------------

def test_F012_determinism_scorer_call_order_is_fixed():
    """F-012(決定性・固定順走査): scorer に渡される候補の順序が2回の探索で一致。

    走査順がデータ構造の反復順(挿入順 dict)に固定され、乱数で揺れないことを固定する。
    """
    def run():
        order = []

        def spy(c):
            order.append(dict(c))
            return _scorer(c)

        search.search(_axes(), spy, search_gate=_passing_gate())
        return order

    assert run() == run(), "scorer 呼び出し順が2回で一致しない(走査順が非決定的)"


def test_F012_determinism_no_dependence_on_wall_clock():
    """F-012(決定性・時刻非依存): 連続実行(壁時計が進む)でも結果が変わらない。

    時刻に依存しないことを、間に時間を挟んだ2回の探索で固定する(guard は時計を持たない・
    GUARD_IF 運用規約4 と同じ精神。search も時計を持たない)。
    """
    import time
    a = search.search(_axes(), _scorer, search_gate=_passing_gate())
    time.sleep(0.01)
    b = search.search(_axes(), _scorer, search_gate=_passing_gate())
    assert a.best_config == b.best_config
    assert a.trial_count == b.trial_count
    assert a.trials == b.trials
