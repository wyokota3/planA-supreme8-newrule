"""F-013-1: supreme と baseline が同一封印・同一 canonical_metric_spec・同一 layer schema で
測定される（アダプタ＝封印GT＋PSO入力→trace→score の整合）。

specs/SPEC.md F-013-1:
  「supreme と baseline が同一封印・同一指標式で測定される。」
specs/SPEC.md F-013 境界条件:
  「封印シナリオを baseline に流すための入力アダプタ（封印→PSO形式）が必要。」
decisions/0023-f013-sealed-evaluation-design.md:
  決定2: 封印レコードは GT のみ・PSO 入力は別系統。sealeval は (a)PSO 入力と (b)封印 GT を
         scenario_id で対応づけて採点する。seal_scenario_to_pso がこの seam の境界。
  決定3: supreme と baseline を同一 canonical_metric_spec の layer schema で項目別対比。
decisions/0012-u10-evaluation-metrics.md:
  8層 micro acc・完全一致・NA分母除外。total = 8層単純平均。

----------------------------------------------------------------------------
このファイルが定義する supreme.sealeval の前提 API（テスト駆動・report に明記）:

  sealeval.seal_scenario_to_pso(seal_scenario_input) -> list[pso_snapshot]
    封印シナリオ入力 → PSO-Snapshot 系列（contract v1.4）への決定的アダプタ。
    封印 GT は PSO を持たないため（ADR 0023 決定2）、入力源を PSO 形式へ橋渡しする seam。
    同一入力 → 同一出力（決定的・乱数/時刻なし）。

  sealeval が supreme 採点に使う土俵（同一指標）は harness.canonical_metric_spec() で、
  封印 GT を harness の gt ラベル（8層）へ正規化したうえで harness.score に渡す。
  supreme 側 trace（core.run_supreme → 8層 view）と baseline 側の取り込みスコアが、
  **同じ 8層 layer schema** で並ぶことを本ファイルで固定する。

注意（指示・規律）:
  - 本番封印は開けない。常用テストは production=False のダミー封印で経路をドライランする。
  - stdlib のみ・決定的。時刻 issued_ts/revoked_ts/ts はテストが引数で供給する。
  - 実装不在のうちは import 段階で失敗する（TDD の期待挙動・red）。
"""

import pytest

import fixtures_sealeval as fxs
from supreme import harness


def _import_sealeval():
    """supreme.sealeval を import（実装不在なら ImportError で失敗=TDD 期待 red）。"""
    from supreme import sealeval

    return sealeval


# ===========================================================================
# 公開シンボルの存在（sealeval の入口）
# ===========================================================================

def test_F013_1_sealeval_exposes_seal_scenario_to_pso():
    """F-013-1（契約面・ADR 0023 決定2）: sealeval は封印→PSO アダプタを公開する。

    封印 GT は PSO 入力を持たないため、封印シナリオ入力を PSO-Snapshot 系列へ橋渡しする
    seal_scenario_to_pso が公開されていること（同一土俵で supreme を実走するための seam）。
    """
    sealeval = _import_sealeval()
    assert hasattr(sealeval, "seal_scenario_to_pso"), \
        "sealeval.seal_scenario_to_pso が公開されていない"
    assert callable(sealeval.seal_scenario_to_pso)


# ===========================================================================
# アダプタ決定性: 封印シナリオ入力 → PSO 系列が決定的（乱数で揺れない）
# ===========================================================================

def test_F013_1_seal_to_pso_is_deterministic():
    """F-013-1（決定的アダプタ・ADR 0023 決定2）: 同一封印シナリオ入力 →
    同一 PSO-Snapshot 系列（2回呼んで完全一致）。

    アダプタが乱数・時刻に依存しないこと（F-004-1 の決定性精神を seam にも課す）。
    """
    sealeval = _import_sealeval()
    seal_input = fxs.seal_scenario_inputs_two()["SEAL_P"]
    a = sealeval.seal_scenario_to_pso(seal_input)
    b = sealeval.seal_scenario_to_pso(seal_input)
    assert a == b, "seal_scenario_to_pso が決定的でない（2回の出力が不一致）"


def test_F013_1_seal_to_pso_produces_runnable_pso_snapshots():
    """F-013-1（アダプタ整合）: アダプタ出力は core.run_supreme が消費できる
    PSO-Snapshot 系列（Snapshot 形・各要素が version/ts/frame/tracks を持つ dict）。

    封印→PSO→supreme 実走 が一本につながること（seam の健全性）。出力長は入力フレーム数と
    一致する（封印 GT と PSO がフレーム単位で対応づくため）。
    """
    sealeval = _import_sealeval()
    from supreme import core

    seal_input = fxs.seal_scenario_inputs_two()["SEAL_P"]
    snaps = sealeval.seal_scenario_to_pso(seal_input)
    assert len(list(snaps)) == len(seal_input["frames"]), \
        "アダプタ出力の PSO フレーム数が封印シナリオのフレーム数と一致しない"
    # core.run_supreme に渡せる（8層 view が揃う）= 同一土俵で supreme を実走できる。
    views = core.run_supreme(snaps)
    assert len(list(views)) == len(list(snaps))
    for view in views:
        assert fxs.EIGHT_LAYERS == tuple(
            k for k in fxs.EIGHT_LAYERS if k in view
        ), "アダプタ→run_supreme の view に 8層が揃っていない"


# ===========================================================================
# 同一 layer schema: supreme 採点と baseline 取り込みが同じ 8層で並ぶ
# ===========================================================================

def test_F013_1_supreme_scored_on_canonical_eight_layers():
    """F-013-1（同一指標・supreme 側）: 封印 GT を harness gt へ正規化し、アダプタ→
    run_supreme→build した trace を canonical_metric_spec で採点すると、採点層が
    8層ちょうど（ADR 0012 決定A/C・Anomaly 採点外）。

    supreme 側が「同一指標式の 8層 layer schema」で測られていることを固定する。
    """
    sealeval = _import_sealeval()
    from supreme import core

    seal_input = fxs.seal_scenario_inputs_two()["SEAL_P"]
    snaps = sealeval.seal_scenario_to_pso(seal_input)
    views = core.run_supreme(snaps)
    # view==gt（全正解）の harness 互換 trace を組み（GT 正しさは本テスト対象外・穴5）、
    # canonical_metric_spec で採点する。採点層が 8層であることを固定。
    trace = {
        "SEAL_P": [
            {"ts": float(i), "view": dict(views[i]), "gt": dict(views[i])}
            for i in range(len(views))
        ]
    }
    result = harness.score(trace, harness.canonical_metric_spec())
    assert set(result.layers) == set(fxs.EIGHT_LAYERS), (
        f"supreme 採点層が canonical 8層に一致しない: {sorted(result.layers)}"
    )
    assert "Anomaly" not in result.layers, "Anomaly が採点層に混入（決定C 違反）"


def test_F013_1_baseline_loaded_on_same_layer_schema_as_supreme():
    """F-013-1（同一指標・同一 layer schema）: baseline 取り込みスコアの層集合が、
    supreme 採点（canonical_metric_spec）の層集合と一致する。

    同一封印・同一指標式（ADR 0023 決定3）。supreme と baseline が並んで項目別対比できる
    前提＝両者が**同じ 8層 layer schema** で表現されていることを固定する。
    """
    sealeval = _import_sealeval()
    spec = harness.canonical_metric_spec()

    baseline = sealeval.load_baseline_scores(fxs.baseline_scores_canonical(),
                                             metric_spec=spec)
    # baseline は ScoreResult と同じ面（layer_score/overall/layers）を持つ前提。
    assert set(baseline.layers) == set(fxs.EIGHT_LAYERS), (
        f"baseline の層集合が canonical 8層と一致しない: {sorted(baseline.layers)}"
    )


def test_F013_1_same_canonical_spec_used_for_both_sides():
    """F-013-1（同一指標式の一意性）: supreme 採点と baseline 取り込みが、同じ
    canonical_metric_spec（同一 layer schema）を共有する。

    canonical_metric_spec() を2回構築しても layer schema が同一であること（指標式が一意・
    決定的）を、supreme 採点層 == baseline 取り込み層 で固定する。
    """
    sealeval = _import_sealeval()
    spec = harness.canonical_metric_spec()

    # supreme 側の採点層（全正解 trace で確認）。
    result = harness.score(_all_correct_trace(), spec)
    supreme_layers = set(result.layers)

    baseline = sealeval.load_baseline_scores(fxs.baseline_scores_canonical(),
                                             metric_spec=spec)
    assert supreme_layers == set(baseline.layers), (
        "supreme 採点層と baseline 取り込み層が同一 layer schema でない"
    )


def _all_correct_trace():
    """8層 view==gt の最小 trace（同一 layer schema 確認用）。"""
    import fixtures_harness as fxh

    return fxh.trace_all_correct()
