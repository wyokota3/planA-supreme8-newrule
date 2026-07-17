"""F-013: 封印評価＋baseline 再計測（sealeval）。

汚染ゼロの封印で supreme vs baseline を項目別に対比する最終目標の経路を束ねる。
封印 GT は PSO 入力を持たない（ADR 0023 決定2）ため、(a) PSO 入力 と (b) 封印 GT を
scenario_id で対応づけて採点する。supreme 採点と baseline 取り込みを同一の
canonical_metric_spec（8層 layer schema）で並べ、項目別 verdict（弱: win/lose/draw・
強: maintained/degraded・no_data）を出す。封印開封は SealStore.open_eval_session を
唯一の正規経路として1回だけ行い、全 scenario の GT を単一トークン下で read してから
revoke する。

契約の最終根拠:
  - specs/SPEC.md「F-013」節（F-013-1 同一指標 / F-013-2 項目別 verdict・成功目標 /
    F-013-3 単一開封セッション）。
  - decisions/0023-f013-sealed-evaluation-design.md（決定1〜6＝設計の正）。
  - decisions/0012-u10-evaluation-metrics.md（8層 micro acc・完全一致・NA分母除外・
    総合=8層単純平均・Anomaly 採点外）。
  - specs/GT_SCHEMA.md（封印 GT の frames[]＝t0/t1/t2/t3 構造）。
  - tests/test_F013_*.py（各ファイル docstring が API 契約）。

規律: stdlib のみ・決定的（乱数・時刻なし。時刻 issued_ts/revoked_ts/ts は引数で受ける）。
既存モジュールの公開契約を壊さない（harness/core/sealset/guard を再利用）。
"""

from __future__ import annotations

from . import core
from . import guard
from . import harness


# ===========================================================================
# 例外
# ===========================================================================

class BaselineSchemaMismatch(Exception):
    """baseline 入力の層集合が canonical layer schema（8層）と一致せず取り込みを停止。

    欠落・余分・空のいずれも停止対象（黙って採点しない＝欠落層に既定値を捏造しない・
    ADR 0023 決定3・F-004 異常系の精神）。
    """


class EvalWindowTooNarrow(Exception):
    """run_sealed_evaluation の開封前 fail-closed 検証で送出（封印枠を焼く前に停止）。

    封印 read の ts を issued_ts から scenario ごとに +1.0 で割り当てる（read_ts=issued_ts;
    for sid: read; read_ts += 1.0）。全 read が窓 [issued_ts, revoked_ts)（半開区間・
    GUARD_IF §1/§3）内であるには issued_ts + max(0, N-1) < revoked_ts（N=len(scenario_ids)）
    が必要。これを **open_eval_session 呼び出しより前に**検証し、満たさないとき本例外で停止する
    （開封枠＝生涯1回の計数を消費しない・session_state.json も不変・ADR 0023 申し送り R2）。
    開封後の窓外 read で送出される AccessDenied とは別物で、「開封する前に止めた」ことを型で表す。
    """


# ===========================================================================
# 封印 GT（GT_SCHEMA frames[]）→ 8層 view の正規化（畳み込み）
#   既存 erroran._LAYER_TO_CANONICAL / harness の 8層 layer schema と同一方針。
#   - t2_mode/t2_role/t2_relation = 確率分布 argmax
#   - risk_tier = t0.risk_tier / t1_state = t1.state
#   - t3_hypothesis/quality_regime/scene_regime = t3.*
# ===========================================================================

def _argmax_label(dist):
    """確率分布 dict（クラス→float）の最大確率クラスを返す（決定的・空/None は None）。

    同点時はキーの昇順で先頭を選ぶ（決定性の担保）。erroran._argmax_set と同方針だが、
    8層 view は単一ラベルを要するため決定的に1つへ畳む。
    """
    if not dist:
        return None
    max_val = max(dist.values())
    candidates = sorted(cls for cls, v in dist.items() if v == max_val)
    return candidates[0] if candidates else None


def _gt_frame_to_view(gt_frame):
    """封印 GT の1フレーム（t0/t1/t2/t3）を 8層 view（採点用ラベル dict）へ畳む。

    GT_SCHEMA の構造に従う（ADR 0023 決定2・指示のマッピング）:
      risk_tier      = t0.risk_tier
      t1_state       = t1.state
      t2_mode        = argmax(t2.mode)
      t2_role        = argmax(t2.roles)
      t2_relation    = argmax(t2.relations)
      t3_hypothesis  = t3.hypothesis
      quality_regime = t3.quality_regime
      scene_regime   = t3.scene_regime
    当該フィールドが無い/None の層は None（採点上の NA＝全null層→no_data の素材・決定4）。
    """
    t0 = gt_frame.get("t0", {}) or {}
    t1 = gt_frame.get("t1", {}) or {}
    t2 = gt_frame.get("t2", {}) or {}
    t3 = gt_frame.get("t3", {}) or {}
    return {
        "risk_tier": t0.get("risk_tier"),
        "t1_state": t1.get("state"),
        "t2_mode": _argmax_label(t2.get("mode")),
        "t2_role": _argmax_label(t2.get("roles")),
        "t2_relation": _argmax_label(t2.get("relations")),
        "t3_hypothesis": t3.get("hypothesis"),
        "quality_regime": t3.get("quality_regime"),
        "scene_regime": t3.get("scene_regime"),
    }


def _gt_to_views(sealed_gt):
    """封印 GT（read_sealed_gt の戻り＝{"scenario_id","version","frames":[...]}）を
    各フレームの 8層 gt view 列へ畳む。"""
    return [_gt_frame_to_view(fr) for fr in sealed_gt.get("frames", [])]


# ===========================================================================
# 決定6 (a): 封印シナリオ入力 → PSO-Snapshot 系列アダプタ（seam の境界）
# ===========================================================================

def seal_scenario_to_pso(seal_scenario_input):
    """封印シナリオ入力 → PSO-Snapshot 系列（contract v1.4 形）への決定的アダプタ。

    封印レコードは GT のみで PSO 入力を持たない（ADR 0023 決定2）ため、封印シナリオ入力
    （{"scenario_id": str, "frames": [{"ts": float}, ...]}）を core.run_supreme が消費できる
    PSO-Snapshot 系列へ橋渡しする seam。

    決定的（同一入力 → 同一出力・乱数/時刻なし）。出力長 = 入力 frames 長。各 Snapshot は
    会話証拠フレーム（speech track + 近接 human + speaking link）として合成し、run_supreme が
    8層 view を返せる正当な Snapshot にする（fixtures_pso.frame_conversation と同方針だが、
    本モジュールは fixtures に依存しない＝自前で v1.4 形を組む）。
    """
    frames = seal_scenario_input.get("frames", [])
    snaps = []
    for fr in frames:
        ts = float(fr.get("ts", 0.0))
        snaps.append(_conversation_snapshot(ts))
    return snaps


def _conversation_snapshot(ts):
    """会話証拠の決定的な PSO-Snapshot/1.4 を1フレーム合成する（乱数・時刻なし）。

    speech track（近接）＋ speaking_prob 高 human ＋ speaking link ＋ 良好 scene_state。
    run_supreme の各層が明確に発火する強い証拠（境界の網羅は各モジュールの F-006〜011 済み）。
    """
    r_m = 2.0
    return {
        "version": "PSO-Snapshot/1.4",
        "ts": float(ts),
        "frame": "W2D",
        "origin": {"x_m": 0.0, "y_m": 0.0, "yaw_deg": 0.0},
        "tracks": {
            "audio": [
                {"aid": "A_sp", "type": "speech", "r_m": r_m, "theta_deg": 0.0},
            ],
            "humans": [
                {"hid": "H1", "r_m": r_m, "theta_deg": 0.0,
                 "speaking_prob": 0.95, "face_towards_user": 0.9},
            ],
            "objects": [],
        },
        "links": [
            {"from": "A_sp", "to": "H1", "type": "speaking", "score": 0.9},
        ],
        "geom": {"overlap_path": False, "lane_alignment": False, "min_TTC_s": 99.0},
        "scene_state": {"latency_ms": 20.0, "QoS": 0.95},
    }


# ===========================================================================
# 決定6 (b): baseline 取り込み I/F（研究者手動・同一 layer schema・捏造禁止）
# ===========================================================================

class BaselineScores:
    """取り込んだ baseline スコア（ScoreResult 互換の最小面）。

    .layer_score(layer) -> float   各層 acc [0,1]
    .layers -> tuple[str]          8層
    .overall() -> float            8層単純平均（ADR 0012 総合・supreme と同一土俵）
    """

    def __init__(self, scored_layers, layer_accs):
        # scored_layers: 採点層（順序付き）。layer_accs: {layer: float}。
        self.layers = tuple(scored_layers)
        self._accs = dict(layer_accs)

    def layer_score(self, layer):
        """指定層の acc を返す（取り込み済みの 8層は必ず値を持つ）。"""
        return self._accs.get(layer)

    def overall(self):
        """8層 acc の単純平均（同一指標・ADR 0012）。"""
        vals = [self._accs[layer] for layer in self.layers]
        if not vals:
            return None
        return sum(vals) / len(vals)


def load_baseline_scores(source, *, metric_spec=None):
    """研究者手動の baseline 層 acc（dict {layer: float}）を取り込む（ADR 0023 決定3）。

    metric_spec 省略時は harness.canonical_metric_spec() の 8層を layer schema 基準にする
    （同一指標式が一意・supreme と同一土俵）。source の層集合が canonical 8層と一致しないと
    BaselineSchemaMismatch で停止する（欠落・余分・空のいずれも停止＝黙って採点しない・
    欠落層に既定値を捏造しない）。

    正常時は ScoreResult 互換の BaselineScores を返す。
    """
    if metric_spec is None:
        metric_spec = harness.canonical_metric_spec()
    canonical = tuple(metric_spec.scored_layers)
    canonical_set = set(canonical)
    source_set = set(source.keys())

    if source_set != canonical_set:
        missing = canonical_set - source_set
        extra = source_set - canonical_set
        raise BaselineSchemaMismatch(
            "baseline 層集合が canonical layer schema（8層）と不一致のため停止する"
            "（黙って採点しない・ADR 0023 決定3）。"
            f" 欠落={sorted(missing)!r} 余分={sorted(extra)!r}"
        )

    # canonical の固定順で acc を保持（決定性）。
    layer_accs = {layer: float(source[layer]) for layer in canonical}
    return BaselineScores(canonical, layer_accs)


# ===========================================================================
# 決定5: 項目別 verdict（compare_items）
# ===========================================================================

class ItemComparisonReport:
    """compare_items の結果（項目別 verdict・成功目標フラグ）。

    .verdict(item) -> str   弱: win/lose/draw ／ 強: maintained/degraded ／ no_data
    .verdicts -> dict       item -> verdict（報告用）
    .weak_items / .strong_items -> tuple  入力をそのまま保持
    .no_data_items -> tuple  no_data として勝敗から除外された項目
    .success_goal -> bool    弱い全 win ∧ 強い全 maintained ∧ no_data 無し
    """

    def __init__(self, weak_items, strong_items, verdicts, no_data_items, success_goal):
        self.weak_items = tuple(weak_items)
        self.strong_items = tuple(strong_items)
        self.verdicts = dict(verdicts)
        self.no_data_items = tuple(no_data_items)
        self.success_goal = bool(success_goal)

    def verdict(self, item):
        """指定項目の verdict 文字列を返す。"""
        return self.verdicts.get(item)


# 境界（|Δ| == δ）の浮動小数点判定許容（ADR 0002・U5a の ε を再利用）。
#   0.62-0.60 等は二進浮動小数で 0.0200000000000000018 となり δ=0.02 を僅かに超える。
#   テスト docstring の意図は「|Δ|==δ ちょうどは draw / 低下 δ ちょうどは maintained」
#   （十進等価＝境界）。この浮動小数点誤差ぶんを ε で境界側へ吸収する（決定5 の閉/開を
#   保つ）。genuine な差（0.021 等＝δ を ~5e-4 超）は ε を遥かに超え win/degraded のまま。
_EPS_ABS = 1e-9
_EPS_REL = 1e-6


def _exceeds_delta(magnitude, delta_strong):
    """|Δ| が δ を「厳密に」超えるか（ε 境界吸収つき）。

    境界（|Δ| が δ と ε 以内で等しい）は False（超えていない＝draw/maintained 側）。
    """
    threshold = _EPS_ABS + _EPS_REL * max(abs(magnitude), abs(delta_strong))
    return magnitude > delta_strong + threshold


def _weak_verdict(delta, delta_strong):
    """弱い項目の verdict（境界 |Δ|==δ は draw・厳密 > のみ win/lose）。"""
    if _exceeds_delta(delta, delta_strong):
        return "win"
    if _exceeds_delta(-delta, delta_strong):
        return "lose"
    return "draw"


def _strong_verdict(delta, delta_strong):
    """強い項目の verdict（低下 δ ちょうどは maintained・厳密 > 低下のみ degraded）。"""
    if _exceeds_delta(-delta, delta_strong):
        return "degraded"
    return "maintained"


def compare_items(supreme, baseline, *, delta_strong, weak_items, strong_items):
    """supreme / baseline（ScoreResult 互換）を項目別に対比する（ADR 0023 決定5）。

    Δ = supreme.layer_score(item) - baseline.layer_score(item)。どちらかが None
    （封印に当該層データ無し）→ no_data（draw にしない・勝敗から除外・決定4）。
    弱: Δ>δ→win / Δ<-δ→lose / |Δ|≤δ→draw（境界 |Δ|==δ は draw）。
    強: Δ<-δ→degraded / それ以外→maintained（低下 δ ちょうどは maintained）。

    成功目標フラグ（弱い全 win ∧ 強い全 maintained ∧ no_data 無し）は report に載せるだけで、
    例外/失敗で合否を強制しない（合否ゲートでない・SPEC 非機能要件）。未達でも raise しない。
    """
    verdicts = {}
    no_data_items = []

    for item in weak_items:
        s = supreme.layer_score(item)
        b = baseline.layer_score(item)
        if s is None or b is None:
            verdicts[item] = "no_data"
            no_data_items.append(item)
            continue
        verdicts[item] = _weak_verdict(s - b, delta_strong)

    for item in strong_items:
        s = supreme.layer_score(item)
        b = baseline.layer_score(item)
        if s is None or b is None:
            verdicts[item] = "no_data"
            no_data_items.append(item)
            continue
        verdicts[item] = _strong_verdict(s - b, delta_strong)

    # 成功目標: 弱い全 win ∧ 強い全 maintained ∧ no_data 無し。
    success_goal = (
        not no_data_items
        and all(verdicts.get(it) == "win" for it in weak_items)
        and all(verdicts.get(it) == "maintained" for it in strong_items)
    )

    return ItemComparisonReport(
        weak_items, strong_items, verdicts, no_data_items, success_goal
    )


# ===========================================================================
# 決定1/6: 封印評価 E2E（run_sealed_evaluation）
# ===========================================================================

class SealEvalReport:
    """run_sealed_evaluation の結果（項目別 verdict ＋ 単一開封セッションの証跡）。

    .comparison              -> ItemComparisonReport（compare_items の結果・F-013-2）
    .session_id              -> str  使った開封 session_id
    .lifetime_session_count  -> int  実行後の生涯開封セッション数（==1 を保証）
    .audit_passed            -> bool  guard.audit_seal_access(access_log, token).passed
    .token                   -> OpenToken  実行で使い revoke 済みの開封トークン（監査突合用）
    """

    def __init__(self, comparison, session_id, lifetime_session_count,
                 audit_passed, token):
        self.comparison = comparison
        self.session_id = session_id
        self.lifetime_session_count = lifetime_session_count
        self.audit_passed = audit_passed
        self.token = token


class _SupremeScores:
    """harness.ScoreResult を ScoreResult 互換面で薄くラップする（全null層→None 表現）。

    ScoreResult.layer_score は分母0の層を NaN で返す（実装裁量）。compare_items は
    None を no_data の素材とするため、NaN/分母0 を None に正規化して渡す。
    """

    def __init__(self, score_result):
        self._result = score_result
        self.layers = tuple(score_result.layers)

    def layer_score(self, layer):
        import math
        val = self._result.layer_score(layer)
        if val is None:
            return None
        if isinstance(val, float) and math.isnan(val):
            return None
        return val

    def overall(self):
        return self._result.overall()


def run_sealed_evaluation(seal_store, aggregate, baseline_scores, *,
                          scenario_ids, scenario_inputs, session_id,
                          issued_ts, revoked_ts, weak_items, strong_items,
                          delta_strong, config=None, params=None):
    """封印を1回開封→全 GT を単一トークン下で read→supreme 実走＋採点→baseline 取り込み
    →compare_items→revoke する E2E ランナー（ADR 0023 決定1/6・ADR 0025 P1-R4/Phase1b）。

    1. token = seal_store.open_eval_session(aggregate, session_id, issued_ts)
       （唯一の正規開封経路・1回だけ開封・aggregate 強制）。
    2. 各 scenario_ids の GT を単一トークン下で read_sealed_gt（ts は [issued_ts, revoked_ts)
       窓内・決定的）。封印 GT を 8層 gt view へ畳む。
    3. seal_scenario_to_pso(scenario_inputs[sid]) → core.run_supreme（学習済み params 注入）
       → 全 scenario を1つの trace に束ね harness.score(trace, canonical_metric_spec()) で
       supreme ScoreResult。
    4. load_baseline_scores(baseline_scores) で baseline を取り込み（同一 layer schema）。
    5. compare_items で項目別 verdict。
    6. seal_store.revoke_open_token(token, revoked_ts=revoked_ts) で失効。

    返り値 SealEvalReport（lifetime_session_count==1・audit_passed・revoke 済みトークン同梱）。

    決定的: ts は窓内で scenario の列挙順に決定的に割り当てる（乱数・時刻なし）。

    params（ADR 0025 Phase1b・後方互換の最重要）:
      core.fit_supreme(練習) の返り値 SupremeParams を渡すと、内部の core.run_supreme に
      その params を通して学習済み supreme を封印で実走する（学習は練習データで・封印は評価専用＝
      seal は学習に使わない過学習ガード）。**params=None（既定）は現状の挙動を一切変えない**
      （core.run_supreme(..., params=None) は未学習の既定実走）。封印開封・単一セッション・revoke・
      audit の F-013 機構は params の有無で不変。
    """
    spec = harness.canonical_metric_spec()

    # 0) 開封前 fail-closed 窓内不変条件検証（ADR 0023 申し送り R2）。
    #    read ts は issued_ts から scenario ごとに +1.0（last read ts = issued_ts + (N-1)）。
    #    窓 [issued_ts, revoked_ts) は半開区間（GUARD_IF §1/§3）なので、全 read が窓内である
    #    条件は issued_ts + max(0, N-1) < revoked_ts（厳密 <）。満たさないときは open_eval_session
    #    を呼ぶ前に停止する＝封印の生涯1回の開封枠を消費しない・session_state.json も不変。
    n_scenarios = len(scenario_ids)
    last_read_ts = float(issued_ts) + max(0, n_scenarios - 1)
    if not (last_read_ts < revoked_ts):
        min_revoked_ts = last_read_ts  # これより厳密に大きい revoked_ts が必要（半開区間）。
        raise EvalWindowTooNarrow(
            "封印評価の窓が狭く全 read が窓内に収まらないため開封前に停止する"
            "（fail-closed・開封枠を消費しない・ADR 0023 申し送り R2）。"
            f" issued_ts={issued_ts!r} revoked_ts={revoked_ts!r} N={n_scenarios}"
            f" last_read_ts=issued_ts+(N-1)={last_read_ts!r}"
            f" 必要条件: last_read_ts < revoked_ts（revoked_ts > {min_revoked_ts!r} が必要）"
        )

    # 1) 1回だけ開封（aggregate 強制・store 自身の guard 発行）。
    token = seal_store.open_eval_session(aggregate, session_id, issued_ts)

    # 2-3) 単一トークン下で全 scenario の GT を read し、PSO→run_supreme→trace を束ねる。
    #      ts は窓 [issued_ts, revoked_ts) 内で決定的に割り当てる（read ごとに +1 ずつ前進）。
    trace = {}
    read_ts = float(issued_ts)
    for sid in scenario_ids:
        sealed_gt = seal_store.read_sealed_gt(sid, token=token, ts=read_ts)
        read_ts += 1.0

        gt_views = _gt_to_views(sealed_gt)
        snaps = seal_scenario_to_pso(scenario_inputs[sid])
        views = core.run_supreme(snaps, params=params, config=config)

        frames = []
        n = min(len(views), len(gt_views))
        for i in range(n):
            frames.append({
                "ts": float(i),
                "view": dict(views[i]),
                "gt": dict(gt_views[i]),
            })
        trace[sid] = frames

    # 全 scenario を1つの trace に束ねて採点（micro global pooling・ADR 0012）。
    supreme_result = harness.score(trace, spec)
    supreme = _SupremeScores(supreme_result)

    # 4) baseline 取り込み（同一 layer schema・捏造禁止）。
    baseline = load_baseline_scores(baseline_scores, metric_spec=spec)

    # 5) 項目別 verdict。
    comparison = compare_items(
        supreme, baseline,
        delta_strong=delta_strong,
        weak_items=weak_items, strong_items=strong_items,
    )

    # 6) 失効（評価フェーズを閉じる）。
    seal_store.revoke_open_token(token, revoked_ts=revoked_ts)

    # 監査突合（永続ログ × revoke 済み実トークン・GUARD_IF §3 運用規約2）。
    audit = guard.audit_seal_access(seal_store.access_log(), token)

    return SealEvalReport(
        comparison=comparison,
        session_id=session_id,
        lifetime_session_count=seal_store.lifetime_session_count(),
        audit_passed=audit.passed,
        token=token,
    )
