"""F-002 異常系: 評価フェーズ外アクセスの検出・記録・拒否 / ログファイル破損の検出。

specs/SPEC.md F-002 異常系:
  「評価フェーズ外のアクセス試行を検出・記録・拒否。」
specs/GUARD_IF.md:
  「評価フェーズ」＝有効な開封トークンの期間（半開区間 [issued_ts, revoked_ts)）。
  この期間外のアクセスは「評価フェーズ外アクセス」。
decisions/0009-f002-sealset-policies.md:
  永続 JSONL ログに全アクセス試行（拒否含む）を記録。
TEST_STRATEGY.md 穴8:
  ログを介さないファイル直読みは既知限界（暗号化は採らない）。本テストはログ経由の
  検出・記録・拒否の機構を対象とする。

ログ破損の検出は SPEC の異常系規律「黙って無視しない」の延長として置く
（破損したログを正常として読み飛ばすと監査の根拠が崩れるため、検出して例外化する）。

----------------------------------------------------------------------------
このファイルが定義する supreme.sealset の前提 API（テスト駆動・report に明記）:

  SealStore.read_sealed_gt(scenario_id, *, token, ts)
    評価フェーズ外（トークン無し/失効後/窓外 ts）のアクセスは sealset.AccessDenied で
    拒否し、access_log に session_id=None で記録する。

  SealStore.access_log() -> list[dict]
    root_dir/access_log.jsonl を読み戻す。**不正 JSON 行（破損）を検出したら
    sealset.LogCorruptionError を送出する（黙って読み飛ばさない）。**

  例外:
    sealset.AccessDenied        評価フェーズ外アクセス（拒否）。
    sealset.LogCorruptionError  永続ログの破損（不正 JSON 行）を検出。
"""

import json

import pytest

import fixtures_gt as fx
from supreme import datagov
from supreme import sealset


def _store(tmp_path, *, production=False):
    # register の ts は ADR 0010 追記でキーワード必須。正常登録は access_log に
    # 記録しないため、本ファイルの拒否記録アサーションは ts 追加後も不変。
    store = sealset.SealStore(root_dir=tmp_path, production=production)
    store.register(fx.make_record("seal001", gt_origin="human"),
                   governor=datagov.DataGovernor(), ts=0.0)
    return store


# ---------------------------------------------------------------------------
# 評価フェーズ外アクセス試行の検出・記録・拒否
# ---------------------------------------------------------------------------

def test_F002_abnormal_access_without_phase_detected_and_recorded(tmp_path):
    """F-002（異常系）: 評価フェーズ外（トークン未発行）のアクセスを検出・拒否・記録。

    一切トークンを発行していない状態（評価フェーズに入っていない）でのアクセスは
    AccessDenied で拒否され、session_id=None で永続ログに記録される。
    """
    store = _store(tmp_path)
    with pytest.raises(sealset.AccessDenied):
        store.read_sealed_gt("seal001", token=None, ts=100.0)

    log = store.access_log()
    assert len(log) == 1
    assert log[0]["session_id"] is None
    assert log[0]["target"] == "seal001"


def test_F002_abnormal_access_after_phase_ended_recorded(tmp_path):
    """F-002（異常系）: 評価フェーズ終了後（失効後）のアクセスを検出・拒否・記録。"""
    store = _store(tmp_path)
    tok = store.issue_open_token("S1", issued_ts=100.0, precheck_passed=True)
    store.revoke_open_token(tok, revoked_ts=200.0)  # 評価フェーズ終了

    with pytest.raises(sealset.AccessDenied):
        store.read_sealed_gt("seal001", token=tok, ts=250.0)

    log = store.access_log()
    assert log[-1]["session_id"] is None
    assert log[-1]["ts"] == 250.0


def test_F002_abnormal_denied_access_persisted_for_audit(tmp_path):
    """F-002（異常系）: 拒否アクセスが永続ログに残り、別インスタンスから監査できる。

    フェーズ外アクセスの「記録」が再起動後も失われないこと（事後監査の根拠）。
    """
    store = _store(tmp_path)
    with pytest.raises(sealset.AccessDenied):
        store.read_sealed_gt("seal001", token=None, ts=100.0)

    store2 = sealset.SealStore(root_dir=tmp_path, production=False)
    log2 = store2.access_log()
    assert any(r["session_id"] is None and r["ts"] == 100.0 for r in log2), (
        "フェーズ外アクセスの記録が永続化されていない"
    )


# ---------------------------------------------------------------------------
# ログファイル破損（不正 JSON 行）の検出（黙って無視しない）
# ---------------------------------------------------------------------------

def test_F002_abnormal_corrupt_log_line_detected(tmp_path):
    """F-002（異常系）: 永続ログに不正 JSON 行があると LogCorruptionError で検出。

    破損行を黙って読み飛ばすと監査の根拠（全アクセス履歴）が崩れるため、
    検出して例外化する（黙って無視しない）。
    """
    store = _store(tmp_path)
    tok = store.issue_open_token("S1", issued_ts=100.0, precheck_passed=True)
    store.read_sealed_gt("seal001", token=tok, ts=150.0)

    # 永続ログに不正 JSON 行を直接追記して破損させる。
    log_path = tmp_path / "access_log.jsonl"
    with log_path.open("a", encoding="utf-8") as f:
        f.write("THIS IS NOT JSON{{{\n")

    store2 = sealset.SealStore(root_dir=tmp_path, production=False)
    with pytest.raises(sealset.LogCorruptionError):
        store2.access_log()


def test_F002_abnormal_corrupt_log_missing_field_detected(tmp_path):
    """F-002（異常系）: SealAccessRecord の必須フィールド欠落行も破損として検出。

    JSON としては妥当でも SealAccessRecord 契約（session_id/ts/target）を満たさない
    行は破損扱い（黙って無視しない）。
    """
    store = _store(tmp_path)
    tok = store.issue_open_token("S1", issued_ts=100.0, precheck_passed=True)
    store.read_sealed_gt("seal001", token=tok, ts=150.0)

    log_path = tmp_path / "access_log.jsonl"
    with log_path.open("a", encoding="utf-8") as f:
        # ts と target を欠く（契約違反）。
        f.write(json.dumps({"session_id": "S1"}) + "\n")

    store2 = sealset.SealStore(root_dir=tmp_path, production=False)
    with pytest.raises(sealset.LogCorruptionError):
        store2.access_log()


def test_F002_abnormal_intact_log_reads_back_clean(tmp_path):
    """F-002（異常系・対照）: 破損していない正常なログは例外なく読み戻せる。

    破損検出が「常に例外」ではなく、健全なログは通すことを担保する。
    """
    store = _store(tmp_path)
    tok = store.issue_open_token("S1", issued_ts=100.0, precheck_passed=True)
    store.read_sealed_gt("seal001", token=tok, ts=150.0)
    with pytest.raises(sealset.AccessDenied):
        store.read_sealed_gt("seal001", token=None, ts=160.0)

    store2 = sealset.SealStore(root_dir=tmp_path, production=False)
    log2 = store2.access_log()  # 例外が出ないこと
    assert len(log2) == 2
