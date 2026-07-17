"""F-基盤-001-4(ADR 0022)— v1.4 語彙: 8層 view の各値が v1.4 統制語彙に閉じる。
baseline v1.3 logit からの語彙マッピングが適用され、旧語彙(alert_observation /
conv_participation や quality PASS)が出ない。

契約の最終根拠:
  - decisions/0022-fbase001-supreme-runner.md:
      確定事項「語彙マッピング: baseline 流の logit キー ↔ supreme v1.4 統制語彙
      (mode 2クラスリネーム・quality 順位シフト・ADR 0006)」。
      F-基盤-001-4「8層 view は v1.4 統制語彙(baseline logit からの語彙マッピング適用)」。
  - decisions/0006-v14-vocabulary-migration-u7.md:
      mode 10クラス(side_rear_caution/uncertain を含む)・quality GOOD/DEGRADED/BLOCK・
      scene STABLE/CHANGING/DEGRADING。旧 v1.3 の alert_observation/conv_participation・
      quality PASS は v1.4 では出ない(機械マッピング: alert_observation→side_rear_caution、
      conv_participation→uncertain、quality PASS→DEGRADED 等の順位シフト)。
  - specs/SPEC.md F-基盤-001-4(行 223)/ 各層の v1.4 語彙:
      mode 10 / quality 3 / scene 3 / t1 4 / risk_tier 3 / role 6 / relation 4 / t3 10。
  - 各モジュールの語彙定数: tests/test_F006_*(t0/t1/role)・F007(mode)・F008(relation)・
    F011(quality)・F010(scene)・F009(t3)。

スコープ外(ADR 0022・推測でテスト化しない):
  - どの入力がどの語彙ラベルになるか(代表ケース値)は test_Fbase001_wiring.py。本ファイルは
    『語彙集合に閉じる・旧語彙が出ない』という語彙閉包のみを固定する。
  - t1_state は GT 出現 4クラス(idle/approach/pass/depart)に閉じる(ADR 0012 決定E)。
    enum の stop/repeat 等は採点語彙外(出ないことは要求しない=出てもよいが採点 4クラス)。
    本ファイルは『t1_state が 4クラスに閉じる』を採点語彙基準で固定する。

本ファイルが前提とする supreme.core の公開 API:
  core.run_supreme(pso_snapshots, config=None) -> list[frame_view]
"""

import pytest

import fixtures_pso as fxp


# 各層の v1.4 統制語彙(ADR 0006・各 F-006〜011 テストの語彙定数と一致)。
V14_VOCAB = {
    "risk_tier": {"info", "caution", "danger"},
    "t1_state": {"idle", "approach", "pass", "depart"},  # ADR 0012 決定E 採点 4クラス
    "t2_mode": {
        "conv_request", "conv_ongoing", "surround_activity", "forward_caution",
        "side_rear_caution", "alert_required", "emergency", "quiet_standby",
        "env_change", "uncertain",
    },
    "t2_role": {
        "source_speech", "source_vehicle", "source_alarm",
        "source_human", "source_object", "unknown",
    },
    # ADR 0043: catalog 1.4.0 の relation は 6 クラス。ADR 0016 決定4 は当時の dev set(v021_core)に
    # departing/unrelated の勝ち GT が無く 4 クラスに絞っていたが、coverage corpus(GT version 1.4.0)は
    # 両クラスを実値として持つ。supreme は range 幾何でこれらを回収するため語彙を catalog 準拠に戻す。
    "t2_relation": {"addressing_user", "near_user", "approaching", "grouped", "departing", "unrelated"},
    "t3_hypothesis": {
        "quiet_stable", "conv_participating", "sustained_alert", "env_shift", "env_start",
        "crowd_tendency", "traffic_unstable", "hazard_declining", "uncertain_context",
        "alert_required",
    },
    "quality_regime": {"GOOD", "DEGRADED", "BLOCK"},
    "scene_regime": {"STABLE", "CHANGING", "DEGRADING"},
}

# v1.3 旧語彙(v1.4 では機械マッピングで置換され、出てはならない)。
FORBIDDEN_V13_LABELS = {
    "alert_observation",   # → side_rear_caution
    "conv_participation",  # → uncertain
    "PASS",                # quality: PASS → DEGRADED(順位シフト)
}


def _import_core():
    from supreme import core

    return core


def _diverse_sequence():
    """各モジュールが多様なラベルを出すよう設計した混在系列(語彙閉包を広く試す)。"""
    return [
        fxp.frame_benign(ts=0.0),
        fxp.frame_siren(ts=1.0, r_m=25.0, min_TTC_s=1.5),   # danger 側
        fxp.frame_siren(ts=2.0, r_m=30.0, min_TTC_s=15.0),  # caution 側
        fxp.frame_conversation(ts=3.0, r_m=2.0, speaking_prob=0.95),
        fxp.frame_approach(ts=4.0, r_m=8.0, min_TTC_s=4.0),
        fxp.frame_low_qos(ts=5.0, qos=0.05, latency_ms=190.0),
        fxp.frame_low_qos(ts=6.0, qos=0.1, latency_ms=180.0),
        fxp.frame_benign(ts=7.0),
    ]


# ===========================================================================
# 各層が v1.4 統制語彙に閉じる(全フレーム・全層)
# ===========================================================================

def test_Fbase001_4_every_layer_value_in_v14_vocabulary():
    """F-基盤-001-4(ADR 0022/0006・語彙閉包): 多様な系列の全フレーム・全層の view 値が、
    その層の v1.4 統制語彙集合に閉じる。

    8層それぞれが定義された v1.4 語彙(mode 10/quality 3/scene 3/t1 4/risk_tier 3/role 6/
    relation 4/t3 10)のいずれかのみを出すことを固定する(開いた語彙にしない)。
    """
    core = _import_core()
    views = core.run_supreme(_diverse_sequence())
    for i, view in enumerate(views):
        for layer, vocab in V14_VOCAB.items():
            value = view[layer]
            assert value in vocab, (
                f"frame {i} の層 {layer} が v1.4 語彙外: {value!r} "
                f"(許容語彙 {sorted(vocab)!r})"
            )


def test_Fbase001_4_no_v13_legacy_labels_anywhere():
    """F-基盤-001-4(ADR 0022/0006・旧語彙不在): どのフレーム・どの層にも v1.3 旧語彙
    (alert_observation / conv_participation / quality PASS)が現れない。

    語彙マッピング(baseline v1.3 logit → v1.4)が適用されていれば、旧語彙は機械マッピングで
    置換され出力されない。旧語彙が 1 つでも出たらマッピング不全(F-基盤-001-4 違反)。
    """
    core = _import_core()
    views = core.run_supreme(_diverse_sequence())
    for i, view in enumerate(views):
        for layer, value in view.items():
            assert value not in FORBIDDEN_V13_LABELS, (
                f"frame {i} の層 {layer} に v1.3 旧語彙が出力された: {value!r}"
                "(語彙マッピング未適用・F-基盤-001-4 違反)"
            )


# ===========================================================================
# 層別の語彙閉包(各層を個別に固定・どの層が崩れたか分かる粒度)
# ===========================================================================

@pytest.mark.parametrize("layer", sorted(V14_VOCAB.keys()))
def test_Fbase001_4_layer_closed_in_its_v14_vocabulary(layer):
    """F-基盤-001-4(ADR 0022/0006・層別語彙閉包): 各層 {layer} の出力が、その層の v1.4 語彙
    集合に閉じる(parametrize で層ごとに独立に固定)。

    層単位で語彙閉包を見ることで、ある 1 層だけ語彙マッピングが崩れた(例: quality だけ PASS が
    漏れる)ケースを切り分けて検出する。
    """
    core = _import_core()
    vocab = V14_VOCAB[layer]
    values = {v[layer] for v in core.run_supreme(_diverse_sequence())}
    extra = values - vocab
    assert not extra, (
        f"層 {layer} に v1.4 語彙外の値がある: {sorted(extra)!r}(許容 {sorted(vocab)!r})"
    )


# ===========================================================================
# quality の v1.4 順位シフト(PASS が出ない=GOOD/DEGRADED/BLOCK の 3クラス)
# ===========================================================================

def test_Fbase001_4_quality_is_v14_three_class_not_pass():
    """F-基盤-001-4(ADR 0022/0006・quality 順位シフト): quality_regime は v1.4 3クラス
    (GOOD/DEGRADED/BLOCK)に閉じ、v1.3 の PASS が出ない。

    ADR 0006: quality は順位シフト(v1.3 GOOD/PASS/DEGRADED → v1.4 GOOD/DEGRADED/BLOCK)。
    高 QoS〜低 QoS を含む系列で quality_regime が常に 3クラスのいずれかで PASS を含まないことを
    固定する(quality 結線の値は test_Fbase001_wiring.py)。
    """
    core = _import_core()
    regimes = {v["quality_regime"] for v in core.run_supreme(_diverse_sequence())}
    assert regimes.issubset({"GOOD", "DEGRADED", "BLOCK"}), (
        f"quality_regime が v1.4 3クラス外を含む: {sorted(regimes)!r}"
    )
    assert "PASS" not in regimes, (
        "quality_regime に v1.3 の PASS が出ている(順位シフト未適用・F-基盤-001-4 違反)"
    )


# ===========================================================================
# mode の v1.4 10クラス(side_rear_caution/uncertain を含む・旧語彙でない)
# ===========================================================================

def test_Fbase001_4_mode_is_v14_ten_class_not_legacy():
    """F-基盤-001-4(ADR 0022/0006・mode リネーム): t2_mode は v1.4 10クラスに閉じ、v1.3 旧語彙
    (alert_observation / conv_participation)が出ない。

    ADR 0006: mode 2クラスリネーム(alert_observation→side_rear_caution、
    conv_participation→uncertain)。系列の t2_mode が常に v1.4 10クラスで旧語彙を含まないことを
    固定する。
    """
    core = _import_core()
    modes = {v["t2_mode"] for v in core.run_supreme(_diverse_sequence())}
    assert modes.issubset(V14_VOCAB["t2_mode"]), (
        f"t2_mode が v1.4 10クラス外を含む: {sorted(modes - V14_VOCAB['t2_mode'])!r}"
    )
    assert "alert_observation" not in modes and "conv_participation" not in modes, (
        "t2_mode に v1.3 旧語彙が出ている(2クラスリネーム未適用・F-基盤-001-4 違反)"
    )
