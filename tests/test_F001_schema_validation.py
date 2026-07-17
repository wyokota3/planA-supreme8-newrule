"""F-001-2: GT 単一スキーマのバリデーション（拒否系 / 警告系の分離）。

specs/GT_SCHEMA.md「バリデーション規則」（2026-06-12 改版・ADR 0004）に厳密に従う。
- 拒否(登録不可): 必須キー欠落・型不一致 / 文字列必須フィールドの空文字列(非空要求) /
  meta.scenario_id ≠ gt.scenario_id / scenario_id の再登録 / 親系統不明 /
  root 宣言の不整合（parents=[] なのに parent_lineage_id≠自身 または generation≠0） /
  parent_lineage_id・generation の検算不一致 / 確率値 [0,1] 外 / ts 非単調 /
  t2 クラスキー集合不一致。
- 警告(登録可・記録): 分布合計が 1±0.01 を外れる / description 欠落。
- 検査しない: custom 配下すべて。

テストが前提とする supreme.datagov の公開 API:
- datagov.validate_record(record) -> ValidationResult
    .ok: bool（拒否事由が無ければ True）
    .errors: list[str]（拒否事由。空なら登録可）
    .warnings: list[str]（警告事由。登録は可だが記録される）
- DataGovernor().register(record):
    拒否事由があれば datagov.ValidationError を送出。
    親系統不明（親未登録 かつ root 宣言でない）は datagov.LineageError を送出。
    正常登録時は警告を保持できる戻り値（.warnings を持つ）を返す。
- 例外: datagov.ValidationError, datagov.LineageError。
"""

import pytest

import fixtures_gt as fx
from supreme import datagov


# --- 正常系（基準）-------------------------------------------------------

def test_F001_2_valid_record_passes_validation():
    """F-001-2: 正規形として妥当な root レコードは拒否事由ゼロで通る。"""
    rec = fx.make_record("ns001", gt_origin="human")
    result = datagov.validate_record(rec)
    assert result.ok is True
    assert result.errors == []


# --- 拒否系 -------------------------------------------------------------

def test_F001_2_missing_required_key_rejected():
    """F-001-2(拒否): 必須キー(meta.parent_lineage_id)の欠落は登録不可。"""
    rec = fx.make_record("ns001")
    del rec["meta"]["parent_lineage_id"]
    result = datagov.validate_record(rec)
    assert result.ok is False
    assert result.errors != []


def test_F001_2_type_mismatch_rejected():
    """F-001-2(拒否): 型不一致(generation を文字列に)は登録不可。"""
    rec = fx.make_record("ns001")
    rec["meta"]["generation"] = "zero"  # int であるべき
    result = datagov.validate_record(rec)
    assert result.ok is False
    assert result.errors != []


def test_F001_2_scenario_id_mismatch_rejected():
    """F-001-2(拒否): meta.scenario_id ≠ gt.scenario_id は登録不可。"""
    rec = fx.make_record("ns001")
    rec["gt"]["scenario_id"] = "ns999"  # meta と不一致
    result = datagov.validate_record(rec)
    assert result.ok is False
    assert result.errors != []


def test_F001_2_probability_out_of_range_rejected():
    """F-001-2(拒否): 確率値が [0,1] 外(1.5)は登録不可。"""
    rec = fx.make_record("ns001")
    rec["gt"]["frames"][0]["t2"]["mode"]["uncertain"] = 1.5
    result = datagov.validate_record(rec)
    assert result.ok is False
    assert result.errors != []


def test_F001_2_probability_negative_rejected():
    """F-001-2(拒否): 確率値が負(-0.01)は [0,1] 外で登録不可。"""
    rec = fx.make_record("ns001")
    rec["gt"]["frames"][0]["t3"]["outdoor_prob"] = -0.01
    result = datagov.validate_record(rec)
    assert result.ok is False
    assert result.errors != []


def test_F001_2_non_monotonic_ts_rejected():
    """F-001-2(拒否): ts が狭義単調増加でない(同値/逆順)は登録不可。"""
    rec = fx.make_record("ns001", n_frames=3)
    rec["gt"]["frames"][2]["ts"] = rec["gt"]["frames"][1]["ts"]  # 同値で単調性違反
    result = datagov.validate_record(rec)
    assert result.ok is False
    assert result.errors != []


def test_F001_2_t2_class_key_set_mismatch_rejected():
    """F-001-2(拒否): t2 各分布のクラスキー集合が定義と不一致は登録不可。

    突合可能性(F-001-2)が壊れるため。ここでは mode に未定義キーを足し既定キーを欠く。
    """
    rec = fx.make_record("ns001")
    mode = rec["gt"]["frames"][0]["t2"]["mode"]
    del mode["side_rear_caution"]      # 既定キーを欠く
    mode["NOT_A_REAL_MODE"] = 0.0       # 未定義キーを足す
    result = datagov.validate_record(rec)
    assert result.ok is False
    assert result.errors != []


def test_F001_2_unknown_lineage_register_rejected():
    """F-001-2(拒否・必須異常系): 親系統不明データの登録は拒否される。

    parents が未登録の scenario_id を参照し、かつ root 宣言でもない。
    GT_SCHEMA.md: 親系統不明(参照先が未登録 かつ root でない)は登録不可。
    """
    gov = datagov.DataGovernor()
    orphan = fx.make_record(
        "orphan", parent_lineage_id="GHOST", parents=["GHOST"], generation=1,
    )
    with pytest.raises((datagov.LineageError, datagov.ValidationError)):
        gov.register(orphan)


def test_F001_2_register_raises_on_reject_rule():
    """F-001-2(拒否): register は拒否事由のあるレコードで ValidationError を送出する。"""
    gov = datagov.DataGovernor()
    rec = fx.make_record("ns001")
    rec["gt"]["scenario_id"] = "mismatch"  # scenario_id 不一致(拒否)
    with pytest.raises(datagov.ValidationError):
        gov.register(rec)


# --- 警告系（登録可・記録）-----------------------------------------------

def test_F001_2_distribution_sum_off_is_warning_not_reject():
    """F-001-2(警告): 分布合計が 1±0.01 を外れても登録可・警告記録のみ。

    封印GT・人手GT を過剰拘束しないため。合計が 0.5 でも拒否しない。
    """
    rec = fx.make_record("ns001", gt_origin="human")
    # mode の合計を大きく崩す（全キーを 0.05 に＝合計 0.5）。
    for k in list(rec["gt"]["frames"][0]["t2"]["mode"].keys()):
        rec["gt"]["frames"][0]["t2"]["mode"][k] = 0.05
    result = datagov.validate_record(rec)
    assert result.ok is True, "分布合計逸脱は拒否ではなく警告であるべき"
    assert result.errors == []
    assert result.warnings != [], "分布合計逸脱は警告として記録されるべき"


def test_F001_2_missing_description_is_warning_not_reject():
    """F-001-2(警告): description 欠落は登録可・警告記録のみ。"""
    rec = fx.make_record("ns001", gt_origin="human", description=None)
    assert "description" not in rec["gt"]  # 欠落していること
    result = datagov.validate_record(rec)
    assert result.ok is True, "description 欠落は拒否ではなく警告であるべき"
    assert result.errors == []
    assert result.warnings != [], "description 欠落は警告として記録されるべき"


def test_F001_2_register_keeps_warnings_for_valid_record():
    """F-001-2(警告): 警告のみのレコードは register され、警告が保持される。"""
    gov = datagov.DataGovernor()
    rec = fx.make_record("ns001", gt_origin="human", description=None)
    reg = gov.register(rec)
    assert reg.warnings != []


# --- 検査しない（custom）-------------------------------------------------

def test_F001_2_custom_passthrough_not_validated():
    """F-001-2: custom 配下は検査対象外（不正な値でも拒否されない）。"""
    rec = fx.make_record("ns001", gt_origin="human")
    rec["custom"] = {"anything": 1.5, "nested": {"prob": -9, "k": object()}}
    result = datagov.validate_record(rec)
    assert result.ok is True
    assert result.errors == []


# --- 2026-06-12 監査対処（ADR 0004）で追加した拒否系 -----------------------
#
# 改版 GT_SCHEMA の拒否表に追加された4区分:
#   1. scenario_id の再登録（リネージ不変性の担保）
#   2. root 宣言の3条件（parents=[] ∧ parent_lineage_id=自身 ∧ generation=0）
#   3. parent_lineage_id・generation の検算不一致（parents 連鎖から解決した値と不一致）
#   4. 文字列必須フィールドの空文字列（非空要求）


# B1. scenario_id の再登録の拒否 ------------------------------------------

def test_F001_2_reregister_same_scenario_id_rejected():
    """F-001-2(拒否): 同一 scenario_id の2回目 register は ValidationError。

    改版 GT_SCHEMA「scenario_id の再登録（リネージ不変性の担保）」。
    無言上書き（リネージの事後改変）を拒否する（ADR 0004 決定2）。
    """
    gov = datagov.DataGovernor()
    rec1 = fx.make_record("dup001", gt_origin="human")
    gov.register(rec1)

    rec2 = fx.make_record("dup001", gt_origin="human", description="second")
    with pytest.raises(datagov.ValidationError):
        gov.register(rec2)


def test_F001_2_reregister_does_not_overwrite_existing_record():
    """F-001-2(拒否・上書き禁止): 再登録が拒否され、既存レコードは保持される。

    2回目の register が（万一通っても）既存を上書きしないことを確認する。
    リネージ不変性: 登録済みの内容が事後改変されてはならない。
    """
    gov = datagov.DataGovernor()
    rec1 = fx.make_record("dup001", gt_origin="human", description="first")
    gov.register(rec1)

    rec2 = fx.make_record("dup001", gt_origin="human", description="OVERWRITTEN")
    with pytest.raises(datagov.ValidationError):
        gov.register(rec2)

    # 既存レコードは1回目の内容のまま（上書きされていない）。
    stored = gov.payout("unassigned")
    matched = [r for r in stored if r["meta"]["scenario_id"] == "dup001"]
    assert len(matched) == 1, "再登録で重複・置換されてはならない"
    assert matched[0]["gt"]["description"] == "first", (
        "再登録が既存レコードを上書きしている（リネージの事後改変）"
    )


# B2. root 宣言の3条件の強制 ---------------------------------------------

def test_F001_2_root_decl_empty_parents_with_foreign_lineage_id_rejected():
    """F-001-2(拒否): parents=[] なのに parent_lineage_id≠自身 は登録不可。

    改版 GT_SCHEMA「root 宣言の不整合（parents=[] なのに parent_lineage_id≠自身）」。
    監査指摘の「parents=[] かつ parent_lineage_id≠自身 が通る抜け道」を閉じる。
    root でないのに root 扱いになるレコードの正規登録を防ぐ。
    """
    gov = datagov.DataGovernor()
    rec = fx.make_record(
        "fake_root",
        parent_lineage_id="SOMEONE_ELSE",  # 自身でない
        parents=[],                          # しかし root を主張する空 parents
        generation=0,
    )
    with pytest.raises((datagov.ValidationError, datagov.LineageError)):
        gov.register(rec)


def test_F001_2_root_decl_empty_parents_with_nonzero_generation_rejected():
    """F-001-2(拒否): parents=[] なのに generation≠0 は登録不可。

    改版 GT_SCHEMA「root 宣言の不整合（parents=[] なのに generation≠0）」。
    root 宣言の3条件（parents=[] ∧ parent_lineage_id=自身 ∧ generation=0）の強制。
    """
    gov = datagov.DataGovernor()
    rec = fx.make_record(
        "fake_root2",
        parent_lineage_id="fake_root2",  # 自身（ここは整合）
        parents=[],                       # root を主張
        generation=5,                     # しかし generation が 0 でない
    )
    with pytest.raises((datagov.ValidationError, datagov.LineageError)):
        gov.register(rec)


# B3. parent_lineage_id・generation の検算不一致の拒否 ---------------------

def test_F001_2_nonroot_parent_lineage_id_checksum_mismatch_rejected():
    """F-001-2(拒否): 非 root の parent_lineage_id が解決値と不一致は登録不可。

    改版 GT_SCHEMA「parent_lineage_id・generation の検算不一致（parents 連鎖から
    解決した値と不一致）」。子の parent_lineage_id は親の parent_lineage_id を継承
    （= root "A"）すべきだが、ここでは虚偽の root を宣言する。
    下流が meta を直接信頼してもリークしないため、登録時に検算で弾く。
    """
    gov = datagov.DataGovernor()
    A = fx.make_record("A", generation=0, gt_origin="human")
    gov.register(A)

    bad_child = fx.make_record(
        "A_c1",
        parent_lineage_id="WRONG_ROOT",  # 解決値 "A" と不一致（本来は "A"）
        parents=["A"],
        generation=1,
    )
    with pytest.raises((datagov.ValidationError, datagov.LineageError)):
        gov.register(bad_child)


def test_F001_2_nonroot_generation_checksum_mismatch_rejected():
    """F-001-2(拒否): 非 root の generation が連鎖深さと不一致は登録不可。

    改版 GT_SCHEMA「parent_lineage_id・generation の検算不一致」。
    A(gen0)→A_c1(gen1) の子は generation=1 のはずだが、虚偽の generation を宣言する。
    """
    gov = datagov.DataGovernor()
    A = fx.make_record("A", generation=0, gt_origin="human")
    gov.register(A)

    bad_child = fx.make_record(
        "A_c1",
        parent_lineage_id="A",  # ここは整合
        parents=["A"],
        generation=7,            # 連鎖深さ(=1)と不一致
    )
    with pytest.raises((datagov.ValidationError, datagov.LineageError)):
        gov.register(bad_child)


# B4. 文字列必須フィールドの空文字列の拒否（非空要求）----------------------

def test_F001_2_empty_string_state_rejected():
    """F-001-2(拒否): gt.frames[].t1.state の空文字列は登録不可（非空要求）。

    改版 GT_SCHEMA「文字列必須フィールドの空文字列（非空要求）」。
    値集合は閉じないが、空文字列は拒否（2026-06-12 監査反映、ADR 0004 決定3）。
    """
    rec = fx.make_record("ns001")
    rec["gt"]["frames"][0]["t1"]["state"] = ""  # 空文字列
    result = datagov.validate_record(rec)
    assert result.ok is False
    assert result.errors != []


def test_F001_2_empty_string_hypothesis_rejected():
    """F-001-2(拒否): gt.frames[].t3.hypothesis の空文字列は登録不可（非空要求）。"""
    rec = fx.make_record("ns001")
    rec["gt"]["frames"][0]["t3"]["hypothesis"] = ""  # 空文字列
    result = datagov.validate_record(rec)
    assert result.ok is False
    assert result.errors != []


def test_F001_2_empty_string_meta_scenario_id_rejected():
    """F-001-2(拒否): meta.scenario_id の空文字列は登録不可（非空要求）。

    空文字列の scenario_id は一意性・突合キーの基盤を壊すため拒否。
    （gt.scenario_id も同時に空にして scenario_id 不一致でなく空文字列で弾くことを確認）。
    """
    rec = fx.make_record("ns001")
    rec["meta"]["scenario_id"] = ""
    rec["gt"]["scenario_id"] = ""  # 不一致ではなく「空文字列」を理由に弾くため一致させる
    result = datagov.validate_record(rec)
    assert result.ok is False
    assert result.errors != []
