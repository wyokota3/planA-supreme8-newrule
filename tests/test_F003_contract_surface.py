"""F-003 公開契約面: supreme.augment モジュールの公開 API が存在し、
datagov/sealset と正しく結線されること（統合観点・契約面の固定）。

specs/SPEC.md F-003 / 対応コンポーネント `augment`。
decisions/0011-f003-augment-policies.md:
  - 決定1: 機構のみ実装（生成器は注入可能な抽象）。
  - 決定2: augment は DataGovernor(train 権威) と SealStore(封印 root 供給元) を受領して突合。
  - 決定3: datagov 単一権威化案は不採用（sealset は改修しない）。
            → augment は sealset の sealed_lineage_set() を root ID 集合として読むだけで、
              封印本体 gt には触れない。

このファイルは個々の受け入れ条件の振る舞いではなく「契約面（公開シンボルの存在・
結線・最小不変条件）」を固定する。実装不在のうちは import 段階で失敗する。
"""

import inspect

import pytest

import fixtures_gt as fx
from supreme import datagov
from supreme import sealset
from supreme import augment


def _fake_generator(parent_record, *, index):
    parent_id = parent_record["meta"]["scenario_id"]
    derived_id = f"{parent_id}__aug{index}"
    return fx.make_record(
        derived_id, parent_lineage_id=derived_id, parents=[], generation=0,
        gt_origin="fake_generator",
    )


def _aug(tmp_path, governor):
    store = sealset.SealStore(root_dir=tmp_path / "seal", production=False)
    return augment.Augmentor(
        governor=governor, seal_store=store, generator=_fake_generator,
        generator_lineage="fake_generator",
    )


# ---------------------------------------------------------------------------
# 公開シンボルの存在
# ---------------------------------------------------------------------------

def test_F003_augment_module_exposes_augmentor():
    """F-003: augment は Augmentor クラスを公開する。"""
    assert hasattr(augment, "Augmentor")
    assert isinstance(augment.Augmentor, type)


def test_F003_augment_module_exposes_exceptions():
    """F-003: augment は ParentNotRegisteredError / SealCrossError を公開する。

    - ParentNotRegisteredError: 未登録の親からの増強（F-003-1 異常系）。
    - SealCrossError: 新規 train root ∩ 封印 root ≠ ∅（着手条件・G1）。
    """
    for name in ("ParentNotRegisteredError", "SealCrossError"):
        assert hasattr(augment, name), f"augment.{name} が公開されていない"
        cls = getattr(augment, name)
        assert isinstance(cls, type) and issubclass(cls, Exception)


def test_F003_augmentor_requires_governor_seal_store_generator():
    """F-003（契約面）: Augmentor は governor / seal_store / generator を受領する。

    ADR 0011 決定2: train 権威 governor と封印 root 供給元 seal_store を受領して突合する。
    キーワード専用で受け取る（既存 datagov/sealset の流儀）。
    """
    sig = inspect.signature(augment.Augmentor)
    params = sig.parameters
    for name in ("governor", "seal_store", "generator"):
        assert name in params, f"Augmentor は {name} を受領すべき"


# ---------------------------------------------------------------------------
# 結線: governor / seal_store を実際に使う（受領が飾りでない）
# ---------------------------------------------------------------------------

def test_F003_augmentor_uses_injected_governor_for_registration(tmp_path):
    """F-003（結線）: 注入された governor に派生が登録される（train 権威の単一窓口）。

    augment は独自ストアを持たず、受領した governor に train 登録する（ADR 0011 決定2）。
    """
    A = fx.make_record("A", generation=0, gt_origin="human")
    gov = datagov.DataGovernor()
    gov.register(A)
    aug = _aug(tmp_path, gov)

    [r] = aug.augment("A", count=1, gt_origin="cross_checked")

    # 派生は注入 governor 経由で resolve 可能（governor が権威）。
    assert gov.resolve_root(r.scenario_id) == "A"


def test_F003_augmentor_reads_seal_root_set_only(tmp_path):
    """F-003（結線・決定3）: augment は seal_store の root 集合を読むだけで本体 gt に触れない。

    ADR 0011 決定3: sealset は改修しない。augment は sealed_lineage_set()（root ID 集合）
    を読むのみ。封印本体 gt を読む API（read_sealed_gt 等・トークンが要る経路）は使わない。
    本テストはトークン無しの SealStore でも augment の突合が成立することで「本体に触れない」
    ことを担保する（本体を読むならトークンが要り、トークン無しでは AccessDenied になるはず）。
    """
    A = fx.make_record("A", generation=0, gt_origin="human")
    humans = fx.human_roots()
    gov = datagov.DataGovernor()
    gov.register(A)
    gov.register(humans["C"])

    store = sealset.SealStore(root_dir=tmp_path / "seal", production=False)
    store.register(humans["C"], governor=gov, ts=0.0)  # 封印 root = {'C'}

    aug = augment.Augmentor(
        governor=gov, seal_store=store, generator=_fake_generator,
        generator_lineage="fake_generator",
    )
    # トークンを一切発行・使用せずに突合（root 集合読みのみ）して増強が成立する。
    results = aug.augment("A", count=1, gt_origin="cross_checked")
    assert len(results) == 1
    # 封印本体に触れていないこと自体は「トークン無しで AccessDenied にならず完了した」で担保。
    assert results[0].root == "A"
