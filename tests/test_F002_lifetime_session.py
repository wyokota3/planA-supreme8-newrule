"""F-002-2: 開封セッションの生涯1回制約（production）とダミーモード（複数回）。

specs/SPEC.md F-002-2 / F-013-3:
  「封印へのアクセスは開封セッション単位で生涯1回のみ。」「本番封印の生涯開封セッション数が1。」
specs/GUARD_IF.md:
  - SealGuard(production=True) の2回目発行は SessionLimitExceeded。失効しても枠は復活しない。
  - 運用規約2: 生涯計数のスコープは SealGuard インスタンスの寿命（インメモリ・R4）。
    プロセスを跨ぐ「生涯1回」の最終保証は、F-002 のアクセス制御と
    永続化されたセッションID付きログ/状態を突合して担保する（F-002 の責務）。
decisions/0009-f002-sealset-policies.md 決定2/3:
  - 生涯1回をプロセス跨ぎで検証可能にする（永続 JSONL ログ＋永続セッション状態）。
  - ダミーモード（production=False）は同一機構で複数回開封でき、常用テスト経路を確保。

----------------------------------------------------------------------------
このファイルが定義する supreme.sealset の前提 API（テスト駆動・report に明記）:

  SealStore.issue_open_token(session_id, issued_ts, *, precheck_passed) -> OpenToken
    内包 SealGuard.issue_token に委譲（生涯計数を消費）。production=True の2回目は
    guard.SessionLimitExceeded。precheck_passed=False は guard.PrecheckFailed。
    SealStore は発行成功のたびに root_dir/session_state.json を更新し、
    別インスタンス（プロセス再起動相当・同一 root_dir）でも生涯計数を引き継ぐ。

  SealStore.lifetime_session_count() -> int
    永続セッション状態を反映した生涯開封セッション数。

  SealStore.revoke_open_token(token, *, revoked_ts) -> None
    内包 SealGuard.revoke_token に委譲。
"""

import pytest

import fixtures_gt as fx
from supreme import datagov
from supreme import guard
from supreme import sealset


def _store(tmp_path, *, production):
    # register の ts は ADR 0010 追記でキーワード必須。正常登録は access_log に
    # 記録しないため、本ファイルの lifetime/ログ アサーションは ts 追加後も不変。
    store = sealset.SealStore(root_dir=tmp_path, production=production)
    store.register(fx.make_record("seal001", gt_origin="human"),
                   governor=datagov.DataGovernor(), ts=0.0)
    return store


# ---------------------------------------------------------------------------
# production: 生涯1回（同一インスタンス内）
# ---------------------------------------------------------------------------

def test_F002_2_production_first_issue_counts_one(tmp_path):
    """F-002-2: 本番封印で1回発行後の生涯開封セッション数は1。"""
    store = _store(tmp_path, production=True)
    store.issue_open_token("S1", issued_ts=100.0, precheck_passed=True)
    assert store.lifetime_session_count() == 1


def test_F002_2_production_second_issue_rejected(tmp_path):
    """F-002-2（陰性）: 本番封印で2セッション目の発行は拒否される。"""
    store = _store(tmp_path, production=True)
    store.issue_open_token("S1", issued_ts=100.0, precheck_passed=True)
    with pytest.raises(guard.SessionLimitExceeded):
        store.issue_open_token("S2", issued_ts=200.0, precheck_passed=True)


def test_F002_2_production_second_issue_rejected_even_after_revoke(tmp_path):
    """F-002-2（陰性）: 失効しても本番封印は生涯1回。失効後の2回目も拒否。

    失効＝評価終了であって再開封枠の復活ではない。
    """
    store = _store(tmp_path, production=True)
    tok = store.issue_open_token("S1", issued_ts=100.0, precheck_passed=True)
    store.revoke_open_token(tok, revoked_ts=200.0)
    with pytest.raises(guard.SessionLimitExceeded):
        store.issue_open_token("S2", issued_ts=300.0, precheck_passed=True)
    assert store.lifetime_session_count() == 1


# ---------------------------------------------------------------------------
# production: プロセス跨ぎ（新インスタンス＋同一 root_dir/状態ファイル）でも2回目拒否
# ---------------------------------------------------------------------------

def test_F002_2_production_second_issue_rejected_across_instances(tmp_path):
    """F-002-2（プロセス跨ぎ・核心）: 新インスタンス（同一 root_dir）でも2回目発行は拒否。

    GUARD_IF 運用規約2 を F-002 が実装する核心。1つ目のインスタンスで開封した後、
    プロセス再起動相当の新インスタンスが永続セッション状態を読み戻し、
    2セッション目を拒否する（インメモリ計数のみに依存しない）。
    """
    store1 = _store(tmp_path, production=True)
    store1.issue_open_token("S1", issued_ts=100.0, precheck_passed=True)
    assert store1.lifetime_session_count() == 1

    # プロセス再起動相当: 同一 root_dir を指す新インスタンス。
    store2 = sealset.SealStore(root_dir=tmp_path, production=True)
    assert store2.lifetime_session_count() == 1, (
        "新インスタンスが永続セッション状態を読み戻せていない"
    )
    with pytest.raises(guard.SessionLimitExceeded):
        store2.issue_open_token("S2", issued_ts=200.0, precheck_passed=True)


def test_F002_2_production_count_persists_after_revoke_across_instances(tmp_path):
    """F-002-2（プロセス跨ぎ）: 失効後に再起動しても生涯1回は維持され2回目は拒否。"""
    store1 = _store(tmp_path, production=True)
    tok = store1.issue_open_token("S1", issued_ts=100.0, precheck_passed=True)
    store1.revoke_open_token(tok, revoked_ts=200.0)

    store2 = sealset.SealStore(root_dir=tmp_path, production=True)
    assert store2.lifetime_session_count() == 1
    with pytest.raises(guard.SessionLimitExceeded):
        store2.issue_open_token("S2", issued_ts=300.0, precheck_passed=True)


# ---------------------------------------------------------------------------
# production: precheck 不合格は枠を消費しない
# ---------------------------------------------------------------------------

def test_F002_2_production_precheck_fail_does_not_consume_quota(tmp_path):
    """F-002-2: 事前検査不合格の発行失敗は生涯セッション枠を消費しない。"""
    store = _store(tmp_path, production=True)
    with pytest.raises(guard.PrecheckFailed):
        store.issue_open_token("S1", issued_ts=100.0, precheck_passed=False)
    assert store.lifetime_session_count() == 0
    # 失敗後でも正当な1回は可能（枠未消費）。
    store.issue_open_token("S1", issued_ts=110.0, precheck_passed=True)
    assert store.lifetime_session_count() == 1


# ---------------------------------------------------------------------------
# dummy モード: 複数回開封できる（常用テスト経路）が、ログには同様に記録される
# ---------------------------------------------------------------------------

def test_F002_2_dummy_allows_multiple_open_sessions(tmp_path):
    """F-002-2: ダミーモード（production=False）は複数回開封できる（常用テスト経路）。"""
    store = _store(tmp_path, production=False)
    tok1 = store.issue_open_token("S1", issued_ts=100.0, precheck_passed=True)
    store.revoke_open_token(tok1, revoked_ts=200.0)
    tok2 = store.issue_open_token("S2", issued_ts=300.0, precheck_passed=True)
    assert tok2.active is True
    assert store.lifetime_session_count() == 2


def test_F002_2_dummy_access_still_logged(tmp_path):
    """F-002-2: ダミーモードでもアクセスは同様に永続ログに記録される。

    機構は同一（ADR 0009 決定3）。dummy でもログの記録は省略しない。
    """
    store = _store(tmp_path, production=False)
    tok1 = store.issue_open_token("S1", issued_ts=100.0, precheck_passed=True)
    store.read_sealed_gt("seal001", token=tok1, ts=150.0)
    store.revoke_open_token(tok1, revoked_ts=200.0)
    tok2 = store.issue_open_token("S2", issued_ts=300.0, precheck_passed=True)
    store.read_sealed_gt("seal001", token=tok2, ts=350.0)

    log = store.access_log()
    assert len(log) == 2
    assert log[0]["session_id"] == "S1"
    assert log[1]["session_id"] == "S2"


def test_F002_2_sealstore_requires_explicit_production(tmp_path):
    """F-002-2（向き固定・陰性）: production を省略した SealStore は TypeError。

    GUARD_IF / SealGuard と同じ向き（ADR 0008 決定1）。書き忘れによる
    silent fail-open（本番封印を非本番扱いで複数回開封）を型レベルで排除する。
    """
    with pytest.raises(TypeError):
        sealset.SealStore(root_dir=tmp_path)
