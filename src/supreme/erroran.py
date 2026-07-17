"""F-005: baseline 取込＋エラー分析（erroran）。

GitHub の baseline 結果（`results/trace/trace.json` と同形の dict）を取り込み、
F-001 単一スキーマ（specs/GT_SCHEMA.md）の canonical GT レコードと突合して、
弱い5項目について「どこで・どのクラスで間違うか」を抽出する。

契約の最終根拠は specs/SPEC.md「F-005」節・specs/GT_SCHEMA.md・ADR 0005。
本モジュールは stdlib のみに依存し、ファイルI/O・外部クローン読込・YAML パースは
持たない（入力は dict を受ける）。datagov の normalize は再利用する（supreme 内部リンク）。

突合ルール（test-writer 定義／specs/GT_SCHEMA.md「9評価項目との対応」準拠）:
  - t2_mode / t2_relation: canonical の確率分布の argmax 集合に trace gt ラベルが
    含まれれば一致（同率最大が複数ある場合は集合包含で判定）。
  - t3_hypothesis / quality_regime / scene_regime: canonical の文字列フィールドと完全一致。
  - フレーム対応キーは (scenario_id, ts)。

評価対象（弱い5項目）: t2_mode, t2_relation, t3_hypothesis, quality_regime, scene_regime。
trace の view（予測）と gt（正解）の差がエラー（分析フェーズで集計）。
trace の gt と canonical GT の整合は取込フェーズで検証する。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import datagov


# ---------------------------------------------------------------------------
# 例外
# ---------------------------------------------------------------------------

class TraceFormatError(Exception):
    """trace の形式不正（必須キー欠落・ts 非数値・未知層キー・フレーム非配列・空 trace 等）。

    黙って読み飛ばさない（SPEC.md F-005 異常系・U22）ための明示エラー。
    """


class IngestError(Exception):
    """突合不整合・フレーム欠落/過剰により取込を拒否する際に発出する例外。

    属性として mismatches / missing_frames / extra_frames を保持する（IngestResult と同形）。
    """

    def __init__(self, message="", *, mismatches=None, missing_frames=None,
                 extra_frames=None):
        super().__init__(message)
        self.mismatches = mismatches if mismatches is not None else []
        self.missing_frames = missing_frames if missing_frames is not None else []
        self.extra_frames = extra_frames if extra_frames is not None else []


# ---------------------------------------------------------------------------
# 8層／弱い5項目の定義（ADR 0005・GT_SCHEMA.md「9評価項目との対応」）
# ---------------------------------------------------------------------------

# baseline trace.json の 8 層キー（Anomaly は評価層に存在しない＝ADR 0005）。
TRACE_LAYERS = (
    "risk_tier", "t1_state", "t2_mode", "t2_role", "t2_relation",
    "t3_hypothesis", "quality_regime", "scene_regime",
)

# 分析必須の弱い5項目。
WEAK_LAYERS = (
    "t2_mode", "t2_relation", "t3_hypothesis", "quality_regime", "scene_regime",
)

# 各弱い層 → canonical GT への対応（突合方式付き）。
#   "argmax": frames[].t2.<dist_key> の確率分布の argmax 集合と比較
#   "string": frames[].t3.<field> の文字列と完全一致
_LAYER_TO_CANONICAL = {
    "t2_mode": ("argmax", ("t2", "mode")),
    "t2_relation": ("argmax", ("t2", "relations")),
    "t3_hypothesis": ("string", ("t3", "hypothesis")),
    "quality_regime": ("string", ("t3", "quality_regime")),
    "scene_regime": ("string", ("t3", "scene_regime")),
}


# ---------------------------------------------------------------------------
# 結果オブジェクト
# ---------------------------------------------------------------------------

@dataclass
class IngestResult:
    """ingest の戻り値。

    ok          : 全フレーム整合かつフレーム欠落/過剰なしなら True。
    mismatches  : trace gt と canonical GT の不整合（弱い5項目）。
                  各要素 {scenario_id, ts, layer, trace_gt, canonical}。
    missing_frames : trace にあって canonical に無い (scenario_id, ts)。
    extra_frames   : canonical にあって trace に無い (scenario_id, ts)。
    warnings    : 黙殺しない補助情報（現状は未使用だが属性として公開）。
    """

    ok: bool
    mismatches: list = field(default_factory=list)
    missing_frames: list = field(default_factory=list)
    extra_frames: list = field(default_factory=list)
    warnings: list = field(default_factory=list)


class AnalysisResult:
    """analyze の戻り値。弱い5項目の混同行列・誤りフレーム・正解率を提供する。

    内部に層別の (gt, pred) フレーム列を保持し、要求に応じて集計する。
    """

    def __init__(self, layers, per_layer_frames):
        # layers: 分析した層名のリスト（弱い5項目）
        # per_layer_frames: {layer: [ {scenario_id, ts, gt, pred}, ... ]}
        self.layers = list(layers)
        self._frames = per_layer_frames

    def confusion_matrix(self, layer):
        """dict[gt_cls][pred_cls] = int の混同行列を返す。

        全フレーム（正解・誤り）を計上する（対角＝正解、非対角＝誤り）。
        """
        cm = {}
        for fr in self._frames.get(layer, []):
            gt = fr["gt"]
            pred = fr["pred"]
            cm.setdefault(gt, {})
            cm[gt][pred] = cm[gt].get(pred, 0) + 1
        return cm

    def error_frames(self, layer):
        """誤り（gt != pred）フレーム一覧を返す。

        各要素 {scenario_id, ts, pred, gt}。
        """
        out = []
        for fr in self._frames.get(layer, []):
            if fr["gt"] != fr["pred"]:
                out.append({
                    "scenario_id": fr["scenario_id"],
                    "ts": fr["ts"],
                    "pred": fr["pred"],
                    "gt": fr["gt"],
                })
        return out

    def accuracy(self, layer):
        """[0,1] の正解率を返す（フレーム0件なら 1.0）。"""
        frames = self._frames.get(layer, [])
        total = len(frames)
        if total == 0:
            return 1.0
        correct = sum(1 for fr in frames if fr["gt"] == fr["pred"])
        return correct / total


# ---------------------------------------------------------------------------
# 形式検証（黙って読み飛ばさない・U22）
# ---------------------------------------------------------------------------

def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _validate_trace_format(trace):
    """trace の形式を検査し、不正なら TraceFormatError を送出する。

    検査項目（SPEC.md F-005 異常系・test_F005_abnormal）:
      - trace は非空 dict
      - 各シナリオ値はフレームの list
      - 各フレームは dict で ts/view/gt を持つ
      - ts は数値（bool 不可・None 不可・文字列不可）
      - view/gt は 8 層キーをちょうど持つ（欠落・未知キーは形式違反）
    """
    if not isinstance(trace, dict):
        raise TraceFormatError(
            f"trace は dict である必要があるが {type(trace).__name__} を受領した"
        )
    if len(trace) == 0:
        raise TraceFormatError("trace が空（空 dict は有効なデータでない）")

    layer_set = set(TRACE_LAYERS)
    for scenario_id, frames in trace.items():
        if not isinstance(frames, list):
            raise TraceFormatError(
                f"シナリオ '{scenario_id}' の値はフレームの list である必要があるが "
                f"{type(frames).__name__} を受領した"
            )
        for idx, frame in enumerate(frames):
            if not isinstance(frame, dict):
                raise TraceFormatError(
                    f"シナリオ '{scenario_id}' フレーム#{idx} は dict でない"
                )
            for key in ("ts", "view", "gt"):
                if key not in frame:
                    raise TraceFormatError(
                        f"シナリオ '{scenario_id}' フレーム#{idx} に必須キー "
                        f"'{key}' が無い"
                    )
            if not _is_number(frame["ts"]):
                raise TraceFormatError(
                    f"シナリオ '{scenario_id}' フレーム#{idx} の ts が数値でない: "
                    f"{frame['ts']!r}"
                )
            for side in ("view", "gt"):
                labels = frame[side]
                if not isinstance(labels, dict):
                    raise TraceFormatError(
                        f"シナリオ '{scenario_id}' フレーム#{idx} の '{side}' が dict でない"
                    )
                keys = set(labels.keys())
                unknown = keys - layer_set
                if unknown:
                    raise TraceFormatError(
                        f"シナリオ '{scenario_id}' フレーム#{idx} の '{side}' に未知の層キー: "
                        f"{sorted(unknown)}"
                    )
                missing = layer_set - keys
                if missing:
                    raise TraceFormatError(
                        f"シナリオ '{scenario_id}' フレーム#{idx} の '{side}' に層キー欠落: "
                        f"{sorted(missing)}"
                    )


# ---------------------------------------------------------------------------
# canonical GT のインデックス化（(scenario_id, ts) → frame）
# ---------------------------------------------------------------------------

def _index_canonical(canonical_records):
    """canonical レコード群を (scenario_id, ts) → canonical frame に索引化する。

    datagov.normalize で各レコードを正規化（deep copy）してから取り込む。
    """
    index = {}
    for record in canonical_records:
        norm = datagov.normalize(record)
        sid = norm["gt"]["scenario_id"]
        for fr in norm["gt"]["frames"]:
            index[(sid, float(fr["ts"]))] = fr
    return index


def _argmax_set(dist):
    """確率分布 dict（クラス→float）の最大値を取るクラス集合を返す。"""
    if not dist:
        return set()
    max_val = max(dist.values())
    return {cls for cls, v in dist.items() if v == max_val}


def _canonical_label_matches(layer, canonical_frame, trace_gt_label):
    """canonical frame の該当層が trace gt ラベルと整合するか判定する。

    argmax 層: trace gt ラベルが分布の argmax 集合に含まれれば一致。
    string 層: 文字列完全一致。
    戻り値: (matched: bool, canonical_value: dict|str)。
    """
    method, path = _LAYER_TO_CANONICAL[layer]
    node = canonical_frame
    for key in path:
        node = node[key]
    if method == "argmax":
        matched = trace_gt_label in _argmax_set(node)
        return matched, node
    else:  # string
        return node == trace_gt_label, node


# ---------------------------------------------------------------------------
# 取込（ingest）
# ---------------------------------------------------------------------------

def ingest(trace, canonical_records):
    """baseline trace と canonical GT を突合し IngestResult を返す。

    SPEC.md F-005 境界条件「取り込めるのは baseline 側 GT と F-001 スキーマが
    突合できる場合のみ」を実装する。

    - 形式不正は TraceFormatError（黙って読み飛ばさない・U22）。
    - 弱い5項目について trace gt と canonical GT が不整合なら mismatches に全件記録。
    - trace にあって canonical に無いフレームは missing_frames、逆は extra_frames。
    - すべて整合かつ欠落/過剰なしなら ok=True。
    """
    _validate_trace_format(trace)

    canonical_index = _index_canonical(canonical_records)

    mismatches = []
    missing_frames = []
    extra_frames = []

    # trace 側のフレームキー集合（フレーム対応の比較に使う）。
    trace_keys = set()

    for scenario_id, frames in trace.items():
        for frame in frames:
            ts = float(frame["ts"])
            key = (scenario_id, ts)
            trace_keys.add(key)

            canonical_frame = canonical_index.get(key)
            if canonical_frame is None:
                # trace にあって canonical に無い
                missing_frames.append({"scenario_id": scenario_id, "ts": ts})
                continue

            gt_labels = frame["gt"]
            for layer in WEAK_LAYERS:
                trace_gt_label = gt_labels[layer]
                matched, canonical_value = _canonical_label_matches(
                    layer, canonical_frame, trace_gt_label
                )
                if not matched:
                    mismatches.append({
                        "scenario_id": scenario_id,
                        "ts": ts,
                        "layer": layer,
                        "trace_gt": trace_gt_label,
                        "canonical": canonical_value,
                    })

    # canonical にあって trace に無いフレーム
    for key in canonical_index:
        if key not in trace_keys:
            extra_frames.append({"scenario_id": key[0], "ts": key[1]})

    ok = not (mismatches or missing_frames or extra_frames)
    return IngestResult(
        ok=ok,
        mismatches=mismatches,
        missing_frames=missing_frames,
        extra_frames=extra_frames,
        warnings=[],
    )


# ---------------------------------------------------------------------------
# 分析（analyze）
# ---------------------------------------------------------------------------

def analyze(trace, canonical_records):
    """trace と canonical GT を取り込み、弱い5項目のエラー分析結果を返す。

    取込で不整合・フレーム欠落/過剰があれば IngestError を送出する
    （F-005-1: 突合できる場合のみ分析対象）。形式不正は TraceFormatError。

    エラーは trace の view（予測）と gt（正解）の差で定義し、層別に
    (scenario_id, ts, gt, pred) を蓄積する。混同行列・誤りフレーム・正解率は
    AnalysisResult が遅延集計する。
    """
    result = ingest(trace, canonical_records)
    if not result.ok:
        raise IngestError(
            "trace と canonical GT が突合できないため分析を中止",
            mismatches=result.mismatches,
            missing_frames=result.missing_frames,
            extra_frames=result.extra_frames,
        )

    per_layer_frames = {layer: [] for layer in WEAK_LAYERS}
    for scenario_id, frames in trace.items():
        for frame in frames:
            ts = float(frame["ts"])
            view = frame["view"]
            gt_labels = frame["gt"]
            for layer in WEAK_LAYERS:
                per_layer_frames[layer].append({
                    "scenario_id": scenario_id,
                    "ts": ts,
                    "gt": gt_labels[layer],
                    "pred": view[layer],
                })

    return AnalysisResult(layers=list(WEAK_LAYERS),
                          per_layer_frames=per_layer_frames)


# ---------------------------------------------------------------------------
# レポート生成（generate_report）
# ---------------------------------------------------------------------------

# 弱い5項目の人間可読な表示名（レポート見出し補助）。
_LAYER_TITLES = {
    "t2_mode": "t2_mode（mode・弱い項目）",
    "t2_relation": "t2_relation（relation・弱い項目）",
    "t3_hypothesis": "t3_hypothesis（T3 hypothesis・弱い項目）",
    "quality_regime": "quality_regime（quality・弱い項目）",
    "scene_regime": "scene_regime（scene・弱い項目）",
}


def _format_confusion_matrix(cm):
    """混同行列 dict を Markdown 表に整形する。"""
    if not cm:
        return "（フレーム0件・混同行列なし）\n"
    lines = ["| GT \\ pred | pred_cls | count |", "| --- | --- | --- |"]
    for gt_cls in sorted(cm):
        for pred_cls in sorted(cm[gt_cls]):
            count = cm[gt_cls][pred_cls]
            mark = "" if gt_cls == pred_cls else " (error)"
            lines.append(f"| {gt_cls} | {pred_cls}{mark} | {count} |")
    return "\n".join(lines) + "\n"


def _format_error_patterns(error_frames):
    """主要誤りパターン（gt→pred の件数）を Markdown 箇条書きに整形する。"""
    if not error_frames:
        return "- 誤りパターン: なし（accuracy=1.0）\n"
    counts = {}
    for fr in error_frames:
        pair = (fr["gt"], fr["pred"])
        counts[pair] = counts.get(pair, 0) + 1
    lines = []
    for (gt_cls, pred_cls), count in sorted(
        counts.items(), key=lambda kv: (-kv[1], kv[0])
    ):
        lines.append(f"- 誤りパターン: gt={gt_cls} → pred={pred_cls}（{count} 件）")
    return "\n".join(lines) + "\n"


def generate_report(trace, canonical_records):
    """弱い5項目のエラー分析レポート（Markdown 骨子）を生成して返す。

    SPEC.md F-005-2「各改良モジュール（F-007〜011）が着手前に参照すべき
    構造原因が文書化される」の骨子。構成:
      - 弱い5項目それぞれのセクション（accuracy・混同行列・主要誤りパターン
        ＋「原因仮説（記入欄）」）
      - F-008 配線漏れ仮説の検証セクション（relation の誤りパターン statistics ＋判定記入欄）

    NOTE: F-008 の relation 配線漏れは未検証の仮説（SPEC.md F-008 注記）。
          本レポートはセクションと統計を提供するのみで、仮説を事実として断定しない。
    """
    analysis = analyze(trace, canonical_records)

    parts = []
    parts.append("# F-005 baseline エラー分析レポート（骨子）\n")
    parts.append(
        "> 弱い5項目のクラス別誤り内訳と構造原因の記入欄。"
        "F-007〜011 の着手前に参照する（SPEC.md F-005-2）。\n"
    )
    parts.append(
        "> 注記: F-008 の relation 配線漏れは未検証の仮説（SPEC.md F-008）。"
        "本レポートは統計を提示するのみで仮説を断定しない。\n"
    )

    # --- 弱い5項目セクション ---
    parts.append("## 弱い5項目の誤り内訳\n")
    for layer in WEAK_LAYERS:
        acc = analysis.accuracy(layer)
        cm = analysis.confusion_matrix(layer)
        error_frames = analysis.error_frames(layer)
        total = sum(c for d in cm.values() for c in d.values())
        n_error = len(error_frames)

        parts.append(f"### {_LAYER_TITLES.get(layer, layer)}\n")
        parts.append("**統計**\n")
        parts.append(
            f"- accuracy（正解率）: {acc:.4f}\n"
            f"- フレーム件数: {total} / 誤り件数: {n_error}\n"
        )
        parts.append("**confusion matrix（混同行列）**\n")
        parts.append(_format_confusion_matrix(cm))
        parts.append("**主要誤りパターン（error patterns）**\n")
        parts.append(_format_error_patterns(error_frames))
        parts.append(
            "**原因仮説（記入欄）**\n"
            "- TODO（記入欄）: この項目の構造原因の仮説を記入する。\n"
        )

    # --- F-008 配線漏れ仮説の検証セクション ---
    rel_acc = analysis.accuracy("t2_relation")
    rel_cm = analysis.confusion_matrix("t2_relation")
    rel_errors = analysis.error_frames("t2_relation")
    rel_total = sum(c for d in rel_cm.values() for c in d.values())
    parts.append("## F-008 relation 配線漏れ仮説の検証\n")
    parts.append(
        "> 仮説（未検証・SPEC.md F-008）: relations が mode ルールの副作用として"
        "各1箇所でしか発火せず、抽出済み証拠が relation に配線されていない。\n"
    )
    parts.append("**relation 誤りパターン statistics**\n")
    parts.append(
        f"- relation accuracy: {rel_acc:.4f}\n"
        f"- relation フレーム件数: {rel_total} / 誤り件数: {len(rel_errors)}\n"
    )
    parts.append(_format_error_patterns(rel_errors))
    parts.append(
        "**判定（記入欄）**\n"
        "- [ ] 配線漏れ仮説は支持される / [ ] 棄却される（verdict）\n"
        "- TODO（判定記入欄）: 上記 statistics を根拠に判定を記入する。\n"
    )

    return "\n".join(parts)
