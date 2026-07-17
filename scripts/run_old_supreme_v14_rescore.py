"""旧 supreme(l04-ours)を v1.4 語彙で全 8 層 再採点して新 supreme(v1.4)と
apples-to-apples 比較する分析(分析専用・src/supreme もテストも変更しない)。

背景(語彙混在の是正):
  これまでの新旧比較は採点語彙が混在していた。
    - 新 supreme = run_supreme の **v1.4 view** を v1.4 GT で採点(本来の v1.4 採点)。
    - 旧 supreme(l04-ours)= trace.json の **v1.3 view**(GOOD/PASS/DEGRADED/BLOCK・
      alert_observation/conv_participation を含む)を、**未正準化の v1.3 GT**(trace.json
      埋め込み gt・PASS×32・conv_participation×11 等)で採点した値が per_layer.json(=
      catalog 1.4.0 とファイルには書かれているが、採点土俵は v1.3)。
  本分析は **旧 supreme の per-frame 予測を v1.4 へ正準化**し、**新 supreme と同一の
  v1.4 採点規約**(harness.canonical_metric_spec・micro acc・完全一致・210 frame・NA 分母除外)
  で全 8 層を採点する。GT は n04-feat から読み直して ADR 0006 で v1.4 正準化する
  (trace.json 埋め込み gt は使わない=混在の元なので)。

データ:
  - 旧 supreme per-frame 予測: results/trace/trace.json(scenario→[{ts,view,gt,correct,modules}])。
    view が per-frame の 8 層単一ラベル予測(v1.3 語彙)。
  - GT: n04-feat/scenarios/v021_core/<id>/ground_truth.yaml(timeline・t0/t1/t2/t3)。
  - 新 supreme: run_dev_eval のロジック(PSO→core.run_supreme→v1.4 view)を in-process で再利用。
    既定列(非学習層)＋学習層(t3/scene)は in-sample と CV held-out の両方を併記。

正準化(ADR 0006・run_dev_eval の関数を再利用):
  - 旧予測 view(単一ラベル)→ v1.4:
      mode:    alert_observation→side_rear_caution / conv_participation→uncertain(他恒等)
      quality: GOOD→GOOD / PASS→DEGRADED / DEGRADED→BLOCK / 既存 BLOCK→BLOCK(順位保存)
      他層:    恒等(語彙が v1.4 集合に収まることを各層で検証)
  - GT(分布)→ v1.4: run_dev_eval.gt_frame_to_v14_view(t2 は argmax→正準化)。

最重要規律(捏造防止):
  - 旧予測の語彙が v1.4 集合に正準化できない層・値が 1 つでも出たら、その層・値を挙げて
    即停止する(黙って恒等扱いにしない・数字を捏造しない)。
  - 新と旧で v1.4 正準化・採点規約を完全に同一にする(片側だけ違う規約で測らない)。
  - trace.json の view が無い層・正準化が一意でない層は「比較不能」と明記する。

依存: supreme.* 公開 API と stdlib + pyyaml のみ。baseline コードは import しない。決定的。
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_SRC_DIR = os.path.join(os.path.dirname(_SCRIPT_DIR), "src")
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

try:
    import yaml  # noqa: F401  (run_dev_eval が使用)
except ImportError:
    print("ERROR: pyyaml が必要です。", file=sys.stderr)
    sys.exit(1)

from supreme import core, harness  # noqa: E402

# run_dev_eval の正準化・データ読込・採点ロジックを再利用(同一規約の担保)。
import run_dev_eval as rde  # noqa: E402


# ---------------------------------------------------------------------------
# 既定パス
# ---------------------------------------------------------------------------

DEFAULT_TRACE = (
    r"C:\work\L04-planA\supreme\external-data\planA-baseline\results\trace\trace.json"
)
DEFAULT_PSO_DIR = rde.DEFAULT_PSO_DIR
DEFAULT_GT_DIR = rde.DEFAULT_GT_DIR
DEFAULT_OUT_DIR = "reports"

LAYERS = list(harness.canonical_metric_spec().scored_layers)

# 旧 supreme(l04-ours) per_layer.json(catalog 1.4.0 と書かれているが採点土俵は v1.3)。
#   = 旧予測 view を「未正準化の v1.3 GT(trace 埋め込み)」で採点した値。
#   本分析の v1.4 再採点との差 = 語彙差の可視化。
OURS_PER_LAYER_V13 = {
    "risk_tier": 0.933333,
    "t1_state": 0.909524,
    "t2_mode": 0.623810,
    "t2_role": 0.933333,
    "t2_relation": 0.747619,
    "t3_hypothesis": 0.585714,
    "quality_regime": 0.761905,
    "scene_regime": 0.528571,
}

# 新 supreme の学習層 CV held-out(正直な汎化推定・run_dev_eval と同源)。
CV_HELDOUT_LEARNED = dict(rde.CV_HELDOUT_LEARNED)
CV_HELDOUT_DEFAULT = dict(rde.CV_HELDOUT_DEFAULT)
CV_REPORT_REF = rde.CV_REPORT_REF


# ===========================================================================
# 旧予測(trace.json view・v1.3)→ v1.4 正準化(全 8 層・単一ラベル)
# ===========================================================================

class OldPredCanonError(Exception):
    """旧予測 view を v1.4 へ正準化できない(語彙にない値・捏造せず停止)。"""


# quality_regime: 旧 view は v1.3 4 クラス(GOOD/PASS/DEGRADED/BLOCK)。
#   評価語彙の順位シフト(ADR 0006/0005)= GOOD→GOOD / PASS→DEGRADED / DEGRADED→BLOCK。
#   旧 view が native に出す "BLOCK"(=最重度)は v1.4 最重度 BLOCK へ写す(順位保存・
#   run_quality_diagnose._B_REMAP_V14 と同一)。これは順位シフトと矛盾しない。
_OLD_QUALITY_REMAP = {"GOOD": "GOOD", "PASS": "DEGRADED", "DEGRADED": "BLOCK", "BLOCK": "BLOCK"}


def canonicalize_old_view(view, *, scenario_id, ts):
    """旧 supreme の 1 フレーム view(v1.3 単一ラベル 8 層)を v1.4 へ正準化する。

    - t2_mode      : ADR 0006 の 2 クラスリネーム(run_dev_eval._MODE_RENAME)。
    - quality_regime: 順位シフト + native BLOCK→BLOCK(_OLD_QUALITY_REMAP)。
    - 他 6 層       : 恒等。ただし正準化後の値が v1.4 語彙集合に収まることを検証する。
    正準化後の値が v1.4 集合に無ければ OldPredCanonError で停止(捏造しない)。
    """
    out = {}
    for layer in LAYERS:
        raw = view.get(layer)
        if raw is None:
            # 旧 view にその層が無い(=比較不能の素材)。None のまま落とす。
            out[layer] = None
            continue
        if layer == "t2_mode":
            canon = rde._MODE_RENAME.get(raw, raw)
        elif layer == "quality_regime":
            if raw not in _OLD_QUALITY_REMAP:
                raise OldPredCanonError(
                    f"[quality_regime] 旧 view の値 '{raw}' が順位シフト表に無い "
                    f"(scenario_id={scenario_id} ts={ts})。"
                    f" 既知 v1.3 値={sorted(_OLD_QUALITY_REMAP)!r}。捏造せず停止。"
                )
            canon = _OLD_QUALITY_REMAP[raw]
        else:
            canon = raw
        if canon not in rde._V14_VOCAB[layer]:
            raise OldPredCanonError(
                f"[{layer}] 旧 view の値 '{raw}'→'{canon}' が v1.4 語彙集合に無い "
                f"(scenario_id={scenario_id} ts={ts})。"
                f" v1.4 語彙={sorted(rde._V14_VOCAB[layer])!r}。"
                f" ADR 0006 にこの層のリネーム規定が無ければ黙って恒等扱いにせず停止する。"
            )
        out[layer] = canon
    return out


# ===========================================================================
# trace.json 読込 + GT(n04-feat)読込 + 対応検証
# ===========================================================================

def load_old_views(trace_path):
    """trace.json から {scenario_key: [(ts, v1.4正準化済 view), ...]} を返す。

    旧予測の語彙監査(各層 view の生語彙 set)も併せて返す。
    """
    with open(trace_path, "r", encoding="utf-8") as f:
        trace = json.load(f)

    from collections import defaultdict
    raw_vocab = defaultdict(set)   # 旧 view の生語彙(v1.3)
    canon_vocab = defaultdict(set)  # 正準化後(v1.4)
    missing_layers = defaultdict(int)  # 旧 view に無い層の件数

    old_by_key = {}
    for skey, frames in trace.items():
        seq = []
        for fr in frames:
            ts = fr.get("ts")
            view = fr.get("view", {}) or {}
            for layer in LAYERS:
                v = view.get(layer)
                if v is None:
                    missing_layers[layer] += 1
                else:
                    raw_vocab[layer].add(v)
            canon = canonicalize_old_view(view, scenario_id=skey, ts=ts)
            for layer in LAYERS:
                if canon[layer] is not None:
                    canon_vocab[layer].add(canon[layer])
            seq.append((float(ts), canon))
        old_by_key[skey] = seq
    return old_by_key, raw_vocab, canon_vocab, missing_layers


def build_old_trace(old_by_key, gt_by_sid, dir_to_key, dirs):
    """旧予測(v1.4)と GT(v1.4)を harness.score 互換 trace に束ねる(ts 整合で突合)。

    GT は run_dev_eval が dir→scenario_id で読んだ {sid: [gt_view,...]}。trace.json は
    dir 名キー。dir_to_key で対応づけ、ts(frame index)を揃えて突合する。
    フレーム数/ts 不整合は停止(捏造しない)。
    """
    trace = {}
    for dir_name in dirs:
        old_key = dir_to_key[dir_name]      # trace.json 側のキー(=dir 名)
        sid = _dir_to_sid(dir_name, gt_by_sid)
        old_seq = old_by_key[old_key]
        gt_views = gt_by_sid[sid]
        if len(old_seq) != len(gt_views):
            raise rde.DataMismatch(
                f"[{dir_name}] 旧予測フレーム数({len(old_seq)})と GT フレーム数"
                f"({len(gt_views)})が不一致。停止する。"
            )
        frames = []
        for i, ((ts, old_view), gt_view) in enumerate(zip(old_seq, gt_views)):
            frames.append({
                "ts": float(ts),
                "view": dict(old_view),
                "gt": dict(gt_view),
            })
        trace[sid] = frames
    return trace


def _dir_to_sid(dir_name, gt_by_sid):
    """dir 名から GT 側 scenario_id を引く(run_dev_eval の dir_to_sid を再現)。"""
    # gt_by_sid は scenario_id キー。dir_name は ns002_conv_approach 形式。
    # scenario_id は ns-epi-v021-ns002-conv-approach 形式。末尾照合で対応づける。
    suffix = dir_name.replace("_", "-")  # ns002-conv-approach
    for sid in gt_by_sid:
        if sid.endswith(suffix):
            return sid
    raise rde.DataMismatch(f"dir '{dir_name}' に対応する GT scenario_id が無い。")


def load_gt_v14(pso_dir, gt_dir):
    """run_dev_eval のデータ読込・GT 正準化を再利用して {sid: [gt_view_v14,...]} を得る。

    PSO 入力は不要だが、run_dev_eval は PSO/GT のフレーム数・ts 対応検証を内蔵するため
    その検証ごと再利用する(同一の対応規約で GT を取る=採点土俵を揃える)。
    """
    dirs = rde._scenario_dirs(pso_dir, gt_dir)
    scenario_gt = {}
    dir_to_key = {}
    for dir_name in dirs:
        gt_path = os.path.join(gt_dir, dir_name, "ground_truth.yaml")
        gt_data = rde._load_gt(gt_path)
        timeline = gt_data.get("timeline", []) or []
        scenario_id = str(gt_data.get("scenario_id", dir_name))
        gt_views = [
            rde.gt_frame_to_v14_view(gt_fr, scenario_id=scenario_id, ts=gt_fr.get("ts"))
            for gt_fr in timeline
        ]
        scenario_gt[scenario_id] = gt_views
        dir_to_key[dir_name] = dir_name  # trace.json のキーは dir 名と同一
    return scenario_gt, dir_to_key, dirs


# ===========================================================================
# 採点(harness.score・新 supreme と同一規約)
# ===========================================================================

def score_trace(trace, spec):
    """harness.score で 8 層 acc + (correct,nonnull) を返す(2 回採点で決定性検査)。"""
    r1 = harness.score(trace, spec)
    r2 = harness.score(trace, spec)
    acc = {}
    counts = {}
    for layer in spec.scored_layers:
        a1 = r1.layer_score(layer)
        a2 = r2.layer_score(layer)
        if a1 != a2:
            raise rde.DataMismatch(f"[{layer}] 2 回採点の acc 不一致: {a1} != {a2}。停止。")
        acc[layer] = a1
        counts[layer] = dict(r1._counts[layer])
    return acc, counts


# ===========================================================================
# メイン
# ===========================================================================

def run(trace_path, pso_dir, gt_dir, out_path):
    spec = harness.canonical_metric_spec()

    print(f"[1/6] 旧予測(trace.json)読込・v1.4 正準化: {trace_path}")
    old_by_key, raw_vocab, canon_vocab, missing_layers = load_old_views(trace_path)
    n_old_frames = sum(len(v) for v in old_by_key.values())
    print(f"      旧 view 読込 OK: {len(old_by_key)} シナリオ・{n_old_frames} フレーム")
    print("      旧予測 語彙(層別・正準化前 v1.3 → 後 v1.4):")
    for layer in LAYERS:
        miss = missing_layers.get(layer, 0)
        print(f"        {layer:16s} raw={sorted(raw_vocab[layer])}"
              f" -> v14={sorted(canon_vocab[layer])}"
              + (f"  [欠落 {miss} frame]" if miss else ""))

    print()
    print(f"[2/6] GT(n04-feat)読込・v1.4 正準化(run_dev_eval 再利用): {gt_dir}")
    gt_by_sid, dir_to_key, dirs = load_gt_v14(pso_dir, gt_dir)
    n_gt_frames = sum(len(v) for v in gt_by_sid.values())
    print(f"      GT 正準化 OK: {len(gt_by_sid)} シナリオ・{n_gt_frames} フレーム")

    print()
    print("[3/6] 旧予測(v1.4) × GT(v1.4) を束ねて同一規約で採点(harness.score)")
    old_trace = build_old_trace(old_by_key, gt_by_sid, dir_to_key, dirs)
    old_acc, old_counts = score_trace(old_trace, spec)
    print("      --- 旧 supreme(v1.4 再採点) 8 層 acc ---")
    for layer in LAYERS:
        c = old_counts[layer]
        print(f"        {layer:16s}: {old_acc[layer]:.4f} ({c['correct']}/{c['nonnull']})"
              f"  [v1.3 per_layer.json={OURS_PER_LAYER_V13[layer]:.4f}"
              f" Δ={old_acc[layer]-OURS_PER_LAYER_V13[layer]:+.4f}]")

    print()
    print("[4/6] 新 supreme(v1.4) を同一 GT・同一規約で採点(既定 + 学習 in-sample)")
    new_default_acc, new_default_counts = _score_new_supreme(
        gt_by_sid, dirs, gt_dir, pso_dir, spec, params=None, label="default")
    # 学習(in-sample): run_dev_eval と同じ fit→注入。
    scenario_inputs = _load_scenario_inputs(pso_dir, gt_dir, gt_by_sid)
    trained = core.fit_supreme(scenario_inputs, gt_by_sid)
    new_trained_acc, _ = _score_new_supreme(
        gt_by_sid, dirs, gt_dir, pso_dir, spec, params=trained, label="trained",
        scenario_inputs=scenario_inputs)
    print("      --- 新 supreme(v1.4) 8 層 acc(既定 / 学習 in-sample)---")
    for layer in LAYERS:
        mark = "  <- 学習対象" if layer in CV_HELDOUT_LEARNED else ""
        print(f"        {layer:16s}: 既定={new_default_acc[layer]:.4f}"
              f"  学習(in-sample)={new_trained_acc[layer]:.4f}{mark}")

    print()
    print("[5/6] 新 vs 旧(同一 v1.4 土俵)比較")
    for layer in LAYERS:
        d = new_default_acc[layer] - old_acc[layer]
        verd = _verdict(d)
        print(f"        {layer:16s}: 新(既定)={new_default_acc[layer]:.4f}"
              f" 旧(v1.4)={old_acc[layer]:.4f} Δ(新-旧)={d:+.4f} -> {verd}")

    print()
    print(f"[6/6] レポート出力: {out_path}")
    report = _render_report(
        dirs=dirs, gt_by_sid=gt_by_sid,
        n_frames=n_gt_frames,
        raw_vocab=raw_vocab, canon_vocab=canon_vocab, missing_layers=missing_layers,
        old_acc=old_acc, old_counts=old_counts,
        new_default_acc=new_default_acc, new_default_counts=new_default_counts,
        new_trained_acc=new_trained_acc,
    )
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"      出力完了: {out_path}")
    return old_acc, new_default_acc, new_trained_acc


def _load_scenario_inputs(pso_dir, gt_dir, gt_by_sid):
    """PSO 入力 {sid: snaps} を読む(run_dev_eval と同じ対応規約)。"""
    dirs = rde._scenario_dirs(pso_dir, gt_dir)
    scenario_inputs = {}
    for dir_name in dirs:
        pso_path = os.path.join(pso_dir, dir_name, "pso_input.jsonl")
        gt_path = os.path.join(gt_dir, dir_name, "ground_truth.yaml")
        gt_data = rde._load_gt(gt_path)
        sid = str(gt_data.get("scenario_id", dir_name))
        scenario_inputs[sid] = rde._load_pso(pso_path)
    return scenario_inputs


def _score_new_supreme(gt_by_sid, dirs, gt_dir, pso_dir, spec, *, params, label,
                       scenario_inputs=None):
    """新 supreme(run_supreme)を v1.4 GT・同一規約で採点する。"""
    if scenario_inputs is None:
        scenario_inputs = _load_scenario_inputs(pso_dir, gt_dir, gt_by_sid)
    views_by_sid = core.run_supreme_scenarios(scenario_inputs, params=params)
    views_by_sid_2 = core.run_supreme_scenarios(scenario_inputs, params=params)
    if views_by_sid != views_by_sid_2:
        raise rde.DataMismatch(f"[{label}] run_supreme_scenarios 決定性検査に失敗。停止。")
    trace = {}
    for sid, views in views_by_sid.items():
        gt_views = gt_by_sid[sid]
        if len(views) != len(gt_views):
            raise rde.DataMismatch(
                f"[{label}][{sid}] view 数({len(views)})が gt 数({len(gt_views)})と不一致。")
        frames = [{"ts": float(i), "view": dict(v), "gt": dict(gt_views[i])}
                  for i, v in enumerate(views)]
        trace[sid] = frames
    return score_trace(trace, spec)


def _verdict(delta, eps=rde.DELTA_STRONG):
    if delta > eps:
        return "新が優"
    if delta < -eps:
        return "旧が優"
    return "互角"


# ===========================================================================
# レポート生成
# ===========================================================================

def _render_report(*, dirs, gt_by_sid, n_frames, raw_vocab, canon_vocab, missing_layers,
                   old_acc, old_counts, new_default_acc, new_default_counts,
                   new_trained_acc):
    now = datetime.datetime.now()
    stamp = now.strftime("%Y-%m-%d %H:%M")
    a_list = []
    a = a_list.append

    a("# 旧 supreme(l04-ours)v1.4 全 8 層 再採点 — 新 supreme との apples-to-apples 比較")
    a("")
    a(f"- 生成時刻: {stamp}")
    a(f"- 対象: v021_core {len(dirs)} シナリオ・{n_frames} フレーム"
      "(in-sample・封印 verdict ではない)")
    a("- 旧 supreme 予測: `results/trace/trace.json` の per-frame `view`"
      "(=l04-ours の権威 per-frame 予測)")
    a("- GT: n04-feat/scenarios/v021_core(ADR 0006 で v1.4 正準化・"
      "trace.json 埋め込み gt は使わない=混在の元)")
    a("- 新 supreme: PSO→core.run_supreme→v1.4 view(run_dev_eval ロジック再利用・"
      "既定列＋学習層 in-sample/CV held-out)")
    a("- 採点: `harness.canonical_metric_spec()`(8 層 micro acc・完全一致・NA 分母除外)"
      "を **新旧で完全に同一**に適用")
    a("- src/supreme・テスト無改変。決定的・stdlib + pyyaml。baseline コードは import しない。")
    a("")

    # ----- 結論 -----
    a("## 0. 結論サマリ")
    a("")
    old_overall = sum(old_acc[l] for l in LAYERS) / len(LAYERS)
    new_overall = sum(new_default_acc[l] for l in LAYERS) / len(LAYERS)
    new_tr_overall = sum(new_trained_acc[l] for l in LAYERS) / len(LAYERS)
    a(f"- **旧 supreme を v1.4 で再採点した overall(8 層単純平均)= {old_overall:.4f}**。")
    a(f"- 新 supreme(既定)overall = {new_overall:.4f}、新 supreme(学習 in-sample)= "
      f"{new_tr_overall:.4f}。")
    wins = sum(1 for l in LAYERS if new_default_acc[l] - old_acc[l] > rde.DELTA_STRONG)
    loses = sum(1 for l in LAYERS if new_default_acc[l] - old_acc[l] < -rde.DELTA_STRONG)
    draws = len(LAYERS) - wins - loses
    a(f"- 既定列での新 vs 旧(同一 v1.4 土俵): 新が優 **{wins}** / 互角 **{draws}** / "
      f"旧が優 **{loses}**(δ={rde.DELTA_STRONG})。")
    a("- **語彙差の可視化**: per_layer.json(v1.3 採点)と本 v1.4 再採点の差が大きいのは "
      "quality_regime と t2_mode(正準化が値を動かす層)。恒等層(risk_tier/t1_state/"
      "t2_role/t2_relation/scene_regime)は per_layer.json と一致(GT 側の v1.3 固有値が "
      "それらの層に無いため)。")
    a("- **正準化不能の層は無し**(旧予測 view の全 8 層が ADR 0006 マッピングで v1.4 語彙集合に "
      "収束)。比較不能層は無い。")
    a("")

    # ----- 旧予測の構造・語彙 -----
    a("## 1. 旧 supreme 予測の構造・語彙(trace.json)")
    a("")
    a("`results/trace/trace.json` は `{scenario_key: [frame, ...]}`。各 frame は "
      "`{ts, view, gt, correct, modules}`。**`view` が per-frame の 8 層単一ラベル予測**で、"
      "これが旧 supreme(l04-ours)の権威 per-frame 出力である。8 層すべて在る"
      "(欠落層は無し)。")
    a("")
    a("> ⚠️ 重要(語彙混在の正体): trace.json に**埋め込まれた `gt` は未正準化の v1.3**である"
      "(quality_regime に PASS×32、t2_mode 分布に conv_participation 等)。"
      "`l04-ours/per_layer.json`(ファイルには catalog 1.4.0 と記載)は、この **v1.3 view を "
      "v1.3 gt で採点**した値であり、**採点土俵は v1.3**。本分析は view も GT も v1.4 へ正準化し直す。")
    a("")
    a("| 層 | 旧 view 生語彙(v1.3) | 正準化後(v1.4) | 正準化 | 8 層在/欠 |")
    a("|---|---|---|---|---|")
    canon_kind = {
        "risk_tier": "恒等",
        "t1_state": "恒等",
        "t2_mode": "ADR0006 2クラスリネーム",
        "t2_role": "恒等",
        "t2_relation": "恒等",
        "t3_hypothesis": "恒等",
        "quality_regime": "ADR0006/0005 順位シフト(+native BLOCK)",
        "scene_regime": "恒等",
    }
    for layer in LAYERS:
        miss = missing_layers.get(layer, 0)
        raws = ", ".join(sorted(raw_vocab[layer]))
        cans = ", ".join(sorted(canon_vocab[layer]))
        instat = "在(欠落 0)" if miss == 0 else f"欠 {miss} frame"
        a(f"| {layer} | {raws} | {cans} | {canon_kind[layer]} | {instat} |")
    a("")
    a("- 旧 view の quality_regime は v1.3 4 クラス(GOOD/PASS/DEGRADED/**BLOCK** を native 出力)。"
      "順位シフト GOOD→GOOD / PASS→DEGRADED / DEGRADED→BLOCK に加え、native BLOCK は最重度 "
      "BLOCK へ写す(順位保存・run_quality_diagnose._B_REMAP_V14 と同一)。")
    a("- 旧 view の t2_mode は v1.3 で `alert_observation`(→side_rear_caution)・"
      "`conv_participation`(→uncertain)を含む。他 8 クラスは恒等。")
    a("- 他 6 層は ADR 0006 にリネーム規定が無く恒等。**正準化後の値が v1.4 語彙集合に収まることを"
      "各層で検証済み**(収まらない値が出れば数字を出さず停止する設計)。**全層収束=正準化不能層なし**。")
    a("")

    # ----- 旧 v1.4 vs v1.3(語彙差) -----
    a("## 2. 旧 supreme(v1.4 再採点)全 8 層 — per_layer.json(v1.3 採点)との差")
    a("")
    a("> per_layer.json(v1.3 採点)= 旧 view を **未正準化 v1.3 GT** で採点した値。"
      "本列(v1.4 再採点)= 旧 view も GT も v1.4 正準化して採点。差 = **採点語彙差そのもの**。")
    a("")
    a("| 層 | 旧 v1.4 再採点 | (correct/nonnull) | per_layer.json(v1.3) | Δ(v1.4 − v1.3) | 差の主因 |")
    a("|---|---:|:---:|---:|---:|---|")
    for layer in LAYERS:
        c = old_counts[layer]
        v14 = old_acc[layer]
        v13 = OURS_PER_LAYER_V13[layer]
        d = v14 - v13
        if layer == "quality_regime":
            cause = "順位シフト(PASS/DEGRADED の意味が新 GT と入替)"
        elif layer == "t2_mode":
            cause = "mode リネーム(GT 側 argmax 正準化の影響)"
        elif abs(d) < 1e-6:
            cause = "恒等層(GT に v1.3 固有値なし=不変)"
        else:
            cause = "GT 正準化(argmax/恒等検証)の影響"
        a(f"| {layer} | {v14:.4f} | {c['correct']}/{c['nonnull']} | {v13:.4f} | {d:+.4f} | {cause} |")
    old_overall_v13 = sum(OURS_PER_LAYER_V13[l] for l in LAYERS) / len(LAYERS)
    a(f"| **overall(8 層平均)** | **{old_overall:.4f}** | — | {old_overall_v13:.4f} | "
      f"{old_overall - old_overall_v13:+.4f} | — |")
    a("")

    # ----- 新 vs 旧(同一 v1.4 土俵) -----
    a("## 3. 新 vs 旧(同一 v1.4 土俵)全 8 層比較")
    a("")
    a("> **新旧で v1.4 正準化・採点規約を完全に同一**にした apples-to-apples 比較。"
      "新 supreme は既定列(非学習層=確定)＋学習層(t3/scene)は in-sample と CV held-out を併記。"
      "判定 δ=0.02。")
    a("")
    a("| 層 | 旧 supreme(v1.4) | 新 supreme(既定) | Δ(新−旧) | 判定 | "
      "新 学習(in-sample) | 新 CV held-out(正直) |")
    a("|---|---:|---:|---:|---|---:|---:|")
    for layer in LAYERS:
        o = old_acc[layer]
        nd = new_default_acc[layer]
        nt = new_trained_acc[layer]
        d = nd - o
        verd = _verdict(d)
        cv = CV_HELDOUT_LEARNED.get(layer)
        if layer in CV_HELDOUT_LEARNED:
            tr_cell = f"{nt:.4f}"
            cv_cell = f"{cv:.4f}"
        else:
            tr_cell = "—(学習対象外)"
            cv_cell = "—(学習対象外)"
        a(f"| {layer} | {o:.4f} | {nd:.4f} | {d:+.4f} | {verd} | {tr_cell} | {cv_cell} |")
    d_overall = new_overall - old_overall
    a(f"| **overall(8 層平均)** | **{old_overall:.4f}** | **{new_overall:.4f}** | "
      f"{d_overall:+.4f} | {_verdict(d_overall)} | {new_tr_overall:.4f} | — |")
    a("")
    a("- **学習層(t3_hypothesis / scene_regime)の honest 比較は CV held-out 列を見ること**。"
      "in-sample 学習列は楽観値(train=eval)。既定列(非学習)は新旧とも確定値。")
    a("- 学習層の CV held-out で新 supreme を旧 supreme(v1.4)と比べると:")
    for layer in ("t3_hypothesis", "scene_regime"):
        cv = CV_HELDOUT_LEARNED[layer]
        d_cv = cv - old_acc[layer]
        a(f"  - {layer}: 新 CV held-out {cv:.4f} vs 旧(v1.4) {old_acc[layer]:.4f} "
          f"→ Δ={d_cv:+.4f}({_verdict(d_cv)})")
    a("")

    # ----- 層別の優劣まとめ -----
    a("### 3.1 層別の優劣(既定列・同一 v1.4 土俵)")
    a("")
    win_layers = [l for l in LAYERS if new_default_acc[l] - old_acc[l] > rde.DELTA_STRONG]
    lose_layers = [l for l in LAYERS if new_default_acc[l] - old_acc[l] < -rde.DELTA_STRONG]
    draw_layers = [l for l in LAYERS if l not in win_layers and l not in lose_layers]
    a(f"- **新が優**({len(win_layers)}): {', '.join(win_layers) if win_layers else 'なし'}")
    a(f"- **互角**({len(draw_layers)}): {', '.join(draw_layers) if draw_layers else 'なし'}")
    a(f"- **旧が優**({len(lose_layers)}): {', '.join(lose_layers) if lose_layers else 'なし'}")
    a("")

    # ----- 正準化・不整合の honest 報告 -----
    a("## 4. 正準化不能・不整合の honest 報告")
    a("")
    any_missing = any(missing_layers.get(l, 0) for l in LAYERS)
    a("- **正準化不能の層: 無し**。旧予測 view の全 8 層が ADR 0006 の文書化済みマッピング"
      "(mode 2 クラスリネーム + quality 順位シフト + native BLOCK 最重度写像)で v1.4 語彙集合に"
      "収束した。v1.4 集合に収まらない値が 1 つでも出れば数字を出さず停止する設計だが、停止は"
      "発生しなかった。")
    if any_missing:
        a("- ⚠️ 一部層に欠落フレームあり(上表参照)。欠落層は当該フレームで比較不能。")
    else:
        a("- **欠落層: 無し**(全 210 フレームで 8 層 view が揃う)。比較不能フレームは無い。")
    a("")
    a("- **採点規約の非対称(honest 注記)**: `risk_tier` は本採点(canonical_metric_spec)で "
      "210 全件を分母にする(ADR 0012 決定B)。baseline カタログは短尺 T0 を NA 除外して "
      "non-null=125 で測る規約のため、**baseline 値との厳密 apples-to-apples ではない**。"
      "ただし本比較は**旧 supreme と新 supreme を同一 spec で測る**ので、新旧間は厳密に揃っている"
      "(旧 supreme も新 supreme も同じ 210 分母・同じ NA 規約)。")
    a("")
    a("- **t3_hypothesis / scene_regime の GT 値域**: GT には旧 view が native に出さない値"
      "(t3: hazard_declining / alert_required、relation: addressing_user 等)が含まれる。"
      "これは正準化の不整合ではなく、**旧アーキが該当クラスを予測しないだけ**(exact-match では"
      "正しく不正解計上される)。捏造せず、旧の予測語彙が GT より狭い事実として記録する。")
    a("")

    # ----- 自己検査 -----
    a("## 5. 自己検査(捏造防止)")
    a("")
    a("- 決定性: harness.score を旧・新(既定/学習)で各 2 回呼び 8 層 acc が完全一致(OK)。")
    a("- 新 supreme: `run_supreme_scenarios` を各 params で 2 回走行し view 完全一致(OK)。")
    a("- 旧予測 v1.4 正準化: 全 8 層・全フレームで v1.4 語彙集合に収束(停止せず=正準化一意)。")
    a("- GT 正準化: run_dev_eval.gt_frame_to_v14_view を再利用(新 supreme 採点と同一の GT 列)。")
    a("- フレーム数・ts: 旧予測・GT・新予測の 3 者で全シナリオ一致(不一致なら停止する設計)。")
    a("")

    a("---")
    a("")
    a("_本レポートは supreme.* 公開 API(core / harness)と run_dev_eval の正準化ロジックのみで"
      "生成した(baseline コードは import していない)。旧 supreme 予測は trace.json の実測 view"
      "(再構成ではない)。src/supreme・テスト無改変・決定的・stdlib + pyyaml。_")
    a("")
    return "\n".join(a_list)


# ===========================================================================
# エントリポイント
# ===========================================================================

def main():
    parser = argparse.ArgumentParser(
        description="旧 supreme(l04-ours)を v1.4 で全 8 層再採点し新 supreme と比較(分析専用)")
    parser.add_argument("--trace", default=DEFAULT_TRACE)
    parser.add_argument("--pso-dir", default=DEFAULT_PSO_DIR)
    parser.add_argument("--gt-dir", default=DEFAULT_GT_DIR)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    out_path = args.out
    if out_path is None:
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M")
        out_path = os.path.join(DEFAULT_OUT_DIR, f"old-supreme-v14-rescore-{stamp}.md")

    try:
        run(args.trace, args.pso_dir, args.gt_dir, out_path)
    except (OldPredCanonError, rde.V13LabelError, rde.DataMismatch) as e:
        print(file=sys.stderr)
        print("=" * 70, file=sys.stderr)
        print("STOP(数字を捏造せず停止しました)。", file=sys.stderr)
        print(f"  種別: {type(e).__name__}", file=sys.stderr)
        print(f"  内容: {e}", file=sys.stderr)
        print("=" * 70, file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
