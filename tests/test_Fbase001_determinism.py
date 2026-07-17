"""F-基盤-001-2(ADR 0022)— 決定性: 同じ pso_snapshots + config で 2 回 run_supreme すると
8層 view 列が完全一致する(乱数・時刻なし)。harness.check_reproduction でも合格する。

契約の最終根拠:
  - decisions/0022-fbase001-supreme-runner.md:
      確定事項「決定的(F-004-2)」/ F-基盤-001-2「決定的(同一入力で trace 完全再現・
      F-004-2 合格・乱数/時刻なし)」。
  - specs/SPEC.md F-基盤-001-2(行 221)/ F-004-1(ハーネス自体が乱数で揺れない)/
    F-004-2(ε 再現判定・decisions/0002 U5a: ε_rel=1e-6, ε_abs=1e-9)。
  - tests/test_F004_t3_reproduction.py(harness.check_reproduction の契約・run 形状)。

スコープ外(ADR 0022):
  - 実際の精度・改善(F-013 の成功目標)。本ファイルは「2 回流して完全一致」のみ。
  - 環境跨ぎ(U23)。F-基盤-001 は単一環境・決定的(ε は環境一致が前提)。

本ファイルが前提とする supreme.core / supreme.harness の公開 API:
  core.run_supreme(pso_snapshots, config=None) -> list[frame_view]
  harness.check_reproduction(run_a, run_b, *, eps_abs, eps_rel) -> ReproResult
      (run = フレーム列・各フレーム {"ts", "continuous"{}, "categorical"{}})。
"""

import time

import pytest

import fixtures_pso as fxp

EPS_ABS = 1e-9
EPS_REL = 1e-6


def _import_core():
    from supreme import core

    return core


def _mixed_sequence():
    """各モジュールが動く混在系列(決定性を強く試すため層が動く系列にする)。"""
    return [
        fxp.frame_benign(ts=0.0),
        fxp.frame_siren(ts=1.0, r_m=25.0, min_TTC_s=1.5),
        fxp.frame_conversation(ts=2.0, r_m=2.0, speaking_prob=0.9),
        fxp.frame_approach(ts=3.0, r_m=8.0, min_TTC_s=4.0),
        fxp.frame_low_qos(ts=4.0, qos=0.05, latency_ms=190.0),
    ]


# ===========================================================================
# 8層 view 列が 2 回で完全一致(乱数・時刻なし)
# ===========================================================================

def test_Fbase001_2_two_runs_produce_identical_views():
    """F-基盤-001-2(ADR 0022・決定性・核心): 同一 pso_snapshots + 既定 config で 2 回
    run_supreme すると 8層 view 列が要素単位で完全一致(== で bit 同一)。

    8層は全て分類ラベル(完全一致採点・F-004-1)なので、許容誤差でなく完全一致を要求する。
    乱数・時刻・実行順に依存しないことを最も強い形で固定する。
    """
    core = _import_core()
    seq = _mixed_sequence()
    a = list(core.run_supreme(seq))
    b = list(core.run_supreme(seq))
    assert a == b, "同一入力で run_supreme の 8層 view 列が 2 回で一致しない(非決定的)"


def test_Fbase001_2_two_runs_identical_per_frame_per_layer():
    """F-基盤-001-2(ADR 0022・決定性・層別): 2 回の run_supreme で各フレーム各層が完全一致。

    リスト全体の == に加え、フレーム単位・層単位でも一致を明示する(どこか 1 層でも揺れたら
    検出できる粒度)。
    """
    core = _import_core()
    seq = _mixed_sequence()
    a = list(core.run_supreme(seq))
    b = list(core.run_supreme(seq))
    assert len(a) == len(b)
    for i, (va, vb) in enumerate(zip(a, b)):
        for layer in va.keys():
            assert va[layer] == vb[layer], (
                f"frame {i} の層 {layer} が 2 回で不一致: {va[layer]!r} != {vb[layer]!r}"
            )


def test_Fbase001_2_determinism_independent_of_wall_clock():
    """F-基盤-001-2(ADR 0022・時刻非依存): 間に時間を挟んだ 2 回の run_supreme でも結果が
    変わらない(壁時計に依存しない)。

    時刻を実行に混ぜていないこと(F-012 determinism と同じ精神)を、sleep を挟んだ 2 回で固定する。
    """
    core = _import_core()
    seq = _mixed_sequence()
    a = list(core.run_supreme(seq))
    time.sleep(0.01)
    b = list(core.run_supreme(seq))
    assert a == b, "時間を挟むと結果が変わる(時刻依存=非決定的)"


def test_Fbase001_2_determinism_with_explicit_config():
    """F-基盤-001-2(ADR 0022・決定性・config 指定時): 同一 config を 2 回与えても結果が完全一致。

    config を明示した経路でも決定的であることを固定する。config の中身(キー)には踏み込まず、
    『同じ config を渡せば同じ結果』のみを契約する(config 構造は ADR 0022 で実装裁量)。
    """
    core = _import_core()
    seq = _mixed_sequence()
    # config は空 dict(=既定相当)を 2 回与える。ハイパラ構造に踏み込まない最小形。
    a = list(core.run_supreme(seq, config={}))
    b = list(core.run_supreme(seq, config={}))
    assert a == b, "同一 config 明示時に結果が 2 回で一致しない(非決定的)"


def test_Fbase001_2_runs_do_not_share_mutable_state():
    """F-基盤-001-2(ADR 0022・決定性・呼び出し間の状態漏れ): 連続した複数回の run_supreme で
    呼び出し間に状態が漏れない(前回の run の状態が次回に影響しない)。

    モジュールが状態(t1/t3/scene/quality-HGF)を持つため、run_supreme が呼び出しごとに状態を
    初期化していないと『2 回目の結果が 1 回目と違う』漏れが起きうる。同一入力を 3 回連続で
    流して全て一致することで、run_supreme が呼び出しスコープで状態を閉じている(クリーンに
    初期化している)ことを固定する。
    """
    core = _import_core()
    seq = _mixed_sequence()
    r1 = list(core.run_supreme(seq))
    r2 = list(core.run_supreme(seq))
    r3 = list(core.run_supreme(seq))
    assert r1 == r2 == r3, (
        "連続呼び出しで結果が変わる(run_supreme 間で状態が漏れている=初期化漏れ)"
    )


# ===========================================================================
# harness.check_reproduction でも合格(F-004-2 互換・F-基盤-001-2)
# ===========================================================================

def _view_to_repro_run(views):
    """8層 view 列を check_reproduction の run 形状へ写す。

    8層は全て分類項目なので categorical に入れる(連続値は本機能の view に無い)。
    run = [{"ts", "continuous"{}, "categorical"{8層}}, ...]。
    """
    run = []
    for i, v in enumerate(views):
        run.append({
            "ts": float(i),
            "continuous": {},
            "categorical": dict(v),
        })
    return run


def test_Fbase001_2_passes_harness_check_reproduction():
    """F-基盤-001-2(ADR 0022・F-004-2 合格): 同一入力で 2 回流した 8層 view 列を
    harness.check_reproduction に掛けると再現 OK(reproduced=True・mismatch なし)。

    ADR 0022 F-基盤-001-2「F-004-2 合格」。8層は分類項目=完全一致判定で再現とみなされる
    (test_F004_t3_reproduction.py の categorical 完全一致と同型)。
    """
    core = _import_core()
    from supreme import harness

    seq = _mixed_sequence()
    run_a = _view_to_repro_run(core.run_supreme(seq))
    run_b = _view_to_repro_run(core.run_supreme(seq))
    result = harness.check_reproduction(run_a, run_b, eps_abs=EPS_ABS, eps_rel=EPS_REL)
    assert result.reproduced is True, (
        f"同一入力 2 回流しが再現判定で NG: {list(result.mismatches)!r}"
        "(run_supreme が決定的でない=F-004-2 不合格)"
    )
    assert list(result.mismatches) == [], "再現 OK なのに mismatch が空でない"
