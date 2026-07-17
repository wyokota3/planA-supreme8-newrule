"""F-基盤-001-1(ADR 0022)— モジュール結線の代表ケース固定: 各モジュールが run_supreme で
実際に結線されている(内部に届く)ことを代表ケースで固定する(内部網羅でなく結線確認)。

各層の「ある入力 → その層が想定側に動く」を 1〜数ケースで固定する。境界値の網羅は各モジュールの
F-006〜011 が済ませている。本ファイルは「PSO Snapshot がその層まで届いて結線が効いている」ことのみ。

契約の最終根拠:
  - decisions/0022-fbase001-supreme-runner.md:
      正常系: PSO → 証拠抽出 → 観測式+HGF(h_q/vol・pw_anom)→ 段2 mode logits →
              各モジュール結線(quality→anomaly→t0→t1→t2[mode/role/relation]→scene→t3)→
              8層 view 組み立て。tick 間状態持ち越し・T3 はシナリオ境界で reset。
      決定2: T3 reset 発火源 = シナリオ境界(シナリオ先頭で reset=True を T3 へ注入)。
      決定3: quality h_q/vol・anomaly pw_anom は baseline 観測式 + 共有 HGF で再実装。
      F-基盤-001-1: 全モジュール結線・状態持ち越し・T3 シナリオ境界 reset・harness.score 互換。
  - 各モジュールの契約(結線先・本ファイルの期待ラベルの根拠):
      t0: tests/test_F006_t0_risk_tier.py(siren 下限で caution・kind 別 TTC 閾値)。
      t1: tests/test_F006_t1_state.py(ttc<閾値で approach・状態保持)。
      mode/role/relation: tests/test_F007_*/test_F006_role_logits/test_F008_*(会話証拠→conv系)。
      quality: tests/test_F011_classify_rule.py(h_q 低→BLOCK 側)。
      scene: tests/test_F010_classify.py(持続変化→CHANGING 側)。
      t3: tests/test_F009_*(reset でエピソード境界初期化)。
  - PSO 入力契約 v1.4: tracks/links/geom.min_TTC_s/scene_state.QoS,latency_ms。

スコープ外(ADR 0022・推測でテスト化しない):
  - 各層の閾値の正確値・境界(F-006〜011 で済み)。本ファイルは「caution/danger 側」「conv 系」
    「DEGRADED/BLOCK 側」「CHANGING 側」のような **方向性** を代表ケースで固定し、厳密な単一値は
    上流の証拠抽出閾値(ADR 0022 で実装裁量・F-013 の δ_strong 測定)に委ねる。
  - run_supreme の signature 詳細(frame 列 / scenario 単位)は性質契約(end_to_end.py と同方針)。

本ファイルが前提とする supreme.core / supreme.harness の公開 API:
  core.run_supreme(pso_snapshots, config=None) -> list[frame_view]
  core.run_supreme_scenarios(scenarios, config=None) -> dict[scenario_id, list[frame_view]]
  core.build_trace(scenarios, gt, config=None) -> harness 互換 trace(任意・あれば使う)
  harness.score(trace, metric_spec) / harness.canonical_metric_spec()(tests/test_F004_* 参照)
"""

import pytest

import fixtures_pso as fxp


# v1.4 統制語彙(各モジュールの F-006〜011 テストから引用・結線方向の判定に使う)。
V14_RISK_TIER = {"info", "caution", "danger"}
CAUTION_DANGER = {"caution", "danger"}
V14_T1 = {"idle", "approach", "pass", "depart"}
V14_MODE = {
    "conv_request", "conv_ongoing", "surround_activity", "forward_caution",
    "side_rear_caution", "alert_required", "emergency", "quiet_standby",
    "env_change", "uncertain",
}
CONV_MODES = {"conv_request", "conv_ongoing"}
V14_ROLE = {
    "source_speech", "source_vehicle", "source_alarm",
    "source_human", "source_object", "unknown",
}
V14_RELATION = {"addressing_user", "near_user", "approaching", "grouped"}
CONV_RELATIONS = {"addressing_user", "near_user"}
V14_QUALITY = {"GOOD", "DEGRADED", "BLOCK"}
DEGRADED_BLOCK = {"DEGRADED", "BLOCK"}
V14_SCENE = {"STABLE", "CHANGING", "DEGRADING"}
CHANGING_DEGRADING = {"CHANGING", "DEGRADING"}
V14_T3 = {
    "quiet_stable", "conv_participating", "sustained_alert", "env_shift", "env_start",
    "crowd_tendency", "traffic_unstable", "hazard_declining", "uncertain_context",
    "alert_required",
}

EIGHT_LAYERS = {
    "risk_tier", "t1_state", "t2_mode", "t2_role", "t2_relation",
    "t3_hypothesis", "quality_regime", "scene_regime",
}


def _import_core():
    from supreme import core

    return core


# ===========================================================================
# t0 結線: siren track を含む Snapshot → risk_tier が caution/danger 側
# (ADR 0017 決定3 T0: siren は siren 下限/閾値で info にならない)
# ===========================================================================

def test_Fbase001_1_wiring_t0_siren_makes_risk_tier_caution_or_danger():
    """F-基盤-001-1(ADR 0022・t0 結線): siren track を含むフレームでは risk_tier が
    caution/danger 側になる(info でない)。

    siren が Snapshot.tracks.audio に届き t0.risk_tier の siren 下限(高 TTC でも caution)・
    kind 別閾値(低 TTC で danger)が効いていること=t0 が結線されていることを固定する。
    """
    core = _import_core()
    views = core.run_supreme([fxp.frame_siren(ts=0.0, r_m=30.0, min_TTC_s=15.0)])
    rt = views[0]["risk_tier"]
    assert rt in CAUTION_DANGER, (
        f"siren フレームの risk_tier が caution/danger 側でない: {rt!r}"
        "(t0 が siren track まで結線されていない疑い)"
    )


def test_Fbase001_1_wiring_t0_benign_is_info_not_caution():
    """F-基盤-001-1(ADR 0022・t0 結線の対比): 危険トラックの無い良性フレームでは risk_tier が
    info(siren フレームと異なる)。

    siren フレーム(caution/danger)と良性フレーム(info)で risk_tier が変わることで、
    risk_tier が入力に応じて動く=t0 が固定値でなく結線されていることを固定する。
    """
    core = _import_core()
    benign = core.run_supreme([fxp.frame_benign(ts=0.0)])[0]["risk_tier"]
    siren = core.run_supreme([fxp.frame_siren(ts=0.0)])[0]["risk_tier"]
    assert benign == "info", f"良性フレームの risk_tier が info でない: {benign!r}"
    assert benign != siren, (
        "良性フレームと siren フレームで risk_tier が同じ(t0 が入力に反応していない)"
    )


# ===========================================================================
# t1 結線: 接近系列(min_TTC 小・range 減少)→ t1_state が approach 等
# (ADR 0017 決定3 T1: ttc < 閾値で approach・状態保持)
# ===========================================================================

def test_Fbase001_1_wiring_t1_approaching_sequence_yields_approach():
    """F-基盤-001-1(ADR 0022・t1 結線): min_TTC が小さく range が系列で減少する接近フレームで
    t1_state が approach(idle でない)。

    geom.min_TTC_s と track.r_m が t1 まで届き、ttc<閾値(12)で approach になること=t1 が
    結線されていることを固定する。接近は range 減少系列で与える。
    """
    core = _import_core()
    seq = [
        fxp.frame_approach(ts=0.0, r_m=20.0, min_TTC_s=8.0),
        fxp.frame_approach(ts=1.0, r_m=12.0, min_TTC_s=6.0),
        fxp.frame_approach(ts=2.0, r_m=6.0, min_TTC_s=4.0),
    ]
    views = core.run_supreme(seq)
    # 接近系列のいずれかのフレームで approach が立つ(idle に張り付かない)。
    states = [v["t1_state"] for v in views]
    assert any(s == "approach" for s in states), (
        f"接近系列で t1_state に approach が現れない: {states!r}"
        "(t1 が min_TTC/range まで結線されていない疑い)"
    )


def test_Fbase001_1_wiring_t1_benign_high_ttc_is_idle():
    """F-基盤-001-1(ADR 0022・t1 結線の対比): 接近しない良性フレーム(min_TTC 大)では
    t1_state が idle。

    良性(idle)と接近(approach)で t1_state が変わることで、t1 が入力 TTC に反応している
    =固定値でなく結線されていることを固定する。
    """
    core = _import_core()
    benign = core.run_supreme([fxp.frame_benign(ts=0.0)])[0]["t1_state"]
    assert benign == "idle", (
        f"良性・高 TTC フレームの t1_state が idle でない: {benign!r}"
    )


# ===========================================================================
# mode/role/relation 結線: 会話証拠 → conv 系
# (speech track + speaking_prob 高 + speaking link)
# ===========================================================================

def test_Fbase001_1_wiring_conversation_role_is_source_speech():
    """F-基盤-001-1(ADR 0022・role 結線): 会話証拠フレーム(speech track + 近接 human +
    speaking_prob 高)で t2_role が source_speech。

    speech track / human.speaking_prob / speaking link が証拠抽出 → role まで届き、
    conv_strong(speaking>0.7 ∧ min_range<5)で source_speech が立つこと=role 結線を固定する。
    """
    core = _import_core()
    view = core.run_supreme([fxp.frame_conversation(ts=0.0, r_m=2.0, speaking_prob=0.9)])[0]
    assert view["t2_role"] == "source_speech", (
        f"会話証拠フレームの t2_role が source_speech でない: {view['t2_role']!r}"
        "(speech track/speaking_prob が role まで結線されていない疑い)"
    )


def test_Fbase001_1_wiring_conversation_relation_is_conv_side():
    """F-基盤-001-1(ADR 0022・relation 結線): 会話証拠フレーム(近接 ∧ speaking link)で
    t2_relation が conv 系(addressing_user または near_user)。

    near_prox(<3m)∧ speaking_link → addressing_user、または conv_strong → near_user。
    無証拠既定 grouped でないこと=会話証拠が relation まで結線されていることを固定する。
    """
    core = _import_core()
    rel = core.run_supreme([fxp.frame_conversation(ts=0.0, r_m=2.0, speaking_prob=0.9)])[0]["t2_relation"]
    assert rel in CONV_RELATIONS, (
        f"会話証拠フレームの t2_relation が conv 系(addressing_user/near_user)でない: {rel!r}"
        "(会話証拠が relation まで結線されず無証拠既定 grouped に落ちている疑い)"
    )


def test_Fbase001_1_wiring_conversation_mode_is_conv_side():
    """F-基盤-001-1(ADR 0022・mode 結線): 会話証拠が持続するフレーム系列で t2_mode が
    conv 系(conv_request/conv_ongoing)になるフレームがある。

    段2 mode logits 生成(ADR 0022 構成要素4)が会話証拠から conv logit を立て、
    mode.hysteresis を経て conv 系が出ること=mode 結線を固定する。ヒステリシスは quiet 起点の
    弱い証拠を抑えるため、強い会話証拠を複数フレーム持続させる。
    """
    core = _import_core()
    seq = [fxp.frame_conversation(ts=float(i), r_m=2.0, speaking_prob=0.95) for i in range(4)]
    modes = [v["t2_mode"] for v in core.run_supreme(seq)]
    assert any(m in CONV_MODES for m in modes), (
        f"持続会話系列で t2_mode に conv 系が現れない: {modes!r}"
        "(会話証拠 → mode logits → hysteresis の結線が効いていない疑い)"
    )


# ===========================================================================
# quality 結線: scene_state.QoS 低 → quality_regime が DEGRADED/BLOCK 側
# (ADR 0022 決定3: 観測式 + HGF → h_q/vol → quality.classify)
# ===========================================================================

def test_Fbase001_1_wiring_low_qos_yields_degraded_or_block():
    """F-基盤-001-1(ADR 0022 決定3・quality 結線): QoS 低・latency 高のフレーム系列で
    quality_regime が DEGRADED/BLOCK 側になる(GOOD でない)。

    scene_state.QoS/latency_ms が baseline 観測式 → h_q(低)→ 共有 HGF → quality.classify
    まで届き、h_q 低で BLOCK/DEGRADED になること=観測式+HGF→quality の結線を固定する。
    HGF は系列で状態を持つため、低 QoS を複数フレーム持続させる。
    """
    core = _import_core()
    seq = [fxp.frame_low_qos(ts=float(i), qos=0.05, latency_ms=190.0) for i in range(4)]
    regimes = [v["quality_regime"] for v in core.run_supreme(seq)]
    assert any(r in DEGRADED_BLOCK for r in regimes), (
        f"低 QoS 系列で quality_regime に DEGRADED/BLOCK が現れない: {regimes!r}"
        "(QoS → 観測式 → HGF → quality.classify の結線が効いていない疑い)"
    )


def test_Fbase001_1_wiring_high_qos_yields_good_side():
    """F-基盤-001-1(ADR 0022 決定3・quality 結線の対比): QoS 高の良性系列では quality_regime が
    GOOD 側になりうる(低 QoS と異なる)。

    良性(高 QoS)と低 QoS で quality_regime が変わることで、QoS が quality まで結線されている
    =固定値でないことを固定する。HGF の立ち上がりを許すため複数フレーム持続させ、
    『良性系列に GOOD が現れる』ことを要求する(全フレーム一致までは要求しない)。
    """
    core = _import_core()
    good_seq = [fxp.frame_benign(ts=float(i)) for i in range(5)]
    good_regimes = [v["quality_regime"] for v in core.run_supreme(good_seq)]
    assert any(r == "GOOD" for r in good_regimes), (
        f"高 QoS の良性系列で quality_regime に GOOD が現れない: {good_regimes!r}"
        "(QoS が quality まで結線されていない疑い)"
    )


# ===========================================================================
# scene 結線: 持続変化系列 → scene_regime が CHANGING 側
# (ADR 0019/0022: HGF 層2 が持続的変化を捕捉)
# ===========================================================================

def test_Fbase001_1_wiring_sustained_change_yields_changing_side():
    """F-基盤-001-1(ADR 0022・scene 結線): 観測品質が持続的に変化する系列で scene_regime が
    CHANGING/DEGRADING 側になるフレームがある(全フレーム STABLE に張り付かない)。

    scene の HGF は系列の観測(QoS/品質)変動から潜在水準+ボラティリティを推定する。
    安定 → 急変 → を持続させると HGF 層2 が変化を捉え CHANGING 側になること=scene 結線を固定する。
    """
    core = _import_core()
    # 前半: 安定して高 QoS。後半: 持続的に低 QoS(品質が持続変化する系列)。
    seq = (
        [fxp.frame_benign(ts=float(i)) for i in range(4)]
        + [fxp.frame_low_qos(ts=float(4 + i), qos=0.1, latency_ms=180.0) for i in range(4)]
    )
    regimes = [v["scene_regime"] for v in core.run_supreme(seq)]
    assert any(r in CHANGING_DEGRADING for r in regimes), (
        f"持続変化系列で scene_regime に CHANGING/DEGRADING が現れない: {regimes!r}"
        "(品質変動 → scene HGF の結線が効いていない疑い)"
    )


# ===========================================================================
# t3 結線: mode 系列 → t3_hypothesis(各フレームに v1.4 T3 ラベル)
# ===========================================================================

def test_Fbase001_1_wiring_t3_hypothesis_present_and_in_vocab():
    """F-基盤-001-1(ADR 0022・t3 結線): mode 系列が t3 まで届き、各フレームに v1.4 T3 語彙の
    t3_hypothesis が出る。

    T2 mode の出力系列が t3.step/run_t3_sequence へ結線され、各フレームに 1 つの T3 hypothesis
    (v1.4 10語彙)が組み立てられること=t3 結線を固定する。
    """
    core = _import_core()
    seq = [fxp.frame_conversation(ts=float(i), r_m=2.0, speaking_prob=0.95) for i in range(5)]
    hyps = [v["t3_hypothesis"] for v in core.run_supreme(seq)]
    assert all(h in V14_T3 for h in hyps), (
        f"t3_hypothesis に v1.4 T3 語彙外がある(t3 結線/語彙マッピング不全): {hyps!r}"
    )


# ===========================================================================
# 状態持ち越し(t1/t3/scene/quality-HGF が tick 間で状態を保つ)が結線されている
# ===========================================================================

def test_Fbase001_1_state_carries_over_across_ticks_t1():
    """F-基盤-001-1(ADR 0022・状態持ち越し t1): t1 の状態が tick 間で持ち越され、同じフレームでも
    直前の系列によって結果が変わりうる(pass/depart は前状態 approach があって初めて出る)。

    接近(range 減少)→ 発散(range 増加)の系列で pass/depart が出るのは、t1 が前 tick の
    min_seen/approach 状態を持ち越しているから。状態無持ち越しなら各フレーム単独の tick0 扱いに
    なり pass/depart は出ない(test_F006_t1_state.py 参照)。
    """
    core = _import_core()
    # tick0 接近(range 3.0)→ 発散(range 4.5, cur<5)で pass を引き出す系列。
    seq = [
        fxp.frame_approach(ts=0.0, r_m=3.0, min_TTC_s=8.0),
        fxp.frame_approach(ts=1.0, r_m=4.5, min_TTC_s=8.0),
    ]
    states = [v["t1_state"] for v in core.run_supreme(seq)]
    assert "pass" in states or "depart" in states, (
        f"接近→発散系列で t1_state に pass/depart が出ない: {states!r}"
        "(t1 の状態が tick 間で持ち越されていない=各フレーム独立に処理されている疑い)"
    )


def test_Fbase001_1_state_carryover_changes_output_vs_single_frame():
    """F-基盤-001-1(ADR 0022・状態持ち越しの観測): 状態依存層を前史で『動かす』遷移系列の
    末尾 view と、その同じ最終フレームを単発で流したときの view が一致しないことを固定する。

    観点(直上 ..._t1 テストとは別角度): 直上テストが「接近→発散で t1_state に pass/depart が
    現れる」ことを示すのに対し、本テストは『単発の最終フレーム 8層 view 全体』と『同じ最終
    フレームを末尾に持つ状態蓄積系列の 8層 view 全体』の不一致を、状態を持つ層(t1)の差として
    固定する(= run_supreme が組み立てる 8層 view まで状態持ち越しが伝播していることの確認)。

    根拠の堅さ(バグ非依存・状態を本当に検出する理由):
      旧 fixture は「定常会話 8 フレーム」の末尾が単発と異なることで状態持ち越しを示そうとして
      いたが、定常入力で view が変わっていたのは quality の spurious flip(DEGRADED↔GOOD)という
      バグが唯一の原因で、修正後は正しく single==tail に収束する。よって定常反復ではなく、
      状態依存層が前史で確実に出力を変える『遷移』fixture に置き換える。

      最終フレーム = frame_approach(r_m=4.5)。t1 が状態を持たなければ、この最終フレームは
      単発でも系列末尾でも『各々の tick0(前史なし)』として同一に処理され single==tail に
      なるはず(test_F006_t1_state.py: 前 tick の approach/min_seen が無ければ pass/depart は
      出ず approach 止まり)。実際には系列では前 tick の接近(r_m=3.0)状態が t1 に持ち越され、
      発散(r_m=4.5)が pass(離脱)と判定されて単発(approach)と食い違う。
      → single!=tail は『t1 が前史を持つ』ことだけが理由で成立する(quality バグ非依存)。
    """
    core = _import_core()
    # 最終フレームは両ケースで同一(同じ approach r_m=4.5)。前史の有無だけが違う。
    final_frame = lambda ts: fxp.frame_approach(ts=ts, r_m=4.5, min_TTC_s=8.0)
    # (B) 前史なし: 最終フレームを単発で(t1 にとって tick0)。
    single = core.run_supreme([final_frame(0.0)])[0]
    # (A) 前史あり: 接近(r_m=3.0)→ 同じ最終フレーム(r_m=4.5)。t1 に接近状態が蓄積する。
    seq = [fxp.frame_approach(ts=0.0, r_m=3.0, min_TTC_s=8.0), final_frame(1.0)]
    tail = core.run_supreme(seq)[-1]

    # 8層 view 全体が不一致=状態が view 組み立てまで効いている。
    assert single != tail, (
        "同一の最終フレーム(approach r_m=4.5)を、単発と『接近→発散』系列末尾とで流して "
        f"8層 view が完全一致した: {single!r}"
        "(状態を持つ層が 1 つも結線されていない=最終フレームが前史と無関係に処理されている疑い)"
    )
    # 差を生む層を明示: t1_state(状態を持つ層)。単発は approach、系列末尾は前 tick の
    # 接近状態の持ち越しで pass/depart になる。状態が無ければ両者とも approach=一致のはず。
    assert single["t1_state"] != tail["t1_state"], (
        "8層 view は不一致だが状態層 t1_state は単発と系列末尾で同一: "
        f"single={single['t1_state']!r} tail={tail['t1_state']!r}"
        "(本テストは t1 の状態持ち越しを single!=tail の根拠にしている。t1 が前史で動かないなら"
        "他層の非決定など別要因で偶発的に不一致になっている疑い=状態結線の検出になっていない)"
    )
    assert single["t1_state"] == "approach" and tail["t1_state"] in {"pass", "depart"}, (
        "状態持ち越しの方向が想定外: 単発の最終フレームは approach、系列末尾は前史(接近)の"
        f"持ち越しで pass/depart になるはず。実際 single={single['t1_state']!r} "
        f"tail={tail['t1_state']!r}(t1 の状態持ち越しが期待どおり結線されていない疑い)"
    )


# ===========================================================================
# T3 シナリオ境界 reset(ADR 0022 決定2): 別シナリオ先頭で前状態を引きずらない
# ===========================================================================

def test_Fbase001_1_t3_resets_at_scenario_boundary():
    """F-基盤-001-1(ADR 0022 決定2・T3 シナリオ境界 reset): 別シナリオの先頭フレームでは、
    前シナリオの T3 累積を引きずらない(シナリオ境界で reset=True が T3 へ注入される)。

    検証: (A) conv を長く蓄積したシナリオ sc_prev の直後に、quiet 系の sc_target を流す。
          (B) sc_target を単独で(前史なしで)流す。
    シナリオ境界 reset が効いていれば、sc_target の t3_hypothesis 列は (A)(B) で一致する
    (前シナリオの conv 蓄積が消える)。reset が無いと sc_prev の conv 累積が sc_target に
    漏れて (A)≠(B) になる(test_F009_reset.py の系列リセットと同型)。
    """
    core = _import_core()
    if not hasattr(core, "run_supreme_scenarios"):
        pytest.skip("scenario 単位 API は run_supreme(...) 一本に集約された実装(裁量・ADR 0022)")

    conv_seq = [fxp.frame_conversation(ts=float(i), r_m=2.0, speaking_prob=0.95) for i in range(8)]
    target_seq = [fxp.frame_benign(ts=float(i)) for i in range(4)]

    # (A) 前シナリオ(conv 蓄積)→ target を同一バッチで(シナリオ境界 reset 込み)。
    out_a = core.run_supreme_scenarios({"sc_prev": conv_seq, "sc_target": target_seq})
    t3_a = [v["t3_hypothesis"] for v in out_a["sc_target"]]

    # (B) target を単独で(前史なし=エピソード先頭)。
    out_b = core.run_supreme_scenarios({"sc_target": target_seq})
    t3_b = [v["t3_hypothesis"] for v in out_b["sc_target"]]

    assert t3_a == t3_b, (
        f"sc_target の t3_hypothesis 列が前シナリオ有無で異なる: 前史あり {t3_a} != "
        f"前史なし {t3_b}(シナリオ境界で T3 reset が効かず前シナリオを引きずっている)"
    )


def test_Fbase001_1_within_scenario_t3_does_not_reset_each_frame():
    """F-基盤-001-1(ADR 0022 決定2・reset はシナリオ境界のみ): シナリオ内の各フレームでは
    T3 が毎フレーム reset されない(reset はシナリオ先頭のみ)。

    シナリオ内で会話を持続させると T3 はエピソード集約を育てる。reset が毎フレーム掛かると
    集約が育たず、持続会話シナリオの末尾 t3_hypothesis が先頭(初期状態1フレーム)と同じに
    なってしまう。シナリオ内で t3_hypothesis 列が一様でない(=フレーム間で状態が育つ)ことで、
    reset がシナリオ境界限定であることを固定する。
    """
    core = _import_core()
    if not hasattr(core, "run_supreme_scenarios"):
        pytest.skip("scenario 単位 API は run_supreme(...) 一本に集約された実装(裁量・ADR 0022)")
    # conv 持続 → traffic 切替 を混ぜ、エピソード集約が育つ系列にする。
    seq = []
    for i in range(8):
        if i % 3 == 2:
            seq.append(fxp.frame_siren(ts=float(i)))  # 切替要素
        else:
            seq.append(fxp.frame_conversation(ts=float(i), r_m=2.0, speaking_prob=0.95))
    out = core.run_supreme_scenarios({"sc": seq})
    t3_seq = [v["t3_hypothesis"] for v in out["sc"]]
    assert len(set(t3_seq)) >= 2, (
        f"シナリオ内の t3_hypothesis が全フレーム同一: {t3_seq!r}"
        "(毎フレーム reset されて T3 が状態を育てていない疑い・reset はシナリオ境界のみのはず)"
    )


# ===========================================================================
# harness.score 互換(F-基盤-001-1): 生成 view + gt を harness.score に渡せる
# ===========================================================================

def _gt_from_views(views):
    """生成 view と同形・全層一致の gt を作る(8層キーを揃えた突合用ダミー)。

    harness.score の trace 形状(view+gt の 8層)に view を渡せることのみを検証するための
    決定的 gt(view をそのままコピー=全正解 trace)。GT の正しさは本テストの対象外
    (TEST_STRATEGY 穴5)。
    """
    return [dict(v) for v in views]


def test_Fbase001_1_generated_views_are_scorable_by_harness():
    """F-基盤-001-1(ADR 0022・harness 互換): run_supreme が生成した 8層 view + gt を
    harness.canonical_metric_spec() の score に渡せる(trace 形状が harness 互換)。

    harness の trace 形状は {scenario: [{"ts", "view"{8層}, "gt"{8層}}, ...]}(fixtures_harness)。
    生成 view を view 欄に入れた trace を harness.score に渡し、例外なく 8層の層スコアが
    得られることを固定する(view を gt と同一にすれば全正解 → 各層 acc=1.0)。これにより
    『生成 trace が F-013 採点エンジンに供給可能』(F-基盤-001-1 の最終目的)を 1 ケース固定する。
    """
    core = _import_core()
    from supreme import harness

    snaps = [fxp.frame_conversation(ts=float(i), r_m=2.0, speaking_prob=0.95) for i in range(3)]
    views = core.run_supreme(snaps)
    gts = _gt_from_views(views)

    trace = {
        "sc1": [
            {"ts": float(i), "view": dict(views[i]), "gt": dict(gts[i])}
            for i in range(len(views))
        ]
    }
    result = harness.score(trace, harness.canonical_metric_spec())
    # 8層すべてが採点層に現れ、view==gt(全正解)なので各層 acc=1.0。
    assert set(result.layers) == EIGHT_LAYERS, (
        f"harness が採点した層が 8層と一致しない: {set(result.layers)!r}"
    )
    for layer in result.layers:
        assert result.layer_score(layer) == pytest.approx(1.0), (
            f"{layer}: view==gt の全正解 trace で acc が 1.0 でない(trace 形状の不整合疑い)"
        )


def test_Fbase001_1_build_trace_helper_is_harness_compatible_if_present():
    """F-基盤-001-1(ADR 0022・harness 互換・任意ヘルパ): core が build_trace(scenarios, gt)
    のような trace 組み立てヘルパを公開する場合、その出力は harness.score にそのまま渡せる。

    build_trace は ADR 0022 構成要素6「trace」の組み立てヘルパ(API 名は裁量)。公開されて
    いれば harness 互換(8層 view+gt の trace)であることを 1 ケース固定する。無い場合は
    上の test(手組み trace)で互換性を担保しているため skip する。
    """
    core = _import_core()
    from supreme import harness

    if not hasattr(core, "build_trace"):
        pytest.skip("trace 組み立ては run_supreme の出力を呼び出し側で trace 化する実装(裁量)")

    snaps = [fxp.frame_benign(ts=float(i)) for i in range(2)]
    views = core.run_supreme(snaps)
    gt = {"sc1": _gt_from_views(views)}
    trace = core.build_trace({"sc1": snaps}, gt)
    result = harness.score(trace, harness.canonical_metric_spec())
    assert set(result.layers) == EIGHT_LAYERS
