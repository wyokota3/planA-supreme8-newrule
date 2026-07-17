"""開発セット(v021_core)評価ランナー — supreme vs baseline(v1.4)を 8 層で対比する。

⚠️ これは in-sample(開発セット v021_core)評価である。v021_core は F-005 エラー分析=
   supreme の開発に使用済みのため、**汚染ゼロの封印評価ではない**。最終 verdict には使えない。
   真の封印 verdict は held-out 人手シナリオが前提(docs/SEALED_EVAL_RUNBOOK.md)。

処理(同一土俵・厳密・ADR 0025 Phase1b で学習列を追加):
  1. 各シナリオ: pso_input.jsonl(planA-baseline)→ snapshots → core.run_supreme(snaps)
     → 8 層 view(v1.4)。
  2. ground_truth.yaml(n04-feat・catalog 1.4.0)→ ADR 0006 の v1.3→v1.4 正準化を適用して
     8 層 gt view 列(t2 は argmax で単一ラベル化=sealeval._gt_frame_to_view と整合)。
  3. 既定(params=None)で全シナリオを 1 trace に束ね harness.score(...) → 既定 8 層 acc。
  4. **v021_core を練習データとして core.fit_supreme(scenario_inputs, gt) で学習**し、
     params=trained を core.run_supreme_scenarios に注入して再採点 → 学習 8 層 acc。
     ⚠️ 学習も採点も同じ v021_core ＝ **in-sample(train=eval=楽観)**。汎化の正直な推定は
     CV held-out(reports/cv-train-*.md・scene 0.557 / t3 0.410)。trained 列は楽観値。
  5. sealeval.load_baseline_scores(baseline 8 層 dict) → sealeval.compare_items(...)(既定列)。
  6. reports/dev-eval-<YYYYMMDD-HHMM>.md 出力(既定 / 学習(in-sample) / baseline /
     CV held-out を併記・封印 verdict ではない警告は維持)。

最重要規律(捏造防止):
  - ADR 0006 が定義する文書化済みマッピング(mode 2 クラスリネーム + quality 順位シフト)のみ
    を GT に適用する。それ以外の層は恒等だが、**GT の(採点される argmax)値が supreme の
    v1.4 語彙集合に収まることを各層で検証**し、収まらない v1.3 固有値が 1 つでも出たら、
    その層・値・シナリオを挙げて即停止する(数字を捏造しない・黙って恒等扱いにしない)。
  - pso 入力と GT のフレーム数・ts が対応しないシナリオは停止して報告する。

使い方:
    python scripts/run_dev_eval.py [--pso-dir <path>] [--gt-dir <path>] [--out <path>]

依存: supreme.* 公開 API のみ(baseline コードは import しない)。pyyaml 使用可。
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys

# プロジェクト src を Python パスに追加(インストール不要で実行できるように)。
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_SRC_DIR = os.path.join(os.path.dirname(_SCRIPT_DIR), "src")
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

try:
    import yaml
except ImportError:
    print("ERROR: pyyaml が必要です。pip install 'pyyaml>=6.0' でインストールしてください。",
          file=sys.stderr)
    sys.exit(1)

# supreme 公開 API のみ(baseline コードは一切 import しない=独立性)。
from supreme import core, harness, sealeval


# ---------------------------------------------------------------------------
# 既定パス
# ---------------------------------------------------------------------------

DEFAULT_PSO_DIR = (
    r"C:\work\L04-planA\supreme\external-data\planA-baseline\scenarios\v021_core"
)
DEFAULT_GT_DIR = (
    r"C:\work\L04-planA\supreme\external-data\n04-feat\scenarios\v021_core"
)
DEFAULT_OUT_DIR = "reports"


# ---------------------------------------------------------------------------
# baseline 参照スコア(v1.4・研究者再計測済み・results/baseline-catalog-1.4.0.md)
#   = supreme が項目別に挑む基準値の最新参考(ADR 0005/0006 / 指示)。
# ---------------------------------------------------------------------------

BASELINE_V14 = {
    "risk_tier": 0.9040,
    "t1_state": 0.9095,
    "t2_mode": 0.5714,
    "t2_role": 0.8429,
    "t2_relation": 0.5571,
    "t3_hypothesis": 0.6286,
    "quality_regime": 0.6667,
    "scene_regime": 0.5429,
}

# verdict 分類(ADR 0023/0012・指示 step4)。
WEAK_ITEMS = ("t2_mode", "t2_relation", "t3_hypothesis", "scene_regime", "quality_regime")
STRONG_ITEMS = ("risk_tier", "t1_state", "t2_role")
DELTA_STRONG = 0.02

# CV held-out(正直な汎化推定・lineage-disjoint 5-fold・reports/cv-train-*.md)。
#   ⚠️ in-sample(train=eval)の楽観値とは別物。verdict には CV held-out 側を使う。
#   t3/scene のみ学習対象(ADR 0025 決定2)。他層は CV 対象外のため None(= 学習しない既定値)。
CV_HELDOUT_LEARNED = {
    "scene_regime": 0.5571,    # 既定 0.3238 → 学習 0.5571(+0.2333・全fold正・過学習0)
    "t3_hypothesis": 0.4095,   # 既定 0.3571 → 学習 0.4095(+0.0524・fold ばらつき大・中過学習)
}
CV_HELDOUT_DEFAULT = {
    "scene_regime": 0.3238,
    "t3_hypothesis": 0.3571,
}
CV_REPORT_REF = "reports/cv-train-20260614-1945.md"

# 参考 sanity(旧アーキ ours の弱5・per_layer.json 由来)。桁違いに乖離なら
# 配線/語彙ミスを疑い停止報告する(一致強制はしない・指示 自己検査)。
_OURS_SANITY = {
    "t2_mode": 0.624,
    "t2_relation": 0.748,
    "t3_hypothesis": 0.586,
    "quality_regime": 0.762,
    "scene_regime": 0.529,
}
_SANITY_ORDER_OF_MAGNITUDE = 0.40  # |supreme - ours| がこの幅を超えたら「桁違い」とみなす。


# ===========================================================================
# 語彙正準化(GT→v1.4・ADR 0006)— スクリプト内ローカル関数(supreme 本体は変更しない)
# ===========================================================================

class V13LabelError(Exception):
    """ADR 0006 に正準化規定が無い v1.3 固有ラベルに当たった(=数字を捏造せず停止)。"""


# mode(t2.mode の分布キー)v1.3→v1.4(ADR 0006 決定1・契約 v1.4):
#   alert_observation → side_rear_caution
#   conv_participation → uncertain
#   他 8 クラスは恒等。
_MODE_RENAME = {
    "alert_observation": "side_rear_caution",
    "conv_participation": "uncertain",
}

# quality_regime(t3.quality_regime)v1.3→v1.4 順位シフト(ADR 0006/0005):
#   GOOD → GOOD / PASS → DEGRADED / DEGRADED → BLOCK。
_QUALITY_REMAP = {
    "GOOD": "GOOD",
    "PASS": "DEGRADED",
    "DEGRADED": "BLOCK",
}

# 各層の supreme v1.4 語彙集合(各モジュール出力 / datagov._T2_KEY_SETS)。
# 恒等層は GT の(採点される)値がこの集合に収まることを検証する。
_V14_VOCAB = {
    # t0.risk_tier(supreme.t0)
    "risk_tier": frozenset(("info", "caution", "danger")),
    # t1.state(supreme.t1)
    "t1_state": frozenset(("idle", "approach", "pass", "depart")),
    # t2.mode キー集合(supreme.datagov._T2_KEY_SETS["mode"]・正準化後はこの集合に閉じる)
    "t2_mode": frozenset((
        "conv_request", "conv_ongoing", "surround_activity", "forward_caution",
        "side_rear_caution", "alert_required", "emergency", "quiet_standby",
        "env_change", "uncertain",
    )),
    # t2.roles キー集合(supreme.role 語彙 6・datagov._T2_KEY_SETS["roles"])
    "t2_role": frozenset((
        "source_speech", "source_vehicle", "source_alarm",
        "source_human", "source_object", "unknown",
    )),
    # t2.relations キー集合(GT 側 v1.4 schema・datagov._T2_KEY_SETS["relations"])。
    # supreme.relation は 4 クラスのみ出力するが、GT 採点ラベルは 6 クラス集合に収まればよい
    # (departing/unrelated は v1.4 GT schema にある正当な値。supreme が予測しないだけ)。
    "t2_relation": frozenset((
        "addressing_user", "near_user", "approaching", "grouped",
        "departing", "unrelated",
    )),
    # t3.hypothesis(supreme.t3 語彙 10)
    "t3_hypothesis": frozenset((
        "quiet_stable", "conv_participating", "sustained_alert", "env_shift",
        "env_start", "crowd_tendency", "traffic_unstable", "hazard_declining",
        "uncertain_context", "alert_required",
    )),
    # quality_regime(supreme.quality・正準化後)
    "quality_regime": frozenset(("GOOD", "DEGRADED", "BLOCK")),
    # scene_regime(supreme.scene)
    "scene_regime": frozenset(("STABLE", "CHANGING", "DEGRADING")),
}


def _argmax_label(dist):
    """確率分布 dict(クラス→float)の最大確率クラスを返す(決定的・同点はキー昇順)。

    sealeval._argmax_label と同方針(8 層 view は単一ラベルを要するため決定的に 1 つへ畳む)。
    空/None は None。
    """
    if not dist:
        return None
    max_val = max(dist.values())
    candidates = sorted(cls for cls, v in dist.items() if v == max_val)
    return candidates[0] if candidates else None


def canonicalize_mode_label(label, *, scenario_id, ts):
    """GT の t2.mode argmax ラベルを v1.4 語彙へ正準化する(ADR 0006・2 クラスリネーム)。

    リネーム後のラベルが v1.4 mode 集合に収まらなければ V13LabelError で停止する。
    """
    if label is None:
        return None
    canon = _MODE_RENAME.get(label, label)
    if canon not in _V14_VOCAB["t2_mode"]:
        raise V13LabelError(
            f"[t2_mode] ADR 0006 正準化後も v1.4 語彙に無いラベル '{label}'→'{canon}' "
            f"(scenario_id={scenario_id} ts={ts})。数字を捏造せず停止する。"
        )
    return canon


def canonicalize_quality_label(label, *, scenario_id, ts):
    """GT の quality_regime を v1.4 へ正準化する(ADR 0006/0005・順位シフト)。"""
    if label is None:
        return None
    if label not in _QUALITY_REMAP:
        raise V13LabelError(
            f"[quality_regime] ADR 0006 の順位シフト表に無いラベル '{label}' "
            f"(scenario_id={scenario_id} ts={ts})。"
            f" 既知 v1.3 値は {sorted(_QUALITY_REMAP)!r}。数字を捏造せず停止する。"
        )
    return _QUALITY_REMAP[label]


def _check_identity_label(layer, label, *, scenario_id, ts):
    """恒等層のラベルが v1.4 語彙集合に収まることを検証する(収まらなければ停止)。

    ADR 0006 にリネーム規定が無い層は恒等だが、GT に v1.3 固有値が紛れていれば
    黙って恒等扱いにせず停止する(指示の最重要規律)。None は NA として許容(採点除外)。
    """
    if label is None:
        return None
    if label not in _V14_VOCAB[layer]:
        raise V13LabelError(
            f"[{layer}] supreme v1.4 語彙集合に無い値 '{label}' "
            f"(scenario_id={scenario_id} ts={ts})。ADR 0006 にこの層のリネーム規定は無く、"
            f" v1.3 固有値の可能性があるため黙って恒等扱いにせず停止する。"
            f" v1.4 語彙={sorted(_V14_VOCAB[layer])!r}。"
        )
    return label


def gt_frame_to_v14_view(gt_frame, *, scenario_id, ts):
    """GT の 1 フレーム(t0/t1/t2/t3)を ADR 0006 正準化済みの 8 層 v1.4 gt view へ畳む。

    マッピング(sealeval._gt_frame_to_view と整合・t2 は argmax で単一ラベル化):
      risk_tier      = t0.risk_tier               (恒等・語彙検証)
      t1_state       = t1.state                   (恒等・語彙検証)
      t2_mode        = canon(argmax(t2.mode))      (ADR 0006 2 クラスリネーム)
      t2_role        = argmax(t2.roles)            (恒等・語彙検証)
      t2_relation    = argmax(t2.relations)        (恒等・語彙検証)
      t3_hypothesis  = t3.hypothesis               (恒等・語彙検証)
      quality_regime = remap(t3.quality_regime)    (ADR 0006/0005 順位シフト)
      scene_regime   = t3.scene_regime             (恒等・語彙検証)
    """
    t0 = gt_frame.get("t0", {}) or {}
    t1 = gt_frame.get("t1", {}) or {}
    t2 = gt_frame.get("t2", {}) or {}
    t3 = gt_frame.get("t3", {}) or {}

    return {
        "risk_tier": _check_identity_label(
            "risk_tier", t0.get("risk_tier"), scenario_id=scenario_id, ts=ts),
        "t1_state": _check_identity_label(
            "t1_state", t1.get("state"), scenario_id=scenario_id, ts=ts),
        "t2_mode": canonicalize_mode_label(
            _argmax_label(t2.get("mode")), scenario_id=scenario_id, ts=ts),
        "t2_role": _check_identity_label(
            "t2_role", _argmax_label(t2.get("roles")), scenario_id=scenario_id, ts=ts),
        "t2_relation": _check_identity_label(
            "t2_relation", _argmax_label(t2.get("relations")),
            scenario_id=scenario_id, ts=ts),
        "t3_hypothesis": _check_identity_label(
            "t3_hypothesis", t3.get("hypothesis"), scenario_id=scenario_id, ts=ts),
        "quality_regime": canonicalize_quality_label(
            t3.get("quality_regime"), scenario_id=scenario_id, ts=ts),
        "scene_regime": _check_identity_label(
            "scene_regime", t3.get("scene_regime"), scenario_id=scenario_id, ts=ts),
    }


# ===========================================================================
# データ読み込み(PSO 入力 / GT)+ 対応検証
# ===========================================================================

class DataMismatch(Exception):
    """pso 入力と GT の対応(フレーム数・ts)不整合(=停止して報告)。"""


def _scenario_dirs(pso_dir, gt_dir):
    """PSO 側と GT 側の両方に存在する ns* ディレクトリ名を昇順で返す。

    片側にしか無いディレクトリがあれば停止して報告する(対応が取れない)。
    """
    pso_set = {d for d in os.listdir(pso_dir)
               if d.startswith("ns") and os.path.isdir(os.path.join(pso_dir, d))}
    gt_set = {d for d in os.listdir(gt_dir)
              if d.startswith("ns") and os.path.isdir(os.path.join(gt_dir, d))}
    only_pso = sorted(pso_set - gt_set)
    only_gt = sorted(gt_set - pso_set)
    if only_pso or only_gt:
        raise DataMismatch(
            "PSO 側と GT 側でシナリオディレクトリ集合が不一致(対応が取れない)。"
            f" PSO のみ={only_pso!r} GT のみ={only_gt!r}"
        )
    return sorted(pso_set)


def _load_pso(pso_path):
    """pso_input.jsonl(1 行 1 フレーム)を Snapshot dict 列として読む。"""
    snaps = []
    with open(pso_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            snaps.append(json.loads(line))
    return snaps


def _load_gt(gt_path):
    """ground_truth.yaml を読む。"""
    with open(gt_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ===========================================================================
# メイン処理
# ===========================================================================

def run(pso_dir, gt_dir, out_path):
    print(f"[1/6] シナリオ対応検証: PSO={pso_dir}")
    print(f"                       GT ={gt_dir}")
    dirs = _scenario_dirs(pso_dir, gt_dir)
    print(f"      共通シナリオ数: {len(dirs)}")

    print()
    print("[2/6] 各シナリオを読み込み・対応検証(フレーム数 / ts)します")
    scenario_inputs = {}   # scenario_id -> snaps
    scenario_gt = {}       # scenario_id -> [gt_view_v14, ...]
    dir_to_sid = {}        # dir_name -> scenario_id(GT 由来)
    total_frames = 0

    for dir_name in dirs:
        pso_path = os.path.join(pso_dir, dir_name, "pso_input.jsonl")
        gt_path = os.path.join(gt_dir, dir_name, "ground_truth.yaml")
        if not os.path.isfile(pso_path):
            raise DataMismatch(f"PSO 入力が存在しない: {pso_path}")
        if not os.path.isfile(gt_path):
            raise DataMismatch(f"GT が存在しない: {gt_path}")

        snaps = _load_pso(pso_path)
        gt_data = _load_gt(gt_path)
        timeline = gt_data.get("timeline", []) or []
        scenario_id = str(gt_data.get("scenario_id", dir_name))

        # --- フレーム数の対応検証 ---
        if len(snaps) != len(timeline):
            raise DataMismatch(
                f"[{dir_name}] pso 入力と GT のフレーム数が不一致: "
                f"pso={len(snaps)} gt={len(timeline)}(scenario_id={scenario_id})。停止する。"
            )

        # --- ts の対応検証(同一フレーム同一 ts) ---
        for i, (snap, gt_fr) in enumerate(zip(snaps, timeline)):
            pso_ts = float(snap.get("ts"))
            gt_ts = float(gt_fr.get("ts"))
            if pso_ts != gt_ts:
                raise DataMismatch(
                    f"[{dir_name}] frame {i} の ts が pso と GT で不一致: "
                    f"pso_ts={pso_ts} gt_ts={gt_ts}(scenario_id={scenario_id})。停止する。"
                )

        # --- GT を v1.4 8 層 gt view へ正準化(v1.3 固有ラベルがあればここで停止) ---
        gt_views = [
            gt_frame_to_v14_view(gt_fr, scenario_id=scenario_id, ts=gt_fr.get("ts"))
            for gt_fr in timeline
        ]

        scenario_inputs[scenario_id] = snaps
        scenario_gt[scenario_id] = gt_views
        dir_to_sid[dir_name] = scenario_id
        total_frames += len(snaps)

    print(f"      対応 OK: {len(dirs)} シナリオ・{total_frames} フレーム"
          f"(全シナリオでフレーム数・ts 一致)")
    print("      GT 正準化 OK: v1.3 固有ラベルは検出されず(各層 v1.4 語彙集合に収束)")

    spec = harness.canonical_metric_spec()

    # --- 既定(params=None・後方互換)で実走・採点 ---
    print()
    print("[3/7] 既定(params=None)で core.run_supreme を実走・採点します")
    supreme_acc, scored_layers, supreme_result = _score_with_params(
        scenario_inputs, scenario_gt, spec, params=None, label="default")
    print(f"      生成・採点 OK: {len(scenario_inputs)} シナリオ・8 層・2 回走行完全一致")
    print("      --- 既定 supreme 8 層 acc ---")
    for layer in scored_layers:
        print(f"        {layer:16s}: {supreme_acc[layer]:.4f}")

    # --- 参考 sanity 検査(旧アーキ ours の弱5 と桁違い乖離なら停止) ---
    print()
    print("[3b]  参考 sanity 検査(旧アーキ ours 弱5 と桁違い乖離が無いか・既定列)")
    sanity_warnings = []
    for layer, ours in _OURS_SANITY.items():
        diff = abs(supreme_acc[layer] - ours)
        flag = "OK" if diff <= _SANITY_ORDER_OF_MAGNITUDE else f"WARN(diff={diff:.3f})"
        print(f"        {layer:16s}: supreme={supreme_acc[layer]:.3f} ours={ours:.3f} [{flag}]")
        if diff > _SANITY_ORDER_OF_MAGNITUDE:
            sanity_warnings.append(
                f"{layer}: supreme={supreme_acc[layer]:.3f} vs ours={ours:.3f} "
                f"(|Δ|={diff:.3f} > {_SANITY_ORDER_OF_MAGNITUDE})"
            )
    if sanity_warnings:
        raise DataMismatch(
            "参考 sanity 検査で旧アーキ ours の弱5 と桁違いに乖離(配線/語彙ミスを疑う)。"
            "数字を出さず停止する:\n  - " + "\n  - ".join(sanity_warnings)
        )
    print("      sanity OK: 桁違いの乖離なし(注: 一致は強制しない・参考のみ)")

    # --- v021_core を練習データとして fit_supreme で学習(ADR 0025 Phase1b)---
    #     ⚠️ 学習も採点も同じ v021_core = in-sample(train=eval=楽観)。汎化の正直な推定は
    #        CV held-out(reports/cv-train-*.md)。trained 列は in-sample と分かる見出しにする。
    print()
    print("[4/7] v021_core を練習データとして core.fit_supreme で学習します(in-sample)")
    print("      [警告] 学習・採点ともに v021_core = train=eval(in-sample 楽観値)。"
          "正直な汎化は CV held-out。")
    trained = core.fit_supreme(scenario_inputs, scenario_gt)
    print(f"      学習 OK: learnable param 数 = {trained.learnable_param_count()}"
          "(t3 + scene・F-014 ガード対象)")

    # --- 学習(params=trained)で実走・採点 ---
    print()
    print("[5/7] 学習済み params=trained で core.run_supreme を実走・採点します(in-sample)")
    trained_acc, trained_layers, trained_result = _score_with_params(
        scenario_inputs, scenario_gt, spec, params=trained, label="trained")
    if trained_layers != scored_layers:
        raise DataMismatch(
            f"既定と学習で採点層が不一致: {scored_layers!r} != {trained_layers!r}。停止する。"
        )
    print("      生成・採点 OK: 8 層・2 回走行完全一致")
    print("      --- 既定 vs 学習(in-sample) 8 層 acc(学習対象=t3/scene のみ動く)---")
    for layer in scored_layers:
        d = supreme_acc[layer]
        t = trained_acc[layer]
        mark = "  <- 学習対象" if layer in CV_HELDOUT_LEARNED else ""
        print(f"        {layer:16s}: 既定={d:.4f}  学習(in-sample)={t:.4f}  "
              f"Δ={t - d:+.4f}{mark}")

    # --- baseline 取り込み + 項目別 verdict(既定列で・封印 verdict ではない)---
    print()
    print("[6/7] baseline(v1.4)を取り込み compare_items で項目別 verdict を出します(既定列)")
    baseline = sealeval.load_baseline_scores(BASELINE_V14, metric_spec=spec)
    supreme_scores = _ScoreResultAdapter(supreme_result)
    comparison = sealeval.compare_items(
        supreme_scores, baseline,
        delta_strong=DELTA_STRONG,
        weak_items=WEAK_ITEMS, strong_items=STRONG_ITEMS,
    )
    print(f"      success_goal(既定列) = {comparison.success_goal}")
    print("      CV held-out(正直): "
          f"scene {CV_HELDOUT_LEARNED['scene_regime']:.3f} / "
          f"t3 {CV_HELDOUT_LEARNED['t3_hypothesis']:.3f}（{CV_REPORT_REF}）")

    # --- レポート出力 ---
    print()
    print(f"[7/7] レポートを書き出します: {out_path}")
    report_md = _render_report(
        dirs=dirs,
        dir_to_sid=dir_to_sid,
        total_frames=total_frames,
        scored_layers=scored_layers,
        supreme_acc=supreme_acc,
        trained_acc=trained_acc,
        baseline=baseline,
        comparison=comparison,
    )
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report_md)
    print(f"      出力完了: {out_path}")

    return supreme_acc, trained_acc, comparison


def _score_with_params(scenario_inputs, scenario_gt, spec, *, params, label):
    """指定 params(None=既定 / trained=学習済み)で全シナリオを実走・採点し supreme_acc を返す。

    決定的検査(2 回走行で view・acc 完全一致)を内蔵する。params=None は既存の in-sample 既定
    経路そのもの(後方互換)。params が SupremeParams なら学習済み t3/scene を注入して実走する
    (ADR 0025 Phase1b・利得の実測)。

    Returns:
        (supreme_acc{layer:acc}, scored_layers, supreme_result)。
    """
    views_by_sid = core.run_supreme_scenarios(scenario_inputs, params=params)
    for sid, views in views_by_sid.items():
        if len(views) != len(scenario_gt[sid]):
            raise DataMismatch(
                f"[{label}][{sid}] supreme view 数({len(views)})が gt view 数"
                f"({len(scenario_gt[sid])})と不一致。停止する。"
            )

    # 決定性検査(2 回走行で完全一致)。
    views_by_sid_2 = core.run_supreme_scenarios(scenario_inputs, params=params)
    if views_by_sid != views_by_sid_2:
        raise DataMismatch(
            f"[{label}] 決定性検査に失敗: 2 回の run_supreme_scenarios が一致しない。停止する。"
        )

    trace = _build_trace(views_by_sid, scenario_gt)
    supreme_result = harness.score(trace, spec)
    supreme_result_2 = harness.score(trace, spec)

    scored_layers = list(supreme_result.layers)
    if len(scored_layers) != 8:
        raise DataMismatch(
            f"[{label}] 採点層数が 8 でない: {len(scored_layers)} ({scored_layers!r})。停止する。"
        )

    supreme_acc = {}
    for layer in scored_layers:
        a = supreme_result.layer_score(layer)
        a2 = supreme_result_2.layer_score(layer)
        if a != a2:
            raise DataMismatch(
                f"[{label}][{layer}] 2 回採点の acc が不一致: {a} != {a2}。停止する。"
            )
        if not (isinstance(a, float) and 0.0 <= a <= 1.0):
            raise DataMismatch(
                f"[{label}][{layer}] acc が [0,1] に無い: {a!r}。停止する。"
            )
        supreme_acc[layer] = a

    return supreme_acc, scored_layers, supreme_result


def _build_trace(views_by_sid, scenario_gt):
    """8 層 view + v1.4 gt view を harness.score 互換 trace へ束ねる。

    trace 形状: {scenario_id: [{"ts", "view"{8層}, "gt"{8層}}, ...]}。
    """
    trace = {}
    for sid, views in views_by_sid.items():
        gt_views = scenario_gt[sid]
        frames = []
        for i, view in enumerate(views):
            frames.append({
                "ts": float(i),
                "view": dict(view),
                "gt": dict(gt_views[i]),
            })
        trace[sid] = frames
    return trace


class _ScoreResultAdapter:
    """harness.ScoreResult を sealeval.compare_items 互換面(layer_score)にする薄いラッパ。

    NaN(分母 0=全 null 層)は None に正規化して no_data の素材にする
    (sealeval._SupremeScores と同方針)。
    """

    def __init__(self, score_result):
        import math
        self._result = score_result
        self._math = math
        self.layers = tuple(score_result.layers)

    def layer_score(self, layer):
        val = self._result.layer_score(layer)
        if val is None:
            return None
        if isinstance(val, float) and self._math.isnan(val):
            return None
        return val

    def overall(self):
        return self._result.overall()


# ===========================================================================
# レポート生成
# ===========================================================================

def _render_report(*, dirs, dir_to_sid, total_frames, scored_layers,
                   supreme_acc, trained_acc, baseline, comparison):
    """評価レポート(Markdown)を組み立てる。誤解防止のため冒頭に強い警告を置く。

    supreme_acc=既定(params=None)/ trained_acc=学習(params=trained・in-sample 楽観値)。
    両列を並べ、CV held-out(正直)を併記する(ADR 0025 Phase1b・楽観値を verdict に使わせない)。
    """
    now = datetime.datetime.now()
    stamp = now.strftime("%Y-%m-%d %H:%M")

    lines = []
    a = lines.append

    a("# 開発セット(v021_core)評価レポート — supreme vs baseline(v1.4)")
    a("")
    a(f"- 生成時刻: {stamp}")
    a(f"- 対象シナリオ: {len(dirs)} 件 / 総フレーム {total_frames}")
    a("- PSO 入力: planA-baseline/scenarios/v021_core(1 行 1 フレーム)")
    a("- GT: n04-feat/scenarios/v021_core(catalog 1.4.0・baseline 採点と同源)")
    a("- baseline 参照: results/baseline-catalog-1.4.0.md(v1.4・研究者再計測済み)")
    a("")

    # ----- 冒頭の強い警告 -----
    a("## ⚠️ 重大な警告: これは in-sample 評価であり最終 verdict に使ってはならない")
    a("")
    a("本レポートは **開発セット(v021_core)による in-sample 評価**である。"
      "v021_core は F-005 エラー分析(=supreme の改良モジュール F-007〜011 の開発)に"
      "**使用済み**であり、**汚染ゼロの封印評価ではない**。")
    a("")
    a("- ここに出る Δ や verdict・`success_goal` は **開発に使ったデータ上での自己採点**であり、"
      "**最終的な勝敗 verdict として用いてはならない**(過適合により楽観方向へ歪み得る)。")
    a("- 真の封印 verdict は **held-out 人手シナリオ**を前提とする"
      "(`docs/SEALED_EVAL_RUNBOOK.md` / F-013 の封印評価経路)。")
    a("- 本レポートの用途は、配線・語彙正準化の健全性確認と、開発セット上の"
      "現状把握(回帰検出の足場)に限る。")
    a("")
    a("### ⚠️ 学習(trained)列は in-sample 楽観値である(混同禁止)")
    a("")
    a("本レポートは `core.fit_supreme(v021_core)` で学習した params を **同じ v021_core で採点**"
      "する(ADR 0025 Phase1b)。**学習データ=採点データ=v021_core ＝ in-sample(train=eval)**"
      "であり、trained 列の数値は**楽観方向に歪んだ自己再代入値**である。")
    a("")
    a(f"- **汎化の正直な推定は CV held-out(lineage-disjoint 5-fold・`{CV_REPORT_REF}`)**: "
      f"scene_regime **{CV_HELDOUT_LEARNED['scene_regime']:.3f}**"
      f"(既定 {CV_HELDOUT_DEFAULT['scene_regime']:.3f}) / "
      f"t3_hypothesis **{CV_HELDOUT_LEARNED['t3_hypothesis']:.3f}**"
      f"(既定 {CV_HELDOUT_DEFAULT['t3_hypothesis']:.3f})。")
    a("- 学習対象は **t3_hypothesis / scene_regime のみ**(ADR 0025 決定2)。他 6 層は学習で"
      "動かない(既定列=学習列)。")
    a("- **trained 列を勝敗 verdict に使ってはならない**。下の verdict は既定列で算出し、"
      "封印 verdict でもない。")
    a("")

    # ----- 結果表(既定 / 学習(in-sample) / baseline / CV held-out(正直)を併記)-----
    a("## 8 層スコア(既定 / 学習(in-sample) / baseline / CV held-out)")
    a("")
    a("> verdict は**既定列**(params=None)を baseline と対比したもの(封印 verdict ではない)。"
      "学習(in-sample)列は楽観値・**verdict には使わない**。CV held-out 列のみが正直な汎化推定。")
    a("")
    a("| 層 | 区分 | 既定 acc | 学習(in-sample) acc | Δ(学習−既定) | "
      "baseline v1.4 | Δ(既定−base) | verdict(既定列) | CV held-out(正直) |")
    a("|---|---|---:|---:|---:|---:|---:|---|---:|")

    def _row(layer, kind):
        d = supreme_acc[layer]
        t = trained_acc[layer]
        b = baseline.layer_score(layer)
        v = comparison.verdict(layer)
        cv = CV_HELDOUT_LEARNED.get(layer)
        cv_cell = f"{cv:.4f}" if cv is not None else "—(学習対象外)"
        return (f"| {layer} | {kind} | {d:.4f} | {t:.4f} | {t - d:+.4f} | "
                f"{b:.4f} | {d - b:+.4f} | {v} | {cv_cell} |")

    # 強3 → 弱5 の順で並べる(verdict 区分が読みやすいように)。
    for layer in STRONG_ITEMS:
        a(_row(layer, "強"))
    for layer in WEAK_ITEMS:
        a(_row(layer, "弱"))
    a("")
    a("> 「Δ(学習−既定)」は in-sample 上での利得(t3/scene のみ非ゼロ・他層は学習対象外で 0)。"
      "**この利得は楽観値**。汎化は CV held-out 列を見ること: "
      f"scene {CV_HELDOUT_DEFAULT['scene_regime']:.3f}→{CV_HELDOUT_LEARNED['scene_regime']:.3f}"
      f"(+{CV_HELDOUT_LEARNED['scene_regime'] - CV_HELDOUT_DEFAULT['scene_regime']:.3f}) / "
      f"t3 {CV_HELDOUT_DEFAULT['t3_hypothesis']:.3f}→{CV_HELDOUT_LEARNED['t3_hypothesis']:.3f}"
      f"(+{CV_HELDOUT_LEARNED['t3_hypothesis'] - CV_HELDOUT_DEFAULT['t3_hypothesis']:.3f})。")
    a("")

    # ----- 小計(弱5 / 強3) -----
    a("### 小計(弱5 / 強3)")
    a("")
    weak_verdicts = [comparison.verdict(it) for it in WEAK_ITEMS]
    strong_verdicts = [comparison.verdict(it) for it in STRONG_ITEMS]
    weak_win = sum(1 for v in weak_verdicts if v == "win")
    weak_draw = sum(1 for v in weak_verdicts if v == "draw")
    weak_lose = sum(1 for v in weak_verdicts if v == "lose")
    strong_maint = sum(1 for v in strong_verdicts if v == "maintained")
    strong_deg = sum(1 for v in strong_verdicts if v == "degraded")

    def _mean(items):
        vals = [supreme_acc[it] for it in items]
        return sum(vals) / len(vals) if vals else float("nan")

    def _mean_base(items):
        vals = [baseline.layer_score(it) for it in items]
        return sum(vals) / len(vals) if vals else float("nan")

    a(f"- **弱5**(t2_mode / t2_relation / t3_hypothesis / scene_regime / quality_regime): "
      f"win {weak_win} / draw {weak_draw} / lose {weak_lose}"
      f"(supreme 平均 {_mean(WEAK_ITEMS):.4f} vs baseline 平均 {_mean_base(WEAK_ITEMS):.4f})")
    a(f"- **強3**(risk_tier / t1_state / t2_role): "
      f"maintained {strong_maint} / degraded {strong_deg}"
      f"(supreme 平均 {_mean(STRONG_ITEMS):.4f} vs baseline 平均 {_mean_base(STRONG_ITEMS):.4f})")
    overall_supreme = sum(supreme_acc[l] for l in scored_layers) / len(scored_layers)
    overall_base = sum(baseline.layer_score(l) for l in scored_layers) / len(scored_layers)
    a(f"- **8 層単純平均**: supreme {overall_supreme:.4f} vs baseline {overall_base:.4f}")
    a("")
    a(f"- **success_goal フラグ**: `{comparison.success_goal}` "
      f"(弱5 全 win ∧ 強3 全 maintained ∧ no_data 無し のとき True)")
    if comparison.no_data_items:
        a(f"- no_data 項目: {list(comparison.no_data_items)!r}")
    a("")
    a("> verdict 規約(ADR 0023 / 0012・δ=0.02): "
      "弱は Δ>δ→win / Δ<−δ→lose / |Δ|≤δ→draw、強は Δ<−δ→degraded / それ以外→maintained。"
      "`success_goal` は合否ゲートではなく報告フラグ(SPEC 非機能要件)。")
    a("")

    # ----- 学習利得(in-sample 楽観値 vs CV held-out 正直)-----
    a("## 学習利得 — in-sample(楽観)と CV held-out(正直)を混同しない")
    a("")
    a("`core.fit_supreme(v021_core)` で学習した params(=trained)を **同じ v021_core で採点**した"
      "利得(in-sample・train=eval)と、**lineage-disjoint 5-fold CV** の held-out 利得"
      f"(正直・`{CV_REPORT_REF}`)を並べる。学習対象は t3/scene のみ(ADR 0025 決定2)。")
    a("")
    a("| 層 | 既定(in-sample) | 学習(in-sample) | Δ in-sample(楽観) | "
      "既定(CV held-out) | 学習(CV held-out) | Δ CV held-out(正直) |")
    a("|---|---:|---:|---:|---:|---:|---:|")
    for layer in ("scene_regime", "t3_hypothesis"):
        d_in = supreme_acc[layer]
        t_in = trained_acc[layer]
        d_cv = CV_HELDOUT_DEFAULT[layer]
        t_cv = CV_HELDOUT_LEARNED[layer]
        a(f"| {layer} | {d_in:.4f} | {t_in:.4f} | {t_in - d_in:+.4f} | "
          f"{d_cv:.4f} | {t_cv:.4f} | {t_cv - d_cv:+.4f} |")
    a("")
    a("- **in-sample 列(楽観)**: 学習データ自身での再代入採点。trained は既定を下回らない設計"
      "(`fit_supreme` が train acc で良い方を採る)だが、**汎化を過大評価する**。")
    a("- **CV held-out 列(正直)**: 学習に使っていない fold で採点。**これが汎化の正直な推定**で、"
      "scene は **win 反転**(0.5571 > baseline 0.5429)、t3 は改善(0.4095・まだ lose)。")
    a("- いずれも **練習/CV 上の数値であって封印 verdict ではない**(最終確定は F-013 封印)。")
    a("")

    # ----- caveat -----
    a("## caveat(厳密性に関する注記)")
    a("")
    a("1. **GT への v1.3→v1.4 正準化適用(ADR 0006)**: GT(catalog 1.4.0)は v1.3 系語彙を含む"
      "ため、取込時に ADR 0006 の文書化済み機械マッピングを適用した:")
    a("   - mode: `alert_observation→side_rear_caution`、`conv_participation→uncertain`"
      "(他 8 クラス恒等)。")
    a("   - quality_regime: `GOOD→GOOD` / `PASS→DEGRADED` / `DEGRADED→BLOCK`(順位シフト)。")
    a("   - 他層(risk_tier / t1_state / t2_role / t2_relation / t3_hypothesis / scene_regime)"
      "は ADR 0006 にリネーム規定が無く恒等。各層で GT の採点値が supreme の v1.4 語彙集合に"
      "収まることを検証済み(v1.3 固有値は検出されず)。")
    a("   - リラベルは accuracy を保存する(exact-match 採点では GT 側ラベル分布の非対称は"
      "正しく処理される)。")
    a("2. **risk_tier の分母規約差**: baseline は短尺 T0 を NA 除外して non-null=125 で採点する"
      "のに対し、supreme は 210 全採点(ADR 0012 決定B)。**この層は厳密な apples-to-apples では"
      "ない**。弱5 は 210 ベースで比較可能。")
    a("3. **二重の in-sample 性**: (a) v021_core は supreme 開発に使用済み(dev-set 汚染)、"
      "かつ (b) 学習(trained)も同じ v021_core で fit→採点(train=eval)。**trained 列は二重に"
      "楽観**。汎化の正直な推定は CV held-out("
      f"`{CV_REPORT_REF}`)。本数値は封印 verdict ではない。")
    a("")

    # ----- 正準化の層別 OK 明記 -----
    a("## 語彙正準化の層別チェック結果")
    a("")
    a("ADR 0006 の正準化適用後、恒等にできない v1.3 固有ラベルは **どの層にも無かった**"
      "(あれば数字を出さず停止する設計)。層別:")
    a("")
    a("| 層 | 正準化 | 結果 |")
    a("|---|---|---|")
    a("| risk_tier | 恒等(語彙検証) | OK(v1.4 集合に収束) |")
    a("| t1_state | 恒等(語彙検証) | OK(v1.4 集合に収束) |")
    a("| t2_mode | ADR 0006 2 クラスリネーム | OK(リネーム後 v1.4 集合に収束) |")
    a("| t2_role | 恒等(語彙検証) | OK(v1.4 集合に収束) |")
    a("| t2_relation | 恒等(語彙検証) | OK(argmax 値が v1.4 集合に収束) |")
    a("| t3_hypothesis | 恒等(語彙検証) | OK(v1.4 集合に収束) |")
    a("| quality_regime | ADR 0006/0005 順位シフト | OK(シフト後 v1.4 集合に収束) |")
    a("| scene_regime | 恒等(語彙検証) | OK(v1.4 集合に収束) |")
    a("")

    # ----- 自己検査の記録 -----
    a("## 自己検査(捏造防止)の結果")
    a("")
    a("- 決定性: `run_supreme_scenarios` を **既定・学習の両 params で各 2 回走行**し supreme 8 層"
      "view・acc が完全一致(OK・決定的)。")
    a("- 採点層: ちょうど 8 層(Anomaly 不混入)・各 acc ∈ [0,1]・2 回採点完全一致(OK)。")
    a("- 参考 sanity: 旧アーキ ours 弱5 と桁違いの乖離なし(OK・一致は強制せず参考のみ・既定列)。")
    a("- 学習配線(ADR 0025 Phase1b): `core.fit_supreme(v021_core)` → `params=trained` を"
      "`run_supreme_scenarios` に注入して採点。trained 列は in-sample 楽観値・verdict には不使用。")
    a("")

    # ----- シナリオ対応表 -----
    a("## シナリオ対応(dir → scenario_id)")
    a("")
    a("PSO 入力(planA-baseline)と GT(n04-feat)はディレクトリ名で対応づけ、"
      "各シナリオでフレーム数・ts の一致を検証した。")
    a("")
    a("| dir | scenario_id(GT) |")
    a("|---|---|")
    for d in dirs:
        a(f"| {d} | {dir_to_sid[d]} |")
    a("")

    a("---")
    a("")
    a("_本レポートは supreme.* 公開 API(core / harness / sealeval)のみを用いて生成した"
      "(baseline コードは import していない=独立性)。GT 正準化は ADR 0006 の文書化済み"
      "マッピングをスクリプト内ローカル関数で適用したもので、supreme パッケージ本体は変更していない。_")
    a("")

    return "\n".join(lines)


# ===========================================================================
# エントリポイント
# ===========================================================================

def main():
    parser = argparse.ArgumentParser(
        description="開発セット(v021_core)評価ランナー: supreme vs baseline(v1.4)を 8 層で対比"
    )
    parser.add_argument("--pso-dir", default=DEFAULT_PSO_DIR,
                        help=f"PSO 入力ディレクトリ(既定: {DEFAULT_PSO_DIR})")
    parser.add_argument("--gt-dir", default=DEFAULT_GT_DIR,
                        help=f"GT ディレクトリ(既定: {DEFAULT_GT_DIR})")
    parser.add_argument("--out", default=None,
                        help="出力 Markdown パス(既定: reports/dev-eval-<YYYYMMDD-HHMM>.md)")
    args = parser.parse_args()

    out_path = args.out
    if out_path is None:
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M")
        out_path = os.path.join(DEFAULT_OUT_DIR, f"dev-eval-{stamp}.md")

    try:
        run(args.pso_dir, args.gt_dir, out_path)
    except (V13LabelError, DataMismatch,
            sealeval.BaselineSchemaMismatch, harness.MetricSpecMissingError) as e:
        print(file=sys.stderr)
        print("=" * 70, file=sys.stderr)
        print("STOP(数字を捏造せず停止しました)。", file=sys.stderr)
        print(f"  種別: {type(e).__name__}", file=sys.stderr)
        print(f"  内容: {e}", file=sys.stderr)
        print("=" * 70, file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
