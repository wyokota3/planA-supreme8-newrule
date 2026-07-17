"""F-014-2: SealGuard の公開復元API（initial_session_count）と入力検証。

specs/SPEC.md:
  F-014-2 / F-013-3: 「本番封印の生涯開封セッション数が1。」
  F-002-2: 「封印へのアクセスは開封セッション単位で生涯1回のみ。」
specs/GUARD_IF.md:
  - SealGuard(*, production) は production キーワード明示必須（既定なし・省略 TypeError）。
  - lifetime_session_count() は発行成功時のみ加算。
  - 運用規約2: プロセス跨ぎの「生涯1回」最終保証は F-002 のアクセス制御＋永続化と突合。
  - check_trial_cap: cap 不正値（負数・非整数・bool）は checked=True の不合格。
    → 本ファイルの initial_session_count 検証も同じ「bool も明示拒否」流儀を採る。

decisions/0010-f002-audit-fixes.md（本ファイルが固定する契約の正）:
  決定3「guard に公開復元APIを追加（今回修正）」:
    SealGuard(*, production, initial_session_count=0)。既定値付きキーワードのため
    既存契約は非破壊。復元値の型検証（非負整数）込み。sealset の private 属性依存
    （_lifetime_session_count への代入）を解消し GUARD_IF に追記。
  追記「復元値の例外型」:
    initial_session_count の不正値（負数・非整数・bool・文字列等）は GuardInputError
    （guard 既存の入力エラー例外に統一）。

----------------------------------------------------------------------------
本ファイルが固定する supreme.guard.SealGuard の契約（ADR 0010 決定3+追記）:

  SealGuard(*, production: bool, initial_session_count: int = 0)
    - initial_session_count は既定値付き keyword-only。省略時は従来挙動（非破壊）。
    - production=True かつ initial_session_count=1 のとき、生涯1回制限が既に消費済みと
      みなされ、issue_token(..., precheck_passed=True) は SessionLimitExceeded。
    - production=True かつ initial_session_count=0 は既定と同一（発行成功）。
    - lifetime_session_count() は initial 値を反映し、発行成功で加算される。
    - 不正値（負数・非整数・bool・文字列）は guard.GuardInputError。
      bool は int のサブクラスだが明示拒否（check_trial_cap の cap 検証と同流儀）。
    - 入力検証は dummy（production=False）でも走る。
    - dummy では initial 値があっても複数発行可（制限は production のみ・現行どおり）。
"""

import pytest

from supreme import guard


# ---------------------------------------------------------------------------
# 復元値が production の生涯1回制限に効く（核心）
# ---------------------------------------------------------------------------

def test_F014_2_restore_initial_count_one_blocks_issue_in_production():
    """F-014-2（ADR 0010 決定3・核心）: production で initial=1 → 発行は SessionLimitExceeded。

    プロセス再起動相当の「生涯1回をすでに1回消費した」状態を復元値で表現する。
    復元後の issue_token（precheck 合格）は枠超過で拒否される。
    """
    sg = guard.SealGuard(production=True, initial_session_count=1)
    with pytest.raises(guard.SessionLimitExceeded):
        sg.issue_token("S1", issued_ts=100.0, precheck_passed=True)


def test_F014_2_restore_initial_count_zero_allows_issue_in_production():
    """F-014-2（ADR 0010 決定3・対照）: production で initial=0 は既定と同一（発行成功）。

    既定値付きキーワードのため非破壊であることの対照。initial=0 は復元なしの従来挙動。
    """
    sg = guard.SealGuard(production=True, initial_session_count=0)
    tok = sg.issue_token("S1", issued_ts=100.0, precheck_passed=True)
    assert tok.active is True
    assert sg.lifetime_session_count() == 1


def test_F014_2_restore_omitted_initial_count_is_legacy_behavior():
    """F-014-2（ADR 0010 決定3・非破壊）: initial 省略時は従来挙動（発行成功）。

    既存の SealGuard(production=True) 契約（F-014 既存テスト）が壊れないことを固定する。
    """
    sg = guard.SealGuard(production=True)
    sg.issue_token("S1", issued_ts=100.0, precheck_passed=True)
    assert sg.lifetime_session_count() == 1


# ---------------------------------------------------------------------------
# lifetime_session_count() が initial 値を反映し、発行成功で加算される
# ---------------------------------------------------------------------------

def test_F014_2_lifetime_count_reflects_initial_value():
    """F-014-2（ADR 0010 決定3）: lifetime_session_count() は initial 値を反映する。

    発行前から復元値を返す（永続セッション状態の読み戻しを公開APIで表現）。
    """
    sg = guard.SealGuard(production=True, initial_session_count=1)
    assert sg.lifetime_session_count() == 1


def test_F014_2_lifetime_count_increments_from_initial_in_dummy():
    """F-014-2（ADR 0010 決定3）: dummy で initial 値からさらに発行成功で加算される。

    dummy（production=False）は複数発行可。initial=2 から2回発行すると 2→3→4 と加算。
    """
    sg = guard.SealGuard(production=False, initial_session_count=2)
    assert sg.lifetime_session_count() == 2
    sg.issue_token("S1", issued_ts=100.0, precheck_passed=True)
    assert sg.lifetime_session_count() == 3
    sg.issue_token("S2", issued_ts=200.0, precheck_passed=True)
    assert sg.lifetime_session_count() == 4


# ---------------------------------------------------------------------------
# dummy では initial 値があっても複数発行可（制限は production のみ・現行どおり）
# ---------------------------------------------------------------------------

def test_F014_2_dummy_with_initial_count_still_allows_multiple_issue():
    """F-014-2（ADR 0010 決定3）: dummy では initial 値があっても複数発行できる。

    生涯1回制限は production のみ（現行どおり）。dummy は復元値があっても制限されない。
    """
    sg = guard.SealGuard(production=False, initial_session_count=1)
    tok1 = sg.issue_token("S1", issued_ts=100.0, precheck_passed=True)
    tok2 = sg.issue_token("S2", issued_ts=200.0, precheck_passed=True)
    assert tok1.active is True
    assert tok2.active is True


# ---------------------------------------------------------------------------
# 不正値は GuardInputError（負数・非整数・bool・文字列）。bool も明示拒否。
# ---------------------------------------------------------------------------

def test_F014_2_restore_negative_initial_count_rejected():
    """F-014-2（ADR 0010 追記・陰性）: 負数の initial_session_count は GuardInputError。"""
    with pytest.raises(guard.GuardInputError):
        guard.SealGuard(production=True, initial_session_count=-1)


def test_F014_2_restore_float_initial_count_rejected():
    """F-014-2（ADR 0010 追記・陰性）: 非整数（float 1.5）は GuardInputError。"""
    with pytest.raises(guard.GuardInputError):
        guard.SealGuard(production=True, initial_session_count=1.5)


def test_F014_2_restore_str_initial_count_rejected():
    """F-014-2（ADR 0010 追記・陰性）: 文字列 "1" は GuardInputError（暗黙変換しない）。"""
    with pytest.raises(guard.GuardInputError):
        guard.SealGuard(production=True, initial_session_count="1")


def test_F014_2_restore_bool_true_initial_count_rejected():
    """F-014-2（ADR 0010 追記・陰性）: bool True は GuardInputError（明示拒否）。

    bool は int のサブクラス（True==1）だが、check_trial_cap の cap 検証と同じ流儀で
    明示的に拒否する（型の取り違えを silent に受理しない）。
    """
    with pytest.raises(guard.GuardInputError):
        guard.SealGuard(production=True, initial_session_count=True)


def test_F014_2_restore_bool_false_initial_count_rejected():
    """F-014-2（ADR 0010 追記・陰性）: bool False も GuardInputError（明示拒否）。

    False==0 で「既定と同義」に見えるが、bool は型として拒否する（cap 検証と同流儀）。
    """
    with pytest.raises(guard.GuardInputError):
        guard.SealGuard(production=True, initial_session_count=False)


def test_F014_2_restore_input_validation_runs_in_dummy_too():
    """F-014-2（ADR 0010 追記・陰性）: 入力検証は dummy でも走る。

    production=False でも不正な initial_session_count（負数）は GuardInputError。
    検証は production フラグに依存しない（fail-closed をモード非依存で担保）。
    """
    with pytest.raises(guard.GuardInputError):
        guard.SealGuard(production=False, initial_session_count=-1)


# ---------------------------------------------------------------------------
# 既存契約の非破壊: production はキーワード明示必須のまま
# ---------------------------------------------------------------------------

def test_F014_2_restore_api_preserves_production_required():
    """F-014-2（ADR 0010 決定3・非破壊）: production 省略は依然 TypeError。

    initial_session_count に既定を付けても、production の明示必須（ADR 0008 決定1）は
    維持される（省略時 silent fail-open を構造的に排除する向きを崩さない）。
    """
    with pytest.raises(TypeError):
        guard.SealGuard(initial_session_count=0)
