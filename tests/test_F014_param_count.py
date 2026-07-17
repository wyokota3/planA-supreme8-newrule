"""F-014-1 / ガードレール①(過学習ガード・param数 ≪ data数)の検査。

specs/SPEC.md F-014-1:
  「学習モジュール総パラメータ数 < 練習用データ数 × k を検査(ガードレール①)。
   データ数＝練習用シナリオ件数。パラメータ数の定義・係数 k は U24 確定までブロック。」

decisions/0007-f014-guard-policies.md(決定1・fail-closed):
  「F-014-1 は fail-closed のパラメータ化で実装。検査式(param_count < data_count × k)は実装し、
   param_count / data_count / k は呼び出し側が供給。**k 未供給なら不合格**(安全側に倒す)。」

TEST_STRATEGY.md「F-014」:
  分岐網羅必須。「合格を出すべきでないケースで合格を出さない」陰性テスト必須。

------------------------------------------------------------------------
テストが定義する supreme.guard の公開 API(ガードレール①):

  guard.check_param_budget(param_count, data_count, k=None) -> GuardResult
    - param_count: 学習モジュール総パラメータ数(非負整数)。
    - data_count : 練習用シナリオ件数(非負整数)。
    - k          : 係数(float > 0)。**未供給(None)なら fail-closed で不合格**(ADR 0007)。
    - 検査式: 合格 ⇔ (k is not None) かつ param_count < data_count * k(「<」厳密・等号は不合格)。
    - param_count / data_count が負数・非整数(bool 除く int 以外)なら不正値として不合格。
      (fail-closed: 検査不能な入力で合格を出さない)

  GuardResult(レコード契約・全ガード共通):
    .passed   : bool          検査に合格したか。
    .guard_id : str           "F-014-1" 等の検査識別子。
    .checked  : bool          実際に検査を行ったか(④の未検査スキップと区別するため)。
    .reason   : str           判定理由(人間可読・空でない)。

  guard.GuardInputError:
    値の意味的不正(負数・非整数)で「不合格」を返す経路とは別に、API 誤用
    (型が int/None ですらない等)で送出してよい例外。本ファイルでは fail-closed の
    「不合格」優先のため原則使わないが、契約として定義する。
"""

import pytest

from supreme import guard


# ---------------------------------------------------------------------------
# 合格/不合格の境界(「<」厳密・等号は不合格)
# ---------------------------------------------------------------------------

def test_F014_1_pass_when_param_strictly_below_budget():
    """F-014-1: param_count < data_count × k(厳密に下回る)→ 合格。"""
    # data=200, k=0.1 → budget=20.0。param=19 < 20 → 合格。
    r = guard.check_param_budget(param_count=19, data_count=200, k=0.1)
    assert r.passed is True
    assert r.checked is True
    assert r.guard_id == "F-014-1"


def test_F014_1_fail_when_param_equals_budget_boundary():
    """F-014-1(境界): param_count == data_count × k(等号)→ 不合格(「<」厳密)。"""
    # data=200, k=0.1 → budget=20.0。param=20 は等号 → 不合格。
    r = guard.check_param_budget(param_count=20, data_count=200, k=0.1)
    assert r.passed is False
    assert r.checked is True


def test_F014_1_fail_when_param_just_over_budget():
    """F-014-1(境界): budget をわずかに超える(param=21, budget=20)→ 不合格。"""
    r = guard.check_param_budget(param_count=21, data_count=200, k=0.1)
    assert r.passed is False
    assert r.checked is True


def test_F014_1_pass_just_below_integer_budget():
    """F-014-1(境界): budget=20、param=19 は厳密に下回るので合格(等号の片側)。"""
    r = guard.check_param_budget(param_count=19, data_count=40, k=0.5)  # budget=20.0
    assert r.passed is True


# ---------------------------------------------------------------------------
# k 未供給(None)→ fail-closed で不合格(ADR 0007・決定1)
# ---------------------------------------------------------------------------

def test_F014_1_fail_closed_when_k_is_none():
    """F-014-1(fail-closed): k 未供給(None)→ 不合格(安全側)。ADR 0007 決定1。"""
    # param=0(どれだけ小さくても)・data 十分でも、k が無ければ検査不能 → 不合格。
    r = guard.check_param_budget(param_count=0, data_count=200, k=None)
    assert r.passed is False
    assert r.checked is True  # 検査は実施(した上で不合格)。④の「未検査」とは区別する。


def test_F014_1_fail_closed_when_k_omitted():
    """F-014-1(fail-closed): k 引数を省略(既定 None)→ 不合格。"""
    r = guard.check_param_budget(param_count=0, data_count=200)
    assert r.passed is False


# ---------------------------------------------------------------------------
# param_count / data_count の不正値(負数・非整数)→ fail-closed で不合格
# ---------------------------------------------------------------------------

def test_F014_1_fail_when_param_count_negative():
    """F-014-1(不正値): param_count が負数 → 不合格(検査不能で合格を出さない)。"""
    r = guard.check_param_budget(param_count=-1, data_count=200, k=0.1)
    assert r.passed is False


def test_F014_1_fail_when_data_count_negative():
    """F-014-1(不正値): data_count が負数 → 不合格。"""
    r = guard.check_param_budget(param_count=1, data_count=-200, k=0.1)
    assert r.passed is False


def test_F014_1_fail_when_param_count_non_integer():
    """F-014-1(不正値): param_count が非整数(float)→ 不合格。"""
    r = guard.check_param_budget(param_count=10.5, data_count=200, k=0.1)
    assert r.passed is False


def test_F014_1_fail_when_data_count_non_integer():
    """F-014-1(不正値): data_count が非整数(float)→ 不合格。"""
    r = guard.check_param_budget(param_count=1, data_count=200.0, k=0.1)
    assert r.passed is False


def test_F014_1_fail_when_param_count_is_bool():
    """F-014-1(不正値): param_count が bool(True/False)→ 非整数として不合格。

    bool は int の派生だが、計数として bool を受けるのは API 誤用。fail-closed で不合格。
    """
    r = guard.check_param_budget(param_count=True, data_count=200, k=0.1)
    assert r.passed is False


# ---------------------------------------------------------------------------
# k の不正値(0・負数)
# ---------------------------------------------------------------------------

def test_F014_1_fail_when_k_is_zero():
    """F-014-1(不正値): k=0 → budget=0、param<0 はあり得ず実質常に不合格。"""
    r = guard.check_param_budget(param_count=0, data_count=200, k=0.0)
    assert r.passed is False


def test_F014_1_fail_when_k_negative():
    """F-014-1(不正値): k が負数 → 不正な係数として不合格(fail-closed)。"""
    r = guard.check_param_budget(param_count=1, data_count=200, k=-0.1)
    assert r.passed is False


# ---------------------------------------------------------------------------
# 決定性(同一入力 → 同一結果)
# ---------------------------------------------------------------------------

def test_F014_1_deterministic_same_input_same_result():
    """F-014-1: 同一入力で結果が決定的(乱数・時刻に依存しない)。"""
    a = guard.check_param_budget(param_count=19, data_count=200, k=0.1)
    b = guard.check_param_budget(param_count=19, data_count=200, k=0.1)
    assert a.passed == b.passed
    assert a.checked == b.checked
    assert a.guard_id == b.guard_id


def test_F014_1_result_has_nonempty_reason():
    """F-014-1: GuardResult.reason は人間可読で空でない(報告契約)。"""
    r = guard.check_param_budget(param_count=20, data_count=200, k=0.1)
    assert isinstance(r.reason, str)
    assert r.reason.strip() != ""
