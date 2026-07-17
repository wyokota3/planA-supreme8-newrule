"""F-002-1: 封印セットの各シナリオ親系統が F-001 のリネージで練習用と非交差。

specs/SPEC.md F-002-1:
  「封印セットの各シナリオ親系統が F-001 のリネージで練習用と非交差。」
specs/GT_SCHEMA.md「リネージ規則」「分割非交差」:
  split=seal の親系統集合 ∩ split=train の親系統集合 = ∅。孫・ひ孫は推移閉包で root へ畳む。
decisions/0009-f002-sealset-policies.md 決定1/2:
  sealset は datagov の既存契約(リネージ検証)を再利用する。独自のリネージ検証を再発明しない。

----------------------------------------------------------------------------
このファイルが定義する supreme.sealset の前提 API（テスト駆動・report に明記）:

  SealStore(*, root_dir, production, seal_guard=None):
    封印データの分離保管・アクセス制御・永続ログを束ねる機構。
    root_dir : pathlib.Path | str  封印データ/ログ/状態ファイルを置く専用ディレクトリ
                                   （テストは pytest の tmp_path を注入。リポジトリ外想定）。
    production: bool   キーワード明示必須（GUARD_IF / SealGuard と同じ向き。省略は TypeError）。
                       True=本番封印(生涯1回)、False=ダミーモード(常用テスト・複数回開封可)。
    seal_guard: guard.SealGuard | None  省略時は SealStore が production に応じて内部生成する。

  SealStore.register(record, *, governor, ts) -> RegisterResult
    封印への登録。governor は登録済みデータ(練習用 train を含む)を持つ
    datagov.DataGovernor。sealset は governor のリネージ/バリデーション契約で
    検証してから封印保管する（独自検証を再発明しない）。
    ts はキーワード必須（ADR 0010 追記・上書き試行の記録時刻）。正常登録では
    access_log に何も記録しない。
    注: governor.register(record)（DataGovernor 側・本ファイルの _governor_with_train
    内）の署名は変更されない。ts 付きは SealStore.register のみ。
    - record の root 親系統が governor 上の train 親系統集合と交わるなら
      sealset.LineageCrossError を送出し、封印に書かない（陰性）。
    - スキーマ違反は datagov.ValidationError 系（F-002-3 ファイルで詳述）。
    - 成功時 RegisterResult を返し、record は root_dir 配下の封印ストレージに書かれる。
    例外: sealset.LineageCrossError（datagov.LineageCrossError を継承 or 同一でもよい）。

  SealStore.sealed_lineage_set() -> set[str]
    現在封印に登録済みの root 親系統ID集合。

ストレージ前提（report に明記）:
  封印データは root_dir 配下にのみ書かれる（分離保管）。具体レイアウトは
  test_F002_storage_isolation.py で固定する。
"""

import pytest

import fixtures_gt as fx
from supreme import datagov
from supreme import sealset


def _governor_with_train(records):
    """split=train を直接指定して register した governor を返す（練習用の素材）。"""
    gov = datagov.DataGovernor()
    for r in records:
        gov.register(r)
    return gov


# ---------------------------------------------------------------------------
# 陽性対照: 交差しない封印登録は成功する
# ---------------------------------------------------------------------------

def test_F002_1_register_disjoint_lineage_succeeds(tmp_path):
    """F-002-1（陽性対照）: 練習用と交差しない root を封印登録できる。

    リーク検査が「常に拒否」でなく、非交差なら通すことを担保する。
    """
    humans = fx.human_roots()
    # 練習用に B 系統と D を登録（C/E は封印に回す）。
    fam_B = fx.lineage_family_B()
    gov = _governor_with_train([
        fx.with_split(fam_B["B"], "train"),
        fx.with_split(fam_B["B_c1"], "train"),
        fx.with_split(humans["D"], "train"),
    ])

    store = sealset.SealStore(root_dir=tmp_path, production=False)
    store.register(humans["C"], governor=gov, ts=0.0)
    store.register(humans["E"], governor=gov, ts=1.0)

    assert store.sealed_lineage_set() == {"C", "E"}
    # 封印 root と train root は交わらない。
    assert store.sealed_lineage_set() & gov.lineage_set("train") == set()


# ---------------------------------------------------------------------------
# 陰性: root が train と直接交差する封印登録は拒否
# ---------------------------------------------------------------------------

def test_F002_1_register_crossing_train_root_rejected(tmp_path):
    """F-002-1（陰性）: 練習用と同一 root を封印登録しようとすると拒否される。

    root "B" を train に持つ governor に対し、同じ root "B" を封印登録しようとする。
    """
    fam_B = fx.lineage_family_B()
    gov = _governor_with_train([
        fx.with_split(fam_B["B"], "train"),
        fx.with_split(fam_B["B_c1"], "train"),
    ])

    store = sealset.SealStore(root_dir=tmp_path, production=False)
    with pytest.raises(sealset.LineageCrossError):
        store.register(fam_B["B"], governor=gov, ts=0.0)

    # 拒否されたので封印には何も入っていない。
    assert store.sealed_lineage_set() == set()


# ---------------------------------------------------------------------------
# 陰性（孫経由交差）: train 側の root の孫を封印登録しようとすると拒否
# ---------------------------------------------------------------------------

def test_F002_1_register_grandchild_of_train_root_rejected(tmp_path):
    """F-002-1（陰性・孫経由交差）: train 側 root A の孫を封印登録しようとすると拒否。

    親A→子(A_c1)→孫(A_gc1) のうち A・A_c1 を train に登録した governor に対し、
    孫 A_gc1 を封印登録しようとする。孫は推移閉包で root "A" に畳まれるため、
    train の root "A" と交差する＝リーク。datagov のリネージで畳んで検出すること。
    """
    fam_A = fx.lineage_family_A()
    gov = _governor_with_train([
        fx.with_split(fam_A["A"], "train"),
        fx.with_split(fam_A["A_c1"], "train"),
    ])

    store = sealset.SealStore(root_dir=tmp_path, production=False)
    with pytest.raises(sealset.LineageCrossError):
        # 封印側でも孫の親系統解決のため A_c1/A_gc1 のリネージが要る。
        # governor は train として既に A 系統を保持しているので、その root へ畳んで判定。
        store.register(fam_A["A_gc1"], governor=gov, ts=0.0)

    assert store.sealed_lineage_set() == set()


def test_F002_1_sealed_lineage_disjoint_from_train(tmp_path):
    """F-002-1: 複数封印登録後も、封印 root 集合と train root 集合が非交差。

    集合演算で seal ∩ train = ∅ を assert（方法論検証層・リーク検査）。
    """
    humans = fx.human_roots()
    fam_A = fx.lineage_family_A()
    gov = _governor_with_train([
        fx.with_split(fam_A["A"], "train"),
        fx.with_split(fam_A["A_c1"], "train"),
        fx.with_split(fam_A["A_gc1"], "train"),
        fx.with_split(fam_A["A_c2"], "train"),
    ])

    store = sealset.SealStore(root_dir=tmp_path, production=False)
    store.register(humans["C"], governor=gov, ts=0.0)
    store.register(humans["D"], governor=gov, ts=1.0)
    store.register(humans["E"], governor=gov, ts=2.0)

    assert store.sealed_lineage_set() & gov.lineage_set("train") == set()
    assert store.sealed_lineage_set() == {"C", "D", "E"}
