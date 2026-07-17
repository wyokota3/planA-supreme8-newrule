"""F-014-3 / ガードレール③(選定純度・組み合わせ選定は練習用のみ)の検査。

specs/SPEC.md:
  F-014-3: 「組み合わせ選定が練習用のみで行われたことを検査(ガードレール③)。」
  F-012-1: 「探索中に封印セットへのアクセスが0回(ログで検証)。」
  F-012-2: 「選定は練習用スコアのみに基づく。」

TEST_STRATEGY.md「方法論検証層 / 選定純度」:
  「組み合わせ選定が練習用スコアのみ(F-012-2 / F-014-3)」。陰性テスト必須。

decisions/0007-f014-guard-policies.md(決定3):
  選定来歴のレコード契約は test-writer が定義(テスト駆動)。

------------------------------------------------------------------------
テストが定義する supreme.guard の公開 API(ガードレール③):

  guard.check_selection_purity(provenance, seal_access_log=None) -> GuardResult
    - provenance: 選定来歴(SelectionProvenanceRecord の列)。組み合わせ選定に使った
      各評価が「どの split のデータで行われたか」を表す。
      合格 ⇔ 全評価レコードの split が "train"。1件でも "seal" 由来が混入 → 不合格。
    - seal_access_log: 省略可。封印アクセスログ(F-014-2 と同形の dict 列)。
      与えられた場合、選定期間中の seal アクセスが**0件**であることも合格条件に加える
      (target が封印を指すアクセスが1件でもあれば不合格)。
      **未供給(None)時は封印アクセス検査を実施しない**。この場合の合格 reason は
      「封印アクセス検査は未実施」相当を明示し、検査していない事実を隠さない
      (虚偽の「0件」報告を排除・ADR 0008 決定5)。来歴の split・ログがいずれも
      呼び出し側の自己申告に依存する限界(TEST_STRATEGY 穴3/穴8 と同種)。

  SelectionProvenanceRecord(レコード契約・選定来歴1件):
    フィールド = (eval_id, split, scenario_id, score)
      eval_id    : str    選定中の1評価の識別子。
      split      : str    その評価に使ったデータの split("train" / "seal")。
      scenario_id: str    評価対象シナリオ。
      score      : float  練習用スコア(選定はこの値のみに基づくべき)。
    本ファイルでは dict {"eval_id":..., "split":..., "scenario_id":..., "score":...}
    で表現し、guard 側がこの形を受理する契約とする。

  GuardResult: test_F014_param_count.py のレコード契約と同一(.passed/.guard_id/.checked/.reason)。
"""

import pytest

from supreme import guard


def _prov(eval_id, split, scenario_id, score=0.5):
    """SelectionProvenanceRecord(dict 表現)を1件作る。"""
    return {
        "eval_id": eval_id,
        "split": split,
        "scenario_id": scenario_id,
        "score": float(score),
    }


def _seal_access(session_id, ts, target):
    """封印アクセスログ(F-014-2 と同形)を1件作る。"""
    return {"session_id": session_id, "ts": float(ts), "target": target}


# ---------------------------------------------------------------------------
# 陽性: 全評価レコードが split=train → 合格
# ---------------------------------------------------------------------------

def test_F014_3_pass_when_all_provenance_is_train():
    """F-014-3(陽性): 全評価レコードが split=train → 合格。"""
    prov = [
        _prov("e1", "train", "A_c1"),
        _prov("e2", "train", "A_c2"),
        _prov("e3", "train", "B_c1"),
    ]
    r = guard.check_selection_purity(prov)
    assert r.passed is True
    assert r.guard_id == "F-014-3"
    assert r.checked is True


def test_F014_3_pass_empty_provenance():
    """F-014-3(境界): 来歴が空(評価0件)→ seal 混入0件で合格。"""
    r = guard.check_selection_purity([])
    assert r.passed is True


# ---------------------------------------------------------------------------
# 陰性: 1件でも seal 由来の評価が混入 → 不合格
# ---------------------------------------------------------------------------

def test_F014_3_fail_when_one_seal_evaluation_mixed_in():
    """F-014-3(陰性): 多数の train の中に1件 seal 由来が混入 → 不合格。"""
    prov = [
        _prov("e1", "train", "A_c1"),
        _prov("e2", "train", "A_c2"),
        _prov("e3", "seal", "C"),  # 封印データで選定した = 汚染
        _prov("e4", "train", "B_c1"),
    ]
    r = guard.check_selection_purity(prov)
    assert r.passed is False


def test_F014_3_fail_when_all_seal():
    """F-014-3(陰性): 全評価が seal 由来 → 不合格。"""
    prov = [
        _prov("e1", "seal", "C"),
        _prov("e2", "seal", "D"),
    ]
    r = guard.check_selection_purity(prov)
    assert r.passed is False


def test_F014_3_fail_when_split_is_unassigned():
    """F-014-3(陰性): split が train でない値(unassigned 等)→ 不合格。

    「練習用のみ」を厳密に解釈し、train と確証できない split は合格にしない(fail-closed)。
    """
    prov = [
        _prov("e1", "train", "A_c1"),
        _prov("e2", "unassigned", "Z"),
    ]
    r = guard.check_selection_purity(prov)
    assert r.passed is False


# ---------------------------------------------------------------------------
# 封印アクセスログとの突合(選定期間中の seal アクセスが0件)
# ---------------------------------------------------------------------------

def test_F014_3_pass_when_seal_access_log_empty():
    """F-014-3(陽性): train 来歴 ＋ 封印アクセス0件 → 合格。"""
    prov = [_prov("e1", "train", "A_c1")]
    r = guard.check_selection_purity(prov, seal_access_log=[])
    assert r.passed is True


def test_F014_3_fail_when_seal_accessed_during_selection():
    """F-014-3(陰性): 来歴は全 train でも、選定期間中に封印アクセスが1件 → 不合格。

    F-012-1(探索中の封印アクセス0回)との突合。来歴ラベルが綺麗でも、実アクセスで
    封印に触れていれば汚染とみなす。
    """
    prov = [_prov("e1", "train", "A_c1")]
    seal_log = [_seal_access(None, 120.0, target="seal_C")]  # 探索中の封印アクセス
    r = guard.check_selection_purity(prov, seal_access_log=seal_log)
    assert r.passed is False


# ---------------------------------------------------------------------------
# 決定性・報告契約
# ---------------------------------------------------------------------------

def test_F014_3_deterministic_same_input_same_result():
    """F-014-3: 同一入力で結果が決定的。"""
    prov = [_prov("e1", "train", "A_c1"), _prov("e2", "seal", "C")]
    a = guard.check_selection_purity(prov)
    b = guard.check_selection_purity(prov)
    assert a.passed == b.passed and a.guard_id == b.guard_id


def test_F014_3_result_has_nonempty_reason():
    """F-014-3: 不合格時に reason が空でない(どの評価が seal だったか報告できる根拠)。"""
    prov = [_prov("e1", "seal", "C")]
    r = guard.check_selection_purity(prov)
    assert isinstance(r.reason, str) and r.reason.strip() != ""


# ---------------------------------------------------------------------------
# reason の真実化(ADR 0008 決定5)
#   seal_access_log=None(未供給)時、検査していない事実を reason に明記する。
#   「封印アクセス0件」のような虚偽の検査済み主張を排除する。
# ---------------------------------------------------------------------------

def test_F014_3_reason_states_seal_check_not_performed_when_log_absent():
    """F-014-3(ADR 0008 決定5): seal_access_log 未供給時の合格 reason は
    「封印アクセス検査は未実施」相当を明示し、虚偽の「0件」を含まない。

    旧 reason は log 未供給でも「封印アクセス0件」と検査済みを偽装していた(監査指摘)。
    検査していない事実が報告に現れることで誤解(自己申告依存の限界)を防ぐ。
    """
    prov = [_prov("e1", "train", "A_c1")]
    r = guard.check_selection_purity(prov)  # seal_access_log は未供給(None)
    assert r.passed is True
    # 未実施である旨が reason に現れる(「未実施」相当の文言)。
    assert "未実施" in r.reason
    # 「0件」のような検査済みを装う虚偽が無い。
    assert "0件" not in r.reason


def test_F014_3_reason_truthful_when_log_supplied_empty():
    """F-014-3(対照・ADR 0008 決定5): seal_access_log=[](供給・0件)時は、
    実際に0件を検査したので「未実施」とは言わない。

    未供給(未実施)と供給かつ空(検査して0件)を reason で区別できることを固定する。
    """
    prov = [_prov("e1", "train", "A_c1")]
    r = guard.check_selection_purity(prov, seal_access_log=[])
    assert r.passed is True
    assert "未実施" not in r.reason
