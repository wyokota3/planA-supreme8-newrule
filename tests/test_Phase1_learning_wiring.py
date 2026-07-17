"""Phase1 学習配線(ADR 0025)— core への少量学習 end-to-end 配線の受け入れ契約。

ADR 0019/0020 は scene/t3 に少量学習(`fit`)を設計したが、`core.run_supreme` は**未学習の
既定値**で動いていた(end-to-end で一度も学習していない)。ADR 0025 はこれを配線する:
`core.fit_supreme(practice_scenarios, gt) -> SupremeParams` で t3/scene を**決定的に学習**し、
`core.run_supreme(snaps, params=...)` / `run_supreme_scenarios(scenarios, params=...)` で学習済みに
実走する。**`params=None` は現状の既定挙動(後方互換)**を変えない。

本ファイルは「学習配線の受け入れ条件」を契約化する。観点と関数の対応:
  1. 後方互換(最重要): params=None が params 省略と完全一致(既定挙動を変えない)。
  2. 公開面:           fit_supreme / SupremeParams が公開され callable/型を持つ。
  3. 決定性(F-004-2): 同一練習で 2 回 fit すると同一 params。学習済み run も 2 回完全一致。
  4. 学習済み実走:     params=fit_supreme(...) を run_supreme に渡すと各フレーム 8層が揃う。
  5. in-sample 改善:   練習データを学習 params で採点した acc ≥ 既定 params の acc(t3/scene)。
  6. F-014 過学習ガード: learnable param 総数 ≪ 練習採点フレーム数。fit 前後で count 不変。

契約の最終根拠(設計=契約の出典):
  - decisions/0025-learning-wiring-into-core.md:
      決定1: core.fit_supreme(practice_scenarios, gt) -> SupremeParams。t3/scene を core の
             実経路と一致させて決定的に学習。run_supreme(snaps, params=None) /
             run_supreme_scenarios(scenarios, params=None) は params=None で**現状の既定挙動
             (後方互換)**、params=SupremeParams で学習済み実走。
      決定2: 学習対象は t3/scene のみ(quality は固定ルールで win・mode/relation/strong は scope 外)。
      決定3: F-014 ガード — learnable param 数(t3=6, scene=3)≪ 練習採点フレーム数・configurable k。
             決定的(乱数・時刻なし)・stdlib のみ。
      決定4: params=None 既定で既存テストの挙動を一切変えない。
  - decisions/0020(t3 fit・決定3 fit 決定性 / learnable_param_count)・
    decisions/0019(scene fit・決定3 fit 決定性 / learnable_param_count)。
  - specs/TEST_STRATEGY.md: F-004-2(再現性・同一入力で完全一致/連続は U5a・分類は完全一致)、
    F-014(過学習ガード・param総数 < data×k・方法論検証層・既存 guard 再利用)。
  - 既存呼び出しパターン: tests/test_Fbase001_*.py(run_supreme / run_supreme_scenarios /
    build_trace / harness.score の使い方)、tests/test_F009_fit.py / test_F010_fit.py
    (fit・learnable_param_count・guard.check_param_budget の使い方)。

スコープ外(ADR 0025・推測でテスト化しない):
  - fit の具体手順(grid か座標降下か)・収束した学習値・改善幅の絶対量は ADR 0025 が一意に
    規定しない(CV held-out は別途 scripts/run_cv_train.py で測定する成功目標)。本ファイルは
    『in-sample acc ≥ 既定』(座標降下が train acc を最大化する性質・完全一致でなく `>=`)のみ固定。
  - GT の正しさ(穴5)・実データ(v021_core)依存は対象外。合成 fixture で完結する。
  - mode/relation/quality/strong の学習は ADR 0025 scope 外(t3/scene のみ)。

本ファイルが前提とする supreme.core の公開 API(ADR 0025 / 既存テストの呼び出しパターン):
  core.run_supreme(pso_snapshots, params=None, config=None) -> list[frame_view]
      params=None は既定挙動(後方互換)。params=SupremeParams なら学習済みで実走。
  core.run_supreme_scenarios(scenarios, params=None, config=None)
      -> dict[scenario_id, list[frame_view]]   (同上・シナリオ境界 reset 付き)
  core.fit_supreme(practice_scenarios, gt) -> SupremeParams
      practice_scenarios = {scenario_id: pso_snapshots}(PSO-Snapshot 系列・Snapshot のみ)。
      gt                 = {scenario_id: [gt_view, ...]}(各フレームの 8層 GT view・gt_view は
                           8層キーの一部 or 全部を持つ dict。本ファイルは scene_regime /
                           t3_hypothesis を採点キーとして与える)。
      返り値 SupremeParams は run_supreme(..., params=) に渡せ、学習済み t3/scene params を保持する。
  core.SupremeParams: 型(class)。learnable param 数を取り出せる面を持つ
      (learnable_param_count() -> int。t3=6, scene=3 相当の総数=t3+scene)。
"""

import time

import pytest

import fixtures_pso as fxp


# F-基盤-001 が組み立てる 8層 view のキー(ADR 0022 / SPEC.md)。
EIGHT_LAYERS = {
    "risk_tier",
    "t1_state",
    "t2_mode",
    "t2_role",
    "t2_relation",
    "t3_hypothesis",
    "quality_regime",
    "scene_regime",
}

# F-014 過学習ガードの係数(U24・ADR 0018 決定6)。
K = 0.5


def _import_core():
    """supreme.core を import して返す(実装不在なら ImportError で失敗=TDD 期待)。"""
    from supreme import core

    return core


# ---------------------------------------------------------------------------
# 合成練習データ(決定的・実データ非依存)
#
# scene_regime / t3_hypothesis のラベルが明確に出る構成にする。fixtures_pso の
# frame_* 系列(benign=安定/高QoS、low_qos=持続低品質、conversation=会話持続、
# siren=危険)を使い、各シナリオの GT view を「その系列の代表ラベル」で与える。
# GT の正しさ(穴5)は対象外なので、GT は run_supreme が出しうる v1.4 語彙のラベルで
# 構成する(座標降下が train acc を最大化できる学習信号として機能すればよい)。
# ---------------------------------------------------------------------------

def _stable_scenario(n=6):
    """安定・高 QoS の系列(scene_regime=STABLE が出やすい)。"""
    return [fxp.frame_benign(ts=float(i)) for i in range(n)]


def _degrading_scenario(n=6):
    """安定→持続低品質の系列(後半で scene_regime が CHANGING/DEGRADING 側)。"""
    head = [fxp.frame_benign(ts=float(i)) for i in range(n // 2)]
    tail = [
        fxp.frame_low_qos(ts=float(n // 2 + i), qos=0.08, latency_ms=185.0)
        for i in range(n - n // 2)
    ]
    return head + tail


def _conversation_scenario(n=6):
    """会話持続の系列(t3_hypothesis が conv 系・mode が conv 系)。"""
    return [fxp.frame_conversation(ts=float(i), r_m=2.0, speaking_prob=0.95) for i in range(n)]


def _alert_scenario(n=6):
    """危険(siren)持続の系列(t3_hypothesis が alert 系)。"""
    return [fxp.frame_siren(ts=float(i), r_m=25.0, min_TTC_s=1.5) for i in range(n)]


def _practice_scenarios():
    """合成練習シナリオ {scenario_id: pso_snapshots}(決定的・実データ非依存)。

    scene/t3 のラベルが明確に分かれる 4 系統(stable/degrading/conversation/alert)を含める。
    """
    return {
        "sc_stable": _stable_scenario(),
        "sc_degrading": _degrading_scenario(),
        "sc_conversation": _conversation_scenario(),
        "sc_alert": _alert_scenario(),
    }


def _scene_gt(scenarios):
    """各シナリオの scene_regime GT view を作る(系列の代表ラベルを全フレームに付与)。

    GT view は 8層キーの一部(ここでは scene_regime のみ)を持つ dict の列。採点は
    scene_regime 層のみ。GT の正しさは対象外(穴5)。
    """
    labels = {
        "sc_stable": "STABLE",
        "sc_degrading": "DEGRADING",
        "sc_conversation": "STABLE",
        "sc_alert": "CHANGING",
    }
    return {
        sid: [{"scene_regime": labels[sid]} for _ in snaps]
        for sid, snaps in scenarios.items()
    }


def _t3_gt(scenarios):
    """各シナリオの t3_hypothesis GT view を作る(系列の代表ラベルを全フレームに付与)。

    v1.4 T3 語彙のラベル。GT の正しさは対象外(穴5)で、学習信号として機能すればよい。
    """
    labels = {
        "sc_stable": "quiet_stable",
        "sc_degrading": "env_shift",
        "sc_conversation": "conv_participating",
        "sc_alert": "alert_required",
    }
    return {
        sid: [{"t3_hypothesis": labels[sid]} for _ in snaps]
        for sid, snaps in scenarios.items()
    }


def _acc_on_layer(scenarios, gt, views_by_sid, layer):
    """views_by_sid を gt の指定層で採点した micro acc(Σ正答 / Σ非null)。

    harness の micro pooling(ADR 0012)と同じく全シナリオ×全フレームでプールする。
    gt_view にその層が無い(None)フレームは分母外。
    """
    correct = 0
    total = 0
    for sid in scenarios:
        gt_frames = gt[sid]
        views = views_by_sid[sid]
        for i, view in enumerate(views):
            gt_label = gt_frames[i].get(layer)
            if gt_label is None:
                continue
            total += 1
            if view.get(layer) == gt_label:
                correct += 1
    assert total > 0, "採点対象フレームが 0(練習 fixture の構成ミス)"
    return correct / total


def _run_all(core, scenarios, *, params):
    """全練習シナリオを params で実走し {scenario_id: [view,...]} を返す。

    run_supreme_scenarios があればそれを使い(シナリオ境界 reset・ADR 0022 決定2)、
    無ければ run_supreme をシナリオごとに呼ぶ(裁量実装への両対応)。
    """
    if hasattr(core, "run_supreme_scenarios"):
        return core.run_supreme_scenarios(scenarios, params=params)
    return {sid: list(core.run_supreme(snaps, params=params)) for sid, snaps in scenarios.items()}


# ===========================================================================
# 観点1: 後方互換(最重要)— params=None が params 省略と完全一致
# ===========================================================================

def _mixed_sequence():
    """各層が動く混在系列(後方互換・決定性を強く試す)。"""
    return [
        fxp.frame_benign(ts=0.0),
        fxp.frame_siren(ts=1.0, r_m=25.0, min_TTC_s=1.5),
        fxp.frame_conversation(ts=2.0, r_m=2.0, speaking_prob=0.9),
        fxp.frame_approach(ts=3.0, r_m=8.0, min_TTC_s=4.0),
        fxp.frame_low_qos(ts=4.0, qos=0.05, latency_ms=190.0),
    ]


def test_Phase1_run_supreme_params_none_equals_params_omitted():
    """観点1 後方互換(ADR 0025 決定1/決定4・最重要): run_supreme(snaps, params=None) が
    run_supreme(snaps)(params 省略)と 8層 view 列で完全一致する。

    ADR 0025 決定4「params=None 既定で既存テストの挙動を一切変えない」。学習経路の追加が
    既定挙動を一切変えないことを最も強い形(完全一致)で固定する。これが崩れると既存 740 テストが
    壊れる。
    """
    core = _import_core()
    seq = _mixed_sequence()
    omitted = list(core.run_supreme(seq))
    explicit_none = list(core.run_supreme(seq, params=None))
    assert omitted == explicit_none, (
        "run_supreme(snaps) と run_supreme(snaps, params=None) の 8層 view 列が一致しない"
        "(params=None が既定挙動を変えている=後方互換違反)"
    )


def test_Phase1_run_supreme_scenarios_params_none_equals_omitted():
    """観点1 後方互換(ADR 0025 決定1/決定4): run_supreme_scenarios(scenarios, params=None) が
    params 省略時と完全一致する。

    scenario 単位 API でも params=None が既定挙動を変えないことを固定する(シナリオ境界 reset 込み)。
    run_supreme_scenarios が無い実装(run_supreme 一本化・裁量)では skip。
    """
    core = _import_core()
    if not hasattr(core, "run_supreme_scenarios"):
        pytest.skip("scenario 単位 API は run_supreme(...) 一本に集約された実装(裁量・ADR 0022)")
    scenarios = {"sc1": _mixed_sequence(), "sc2": _stable_scenario(4)}
    omitted = core.run_supreme_scenarios(scenarios)
    explicit_none = core.run_supreme_scenarios(scenarios, params=None)
    assert set(omitted.keys()) == set(explicit_none.keys())
    for sid in omitted:
        assert list(omitted[sid]) == list(explicit_none[sid]), (
            f"{sid}: run_supreme_scenarios の params=None が省略時と一致しない(後方互換違反)"
        )


def test_Phase1_params_none_unchanged_across_repeated_calls():
    """観点1 後方互換(ADR 0025 決定4 / F-基盤-001-2・状態漏れ無し): params=None の run_supreme を
    連続で呼んでも結果が変わらない(学習経路の追加が既定経路に状態を漏らさない)。

    fit_supreme/SupremeParams を追加しても、params=None の経路は呼び出しスコープで状態を閉じ
    続ける(既存の決定性・状態非漏洩を維持する)ことを 3 回連続実行で固定する。
    """
    core = _import_core()
    seq = _mixed_sequence()
    r1 = list(core.run_supreme(seq, params=None))
    r2 = list(core.run_supreme(seq))
    r3 = list(core.run_supreme(seq, params=None))
    assert r1 == r2 == r3, (
        "params=None の連続呼び出しで結果が変わる(学習経路追加で既定経路に状態が漏れている疑い)"
    )


# ===========================================================================
# 観点2: 公開面 — fit_supreme / SupremeParams が公開され callable/型を持つ
# ===========================================================================

def test_Phase1_core_exposes_fit_supreme_callable():
    """観点2 公開面(ADR 0025 決定1): supreme.core は学習入口 fit_supreme() を公開し callable。

    fit_supreme(practice_scenarios, gt) -> SupremeParams が core への学習配線の入口。
    """
    core = _import_core()
    assert hasattr(core, "fit_supreme"), "core.fit_supreme が公開されていない"
    assert callable(core.fit_supreme)


def test_Phase1_core_exposes_supreme_params_type():
    """観点2 公開面(ADR 0025 決定1): supreme.core は学習済み params 型 SupremeParams を公開する。

    fit_supreme の返り値型・run_supreme(params=) に渡す型が公開されていることを固定する。
    """
    core = _import_core()
    assert hasattr(core, "SupremeParams"), "core.SupremeParams が公開されていない"
    assert isinstance(core.SupremeParams, type), "SupremeParams は型(class)であるべき"


def test_Phase1_fit_supreme_returns_supreme_params():
    """観点2 公開面(ADR 0025 決定1): fit_supreme(practice_scenarios, gt) の返り値が
    SupremeParams のインスタンスである。

    返り値が run_supreme(..., params=) に渡せる SupremeParams 型であることを固定する。
    gt は scene/t3 の両層を与える(学習対象は t3/scene のみ・ADR 0025 決定2)。
    """
    core = _import_core()
    scenarios = _practice_scenarios()
    gt = _merged_gt(scenarios)
    params = core.fit_supreme(scenarios, gt)
    assert isinstance(params, core.SupremeParams), (
        f"fit_supreme の返り値が SupremeParams でない: {type(params)!r}"
    )


def _merged_gt(scenarios):
    """scene_regime と t3_hypothesis を 1 つの gt view に統合した {sid: [view,...]}。

    fit_supreme は t3/scene を学習するため、両層の GT を同じ gt view に載せて渡す。
    """
    scene_gt = _scene_gt(scenarios)
    t3_gt = _t3_gt(scenarios)
    merged = {}
    for sid, snaps in scenarios.items():
        frames = []
        for i in range(len(snaps)):
            view = {}
            view.update(scene_gt[sid][i])
            view.update(t3_gt[sid][i])
            frames.append(view)
        merged[sid] = frames
    return merged


# ===========================================================================
# 観点3: 決定性(F-004-2)— 同一練習で 2 回 fit すると同一 params、学習済み run も完全一致
# ===========================================================================

def test_Phase1_fit_supreme_is_deterministic_same_params_twice():
    """観点3 決定性(ADR 0025 決定3 / F-004-2): 同一練習データで fit_supreme を 2 回呼ぶと
    同一 SupremeParams を返す(乱数・時刻なし)。

    学習も決定的(座標降下・grid・乱数なし)。等価性は観測可能な end-to-end 出力で比較する
    (内部表現に踏み込まない)。同一練習で得た 2 つの params を同一入力に実走し、8層 view 列が
    完全一致すれば params は等価とみなす。
    """
    core = _import_core()
    scenarios = _practice_scenarios()
    gt = _merged_gt(scenarios)
    p1 = core.fit_supreme(scenarios, gt)
    p2 = core.fit_supreme(scenarios, gt)
    seq = _mixed_sequence()
    out1 = list(core.run_supreme(seq, params=p1))
    out2 = list(core.run_supreme(seq, params=p2))
    assert out1 == out2, (
        "同一練習データで 2 回 fit した params の run_supreme 出力が不一致(fit 非決定)"
    )


def test_Phase1_trained_run_supreme_is_deterministic():
    """観点3 決定性(ADR 0025 決定3 / F-004-2): 学習済み params での run_supreme を同一入力で
    2 回呼ぶと 8層 view 列が完全一致する(乱数・時刻なし)。

    学習済み経路(params 注入)でも決定性(F-004-2)を保つことを固定する。
    """
    core = _import_core()
    scenarios = _practice_scenarios()
    params = core.fit_supreme(scenarios, _merged_gt(scenarios))
    seq = _mixed_sequence()
    a = list(core.run_supreme(seq, params=params))
    b = list(core.run_supreme(seq, params=params))
    assert a == b, "学習済み params での run_supreme が 2 回で不一致(end-to-end 非決定)"


def test_Phase1_trained_run_determinism_independent_of_wall_clock():
    """観点3 決定性(ADR 0025 決定3・時刻非依存): 学習済み params の run_supreme は間に時間を
    挟んでも結果が変わらない(壁時計に依存しない)。

    時刻を学習済み実走に混ぜていないことを sleep を挟んだ 2 回で固定する。
    """
    core = _import_core()
    scenarios = _practice_scenarios()
    params = core.fit_supreme(scenarios, _merged_gt(scenarios))
    seq = _mixed_sequence()
    a = list(core.run_supreme(seq, params=params))
    time.sleep(0.01)
    b = list(core.run_supreme(seq, params=params))
    assert a == b, "時間を挟むと学習済み run の結果が変わる(時刻依存=非決定的)"


# ===========================================================================
# 観点4: 学習済み params で実走可能 — 各フレーム 8層 view が揃う(壊れない)
# ===========================================================================

def test_Phase1_trained_run_supreme_each_frame_has_eight_layers():
    """観点4 学習済み実走(ADR 0025 決定1): params=fit_supreme(...) を run_supreme に渡すと、
    各フレームに 8層すべての view が揃う(学習配線で結線が壊れない)。

    学習が t3/scene を差し替えても、8層 view の組み立て(epiout stage)が壊れないことを固定する。
    """
    core = _import_core()
    scenarios = _practice_scenarios()
    params = core.fit_supreme(scenarios, _merged_gt(scenarios))
    views = core.run_supreme(_mixed_sequence(), params=params)
    assert len(list(views)) == len(_mixed_sequence())
    for i, view in enumerate(views):
        keys = set(view.keys())
        assert EIGHT_LAYERS.issubset(keys), (
            f"frame {i} の学習済み view に欠けている層がある: 欠落={EIGHT_LAYERS - keys!r}"
        )


def test_Phase1_trained_view_values_are_string_labels():
    """観点4 学習済み実走(ADR 0025 決定1・健全性): 学習済み run の各層値が非空の分類ラベル
    文字列(argmax 済み)である。

    学習が分布や None を漏らさず、各層が 1 つの v1.4 語彙ラベルに確定していること(harness の
    完全一致採点に渡せる形)を固定する。
    """
    core = _import_core()
    scenarios = _practice_scenarios()
    params = core.fit_supreme(scenarios, _merged_gt(scenarios))
    views = core.run_supreme(_mixed_sequence(), params=params)
    for i, view in enumerate(views):
        for layer in EIGHT_LAYERS:
            assert isinstance(view[layer], str) and view[layer] != "", (
                f"frame {i} の層 {layer} が非空文字列ラベルでない: {view[layer]!r}"
            )


def test_Phase1_trained_run_scenarios_has_eight_layers():
    """観点4 学習済み実走(ADR 0025 決定1・scenario 単位): run_supreme_scenarios に学習済み
    params を渡してもシナリオごとに 8層 view が揃う(シナリオ境界 reset 込みで壊れない)。

    run_supreme_scenarios が無い実装(裁量)では skip。
    """
    core = _import_core()
    if not hasattr(core, "run_supreme_scenarios"):
        pytest.skip("scenario 単位 API は run_supreme(...) 一本に集約された実装(裁量・ADR 0022)")
    scenarios = _practice_scenarios()
    params = core.fit_supreme(scenarios, _merged_gt(scenarios))
    out = core.run_supreme_scenarios(scenarios, params=params)
    assert set(out.keys()) == set(scenarios.keys())
    for sid, views in out.items():
        assert len(list(views)) == len(scenarios[sid])
        for view in views:
            assert EIGHT_LAYERS.issubset(set(view.keys())), (
                f"{sid}: 学習済み scenario 単位 view に 8層が揃わない"
            )


# ===========================================================================
# 観点5: 学習が in-sample で既定を下回らない(座標降下が train acc を最大化する性質)
#        同じ練習データを学習 params で採点した acc >= 既定 params の acc(>= ・完全一致不要)
# ===========================================================================

def test_Phase1_in_sample_scene_acc_not_below_default():
    """観点5 in-sample 改善(ADR 0025 決定3・scene): 練習データを学習 params で採点した
    scene_regime の in-sample acc が、既定 params(params=None)の acc 以上(>=)である。

    座標降下/grid は train(=in-sample)acc を最大化する手順なので、同じ練習データでの再代入
    acc は既定を下回らない(ADR 0025 決定3: in-sample は楽観方向)。改善幅の絶対量・CV held-out
    の正直精度は対象外(成功目標)。完全一致(>)は求めず `>=` で固定する。
    """
    core = _import_core()
    scenarios = _practice_scenarios()
    gt = _merged_gt(scenarios)
    params = core.fit_supreme(scenarios, gt)

    default_views = _run_all(core, scenarios, params=None)
    trained_views = _run_all(core, scenarios, params=params)

    acc_default = _acc_on_layer(scenarios, gt, default_views, "scene_regime")
    acc_trained = _acc_on_layer(scenarios, gt, trained_views, "scene_regime")
    assert acc_trained >= acc_default, (
        f"scene_regime の in-sample acc が既定を下回った: 学習={acc_trained} < 既定={acc_default}"
        "(座標降下は train acc を最大化するはず=学習が in-sample で既定を下回らない)"
    )


def test_Phase1_in_sample_t3_acc_not_below_default():
    """観点5 in-sample 改善(ADR 0025 決定3・t3): 練習データを学習 params で採点した
    t3_hypothesis の in-sample acc が、既定 params の acc 以上(>=)である。

    t3 についても座標降下が train acc を最大化する性質を固定する(scene と同方針・`>=`)。
    """
    core = _import_core()
    scenarios = _practice_scenarios()
    gt = _merged_gt(scenarios)
    params = core.fit_supreme(scenarios, gt)

    default_views = _run_all(core, scenarios, params=None)
    trained_views = _run_all(core, scenarios, params=params)

    acc_default = _acc_on_layer(scenarios, gt, default_views, "t3_hypothesis")
    acc_trained = _acc_on_layer(scenarios, gt, trained_views, "t3_hypothesis")
    assert acc_trained >= acc_default, (
        f"t3_hypothesis の in-sample acc が既定を下回った: 学習={acc_trained} < 既定={acc_default}"
        "(座標降下は train acc を最大化するはず=学習が in-sample で既定を下回らない)"
    )


# ===========================================================================
# 観点6: F-014 過学習ガード — learnable param 総数 ≪ 練習採点フレーム数、
#        fit 前後で count 不変
# ===========================================================================

def _practice_scored_frame_count(scenarios):
    """練習データの採点フレーム総数(全シナリオ×全フレーム)。F-014 の data 数に使う。"""
    return sum(len(snaps) for snaps in scenarios.values())


def test_Phase1_supreme_params_exposes_learnable_param_count():
    """観点6 F-014(ADR 0025 決定3): SupremeParams は learnable param 総数を取り出せる面を持つ。

    F-014 の param_count に渡す値。ADR 0025 決定3「t3=6, scene=3」相当の総数(=t3+scene)。
    学習対象は t3/scene のみ(決定2)なので 0 でなく、過大でもない。
    """
    core = _import_core()
    scenarios = _practice_scenarios()
    params = core.fit_supreme(scenarios, _merged_gt(scenarios))
    assert hasattr(params, "learnable_param_count"), (
        "SupremeParams が learnable_param_count() を公開していない(F-014 検査面が無い)"
    )
    count = params.learnable_param_count()
    assert isinstance(count, int) and not isinstance(count, bool), (
        f"learnable_param_count() が int でない: {count!r}"
    )
    assert count >= 1, "学習可能 param 総数が 0(t3/scene を学習するはず)"


def test_Phase1_learnable_param_count_much_less_than_scored_frames():
    """観点6 F-014(ADR 0025 決定3 / F-014-1・過学習ガード): SupremeParams の learnable param
    総数が練習採点フレーム数 × k を厳密に下回り、guard.check_param_budget に合格する。

    ADR 0025 決定3「learnable param 数(t3=6, scene=3)≪ 練習採点フレーム数・configurable k」。
    既存 guard を再利用する(独自再実装しない)。data 数=練習採点フレーム数。
    """
    core = _import_core()
    from supreme import guard

    base = _practice_scenarios()
    base_gt = _merged_gt(base)
    # supreme3: T2(NeuPSL・160 param)を含むため、練習データをフィクスチャ複製で
    # 現実的規模に近づけて「param ≪ data」を検査する(趣旨は不変・ADR 0052-s3)。
    scenarios = {f"rep{i}-{sid}": snaps for i in range(30) for sid, snaps in base.items()}
    gt_rep = {f"rep{i}-{sid}": base_gt[sid] for i in range(30) for sid in base}
    params = core.fit_supreme(scenarios, gt_rep)
    data_count = _practice_scored_frame_count(scenarios)
    r = guard.check_param_budget(
        param_count=params.learnable_param_count(),
        data_count=data_count,
        k=K,
    )
    assert r.passed is True, (
        f"learnable param 総数 {params.learnable_param_count()} が予算 "
        f"{data_count}×{K} を超過(過学習ガード不合格): {r.reason}"
    )
    assert r.guard_id == "F-014-1"


def test_Phase1_learnable_param_count_unchanged_by_fit():
    """観点6 F-014(ADR 0025 決定3・param 数が学習で増えない): fit 前後で learnable param 総数が
    不変である(学習が param を増やさない=予算を後から食い破らない)。

    宣言された学習可能 param 数(t3.learnable_param_count() + scene.learnable_param_count())と、
    fit 後の SupremeParams.learnable_param_count() が一致することを固定する。学習対象は固定リスト。
    """
    core = _import_core()
    from supreme import scene, t3

    scenarios = _practice_scenarios()
    from supreme import neupsl
    declared = (t3.learnable_param_count() + scene.learnable_param_count()
                + neupsl.default_params().learnable_param_count())
    fitted = core.fit_supreme(scenarios, _merged_gt(scenarios)).learnable_param_count()
    assert fitted == declared, (
        f"fit 後の learnable param 総数 {fitted} が宣言された t3+scene の {declared} と異なる"
        "(学習で param 数が変動=予算を後から食い破る疑い)"
    )


def test_Phase1_learnable_param_count_deterministic_across_fits():
    """観点6 F-014(ADR 0025 決定3 / F-004-2・count 決定性): 同一練習で 2 回 fit した
    SupremeParams の learnable param 総数が一致する(学習で param 構成が揺れない)。

    決定性(観点3)と F-014(観点6)の交差: 学習が決定的なら param 数も毎回同じ(2 回の fit で
    count が一致)であることを固定する。
    """
    core = _import_core()
    scenarios = _practice_scenarios()
    gt = _merged_gt(scenarios)
    c1 = core.fit_supreme(scenarios, gt).learnable_param_count()
    c2 = core.fit_supreme(scenarios, gt).learnable_param_count()
    assert c1 == c2, (
        f"2 回の fit で learnable param 総数が不一致: {c1} != {c2}(fit が非決定 or param 構成が揺れる)"
    )
