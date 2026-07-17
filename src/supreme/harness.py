"""F-004: 評価ハーネス・測定エンジン（harness）。

指標非依存の汎用測定エンジン。supreme（や baseline）の出力を**受け取って測るだけ**で、
supreme 本体を実行しない（datagov/sealset/augment/guard には触れない）。

契約の最終根拠:
  - specs/SPEC.md「F-004」節（F-004-1 決定性採点 / F-004-2 T3 再現判定 / F-004-3 欠落時停止）
  - decisions/0012-u10-evaluation-metrics.md（採点仕様の正・決定A〜G）
      決定A: micro(global pooling: Σ正答/Σ非null)・完全一致(分類)・NA分母除外。
             層スコア = 8層 global acc、総合 = 8層 global acc の単純平均（層 macro）。
      決定B: risk_tier 分母 = 210全採点に統一（短尺T0の特例NA除外をしない）。
      決定C: Anomaly = 採点対象外（8層のみ）。
      決定E: t1_state 採点語彙 = idle/approach/pass/depart（GT出現4クラス）。
      決定D: 補助21メトリクス = 参考。公式採点・勝敗は8層 acc のみ。
  - decisions/0002-tolerances-and-seal-access.md（U5a・ε の正）
      連続値: |a−b| ≤ eps_abs + eps_rel·max(|a|,|b|)、eps_rel=1e-6、eps_abs=1e-9。
      分類: 完全一致。

決定性（F-004-1）の担保:
  - 乱数・時刻取得を一切使わない。
  - 採点は整数カウント（Σ正答 / Σ非null）由来で、層の走査順は spec.scored_layers の
    固定順。同じ trace・同じ spec で2回呼べば層スコア・総合は bit 単位で完全一致する。

依存: stdlib のみ（dataclasses / math）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# 例外（F-004-3: 指標定義/許容幅の欠落で「値を捏造せず停止」する専用例外）
# ---------------------------------------------------------------------------

class MetricSpecMissingError(Exception):
    """指標定義（metric_spec）が None/未供給のまま score を呼んだ。

    既定指標を黙って埋めて採点しない（SPEC.md F-004 異常系の精神）。
    """


class ToleranceMissingError(Exception):
    """許容幅（eps_abs / eps_rel）が None/未供給のまま check_reproduction を呼んだ。

    既定 ε を黙って埋めて再現判定しない（SPEC.md F-004 異常系の精神）。
    """


# ---------------------------------------------------------------------------
# 指標定義（MetricSpec）— 指標非依存エンジンへの「入力」
# ---------------------------------------------------------------------------

# ADR 0012 決定A/C の採点8層（Anomaly は含まない＝決定C）。固定順で決定性を担保する。
_CANONICAL_SCORED_LAYERS = (
    "risk_tier",
    "t1_state",
    "t2_mode",
    "t2_role",
    "t2_relation",
    "t3_hypothesis",
    "quality_regime",
    "scene_regime",
)


@dataclass(frozen=True)
class MetricSpec:
    """採点の指標定義。

    scored_layers: 採点する層名（順序付き）。完全一致・micro pooling・NA分母除外で
                   採点する層の集合。Anomaly はここに含めない（決定C）。

    指標非依存エンジンの「入力」。canonical_metric_spec() が ADR 0012 の正準値を構築する。
    frozen=True とし、構築後に変化しない（決定性）。
    """

    scored_layers: tuple = _CANONICAL_SCORED_LAYERS


def canonical_metric_spec() -> "MetricSpec":
    """ADR 0012 の8層採点仕様を構築して返す（決定的・乱数なし）。

    2回構築しても同一採点になる（固定タプルから組み立てるのみ）。
    """
    return MetricSpec(scored_layers=_CANONICAL_SCORED_LAYERS)


# ---------------------------------------------------------------------------
# 採点結果（ScoreResult）
# ---------------------------------------------------------------------------

class ScoreResult:
    """score() の戻り値。8層 global acc と総合（層 macro）を提供する。

    内部は層別の整数カウント (correct, nonnull) を保持し、層スコアは
    `correct / nonnull`（nonnull>0）で決定的に算出する。nonnull==0 の層は
    分母0なので層スコアを NaN とし、総合（単純平均）からは除外する
    （0除算で落ちず、他層の採点に波及させない＝fixtures_harness の要求）。
    """

    def __init__(self, scored_layers, counts):
        # scored_layers: 採点した層名（順序付き）
        # counts: {layer: {"correct": int, "nonnull": int}}
        self.layers = list(scored_layers)
        self._counts = counts

    def layer_score(self, layer: str) -> float:
        """指定層の global acc（Σ正答 / Σ非null）を返す。

        分母0（gt が全 null）の層は NaN を返す（表現は実装裁量・fixtures_harness）。
        """
        c = self._counts[layer]
        nonnull = c["nonnull"]
        if nonnull == 0:
            return math.nan
        return c["correct"] / nonnull

    def overall(self) -> float:
        """総合 = 採点した8層 global acc の単純平均（層 macro）。

        分母0の層（NaN）は平均から除外する（0除算回避・他層に波及させない）。
        採点可能な層が1つも無ければ NaN。
        """
        scores = []
        for layer in self.layers:
            c = self._counts[layer]
            if c["nonnull"] == 0:
                continue
            scores.append(c["correct"] / c["nonnull"])
        if not scores:
            return math.nan
        return sum(scores) / len(scores)


# ---------------------------------------------------------------------------
# 採点エンジン（score）
# ---------------------------------------------------------------------------

def score(trace, metric_spec=None) -> "ScoreResult":
    """trace を metric_spec に従って採点し ScoreResult を返す。

    採点規約（ADR 0012）:
      - 採点単位 = フレーム。micro（global pooling）: 全シナリオ×全フレームでプールし
        各層 `Σ正答 / Σ非null`。
      - 正解判定 = 完全一致（view[層] == gt[層]）。
      - NA/null 除外 = gt[層] is None のフレームはその層の分母から除外（決定A）。
        risk_tier も短尺T0の特例除外をしない（非null全件を分母に＝決定B）。
      - Anomaly は metric_spec.scored_layers に無い → 採点しない（決定C）。

    F-004-3（異常系）: metric_spec が None/未供給なら MetricSpecMissingError で停止
    （既定指標を捏造して採点しない）。

    trace 形状（fixtures_harness / fixtures_gt と同形）:
      { "<scenario>": [ {"ts": float, "view": {層:ラベル}, "gt": {層:ラベル or None}}, ... ], ... }
    """
    if metric_spec is None:
        raise MetricSpecMissingError(
            "metric_spec が未供給（None）。既定指標を埋めず停止する（SPEC.md F-004 異常系）"
        )

    scored_layers = tuple(metric_spec.scored_layers)

    # 層別の整数カウンタ（決定性: 整数の蓄積のみ）。
    counts = {layer: {"correct": 0, "nonnull": 0} for layer in scored_layers}

    for frames in trace.values():
        for frame in frames:
            view = frame["view"]
            gt = frame["gt"]
            for layer in scored_layers:
                gt_label = gt.get(layer)
                if gt_label is None:
                    # NA/null は分母から除外（決定A/B）。Anomaly は scored_layers に
                    # 無いのでそもそも走査されない（決定C）。
                    continue
                counts[layer]["nonnull"] += 1
                if view.get(layer) == gt_label:
                    counts[layer]["correct"] += 1

    return ScoreResult(scored_layers=scored_layers, counts=counts)


# ---------------------------------------------------------------------------
# T3 再現判定（check_reproduction）— F-004-2
# ---------------------------------------------------------------------------

@dataclass
class ReproResult:
    """check_reproduction() の戻り値。

    reproduced : 全項目が再現条件を満たすか（連続値が ε 内 ∧ 分類が完全一致）。
    mismatches : 再現しなかった項目の内訳（空なら全再現）。各要素は item 名・
                 種別・突合値を含む dict で、repr で項目名を特定できる。
    """

    reproduced: bool
    mismatches: list = field(default_factory=list)


def check_reproduction(run_a, run_b, *, eps_abs=None, eps_rel=None) -> "ReproResult":
    """2回流した出力（run_a, run_b）を突合し、T3 再現可否を判定する（F-004-2）。

    再現条件（ADR 0002・U5a）:
      - 連続値（continuous の各項目）: |a−b| ≤ eps_abs + eps_rel·max(|a|,|b|) なら再現
        （境界＝等号は ≤ で再現OK）。超えたら mismatch。
      - 分類（categorical の各項目）: 完全一致なら再現、不一致なら mismatch（ε を使わない）。

    F-004-3（異常系）: eps_abs または eps_rel が None/未供給なら ToleranceMissingError で停止
    （既定 ε を捏造して判定しない）。

    run 形状（fixtures_harness.repro_run と同形）:
      [ {"ts": float, "continuous": {項目: float}, "categorical": {項目: str}}, ... ]

    決定性: 乱数・時刻を使わず、項目走査は sorted キー順で固定。同じ2 run で
    2回呼べば結果（reproduced・mismatches）は同一。
    """
    if eps_abs is None or eps_rel is None:
        raise ToleranceMissingError(
            "許容幅（eps_abs/eps_rel）が未供給（None）。既定 ε を埋めず停止する"
            "（SPEC.md F-004 異常系）"
        )

    mismatches = []

    # フレーム数の不一致自体も再現失敗として扱う（突合できない＝再現していない）。
    n = max(len(run_a), len(run_b))
    for idx in range(n):
        if idx >= len(run_a) or idx >= len(run_b):
            mismatches.append({
                "frame_index": idx,
                "kind": "frame_count",
                "reason": "frame missing in one run",
            })
            continue

        fa = run_a[idx]
        fb = run_b[idx]

        # --- 連続値: ε 許容判定 ---
        cont_a = fa.get("continuous", {}) or {}
        cont_b = fb.get("continuous", {}) or {}
        for item in sorted(set(cont_a) | set(cont_b)):
            if item not in cont_a or item not in cont_b:
                mismatches.append({
                    "frame_index": idx,
                    "item": item,
                    "kind": "continuous",
                    "reason": "item missing in one run",
                })
                continue
            a = float(cont_a[item])
            b = float(cont_b[item])
            threshold = eps_abs + eps_rel * max(abs(a), abs(b))
            if abs(a - b) > threshold:
                mismatches.append({
                    "frame_index": idx,
                    "item": item,
                    "kind": "continuous",
                    "a": a,
                    "b": b,
                    "diff": abs(a - b),
                    "threshold": threshold,
                })

        # --- 分類: 完全一致判定（ε を使わない） ---
        cat_a = fa.get("categorical", {}) or {}
        cat_b = fb.get("categorical", {}) or {}
        for item in sorted(set(cat_a) | set(cat_b)):
            va = cat_a.get(item)
            vb = cat_b.get(item)
            if va != vb:
                mismatches.append({
                    "frame_index": idx,
                    "item": item,
                    "kind": "categorical",
                    "a": va,
                    "b": vb,
                })

    return ReproResult(reproduced=(len(mismatches) == 0), mismatches=mismatches)
