"""F-001-1 / 分割自動割当: assign_split の決定性・パラメータ・適格フィルタ・自己検証。

specs/GT_SCHEMA.md「分割割当(自動・決定的)」/ SPEC.md F-001 正常系:
- インターフェース assign_split(params)。params=封印件数 or 比率 ＋ 適格フィルタ。
- アルゴリズム: 適格 root 親系統IDを sha256 で安定ソートし、先頭から封印に割当。
- 乱数・時刻に依存せず、同一入力＋同一パラメータ → 同一割当（決定的）。
- 割当後は親系統が非交差であることを自己検証（seal∩train=∅、F-001-1）。
- 割当は版として記録し、再割当しても履歴を消さない。

テストが前提とする supreme.datagov の公開 API:
- DataGovernor().register(record)
- DataGovernor().assign_split(seal_count=None, seal_ratio=None, eligible=None) -> SplitAssignment
    seal_count: 封印に回す root 親系統の件数（整数）。seal_ratio と排他。
    seal_ratio: 封印比率（0..1 の float）。seal_count と排他。
    eligible: 適格フィルタ。root レコードを受け bool を返す callable（例: lambda r: r["meta"]["gt_origin"]=="human"）。
              省略時は全 root が適格。
    戻り値 SplitAssignment:
        .seal: tuple[str]（封印に割り当てた root 親系統ID。割当順）
        .train: tuple[str]（練習に割り当てた root 親系統ID）
        .version: 割当を識別する版（再割当で履歴が消えないことの根拠）。
- DataGovernor().lineage_set(split): 割当反映後の root 親系統ID集合。
- DataGovernor().assignment_history() -> list[SplitAssignment]（版の履歴。再割当しても消えない）。
- 例外: datagov.SplitError（seal_count と seal_ratio の同時指定/件数超過などの不正パラメータ）。

決定論の参照実装（テスト側で期待値を独立計算する）:
  適格 root を sha256(scenario_id) の16進文字列で昇順安定ソートし、先頭 seal_count 件を封印。
"""

import hashlib

import pytest

import fixtures_gt as fx
from supreme import datagov


def _sha_sorted(root_ids):
    """テスト側の独立参照: sha256(scenario_id) 16進で安定ソート（昇順）。"""
    return sorted(root_ids, key=lambda s: hashlib.sha256(s.encode("utf-8")).hexdigest())


def _gov_with_human_roots():
    """封印適格(human) root を6件登録した governor を返す。"""
    gov = datagov.DataGovernor()
    ids = ["C", "D", "E", "F", "G", "H"]
    for sid in ids:
        gov.register(fx.make_record(sid, generation=0, gt_origin="human"))
    return gov, ids


def test_F001_assign_split_deterministic_same_input_same_assignment():
    """分割割当: 同一入力＋同一パラメータ → 同一割当（決定的）。"""
    gov1, _ = _gov_with_human_roots()
    gov2, _ = _gov_with_human_roots()

    a1 = gov1.assign_split(seal_count=2)
    a2 = gov2.assign_split(seal_count=2)

    assert tuple(a1.seal) == tuple(a2.seal)
    assert tuple(a1.train) == tuple(a2.train)


def test_F001_assign_split_uses_sha256_stable_sort_order():
    """分割割当: 封印は sha256 安定ソート順の先頭から割り当てられる。"""
    gov, ids = _gov_with_human_roots()
    a = gov.assign_split(seal_count=3)

    expected_order = _sha_sorted(ids)
    assert tuple(a.seal) == tuple(expected_order[:3])
    assert set(a.train) == set(expected_order[3:])


def test_F001_assign_split_count_parameter():
    """分割割当: seal_count で封印件数を指定できる。"""
    gov, ids = _gov_with_human_roots()
    a = gov.assign_split(seal_count=2)
    assert len(a.seal) == 2
    assert len(a.train) == len(ids) - 2


def test_F001_assign_split_ratio_parameter():
    """分割割当: seal_ratio で封印比率を指定できる（6件×0.5=3件）。"""
    gov, ids = _gov_with_human_roots()
    a = gov.assign_split(seal_ratio=0.5)
    assert len(a.seal) == 3
    assert len(a.train) == 3


def test_F001_assign_split_eligibility_filter_restricts_seal_pool():
    """分割割当: 適格フィルタ(human のみ封印適格)で非適格 root は封印に入らない。"""
    gov = datagov.DataGovernor()
    # human 2件・ai 2件を root 登録。
    for sid in ("C", "D"):
        gov.register(fx.make_record(sid, generation=0, gt_origin="human"))
    for sid in ("X", "Y"):
        gov.register(fx.make_record(sid, generation=0, gt_origin="ai_generated"))

    a = gov.assign_split(
        seal_count=2,
        eligible=lambda r: r["meta"]["gt_origin"] == "human",
    )
    # 封印は human 由来の C/D のみ。ai 由来は封印に入らない。
    assert set(a.seal) == {"C", "D"}
    assert "X" not in a.seal and "Y" not in a.seal


def test_F001_assign_split_result_is_disjoint_self_check():
    """F-001-1 / 分割割当: 割当後に seal と train の親系統が非交差（自己検証）。"""
    gov, _ = _gov_with_human_roots()
    a = gov.assign_split(seal_count=3)
    assert set(a.seal) & set(a.train) == set()
    # governor 側の集合演算でも非交差。
    assert gov.lineage_set("seal") & gov.lineage_set("train") == set()


def test_F001_assign_split_folds_descendants_to_root():
    """分割割当: 子孫は root 単位で同じ split に入る（孫経由リークを構造的に防ぐ）。"""
    gov = datagov.DataGovernor()
    fam_A = fx.lineage_family_A()
    fam_B = fx.lineage_family_B()
    for r in (fam_A["A"], fam_A["A_c1"], fam_A["A_gc1"], fam_A["A_c2"],
              fam_B["B"], fam_B["B_c1"]):
        gov.register(r)

    gov.assign_split(seal_count=1, eligible=lambda r: r["meta"]["gt_origin"] == "human")

    # 封印に入った root の全子孫は seal、もう一方の root の全子孫は train。
    seal_lineage = gov.lineage_set("seal")
    train_lineage = gov.lineage_set("train")
    assert seal_lineage & train_lineage == set()
    assert seal_lineage | train_lineage == {"A", "B"}


def test_F001_assign_split_records_version_history():
    """分割割当: 割当は版として記録され、再割当しても履歴が消えない。"""
    gov, _ = _gov_with_human_roots()
    first = gov.assign_split(seal_count=2)
    second = gov.assign_split(seal_count=3)

    history = gov.assignment_history()
    assert len(history) >= 2
    versions = [h.version for h in history]
    assert first.version in versions
    assert second.version in versions
    assert first.version != second.version


def test_F001_assign_split_rejects_conflicting_params():
    """分割割当(異常系): seal_count と seal_ratio の同時指定は SplitError。"""
    gov, _ = _gov_with_human_roots()
    with pytest.raises(datagov.SplitError):
        gov.assign_split(seal_count=2, seal_ratio=0.5)


def test_F001_assign_split_rejects_count_over_eligible_pool():
    """分割割当(異常系): 適格 root 件数を超える seal_count は SplitError。"""
    gov = datagov.DataGovernor()
    for sid in ("C", "D"):
        gov.register(fx.make_record(sid, generation=0, gt_origin="human"))
    with pytest.raises(datagov.SplitError):
        gov.assign_split(
            seal_count=5,  # 適格は2件しかない
            eligible=lambda r: r["meta"]["gt_origin"] == "human",
        )
