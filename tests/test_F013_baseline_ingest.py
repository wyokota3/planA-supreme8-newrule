"""F-013 baseline 取り込み I/F: load_baseline_scores が canonical layer schema 不一致で停止
（黙って採点しない）し、fixture で正常取り込みできる。

specs/SPEC.md F-013 境界条件:
  「baseline の実行自体は研究者が手動で実施する（自動化対象外）。sealeval は (1)アダプタで
   baseline 入力を生成 → (2)研究者が baseline を実行 → (3)出力を取り込み同一指標で採点する。」
decisions/0023-f013-sealed-evaluation-design.md 決定3:
  「sealeval は baseline を実行しない。研究者が手動で再計測した baseline スコアを
   load_baseline_scores(...) で取り込み、supreme と同一 canonical_metric_spec の layer schema で
   項目別対比する。canonical layer と不一致な baseline 入力は停止（黙って採点しない）。」
decisions/0012-u10-evaluation-metrics.md:
  8層 = risk_tier/t1_state/t2_mode/t2_role/t2_relation/t3_hypothesis/quality_regime/scene_regime。
  Anomaly = 採点対象外（8層に無い）。

F-004 異常系の精神（適当な値を埋めない）を baseline 取り込みにも課す:
  layer schema 不一致は専用例外で停止し、欠落層に既定値を捏造して採点しない。

----------------------------------------------------------------------------
このファイルが定義する supreme.sealeval.load_baseline_scores の前提 API（report 明記）:

  sealeval.load_baseline_scores(source, *, metric_spec=None) -> BaselineScores
    source: 研究者手動の baseline 層 acc（dict {layer: float}）。
    metric_spec: 省略時は canonical_metric_spec() を基準に layer schema を検査する。
    - source の層集合が canonical layer schema（8層）と一致しないと
      sealeval.BaselineSchemaMismatch で停止する（欠落・余分どちらも不一致）。
    - 正常時は ScoreResult 互換の BaselineScores を返す:
        .layer_score(layer) -> float   各層 acc [0,1]
        .layers -> list[str]           8層
        .overall() -> float            8層単純平均（同一指標）

  例外 sealeval.BaselineSchemaMismatch（取り込み停止・黙って採点しない）。

注意（規律）: stdlib のみ・決定的。baseline は再実行しない（取り込むだけ・fixture でモック）。
実装不在のうちは import 段階で失敗する（TDD の期待挙動・red）。
"""

import pytest

import fixtures_sealeval as fxs
from supreme import harness


def _import_sealeval():
    from supreme import sealeval

    return sealeval


# ===========================================================================
# 公開シンボルの存在
# ===========================================================================

def test_F013_load_baseline_scores_exists():
    """F-013（契約面・ADR 0023 決定3）: sealeval は baseline 取り込み I/F を公開する。"""
    sealeval = _import_sealeval()
    assert hasattr(sealeval, "load_baseline_scores")
    assert callable(sealeval.load_baseline_scores)


def test_F013_baseline_schema_mismatch_exception_exists():
    """F-013（契約面）: layer schema 不一致停止の専用例外が公開されている。"""
    sealeval = _import_sealeval()
    assert hasattr(sealeval, "BaselineSchemaMismatch")
    cls = sealeval.BaselineSchemaMismatch
    assert isinstance(cls, type) and issubclass(cls, Exception)


# ===========================================================================
# 正常系: canonical 8層に一致する baseline は取り込める
# ===========================================================================

def test_F013_load_baseline_normal_canonical_layers():
    """F-013（取り込み正常系・ADR 0023 決定3）: canonical 8層に一致する baseline スコアは
    取り込め、ScoreResult 互換の面（layers / layer_score / overall）を持つ。
    """
    sealeval = _import_sealeval()
    baseline = sealeval.load_baseline_scores(
        fxs.baseline_scores_canonical(),
        metric_spec=harness.canonical_metric_spec(),
    )
    assert set(baseline.layers) == set(fxs.EIGHT_LAYERS)
    for layer in fxs.EIGHT_LAYERS:
        assert baseline.layer_score(layer) == pytest.approx(0.50)


def test_F013_load_baseline_overall_is_eight_layer_mean():
    """F-013（同一指標・total）: 取り込んだ baseline の overall() は 8層の単純平均
    （ADR 0012 総合＝8層単純平均・supreme と同一土俵）。
    """
    sealeval = _import_sealeval()
    src = fxs.baseline_scores_with({"t2_mode": 0.60, "scene_regime": 0.40})
    baseline = sealeval.load_baseline_scores(
        src, metric_spec=harness.canonical_metric_spec())
    expected = sum(src[l] for l in fxs.EIGHT_LAYERS) / len(fxs.EIGHT_LAYERS)
    assert baseline.overall() == pytest.approx(expected)


def test_F013_load_baseline_defaults_to_canonical_spec_when_omitted():
    """F-013（既定 spec）: metric_spec 省略時も canonical layer schema を基準に検査する。

    既定で canonical_metric_spec() の 8層を採用（同一指標式が一意）。canonical に一致する
    正常入力は metric_spec 省略でも取り込める。
    """
    sealeval = _import_sealeval()
    baseline = sealeval.load_baseline_scores(fxs.baseline_scores_canonical())
    assert set(baseline.layers) == set(fxs.EIGHT_LAYERS)


# ===========================================================================
# 異常系: layer schema 不一致は停止（黙って採点しない）
# ===========================================================================

def test_F013_load_baseline_missing_layer_stops():
    """F-013（停止・欠落・核心・ADR 0023 決定3）: canonical 層が欠落した baseline は
    BaselineSchemaMismatch で停止する（欠落層に既定値を捏造して採点しない）。

    fixtures_sealeval.baseline_scores_missing_layer: scene_regime 欠落。
    """
    sealeval = _import_sealeval()
    with pytest.raises(sealeval.BaselineSchemaMismatch):
        sealeval.load_baseline_scores(
            fxs.baseline_scores_missing_layer(),
            metric_spec=harness.canonical_metric_spec(),
        )


def test_F013_load_baseline_extra_layer_stops():
    """F-013（停止・余分）: canonical layer schema に無い層（Anomaly 等）が混じる baseline は
    停止する（Anomaly は採点外・ADR 0012 決定C。layer schema 不一致）。

    fixtures_sealeval.baseline_scores_extra_layer: Anomaly 混入。
    """
    sealeval = _import_sealeval()
    with pytest.raises(sealeval.BaselineSchemaMismatch):
        sealeval.load_baseline_scores(
            fxs.baseline_scores_extra_layer(),
            metric_spec=harness.canonical_metric_spec(),
        )


def test_F013_load_baseline_does_not_fabricate_on_mismatch():
    """F-013（捏造禁止）: layer schema 不一致時に「それらしい BaselineScores」を返さない。

    欠落入力で停止せず黙って採点する実装を禁止する（F-004 異常系の精神＝適当な値を埋めない）。
    必ず例外で停止すること（BaselineScores を返さない）。
    """
    sealeval = _import_sealeval()
    raised = False
    try:
        sealeval.load_baseline_scores(
            fxs.baseline_scores_missing_layer(),
            metric_spec=harness.canonical_metric_spec(),
        )
    except sealeval.BaselineSchemaMismatch:
        raised = True
    except Exception:
        # 他の例外でも「停止した（値を埋めて返していない）」は満たす。
        raised = True
    assert raised, "layer schema 不一致で停止せず baseline スコアを返した（捏造の疑い）"


def test_F013_load_baseline_empty_source_stops():
    """F-013（停止・空入力）: 空の baseline 入力（層が1つも無い）は停止する。

    空入力を「全層0」などに捏造して採点しない（黙って採点しない）。
    """
    sealeval = _import_sealeval()
    with pytest.raises(sealeval.BaselineSchemaMismatch):
        sealeval.load_baseline_scores({}, metric_spec=harness.canonical_metric_spec())
