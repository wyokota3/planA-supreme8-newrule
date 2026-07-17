"""F-003-1: 増強(派生)データに親系統タグが付与され、推移閉包で親へ遡及可能。

specs/SPEC.md F-003 / F-003-1:
  「親から派生を生成し、親系統タグを付与して F-001 に登録。」
  「全増強データに親系統タグが付与され、推移閉包で親へ遡及可能。」
specs/SPEC.md F-003 境界条件 / F-001 境界条件:
  「増強で孫・ひ孫が出た場合、リネージは推移的に親系統へ畳む（孫経由リーク防止）。」
decisions/0011-f003-augment-policies.md 決定1:
  - F-003-1（機構）: 増強(派生)レコードに親系統タグを付与し、F-001(DataGovernor)へ
    train として登録する。推移閉包で親へ遡及可能（datagov の resolve_root を再利用・
    独自再発明しない）。
  - 生成器(AI生成器)は注入可能な抽象(callable)とし、テストは偽生成器で機構を検証する
    （本物の生成品質・多様性はテスト対象外）。

----------------------------------------------------------------------------
このファイルが定義する supreme.augment の前提 API（テスト駆動・report に明記）:

  Augmentor(*, governor, seal_store, generator):
    増強(練習用データ増強)の単一窓口。
    governor  : datagov.DataGovernor  train 権威。派生は train として登録される。
    seal_store: sealset.SealStore     封印 root 集合の供給元（F-003 着手条件の突合用。
                本ファイルでは非交差な構成のみ扱う。突合の陰性は別ファイル）。
    generator : callable              注入可能な抽象。偽生成器を注入して機構を検証する。
                呼び出し署名: generator(parent_record, *, index) -> derived_record
                  parent_record: governor に登録済みの親レコード（canonical GT record）。
                  index        : 同一親からの派生連番(0始まり)。決定的な scenario_id 採番用。
                戻り値 derived_record は canonical GT record だが、親系統タグ
                  (parent_lineage_id / parents / generation) は Augmentor が
                  正しい値に確定する（生成器が詐称しても Augmentor が上書き・検算する）。

  Augmentor.augment(parent_id, *, count, gt_origin="cross_checked") -> list[AugmentResult]
    親 parent_id（governor 登録済み）から count 件の派生を生成し、親系統タグを付与して
    governor へ train として登録する。
    gt_origin は増強GTの確定系統（生成器と別系統であること。詳細は F-003-2 ファイル）。
    戻り値は登録に成功した派生の AugmentResult のリスト:
      .scenario_id      : str   登録した派生の scenario_id
      .parent_lineage_id: str   付与された親系統タグ（= 親の root）
      .root             : str   governor.resolve_root による再解決 root（= 親の root）
      .generation       : int   親の generation + 1（孫・ひ孫まで連鎖）
      .split            : str   train（増強は練習用）
    例外: augment.ParentNotRegisteredError（parent_id が governor 未登録）。
"""

import pytest

import fixtures_gt as fx
from supreme import datagov
from supreme import sealset
from supreme import augment


# ---------------------------------------------------------------------------
# 偽生成器（注入可能な抽象の fake）: 親から決定的に派生を作る。
#
# 親系統タグを「あえて詐称」して返すことで、Augmentor が生成器を信頼せず
# 自分で正しい親系統タグを確定・検算することをテストで固定する。
# ---------------------------------------------------------------------------

def _fake_generator(parent_record, *, index):
    """親レコードから決定的に派生レコードを1件作る偽生成器。

    親系統タグ(parent_lineage_id/parents/generation)はわざと不正な値を入れて返す。
    Augmentor が生成器の親系統タグを信頼せず正しい値に確定することを検証するため。
    """
    parent_id = parent_record["meta"]["scenario_id"]
    derived_id = f"{parent_id}__aug{index}"
    rec = fx.make_record(
        derived_id,
        # 生成器は親系統を詐称する（root を自称＝generation 0 を主張）。
        parent_lineage_id=derived_id,
        parents=[],
        generation=0,
        gt_origin="fake_generator_origin",  # Augmentor が gt_origin を確定で上書きする想定
    )
    return rec


def _governor_with_parent(*records):
    gov = datagov.DataGovernor()
    for r in records:
        gov.register(r)
    return gov


def _augmentor(tmp_path, governor, *, generator=_fake_generator):
    """非交差な（封印が空の）SealStore を持つ Augmentor を作る。

    本ファイルは F-003-1（親遡及）が主眼。封印突合は別ファイルで陰性も含めて扱う。
    """
    store = sealset.SealStore(root_dir=tmp_path, production=False)
    return augment.Augmentor(governor=governor, seal_store=store, generator=generator)


# ---------------------------------------------------------------------------
# F-003-1: 派生が親系統タグを得て、推移閉包で親 root へ遡及できる
# ---------------------------------------------------------------------------

def test_F003_1_augmented_record_gets_parent_lineage_tag(tmp_path):
    """F-003-1: 親 A から生成した派生に親系統タグ(parent_lineage_id=A)が付与される。

    ADR 0011 決定1（機構）。生成器が root を詐称しても Augmentor が親系統タグを確定する。
    """
    A = fx.make_record("A", generation=0, gt_origin="human")
    gov = _governor_with_parent(A)
    aug = _augmentor(tmp_path, gov)

    results = aug.augment("A", count=1)

    assert len(results) == 1
    assert results[0].parent_lineage_id == "A", (
        "派生の親系統タグが親 root 'A' に確定されていない"
    )
    assert results[0].generation == 1, "親 gen0 の子は generation=1 のはず"


def test_F003_1_augmented_lineage_traces_to_parent(tmp_path):
    """F-003-1: 登録後、governor.resolve_root で派生 root が親の root に畳まれる。

    datagov の推移閉包(resolve_root)を再利用して親へ遡及できること（独自再発明しない）。
    """
    A = fx.make_record("A", generation=0, gt_origin="human")
    gov = _governor_with_parent(A)
    aug = _augmentor(tmp_path, gov)

    [r] = aug.augment("A", count=1)

    # Augmentor が報告する root と governor が解決する root が一致し、ともに親 root。
    assert r.root == "A"
    assert gov.resolve_root(r.scenario_id) == "A", (
        "増強レコードの root が親の root 'A' に畳まれていない"
    )


def test_F003_1_augment_registers_as_train(tmp_path):
    """F-003-1: 増強(派生)は train として登録される（練習用データ増強）。

    ADR 0011 決定2: train 追加の単一窓口は augment。登録後 governor の train split に入る。
    """
    A = fx.make_record("A", generation=0, gt_origin="human")
    gov = _governor_with_parent(A)
    aug = _augmentor(tmp_path, gov)

    results = aug.augment("A", count=2)

    assert all(r.split == "train" for r in results)
    train_ids = {rec["meta"]["scenario_id"] for rec in gov.payout("train")}
    for r in results:
        assert r.scenario_id in train_ids, (
            f"派生 {r.scenario_id} が train split に登録されていない"
        )


def test_F003_1_multiple_derivatives_all_trace_to_parent(tmp_path):
    """F-003-1: 1親から複数派生しても、全派生が同じ親 root に遡及する。

    count 件の派生がすべて root 'A' に畳まれる（量はテストの本質にしない＝係数的に扱う）。
    """
    A = fx.make_record("A", generation=0, gt_origin="human")
    gov = _governor_with_parent(A)
    aug = _augmentor(tmp_path, gov)

    results = aug.augment("A", count=5)

    assert len(results) == 5
    # scenario_id は決定的かつ一意。
    sids = [r.scenario_id for r in results]
    assert len(set(sids)) == 5, "派生 scenario_id が一意でない（決定的採番が壊れている）"
    for r in results:
        assert gov.resolve_root(r.scenario_id) == "A"


def test_F003_1_grandchild_augmentation_folds_to_root(tmp_path):
    """F-003-1（境界・孫経由）: 派生(子)をさらに増強した孫が、推移閉包で root 'A' へ畳まれる。

    SPEC 境界条件「増強で孫・ひ孫が出た場合、リネージは推移的に親系統へ畳む」。
    親 A → 増強で子 → その子を親にさらに増強 → 孫。孫の root も 'A'。
    """
    A = fx.make_record("A", generation=0, gt_origin="human")
    gov = _governor_with_parent(A)
    aug = _augmentor(tmp_path, gov)

    [child] = aug.augment("A", count=1)
    assert child.generation == 1

    # 子を親としてさらに増強（孫を作る）。
    [grandchild] = aug.augment(child.scenario_id, count=1)

    assert grandchild.generation == 2, "孫の generation は 2 のはず"
    assert grandchild.root == "A"
    assert gov.resolve_root(grandchild.scenario_id) == "A", (
        "孫の root が推移閉包で 'A' に畳まれていない（孫経由リーク防止の前提）"
    )


def test_F003_1_great_grandchild_folds_to_root(tmp_path):
    """F-003-1（境界・ひ孫）: ひ孫(gen3)まで推移閉包で root 'A' に畳まれる。"""
    A = fx.make_record("A", generation=0, gt_origin="human")
    gov = _governor_with_parent(A)
    aug = _augmentor(tmp_path, gov)

    [child] = aug.augment("A", count=1)
    [grandchild] = aug.augment(child.scenario_id, count=1)
    [great] = aug.augment(grandchild.scenario_id, count=1)

    assert great.generation == 3
    assert gov.resolve_root(great.scenario_id) == "A"


def test_F003_1_distinct_parents_keep_distinct_roots(tmp_path):
    """F-003-1（対照・一意性）: 異なる親から増強した派生は異なる root に解決される。

    リネージ遡及が一意であること（混線しない）。親 A の派生は 'A'、親 B の派生は 'B'。
    """
    A = fx.make_record("A", generation=0, gt_origin="human")
    B = fx.make_record("B", generation=0, gt_origin="human")
    gov = _governor_with_parent(A, B)
    aug = _augmentor(tmp_path, gov)

    [ra] = aug.augment("A", count=1)
    [rb] = aug.augment("B", count=1)

    assert gov.resolve_root(ra.scenario_id) == "A"
    assert gov.resolve_root(rb.scenario_id) == "B"
    assert gov.resolve_root(ra.scenario_id) != gov.resolve_root(rb.scenario_id)


def test_F003_1_generator_is_injected_abstraction(tmp_path):
    """F-003-1: 生成器は注入可能な抽象(callable)であり、Augmentor が呼び出す。

    ADR 0011 決定1: 生成器は注入可能な callable。偽生成器が親ごとに呼ばれることを確認。
    機構（注入点）の検証であり、生成品質はテスト対象外。
    """
    A = fx.make_record("A", generation=0, gt_origin="human")
    gov = _governor_with_parent(A)

    calls = []

    def spy_generator(parent_record, *, index):
        calls.append((parent_record["meta"]["scenario_id"], index))
        return _fake_generator(parent_record, index=index)

    aug = _augmentor(tmp_path, gov, generator=spy_generator)
    aug.augment("A", count=3)

    # 親 A について index 0,1,2 で3回呼ばれる（注入された callable が機構の生成点）。
    assert calls == [("A", 0), ("A", 1), ("A", 2)], (
        "注入生成器が親ごと・連番で呼ばれていない"
    )


# ---------------------------------------------------------------------------
# 異常系: 未登録の親からは増強できない
# ---------------------------------------------------------------------------

def test_F003_1_augment_unregistered_parent_rejected(tmp_path):
    """F-003-1（異常系）: governor 未登録の親IDからの増強は拒否される。

    親系統への遡及が成立しない（root が解決できない）ため、増強を許してはならない。
    """
    gov = datagov.DataGovernor()  # 何も登録していない
    aug = _augmentor(tmp_path, gov)

    with pytest.raises(augment.ParentNotRegisteredError):
        aug.augment("NOT_REGISTERED", count=1)
