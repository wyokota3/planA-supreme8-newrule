"""Phase 1b 封印評価への学習 params 配線(ADR 0025 P1-R4)— run_sealed_evaluation が
学習済み params を core へ通す契約。**実装は読まず・書かず**、既存テスト不変。

背景(ADR 0025 / 追記 P1-R4・Phase1b):
  Phase1 で `core.fit_supreme(練習)->SupremeParams` / `core.run_supreme(snaps, params=)` を
  配線したが、`sealeval.run_sealed_evaluation` は内部で `core.run_supreme(snaps, config=config)`
  (params 省略=既定=未学習)で動いている(監査 P1-R4)。封印 verdict に学習を効かせるには、
  `run_sealed_evaluation` に `params=None` を追加して core へ通す。方法論: **学習は練習データで
  (fit_supreme)、封印は評価専用**(seal は触らず、trained params で実走)。

追加する契約(本ファイルが固定):
  sealeval.run_sealed_evaluation(
      seal_store, aggregate, baseline_scores, *,
      scenario_ids, scenario_inputs, session_id, issued_ts, revoked_ts,
      weak_items, strong_items, delta_strong, config=None, params=None) -> SealEvalReport
  - **params=None は現状の挙動を一切変えない(後方互換・最重要)**。既存
    tests/test_F013_single_session.py の 8 件が壊れない。
  - params=SupremeParams(core.fit_supreme の返り値)のとき、内部の core.run_supreme に
    その params を渡して学習済みで supreme を実走する(封印開封・単一セッション・revoke 等の
    F-013 機構は不変)。

観点 ↔ テスト関数の対応:
  1. 後方互換(最重要):
       - test_Phase1b_params_keyword_accepted (params キーワード受理)
       - test_Phase1b_params_none_equals_omitted_comparison_verdicts
       - test_Phase1b_params_none_equals_omitted_lifetime_and_audit
       - test_Phase1b_params_none_equals_omitted_session_and_token_window
  2. params 注入で学習済み実走(例外なく完走・単一開封・audit・8 項目 verdict):
       - test_Phase1b_trained_params_run_completes_lifetime_one
       - test_Phase1b_trained_params_audit_passed
       - test_Phase1b_trained_params_verdicts_cover_all_eight_items
  3. 学習が supreme 採点に効く経路であること(core.run_supreme に params が渡る・完全一致非強制):
       - test_Phase1b_trained_params_reach_core_run_supreme
       - test_Phase1b_default_params_none_reaches_core_as_none
  封印保全(params 注入でも維持・access_log/lifetime で機械検証):
       - test_Phase1b_trained_params_read_after_revoke_is_access_denied
       - test_Phase1b_trained_params_all_reads_single_session_within_window
       - test_Phase1b_trained_params_no_denied_access_records

前提 API(test_F013_single_session.py が定義する SealEvalReport の面・本ファイルは不変):
  .comparison / .session_id / .lifetime_session_count / .audit_passed / .token

規律(指示):
  - stdlib のみ・決定的・時刻は引数供給(issued_ts/revoked_ts)。production=False のダミー封印(穴2)。
  - 既存テスト不変。実データ非依存(合成 fixture)。実装不在/params 未対応の間は red(TDD 期待)。
  - 観点3 は「core.run_supreme に params が渡った」ことを公開シンボルの wrap で観測する
    (SealEvalReport は supreme 生スコアの露出を約束しないため・完全一致は強制しない)。
"""

import pytest

import fixtures_pso as fxp
import fixtures_sealeval as fxs
from supreme import datagov
from supreme import guard
from supreme import sealset


def _import_sealeval():
    """supreme.sealeval を import(実装/契約不在なら ImportError/TypeError で red=TDD 期待)。"""
    from supreme import sealeval

    return sealeval


def _import_core():
    from supreme import core

    return core


# ---------------------------------------------------------------------------
# 共有ヘルパ: ダミー封印 2 件(production=False)＋ 合格 aggregate(test_F013 と同流儀)
# ---------------------------------------------------------------------------

def _store_with_dummy_seals(tmp_path):
    """ダミー封印 SEAL_P / SEAL_Q を登録した production=False の SealStore(穴2)。"""
    store = sealset.SealStore(root_dir=tmp_path, production=False)
    gov = datagov.DataGovernor()
    for rec in fxs.sealed_records_two_scenarios():
        store.register(rec, governor=gov, ts=0.0)
    return store


def _passing_aggregate():
    """全ガード合格の AggregateResult(開封が通る前提・test_F014/F013 の流儀)。"""
    g1 = guard.check_param_budget(param_count=19, data_count=200, k=0.5)
    return guard.combine_guards([g1])


def _run(tmp_path, *, params, store=None, aggregate=None, baseline=None,
         session_id="EVAL-1", issued_ts=100.0, revoked_ts=300.0):
    """run_sealed_evaluation をダミー封印・2 シナリオでドライランする薄いラッパ。

    test_F013_single_session._run と同一の引数構成に params=... を1つ加えただけ
    (後方互換の比較が成り立つよう、他の供給は完全に同一に保つ)。
    """
    sealeval = _import_sealeval()
    store = store or _store_with_dummy_seals(tmp_path)
    aggregate = aggregate or _passing_aggregate()
    baseline = baseline if baseline is not None else fxs.baseline_scores_canonical()
    return store, sealeval.run_sealed_evaluation(
        store,
        aggregate,
        baseline,
        scenario_ids=["SEAL_P", "SEAL_Q"],
        scenario_inputs=fxs.seal_scenario_inputs_two(),
        session_id=session_id,
        issued_ts=issued_ts,
        revoked_ts=revoked_ts,
        weak_items=fxs.WEAK_ITEMS,
        strong_items=fxs.STRONG_ITEMS,
        delta_strong=fxs.DELTA_STRONG,
        params=params,
    )


def _run_without_params_kw(tmp_path, *, session_id="EVAL-1",
                           issued_ts=100.0, revoked_ts=300.0):
    """params キーワードを**一切渡さない**(省略)ドライラン。

    後方互換の基準値: 「params 省略時」と「params=None」が同一であることを比較するため、
    params キーワードを構文上も渡さない呼び出し(=既存 test_F013_single_session._run 相当)。
    """
    sealeval = _import_sealeval()
    store = _store_with_dummy_seals(tmp_path)
    return store, sealeval.run_sealed_evaluation(
        store,
        _passing_aggregate(),
        fxs.baseline_scores_canonical(),
        scenario_ids=["SEAL_P", "SEAL_Q"],
        scenario_inputs=fxs.seal_scenario_inputs_two(),
        session_id=session_id,
        issued_ts=issued_ts,
        revoked_ts=revoked_ts,
        weak_items=fxs.WEAK_ITEMS,
        strong_items=fxs.STRONG_ITEMS,
        delta_strong=fxs.DELTA_STRONG,
    )


# ---------------------------------------------------------------------------
# 合成練習データ → fit_supreme(test_Phase1_learning_wiring と同方針・小さな合成)
#
# scene/t3 のラベルが明確に分かれる 4 系統で fit_supreme を呼び、学習済み
# SupremeParams を得る。GT の正しさ(穴5)は対象外・学習信号として機能すればよい。
# ---------------------------------------------------------------------------

def _practice_scenarios():
    """合成練習シナリオ {scenario_id: pso_snapshots}(決定的・実データ非依存)。"""
    return {
        "sc_stable": [fxp.frame_benign(ts=float(i)) for i in range(6)],
        "sc_degrading": (
            [fxp.frame_benign(ts=float(i)) for i in range(3)]
            + [fxp.frame_low_qos(ts=float(3 + i), qos=0.08, latency_ms=185.0)
               for i in range(3)]
        ),
        "sc_conversation": [
            fxp.frame_conversation(ts=float(i), r_m=2.0, speaking_prob=0.95)
            for i in range(6)
        ],
        "sc_alert": [
            fxp.frame_siren(ts=float(i), r_m=25.0, min_TTC_s=1.5) for i in range(6)
        ],
    }


def _merged_gt(scenarios):
    """scene_regime と t3_hypothesis を 1 つの gt view に統合した {sid: [view,...]}。

    fit_supreme は t3/scene を学習するため、両層の GT を同じ gt view に載せて渡す
    (test_Phase1_learning_wiring._merged_gt と同方針)。
    """
    scene_labels = {
        "sc_stable": "STABLE", "sc_degrading": "DEGRADING",
        "sc_conversation": "STABLE", "sc_alert": "CHANGING",
    }
    t3_labels = {
        "sc_stable": "quiet_stable", "sc_degrading": "env_shift",
        "sc_conversation": "conv_participating", "sc_alert": "alert_required",
    }
    merged = {}
    for sid, snaps in scenarios.items():
        merged[sid] = [
            {"scene_regime": scene_labels[sid], "t3_hypothesis": t3_labels[sid]}
            for _ in snaps
        ]
    return merged


def _trained_params():
    """小さな合成練習で fit した SupremeParams(core.fit_supreme の返り値)。"""
    core = _import_core()
    scenarios = _practice_scenarios()
    return core.fit_supreme(scenarios, _merged_gt(scenarios))


# ===========================================================================
# 観点1: 後方互換(最重要)— params キーワード受理 / params=None が省略時と同一
# ===========================================================================

def test_Phase1b_params_keyword_accepted(tmp_path):
    """観点1 後方互換(ADR 0025 P1-R4・契約面): run_sealed_evaluation が params キーワードを
    受理する(params=None で例外なく完走する)。

    Phase1b で追加する `params=None` シグネチャ自体を固定する。未対応(TypeError: unexpected
    keyword argument 'params')の間は red(TDD 期待)。
    """
    store, report = _run(tmp_path, params=None)
    assert report is not None
    # 既定面が壊れていない(後方互換の最低限)。
    assert report.lifetime_session_count == 1
    assert report.audit_passed is True


def test_Phase1b_params_none_equals_omitted_comparison_verdicts(tmp_path):
    """観点1 後方互換(最重要): params=None の comparison.verdicts が params 省略時と完全一致する。

    ADR 0025 決定4「params=None 既定で既存挙動を一切変えない」を封印評価経路で固定する。
    既存 test_F013_single_session の 8 件(comparison 同梱・項目別 verdict)が壊れないことを、
    省略呼び出し(params キーワードを構文上も渡さない)との verdicts 一致で機械検証する。
    封印・aggregate・baseline・scenario 入力・時刻は完全に同一供給。
    """
    _store_omit, rep_omit = _run_without_params_kw(tmp_path / "omit")
    _store_none, rep_none = _run(tmp_path / "none", params=None)
    assert rep_none.comparison.verdicts == rep_omit.comparison.verdicts, (
        "params=None の comparison.verdicts が params 省略時と一致しない"
        "(params=None が既定挙動を変えている=後方互換違反)"
    )


def test_Phase1b_params_none_equals_omitted_lifetime_and_audit(tmp_path):
    """観点1 後方互換(最重要): params=None の lifetime_session_count / audit_passed が
    params 省略時と完全一致する(共に 1 / True)。

    封印保全(単一開封・audit 合格)が params=None の追加で一切揺れないことを固定する。
    """
    _store_omit, rep_omit = _run_without_params_kw(tmp_path / "omit")
    _store_none, rep_none = _run(tmp_path / "none", params=None)
    assert rep_none.lifetime_session_count == rep_omit.lifetime_session_count == 1
    assert rep_none.audit_passed == rep_omit.audit_passed is True


def test_Phase1b_params_none_equals_omitted_session_and_token_window(tmp_path):
    """観点1 後方互換(最重要): params=None の session_id と発行トークンの開封窓
    [issued_ts, revoked_ts) が params 省略時と一致し、失効済みである。

    封印機構(単一トークン・窓・失効)が params=None で不変であることを、report.session_id と
    report.token の面で固定する(F-013 の単一開封セッション識別が崩れない)。
    """
    _store_omit, rep_omit = _run_without_params_kw(tmp_path / "omit")
    _store_none, rep_none = _run(tmp_path / "none", params=None)
    assert rep_none.session_id == rep_omit.session_id == "EVAL-1"
    # 発行トークンの session_id も一致(単一開封セッションの識別子が不変)。
    assert rep_none.token.session_id == rep_omit.token.session_id == "EVAL-1"
    # 実行後はいずれも失効済み(revoke されている)。
    assert rep_none.token.active is False
    assert rep_omit.token.active is False


# ===========================================================================
# 観点2: params 注入で学習済み実走 — 例外なく完走・単一開封・audit・8 項目 verdict
# ===========================================================================

def test_Phase1b_trained_params_run_completes_lifetime_one(tmp_path):
    """観点2 学習済み実走(ADR 0025 P1-R4・核心): params=fit_supreme(練習) を渡して
    run_sealed_evaluation が例外なく完走し、生涯開封セッション数が 1。

    学習 params の注入で封印開封・単一セッションの機構が壊れないこと(封印は params で
    開封挙動を変えない=評価専用)を固定する。store 側計数とも突合する。
    """
    params = _trained_params()
    store, report = _run(tmp_path, params=params)
    assert report.lifetime_session_count == 1, (
        f"学習 params 注入で単一開封が崩れた: {report.lifetime_session_count}"
    )
    assert store.lifetime_session_count() == 1


def test_Phase1b_trained_params_audit_passed(tmp_path):
    """観点2 学習済み実走(封印保全): params 注入時も guard.audit_seal_access が合格する
    (report.audit_passed is True)。

    封印開封(単一トークン・窓内 read)の監査が学習 params で揺れないことを固定する。
    """
    params = _trained_params()
    store, report = _run(tmp_path, params=params)
    assert report.audit_passed is True, (
        "学習 params 注入で audit_seal_access が合格しない(封印アクセスの規律が崩れた疑い)"
    )


def test_Phase1b_trained_params_verdicts_cover_all_eight_items(tmp_path):
    """観点2 学習済み実走(報告同梱): params 注入時も comparison が弱5+強3 の全 8 項目の
    verdict を報告する(F-013-2 機構不変)。

    学習が supreme スコアを変えても、項目別対比(comparison)の報告面が壊れないことを固定する。
    """
    params = _trained_params()
    store, report = _run(tmp_path, params=params)
    for it in fxs.WEAK_ITEMS + fxs.STRONG_ITEMS:
        assert it in report.comparison.verdicts, (
            f"学習 params 注入の報告に項目 {it} の verdict が無い"
        )
    assert report.session_id == "EVAL-1"


# ===========================================================================
# 観点3: 学習が supreme 採点に効く経路であること(core.run_supreme に params が渡る)
#        完全一致は強制しない。「params が core へ届く」ことを公開 wrap で観測する。
# ===========================================================================

def test_Phase1b_trained_params_reach_core_run_supreme(tmp_path, monkeypatch):
    """観点3 学習経路(ADR 0025 P1-R4・核心): run_sealed_evaluation に params=学習済みを渡すと、
    内部の core.run_supreme(...) に**その params が渡る**(=学習が supreme 採点に効く経路)。

    SealEvalReport は supreme 生スコアの露出を約束しないため(完全一致は強制しない・学習で
    変わらない封印/入力なら同じこともある)、本契約は「params が core へ届く」ことを公開
    シンボル core.run_supreme の wrap で機械検証する。run_sealed_evaluation が core.run_supreme を
    params 省略(=既定=未学習)で呼んでいる現状(監査 P1-R4)では、渡る params が None になり red。
    """
    core = _import_core()
    params = _trained_params()

    seen_params = []
    real_run_supreme = core.run_supreme

    def _spy_run_supreme(snaps, *args, **kwargs):
        # 位置/キーワードどちらで渡されても params を捕捉する(裁量実装に両対応)。
        if "params" in kwargs:
            seen_params.append(kwargs["params"])
        elif args:
            seen_params.append(args[0])
        else:
            seen_params.append(None)
        return real_run_supreme(snaps, *args, **kwargs)

    monkeypatch.setattr(core, "run_supreme", _spy_run_supreme)

    _store, _report = _run(tmp_path, params=params)

    assert seen_params, (
        "run_sealed_evaluation が core.run_supreme を一度も呼んでいない"
        "(封印 GT に対し supreme を実走していない疑い)"
    )
    # 注入した学習済み params が core.run_supreme に届いている(同一オブジェクト)。
    assert any(p is params for p in seen_params), (
        "run_sealed_evaluation が core.run_supreme に学習 params を渡していない"
        f"(渡った params={seen_params!r}・現状は params 省略=既定=未学習で実走している疑い)"
    )


def test_Phase1b_default_params_none_reaches_core_as_none(tmp_path, monkeypatch):
    """観点3 学習経路(後方互換の裏面): params=None(既定)では core.run_supreme に params=None
    (=既定=未学習)が渡る(学習 params を勝手に注入しない)。

    Phase1b の配線が「params=None のときは未学習で実走」する後方互換を、core への伝播の側から
    固定する。params=None でも学習済みオブジェクトが core に混入しないことを観測する。
    """
    core = _import_core()

    seen_params = []
    real_run_supreme = core.run_supreme

    def _spy_run_supreme(snaps, *args, **kwargs):
        if "params" in kwargs:
            seen_params.append(kwargs["params"])
        elif args:
            seen_params.append(args[0])
        else:
            seen_params.append(None)
        return real_run_supreme(snaps, *args, **kwargs)

    monkeypatch.setattr(core, "run_supreme", _spy_run_supreme)

    _store, _report = _run(tmp_path, params=None)

    assert seen_params, "params=None で core.run_supreme が呼ばれていない"
    assert all(p is None for p in seen_params), (
        f"params=None なのに core.run_supreme に非 None の params が渡っている: {seen_params!r}"
        "(既定経路に学習 params が漏れている=後方互換違反)"
    )


# ===========================================================================
# 封印保全(params 注入でも維持)— access_log / lifetime で機械検証
# ===========================================================================

def test_Phase1b_trained_params_read_after_revoke_is_access_denied(tmp_path):
    """封印保全(revoke 後拒否・核心): params 注入で run_sealed_evaluation 後(revoke 済み)に、
    同じ scenario を read しようとすると sealset.AccessDenied で拒否される。

    学習 params を通しても、最後に revoke して封印が閉じる(評価フェーズ外 read を技術的に遮断)
    ことを固定する(F-013-3 機構が params で壊れない)。
    """
    params = _trained_params()
    store, report = _run(tmp_path, params=params, revoked_ts=300.0)
    with pytest.raises(sealset.AccessDenied):
        store.read_sealed_gt("SEAL_P", token=None, ts=400.0)


def test_Phase1b_trained_params_all_reads_single_session_within_window(tmp_path):
    """封印保全(単一 session_id・窓内): params 注入時も access_log の全 read が同一 session_id
    かつ [issued_ts, revoked_ts) 窓内で、拒否レコードが混じらない。

    学習 params を通しても封印 GT の read が単一トークン下(同一 session_id・窓内)で行われた
    ことを、永続ログで機械検証する(GUARD_IF §3 運用規約2・F-013-3)。
    """
    params = _trained_params()
    store, report = _run(tmp_path, params=params, session_id="EVAL-1",
                         issued_ts=100.0, revoked_ts=300.0)
    log = store.access_log()
    assert log, "封印 read が1件も記録されていない(GT を読んでいない疑い)"
    for rec in log:
        assert rec["session_id"] == "EVAL-1", (
            f"単一 session_id でない read が混入(学習 params で開封が分裂した疑い): {rec}"
        )
        assert 100.0 <= rec["ts"] < 300.0, f"窓外 read が混入: {rec}"
    # 全 scenario が同一セッションで read された。
    targets = {rec["target"] for rec in log}
    assert {"SEAL_P", "SEAL_Q"}.issubset(targets), (
        f"全 scenario の封印 read が同一セッションで行われていない: targets={targets}"
    )


def test_Phase1b_trained_params_no_denied_access_records(tmp_path):
    """封印保全(評価フェーズ外アクセス 0 件): params 注入時も access_log に拒否(session_id=None)
    レコードが無い(全 read が正規トークン下)。

    封印保全=「評価フェーズ外アクセス 0 件」が学習 params 注入でも維持されることを、永続ログの
    拒否レコード不在で機械検証する(穴2 の代替=カウンタ/ログ検証)。
    """
    params = _trained_params()
    store, report = _run(tmp_path, params=params)
    denied = [rec for rec in store.access_log() if rec["session_id"] is None]
    assert denied == [], (
        f"学習 params 注入で評価フェーズ外(拒否)の封印アクセスが記録されている: {denied}"
    )
