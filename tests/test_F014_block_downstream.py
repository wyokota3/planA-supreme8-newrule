"""F-014 統合: ガード不合格時に後続(探索・封印評価)を実際にブロックする。

specs/SPEC.md F-014:
  正常系「各規律を検査し合格時のみ後続へ。」
  異常系「違反検出で後続(探索・封印評価)をブロックし報告。」
  出力「合否(違反時は後続をブロック)。」

TEST_STRATEGY.md「F-014」:
  「統合: 違反検出時に後続(探索・封印評価)を**実際にブロック**する。」
  「ガードレールが『合格を出すべきでないケースで合格を出さない』陰性テスト
   (過学習構成・リーク構成・封印多重アクセス構成をわざと作ってブロックされること)。」

decisions/0007-f014-guard-policies.md:
  ①は必須(k 未供給で不合格 → ブロック)、④は候補(未供給で未検査 → ブロックしない)。

------------------------------------------------------------------------
テストが定義する supreme.guard の公開 API(集約・後続制御):

  guard.combine_guards(results) -> AggregateResult
    - results: GuardResult の列(①②③④の任意部分集合)。
    - 集約規則: checked=True のガードが**全て** passed=True → 全体合格。
      checked=False(④未検査)のガードは合否に算入しない(候補ガード・ADR 0007)。
      checked=True のガードが1件でも passed=False → 全体不合格。
    - **空リスト([])は不合格**(ADR 0008 決定6・fail-closed)。検査が1件も無いことは
      合格の根拠が無いことであり、空虚合格(empty-vacuous pass)を排除する。
      reason に空集約である旨を明示し、後続(探索続行・トークン発行)をブロックする。

  AggregateResult(レコード契約・集約結果):
    .passed   : bool        後続を許可してよいか(checked=True が全合格・空は不合格)。
    .results  : tuple       入力 GuardResult をそのまま保持(報告用)。
    .blocked_by: tuple[str] passed=False だった checked ガードの guard_id(因果の根拠)。
    .reason   : str         判定理由(人間可読・空でない)。空集約や不合格の根拠を記す
                            (ADR 0008 決定6 で空集約の真実な理由報告を要求)。

  guard.SearchGate(seal_guard):
    探索の続行許可ゲート(F-012 が経由する制御点)。
    構築時に SealGuard を内包する(ADR 0008 決定2・発行経路の統合)。
    開封トークンの発行は必ず内包 SealGuard を経由し、生涯セッション計数を消費する。
    .request_continue(aggregate) -> bool
        aggregate.passed が True のときのみ続行許可(True)。不合格なら False(ブロック)。
    .open_token_for_eval(aggregate, session_id, issued_ts) -> OpenToken
        aggregate.passed が True のときのみ開封トークンを発行する(F-013 へ)。
        発行は内包 SealGuard 経由(precheck_passed = aggregate.passed を導出)で行い、
        生涯セッション計数を消費する。事前検査は **AggregateResult を直接受ける**
        (自己申告 bool を受ける別経路は持たない・ADR 0008 決定2)。
        不合格なら guard.Blocked を送出(トークンを発行しない = 封印評価をブロック)。
        内包 SealGuard が production=True の場合、2回目の発行は SealGuard 側の
        生涯1回制約により guard.SessionLimitExceeded で拒否される。

  発行経路の位置づけ(ADR 0008 決定2・本ファイルで設計し報告に明記):
    - SealGuard.issue_token(..., precheck_passed=<bool>) は低レベル基本操作であり、
      呼び出し側の自己申告 bool を信頼する。アプリ正規経路ではない。
    - SearchGate.open_token_for_eval(aggregate, ...) が **唯一のアプリ正規発行経路**。
      precheck_passed を本物の AggregateResult から導出し、自己申告 bool の混入を
      統合境界で排除する。F-013 はこの経路を使う(test_F014_seal_token.py の
      issue_token 直接呼び出しは低レベル契約の単体検証)。

  例外: guard.Blocked(後続ブロックを表す) / guard.SessionLimitExceeded。

これにより「違反検出 → ブロック」の因果(不合格なら続行許可が出ない/トークンが発行されない)
と「全ガード合格時のみ後続許可」(陽性対照)を両方向でテストする。
"""

import pytest

from supreme import guard


# ---------------------------------------------------------------------------
# 集約規則: checked 全合格で合格 / 1件でも不合格でブロック / 未検査は算入しない
# ---------------------------------------------------------------------------

def test_F014_combine_pass_when_all_checked_guards_pass():
    """F-014(陽性対照): checked なガードが全て合格 → 集約合格。"""
    g1 = guard.check_param_budget(param_count=19, data_count=200, k=0.1)   # 合格
    g3 = guard.check_selection_purity([{"eval_id": "e1", "split": "train",
                                        "scenario_id": "A_c1", "score": 0.5}])  # 合格
    agg = guard.combine_guards([g1, g3])
    assert agg.passed is True
    assert agg.blocked_by == ()


def test_F014_combine_fail_when_any_checked_guard_fails():
    """F-014(陰性): checked なガードが1件でも不合格 → 集約不合格・blocked_by に記録。"""
    g1 = guard.check_param_budget(param_count=300, data_count=200, k=0.1)  # 不合格(過学習構成)
    g3 = guard.check_selection_purity([{"eval_id": "e1", "split": "train",
                                        "scenario_id": "A_c1", "score": 0.5}])  # 合格
    agg = guard.combine_guards([g1, g3])
    assert agg.passed is False
    assert "F-014-1" in agg.blocked_by


def test_F014_combine_unchecked_guard4_does_not_block():
    """F-014(①④挙動差): ④未検査(checked=False)は集約合否に算入されない。

    ①②③が全合格で ④だけ未検査なら、全体は合格(候補ガードは止めない・ADR 0007)。
    """
    g1 = guard.check_param_budget(param_count=19, data_count=200, k=0.1)  # 合格
    g4 = guard.check_trial_cap(trial_count=999999, cap=None)              # 未検査
    agg = guard.combine_guards([g1, g4])
    assert agg.passed is True
    assert "F-014-4" not in agg.blocked_by


def test_F014_combine_fail_closed_when_k_missing():
    """F-014(陰性・①fail-closed): k 未供給で①が不合格 → 集約もブロック。

    ④(未供給→未検査でスルー)との対比。①は未供給でも checked=True/passed=False で止める。
    """
    g1 = guard.check_param_budget(param_count=0, data_count=200, k=None)  # fail-closed 不合格
    agg = guard.combine_guards([g1])
    assert agg.passed is False
    assert "F-014-1" in agg.blocked_by


# ---------------------------------------------------------------------------
# 後続ブロック(探索続行): 不合格なら続行許可が出ない / 合格なら出る
# ---------------------------------------------------------------------------

def test_F014_search_gate_allows_continue_when_all_pass():
    """F-014(陽性対照): 全ガード合格時のみ探索続行が許可される。"""
    g1 = guard.check_param_budget(param_count=19, data_count=200, k=0.1)
    agg = guard.combine_guards([g1])
    gate = guard.SearchGate(guard.SealGuard(production=False))
    assert gate.request_continue(agg) is True


def test_F014_search_gate_blocks_continue_on_violation():
    """F-014(因果: 違反検出 → ブロック): ガード不合格なら探索続行が許可されない。"""
    # 過学習構成(param ≫ budget)で①不合格 → ブロック。
    g1 = guard.check_param_budget(param_count=300, data_count=200, k=0.1)
    agg = guard.combine_guards([g1])
    gate = guard.SearchGate(guard.SealGuard(production=False))
    assert gate.request_continue(agg) is False


def test_F014_search_gate_blocks_on_leak_construction():
    """F-014(陰性・リーク構成): seal 由来の選定混入 → ③不合格 → 探索ブロック。"""
    g3 = guard.check_selection_purity([
        {"eval_id": "e1", "split": "train", "scenario_id": "A_c1", "score": 0.5},
        {"eval_id": "e2", "split": "seal", "scenario_id": "C", "score": 0.9},  # 汚染
    ])
    agg = guard.combine_guards([g3])
    gate = guard.SearchGate(guard.SealGuard(production=False))
    assert gate.request_continue(agg) is False


# ---------------------------------------------------------------------------
# 後続ブロック(封印評価): 不合格なら開封トークンが発行されない / 合格なら発行
# ---------------------------------------------------------------------------

def test_F014_eval_token_issued_only_when_all_pass():
    """F-014(陽性対照): 全ガード合格時のみ封印評価の開封トークンが発行される。"""
    g1 = guard.check_param_budget(param_count=19, data_count=200, k=0.1)
    agg = guard.combine_guards([g1])
    gate = guard.SearchGate(guard.SealGuard(production=False))
    tok = gate.open_token_for_eval(agg, session_id="S1", issued_ts=100.0)
    assert tok.session_id == "S1"
    assert tok.active is True


def test_F014_eval_token_blocked_on_violation():
    """F-014(因果: 違反検出 → 封印評価ブロック): 不合格なら開封トークンを発行しない。

    「検査合格が無いと開封トークンが発行されない」= 封印評価が始められない、を検証する。
    """
    g1 = guard.check_param_budget(param_count=300, data_count=200, k=0.1)  # 不合格
    agg = guard.combine_guards([g1])
    gate = guard.SearchGate(guard.SealGuard(production=False))
    with pytest.raises(guard.Blocked):
        gate.open_token_for_eval(agg, session_id="S1", issued_ts=100.0)


def test_F014_eval_token_blocked_on_seal_multiaccess_construction():
    """F-014(陰性・封印多重アクセス構成 → ブロック):

    選定期間中に封印アクセスがあった(F-014-3 の seal_access_log 経路)→ ③不合格 →
    封印評価の開封トークンは発行されない。
    """
    g3 = guard.check_selection_purity(
        provenance=[{"eval_id": "e1", "split": "train",
                     "scenario_id": "A_c1", "score": 0.5}],
        seal_access_log=[{"session_id": None, "ts": 120.0, "target": "seal_C"}],
    )
    agg = guard.combine_guards([g3])
    gate = guard.SearchGate(guard.SealGuard(production=False))
    with pytest.raises(guard.Blocked):
        gate.open_token_for_eval(agg, session_id="S1", issued_ts=100.0)


# ---------------------------------------------------------------------------
# 全ガード合格の end-to-end 陽性対照(①②③④の代表的合格構成)
# ---------------------------------------------------------------------------

def test_F014_full_pass_path_allows_search_and_eval():
    """F-014(陽性対照・統合): ①合格・③合格・④上限内合格 → 続行許可 ＋ トークン発行。"""
    g1 = guard.check_param_budget(param_count=19, data_count=200, k=0.1)
    g3 = guard.check_selection_purity(
        provenance=[{"eval_id": "e1", "split": "train",
                     "scenario_id": "A_c1", "score": 0.5}],
        seal_access_log=[],
    )
    g4 = guard.check_trial_cap(trial_count=5, cap=10)
    agg = guard.combine_guards([g1, g3, g4])
    assert agg.passed is True

    gate = guard.SearchGate(guard.SealGuard(production=False))
    assert gate.request_continue(agg) is True
    tok = gate.open_token_for_eval(agg, session_id="S1", issued_ts=100.0)
    assert tok.active is True


# ---------------------------------------------------------------------------
# 発行経路の統合(ADR 0008 決定2)
#   SearchGate が SealGuard を内包し、open_token_for_eval は必ず内包 SealGuard 経由で
#   発行して生涯計数を消費する。Blocked 時は消費しない。production=True なら2回目拒否。
# ---------------------------------------------------------------------------

def _passing_aggregate():
    """全ガード合格の AggregateResult を作る(発行が通る前提構成)。"""
    g1 = guard.check_param_budget(param_count=19, data_count=200, k=0.1)
    return guard.combine_guards([g1])


def _blocking_aggregate():
    """①不合格(過学習構成)の AggregateResult を作る(発行がブロックされる構成)。"""
    g1 = guard.check_param_budget(param_count=300, data_count=200, k=0.1)
    return guard.combine_guards([g1])


def test_F014_open_token_consumes_lifetime_count_of_internal_sealguard():
    """F-014(ADR 0008 決定2・①): 発行成功時、内包 SealGuard の生涯計数が増える。

    発行経路が SealGuard を経由している(計数を消費する)ことの直接証拠。
    旧 open_token_for_eval は SealGuard を経由せず計数しなかった(監査の構造的欠陥)。
    """
    sg = guard.SealGuard(production=False)
    gate = guard.SearchGate(sg)
    assert sg.lifetime_session_count() == 0
    gate.open_token_for_eval(_passing_aggregate(), session_id="S1", issued_ts=100.0)
    assert sg.lifetime_session_count() == 1


def test_F014_blocked_open_token_does_not_consume_lifetime_count():
    """F-014(ADR 0008 決定2・②): Blocked 時は内包 SealGuard の生涯計数が増えない。

    不合格(Blocked)はセッション枠を消費しない。発行が起きていないことの証拠。
    """
    sg = guard.SealGuard(production=False)
    gate = guard.SearchGate(sg)
    with pytest.raises(guard.Blocked):
        gate.open_token_for_eval(_blocking_aggregate(), session_id="S1", issued_ts=100.0)
    assert sg.lifetime_session_count() == 0


def test_F014_production_gate_rejects_second_issue():
    """F-014(ADR 0008 決定2・③): production=True を内包した gate は2回目の発行を拒否。

    内包 SealGuard が production=True のとき、生涯1回制約が発行経路に効く。
    2回目の open_token_for_eval は SealGuard 側の SessionLimitExceeded で拒否される。
    """
    sg = guard.SealGuard(production=True)
    gate = guard.SearchGate(sg)
    gate.open_token_for_eval(_passing_aggregate(), session_id="S1", issued_ts=100.0)
    with pytest.raises(guard.SessionLimitExceeded):
        gate.open_token_for_eval(_passing_aggregate(), session_id="S2", issued_ts=200.0)
    assert sg.lifetime_session_count() == 1


def test_F014_open_token_takes_aggregate_not_self_reported_bool():
    """F-014(ADR 0008 決定2・④): 事前検査は AggregateResult を直接受ける。

    自己申告 bool(precheck_passed=True 等)を渡す別経路を open_token_for_eval は
    持たない。precheck_passed=True を bool として渡しても、それは AggregateResult
    ではないため発行は通らない(.passed 属性が無い → 合格扱いにならず Blocked か例外)。
    自己申告 bool での素通しが統合境界に存在しないことを固定する。
    """
    sg = guard.SealGuard(production=False)
    gate = guard.SearchGate(sg)
    with pytest.raises((guard.Blocked, AttributeError, TypeError)):
        gate.open_token_for_eval(True, session_id="S1", issued_ts=100.0)
    assert sg.lifetime_session_count() == 0


# ---------------------------------------------------------------------------
# combine_guards([]) は不合格(ADR 0008 決定6・空虚合格の排除・fail-closed)
# ---------------------------------------------------------------------------

def test_F014_combine_empty_is_not_passed():
    """F-014(ADR 0008 決定6・陰性): 空リストの集約は passed=False(空虚合格の排除)。

    結果構築側のバグで空リストが渡ると、旧実装は passed=True で発行まで素通し
    (fail-open)だった。空は「検査が1件も無い=合格を出す根拠が無い」として不合格。
    """
    agg = guard.combine_guards([])
    assert agg.passed is False


def test_F014_combine_empty_has_reason_and_blocks_downstream():
    """F-014(ADR 0008 決定6): 空集約は理由つきで不合格 → 後続もブロックされる。

    空虚合格でトークンが発行される fail-open 経路が塞がれていることを、
    request_continue/open_token_for_eval の両方で固定する。
    """
    agg = guard.combine_guards([])
    # 理由(報告契約)が空でない(AggregateResult.reason)。
    assert isinstance(agg.reason, str) and agg.reason.strip() != ""

    sg = guard.SealGuard(production=False)
    gate = guard.SearchGate(sg)
    assert gate.request_continue(agg) is False
    with pytest.raises(guard.Blocked):
        gate.open_token_for_eval(agg, session_id="S1", issued_ts=100.0)
    assert sg.lifetime_session_count() == 0
