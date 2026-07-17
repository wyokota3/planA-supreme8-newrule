"""F-003-2: 増強GTは生成器と別系統で確定/検算される（機構のみ）。

specs/SPEC.md F-003 / F-003-2:
  「GTは生成と別ルートで確定。」
  「増強分GTは生成器と異なる手段で確定または検算されている（手段定義はU17）。」
specs/SPEC.md F-003 異常系:
  「GT が別系統で確定できない派生は破棄またはフラグ。」
decisions/0011-f003-augment-policies.md 決定1:
  - F-003-2（機構）: 増強GTの gt_origin が生成器と別系統であることを記録・契約化し、
    別系統で確定/検算できない派生は破棄またはフラグする（SPEC 異常系）。
    具体的な U17 ワークフロー（誰が・どの基準で確定するか）は実データ投入時まで保留。
  - 注: U17 は未確定のため、テストは「機構が gt_origin の別系統性を要求し、満たさない
    派生を通さない」ことの検証に留める（具体的な検算手段の正しさはテストしない）。

----------------------------------------------------------------------------
このファイルが固定する supreme.augment の前提 API（テスト駆動・report に明記）:

  Augmentor.augment(parent_id, *, count, gt_origin="cross_checked",
                    on_unverified="drop") -> list[AugmentResult]
    - 生成器の「系統」は Augmentor が知っている識別子 generator_lineage（下記）。
    - gt_origin（増強GTの確定系統）が generator_lineage と同一系統なら、その派生は
      「別系統で確定できていない」とみなす。
    - on_unverified:
        "drop": 別系統で確定できない派生は登録せず破棄する（戻り値に含めない）。
        "flag": 登録はするが unverified_gt=True のフラグを立てる（破棄しない）。
      既定は "drop"（SPEC 異常系「破棄またはフラグ」の安全側）。
    - AugmentResult 追加属性:
        .gt_origin     : str   増強GTの確定系統（記録）。
        .unverified_gt : bool   別系統で確定できていない場合 True（flag モード時のみ True 化）。

  Augmentor.generator_lineage -> str
    注入された生成器の系統識別子。Augmentor 構築時に generator_lineage で受領する
    （省略時の既定値も Augmentor が定める）。gt_origin がこの値と一致する派生は
    「生成器と同系統」＝検算不成立とみなす。

  Augmentor(*, governor, seal_store, generator, generator_lineage="fake_generator")
"""

import pytest

import fixtures_gt as fx
from supreme import datagov
from supreme import sealset
from supreme import augment


def _fake_generator(parent_record, *, index):
    """親から決定的に派生を1件作る偽生成器（F-003-2 用・最小）。"""
    parent_id = parent_record["meta"]["scenario_id"]
    derived_id = f"{parent_id}__aug{index}"
    return fx.make_record(
        derived_id,
        parent_lineage_id=derived_id,
        parents=[],
        generation=0,
        gt_origin="fake_generator",  # 生成器系統（Augmentor が確定で上書きしうる）
    )


def _governor_with_parent(*records):
    gov = datagov.DataGovernor()
    for r in records:
        gov.register(r)
    return gov


def _augmentor(tmp_path, governor, *, generator_lineage="fake_generator"):
    store = sealset.SealStore(root_dir=tmp_path, production=False)
    return augment.Augmentor(
        governor=governor,
        seal_store=store,
        generator=_fake_generator,
        generator_lineage=generator_lineage,
    )


# ---------------------------------------------------------------------------
# 陽性: 生成器と別系統の gt_origin を持つ派生は登録成功し、別系統性が記録される
# ---------------------------------------------------------------------------

def test_F003_2_cross_checked_gt_origin_registers(tmp_path):
    """F-003-2（陽性）: 生成器と別系統(cross_checked)の gt_origin を持つ派生は登録成功。

    生成器系統 "fake_generator" と異なる "cross_checked" で確定されているため通る。
    """
    A = fx.make_record("A", generation=0, gt_origin="human")
    gov = _governor_with_parent(A)
    aug = _augmentor(tmp_path, gov)

    results = aug.augment("A", count=2, gt_origin="cross_checked")

    assert len(results) == 2
    assert all(r.gt_origin == "cross_checked" for r in results)
    assert all(r.unverified_gt is False for r in results), (
        "別系統で確定済みの派生は unverified フラグが立ってはならない"
    )


def test_F003_2_registered_record_records_separate_gt_origin(tmp_path):
    """F-003-2: 登録された派生の meta.gt_origin に別系統の確定系統が記録される。

    gt_origin の値で「生成器由来でない」ことを表現する（来歴の記録）。
    """
    A = fx.make_record("A", generation=0, gt_origin="human")
    gov = _governor_with_parent(A)
    aug = _augmentor(tmp_path, gov)

    [r] = aug.augment("A", count=1, gt_origin="cross_checked")

    stored = [
        rec for rec in gov.payout("train")
        if rec["meta"]["scenario_id"] == r.scenario_id
    ]
    assert len(stored) == 1
    assert stored[0]["meta"]["gt_origin"] == "cross_checked", (
        "登録レコードの gt_origin が別系統の確定系統で記録されていない"
    )
    assert stored[0]["meta"]["gt_origin"] != aug.generator_lineage, (
        "gt_origin が生成器系統と同一になっている（別系統性が破れている）"
    )


def test_F003_2_gt_origin_differs_from_generator_lineage(tmp_path):
    """F-003-2: 登録成功した派生の gt_origin は generator_lineage と必ず異なる。

    「別系統で確定」の契約化。generator_lineage との非同一を機構で要求する。
    """
    A = fx.make_record("A", generation=0, gt_origin="human")
    gov = _governor_with_parent(A)
    aug = _augmentor(tmp_path, gov, generator_lineage="fake_generator")

    results = aug.augment("A", count=3, gt_origin="human_reviewed")

    assert aug.generator_lineage == "fake_generator"
    for r in results:
        assert r.gt_origin != aug.generator_lineage


# ---------------------------------------------------------------------------
# 陰性: 生成器と同系統の gt_origin（別系統で確定できない）派生は破棄される
# ---------------------------------------------------------------------------

def test_F003_2_same_lineage_gt_origin_dropped(tmp_path):
    """F-003-2（陰性・破棄）: gt_origin が生成器と同系統の派生は既定で破棄される。

    SPEC 異常系「GT が別系統で確定できない派生は破棄またはフラグ」。
    gt_origin == generator_lineage は検算不成立 → 既定 on_unverified="drop" で破棄。
    破棄された派生は戻り値に含まれず、governor の train にも登録されない。
    """
    A = fx.make_record("A", generation=0, gt_origin="human")
    gov = _governor_with_parent(A)
    aug = _augmentor(tmp_path, gov, generator_lineage="fake_generator")

    # gt_origin を生成器系統そのものに指定（= 別系統で確定できていない）。
    results = aug.augment("A", count=2, gt_origin="fake_generator")

    assert results == [], "別系統で確定できない派生は破棄され戻り値に含まれてはならない"
    # train に何も登録されていない（親 A のみ）。
    train_ids = {rec["meta"]["scenario_id"] for rec in gov.payout("train")}
    assert train_ids == set(), "破棄された派生が train に登録されている"


def test_F003_2_same_lineage_gt_origin_flag_mode_marks_unverified(tmp_path):
    """F-003-2（陰性・フラグ）: on_unverified="flag" なら登録するが unverified_gt=True。

    SPEC 異常系の「フラグ」側。破棄でなくフラグを選んだ場合、検算不成立が明示される。
    """
    A = fx.make_record("A", generation=0, gt_origin="human")
    gov = _governor_with_parent(A)
    aug = _augmentor(tmp_path, gov, generator_lineage="fake_generator")

    results = aug.augment(
        "A", count=1, gt_origin="fake_generator", on_unverified="flag",
    )

    assert len(results) == 1, "flag モードでは登録される（破棄しない）"
    assert results[0].unverified_gt is True, (
        "別系統で確定できない派生に unverified_gt フラグが立っていない"
    )


def test_F003_2_mixed_default_drop_keeps_only_cross_checked(tmp_path):
    """F-003-2: 別系統確定の親と同系統の親を混在増強したとき、既定 drop は別系統のみ残す。

    別々の親に対し、別系統 gt_origin と生成器同系統 gt_origin で増強し、
    破棄が同系統側にのみ効く（陽性と陰性の分離）ことを確認する。
    """
    A = fx.make_record("A", generation=0, gt_origin="human")
    B = fx.make_record("B", generation=0, gt_origin="human")
    gov = _governor_with_parent(A, B)
    aug = _augmentor(tmp_path, gov, generator_lineage="fake_generator")

    ok = aug.augment("A", count=1, gt_origin="cross_checked")   # 別系統 → 登録
    dropped = aug.augment("B", count=1, gt_origin="fake_generator")  # 同系統 → 破棄

    assert len(ok) == 1
    assert dropped == []
    train_ids = {rec["meta"]["scenario_id"] for rec in gov.payout("train")}
    assert ok[0].scenario_id in train_ids
    # B 由来の派生は1件も train に入らない。
    assert not any(sid.startswith("B__aug") for sid in train_ids)
