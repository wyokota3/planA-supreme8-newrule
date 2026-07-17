"""F-004 公開契約面: supreme.harness モジュールの公開 API が存在し、
ADR 0012 の8層採点仕様を供給可能な「指標非依存の汎用測定エンジン」であること。

specs/SPEC.md F-004 / 対応コンポーネント `harness`。
decisions/0012-u10-evaluation-metrics.md:
  - 採点 = フレーム単位・micro(global pooling: Σ正答/Σ非null)・完全一致(分類)・NA分母除外。
  - 8層 = risk_tier/t1_state/t2_mode/t2_role/t2_relation/t3_hypothesis/quality_regime/scene_regime。
  - 総合 = 8層 global acc の単純平均(層 macro)。
  - Anomaly = 採点対象外(8層に無い)。risk_tier は短尺T0特例NA除外をしない(決定B)。
  - t1_state 採点語彙 = idle/approach/pass/depart(GT出現4クラス)。
  - 補助指標(top2_acc 等)= 参考。公式採点・勝敗は8層 acc のみ。
decisions/0002-tolerances-and-seal-access.md:
  - ε(U5a): 連続値 |a-b| ≤ 1e-9 + 1e-6·max(|a|,|b|)、分類=完全一致。

このファイルは個々の受け入れ条件の振る舞いではなく「契約面(公開シンボルの存在・
最小不変条件)」を固定する。harness は datagov/sealset と疎結合でよい
(指標定義は入力・指標非依存の汎用エンジン)。実装不在のうちは import 段階で失敗する。

設計裁量(指示で明示的に委任された範囲・既存 datagov/sealset/augment の流儀に合わせる):
  harness.canonical_metric_spec() -> MetricSpec
      ADR 0012 の8層 micro acc 仕様を構築済みの指標定義インスタンスを返す。
  harness.score(trace, metric_spec) -> ScoreResult
      フレーム列(view×gt)を指標定義に従って採点する。
  ScoreResult.layer_score(layer) -> float          各層 global acc
  ScoreResult.overall() -> float                   8層 global acc の単純平均
  ScoreResult.layers -> list[str]                  採点した8層名
  harness.check_reproduction(run_a, run_b, *, eps_abs, eps_rel) -> ReproResult
      2回流した出力を受けて再現を判定する(F-004-2)。
  harness.MetricSpecMissingError / ToleranceMissingError: 異常系停止(F-004-3)。
"""

import inspect

import pytest

from supreme import harness


# ---------------------------------------------------------------------------
# 公開シンボルの存在
# ---------------------------------------------------------------------------

def test_F004_harness_module_exposes_canonical_metric_spec():
    """F-004(契約面): harness は ADR 0012 の指標定義を構築する公開関数を持つ。

    指標非依存の汎用エンジンに「正準の指標定義」を供給する入口
    (canonical_metric_spec)が公開されていること。
    """
    assert hasattr(harness, "canonical_metric_spec"), \
        "harness.canonical_metric_spec が公開されていない"
    assert callable(harness.canonical_metric_spec)


def test_F004_harness_module_exposes_score():
    """F-004(契約面): harness は score() を公開する(採点エンジンの入口)。"""
    assert hasattr(harness, "score"), "harness.score が公開されていない"
    assert callable(harness.score)


def test_F004_harness_module_exposes_check_reproduction():
    """F-004-2(契約面): harness は再現判定の入口 check_reproduction() を公開する。"""
    assert hasattr(harness, "check_reproduction"), \
        "harness.check_reproduction が公開されていない"
    assert callable(harness.check_reproduction)


def test_F004_harness_module_exposes_exceptions():
    """F-004-3(契約面): harness は指標定義/許容幅欠落の専用例外を公開する。

    - MetricSpecMissingError: 指標定義 None/未供給で score を呼んだ時(F-004-3)。
    - ToleranceMissingError: 許容幅 None/未供給で再現判定を呼んだ時(F-004-3)。
    どちらも適当な値を埋めず「停止」するための専用例外(SPEC 異常系の精神)。
    """
    for name in ("MetricSpecMissingError", "ToleranceMissingError"):
        assert hasattr(harness, name), f"harness.{name} が公開されていない"
        cls = getattr(harness, name)
        assert isinstance(cls, type) and issubclass(cls, Exception)


# ---------------------------------------------------------------------------
# 指標非依存: score() は指標定義を引数で受け取る(指標が入力である契約)
# ---------------------------------------------------------------------------

def test_F004_score_accepts_metric_spec_argument():
    """F-004(契約面): score() は指標定義を引数として受け取る(指標非依存エンジン)。

    指標定義をハードコードせず外から供給する契約。第2引数または
    metric_spec キーワードで受け取れること。
    """
    sig = inspect.signature(harness.score)
    params = list(sig.parameters)
    # 位置で2つ以上(trace, metric_spec) または metric_spec キーワードを受ける
    assert "metric_spec" in params or len(params) >= 2, \
        "score() が指標定義を引数で受け取らない(指標がハードコードの疑い)"


def test_F004_canonical_metric_spec_covers_eight_layers():
    """F-004(契約面・ADR 0012 決定A/C): 正準指標定義の採点層が8層ちょうど。

    canonical_metric_spec() で構築した指標定義で採点すると、ScoreResult.layers が
    8層(risk_tier/t1_state/t2_mode/t2_role/t2_relation/t3_hypothesis/quality_regime/
    scene_regime)に一致し、Anomaly を含まない(決定C: Anomaly 採点対象外)。
    """
    import fixtures_gt as fx

    spec = harness.canonical_metric_spec()
    result = harness.score(fx.trace_perfect_2scenario(), spec)
    expected = {
        "risk_tier", "t1_state", "t2_mode", "t2_role", "t2_relation",
        "t3_hypothesis", "quality_regime", "scene_regime",
    }
    assert set(result.layers) == expected, (
        f"採点層が8層に一致しない: {sorted(result.layers)}"
    )
    assert "Anomaly" not in result.layers, "Anomaly が採点層に含まれている(決定C 違反)"
    assert len(result.layers) == 8


# ---------------------------------------------------------------------------
# 補助指標は公式スコアと別建て(ADR 0012 決定D)
# ---------------------------------------------------------------------------

def test_F004_auxiliary_metrics_separate_from_official_score():
    """F-004-1(ADR 0012 決定D): 補助指標(top2_acc 等)を勝敗/合否に使わない。

    補助指標API を設けるなら「公式スコアと別建て」であること(参考扱い)。
    決定D: 公式採点・勝敗は8層 global acc のみ。

    本テストは「補助指標を設けるかどうか」自体は実装裁量とするが、
    設けた場合でも overall() / layer_score() が補助指標で汚染されないことを固定する。
    補助指標を取り出す API があれば、それは ScoreResult.auxiliary(...) のように
    公式スコア面とは別の入口で提供されること(公式 layer_score とは別名)。
    """
    import fixtures_harness as fxh

    result = harness.score(fxh.trace_all_correct(), harness.canonical_metric_spec())
    # 公式採点面: overall は8層 acc の単純平均(補助で揺れない)
    assert result.overall() == pytest.approx(1.0)
    # 補助指標を公式の layer_score と同じ入口で混在させていないこと:
    # layers は8層のみで、top2_acc 等の補助指標名を採点層に混ぜていない。
    for aux_name in ("top2_acc", "KL", "range_mae", "mae"):
        assert aux_name not in result.layers, (
            f"補助指標 '{aux_name}' が公式採点層 layers に混在している(決定D 違反)"
        )
