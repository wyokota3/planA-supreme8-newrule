"""F-012 公開契約面: supreme.search モジュールの公開 API が存在し、
ADR 0021 の探索オーケストレーション(決定的 greedy 座標上昇・注入スコアラ・guard 経由)を
供給可能な「探索の規律」エンジンであること。

specs/SPEC.md F-012(組み合わせ探索) / 対応コンポーネント `search`:
  - F-012-1: 探索中に封印セットへのアクセスが0回(ログで検証)。
  - F-012-2: 選定は練習用スコアのみに基づく。
  - F-012-3: 探索試行回数が定義された上限内(U18 確定後)。

decisions/0021-u8-u18-f012-search.md(手法の正):
  - 探索空間 = 5改良モジュール構成(ON/OFF + 離散ハイパラ候補)。強い項目は探索対象外・常時 ON。
  - 手法 = 決定的 greedy 座標上昇(基準構成から各軸を固定順走査・乱数/時刻なし=再現的)。
  - 目的関数 = 練習データのハーネススコア(注入スコアラ・封印には一切アクセスしない)。
  - 制約 = ガードレール(SearchGate/aggregate 経由)。違反候補は不採用。
  - U18: 試行上限(ハード上限)= 50・無改善 patience = 10。
specs/GUARD_IF.md:
  - F-012 は guard 契約に従う側。SearchGate.request_continue / check_param_budget /
    check_trial_cap / combine_guards を再利用する。SelectionProvenanceRecord は F-012 が生成。

------------------------------------------------------------------------------
このファイルが定義する supreme.search の前提 API(テスト駆動・report に明記):

  search.search(axes, scorer, *, search_gate, candidate_guards=None,
                cap=50, patience=10) -> SearchResult
    - axes        : 探索軸。各改良モジュールの構成候補。順序付き dict
                    {module_name: [候補値, ...]} で表現する(候補構造はテストが与える)。
                    各リストの先頭要素が基準構成(greedy の開始点)。
    - scorer      : 注入する練習スコアラ。scorer(candidate) -> float。
                    candidate は module_name -> 選択値 の dict(現構成)。
                    練習データのハーネススコア(テストは fake で決定的に与える)。
    - search_gate : guard.SearchGate。候補の guard 集約合否で続行可否を判定する制御点。
    - candidate_guards: 省略可。candidate を受け、その候補の guard 結果列
                    (GuardResult のリスト。param 予算・δ_strong 等)を返す callable。
                    search はこれを combine_guards で集約し search_gate.request_continue に
                    かける。集約不合格(False)の候補は不採用。None なら guard 制約なし。
    - cap         : 試行上限(ハード上限・既定 50・U18)。試行回数は cap を超えない。
    - patience    : 無改善撤退基準(既定 10・U18)。連続 patience 試行で改善が無ければ撤退。

  SearchResult(レコード契約・探索結果):
    .best_config  : dict   練習ベスト構成(module_name -> 選択値)。
    .best_score   : float  best_config の練習スコア。
    .trial_count  : int    実施した探索試行回数(>=0、cap 以下)。
    .provenance   : list   選定来歴(SelectionProvenanceRecord の列・全 split="train")。
    .trials       : list   試行列(決定的。各要素は評価した candidate と score を含む)。

設計裁量(ADR 0021 で test-writer に委任された範囲・既存 guard/harness/sealset の流儀に合わせる):
  - 候補(module-config)の dict 表現、SearchResult のフィールド名は本ファイルが定義。
  - 封印非アクセスの検証手段は F-002 の access_log を用いる(別ファイル test_F012_seal_isolation.py)。
"""

import inspect

import pytest

from supreme import search


# ---------------------------------------------------------------------------
# 公開シンボルの存在
# ---------------------------------------------------------------------------

def test_F012_search_module_exposes_search():
    """F-012(契約面): search は探索オーケストレーション関数 search() を公開する。"""
    assert hasattr(search, "search"), "search.search が公開されていない"
    assert callable(search.search)


def test_F012_search_signature_accepts_axes_and_scorer():
    """F-012(契約面・ADR 0021): search() は探索軸(axes)と注入スコアラ(scorer)を
    引数で受け取る(候補生成 + 注入スコアラの契約)。

    探索空間も目的関数もハードコードせず外から供給する(注入)。
    """
    sig = inspect.signature(search.search)
    params = list(sig.parameters)
    assert "axes" in params or len(params) >= 2, \
        "search() が探索軸を引数で受け取らない(探索空間ハードコードの疑い)"
    assert "scorer" in params or len(params) >= 2, \
        "search() が注入スコアラを引数で受け取らない(目的関数ハードコードの疑い)"


def test_F012_search_signature_accepts_search_gate():
    """F-012(契約面・GUARD_IF): search() は guard ゲート(search_gate)を受け取る。

    候補の guard 集約合否で続行可否を判定する制御点を外から供給する(F-012×F-014 連携)。
    """
    sig = inspect.signature(search.search)
    assert "search_gate" in sig.parameters, \
        "search() が search_gate を受け取らない(guard 経由でない疑い)"


def test_F012_search_cap_defaults_to_50_per_u18():
    """F-012-3(契約面・ADR 0021 U18): cap の既定値が 50(試行上限のハード ceiling)。

    U18 で確定した試行上限 50 が API の既定として供給されること。
    """
    sig = inspect.signature(search.search)
    assert "cap" in sig.parameters, "search() が cap を受け取らない"
    assert sig.parameters["cap"].default == 50, \
        f"cap の既定が 50(U18)でない: {sig.parameters['cap'].default}"


def test_F012_search_patience_defaults_to_10_per_u18():
    """F-012-3(契約面・ADR 0021 U18): patience の既定値が 10(無改善撤退基準)。"""
    sig = inspect.signature(search.search)
    assert "patience" in sig.parameters, "search() が patience を受け取らない"
    assert sig.parameters["patience"].default == 10, \
        f"patience の既定が 10(U18)でない: {sig.parameters['patience'].default}"


def test_F012_search_gate_is_keyword_only():
    """F-012(契約面): search_gate は誤用防止のためキーワード専用で受ける。

    guard 制御点を位置引数で取り違える事故を防ぐ(既存 guard API の流儀=明示必須)。
    """
    sig = inspect.signature(search.search)
    p = sig.parameters["search_gate"]
    assert p.kind == inspect.Parameter.KEYWORD_ONLY, \
        "search_gate はキーワード専用であるべき"
