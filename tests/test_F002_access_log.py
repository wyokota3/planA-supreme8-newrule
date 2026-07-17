"""F-002-2: 封印アクセス制御（トークンゲート）と永続 JSONL アクセスログ。

specs/SPEC.md F-002-2:
  「封印へのアクセスは開封セッション単位で生涯1回のみ。…有効トークン外の読み出しは
   拒否・記録する（セッションID付きアクセスログで検証）。」
specs/GUARD_IF.md（F-002 はこれに従う側）:
  - SealGuard / OpenToken / is_access_allowed / audit_seal_access の契約。
  - SealAccessRecord（封印アクセスログ1件）は F-002 が生成する:
      dict {"session_id": str|None, "ts": float, "target": str}
      有効トークン下のアクセス=その session_id、トークン無し不正アクセス=None。
  - 運用規約2: プロセス跨ぎの「生涯1回」最終保証は、F-002 のアクセス制御と
    永続化されたセッションID付きログを audit_seal_access+lifetime_session_count で突合して担保。
decisions/0009-f002-sealset-policies.md 決定2:
  全アクセス試行（拒否含む）を永続 JSONL ログ（SealAccessRecord 形式）に追記し、
  生涯1回をプロセス跨ぎで検証可能にする。

----------------------------------------------------------------------------
このファイルが定義する supreme.sealset の前提 API（テスト駆動・report に明記）:

  SealStore(*, root_dir, production, seal_guard=None)
    - SealStore は内部に guard.SealGuard を持つ（production を引き継ぐ）。
    - root_dir/access_log.jsonl に SealAccessRecord を1行=1レコードで追記する。

  SealStore.issue_open_token(session_id, issued_ts, *, precheck_passed) -> OpenToken
    内包 SealGuard.issue_token への委譲（生涯計数を消費）。GUARD_IF の契約どおり、
    precheck_passed=False は guard.PrecheckFailed、production の2回目は
    guard.SessionLimitExceeded。

  SealStore.read_sealed_gt(scenario_id, *, token, ts) -> dict
    封印された gt 本体（dict）を読み出す。
    - token が有効（発行済み・未失効・ts が有効期間内）なら gt を返し、
      access_log に {"session_id": token.session_id, "ts": ts, "target": scenario_id} を追記。
    - token が None / 失効後 / 窓外 ts なら sealset.AccessDenied を送出し、
      access_log に {"session_id": None, "ts": ts, "target": scenario_id} を追記
      （拒否がログに残ることが本質）。

  SealStore.revoke_open_token(token, *, revoked_ts) -> None
    内包 SealGuard.revoke_token への委譲（F-013 終了相当）。

  SealStore.access_log() -> list[dict]
    現インスタンスが参照する永続ログ（root_dir/access_log.jsonl）を読み戻した
    SealAccessRecord のリスト。
"""

import pytest

import fixtures_gt as fx
from supreme import datagov
from supreme import guard
from supreme import sealset


def _store_with_one_seal(tmp_path, *, production=False, scenario_id="seal001"):
    """封印を1件登録した SealStore を返す。

    register の ts は ADR 0010 追記でキーワード必須。正常登録は access_log に
    記録しない契約のため、各テストの access_log アサーション(成功/拒否のみ)は
    ts 追加後も不変。登録時刻は読み出し時刻群より十分前の 0.0 とする。
    """
    store = sealset.SealStore(root_dir=tmp_path, production=production)
    store.register(fx.make_record(scenario_id, gt_origin="human"),
                   governor=datagov.DataGovernor(), ts=0.0)
    return store


# ---------------------------------------------------------------------------
# 有効トークン経由の読み出しのみ成功
# ---------------------------------------------------------------------------

def test_F002_2_read_with_valid_token_succeeds(tmp_path):
    """F-002-2: 有効トークン経由の封印読み出しは成功し gt 本体を返す。"""
    store = _store_with_one_seal(tmp_path)
    tok = store.issue_open_token("S1", issued_ts=100.0, precheck_passed=True)
    gt = store.read_sealed_gt("seal001", token=tok, ts=150.0)
    assert gt["scenario_id"] == "seal001"
    assert "frames" in gt


def test_F002_2_successful_access_logged_with_session_id(tmp_path):
    """F-002-2: 成功アクセスは session_id 付きで永続ログに記録される。"""
    store = _store_with_one_seal(tmp_path)
    tok = store.issue_open_token("S1", issued_ts=100.0, precheck_passed=True)
    store.read_sealed_gt("seal001", token=tok, ts=150.0)

    log = store.access_log()
    assert len(log) == 1
    assert log[0]["session_id"] == "S1"
    assert log[0]["ts"] == 150.0
    assert log[0]["target"] == "seal001"


# ---------------------------------------------------------------------------
# 拒否系: トークン無し / 失効後 / 窓外 ts。拒否は session_id=None でログに残る
# ---------------------------------------------------------------------------

def test_F002_2_read_without_token_denied_and_logged(tmp_path):
    """F-002-2（陰性）: トークン無しの読み出しは拒否され、session_id=None で記録される。"""
    store = _store_with_one_seal(tmp_path)
    with pytest.raises(sealset.AccessDenied):
        store.read_sealed_gt("seal001", token=None, ts=150.0)

    log = store.access_log()
    assert len(log) == 1
    assert log[0]["session_id"] is None
    assert log[0]["ts"] == 150.0
    assert log[0]["target"] == "seal001"


def test_F002_2_read_after_revoke_denied_and_logged(tmp_path):
    """F-002-2（陰性・失効後）: 失効後トークンの読み出しは拒否され、session_id=None で記録。

    失効後アクセスは「有効トークン外」＝不正アクセス。拒否がログに残ることが本質。
    """
    store = _store_with_one_seal(tmp_path)
    tok = store.issue_open_token("S1", issued_ts=100.0, precheck_passed=True)
    store.revoke_open_token(tok, revoked_ts=200.0)

    with pytest.raises(sealset.AccessDenied):
        store.read_sealed_gt("seal001", token=tok, ts=250.0)  # 失効後

    log = store.access_log()
    assert len(log) == 1
    assert log[0]["session_id"] is None
    assert log[0]["ts"] == 250.0


def test_F002_2_read_before_issue_window_denied_and_logged(tmp_path):
    """F-002-2（陰性・窓外 ts）: 発行時刻より前（窓外）の読み出しは拒否され記録される。"""
    store = _store_with_one_seal(tmp_path)
    tok = store.issue_open_token("S1", issued_ts=100.0, precheck_passed=True)

    with pytest.raises(sealset.AccessDenied):
        store.read_sealed_gt("seal001", token=tok, ts=50.0)  # 発行前=窓外

    log = store.access_log()
    assert len(log) == 1
    assert log[0]["session_id"] is None
    assert log[0]["ts"] == 50.0


def test_F002_2_read_at_revoked_ts_denied_half_open_window(tmp_path):
    """F-002-2（境界・上端開）: ts == revoked_ts は窓外（半開区間 [issued, revoked)）。

    GUARD_IF: 窓は半開区間。失効時刻ちょうどのアクセスは窓外=拒否・記録される。
    """
    store = _store_with_one_seal(tmp_path)
    tok = store.issue_open_token("S1", issued_ts=100.0, precheck_passed=True)
    store.revoke_open_token(tok, revoked_ts=200.0)

    with pytest.raises(sealset.AccessDenied):
        store.read_sealed_gt("seal001", token=tok, ts=200.0)  # 失効時刻ちょうど=窓外

    assert store.access_log()[0]["session_id"] is None


def test_F002_2_read_at_issued_ts_allowed_half_open_window(tmp_path):
    """F-002-2（境界・下端閉）: ts == issued_ts は窓内（半開区間の下端は閉）。"""
    store = _store_with_one_seal(tmp_path)
    tok = store.issue_open_token("S1", issued_ts=100.0, precheck_passed=True)
    gt = store.read_sealed_gt("seal001", token=tok, ts=100.0)  # 発行時刻ちょうど=窓内
    assert gt["scenario_id"] == "seal001"
    assert store.access_log()[0]["session_id"] == "S1"


# ---------------------------------------------------------------------------
# 永続ログ（JSONL）を別インスタンス（プロセス再起動相当）から読み戻す
# ---------------------------------------------------------------------------

def test_F002_2_log_is_jsonl_persisted_to_root_dir(tmp_path):
    """F-002-2: 永続ログは root_dir/access_log.jsonl に JSONL（1行=1レコード）で書かれる。"""
    import json

    store = _store_with_one_seal(tmp_path)
    tok = store.issue_open_token("S1", issued_ts=100.0, precheck_passed=True)
    store.read_sealed_gt("seal001", token=tok, ts=150.0)
    # 拒否も1件混ぜる。
    with pytest.raises(sealset.AccessDenied):
        store.read_sealed_gt("seal001", token=None, ts=160.0)

    log_path = tmp_path / "access_log.jsonl"
    assert log_path.exists(), "永続ログ access_log.jsonl が root_dir に無い"
    lines = [ln for ln in log_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 2, "JSONL は1行=1レコード（成功1+拒否1=2行）であるべき"
    recs = [json.loads(ln) for ln in lines]
    assert recs[0]["session_id"] == "S1"
    assert recs[1]["session_id"] is None
    # SealAccessRecord 形式（session_id/ts/target）を満たす。
    for r in recs:
        assert set(r.keys()) >= {"session_id", "ts", "target"}


def test_F002_2_full_history_readback_from_new_instance(tmp_path):
    """F-002-2: 別インスタンス（プロセス再起動相当）から全アクセス履歴を読み戻せる。

    同一 root_dir を指す新しい SealStore で access_log() が同じ履歴を返す。
    """
    store = _store_with_one_seal(tmp_path)
    tok = store.issue_open_token("S1", issued_ts=100.0, precheck_passed=True)
    store.read_sealed_gt("seal001", token=tok, ts=150.0)
    with pytest.raises(sealset.AccessDenied):
        store.read_sealed_gt("seal001", token=None, ts=160.0)

    # プロセス再起動相当: 同一 root_dir を指す新インスタンス。
    store2 = sealset.SealStore(root_dir=tmp_path, production=False)
    log2 = store2.access_log()
    assert len(log2) == 2
    assert log2[0]["session_id"] == "S1"
    assert log2[1]["session_id"] is None


def test_F002_2_lifetime_session_count_readback_from_new_instance(tmp_path):
    """F-002-2: 別インスタンスから生涯開封セッション数を読み戻して検証できる。

    永続化されたセッション状態（session_state.json）を新インスタンスが読み戻し、
    lifetime_session_count() が開封済みセッション数を返す。
    """
    store = _store_with_one_seal(tmp_path, production=True)
    store.issue_open_token("S1", issued_ts=100.0, precheck_passed=True)
    assert store.lifetime_session_count() == 1

    # プロセス再起動相当。
    store2 = sealset.SealStore(root_dir=tmp_path, production=True)
    assert store2.lifetime_session_count() == 1


def test_F002_2_audit_seal_access_consumes_persisted_log(tmp_path):
    """F-002-2: 永続ログを guard.audit_seal_access に渡して窓・セッション整合を検証できる。

    GUARD_IF 運用規約2 の突合: F-002 の永続ログ ＋ guard の audit_seal_access。
    成功アクセスのみのログは、その session_id のトークンで監査合格する。
    """
    store = _store_with_one_seal(tmp_path)
    tok = store.issue_open_token("S1", issued_ts=100.0, precheck_passed=True)
    store.read_sealed_gt("seal001", token=tok, ts=150.0)
    store.read_sealed_gt("seal001", token=tok, ts=160.0)

    # 永続ログを読み戻し、guard の監査契約に通す。
    result = guard.audit_seal_access(store.access_log(), tok)
    assert result.passed is True
    assert result.guard_id == "F-014-2"


def test_F002_2_audit_seal_access_fails_when_denied_access_present(tmp_path):
    """F-002-2（陰性・突合）: 拒否アクセス（session_id=None）が混じると監査は不合格。

    拒否がログに残ること＋それを guard が不合格と判定することの両方を固定する。
    """
    store = _store_with_one_seal(tmp_path)
    tok = store.issue_open_token("S1", issued_ts=100.0, precheck_passed=True)
    store.read_sealed_gt("seal001", token=tok, ts=150.0)
    with pytest.raises(sealset.AccessDenied):
        store.read_sealed_gt("seal001", token=None, ts=160.0)  # 拒否=session_id None

    result = guard.audit_seal_access(store.access_log(), tok)
    assert result.passed is False
