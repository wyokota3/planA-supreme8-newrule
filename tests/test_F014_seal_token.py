"""F-014-2 / ガードレール②(封印保全・開封トークン)の発行・失効・ログ検査。

specs/SPEC.md:
  F-014-2: 「封印アクセスが有効な**開封トークン**の期間(＝評価フェーズ)外で発生していない
            ことをセッションID付きログで検査。トークンは事前検査合格時に発行し、F-013 終了で失効。」
  F-002-2: 「封印へのアクセスは**開封セッション単位で生涯1回のみ**。…有効トークン外の読み出しは
            拒否・記録する(セッションID付きアクセスログで検証)。」
  F-013-3: 「本番封印の生涯開封セッション数が1。」

decisions/0002-tolerances-and-seal-access.md(決定2・開封トークン方式):
  - 開封セッション: 封印アクセスの計数単位。
  - 開封トークン: 「評価フェーズ」の機械的定義。guard がガードレール事前検査の**合格を条件に**
    トークン(セッションID＋発行時刻)を発行し、F-013 終了で失効。有効トークン保持時のみ読み出し可。
  - ガードレール②の検査対象 = 「有効トークン期間外のアクセスが0件」かつ「生涯開封セッション数が1」。

decisions/0007-f014-guard-policies.md(決定3):
  封印アクセスログ・開封トークンのレコード契約は test-writer が定義(テスト駆動)。

時刻は入力で受ける(datetime.now() 等に依存しない決定的設計)。

------------------------------------------------------------------------
テストが定義する supreme.guard の公開 API(ガードレール②):

  SealGuard(*, production):
    封印開封トークンの発行・失効・生涯セッション計数を持つ制御オブジェクト。
    production はキーワード明示必須(既定なし)。書き忘れによる fail-open 事故を
    型レベルで排除するため、`SealGuard()`(引数省略)は TypeError(ADR 0008 決定1)。
    本番封印を縛るときは production=True で生涯開封セッション数 1 を強制する。
    構成検証・非本番用途は production=False を明示する(明示しないと生成できない)。

    .issue_token(session_id, issued_ts, *, precheck_passed) -> OpenToken
        事前検査合格(precheck_passed=True)時のみトークンを発行。
        precheck_passed=False なら guard.PrecheckFailed を送出(発行しない)。
        production=True で2回目の発行要求は guard.SessionLimitExceeded を送出。
    .revoke_token(token, *, revoked_ts) -> None
        トークンを失効させる(F-013 終了相当)。失効後はそのトークンで読み出し不可。
        revoked_ts はキーワード明示必須(ADR 0008 決定4)。省略は窓の一点退縮で
        正当アクセスを遡及不合格にする運用罠のため不可(省略は TypeError)。
    .is_access_allowed(token, ts) -> bool
        与トークンが「発行済み・未失効・かつ ts が有効期間内」かを判定。
        失効後 / 未発行 / None トークンは False。
        有効期間は半開区間 [issued_ts, revoked_ts)(未失効なら [issued_ts, +inf))。
        ts == issued_ts は窓内、ts == revoked_ts は窓外(ADR 0008 決定3)。
    .lifetime_session_count() -> int
        これまでに発行した開封セッション数(production 検査の根拠)。

  OpenToken(レコード契約・開封トークン):
    .session_id : str          開封セッションID。
    .issued_ts  : float        発行時刻(入力で受ける・決定的)。
    .revoked_ts : float | None 失効時刻(未失効は None)。
    .active     : bool         未失効なら True。

  SealAccessRecord(レコード契約・封印アクセスログ1件):
    フィールド = (session_id, ts, target)
      session_id: str | None   有効トークン下のアクセスはトークンの session_id。
                               トークン無しの不正アクセスは None。
      ts        : float        アクセス時刻。
      target    : str          アクセス対象(scenario_id 等)。
    本ファイルでは dict {"session_id":..., "ts":..., "target":...} で表現し、
    guard 側がこの形を受理する契約とする。

  guard.audit_seal_access(log, token) -> GuardResult
      封印アクセスログ(SealAccessRecord の列)を、与えられた開封トークンの
      有効期間と突合する。
      合格 ⇔ 全アクセスが「token.session_id 一致」かつ「token の有効期間内」。
      有効期間は半開区間 [issued_ts, revoked_ts)(ADR 0008 決定3。
      ts == issued_ts は期間内、ts == revoked_ts は期間外=fail-closed 側)。
      期間外アクセス・別セッション・session_id None のアクセスが**1件でもあれば不合格**。

  例外: guard.PrecheckFailed / guard.SessionLimitExceeded
"""

import pytest

from supreme import guard


def _rec(session_id, ts, target="seal_sc1"):
    """SealAccessRecord(dict 表現)を1件作る。"""
    return {"session_id": session_id, "ts": float(ts), "target": target}


# ---------------------------------------------------------------------------
# トークン発行: 事前検査合格時のみ。発行物は session_id + 発行時刻を持つ。
# ---------------------------------------------------------------------------

def test_F014_2_issue_token_only_when_precheck_passed():
    """F-014-2: 事前検査合格(precheck_passed=True)時にトークンを発行できる。"""
    sg = guard.SealGuard(production=False)
    tok = sg.issue_token("S1", issued_ts=100.0, precheck_passed=True)
    assert tok.session_id == "S1"
    assert tok.issued_ts == 100.0
    assert tok.active is True


def test_F014_2_issue_token_rejected_when_precheck_failed():
    """F-014-2: 事前検査不合格(precheck_passed=False)ではトークンを発行しない。"""
    sg = guard.SealGuard(production=False)
    with pytest.raises(guard.PrecheckFailed):
        sg.issue_token("S1", issued_ts=100.0, precheck_passed=False)


def test_F014_2_token_carries_session_id_and_issued_ts():
    """F-014-2(レコード契約): 開封トークンは session_id + 発行時刻を保持する。"""
    sg = guard.SealGuard(production=False)
    tok = sg.issue_token("SESS-42", issued_ts=12345.0, precheck_passed=True)
    assert tok.session_id == "SESS-42"
    assert tok.issued_ts == 12345.0
    assert tok.revoked_ts is None


# ---------------------------------------------------------------------------
# 失効: 明示的な失効操作後はアクセス不可判定
# ---------------------------------------------------------------------------

def test_F014_2_access_allowed_within_active_token():
    """F-014-2: 有効トークン期間内(発行後・未失効)のアクセスは許可。"""
    sg = guard.SealGuard(production=False)
    tok = sg.issue_token("S1", issued_ts=100.0, precheck_passed=True)
    assert sg.is_access_allowed(tok, ts=150.0) is True


def test_F014_2_access_denied_after_revoke():
    """F-014-2(失効): 明示的な失効操作後はアクセス不可と判定される。

    revoked_ts は明示供給(ADR 0008 決定4)。ts=150 は失効時刻 200 より前だが、
    失効済みトークンは(窓内時刻であっても)アクセス不可。
    """
    sg = guard.SealGuard(production=False)
    tok = sg.issue_token("S1", issued_ts=100.0, precheck_passed=True)
    sg.revoke_token(tok, revoked_ts=200.0)
    assert sg.is_access_allowed(tok, ts=150.0) is False
    assert tok.active is False
    assert tok.revoked_ts is not None


def test_F014_2_access_denied_before_issue_time():
    """F-014-2(境界): 発行時刻より前のアクセスは有効期間外 → 不許可。"""
    sg = guard.SealGuard(production=False)
    tok = sg.issue_token("S1", issued_ts=100.0, precheck_passed=True)
    assert sg.is_access_allowed(tok, ts=99.0) is False


def test_F014_2_access_denied_for_none_token():
    """F-014-2(陰性): トークン無し(None)でのアクセス判定は常に不許可。"""
    sg = guard.SealGuard(production=False)
    assert sg.is_access_allowed(None, ts=150.0) is False


# ---------------------------------------------------------------------------
# ログ検査(陽性): 有効トークン期間内のアクセスのみ → 合格
# ---------------------------------------------------------------------------

def test_F014_2_audit_pass_all_access_within_token_window():
    """F-014-2(陽性): 全アクセスが有効トークン期間内・同一セッション → 合格。

    未失効トークンの窓 [issued_ts, +inf) で、発行後・同一セッションのアクセスが合格。
    (旧版にあった「発行→失効→未使用」の死にコード残骸は ADR 0008 決定1 で除去。)
    """
    sg = guard.SealGuard(production=False)
    tok = sg.issue_token("S1", issued_ts=100.0, precheck_passed=True)
    log = [
        _rec("S1", 120.0),
        _rec("S1", 130.0),
        _rec("S1", 199.0),
    ]
    r = guard.audit_seal_access(log, tok)
    assert r.passed is True
    assert r.guard_id == "F-014-2"


def test_F014_2_audit_pass_empty_log():
    """F-014-2(陽性): アクセスログが空(0件)→ 期間外アクセス0件で合格。"""
    sg = guard.SealGuard(production=False)
    tok = sg.issue_token("S1", issued_ts=100.0, precheck_passed=True)
    r = guard.audit_seal_access([], tok)
    assert r.passed is True


# ---------------------------------------------------------------------------
# ログ検査(陰性): 期間外アクセスが1件でもあれば不合格
# ---------------------------------------------------------------------------

def test_F014_2_audit_fail_access_before_issue():
    """F-014-2(陰性): 発行前のアクセスが1件 → 不合格。"""
    sg = guard.SealGuard(production=False)
    tok = sg.issue_token("S1", issued_ts=100.0, precheck_passed=True)
    log = [
        _rec("S1", 120.0),
        _rec("S1", 50.0),  # 発行前 → 期間外
    ]
    r = guard.audit_seal_access(log, tok)
    assert r.passed is False


def test_F014_2_audit_fail_access_after_revoke():
    """F-014-2(陰性・失効後アクセス構成): 失効後のアクセスが1件 → 不合格。"""
    sg = guard.SealGuard(production=False)
    tok = sg.issue_token("S1", issued_ts=100.0, precheck_passed=True)
    sg.revoke_token(tok, revoked_ts=200.0)
    log = [
        _rec("S1", 150.0),  # 期間内
        _rec("S1", 250.0),  # 失効後 → 期間外
    ]
    r = guard.audit_seal_access(log, tok)
    assert r.passed is False


def test_F014_2_audit_fail_access_without_token_session():
    """F-014-2(陰性・トークン無しアクセス構成): session_id=None のアクセス → 不合格。"""
    sg = guard.SealGuard(production=False)
    tok = sg.issue_token("S1", issued_ts=100.0, precheck_passed=True)
    log = [
        _rec("S1", 150.0),
        _rec(None, 160.0),  # トークン無しの不正アクセス
    ]
    r = guard.audit_seal_access(log, tok)
    assert r.passed is False


def test_F014_2_audit_fail_access_from_other_session():
    """F-014-2(陰性・多重アクセス構成): 別セッションIDのアクセスが混入 → 不合格。"""
    sg = guard.SealGuard(production=False)
    tok = sg.issue_token("S1", issued_ts=100.0, precheck_passed=True)
    log = [
        _rec("S1", 150.0),
        _rec("S2", 160.0),  # 別の開封セッション = 多重開封
    ]
    r = guard.audit_seal_access(log, tok)
    assert r.passed is False


def test_F014_2_audit_fail_single_outside_access_among_many():
    """F-014-2(陰性): 多数の正当アクセスの中に1件でも期間外があれば不合格。"""
    sg = guard.SealGuard(production=False)
    tok = sg.issue_token("S1", issued_ts=100.0, precheck_passed=True)
    sg.revoke_token(tok, revoked_ts=300.0)
    log = [_rec("S1", float(t)) for t in range(110, 290, 10)]  # 全て期間内
    log.append(_rec("S1", 301.0))  # 1件だけ失効後
    r = guard.audit_seal_access(log, tok)
    assert r.passed is False


# ---------------------------------------------------------------------------
# 生涯開封セッション数 = 1(本番封印。2セッション目の発行要求は拒否)
# ---------------------------------------------------------------------------

def test_F014_2_production_lifetime_session_count_is_one():
    """F-013-3 / F-014-2: 本番封印で1回発行後の生涯開封セッション数は1。"""
    sg = guard.SealGuard(production=True)
    sg.issue_token("S1", issued_ts=100.0, precheck_passed=True)
    assert sg.lifetime_session_count() == 1


def test_F014_2_production_second_issue_rejected():
    """F-013-3 / F-014-2(陰性): 本番封印で2セッション目の発行要求は拒否。"""
    sg = guard.SealGuard(production=True)
    sg.issue_token("S1", issued_ts=100.0, precheck_passed=True)
    with pytest.raises(guard.SessionLimitExceeded):
        sg.issue_token("S2", issued_ts=200.0, precheck_passed=True)


def test_F014_2_production_second_issue_rejected_even_after_revoke():
    """F-013-3(陰性): 失効しても本番封印は生涯1回。失効後の2セッション目も拒否。

    封印は「生涯」1回開封。失効=評価終了であって再開封枠の復活ではない。
    """
    sg = guard.SealGuard(production=True)
    tok = sg.issue_token("S1", issued_ts=100.0, precheck_passed=True)
    sg.revoke_token(tok, revoked_ts=200.0)
    with pytest.raises(guard.SessionLimitExceeded):
        sg.issue_token("S2", issued_ts=300.0, precheck_passed=True)
    assert sg.lifetime_session_count() == 1


def test_F014_2_session_count_increments_only_on_successful_issue():
    """F-014-2: 事前検査不合格で発行が失敗したら生涯セッション数は増えない。"""
    sg = guard.SealGuard(production=True)
    with pytest.raises(guard.PrecheckFailed):
        sg.issue_token("S1", issued_ts=100.0, precheck_passed=False)
    assert sg.lifetime_session_count() == 0
    # 失敗後でも正当な発行は1回可能(枠を消費していない)。
    sg.issue_token("S1", issued_ts=110.0, precheck_passed=True)
    assert sg.lifetime_session_count() == 1


# ---------------------------------------------------------------------------
# production の明示必須化(ADR 0008 決定1)
#   既定 fail-open を構造的に不可能にする。引数省略は TypeError。
#   既定値の向きを固定するテストが無かったこと自体が監査の最重点欠陥を許した。
# ---------------------------------------------------------------------------

def test_F014_2_sealguard_requires_explicit_production():
    """F-014-2(ADR 0008 決定1・陰性): production を省略した SealGuard() は TypeError。

    既定値(fail-open=False)を廃止し、production をキーワード明示必須にする。
    「書き忘れによる silent fail-open」を型レベルで排除する(監査の最重点欠陥)。
    """
    with pytest.raises(TypeError):
        guard.SealGuard()


def test_F014_2_sealguard_production_true_constructs():
    """F-014-2(ADR 0008 決定1): production=True は明示すれば生成でき、本番封印を縛る。

    向きを固定する陽性側: production=True を内包すると生涯1回が強制される。
    """
    sg = guard.SealGuard(production=True)
    sg.issue_token("S1", issued_ts=100.0, precheck_passed=True)
    with pytest.raises(guard.SessionLimitExceeded):
        sg.issue_token("S2", issued_ts=200.0, precheck_passed=True)


def test_F014_2_sealguard_production_false_constructs():
    """F-014-2(ADR 0008 決定1): production=False は明示すれば生成でき、生涯枠を強制しない。

    向きを固定する対照側: production=False では2回目の発行が拒否されない
    (構成検証・非本番用途。fail-open の選択を呼び出し側の自覚的判断にする)。
    """
    sg = guard.SealGuard(production=False)
    tok1 = sg.issue_token("S1", issued_ts=100.0, precheck_passed=True)
    sg.revoke_token(tok1, revoked_ts=200.0)
    tok2 = sg.issue_token("S2", issued_ts=300.0, precheck_passed=True)
    assert tok2.active is True
    assert sg.lifetime_session_count() == 2


# ---------------------------------------------------------------------------
# トークン窓の境界(ADR 0008 決定3・半開区間 [issued_ts, revoked_ts))
#   ts == issued_ts は窓内、ts == revoked_ts は窓外(fail-closed 側)。
#   両端の境界を is_access_allowed と audit_seal_access の両方で固定する。
# ---------------------------------------------------------------------------

def test_F014_2_window_lower_bound_inclusive_is_access_allowed():
    """F-014-2(境界・下端閉): ts == issued_ts は窓内 → is_access_allowed=True。"""
    sg = guard.SealGuard(production=False)
    tok = sg.issue_token("S1", issued_ts=100.0, precheck_passed=True)
    assert sg.is_access_allowed(tok, ts=100.0) is True


def test_F014_2_window_upper_bound_exclusive_is_access_allowed():
    """F-014-2(境界・上端開): ts == revoked_ts は窓外 → is_access_allowed=False。

    半開区間 [issued_ts, revoked_ts)。失効時刻ちょうどは期間外=fail-closed 側
    (ADR 0008 決定3)。失効ちょうどのアクセスを「期間内」と見なさない。
    """
    sg = guard.SealGuard(production=False)
    tok = sg.issue_token("S1", issued_ts=100.0, precheck_passed=True)
    sg.revoke_token(tok, revoked_ts=200.0)
    assert sg.is_access_allowed(tok, ts=200.0) is False


def test_F014_2_audit_lower_bound_inclusive_passes():
    """F-014-2(境界・下端閉/監査): ts == issued_ts のアクセスのみ → 監査合格。"""
    sg = guard.SealGuard(production=False)
    tok = sg.issue_token("S1", issued_ts=100.0, precheck_passed=True)
    log = [_rec("S1", 100.0)]  # 発行時刻ちょうど = 窓内
    r = guard.audit_seal_access(log, tok)
    assert r.passed is True


def test_F014_2_audit_upper_bound_exclusive_fails():
    """F-014-2(境界・上端開/監査): ts == revoked_ts のアクセスは窓外 → 監査不合格。

    半開区間の上端は窓外。失効時刻ちょうどのアクセスを合格にしない(ADR 0008 決定3)。
    """
    sg = guard.SealGuard(production=False)
    tok = sg.issue_token("S1", issued_ts=100.0, precheck_passed=True)
    sg.revoke_token(tok, revoked_ts=200.0)
    log = [_rec("S1", 150.0), _rec("S1", 200.0)]  # 200.0 は失効時刻ちょうど = 窓外
    r = guard.audit_seal_access(log, tok)
    assert r.passed is False


def test_F014_2_audit_just_below_upper_bound_passes():
    """F-014-2(境界・上端直下/監査): ts < revoked_ts(直下)は窓内 → 監査合格。

    上端の境界が「ちょうど除外・直下は許可」であることを上端開テストと対で固定する。
    """
    sg = guard.SealGuard(production=False)
    tok = sg.issue_token("S1", issued_ts=100.0, precheck_passed=True)
    sg.revoke_token(tok, revoked_ts=200.0)
    log = [_rec("S1", 100.0), _rec("S1", 199.999)]  # 下端ちょうど ＋ 上端直下
    r = guard.audit_seal_access(log, tok)
    assert r.passed is True


# ---------------------------------------------------------------------------
# revoke_token の revoked_ts 必須化(ADR 0008 決定4)
#   省略時の窓一点退縮(正当アクセスの遡及不合格)という運用罠を構造的に除去。
#   省略は TypeError。
# ---------------------------------------------------------------------------

def test_F014_2_revoke_token_requires_explicit_revoked_ts():
    """F-014-2(ADR 0008 決定4・陰性): revoked_ts を省略した revoke_token は TypeError。

    省略時に窓が issued_ts へ一点退縮し、セッション中の正当アクセス(ts > issued_ts)が
    遡って全て「期間外」となる偽陽性(運用罠)を、引数必須化で構造的に排除する。
    """
    sg = guard.SealGuard(production=False)
    tok = sg.issue_token("S1", issued_ts=100.0, precheck_passed=True)
    with pytest.raises(TypeError):
        sg.revoke_token(tok)
