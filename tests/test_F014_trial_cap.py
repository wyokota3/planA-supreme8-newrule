"""F-014-4 / ガードレール④(候補・撤退基準・探索試行回数上限)の検査。

specs/SPEC.md:
  F-014-4: 「(候補)探索試行回数の上限超過を検査(ガードレール④・撤退基準・U18)。」
  F-012-3: 「探索試行回数が定義された上限内(U18 確定後)。」

decisions/0007-f014-guard-policies.md(決定2・機構のみ):
  「F-014-4 は機構のみ実装。上限は呼び出し側供給。**未供給時は「未検査(U18 未確定)」を
   結果に明示し合否に含めない**(候補ガードのため探索を止めない)。供給時は超過で不合格。
   ①(必須ガード)と④(候補ガード)で未供給時の挙動を意図的に変えている点に注意。」

→ ①(check_param_budget)は k 未供給で「不合格」、④は上限未供給で「未検査(checked=False)」。
  この挙動差を両方向からテストする。

------------------------------------------------------------------------
テストが定義する supreme.guard の公開 API(ガードレール④):

  guard.check_trial_cap(trial_count, cap=None) -> GuardResult
    - trial_count: これまでの探索試行回数(非負整数)。
    - cap        : 上限(int)。未供給(None)なら「未検査」。
    - 上限供給時: 合格 ⇔ trial_count <= cap(上限ちょうどは合格・「超過」で不合格)。
                  trial_count > cap → 不合格。
    - 上限未供給(None): checked=False の GuardResult を返す。
      .passed は合否に**影響させない**(候補ガード)。reason に「未検査(U18 未確定)」を明示。
    - trial_count が不正値(負数・非整数)で cap 供給時は不合格(検査不能)。
    - **cap 自体が不正値(負数・非整数・bool)なら checked=True かつ不合格**
      (ADR 0008 決定7・①の k 検証と同形)。cap=None の「未検査(checked=False)」とは
      明確に区別する: 不正な上限が供給された場合は「検査して不合格」であり、
      候補ガードのスルーには倒さない(不正値で合格を出さない fail-closed)。

  GuardResult: test_F014_param_count.py のレコード契約と同一(.passed/.guard_id/.checked/.reason)。
"""

import pytest

from supreme import guard


# ---------------------------------------------------------------------------
# 上限供給時: trial_count <= cap → 合格、超過 → 不合格
# ---------------------------------------------------------------------------

def test_F014_4_pass_when_trials_below_cap():
    """F-014-4: trial_count < cap(上限内)→ 合格・checked=True。"""
    r = guard.check_trial_cap(trial_count=5, cap=10)
    assert r.passed is True
    assert r.checked is True
    assert r.guard_id == "F-014-4"


def test_F014_4_pass_when_trials_equals_cap_boundary():
    """F-014-4(境界): trial_count == cap(上限ちょうど)→ 合格(「超過」ではない)。"""
    r = guard.check_trial_cap(trial_count=10, cap=10)
    assert r.passed is True
    assert r.checked is True


def test_F014_4_fail_when_trials_exceed_cap():
    """F-014-4(境界): trial_count > cap(1超過)→ 不合格。"""
    r = guard.check_trial_cap(trial_count=11, cap=10)
    assert r.passed is False
    assert r.checked is True


# ---------------------------------------------------------------------------
# 上限未供給 → 「未検査(U18 未確定)」が結果に明示され、合否に影響しない
# (①の fail-closed との挙動差を両方向からテスト)
# ---------------------------------------------------------------------------

def test_F014_4_unchecked_when_cap_is_none():
    """F-014-4(機構のみ): 上限未供給(None)→ checked=False(未検査)。ADR 0007 決定2。"""
    r = guard.check_trial_cap(trial_count=999999, cap=None)
    assert r.checked is False  # 検査していない(候補ガード)。


def test_F014_4_unchecked_when_cap_omitted():
    """F-014-4(機構のみ): cap 引数を省略(既定 None)→ checked=False。"""
    r = guard.check_trial_cap(trial_count=999999)
    assert r.checked is False


def test_F014_4_unchecked_reason_mentions_u18():
    """F-014-4(機構のみ): 未検査時の reason に「未検査/U18」が明示される(報告契約)。"""
    r = guard.check_trial_cap(trial_count=5, cap=None)
    assert r.checked is False
    assert "U18" in r.reason or "未検査" in r.reason


def test_F014_4_unchecked_does_not_block_aggregate():
    """F-014-4(①との挙動差): 未検査(checked=False)は集約合否に影響しない。

    ①(check_param_budget)は k 未供給で passed=False(ブロックする)が、
    ④は cap 未供給で「未検査」となり、集約判定(combine_guards)で合否に算入されない。
    両方向(①は止める/④は止めない)をここと統合テストで確認する。
    """
    # 比較対照: ①は k=None で不合格・checked=True(検査した上で安全側に不合格)。
    g1 = guard.check_param_budget(param_count=0, data_count=200, k=None)
    assert g1.checked is True and g1.passed is False
    # ④は cap=None で未検査・checked=False。
    g4 = guard.check_trial_cap(trial_count=999999, cap=None)
    assert g4.checked is False


# ---------------------------------------------------------------------------
# 不正値(上限供給時)
# ---------------------------------------------------------------------------

def test_F014_4_fail_when_trial_count_negative_with_cap():
    """F-014-4(不正値): cap 供給時に trial_count が負数 → 不合格。"""
    r = guard.check_trial_cap(trial_count=-1, cap=10)
    assert r.passed is False
    assert r.checked is True


def test_F014_4_fail_when_trial_count_non_integer_with_cap():
    """F-014-4(不正値): cap 供給時に trial_count が非整数 → 不合格。"""
    r = guard.check_trial_cap(trial_count=5.5, cap=10)
    assert r.passed is False


# ---------------------------------------------------------------------------
# cap 自体の不正値(ADR 0008 決定7・①の k 検証と同形)
#   負数・非整数・bool の cap は checked=True かつ不合格。cap=None の未検査と区別。
# ---------------------------------------------------------------------------

def test_F014_4_fail_when_cap_negative():
    """F-014-4(ADR 0008 決定7・cap 不正値): cap が負数 → checked=True かつ不合格。

    cap=-1 のような不正な上限は検査不能。①(k<0 で不合格)と同形に fail-closed。
    cap=None の「未検査スルー」とは異なり、不正値供給は「検査して不合格」。

    強度注: trial_count=0 を使う。cap=-1 を「正当な上限」として素通り比較すると
    0 <= -1 は False で偶然不合格になるが、それは「上限超過」扱いであり不正値検出ではない。
    本テストは「不正値として」不合格になること(reason が無効/不正を述べること)を要求し、
    cap=-1 を有効上限として比較に使う実装(現状)では reason 不一致で red になる。
    """
    r = guard.check_trial_cap(trial_count=0, cap=-1)
    assert r.checked is True
    assert r.passed is False
    # 「不正な上限」を検出した旨が reason に現れる(単なる「上限超過」ではない)。
    assert ("不正" in r.reason) or ("無効" in r.reason) or ("invalid" in r.reason.lower())


def test_F014_4_fail_when_cap_non_integer():
    """F-014-4(ADR 0008 決定7・cap 不正値): cap が非整数(float)→ checked=True かつ不合格。

    cap=10.5 で trial_count=5 は、非整数 cap を有効上限として比較すると 5 <= 10.5 で
    「合格」になってしまう(現状の fail-open)。非整数 cap を不正値として不合格にする。
    """
    r = guard.check_trial_cap(trial_count=5, cap=10.5)
    assert r.checked is True
    assert r.passed is False


def test_F014_4_fail_when_cap_is_bool():
    """F-014-4(ADR 0008 決定7・cap 不正値): cap が bool(True/False)→ checked=True かつ不合格。

    bool は int の派生だが、上限として bool を受けるのは API 誤用(①の param=bool と同形)。
    True を 1 として比較に使わず、不正値として不合格にする。

    強度注: trial_count=0, cap=True を使う。cap=True を 1 として比較する実装(現状)では
    0 <= True(1) が True となり「合格」を返してしまう。bool を不正値として弾けば不合格。
    これにより「bool を 1/0 として黙って受理する」fail-open が red で検出される。
    """
    r = guard.check_trial_cap(trial_count=0, cap=True)
    assert r.checked is True
    assert r.passed is False


# ---------------------------------------------------------------------------
# 決定性
# ---------------------------------------------------------------------------

def test_F014_4_deterministic_same_input_same_result():
    """F-014-4: 同一入力で結果が決定的。"""
    a = guard.check_trial_cap(trial_count=11, cap=10)
    b = guard.check_trial_cap(trial_count=11, cap=10)
    assert a.passed == b.passed and a.checked == b.checked
