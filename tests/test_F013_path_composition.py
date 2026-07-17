"""F-013 経路合成（陰性含む）: SealStore.open_eval_session が F-013 の唯一の正規開封経路で
あり、aggregate 強制（不合格は guard.Blocked・枠不消費）と、発行トークンの read 受理を固定する。

specs/SPEC.md F-013 着手条件（2026-06-12 監査由来・ADR 0010）:
  「SearchGate × SealStore の開封経路合成を設計時に解決すること。それまで
   SealStore.issue_open_token の直接使用禁止。」
specs/GUARD_IF.md §3 運用規約5:
  「開封の唯一の正規経路は SearchGate.open_token_for_eval。F-013 は issue_open_token を直接使わない。」
specs/GUARD_IF.md（SearchGate.open_token_for_eval）:
  aggregate 不合格 → guard.Blocked（枠不消費＝生涯計数不変）。
decisions/0023-f013-sealed-evaluation-design.md 決定1:
  open_eval_session は内部で gate=SearchGate(self._guard) を作り
  gate.open_token_for_eval(aggregate, session_id, issued_ts) を呼んで aggregate を**強制**し、
  store 自身の guard で発行する（後続 read_sealed_gt がそのトークンを受理）。
  aggregate 不合格は guard.Blocked（枠不消費＝lifetime_session_count 不変・session_state.json 不変）。
  発行成功で session_state を永続化する。F-013 経路で issue_open_token は使わない。

----------------------------------------------------------------------------
このファイルが定義する SealStore.open_eval_session の前提 API（テスト駆動・report 明記）:

  SealStore.open_eval_session(aggregate, session_id, issued_ts) -> guard.OpenToken
    F-013 の唯一の正規開封経路。
    - 内部で SearchGate(store 内包 guard).open_token_for_eval(aggregate, session_id, issued_ts)
      を呼び aggregate 検査を強制する。
    - aggregate 不合格 → guard.Blocked（枠不消費＝lifetime_session_count 不変・session_state 不変）。
    - 発行成功で生涯計数を消費し session_state.json を永続化する。
    - 返すトークンは read_sealed_gt(..., token=token, ...) に受理される（store 自身の guard 発行）。

注意（規律）: stdlib のみ・決定的。時刻はテストが供給。production=False のダミー封印で
経路全体をドライランする（穴2）。陰性（aggregate 不合格）でも枠不消費を機械検証する。
"""

import pytest

import fixtures_sealeval as fxs
from supreme import datagov
from supreme import guard
from supreme import sealset


def _store_with_dummy_seals(tmp_path, *, production=False):
    store = sealset.SealStore(root_dir=tmp_path, production=production)
    gov = datagov.DataGovernor()
    for rec in fxs.sealed_records_two_scenarios():
        store.register(rec, governor=gov, ts=0.0)
    return store


def _passing_aggregate():
    """全ガード合格の AggregateResult（開封が通る前提）。"""
    g1 = guard.check_param_budget(param_count=19, data_count=200, k=0.5)
    return guard.combine_guards([g1])


def _blocking_aggregate():
    """①不合格（過学習構成）の AggregateResult（開封がブロックされる構成）。"""
    g1 = guard.check_param_budget(param_count=300, data_count=200, k=0.5)
    return guard.combine_guards([g1])


# ===========================================================================
# 公開シンボルの存在（F-013 の正規開封経路）
# ===========================================================================

def test_F013_open_eval_session_exists(tmp_path):
    """F-013（契約面・ADR 0023 決定1）: SealStore は open_eval_session を公開する。

    SearchGate × SealStore の経路合成の具体化（ADR 0010 決定2 の解決）。
    """
    store = _store_with_dummy_seals(tmp_path)
    assert hasattr(store, "open_eval_session")
    assert callable(store.open_eval_session)


# ===========================================================================
# 陽性: 合格 aggregate で開封でき、そのトークンで read_sealed_gt が成功する（合成の健全性）
# ===========================================================================

def test_F013_open_eval_session_issues_token_on_pass(tmp_path):
    """F-013（経路合成・陽性）: 合格 aggregate で open_eval_session が開封トークンを発行し、
    生涯開封セッション数が1になる。
    """
    store = _store_with_dummy_seals(tmp_path)
    assert store.lifetime_session_count() == 0
    tok = store.open_eval_session(_passing_aggregate(),
                                  session_id="EVAL-1", issued_ts=100.0)
    assert tok.session_id == "EVAL-1"
    assert tok.active is True
    assert store.lifetime_session_count() == 1


def test_F013_open_eval_session_token_accepted_by_read(tmp_path):
    """F-013（合成の健全性・核心）: open_eval_session が返したトークンで read_sealed_gt が
    成功する（store 自身の guard 発行なので後続 read がそのトークンを受理する）。

    ADR 0023 決定1 が要求する「発行成功で read_sealed_gt がそのトークンを受理する」を固定。
    issue_open_token を使わず open_eval_session 経由のトークンが封印 GT を読めること。
    """
    store = _store_with_dummy_seals(tmp_path)
    tok = store.open_eval_session(_passing_aggregate(),
                                  session_id="EVAL-1", issued_ts=100.0)
    gt = store.read_sealed_gt("SEAL_P", token=tok, ts=150.0)
    assert gt["scenario_id"] == "SEAL_P"
    assert "frames" in gt
    # 同一トークンで別 scenario も同一セッション内で read できる（単一トークン下）。
    gt_q = store.read_sealed_gt("SEAL_Q", token=tok, ts=160.0)
    assert gt_q["scenario_id"] == "SEAL_Q"


def test_F013_open_eval_session_read_logged_with_session_id(tmp_path):
    """F-013（経路合成・ログ整合）: open_eval_session 経由 read は当該 session_id で記録される。

    access_log の read レコードが open_eval_session の session_id を持つ（単一セッション識別）。
    """
    store = _store_with_dummy_seals(tmp_path)
    tok = store.open_eval_session(_passing_aggregate(),
                                  session_id="EVAL-1", issued_ts=100.0)
    store.read_sealed_gt("SEAL_P", token=tok, ts=150.0)
    log = store.access_log()
    assert log[-1]["session_id"] == "EVAL-1"
    assert log[-1]["target"] == "SEAL_P"


# ===========================================================================
# 陰性: aggregate 不合格は guard.Blocked・枠不消費（lifetime/session_state 不変）
# ===========================================================================

def test_F013_open_eval_session_blocks_on_failing_aggregate(tmp_path):
    """F-013（経路合成・陰性・核心）: aggregate 不合格で open_eval_session は guard.Blocked を
    送出する（aggregate を素通しにしない＝SearchGate 経由の強制）。

    ADR 0010 着手条件「aggregate 検査を素通しにしない」。issue_open_token 直呼びの抜け道を塞ぐ。
    """
    store = _store_with_dummy_seals(tmp_path)
    with pytest.raises(guard.Blocked):
        store.open_eval_session(_blocking_aggregate(),
                                session_id="EVAL-1", issued_ts=100.0)


def test_F013_blocked_open_eval_session_does_not_consume_quota(tmp_path):
    """F-013（枠不消費・核心）: Blocked 時は生涯開封セッション数が増えない（枠不消費）。

    ADR 0023 決定1「aggregate 不合格は枠不消費＝lifetime_session_count 不変」。
    不合格で枠を焼くと、後の正当な開封ができなくなる（本番封印の生涯1回を取りこぼす）。
    """
    store = _store_with_dummy_seals(tmp_path)
    with pytest.raises(guard.Blocked):
        store.open_eval_session(_blocking_aggregate(),
                                session_id="EVAL-1", issued_ts=100.0)
    assert store.lifetime_session_count() == 0, "Blocked が枠を消費している"


def test_F013_blocked_open_eval_session_does_not_persist_session_state(tmp_path):
    """F-013（session_state 不変・プロセス跨ぎ）: Blocked 後に新インスタンスを作っても
    生涯計数は 0 のまま（session_state.json を進めていない）。

    ADR 0023 決定1「session_state.json 不変」。永続状態にも枠消費が漏れないことを固定する。
    """
    store = _store_with_dummy_seals(tmp_path)
    with pytest.raises(guard.Blocked):
        store.open_eval_session(_blocking_aggregate(),
                                session_id="EVAL-1", issued_ts=100.0)
    # プロセス再起動相当: 同一 root_dir の新インスタンス。
    store2 = sealset.SealStore(root_dir=tmp_path, production=False)
    assert store2.lifetime_session_count() == 0, (
        "Blocked が session_state.json を進めている（枠消費が永続化された）"
    )


def test_F013_blocked_then_valid_open_still_possible(tmp_path):
    """F-013（枠不消費の含意）: Blocked の後でも、合格 aggregate で正当な開封が1回できる。

    不合格で枠を焼かないので、後続の正規開封が成立する（枠不消費の実利を固定）。
    """
    store = _store_with_dummy_seals(tmp_path)
    with pytest.raises(guard.Blocked):
        store.open_eval_session(_blocking_aggregate(),
                                session_id="EVAL-X", issued_ts=100.0)
    tok = store.open_eval_session(_passing_aggregate(),
                                  session_id="EVAL-1", issued_ts=110.0)
    assert tok.active is True
    assert store.lifetime_session_count() == 1


# ===========================================================================
# production 意味論: open_eval_session も生涯1回を尊重する（2回目は SessionLimitExceeded）
# ===========================================================================

def test_F013_open_eval_session_production_second_open_rejected(tmp_path):
    """F-013-3（生涯1回・production）: production=True の SealStore で2回目の
    open_eval_session は SessionLimitExceeded で拒否される。

    open_eval_session は内包 guard 経由で発行するため、生涯1回制約が開封経路に効く
    （GUARD_IF: production の2回目は SessionLimitExceeded）。本番封印の生涯開封1回を固定する。
    """
    store = _store_with_dummy_seals(tmp_path, production=True)
    store.open_eval_session(_passing_aggregate(),
                            session_id="EVAL-1", issued_ts=100.0)
    with pytest.raises(guard.SessionLimitExceeded):
        store.open_eval_session(_passing_aggregate(),
                                session_id="EVAL-2", issued_ts=200.0)
    assert store.lifetime_session_count() == 1


# ===========================================================================
# リーク検査素材の健全性: ダミー封印 root は train root と非交差（fixture が跨がない）
# ===========================================================================

def test_F013_dummy_seal_lineage_disjoint_from_train(tmp_path):
    """F-013（リーク検査・規律）: ダミー封印 root（SEAL_P/SEAL_Q）が train root（TRAIN_R）と
    非交差なことを、封印登録が拒否されないことで固定する（封印 fixture が train を跨がない）。

    指示の規律「ダミー封印データには親系統タグを持たせ、リーク検査 fixture が跨がないこと」。
    train 系統を持つ governor に対し、独立 root の封印を登録できる（LineageCrossError でない）。
    """
    gov = datagov.DataGovernor()
    gov.register(fxs.train_root_record())  # train 側 TRAIN_R

    store = sealset.SealStore(root_dir=tmp_path, production=False)
    for rec in fxs.sealed_records_two_scenarios():
        store.register(rec, governor=gov, ts=0.0)  # 非交差なので拒否されない

    sealed = store.sealed_lineage_set()
    assert sealed == {"SEAL_P", "SEAL_Q"}
    # 封印 root 集合 ∩ train root 集合 = ∅（リーク検査・集合演算）。
    assert sealed & gov.lineage_set("train") == set(), (
        "ダミー封印 root が train root と交差している（fixture が系統を跨いでいる）"
    )
