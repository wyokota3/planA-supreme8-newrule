"""F-003 着手条件: 新規 train root ∩ 封印 root = ∅ の突合（逆方向交差 G1）。

specs/SPEC.md F-003 着手条件(2026-06-12 監査由来・ADR 0010 決定4):
  「封印後に train を追加する『逆方向交差』(統合ギャップ G1) ... の検査統合点を
   設計に含めること。」
decisions/0011-f003-augment-policies.md 決定2:
  - augment の登録経路で「新規 train root ∩ 封印 root = ∅」を検査し、交差する増強登録を
    拒否する。F-002 が封印登録時に「封印 root ∩ train root = ∅」を検査するのと対向で、
    両方向を閉じる（G1 の継続検証点が F-003 に出来る）。
  - augment は DataGovernor(train 権威)と SealStore(封印 root 集合の供給元)を受領して
    突合する。封印 root 集合は sealset から取得するが、augment は root ID 集合として扱う
    （封印本体 gt には触れない）。
TEST_STRATEGY.md F-001 必須境界 / F-002:
  「孫経由リークを意図的に作って検出」。

----------------------------------------------------------------------------
このファイルが固定する supreme.augment の前提 API（テスト駆動・report に明記）:

  Augmentor は augment() 時に seal_store.sealed_lineage_set()（封印 root ID 集合）を
  取得し、新規 train の root（governor.resolve_root で再解決した値）が封印 root と
  交差するなら登録を拒否する。
    例外: augment.SealCrossError
          （train→seal 方向の交差。F-002 の LineageCrossError と同種だが、train を
            封印に足す方向であることが分かる別名。datagov/sealset の LineageCrossError を
            継承してよいが、augment 名前空間に専用例外を公開する）。
    拒否時、派生は governor の train に登録されない（突合は登録の前に行う）。
"""

import pytest

import fixtures_gt as fx
from supreme import datagov
from supreme import sealset
from supreme import augment


def _fake_generator(parent_record, *, index):
    parent_id = parent_record["meta"]["scenario_id"]
    derived_id = f"{parent_id}__aug{index}"
    return fx.make_record(
        derived_id,
        parent_lineage_id=derived_id,
        parents=[],
        generation=0,
        gt_origin="fake_generator",
    )


def _governor_with(*records):
    gov = datagov.DataGovernor()
    for r in records:
        gov.register(r)
    return gov


def _seal_store_with(tmp_path, governor, sealed_records):
    """指定レコードを封印した SealStore を作って返す。

    封印登録は SealStore.register(record, *, governor, ts) を用いる（F-002 実 API）。
    封印対象 root は governor の train と交差しない前提で構成する。
    """
    store = sealset.SealStore(root_dir=tmp_path / "seal", production=False)
    for i, rec in enumerate(sealed_records):
        store.register(rec, governor=governor, ts=float(i))
    return store


def _augmentor(governor, store):
    return augment.Augmentor(
        governor=governor, seal_store=store, generator=_fake_generator,
        generator_lineage="fake_generator",
    )


# ---------------------------------------------------------------------------
# 陽性: 封印 root と交差しない増強 train 登録は成功する
# ---------------------------------------------------------------------------

def test_F003_disjoint_augment_succeeds(tmp_path):
    """F-003 着手条件（陽性）: 封印 root と交差しない親からの増強は登録成功。

    封印は root C のみ。増強は別 root A から行うので非交差 → 登録される。
    突合が「常に拒否」ではなく非交差なら通すことを担保する（陽性対照）。
    """
    A = fx.make_record("A", generation=0, gt_origin="human")
    humans = fx.human_roots()  # C/D/E/F（独立 root）
    gov = _governor_with(A, humans["C"])

    store = _seal_store_with(tmp_path, gov, [humans["C"]])
    assert store.sealed_lineage_set() == {"C"}

    aug = _augmentor(gov, store)
    results = aug.augment("A", count=2, gt_origin="cross_checked")

    assert len(results) == 2
    # 増強 root 'A' は封印 root 集合 {'C'} と交差しない。
    assert all(r.root == "A" for r in results)
    assert "A" not in store.sealed_lineage_set()


# ---------------------------------------------------------------------------
# 陰性（直接交差）: 親 root 自体が封印されている場合の増強は拒否
# ---------------------------------------------------------------------------

def test_F003_direct_seal_cross_rejected(tmp_path):
    """F-003 着手条件（陰性・直接交差）: 親 root が封印済みなら、その増強は拒否される。

    封印 root C を持つ状態で、同じ root C から増強 train を作ろうとする＝逆方向交差(G1)。
    封印後に train を足してリークさせる経路を augment が閉じる。
    """
    C = fx.make_record("C", generation=0, gt_origin="human")
    gov = _governor_with(C)
    store = _seal_store_with(tmp_path, gov, [C])
    assert store.sealed_lineage_set() == {"C"}

    aug = _augmentor(gov, store)
    with pytest.raises(augment.SealCrossError):
        aug.augment("C", count=1, gt_origin="cross_checked")

    # 拒否されたので C 由来の派生は train に入っていない。
    train_ids = {rec["meta"]["scenario_id"] for rec in gov.payout("train")}
    assert not any(sid.startswith("C__aug") for sid in train_ids)


# ---------------------------------------------------------------------------
# 陰性（孫経由交差）: 親 root の子孫を増強しても root へ畳んで検出して拒否
# ---------------------------------------------------------------------------

def test_F003_grandchild_seal_cross_rejected(tmp_path):
    """F-003 着手条件（陰性・孫経由交差）: 封印 root A の子孫の増強は root へ畳んで拒否。

    TEST_STRATEGY「孫経由リークを意図的に作って検出」。
    親 A→子 A_c1 を封印に置き（root A が封印 root）、A_c1 を親としてさらに増強 train を
    作ろうとする。派生の root は推移閉包で 'A' に畳まれ、封印 root 'A' と交差 → 拒否。
    """
    fam_A = fx.lineage_family_A()
    # 封印側の素材として A・A_c1 を governor に登録（封印は root A に畳まれる）。
    gov = _governor_with(fam_A["A"], fam_A["A_c1"])
    store = _seal_store_with(tmp_path, gov, [fam_A["A"], fam_A["A_c1"]])
    assert store.sealed_lineage_set() == {"A"}

    aug = _augmentor(gov, store)
    # 子 A_c1 をさらに増強しようとする＝孫を train に足す＝root 'A' と交差。
    with pytest.raises(augment.SealCrossError):
        aug.augment("A_c1", count=1, gt_origin="cross_checked")

    train_ids = {rec["meta"]["scenario_id"] for rec in gov.payout("train")}
    assert not any(sid.startswith("A_c1__aug") for sid in train_ids)


def test_F003_seal_cross_error_is_train_to_seal_direction(tmp_path):
    """F-003 着手条件: 専用例外 SealCrossError が augment 名前空間に公開される。

    F-002 の LineageCrossError と同種でよいが、train→seal 方向（train を封印に足す）と
    分かる専用例外を augment が持つ（ADR 0011 決定2の「両方向を閉じる」可視化）。
    """
    assert hasattr(augment, "SealCrossError"), (
        "augment は train→seal 方向の専用例外 SealCrossError を公開すべき"
    )
    # 例外クラスであること。
    assert isinstance(augment.SealCrossError, type)
    assert issubclass(augment.SealCrossError, Exception)


# ---------------------------------------------------------------------------
# D1 回避: augment は保存済み parent_lineage_id を無検算で信頼せず、
#          governor.resolve_root で再解決した root で封印突合する
# ---------------------------------------------------------------------------

def test_F003_seal_cross_uses_resolved_root_not_stored_tag(tmp_path):
    """F-003 着手条件（D1 回避）: 突合は resolve_root の再解決 root で行う。

    decisions/0011 決定2「D1 対策: 突合に使う root は augment 側で governor の推移閉包
    (resolve_root)により再解決し、保存済み parent_lineage_id を無検算で信頼しない」。

    構成: 封印 root A。親 A の子 A_c1 を train に登録済み。A_c1 を親として増強すると、
    派生の直接親(parents=[A_c1])の parent_lineage_id は A だが、これを「文字列として」
    信頼するのではなく governor.resolve_root(派生) が 'A' を返すことに依拠して
    封印 root 'A' との交差を検出する。resolve_root を使わず保存タグだけを見る実装では
    （タグ取り違えで）見逃しうるが、本テストは resolve_root 経由で確実に拒否されること
    を固定する。
    """
    fam_A = fx.lineage_family_A()
    # train 側に A・A_c1 を登録（封印は root A）。
    gov = _governor_with(
        fx.with_split(fam_A["A"], "train"),
        fx.with_split(fam_A["A_c1"], "train"),
    )
    # 封印には別途 root A の素材を登録（封印 root 集合 = {'A'}）。
    # ※ ここでは封印側 store を A 系統で構成し、sealed_lineage_set が root へ畳むことを使う。
    seal_gov = _governor_with(fam_A["A"], fam_A["A_c1"])
    store = sealset.SealStore(root_dir=tmp_path / "seal", production=False)
    store.register(fam_A["A"], governor=seal_gov, ts=0.0)
    assert store.sealed_lineage_set() == {"A"}

    # train governor 側で A_c1 を親に増強 → 派生 root は resolve_root で 'A'。
    aug = augment.Augmentor(
        governor=gov, seal_store=store, generator=_fake_generator,
        generator_lineage="fake_generator",
    )
    # 派生の root は resolve_root('A_c1__aug0') == 'A' で封印 root 'A' と交差 → 拒否。
    with pytest.raises(augment.SealCrossError):
        aug.augment("A_c1", count=1, gt_origin="cross_checked")

    # resolve_root が 'A' に畳むことを独立に確認（D1 の判定根拠が保存タグでなく再解決）。
    assert gov.resolve_root("A_c1") == "A"


def test_F003_seal_cross_checked_against_live_seal_set(tmp_path):
    """F-003 着手条件: 封印 root 集合は seal_store から都度取得した最新集合で突合する。

    封印が後から1件増えたとき、増強時点の sealed_lineage_set() を見て交差判定すること
    （封印 root 集合を Augmentor 構築時に固定キャプチャせず、augment 呼び出しのたびに
    seal_store から最新を取得する＝逆方向交差 G1 の継続検証点）。

    構成: 親 A・B を train、封印は最初 C のみ。A の増強は通る。
    その後 root B を封印に追加してから B を増強しようとすると拒否される。
    （A と C/B は別 root なので、封印登録自体は train との非交差検査を通る。）
    """
    A = fx.make_record("A", generation=0, gt_origin="human")
    B = fx.make_record("B", generation=0, gt_origin="human")
    humans = fx.human_roots()  # C は独立 root
    # train governor には親 A・B を登録。封印対象 C は train に置かない。
    gov = _governor_with(A, B)

    store = sealset.SealStore(root_dir=tmp_path / "seal", production=False)
    # 封印に C を登録（C は train に無いので非交差検査を通る）。
    store.register(humans["C"], governor=gov, ts=0.0)
    assert store.sealed_lineage_set() == {"C"}

    aug = _augmentor(gov, store)

    # 1) 封印 {'C'} のうちは別 root A の増強は通る。
    first = aug.augment("A", count=1, gt_origin="cross_checked")
    assert len(first) == 1

    # 2) その後 root B を封印に追加する（B はまだ増強していないので train と非交差）。
    store.register(B, governor=gov, ts=1.0)
    assert store.sealed_lineage_set() == {"C", "B"}

    # 3) 封印集合が増えた後、B の増強は最新の封印集合 {'C','B'} と交差 → 拒否。
    with pytest.raises(augment.SealCrossError):
        aug.augment("B", count=1, gt_origin="cross_checked")
