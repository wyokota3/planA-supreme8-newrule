"""F-001-1: 封印/練習の親系統が非交差であることの検証。

このファイルは受け入れ条件 F-001-1（および F-001-1 の必須境界=孫経由リーク）を扱う。
- seal の親系統集合 と train の親系統リネージ集合 が交わらないこと（集合演算で assert）。
- 交わる払い出し要求は拒否（エラー化）。
- 必須境界: 親A→子→孫を封印に、親Aの別の子を練習に置く「孫経由リーク」を検出できること。

2026-06-12 監査対処（ADR 0004）:
- set_split は削除された。split 状態・違反状態は meta.split をレコードに直接指定して
  register するデータ駆動方式で構成する（改版 GT_SCHEMA「register は meta.split を
  そのまま受理（既定 unassigned）。payout は経路に関わらず防御的に非交差検証」）。
- set_split が存在しないこと（オーバー実装の再混入防止）を回帰テストで担保する。

テストが前提とする supreme.datagov の公開 API（実装はこれに従う）:
- DataGovernor(): レコード登録・分割・払い出しを管理する。
    .register(record): canonical GT record を登録（meta.split をそのまま受理）。
    .lineage_set(split): その split に属するレコードの root 親系統ID集合(set[str])を返す。
    .payout(split): その split のレコード列を返す。非交差違反時は LineageCrossError。
- exceptions: LineageCrossError（payout 時に seal∩train≠∅ で送出）。
"""

import pytest

import fixtures_gt as fx
from supreme import datagov


def _governor_with(records):
    gov = datagov.DataGovernor()
    for r in records:
        gov.register(r)
    return gov


def test_F001_1_seal_train_lineage_sets_disjoint():
    """F-001-1: seal の root 親系統集合と train の root 親系統集合が交わらない。

    split は meta.split を直接指定して register する（set_split は使わない）。
    """
    fam_A = fx.lineage_family_A()
    fam_B = fx.lineage_family_B()
    humans = fx.human_roots()

    # A 系統と C を封印、B 系統と D を練習に分ける（root 単位で分離）。
    seal_ids = {"A", "A_c1", "A_gc1", "A_c2", "C"}
    train_ids = {"B", "B_c1", "D"}

    records = {
        "A": fam_A["A"], "A_c1": fam_A["A_c1"],
        "A_gc1": fam_A["A_gc1"], "A_c2": fam_A["A_c2"],
        "B": fam_B["B"], "B_c1": fam_B["B_c1"],
        "C": humans["C"], "D": humans["D"],
    }
    to_register = []
    for sid, rec in records.items():
        split = "seal" if sid in seal_ids else "train"
        to_register.append(fx.with_split(rec, split))

    gov = _governor_with(to_register)

    seal_lineage = gov.lineage_set("seal")
    train_lineage = gov.lineage_set("train")

    assert seal_lineage & train_lineage == set(), (
        "seal と train の親系統集合が交差している"
    )
    # root 単位で畳まれていること（A 系統は root "A" として1つにまとまる）。
    assert "A" in seal_lineage
    assert "B" in train_lineage


def test_F001_1_payout_rejects_when_lineage_crosses():
    """F-001-1: seal と train が同一 root 親系統を共有する払い出しは拒否される。

    同一 root "A" の子を train と seal に分けてしまう違反構成を
    meta.split を直接指定して register することで作る（set_split は使わない）。
    payout の防御的非交差検証が経路に関わらず働くことを担保する。
    """
    fam_A = fx.lineage_family_A()
    gov = _governor_with([
        fx.with_split(fam_A["A"], "seal"),
        fx.with_split(fam_A["A_c1"], "seal"),
        fx.with_split(fam_A["A_c2"], "train"),
    ])

    with pytest.raises(datagov.LineageCrossError):
        gov.payout("seal")


def test_F001_1_grandchild_leak_detected():
    """F-001-1（必須境界・孫経由リーク）: A→子→孫を封印、A の別の子を練習にした構成を検出。

    親A→子(A_c1)→孫(A_gc1) を封印に、親A の別の子(A_c2) を練習に置く。
    孫 A_gc1 は推移閉包で root "A" に畳まれるため、seal と train が
    同一 root "A" を共有する＝リーク。払い出しで拒否されること。

    split は meta.split を直接指定して register する（set_split は使わない）。
    """
    fam_A = fx.lineage_family_A()
    gov = _governor_with([
        fx.with_split(fam_A["A"], "unassigned"),
        fx.with_split(fam_A["A_c1"], "seal"),
        fx.with_split(fam_A["A_gc1"], "seal"),
        fx.with_split(fam_A["A_c2"], "train"),
    ])

    # 集合演算でも交差していること（孫が root に畳まれているのが前提）。
    assert gov.lineage_set("seal") & gov.lineage_set("train") == {"A"}, (
        "孫経由リークが root 'A' の共有として検出されていない"
    )

    with pytest.raises(datagov.LineageCrossError):
        gov.payout("train")


def test_F001_1_clean_split_pays_out_without_error():
    """F-001-1: root 単位で正しく分けた構成は払い出しが成功する（陰性対照）。

    リーク検査が「常に拒否」ではなく、非交差なら通すことを担保する。
    split は meta.split を直接指定して register する（set_split は使わない）。
    """
    fam_A = fx.lineage_family_A()
    humans = fx.human_roots()
    gov = _governor_with([
        fx.with_split(fam_A["A"], "train"),
        fx.with_split(fam_A["A_c1"], "train"),
        fx.with_split(fam_A["A_gc1"], "train"),
        fx.with_split(fam_A["A_c2"], "train"),
        fx.with_split(humans["C"], "seal"),
        fx.with_split(humans["D"], "seal"),
    ])

    train_records = gov.payout("train")
    seal_records = gov.payout("seal")

    train_ids = {r["meta"]["scenario_id"] for r in train_records}
    seal_ids = {r["meta"]["scenario_id"] for r in seal_records}
    assert train_ids == {"A", "A_c1", "A_gc1", "A_c2"}
    assert seal_ids == {"C", "D"}


def test_F001_1_set_split_is_removed():
    """F-001-1（回帰・オーバー実装の再混入防止）: set_split は存在しない。

    ADR 0004 決定4: SPEC に無い手動割当 API set_split を削除し、正規の割当経路は
    assign_split のみとする。違反状態の構成は meta.split のデータ駆動方式に置き換えた。
    DataGovernor から set_split が再混入していないことを assert する。
    """
    gov = datagov.DataGovernor()
    assert not hasattr(gov, "set_split"), (
        "set_split は ADR 0004 で削除済み。再混入はオーバー実装"
    )
    assert not hasattr(datagov, "set_split"), (
        "モジュール直下にも set_split は存在してはならない"
    )
