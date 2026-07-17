"""F-013 / 監査残存指摘 R2: run_sealed_evaluation の「開封前 fail-closed 窓内不変条件検証」。

対応指摘: R2（reports/audit-20260614-1526-F-013.md・指摘2 / decisions/0023-...md 申し送り R2）
----------------------------------------------------------------------------
背景（R2）:
  run_sealed_evaluation は封印 read の ts を issued_ts から scenario ごとに +1.0 で割り当てる
  （read_ts = issued_ts; for sid: read; read_ts += 1.0）。全 read が窓 [issued_ts, revoked_ts)
  （半開区間・GUARD_IF §1/§3）内であるには
        issued_ts + (len(scenario_ids) - 1) < revoked_ts
  が必要。現状この不変条件を**開封前に検証していない**ため、窓が狭い／scenario が多い構成では
  open_eval_session で**封印を1回開封して枠を焼いた後**に窓外 read で AccessDenied 中断しうる。
  封印は本番1回開封（GUARD_IF §3 運用規約1・2）なので、開封枠を消費した上での中断は痛い。

追加する契約（fail-closed＝開封前停止）:
  run_sealed_evaluation は**開封（open_eval_session 呼び出し）より前に**窓内不変条件を検証し、
  満たさないとき新例外 sealeval.EvalWindowTooNarrow（Exception サブクラス）を送出する。
  **開封前に停止するので封印枠を消費しない**（lifetime_session_count() は 0 のまま・
  session_state.json も不変）。

検証する条件（半開区間 [issued_ts, revoked_ts)・GUARD_IF §1）:
  - last read ts = issued_ts + (N - 1)。これが < revoked_ts なら成立、>= revoked_ts なら窓外。
  - N=1 のときは issued_ts < revoked_ts（窓が空でなければ成立）。

規律（指示・ADR 0023 決定6 / TEST_STRATEGY 穴2）:
  - stdlib のみ・決定的。時刻 issued_ts/revoked_ts/ts はテストが引数で供給する。
  - 本番封印は開けない。production=False のダミー封印（fixtures_sealeval）でドライランする。
  - 既存 test_F013_single_session.py（widewindow 構成）は変更しない。本ファイルは
    自前の薄いラッパ（_run）を持つ。
"""

import pytest

import fixtures_sealeval as fxs
from supreme import datagov
from supreme import guard
from supreme import sealset


def _import_sealeval():
    from supreme import sealeval

    return sealeval


# ---------------------------------------------------------------------------
# 共有ヘルパ: ダミー封印 2 件（SEAL_P / SEAL_Q）を登録した production=False の SealStore。
# 合格 aggregate（開封が通る前提）。test_F013_single_session.py の流儀を本ファイルに自前複製。
# ---------------------------------------------------------------------------

def _store_with_dummy_seals(tmp_path):
    """ダミー封印 SEAL_P / SEAL_Q を登録した production=False の SealStore。"""
    store = sealset.SealStore(root_dir=tmp_path, production=False)
    gov = datagov.DataGovernor()
    for rec in fxs.sealed_records_two_scenarios():
        store.register(rec, governor=gov, ts=0.0)
    return store


def _passing_aggregate():
    """全ガード合格の AggregateResult（開封が通る前提）。"""
    g1 = guard.check_param_budget(param_count=19, data_count=200, k=0.5)
    return guard.combine_guards([g1])


def _run(tmp_path, *, store=None, scenario_ids=("SEAL_P", "SEAL_Q"),
         scenario_inputs=None, session_id="EVAL-1",
         issued_ts=100.0, revoked_ts=300.0):
    """run_sealed_evaluation をダミー封印でドライランする薄いラッパ。

    scenario_ids / issued_ts / revoked_ts を可変にし、窓内不変条件の境界を直接突く。
    scenario_inputs を省略すると、scenario_ids に合わせた決定的入力を組み立てる。
    """
    sealeval = _import_sealeval()
    store = store or _store_with_dummy_seals(tmp_path)
    sids = list(scenario_ids)
    if scenario_inputs is None:
        all_inputs = fxs.seal_scenario_inputs_two()
        scenario_inputs = {sid: all_inputs[sid] for sid in sids}
    return store, sealeval.run_sealed_evaluation(
        store,
        _passing_aggregate(),
        fxs.baseline_scores_canonical(),
        scenario_ids=sids,
        scenario_inputs=scenario_inputs,
        session_id=session_id,
        issued_ts=issued_ts,
        revoked_ts=revoked_ts,
        weak_items=fxs.WEAK_ITEMS,
        strong_items=fxs.STRONG_ITEMS,
        delta_strong=fxs.DELTA_STRONG,
    )


# ===========================================================================
# 1. 例外クラスの存在
# ===========================================================================

def test_F013_R2_eval_window_too_narrow_is_public_exception_subclass():
    """R2（例外クラスの存在）: sealeval.EvalWindowTooNarrow が公開され Exception サブクラス。

    開封前 fail-closed 検証で送出する新例外。AccessDenied（開封後の窓外 read）とは別物で、
    「開封する前に止めた」ことを型で表す。
    """
    sealeval = _import_sealeval()
    assert hasattr(sealeval, "EvalWindowTooNarrow"), (
        "sealeval が EvalWindowTooNarrow を公開していない"
    )
    assert isinstance(sealeval.EvalWindowTooNarrow, type)
    assert issubclass(sealeval.EvalWindowTooNarrow, Exception), (
        "EvalWindowTooNarrow は Exception のサブクラスであるべき"
    )


# ===========================================================================
# 2. 窓が狭いと開封前停止（核心）
# ===========================================================================

def test_F013_R2_raises_when_window_too_narrow(tmp_path):
    """R2（窓が狭いと停止・核心）: 2 scenario で issued_ts + (N-1) >= revoked_ts の構成なら
    run_sealed_evaluation は EvalWindowTooNarrow を送出する。

    N=2・issued_ts=100.0・revoked_ts=100.5 → last read ts = 100.0 + 1 = 101.0 >= 100.5（窓外）。
    現状は開封枠を焼いた後の窓外 read で AccessDenied 中断しうるところを、開封前停止に倒す。
    """
    sealeval = _import_sealeval()
    with pytest.raises(sealeval.EvalWindowTooNarrow):
        _run(tmp_path, scenario_ids=("SEAL_P", "SEAL_Q"),
             issued_ts=100.0, revoked_ts=100.5)


# ===========================================================================
# 3. 枠不消費（核心）: 開封前停止なので封印を焼いていない
# ===========================================================================

def test_F013_R2_narrow_window_does_not_consume_quota(tmp_path):
    """R2（枠不消費・核心）: EvalWindowTooNarrow 送出後、生涯開封セッション数は 0 のまま。

    開封（open_eval_session）より前に止めるので、封印の生涯1回の枠を消費しない
    （GUARD_IF §3 運用規約1・2）。同一 store インスタンスで lifetime_session_count() == 0。
    """
    sealeval = _import_sealeval()
    store = _store_with_dummy_seals(tmp_path)
    with pytest.raises(sealeval.EvalWindowTooNarrow):
        _run(tmp_path, store=store, scenario_ids=("SEAL_P", "SEAL_Q"),
             issued_ts=100.0, revoked_ts=100.5)
    assert store.lifetime_session_count() == 0, (
        "窓が狭い構成で開封枠を消費している（開封前に止まっていない）"
    )


def test_F013_R2_narrow_window_does_not_persist_session_state(tmp_path):
    """R2（session_state 不変・プロセス跨ぎ＝開封前停止の証拠）: EvalWindowTooNarrow 送出後、
    同一 root_dir の新インスタンスでも生涯計数 0。

    開封前に止めたなら session_state.json は進んでいないはず。新インスタンスは状態ファイルから
    復元する（GUARD_IF §3 運用規約2）ので、ここが 0 なら「開封枠を永続化していない」＝
    開封より前に停止したことの強い証拠になる。
    """
    sealeval = _import_sealeval()
    store = _store_with_dummy_seals(tmp_path)
    with pytest.raises(sealeval.EvalWindowTooNarrow):
        _run(tmp_path, store=store, scenario_ids=("SEAL_P", "SEAL_Q"),
             issued_ts=100.0, revoked_ts=100.5)
    # プロセス再起動相当: 同一 root_dir の新インスタンス。
    store2 = sealset.SealStore(root_dir=tmp_path, production=False)
    assert store2.lifetime_session_count() == 0, (
        "窓が狭い構成で session_state.json を進めている（開封前に止まっていない）"
    )


# ===========================================================================
# 4. 境界（半開区間 [issued_ts, revoked_ts) を固定）
# ===========================================================================

def test_F013_R2_boundary_last_read_strictly_inside_window_passes(tmp_path):
    """R2（境界・ぎりぎり成立は通る）: 2 scenario・issued_ts=100.0・revoked_ts=101.5 なら
    停止せず正常完走し、生涯開封セッション数が 1。

    last read ts = 100.0 + 1 = 101.0 < 101.5（半開区間で窓内）。不変条件成立なので開封して
    完走するべき（fail-closed が genuine に成立する構成を誤って潰さない）。
    """
    store, report = _run(tmp_path, scenario_ids=("SEAL_P", "SEAL_Q"),
                         issued_ts=100.0, revoked_ts=101.5)
    assert store.lifetime_session_count() == 1, (
        "成立する窓で開封・完走していない（過剰に停止している疑い）"
    )
    assert report.lifetime_session_count == 1


def test_F013_R2_boundary_last_read_equals_revoked_is_outside_window(tmp_path):
    """R2（境界・半開区間の上端は窓外）: 2 scenario・issued_ts=100.0・revoked_ts=101.0 なら
    EvalWindowTooNarrow を送出する。

    last read ts = 100.0 + 1 = 101.0。窓 [100.0, 101.0) は半開区間（ts==revoked_ts は窓外・
    GUARD_IF §1 / §3 運用規約2）なので、ちょうど上端に重なる read は窓外＝不変条件不成立。
    境界を「< revoked_ts」（厳密）に固定する。
    """
    sealeval = _import_sealeval()
    with pytest.raises(sealeval.EvalWindowTooNarrow):
        _run(tmp_path, scenario_ids=("SEAL_P", "SEAL_Q"),
             issued_ts=100.0, revoked_ts=101.0)


# ===========================================================================
# 5. 単一 scenario（N=1 のとき条件は issued_ts < revoked_ts）
# ===========================================================================

def test_F013_R2_single_scenario_zero_width_window_raises(tmp_path):
    """R2（N=1・窓ゼロ）: 単一 scenario で issued_ts=100.0・revoked_ts=100.0 なら
    EvalWindowTooNarrow を送出する。

    N=1 のとき last read ts = issued_ts = 100.0。窓 [100.0, 100.0) は半開区間で空集合（窓ゼロ）
    なので、唯一の read すら窓外。条件は issued_ts < revoked_ts（厳密）。
    """
    sealeval = _import_sealeval()
    with pytest.raises(sealeval.EvalWindowTooNarrow):
        _run(tmp_path, scenario_ids=("SEAL_P",),
             issued_ts=100.0, revoked_ts=100.0)


def test_F013_R2_single_scenario_nonzero_window_passes(tmp_path):
    """R2（N=1・正常）: 単一 scenario で issued_ts=100.0・revoked_ts=100.5 なら
    停止せず正常完走し、生涯開封セッション数が 1。

    N=1 のとき last read ts = issued_ts = 100.0 < 100.5（窓内）。issued_ts < revoked_ts を
    満たすので開封して完走するべき。N=1 で過剰停止しないことを固定する。
    """
    store, report = _run(tmp_path, scenario_ids=("SEAL_P",),
                         issued_ts=100.0, revoked_ts=100.5)
    assert store.lifetime_session_count() == 1, (
        "成立する窓（N=1）で開封・完走していない（過剰に停止している疑い）"
    )
    assert report.lifetime_session_count == 1
