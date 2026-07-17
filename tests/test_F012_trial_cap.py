"""F-012-3: 探索試行回数が上限内(cap=50)+ 無改善 patience=10 撤退。

specs/SPEC.md F-012-3: 「探索試行回数が定義された上限内(U18 確定後)。」
decisions/0021-u8-u18-f012-search.md(U18):
  「試行上限(ハード上限)= 50。…無改善 patience = 10(撤退基準): 連続10試行で練習
   スコアが改善しなければ撤退。…F-014-4 check_trial_cap(trial_count, cap) に cap=50 を
   供給(F-012-3 を満たす)。」
specs/GUARD_IF.md:
  check_trial_cap(trial_count, cap) — 合格 ⇔ trial_count <= cap。

このファイルは「常に改善する scorer でも試行 <= cap で停止」「無改善 patience で早期撤退」
「結果が guard.check_trial_cap で合格」を固定する(F-014 の trial_cap ガードレール連携)。

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


def _wide_axes(n_axes=20, n_vals=10):
    """cap を確実に超える大きな探索空間(改善が無限に続く構成で cap を試すため)。"""
    return {f"ax{i}": list(range(n_vals)) for i in range(n_axes)}


def _passing_gate():
    return guard.SearchGate(guard.SealGuard(production=False))


# ---------------------------------------------------------------------------
# 試行上限(cap)内で停止
# ---------------------------------------------------------------------------

def test_F012_3_trial_count_never_exceeds_default_cap_50():
    """F-012-3(U18): 常に改善する scorer + 広い空間でも、試行回数 <= 既定 cap=50。

    各候補が必ず前より高スコア(単調改善で patience に当たらない)になる scorer を与え、
    撤退でなく cap で止まる経路を作る。試行回数が 50 を超えないことを固定する。
    """
    # 各軸の値が大きいほど高スコア = どの軸変更も常に改善しうる(過剰探索を誘発)。
    def always_improving(c):
        return float(sum(c.values()))

    result = search.search(_wide_axes(), always_improving, search_gate=_passing_gate())
    assert result.trial_count <= 50, \
        f"試行回数が cap=50 を超えた: {result.trial_count}"


def test_F012_3_trial_count_respects_custom_cap():
    """F-012-3: cap を明示供給したとき、試行回数はその cap を超えない。"""
    def always_improving(c):
        return float(sum(c.values()))

    result = search.search(_wide_axes(), always_improving,
                           search_gate=_passing_gate(), cap=12)
    assert result.trial_count <= 12, \
        f"試行回数が cap=12 を超えた: {result.trial_count}"


def test_F012_3_result_passes_check_trial_cap_with_cap_50():
    """F-012-3(F-014-4 連携): 探索結果の試行回数が guard.check_trial_cap(.., 50) で合格。

    探索が U18 の上限を守ったことを、F-014-4 のガードレールで機械検証する。
    """
    def always_improving(c):
        return float(sum(c.values()))

    result = search.search(_wide_axes(), always_improving, search_gate=_passing_gate())
    g = guard.check_trial_cap(trial_count=result.trial_count, cap=50)
    assert g.passed is True
    assert g.checked is True
    assert g.guard_id == "F-014-4"


# ---------------------------------------------------------------------------
# 無改善 patience による早期撤退
# ---------------------------------------------------------------------------

def test_F012_3_early_stop_on_no_improvement_patience():
    """F-012-3(U18 patience): 改善を返さない scorer では patience 試行で早期撤退。

    全候補同点(改善ゼロ)の scorer では、cap(50)よりずっと前に撤退する。
    広い空間でも patience=10 を大きく超えて探索し続けないことを固定する。
    """
    def flat(c):
        return 0.3  # どの候補も同点 = 改善ゼロが続く

    result = search.search(_wide_axes(), flat,
                           search_gate=_passing_gate(), patience=10)
    # 撤退基準が効くなら、巨大空間(20軸×10値)を全走査(>>50)せず早く止まる。
    assert result.trial_count <= 50
    # cap よりも patience による撤退が早い(改善ゼロなので cap まで行かない)。
    assert result.trial_count < 50, \
        f"無改善でも cap 近くまで探索した(patience が効いていない): {result.trial_count}"


def test_F012_3_smaller_patience_stops_sooner():
    """F-012-3(U18 patience 単調性): patience を小さくすると撤退が早まる。

    同じ無改善 scorer で patience=3 と patience=10 を比べ、3 の方が試行が少ない
    (または同数以下)= patience が撤退タイミングを支配することを固定する。
    """
    def flat(c):
        return 0.3

    r3 = search.search(_wide_axes(), flat, search_gate=_passing_gate(), patience=3)
    r10 = search.search(_wide_axes(), flat, search_gate=_passing_gate(), patience=10)
    assert r3.trial_count <= r10.trial_count, \
        f"patience を小さくしても撤退が早まらない: p3={r3.trial_count} p10={r10.trial_count}"


def test_F012_3_converges_before_cap_when_space_small():
    """F-012-3(収束 < cap): 小さな探索空間では収束で停止し試行 << cap。

    有界空間の greedy は数試行で収束する。改善が止まれば cap(50)を待たず終わる。
    """
    def scorer(c):
        return (1.0 if c.get("mode") else 0.0) + (0.5 if c.get("scene") else 0.0)

    result = search.search(_axes(), scorer, search_gate=_passing_gate())
    assert result.trial_count < 50, \
        f"小空間なのに cap 近くまで探索した: {result.trial_count}"


def test_F012_3_trial_count_is_nonnegative_int():
    """F-012-3: 試行回数は非負整数(報告契約)。"""
    def scorer(c):
        return 1.0 if c.get("mode") else 0.0

    result = search.search(_axes(), scorer, search_gate=_passing_gate())
    assert isinstance(result.trial_count, int)
    assert result.trial_count >= 0
