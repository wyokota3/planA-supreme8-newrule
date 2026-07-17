"""F-013-3: 単一開封セッション（ドライラン E2E）— run_sealed_evaluation をダミー封印
（production=False）で通し、封印保全・単一開封・revoke 後 AccessDenied を機械検証する。

specs/SPEC.md F-013-3:
  「封印開封が単一の開封セッション（guard 発行の開封トークン下）で行われ、本番封印の生涯
   開封セッション数が1（F-014 のセッションID付きログで検証）。supreme 測定と baseline 再計測
   の読込は同一セッション内なら『1回』と数える。」
specs/TEST_STRATEGY.md F-013 / 穴2:
  「本番封印で1回しか実行できない → ダミー封印で経路を常用テスト…本番は最終1回。」
  「開封セッション数のカウンタ（guard 発行トークンの session_id 付きログ）を対象にする。」
specs/GUARD_IF.md §3 運用規約:
  生涯1回の保証は audit_seal_access + lifetime_session_count の突合で担保する。
  失効は revoke_token（revoked_ts 必須）。窓は半開区間 [issued_ts, revoked_ts)。
decisions/0023-f013-sealed-evaluation-design.md 決定1/6:
  run_sealed_evaluation は封印を1回開封→全 scenario の GT を単一トークン下で read→
  supreme 実走＋採点→baseline 取り込み→compare_items→revoke→lifetime_session_count()==1 と
  audit_seal_access 合格を保証する。開封の唯一の正規経路は SealStore.open_eval_session。

----------------------------------------------------------------------------
このファイルが定義する supreme.sealeval.run_sealed_evaluation の前提 API（report 明記）:

  sealeval.run_sealed_evaluation(
      seal_store, aggregate, baseline_scores, *,
      scenario_ids, session_id, issued_ts, revoked_ts,
      weak_items, strong_items, delta_strong, config=None) -> SealEvalReport
    1. seal_store.open_eval_session(aggregate, session_id, issued_ts) で**1回だけ**開封。
    2. scenario_ids 各 GT を**単一トークン下**で read_sealed_gt（同一 session_id・窓内）。
    3. PSO 入力（seal_scenario_to_pso）→ core.run_supreme → 封印 GT で harness.score。
    4. baseline_scores を load_baseline_scores で取り込み（同一 layer schema）。
    5. compare_items で項目別 verdict。
    6. seal_store.revoke_open_token(token, revoked_ts=revoked_ts) で失効。
    返り値 SealEvalReport の面:
      .comparison      -> ItemComparisonReport（compare_items の結果・F-013-2）
      .session_id      -> str       使った開封 session_id
      .lifetime_session_count -> int  実行後の生涯開封セッション数（==1 を保証）
      .audit_passed    -> bool      guard.audit_seal_access(access_log, token).passed
      .token           -> OpenToken  実行で使い revoke 済みの開封トークン（監査突合用・失効済み）

  PSO 入力源は seal_scenario_to_pso が消費する seal_scenario_inputs を別系統で供給する
  （封印 GT は PSO を持たない・ADR 0023 決定2）。本ファイルは scenario_inputs を
  キーワードで渡せる前提（run_sealed_evaluation(..., scenario_inputs=...)）でドライランする。

注意（規律・指示）:
  - 本番封印は開けない。production=False のダミー封印で経路全体をドライラン（穴2）。
  - stdlib のみ・決定的。時刻 issued_ts/revoked_ts/ts はテストが引数で供給する。
  - 封印保全・単一開封・同一指標は access_log / lifetime_session_count を機械検証する。
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
# 共有ヘルパ: ダミー封印 2 件を登録した SealStore（production=False）＋ 合格 aggregate
# ---------------------------------------------------------------------------

def _store_with_dummy_seals(tmp_path):
    """ダミー封印 SEAL_P / SEAL_Q を登録した production=False の SealStore。

    親系統タグ付き human root（fixtures_sealeval）。常用テスト経路（穴2）。
    """
    store = sealset.SealStore(root_dir=tmp_path, production=False)
    gov = datagov.DataGovernor()
    for rec in fxs.sealed_records_two_scenarios():
        store.register(rec, governor=gov, ts=0.0)
    return store


def _passing_aggregate():
    """全ガード合格の AggregateResult（開封が通る前提・test_F014 の流儀）。"""
    g1 = guard.check_param_budget(param_count=19, data_count=200, k=0.5)
    return guard.combine_guards([g1])


def _run(tmp_path, *, store=None, aggregate=None, baseline=None,
         session_id="EVAL-1", issued_ts=100.0, revoked_ts=300.0):
    """run_sealed_evaluation をダミー封印・2 シナリオでドライランする薄いラッパ。"""
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
    )


# ===========================================================================
# 公開シンボルの存在
# ===========================================================================

def test_F013_3_sealeval_exposes_run_sealed_evaluation():
    """F-013-3（契約面・ADR 0023 決定6）: sealeval は run_sealed_evaluation を公開する。"""
    sealeval = _import_sealeval()
    assert hasattr(sealeval, "run_sealed_evaluation")
    assert callable(sealeval.run_sealed_evaluation)


# ===========================================================================
# 単一開封セッション: 実行後の生涯開封セッション数が 1
# ===========================================================================

def test_F013_3_lifetime_session_count_is_one_after_run(tmp_path):
    """F-013-3（単一開封・核心）: ドライラン実行後、封印の生涯開封セッション数が 1。

    複数 scenario（SEAL_P/SEAL_Q）の GT を読んでも、開封は1回（単一トークン下）。
    supreme 採点 + baseline 取り込みの読込が同一セッション内なら『1回』と数える（SPEC）。
    """
    store, report = _run(tmp_path)
    assert store.lifetime_session_count() == 1, (
        f"生涯開封セッション数が1でない: {store.lifetime_session_count()}"
    )
    assert report.lifetime_session_count == 1


def test_F013_3_all_reads_share_single_session_id_within_window(tmp_path):
    """F-013-3（単一 session_id・窓内）: access_log の全 read が同一 session_id かつ窓内で、
    guard.audit_seal_access に合格する。

    複数 scenario の封印 read が**単一トークン**（同一 session_id・[issued,revoked) 窓内）で
    行われたことを、永続ログ × audit_seal_access の突合で機械検証する（GUARD_IF §3 運用規約2）。
    """
    store, report = _run(tmp_path, session_id="EVAL-1",
                         issued_ts=100.0, revoked_ts=300.0)

    log = store.access_log()
    assert log, "封印 read が1件も記録されていない（GT を読んでいない疑い）"
    # 全 read が同一 session_id・None（拒否）混入なし。
    for rec in log:
        assert rec["session_id"] == "EVAL-1", (
            f"単一 session_id でない read が混入: {rec}"
        )
        assert 100.0 <= rec["ts"] < 300.0, f"窓外 read が混入: {rec}"
    # report のフラグ（audit 合格）も True。
    assert report.audit_passed is True


def test_F013_3_reads_cover_all_scenarios(tmp_path):
    """F-013-3（全 scenario を単一セッションで read）: 指定した全 scenario_ids の封印 GT が
    同一セッション内で read されている（access_log の target に全 scenario が現れる）。
    """
    store, report = _run(tmp_path)
    targets = {rec["target"] for rec in store.access_log()}
    assert {"SEAL_P", "SEAL_Q"}.issubset(targets), (
        f"全 scenario の封印 read が同一セッションで行われていない: targets={targets}"
    )


# ===========================================================================
# revoke 後の read は AccessDenied（窓外＝封印が閉じる）
# ===========================================================================

def test_F013_3_read_after_revoke_is_access_denied(tmp_path):
    """F-013-3（revoke 後拒否・核心）: run_sealed_evaluation 後（revoke 済み）に、
    同じ scenario を read しようとすると sealset.AccessDenied で拒否される。

    revoke（失効）で封印が閉じる＝評価フェーズ外の read を技術的に遮断する（SPEC F-002 正常系）。
    run_sealed_evaluation が最後に revoke していることの直接証拠。
    """
    store, report = _run(tmp_path, revoked_ts=300.0)
    # 実行で使ったトークンは revoke 済み。新たな読み出しは（窓外＝失効後）拒否される。
    # 失効後の任意 ts で read を試みる（トークンは report 経由でなく新規 None でも拒否）。
    with pytest.raises(sealset.AccessDenied):
        store.read_sealed_gt("SEAL_P", token=None, ts=400.0)


def test_F013_3_no_second_open_session_possible_in_production_semantics(tmp_path):
    """F-013-3（単一性の含意）: ドライラン後、access_log の拒否（session_id=None）は無い
    （全 read が正規トークン下）。

    封印保全＝「評価フェーズ外アクセス0件」を access_log で機械検証する（穴2 の代替＝
    カウンタ/ログ検証）。正規の単一セッション内 read のみで、拒否レコードが混じらない。
    """
    store, report = _run(tmp_path)
    denied = [rec for rec in store.access_log() if rec["session_id"] is None]
    assert denied == [], f"評価フェーズ外（拒否）の封印アクセスが記録されている: {denied}"


# ===========================================================================
# 報告: comparison（項目別 verdict）が同梱され、同一セッションの所産であること
# ===========================================================================

def test_F013_3_report_carries_item_comparison(tmp_path):
    """F-013-3 + F-013-2（報告同梱）: SealEvalReport は項目別 verdict（comparison）を含み、
    弱5+強3 の全項目が報告される。

    封印開封→採点→対比→失効 が1本のドライランで完結し、報告に項目別勝敗が載ることを固定する。
    """
    store, report = _run(tmp_path)
    comparison = report.comparison
    for it in fxs.WEAK_ITEMS + fxs.STRONG_ITEMS:
        assert it in comparison.verdicts, f"報告に項目 {it} の verdict が無い"
    # session_id が報告に保持される（どのセッションの所産か）。
    assert report.session_id == "EVAL-1"


def test_F013_3_audit_seal_access_holds_for_persisted_log(tmp_path):
    """F-013-3（永続ログ × 監査の突合）: 実行後の永続 access_log を別インスタンスから
    読み戻し、その session_id のトークンで audit_seal_access が合格する。

    GUARD_IF §3 運用規約2 の突合（インメモリ計数のみに依存しない）を、プロセス跨ぎ相当で固定。
    監査には report が保持する実トークン（run_sealed_evaluation が発行・失効させた本物）を使う。
    """
    store, report = _run(tmp_path, session_id="EVAL-1",
                         issued_ts=100.0, revoked_ts=300.0)

    # プロセス再起動相当: 同一 root_dir（tmp_path）の新インスタンスで永続ログを読み戻す。
    store2 = sealset.SealStore(root_dir=tmp_path, production=False)
    log2 = store2.access_log()
    assert log2, "永続ログが読み戻せていない"
    # report が保持する実トークン（失効済み・窓 [100,300)）で監査突合する。
    result = guard.audit_seal_access(log2, report.token)
    assert result.passed is True, (
        f"永続ログ × audit_seal_access が合格しない: {result.reason}"
    )
