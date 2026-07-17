"""F-009-1 再現性: 同一入力系列+同一リセット列+同一 params で T3 出力が完全再現。

これは「状態保持+学習モジュール」のテストである。fit で決まる実際の学習値は F-013 の成功目標。
本ファイルは F-009-1(再現性・F-004-2 合格)を契約化する: 同じ (mode 系列, reset 系列, params)
で2回流すと hypothesis 系列が**完全一致**(決定的・乱数/時刻なし)であること、および既存
harness.check_reproduction(F-004)で T3 出力列の再現が合格になること。

契約の最終根拠:
  - specs/SPEC.md F-009-1:「同一入力系列+同一リセット列で出力が再現(F-004-2 の判定に合格)」。
  - decisions/0020-f009-t3-episode-learning.md 決定3(F-009-1):
      同一入力系列+同一リセット列で出力が完全再現(決定的状態機構・乱数/時刻なし・F-004-2 合格)。
  - decisions/0002-tolerances-and-seal-access.md(U5a・ε の正):
      連続値 |a−b| ≤ ε_abs + ε_rel·max(|a|,|b|)(ε_rel=1e-6, ε_abs=1e-9)・分類は完全一致。
  - specs/SPEC.md F-004-2(T3 再現判定)/ decisions/0006(v1.4 T3 語彙)。

スコープ外(ADR 0020・推測でテスト化しない):
  - fit 後の厳密な学習値・実際の T3 acc 改善(F-013 の成功目標)。本ファイルは「2回流すと完全一致」
    のみを固定し、出力が何になるか(値の正しさ)には踏み込まない。

テストが前提とする supreme.t3 / supreme.harness の公開 API(設計裁量・指示で委任):
  t3.run_t3_sequence(mode_seq, reset_seq, params) -> list[hypothesis]  (test_F009_state.py 参照)
  harness.check_reproduction(run_a, run_b, *, eps_abs, eps_rel) -> ReproResult
      (test_F004_t3_reproduction.py 参照・分類完全一致 ∧ 連続値 ε 内で .reproduced=True)
"""

import pytest

from supreme import harness, t3

EPS_ABS = 1e-9
EPS_REL = 1e-6


def _mode(label, posterior=0.5):
    return {"mode": label, "posterior": posterior}


def _conv(posterior=0.7):
    return _mode("conv_strong", posterior)


def _quiet(posterior=0.2):
    return _mode("quiet", posterior)


def _traffic(posterior=0.5):
    return _mode("traffic", posterior)


def _scenario():
    """再現性検証用の固定シナリオ(乱数なし)。conv 持続 → reset → 切替不安定 → quiet。

    reset を途中に挟むことで「同一リセット列」の再現も同時に固定する(F-009-1 の核心:
    入力系列だけでなくリセット列も同じなら出力も同じ)。
    """
    mode_seq = [
        _conv(0.7), _conv(0.72), _conv(0.68),    # conv 持続
        _quiet(0.2),                              # frame: reset 注入(下の reset_seq で True)
        _traffic(0.5), _quiet(0.3), _traffic(0.55),  # 切替不安定
        _quiet(0.2), _quiet(0.21),                # quiet 安定
    ]
    reset_seq = [False, False, False, True, False, False, False, False, False]
    return mode_seq, reset_seq


# ===========================================================================
# F-009-1: 同一 (mode 系列, reset 系列, params) で2回流すと hypothesis 系列が完全一致
# ===========================================================================

def test_F009_1_same_sequence_same_reset_reproduces_exactly():
    """F-009-1(ADR 0020 決定3・再現性・完全一致): 同一 mode 系列 + 同一 reset 列 + 同一 params で
    run_t3_sequence を2回流すと hypothesis 系列が完全一致する(決定的・乱数/時刻なし)。

    分類項目(T3 hypothesis)は完全一致(ε を使わない)。状態機構が乱数/時刻に依存しないことの
    end-to-end 確認。
    """
    mode_seq, reset_seq = _scenario()
    params = t3.default_params()
    out_a = list(t3.run_t3_sequence(mode_seq, reset_seq, params))
    out_b = list(t3.run_t3_sequence(mode_seq, reset_seq, params))
    assert out_a == out_b, (
        f"同一系列+同一 reset+同一 params で T3 hypothesis 列が2回で不一致(非決定): "
        f"{out_a} != {out_b}"
    )


def test_F009_1_reproduces_across_repeated_runs():
    """F-009-1(ADR 0020 決定3・再現性・反復): 同一入力を3回以上流しても毎回同一の hypothesis 列
    (決定性が単発の偶然でない)。
    """
    mode_seq, reset_seq = _scenario()
    params = t3.default_params()
    runs = [list(t3.run_t3_sequence(mode_seq, reset_seq, params)) for _ in range(3)]
    assert runs[0] == runs[1] == runs[2], (
        f"反復実行で T3 hypothesis 列が揺れた(非決定): {runs}"
    )


def test_F009_1_different_reset_list_can_change_output():
    """F-009-1(ADR 0020 決定3・リセット列が出力に効く): 同一 mode 系列でも reset 列が異なれば
    出力が変わりうる(reset 列も再現の構成要素であることの裏付け)。

    F-009-1 は『同一入力系列 *かつ* 同一リセット列 → 同一出力』を主張する。リセット列が出力に
    寄与しなければ「同一リセット列」を条件に含める意味が無い。途中で reset するか否かで
    出力列が変わりうることを固定し、reset が再現の本質的構成要素であることを示す。
    (両者が偶然一致する可能性を排除するため、reset 直後に強い文脈差が出る系列を使う。)
    """
    params = t3.default_params()
    # conv を長く蓄積した後、frame#6 で切り替える系列。
    mode_seq = [_conv(0.75)] * 6 + [_quiet(0.2)] * 4
    reset_never = [False] * len(mode_seq)
    # frame#6 直前(index 6)で reset を注入 → conv 蓄積がそこで消える。
    reset_at_6 = [False] * 6 + [True] + [False] * 3
    out_never = list(t3.run_t3_sequence(mode_seq, reset_never, params))
    out_reset = list(t3.run_t3_sequence(mode_seq, reset_at_6, params))
    # 少なくとも reset 後のどこかのフレームで出力が変わる(reset が状態=出力に効く)。
    assert out_never != out_reset, (
        "reset の有無で出力列が一切変わらない(reset が状態/出力に効いていない=F-009-2 と矛盾)"
    )


# ===========================================================================
# F-009-1 ∧ F-004-2: harness.check_reproduction で T3 出力列の再現が合格になる
# ===========================================================================

def _to_repro_run(hyp_seq, mode_seq):
    """T3 hypothesis 列 + mode posterior 列を harness の repro run 形式へ変換する。

    各フレーム = {"ts", "continuous": {"t3_posterior": ...}, "categorical": {"t3_hypothesis": ...}}。
    分類(t3_hypothesis)は完全一致判定、連続値(t3_posterior)は ε 許容判定の対象。
    """
    run = []
    for i, (h, m) in enumerate(zip(hyp_seq, mode_seq)):
        run.append({
            "ts": float(i),
            "continuous": {"t3_posterior": float(m["posterior"])},
            "categorical": {"t3_hypothesis": h},
        })
    return run


def test_F009_1_harness_check_reproduction_passes_for_t3_output():
    """F-009-1 ∧ F-004-2(ADR 0020 決定3 / ADR 0002): T3 を同一系列+同一リセット列で2回流し、
    その出力列を harness.check_reproduction に渡すと再現合格(.reproduced=True)になる。

    F-009-1 は「F-004-2 の判定に合格」を要求する。2回の T3 出力(分類=hypothesis・連続値=
    posterior)を F-004 の再現判定器に通し、分類完全一致 ∧ 連続値 ε 内で合格することを固定する。
    """
    mode_seq, reset_seq = _scenario()
    params = t3.default_params()
    hyp_a = list(t3.run_t3_sequence(mode_seq, reset_seq, params))
    hyp_b = list(t3.run_t3_sequence(mode_seq, reset_seq, params))
    run_a = _to_repro_run(hyp_a, mode_seq)
    run_b = _to_repro_run(hyp_b, mode_seq)
    result = harness.check_reproduction(run_a, run_b, eps_abs=EPS_ABS, eps_rel=EPS_REL)
    assert result.reproduced is True, (
        f"T3 の2回流し出力が F-004-2 再現判定に合格しない: {list(result.mismatches)}"
    )
    assert list(result.mismatches) == [], "再現合格なのに mismatch が空でない"


def test_F009_1_harness_detects_drift_when_hypothesis_differs():
    """F-009-1 ∧ F-004-2(陰性・ドリフト検出): T3 hypothesis 列が1フレームでも食い違うと、
    harness.check_reproduction は再現NG(.reproduced=False)を返す。

    再現判定が『hypothesis 完全一致』を正しく見ていることの裏付け(=本物の再現を測れている)。
    人工的に1フレームだけ hypothesis を改変し、再現NG になることを固定する。
    """
    mode_seq, reset_seq = _scenario()
    params = t3.default_params()
    hyp = list(t3.run_t3_sequence(mode_seq, reset_seq, params))
    run_a = _to_repro_run(hyp, mode_seq)
    # 1フレームだけ hypothesis を別の v1.4 語彙へ改変(ドリフト相当)。
    drifted = list(hyp)
    other = "alert_required" if drifted[0] != "alert_required" else "quiet_stable"
    drifted[0] = other
    run_b = _to_repro_run(drifted, mode_seq)
    result = harness.check_reproduction(run_a, run_b, eps_abs=EPS_ABS, eps_rel=EPS_REL)
    assert result.reproduced is False, (
        "T3 hypothesis が食い違うのに再現OKと誤判定(再現判定が hypothesis を見ていない)"
    )
