"""F-002-3 + 分離保管: 封印登録時の GT スキーマ準拠（datagov 契約の再利用）と
封印データの分離保管・通常読み出しからの遮断。

specs/SPEC.md F-002-3:
  「封印GTは F-001 単一スキーマに準拠。」
specs/GT_SCHEMA.md「バリデーション規則」:
  必須キー欠落・型不一致・空文字列・確率 [0,1] 外・ts 非単調・t2 クラスキー集合不一致 等は拒否。
decisions/0009-f002-sealset-policies.md 決定1/2:
  - 機構は gt_origin 等の来歴を記録するのみ（GT 確認ワークフロー U17 は研究者運用）。
  - 封印データは専用ディレクトリ（root_dir）に分離保管。
  - sealset は datagov の既存バリデーション契約を再利用する（独自スキーマ検証を再発明しない）。

----------------------------------------------------------------------------
このファイルが定義する supreme.sealset の前提 API（テスト駆動・report に明記）:

  SealStore.register(record, *, governor, ts) -> RegisterResult
    封印登録時に datagov の GT_SCHEMA バリデーションを適用する。
    違反データ（拒否事由あり）は datagov.ValidationError を送出し、封印に書かない。
    ts はキーワード必須（ADR 0010 追記・上書き試行の記録時刻に使う）。
    正常登録では access_log に何も記録されない（ts は上書き試行時のみ使用）。
    成功時 RegisterResult を返す:
      .scenario_id : str   登録した scenario_id
      .split       : str   封印登録なので必ず "seal"
      .gt_origin   : str   record の meta.gt_origin（来歴の記録）
      .warnings    : list[str]  datagov の警告（登録は可・記録のみ）

  SealStore.stored_meta(scenario_id) -> dict
    封印に保管したレコードの meta 層（split / gt_origin 等の来歴）を返す。
    トークン無しでも meta は参照できる（メタデータは秘匿対象でない。秘匿対象は gt 本体）。

ストレージレイアウト（テストが固定する・report に明記）:
  root_dir/
    sealed/<scenario_id>.json   … 封印レコード本体（JSON, stdlib json）
    access_log.jsonl            … SealAccessRecord の JSONL 永続ログ
    session_state.json          … 生涯開封セッション状態（プロセス跨ぎ用）
  封印データ本体は root_dir 配下にのみ書かれ、外には漏れない（tmp_path で検証）。
"""

import json

import pytest

import fixtures_gt as fx
from supreme import datagov
from supreme import sealset


def _empty_governor():
    """train を持たない governor（非交差は自明に成立）。"""
    return datagov.DataGovernor()


# ---------------------------------------------------------------------------
# F-002-3: スキーマ準拠（datagov バリデーション契約の再利用）
# ---------------------------------------------------------------------------

def test_F002_3_valid_human_record_registers_to_seal(tmp_path):
    """F-002-3: 正規形として妥当な人手 root レコードは封印登録できる。"""
    store = sealset.SealStore(root_dir=tmp_path, production=False)
    rec = fx.make_record("seal001", gt_origin="human")
    result = store.register(rec, governor=_empty_governor(), ts=0.0)
    assert result.scenario_id == "seal001"


def test_F002_3_split_is_seal_after_register(tmp_path):
    """F-002-3: 封印登録後、meta.split が "seal" になっている。"""
    store = sealset.SealStore(root_dir=tmp_path, production=False)
    rec = fx.make_record("seal001", gt_origin="human")
    result = store.register(rec, governor=_empty_governor(), ts=0.0)
    assert result.split == "seal"
    # 保管された meta からも split=seal を確認できる。
    assert store.stored_meta("seal001")["split"] == "seal"


def test_F002_3_gt_origin_is_recorded(tmp_path):
    """F-002-3: 封印登録時に gt_origin（来歴）が記録される（ADR 0009 決定1）。"""
    store = sealset.SealStore(root_dir=tmp_path, production=False)
    rec = fx.make_record("seal001", gt_origin="human")
    result = store.register(rec, governor=_empty_governor(), ts=0.0)
    assert result.gt_origin == "human"
    assert store.stored_meta("seal001")["gt_origin"] == "human"


def test_F002_3_schema_violation_missing_key_rejected(tmp_path):
    """F-002-3（拒否）: 必須キー欠落のレコードは封印登録不可（datagov 契約）。"""
    store = sealset.SealStore(root_dir=tmp_path, production=False)
    rec = fx.make_record("seal001", gt_origin="human")
    del rec["meta"]["parent_lineage_id"]
    with pytest.raises(datagov.ValidationError):
        store.register(rec, governor=_empty_governor(), ts=0.0)


def test_F002_3_schema_violation_prob_out_of_range_rejected(tmp_path):
    """F-002-3（拒否）: 確率値 [0,1] 外のレコードは封印登録不可（datagov 契約）。"""
    store = sealset.SealStore(root_dir=tmp_path, production=False)
    rec = fx.make_record("seal001", gt_origin="human")
    rec["gt"]["frames"][0]["t2"]["mode"]["uncertain"] = 1.5
    with pytest.raises(datagov.ValidationError):
        store.register(rec, governor=_empty_governor(), ts=0.0)


def test_F002_3_schema_violation_empty_string_rejected(tmp_path):
    """F-002-3（拒否）: 文字列必須フィールドの空文字列は封印登録不可（非空要求）。"""
    store = sealset.SealStore(root_dir=tmp_path, production=False)
    rec = fx.make_record("seal001", gt_origin="human")
    rec["gt"]["frames"][0]["t3"]["hypothesis"] = ""
    with pytest.raises(datagov.ValidationError):
        store.register(rec, governor=_empty_governor(), ts=0.0)


def test_F002_3_schema_violation_t2_keyset_mismatch_rejected(tmp_path):
    """F-002-3（拒否）: t2 分布のクラスキー集合不一致は封印登録不可（突合可能性）。"""
    store = sealset.SealStore(root_dir=tmp_path, production=False)
    rec = fx.make_record("seal001", gt_origin="human")
    mode = rec["gt"]["frames"][0]["t2"]["mode"]
    del mode["side_rear_caution"]
    mode["NOT_A_REAL_MODE"] = 0.0
    with pytest.raises(datagov.ValidationError):
        store.register(rec, governor=_empty_governor(), ts=0.0)


def test_F002_3_rejected_record_not_written_to_disk(tmp_path):
    """F-002-3（拒否・分離保管整合）: 拒否されたレコードは封印ストレージに書かれない。"""
    store = sealset.SealStore(root_dir=tmp_path, production=False)
    rec = fx.make_record("seal001", gt_origin="human")
    rec["gt"]["frames"][0]["t2"]["mode"]["uncertain"] = 1.5  # 確率違反
    with pytest.raises(datagov.ValidationError):
        store.register(rec, governor=_empty_governor(), ts=0.0)

    # sealed/ 配下に seal001 の本体ファイルが存在しないこと。
    sealed_dir = tmp_path / "sealed"
    if sealed_dir.exists():
        contents = json.dumps(
            [p.name for p in sealed_dir.iterdir()]
        )
        assert "seal001" not in contents


# ---------------------------------------------------------------------------
# 分離保管: 封印データは root_dir 配下にのみ書かれる
# ---------------------------------------------------------------------------

def test_F002_storage_data_written_only_under_root_dir(tmp_path):
    """分離保管: 封印データ本体は root_dir 配下にのみ書かれる。

    root_dir を sub/ に置き、その外（兄弟ディレクトリ）に何も書かれないことを確認する。
    """
    root_dir = tmp_path / "seal_root"
    sibling = tmp_path / "outside"
    sibling.mkdir()

    store = sealset.SealStore(root_dir=root_dir, production=False)
    store.register(fx.make_record("seal001", gt_origin="human"),
                   governor=_empty_governor(), ts=0.0)

    # root_dir 配下に何かが書かれている。
    assert root_dir.exists()
    written = list(root_dir.rglob("*"))
    assert any(p.is_file() for p in written), "封印データが root_dir 配下に書かれていない"

    # 兄弟ディレクトリ（root_dir 外）には何も書かれていない。
    assert list(sibling.iterdir()) == [], "封印データが root_dir 外に漏れている"


def test_F002_storage_seal_body_not_reachable_without_token(tmp_path):
    """分離保管: 登録後、通常の読み出しAPI（トークン無し）では gt 本体に到達できない。

    トークン無しの read_sealed_gt は sealset.AccessDenied を送出する（meta は参照可だが
    本体 gt は秘匿）。「技術的に遮断」（SPEC 正常系）の検証。
    """
    store = sealset.SealStore(root_dir=tmp_path, production=False)
    store.register(fx.make_record("seal001", gt_origin="human"),
                   governor=_empty_governor(), ts=0.0)

    # トークン無し（token=None）での本体読み出しは拒否される。
    with pytest.raises(sealset.AccessDenied):
        store.read_sealed_gt("seal001", token=None, ts=100.0)


def test_F002_storage_meta_reachable_without_token(tmp_path):
    """分離保管（対照）: meta（来歴）はトークン無しでも参照できる（秘匿対象は gt 本体のみ）。"""
    store = sealset.SealStore(root_dir=tmp_path, production=False)
    store.register(fx.make_record("seal001", gt_origin="human"),
                   governor=_empty_governor(), ts=0.0)
    meta = store.stored_meta("seal001")
    assert meta["scenario_id"] == "seal001"
    assert meta["split"] == "seal"
