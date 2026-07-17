"""F-004-2: T3 再現判定(2回流した出力を受け取り、ε 内・分類完全一致で再現を判定)。

specs/SPEC.md F-004-2:
  「T3 は『同一入力系列＋同一リセット列を2回流し、連続値が
    |a−b| ≤ ε_abs + ε_rel·max(|a|,|b|)(ε_rel=1e-6, ε_abs=1e-9。U5a)以内・
    分類項目が完全一致』を判定できる。」
decisions/0002-tolerances-and-seal-access.md(U5a・ε の正):
  - 連続値: |a−b| ≤ ε_abs + ε_rel·max(|a|,|b|)、ε_rel=1e-6、ε_abs=1e-9(numpy.isclose と同形)。
  - 分類項目: 完全一致。
注: harness は supreme を実行しない。2回分の出力(run)を受け取って判定する(指示)。

テストが前提とする supreme.harness の公開 API(設計裁量・指示で委任):
  harness.check_reproduction(run_a, run_b, *, eps_abs, eps_rel) -> ReproResult
    .reproduced -> bool         全項目が再現条件を満たすか(連続値ε内 ∧ 分類完全一致)
    .mismatches -> list         再現しなかった項目の内訳(空なら再現)
  run = フレーム列。各フレーム:
    {"ts": float,
     "continuous": {"<項目>": float, ...},   # ε 許容判定
     "categorical": {"<項目>": str, ...}}     # 完全一致判定

ε の式は ADR 0002(U5a)に固定。境界(|a−b| == 閾値)は「以下(≤)」で再現とみなす。
"""

import pytest

import fixtures_harness as fxh
from supreme import harness

EPS_ABS = 1e-9
EPS_REL = 1e-6


def _check(run_a, run_b):
    return harness.check_reproduction(
        run_a, run_b, eps_abs=EPS_ABS, eps_rel=EPS_REL
    )


# ---------------------------------------------------------------------------
# 陽性: ε 内 → 再現OK
# ---------------------------------------------------------------------------

def test_F004_2_identical_runs_reproduce():
    """F-004-2: 完全に同一の2 run は再現OK。"""
    run = fxh.repro_run(t3_posterior=0.5, stability=0.8, hypothesis="indoor_quiet")
    result = _check(run, run)
    assert result.reproduced is True
    assert list(result.mismatches) == []


def test_F004_2_continuous_within_eps_reproduces():
    """F-004-2(陽性): 連続値の差が ε 未満なら再現OK。

    a=0.5, b=0.5 + 1e-10 → 差 1e-10。
    閾値 = 1e-9 + 1e-6·0.5 ≈ 5.01e-7。1e-10 < 閾値 → 再現OK。
    """
    run_a = fxh.repro_run(t3_posterior=0.5, stability=0.8, hypothesis="indoor_quiet")
    run_b = fxh.repro_run(t3_posterior=0.5 + 1e-10, stability=0.8,
                          hypothesis="indoor_quiet")
    result = _check(run_a, run_b)
    assert result.reproduced is True, f"ε内の差を再現NGと誤判定: {list(result.mismatches)}"


def test_F004_2_continuous_relative_eps_for_large_values():
    """F-004-2(陽性): 相対項が効く大きな値でも ε 内なら再現OK。

    a=1e6, b=1e6 + 0.4 → 差 0.4。
    閾値 = 1e-9 + 1e-6·1e6 = 1e-9 + 1.0 ≈ 1.0。0.4 < 1.0 → 再現OK。
    (相対項 ε_rel·max(|a|,|b|) が効く確認。絶対項だけなら誤判定する)
    """
    run_a = fxh.repro_run(t3_posterior=1e6, stability=0.8, hypothesis="indoor_quiet")
    run_b = fxh.repro_run(t3_posterior=1e6 + 0.4, stability=0.8,
                          hypothesis="indoor_quiet")
    result = _check(run_a, run_b)
    assert result.reproduced is True, (
        f"相対 ε 内の大きな値の差を再現NGと誤判定: {list(result.mismatches)}"
    )


# ---------------------------------------------------------------------------
# 陰性: ε 超 → 再現NG
# ---------------------------------------------------------------------------

def test_F004_2_continuous_beyond_eps_does_not_reproduce():
    """F-004-2(陰性): 連続値の差が ε を超えると再現NG。

    a=0.5, b=0.5 + 1e-3 → 差 1e-3。
    閾値 ≈ 5.01e-7。1e-3 ≫ 閾値 → 再現NG(T3 ドリフト相当)。
    """
    run_a = fxh.repro_run(t3_posterior=0.5, stability=0.8, hypothesis="indoor_quiet")
    run_b = fxh.repro_run(t3_posterior=0.5 + 1e-3, stability=0.8,
                          hypothesis="indoor_quiet")
    result = _check(run_a, run_b)
    assert result.reproduced is False, "ε超の差(ドリフト)を再現OKと誤判定"
    assert len(list(result.mismatches)) >= 1, "再現NGなのに mismatch が空"


def test_F004_2_mismatch_identifies_offending_continuous_item():
    """F-004-2(陰性): mismatch に再現しなかった連続項目が特定される。

    t3_posterior だけ ε 超・stability は一致 → t3_posterior が mismatch に含まれる。
    """
    run_a = fxh.repro_run(t3_posterior=0.5, stability=0.8, hypothesis="indoor_quiet")
    run_b = fxh.repro_run(t3_posterior=0.9, stability=0.8, hypothesis="indoor_quiet")
    result = _check(run_a, run_b)
    assert result.reproduced is False
    flat = repr(list(result.mismatches))
    assert "t3_posterior" in flat, (
        f"再現失敗した項目 t3_posterior が mismatch に出ない: {flat}"
    )


# ---------------------------------------------------------------------------
# 分類項目: 完全一致で再現判定
# ---------------------------------------------------------------------------

def test_F004_2_categorical_exact_match_reproduces():
    """F-004-2(陽性): 分類項目が一致すれば(連続値も ε 内なら)再現OK。"""
    run_a = fxh.repro_run(t3_posterior=0.5, stability=0.8, hypothesis="indoor_quiet")
    run_b = fxh.repro_run(t3_posterior=0.5, stability=0.8, hypothesis="indoor_quiet")
    result = _check(run_a, run_b)
    assert result.reproduced is True


def test_F004_2_categorical_mismatch_does_not_reproduce():
    """F-004-2(陰性): 分類項目が不一致なら(連続値が完全一致でも)再現NG。

    分類は ε を使わず完全一致。t3_hypothesis が異なれば再現NG。
    """
    run_a = fxh.repro_run(t3_posterior=0.5, stability=0.8, hypothesis="indoor_quiet")
    run_b = fxh.repro_run(t3_posterior=0.5, stability=0.8, hypothesis="outdoor_busy")
    result = _check(run_a, run_b)
    assert result.reproduced is False, "分類項目の不一致を再現OKと誤判定"
    flat = repr(list(result.mismatches))
    assert "t3_hypothesis" in flat, (
        f"再現失敗した分類項目 t3_hypothesis が mismatch に出ない: {flat}"
    )


# ---------------------------------------------------------------------------
# 境界: |a−b| == 閾値 ちょうどの扱い(ADR 0002 の式 ≤ に従う)
# ---------------------------------------------------------------------------

def test_F004_2_continuous_exactly_at_threshold_reproduces():
    """F-004-2(境界): |a−b| がちょうど閾値に等しい時は再現OK(式が ≤ のため)。

    ADR 0002(U5a): |a−b| ≤ ε_abs + ε_rel·max(|a|,|b|)。等号成立は「以下」で再現。
    a=0、b=ε_abs(=1e-9)とすると max(|a|,|b|)=1e-9、
    閾値 = 1e-9 + 1e-6·1e-9 = 1e-9 + 1e-15。差 = 1e-9 ≤ 閾値 → 再現OK。
    """
    run_a = fxh.repro_run(t3_posterior=0.0, stability=0.8, hypothesis="indoor_quiet")
    run_b = fxh.repro_run(t3_posterior=EPS_ABS, stability=0.8,
                          hypothesis="indoor_quiet")
    result = _check(run_a, run_b)
    assert result.reproduced is True, (
        "閾値ちょうど(差=ε_abs)を再現NGと誤判定(式の ≤ に反する)"
    )


def test_F004_2_continuous_just_beyond_threshold_does_not_reproduce():
    """F-004-2(境界): 閾値をわずかに超えると再現NG。

    a=0、b=2e-9 とすると 閾値 ≈ 1e-9 + 微小。差 = 2e-9 > 閾値 → 再現NG。
    (閾値ちょうど=再現OK と、わずかに超え=再現NG の境界の両側を固定する)
    """
    run_a = fxh.repro_run(t3_posterior=0.0, stability=0.8, hypothesis="indoor_quiet")
    run_b = fxh.repro_run(t3_posterior=2e-9, stability=0.8,
                          hypothesis="indoor_quiet")
    result = _check(run_a, run_b)
    assert result.reproduced is False, "閾値超え(差=2·ε_abs)を再現OKと誤判定"


# ---------------------------------------------------------------------------
# 決定性: 再現判定自体も2回呼んで同一(ハーネスが乱数で揺れない)
# ---------------------------------------------------------------------------

def test_F004_2_reproduction_check_is_deterministic():
    """F-004-2 ∧ F-004-1: 同じ2 run で check_reproduction を2回呼ぶと結果同一。"""
    run_a = fxh.repro_run(t3_posterior=0.5, stability=0.8, hypothesis="indoor_quiet")
    run_b = fxh.repro_run(t3_posterior=0.5 + 1e-3, stability=0.8,
                          hypothesis="indoor_quiet")
    r1 = _check(run_a, run_b)
    r2 = _check(run_a, run_b)
    assert r1.reproduced == r2.reproduced
    assert list(r1.mismatches) == list(r2.mismatches)
