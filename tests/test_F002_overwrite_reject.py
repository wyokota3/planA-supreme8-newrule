"""F-002-2 / 不可触の機構的担保: 封印済みレコードの上書き拒否と試行の永続記録、
および SealStore.register の ts キーワード必須化。

specs/SPEC.md F-002:
  正常系「本物シナリオを封印登録し、評価フェーズ以外からのアクセスを技術的に遮断」。
  異常系「評価フェーズ外のアクセス試行を検出・記録・拒否」。
  F-002-2「封印へのアクセスは開封セッション単位で生涯1回のみ。…有効トークン外の
          読み出しは拒否・記録する」。

decisions/0010-f002-audit-fixes.md（本ファイルが固定する契約の正）:
  決定1「封印済みレコードの上書き拒否（今回修正）」:
    同一 scenario_id の再 register は SealOverwriteError で拒否し、試行を
    access_log に記録する（不可触の機構的担保。reports/audit-20260612-2238-F-002 指摘1）。
  追記「上書き試行の記録時刻」:
    - SealStore.register に keyword-only `ts` を必須追加（省略 TypeError・GUARD_IF
      運用規約4「時刻は呼び出し側供給」と一貫）。
    - 上書き試行は {"session_id": None, "ts": float(ts), "target": scenario_id} で
      access_log に記録（SealAccessRecord 契約の型どおり・session_id=None により
      audit_seal_access の突合も不合格になる tripwire）。
    - 上書き拒否は production / dummy 共通（保管不変性はモード非依存）。

specs/GUARD_IF.md SealAccessRecord 契約:
  dict {"session_id": str|None, "ts": float, "target": str}。

----------------------------------------------------------------------------
本ファイルが固定する supreme.sealset の契約（ADR 0010 決定1+追記）:

  SealStore.register(record, *, governor, ts) -> RegisterResult
    - 同一 scenario_id の2回目の register は sealset.SealOverwriteError を送出する
      （新例外。継承元はテストで固定しない＝送出のみ検証）。
    - 拒否時、封印済み本体は不変（1回目の内容のまま）。
    - 上書き試行は {"session_id": None, "ts": float(ts), "target": scenario_id} で
      access_log に記録される。
    - 異なる scenario_id の追加登録は引き続き成功する（回帰）。
    - ts はキーワード必須（既定なし・省略 TypeError）。正常登録（=1回目）では
      access_log に何も記録されない（ts は上書き試行の記録にのみ使われる）。

  例外: sealset.SealOverwriteError（封印済みレコードの上書き試行）。
"""

import pytest

import fixtures_gt as fx
from supreme import datagov
from supreme import sealset


def _store(tmp_path, *, production=False):
    """空 governor を内包し、封印を1件も持たない SealStore を返す。"""
    return sealset.SealStore(root_dir=tmp_path, production=production)


# ---------------------------------------------------------------------------
# 上書き拒否: 同一 scenario_id の2回目 register は SealOverwriteError
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("production", [False, True])
def test_F002_overwrite_same_scenario_id_rejected(tmp_path, production):
    """F-002（ADR 0010 決定1）: 同一 scenario_id の2回目 register は拒否される。

    上書き拒否はモード非依存（production / dummy 共通・保管不変性はモードに依らない）。
    """
    store = _store(tmp_path, production=production)
    store.register(fx.make_record("seal001", gt_origin="human"),
                   governor=datagov.DataGovernor(), ts=100.0)

    with pytest.raises(sealset.SealOverwriteError):
        store.register(fx.make_record("seal001", gt_origin="human"),
                       governor=datagov.DataGovernor(), ts=200.0)


# ---------------------------------------------------------------------------
# 不変性: 拒否時、封印済み本体は1回目の内容のまま（トークン経由で確認）
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("production", [False, True])
def test_F002_overwrite_rejected_body_unchanged_via_token(tmp_path, production):
    """F-002（ADR 0010 決定1）: 上書き拒否後、封印本体は1回目の内容のまま。

    1回目は description="first" を封印。上書き試行(description="SECOND")が拒否された後、
    トークン経由で read_sealed_gt して gt.description が "first" のまま（不変）を確認する。
    （dummy/production とも1回開封できる範囲で読み出して確認。production は生涯1回枠を
    本テストで1回だけ消費する。）
    """
    store = _store(tmp_path, production=production)
    first = fx.make_record("seal001", gt_origin="human", description="first")
    store.register(first, governor=datagov.DataGovernor(), ts=100.0)

    second = fx.make_record("seal001", gt_origin="human", description="SECOND")
    with pytest.raises(sealset.SealOverwriteError):
        store.register(second, governor=datagov.DataGovernor(), ts=200.0)

    tok = store.issue_open_token("S1", issued_ts=300.0, precheck_passed=True)
    gt = store.read_sealed_gt("seal001", token=tok, ts=350.0)
    assert gt["description"] == "first", "上書き拒否なのに封印本体が書き換わっている"


def test_F002_overwrite_rejected_stored_file_unchanged_on_disk(tmp_path):
    """F-002（ADR 0010 決定1・分離保管整合）: 拒否時、sealed/<sid>.json は1回目のまま。

    test_F002_schema_and_storage.py の「ディスク直読み」流儀を再利用し、トークンを
    一切消費せずに不変を確認する（dummy で root_dir/sealed/seal001.json を直接読む）。
    """
    import json

    store = _store(tmp_path, production=False)
    first = fx.make_record("seal001", gt_origin="human", description="first")
    store.register(first, governor=datagov.DataGovernor(), ts=100.0)

    sealed_path = tmp_path / "sealed" / "seal001.json"
    assert sealed_path.exists(), "1回目の封印本体が分離保管されていない"
    before = sealed_path.read_text(encoding="utf-8")

    second = fx.make_record("seal001", gt_origin="human", description="SECOND")
    with pytest.raises(sealset.SealOverwriteError):
        store.register(second, governor=datagov.DataGovernor(), ts=200.0)

    after = sealed_path.read_text(encoding="utf-8")
    assert after == before, "上書き拒否なのに sealed/<sid>.json が変化している"
    assert "SECOND" not in after, "拒否されたレコード内容がディスクに混入している"


# ---------------------------------------------------------------------------
# 試行の永続記録: 上書き試行は session_id=None / ts=float(ts) / target=sid で記録
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("production", [False, True])
def test_F002_overwrite_attempt_logged_with_none_session(tmp_path, production):
    """F-002（ADR 0010 追記）: 上書き試行は access_log に記録される。

    レコードは {"session_id": None, "ts": float(register に渡した ts),
    "target": scenario_id}。session_id=None により監査突合も不合格になる tripwire。
    正常登録（1回目）はログに何も残さないため、ログは上書き試行の1件のみ。
    """
    store = _store(tmp_path, production=production)
    store.register(fx.make_record("seal001", gt_origin="human"),
                   governor=datagov.DataGovernor(), ts=100.0)
    with pytest.raises(sealset.SealOverwriteError):
        store.register(fx.make_record("seal001", gt_origin="human"),
                       governor=datagov.DataGovernor(), ts=222.0)

    log = store.access_log()
    assert len(log) == 1, "正常登録は無記録・上書き試行のみ1件記録のはず"
    assert log[0]["session_id"] is None
    assert log[0]["ts"] == 222.0
    assert log[0]["target"] == "seal001"


def test_F002_overwrite_attempt_record_uses_register_ts_as_float(tmp_path):
    """F-002（ADR 0010 追記・型）: 記録 ts は register に渡した値の float。

    GUARD_IF SealAccessRecord 契約「ts は float」。register に int 等を渡しても
    記録は float(ts) になる（契約どおりの型）。
    """
    store = _store(tmp_path, production=False)
    store.register(fx.make_record("seal001", gt_origin="human"),
                   governor=datagov.DataGovernor(), ts=10.0)
    with pytest.raises(sealset.SealOverwriteError):
        store.register(fx.make_record("seal001", gt_origin="human"),
                       governor=datagov.DataGovernor(), ts=777)  # int

    rec = store.access_log()[0]
    assert rec["ts"] == 777.0
    assert isinstance(rec["ts"], float)


def test_F002_overwrite_attempt_persisted_across_instances(tmp_path):
    """F-002（ADR 0010 追記・永続）: 上書き試行の記録は別インスタンスから読み戻せる。

    test_F002_access_log.py の「新インスタンス読み戻し」流儀を再利用。プロセス再起動
    相当の新 SealStore が同一 root_dir の access_log.jsonl から試行記録を読める。
    """
    store = _store(tmp_path, production=False)
    store.register(fx.make_record("seal001", gt_origin="human"),
                   governor=datagov.DataGovernor(), ts=100.0)
    with pytest.raises(sealset.SealOverwriteError):
        store.register(fx.make_record("seal001", gt_origin="human"),
                       governor=datagov.DataGovernor(), ts=222.0)

    store2 = sealset.SealStore(root_dir=tmp_path, production=False)
    log2 = store2.access_log()
    assert any(
        r["session_id"] is None and r["ts"] == 222.0 and r["target"] == "seal001"
        for r in log2
    ), "上書き試行の記録が永続化されていない"


# ---------------------------------------------------------------------------
# 回帰: 異なる scenario_id の追加登録は引き続き成功する
# ---------------------------------------------------------------------------

def test_F002_overwrite_different_scenario_id_still_succeeds(tmp_path):
    """F-002（ADR 0010 決定1・回帰）: 異なる scenario_id の追加登録は成功する。

    上書き拒否が「同一 scenario_id のみ」を対象とし、別 scenario の正常な追加登録を
    巻き込まないことを固定する（拒否が常時化していない対照）。
    """
    store = _store(tmp_path, production=False)
    store.register(fx.make_record("seal001", gt_origin="human"),
                   governor=datagov.DataGovernor(), ts=100.0)
    # 別 scenario_id は成功する。
    result = store.register(fx.make_record("seal002", gt_origin="human"),
                            governor=datagov.DataGovernor(), ts=110.0)
    assert result.scenario_id == "seal002"
    assert store.stored_meta("seal002")["scenario_id"] == "seal002"


def test_F002_overwrite_normal_register_logs_nothing(tmp_path):
    """F-002（ADR 0010 追記・対照）: 正常登録のみでは access_log に何も記録されない。

    現行のログ契約（開封アクセス成功/拒否＋上書き試行のみ）を固定。ts を渡しても
    正常登録ではログに残らない（ts は上書き試行の記録にのみ使われる）。
    """
    store = _store(tmp_path, production=False)
    store.register(fx.make_record("seal001", gt_origin="human"),
                   governor=datagov.DataGovernor(), ts=100.0)
    store.register(fx.make_record("seal002", gt_origin="human"),
                   governor=datagov.DataGovernor(), ts=110.0)
    assert store.access_log() == [], "正常登録は access_log に何も残さない契約"


# ---------------------------------------------------------------------------
# ts キーワード必須化（ADR 0010 追記）: 省略は TypeError
# ---------------------------------------------------------------------------

def test_F002_register_requires_keyword_ts(tmp_path):
    """F-002（ADR 0010 追記・陰性）: ts を省略した SealStore.register は TypeError。

    ts は keyword-only・既定なし。GUARD_IF 運用規約4「時刻は呼び出し側供給」と一貫し、
    上書き試行の記録時刻の暗黙既定（=fail-open 的な無記録/誤記録）を構造的に排除する。
    """
    store = _store(tmp_path, production=False)
    with pytest.raises(TypeError):
        store.register(fx.make_record("seal001", gt_origin="human"),
                       governor=datagov.DataGovernor())
