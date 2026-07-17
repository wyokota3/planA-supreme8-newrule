"""F-013 全null層固定: 全null層（nonnull=0）で harness.overall() が当該層を平均から除外する
挙動を固定し、sealeval が当該層項目を no_data 扱いにする。

specs/SPEC.md F-013 着手条件（2026-06-13 監査由来・F-004）:
  「harness の全null層(nonnull=0)の総合算入方法（現状=overall から除外）が、F-013 の同一土俵
   比較で全null層が起きうる設計なら妥当か再評価し、overall() の当該挙動を固定するテストを追加。」
decisions/0012-u10-evaluation-metrics.md（ADR 0012 追記）:
  NA 分母除外。全null層（分母0）は overall から除外（明文化済み）。
decisions/0023-f013-sealed-evaluation-design.md 決定4:
  封印で全null層（nonnull=0）が起きうる前提で overall() の「当該層を平均から除外」挙動を固定。
  封印に当該層データが無い項目は no_data として勝敗から除外（draw 扱いにしない）。

このファイルは2点を固定する:
  (1) harness.overall() が全null層を平均から除外する（= 残り7層の単純平均になる）。
  (2) sealeval が全null層の項目を no_data として勝敗から除外する（F-013-2 決定4 の一貫）。

----------------------------------------------------------------------------
前提 API:
  harness.score(trace, canonical_metric_spec()) -> ScoreResult
    .overall() は全null層を平均から除外する（ADR 0012/0023 決定4）。
    全null層の layer_score は実装裁量（NaN/None/採点除外）だが、overall は除外で算出。
  sealeval が封印 GT から作るスコアの全null層は layer_score(layer) -> None として表現され、
  compare_items でその項目は no_data になる（test_F013_verdict.py と一貫）。
"""

import math

import pytest

import fixtures_harness as fxh
import fixtures_sealeval as fxs
from supreme import harness


def _spec():
    return harness.canonical_metric_spec()


# ===========================================================================
# (1) harness.overall() が全null層を平均から除外する
# ===========================================================================

def test_F013_all_null_layer_excluded_from_overall(tmp_path):
    """F-013（全null層固定・核心）: ある層の gt が全フレーム null のとき、overall() は
    その層を平均から除外する（= 採点できた層だけの単純平均）。

    fixtures_harness.trace_na_all_null_layer: quality_regime 全null・他7層は全正解。
    → 全null層を除外すれば overall = 7層×1.0 / 7 = 1.0。
    （もし全null層を 0 として算入すると overall < 1.0 になり一致しない＝除外を固定する。）
    """
    result = harness.score(fxh.trace_na_all_null_layer(), _spec())
    assert result.overall() == pytest.approx(1.0), (
        f"全null層を平均から除外していない（overall={result.overall()}・"
        f"全null層を 0 算入の疑い）"
    )


def test_F013_all_null_layer_overall_is_mean_of_scored_layers_only(tmp_path):
    """F-013（全null層固定・一般化）: overall() が「採点できた層のみ」の単純平均である。

    全null層（quality_regime）を除いた残り層スコアの算術平均と overall() が一致する。
    全null層の layer_score は実装裁量（NaN/None）なので、None/NaN を除いた採点層で平均を取る。
    """
    result = harness.score(fxh.trace_na_all_null_layer(), _spec())

    scored = []
    for layer in result.layers:
        val = result.layer_score(layer)
        if val is None:
            continue
        if isinstance(val, float) and math.isnan(val):
            continue
        scored.append(val)
    assert scored, "採点できた層が1つも無い（全null層除外が過剰）"
    expected = sum(scored) / len(scored)
    assert result.overall() == pytest.approx(expected), (
        f"overall() が採点層のみの単純平均でない: overall={result.overall()} "
        f"expected={expected}"
    )


def test_F013_all_null_layer_does_not_crash_score(tmp_path):
    """F-013（全null層・0除算しない）: 全null層があっても score 呼び出しが例外で落ちない。

    F-004-1 の all_null 挙動を F-013 の同一土俵比較の文脈で再固定する（ADR 0023 決定4）。
    """
    # 例外なく結果が返ること（落ちないことの固定）。
    result = harness.score(fxh.trace_na_all_null_layer(), _spec())
    assert result is not None
    # 他層（quality_regime 以外）は全正解で採点される。
    for layer in result.layers:
        if layer == "quality_regime":
            continue
        assert result.layer_score(layer) == pytest.approx(1.0), (
            f"{layer}: 全null層の存在が他層採点に波及している"
        )


# ===========================================================================
# (2) sealeval が全null層の項目を no_data として勝敗から除外する
# ===========================================================================

class _ScoreStub:
    """層 acc を直接持つ ScoreResult 互換スタブ（全null層は None）。"""

    def __init__(self, accs):
        self._accs = dict(accs)

    @property
    def layers(self):
        return tuple(self._accs.keys())

    def layer_score(self, layer):
        return self._accs.get(layer, None)

    def overall(self):
        vals = [v for v in self._accs.values() if v is not None]
        return sum(vals) / len(vals) if vals else None


def test_F013_all_null_weak_item_is_no_data_not_draw(tmp_path):
    """F-013（決定4・no_data）: 封印に当該層データが無い弱い項目（layer_score=None）は
    compare_items で no_data になり、勝敗（draw 含む）から除外される。

    全null層を「測ったが互角（draw）」と混同しない（ADR 0023 決定4）。
    scene_regime を supreme 側 None（全null層）にし、baseline は値あり。
    """
    from supreme import sealeval

    supreme = _ScoreStub({it: 0.70 for it in fxs.WEAK_ITEMS + fxs.STRONG_ITEMS})
    supreme._accs["scene_regime"] = None  # 全null層 → no_data 素材
    baseline = _ScoreStub({it: 0.60 for it in fxs.WEAK_ITEMS + fxs.STRONG_ITEMS})

    rep = sealeval.compare_items(
        supreme, baseline,
        delta_strong=fxs.DELTA_STRONG,
        weak_items=fxs.WEAK_ITEMS, strong_items=fxs.STRONG_ITEMS,
    )
    assert rep.verdict("scene_regime") == "no_data"
    assert rep.verdict("scene_regime") != "draw", "全null層を draw に混同している"
    assert "scene_regime" in rep.no_data_items


def test_F013_no_data_item_excludes_success_goal(tmp_path):
    """F-013（決定4 + 成功目標）: 弱い項目に no_data があると成功目標は成立しない
    （弱い全 win を満たせない＝success_goal=False）。

    no_data 層を「成功目標達成」に勝手に算入しないことを固定する（黙って採点しない精神）。
    """
    from supreme import sealeval

    supreme = _ScoreStub({it: 0.70 for it in fxs.WEAK_ITEMS + fxs.STRONG_ITEMS})
    supreme._accs["scene_regime"] = None  # no_data
    baseline = _ScoreStub({it: 0.60 for it in fxs.WEAK_ITEMS + fxs.STRONG_ITEMS})

    rep = sealeval.compare_items(
        supreme, baseline,
        delta_strong=fxs.DELTA_STRONG,
        weak_items=fxs.WEAK_ITEMS, strong_items=fxs.STRONG_ITEMS,
    )
    assert rep.success_goal is False, (
        "no_data 弱項目があるのに成功目標が成立している（no_data を勝ち扱いの疑い）"
    )
