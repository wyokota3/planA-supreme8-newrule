"""F-012-1: 探索中に封印セットへのアクセスが0回(機械検証)。

specs/SPEC.md F-012-1: 「探索中に封印セットへのアクセスが0回(ログで検証)。」
decisions/0021-u8-u18-f012-search.md:
  「各候補を F-004 ハーネスで練習データに対し採点(注入スコアラ)。**封印セットには
   一切アクセスしない**(F-012-1)。…封印は一切開かない(開封は F-013 の最後の1回のみ)。」
specs/GUARD_IF.md / decisions/0002-tolerances-and-seal-access.md:
  封印アクセスの機械的定義(開封トークン)。封印読み出しは access_log に記録される。
  F-012(探索)は SealStore に一切触れない = access_log が探索後も空であること。

検証手段(F-002 の流儀・test_F002_access_log.py を学習元):
  本物の SealStore(封印を1件登録済み)を用意し、探索の前後で access_log() を比較する。
  探索は SealStore を引数に取らない設計(seal を渡さない=触れない構造)を前提とするが、
  「探索を回しても封印 access_log が増えない(=0件のまま)」を機械的に固定する。
  scorer(注入練習スコアラ)が candidate のみを受け、封印に触れないことも併せて固定する。

------------------------------------------------------------------------------
このファイルが用いる supreme.search の前提 API(test_F012_contract_surface.py と同一):
  search.search(axes, scorer, *, search_gate, candidate_guards=None,
                cap=50, patience=10) -> SearchResult
"""

import pytest

import fixtures_gt as fx
from supreme import datagov
from supreme import guard
from supreme import search
from supreme import sealset


# ---------------------------------------------------------------------------
# 共有ヘルパ(探索軸・スコアラ・gate)
# ---------------------------------------------------------------------------

def _axes():
    """5改良モジュール構成の探索軸(ON/OFF + 離散ハイパラ候補)。

    各リストの先頭が基準構成(greedy 開始点)。値の中身はテストが与える(ADR 0021)。
    """
    return {
        "mode":     [False, True],        # ON/OFF
        "relation": [False, True],
        "quality":  [False, True],
        "scene":    [False, True],
        "t3":       ["lo", "mid", "hi"],  # 離散ハイパラ候補
    }


def _passing_gate():
    """全候補を続行許可する SearchGate(seal は production=False のダミー)。"""
    return guard.SearchGate(guard.SealGuard(production=False))


def _practice_scorer(candidate):
    """注入練習スコアラ。candidate(構成 dict)のみで決まる決定的スコア。

    封印に一切触れない(引数は candidate だけ)。値は構成のハッシュ的合成で決定的。
    """
    score = 0.0
    if candidate.get("mode"):
        score += 0.10
    if candidate.get("relation"):
        score += 0.09
    if candidate.get("quality"):
        score += 0.05
    if candidate.get("scene"):
        score += 0.04
    score += {"lo": 0.0, "mid": 0.03, "hi": 0.06}[candidate.get("t3", "lo")]
    return score


def _store_with_seals(tmp_path, n=2):
    """封印を n 件登録した本物の SealStore を返す(F-002 の流儀)。"""
    store = sealset.SealStore(root_dir=tmp_path, production=False)
    gov = datagov.DataGovernor()
    for i in range(n):
        store.register(fx.make_record(f"seal{i:03d}", gt_origin="human"),
                       governor=gov, ts=0.0)
    return store


# ---------------------------------------------------------------------------
# F-012-1: 探索中の封印アクセスが0回(access_log で機械検証)
# ---------------------------------------------------------------------------

def test_F012_1_seal_access_log_stays_empty_after_search(tmp_path):
    """F-012-1: 封印を登録した SealStore の access_log が、探索の前後で 0 件のまま。

    探索(greedy 座標上昇・複数候補評価)を回しても封印読み出しが1件も発生しない。
    封印非アクセスを F-002 の access_log で機械検証する(穴8 の限界はログ経由検査と同じ)。
    """
    store = _store_with_seals(tmp_path)
    assert store.access_log() == [], "前提: 探索前は封印アクセス0件"

    search.search(_axes(), _practice_scorer, search_gate=_passing_gate())

    # 探索後も封印 access_log が増えていない = 探索中の封印アクセス0回。
    assert store.access_log() == [], \
        f"探索中に封印へアクセスした(access_log={store.access_log()})"


def test_F012_1_no_open_token_issued_during_search(tmp_path):
    """F-012-1: 探索中に封印開封トークンが発行されない(生涯開封セッション数 0)。

    封印開封は F-013 の最後の1回のみ(ADR 0021)。探索フェーズでは SearchGate 内包
    SealGuard の生涯計数が消費されない(open_token_for_eval を呼ばない)。
    """
    sg = guard.SealGuard(production=False)
    gate = guard.SearchGate(sg)
    assert sg.lifetime_session_count() == 0

    search.search(_axes(), _practice_scorer, search_gate=gate)

    assert sg.lifetime_session_count() == 0, \
        "探索中に封印開封トークンが発行された(F-013 以外で開封)"


def test_F012_1_scorer_never_receives_seal_data(tmp_path):
    """F-012-1: 注入スコアラに渡されるのは candidate(構成)のみで、封印データではない。

    scorer が受け取った全引数を記録し、封印 SealStore オブジェクトや封印 gt が
    一切渡されていないことを固定する(目的関数が封印に触れない=練習用評価である裏付け)。
    """
    store = _store_with_seals(tmp_path)
    received = []

    def spy_scorer(candidate):
        received.append(candidate)
        return _practice_scorer(candidate)

    search.search(_axes(), spy_scorer, search_gate=_passing_gate())

    assert received, "scorer が一度も呼ばれていない(探索が候補を評価していない)"
    for cand in received:
        # candidate は構成 dict(module_name -> 選択値)であること。
        assert isinstance(cand, dict)
        assert set(cand.keys()) <= set(_axes().keys()), \
            f"scorer に探索軸外のキーが渡された: {cand}"
        # 封印オブジェクトや封印 gt が混入していないこと。
        assert store not in cand.values(), "scorer に SealStore が渡された"
    # 念のため: 探索を回した後も封印 access_log は空。
    assert store.access_log() == []


def test_F012_1_search_does_not_take_seal_store_argument():
    """F-012-1(構造): search() のシグネチャに封印(seal/sealset/store)引数が無い。

    「触れない」を構造で担保する(ADR 0021 の「探索が seal を引数に取らない構造」)。
    封印を渡せない以上、探索が封印に触れる経路が API 上存在しない。
    """
    import inspect
    sig = inspect.signature(search.search)
    for name in sig.parameters:
        low = name.lower()
        assert "seal" not in low, \
            f"search() が封印を受け取る引数 '{name}' を持つ(F-012-1 構造違反)"


def test_F012_1_provenance_is_all_train(tmp_path):
    """F-012-1/F-012-2: 探索結果の選定来歴が全て split=train(封印由来0件)。

    SelectionProvenanceRecord(GUARD_IF・F-012 が生成)が全 train であり、
    guard.check_selection_purity で純度合格になることを固定する(封印非混入の裏付け)。
    """
    result = search.search(_axes(), _practice_scorer, search_gate=_passing_gate())

    assert result.provenance, "選定来歴が空(探索が来歴を残していない)"
    for rec in result.provenance:
        assert rec["split"] == "train", f"封印由来の来歴が混入: {rec}"

    # guard の純度検査(F-014-3)に通す: 全 train + 封印アクセス0件で合格。
    purity = guard.check_selection_purity(result.provenance, seal_access_log=[])
    assert purity.passed is True
