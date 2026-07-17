"""F-001-3: 任意データから root 親系統への遡及が推移閉包で一意に解決できる。

specs/GT_SCHEMA.md「リネージ規則」:
- 元シナリオ(人手含む)は parent_lineage_id=自身、parents=[]、generation=0。
- 派生は parents に直接親、parent_lineage_id は親の parent_lineage_id を継承。
- 任意データ → root の解決は推移閉包で一意（F-001-3）。

テストが前提とする supreme.datagov の公開 API:
- DataGovernor().register(record)
- DataGovernor().resolve_root(scenario_id) -> str（root の scenario_id を返す。一意）。
- DataGovernor().generation_of(scenario_id) -> int（root は 0）。
- 例外: datagov.LineageError（解決不能・循環など）。
"""

import pytest

import fixtures_gt as fx
from supreme import datagov


def _gov(records):
    gov = datagov.DataGovernor()
    for r in records:
        gov.register(r)
    return gov


def test_F001_3_root_resolves_to_self_generation_zero():
    """F-001-3: root（元シナリオ）は自身が root で generation=0。"""
    fam_A = fx.lineage_family_A()
    gov = _gov([fam_A["A"]])
    assert gov.resolve_root("A") == "A"
    assert gov.generation_of("A") == 0


def test_F001_3_child_resolves_to_root():
    """F-001-3: 子(gen1)から root への遡及が一意に解決する。"""
    fam_A = fx.lineage_family_A()
    gov = _gov([fam_A["A"], fam_A["A_c1"]])
    assert gov.resolve_root("A_c1") == "A"
    assert gov.generation_of("A_c1") == 1


def test_F001_3_grandchild_resolves_to_root():
    """F-001-3: 孫(gen2)から root への遡及が推移閉包で一意に解決する。"""
    fam_A = fx.lineage_family_A()
    gov = _gov([fam_A["A"], fam_A["A_c1"], fam_A["A_gc1"]])
    assert gov.resolve_root("A_gc1") == "A"
    assert gov.generation_of("A_gc1") == 2


def test_F001_3_great_grandchild_resolves_to_root():
    """F-001-3: ひ孫(gen3)から root への遡及が推移閉包で一意に解決する。"""
    A = fx.make_record("A", generation=0, gt_origin="human")
    c1 = fx.make_record("A_c1", parent_lineage_id="A", parents=["A"], generation=1)
    gc1 = fx.make_record("A_gc1", parent_lineage_id="A", parents=["A_c1"], generation=2)
    ggc1 = fx.make_record("A_ggc1", parent_lineage_id="A", parents=["A_gc1"], generation=3)
    gov = _gov([A, c1, gc1, ggc1])
    assert gov.resolve_root("A_ggc1") == "A"
    assert gov.generation_of("A_ggc1") == 3


def test_F001_3_siblings_share_same_root():
    """F-001-3: 同一 root を持つ別系統の枝（子と孫）が同じ root に畳まれる。"""
    fam_A = fx.lineage_family_A()
    gov = _gov([fam_A["A"], fam_A["A_c1"], fam_A["A_gc1"], fam_A["A_c2"]])
    assert gov.resolve_root("A_gc1") == "A"
    assert gov.resolve_root("A_c2") == "A"
    assert gov.resolve_root("A_gc1") == gov.resolve_root("A_c2")


def test_F001_3_distinct_roots_do_not_merge():
    """F-001-3: 異なる root を持つ系統は別 root に解決される（一意性の対照）。"""
    fam_A = fx.lineage_family_A()
    fam_B = fx.lineage_family_B()
    gov = _gov([fam_A["A"], fam_A["A_c1"], fam_B["B"], fam_B["B_c1"]])
    assert gov.resolve_root("A_c1") == "A"
    assert gov.resolve_root("B_c1") == "B"
    assert gov.resolve_root("A_c1") != gov.resolve_root("B_c1")
