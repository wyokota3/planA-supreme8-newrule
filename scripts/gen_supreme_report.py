"""新 supreme 研究レポート用 DATA 生成 — planA-baseline 完成形レポートと同形の DATA を実データで作る。

planA-baseline の研究レポート(research-20260610-planA-baseline.html)は、20 シナリオ × 8 層の
`[ts, gt, pred]` セル + env(品質/ttc/発話/nh)+ radar(音源の極座標軌跡)を埋め込んだ DATA を
JS が描画する構造。本スクリプトはその DATA を **新 supreme の実走結果**で作り直す:

  - cells.pred : core.run_supreme_scenarios(params=trained) の per-frame 8 層 view(=学習配備版)。
                 既定(params=None)列も併せて計算し、層別 acc を honest に比較するために出力する。
  - cells.gt   : ADR 0006 で v1.4 正準化した GT(run_dev_eval.gt_frame_to_v14_view を再利用)。
  - env/radar/name/desc : **入力 PSO は新旧で同一**なので baseline レポートの DATA から流用
                 (同一入力=レーダー/イベント帯は視覚的に一致して当然・捏造ではない)。

honest 規律(HANDOVER・run_dev_eval と同じ):
  - cells.pred は trained(in-sample・学習配備版)。**in-sample/CV であって封印 verdict ではない**。
  - 学習層(t3/scene)の honest な汎化推定は CV held-out(別途数値・本スクリプトは in-sample セルのみ生成)。
  - 2 回走行で view が完全一致することを確認(決定的)。

出力:
  - reports/_supreme_report_data.json : DATA(レポート HTML に注入する JSON)
  - 標準出力 : 層別 acc(既定 / 学習 in-sample)・新旧比較の sanity・弱層 top 混同(診断図用)

使い方:
    python scripts/gen_supreme_report.py
依存: supreme.*(core/harness)+ scripts/run_dev_eval.py の正準化ロジック + pyyaml。baseline コード不使用。
"""

from __future__ import annotations

import json
import os
import re
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_SRC_DIR = os.path.join(os.path.dirname(_SCRIPT_DIR), "src")
for p in (_SRC_DIR, _SCRIPT_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

from supreme import core, harness            # noqa: E402  supreme 公開 API のみ
import run_dev_eval as rde                   # noqa: E402  正準化ロジック再利用(baseline 不使用)

BASELINE_REPORT = (
    r"C:\work\L04-planA\baseline\planA-baseline\reports"
    r"\research-20260610-planA-baseline.html"
)
OUT_JSON = os.path.join(os.path.dirname(_SCRIPT_DIR), "reports", "_supreme_report_data.json")

LAYERS = [
    "risk_tier", "t1_state", "t2_mode", "t2_role", "t2_relation",
    "t3_hypothesis", "quality_regime", "scene_regime",
]


def _load_baseline_data():
    """baseline レポート HTML から埋め込み DATA を取り出す(env/radar/name/desc 流用元)。"""
    html = open(BASELINE_REPORT, encoding="utf-8").read()
    m = re.search(r"const DATA = (\{.*?\});", html, re.DOTALL)
    if not m:
        raise SystemExit("baseline レポートから DATA を抽出できなかった")
    data = json.loads(m.group(1))
    by_id = {s["id"]: s for s in data["scenarios"]}
    return data, by_id


def _acc(cells):
    if not cells:
        return None
    return sum(1 for c in cells if c[1] == c[2]) / len(cells)


def main():
    base_data, base_by_id = _load_baseline_data()

    pso_dir, gt_dir = rde.DEFAULT_PSO_DIR, rde.DEFAULT_GT_DIR
    dirs = rde._scenario_dirs(pso_dir, gt_dir)
    print(f"[1] シナリオ {len(dirs)} 件・PSO/GT 対応 OK")

    scenario_inputs = {}     # dir_name -> snaps
    scenario_gt = {}         # dir_name -> [gt_view_v14,...]
    scenario_ts = {}         # dir_name -> [ts,...]  (実 ts・env/radar と整合)
    for d in dirs:
        snaps = rde._load_pso(os.path.join(pso_dir, d, "pso_input.jsonl"))
        gt = rde._load_gt(os.path.join(gt_dir, d, "ground_truth.yaml"))
        timeline = gt.get("timeline", []) or []
        sid = str(gt.get("scenario_id", d))
        if len(snaps) != len(timeline):
            raise SystemExit(f"[{d}] frame 数不一致 pso={len(snaps)} gt={len(timeline)}")
        ts = []
        for snap, gtf in zip(snaps, timeline):
            if float(snap["ts"]) != float(gtf["ts"]):
                raise SystemExit(f"[{d}] ts 不一致")
            ts.append(float(gtf["ts"]))
        scenario_inputs[d] = snaps
        scenario_gt[d] = [
            rde.gt_frame_to_v14_view(gtf, scenario_id=sid, ts=gtf.get("ts"))
            for gtf in timeline
        ]
        scenario_ts[d] = ts

    # --- supreme 実走(既定 / 学習)・決定性検査 ---
    print("[2] core.fit_supreme(v021_core) で学習(in-sample・学習配備版)")
    trained = core.fit_supreme(scenario_inputs, scenario_gt)
    print(f"    learnable param 数 = {trained.learnable_param_count()}")

    def _run(params, label):
        a = core.run_supreme_scenarios(scenario_inputs, params=params)
        b = core.run_supreme_scenarios(scenario_inputs, params=params)
        if a != b:
            raise SystemExit(f"[{label}] 決定性検査失敗(2 回走行不一致)")
        return a

    views_default = _run(None, "default")
    views_trained = _run(trained, "trained")
    print("[3] 既定・学習とも 2 回走行で view 完全一致(決定的)")

    # --- DATA 構築(cells.pred = trained・env/radar は baseline 流用)---
    scenarios_out = []
    default_cells = {ly: [] for ly in LAYERS}   # 層別 acc(既定)集計用
    trained_cells = {ly: [] for ly in LAYERS}
    for d in dirs:
        gtv = scenario_gt[d]
        vt = views_trained[d]
        vd = views_default[d]
        ts = scenario_ts[d]
        if not (len(gtv) == len(vt) == len(vd) == len(ts)):
            raise SystemExit(f"[{d}] view/gt/ts 長さ不一致")
        for ly in LAYERS:
            if ly not in vt[0]:
                raise SystemExit(f"[{d}] supreme view に層 {ly} が無い: keys={list(vt[0])}")
        cells = {}
        for ly in LAYERS:
            row = []
            for i in range(len(ts)):
                g = gtv[i].get(ly)
                p = vt[i].get(ly)
                row.append([ts[i], g, p])
                # acc 集計(GT が None のフレームは NA=除外)
                if g is not None:
                    trained_cells[ly].append((g, p))
                    default_cells[ly].append((g, vd[i].get(ly)))
            cells[ly] = row

        base = base_by_id.get(d, {})
        scenarios_out.append({
            "id": d,
            "name": base.get("name", d),
            "desc": base.get("desc", ""),
            "frames": len(ts),
            "cells": cells,
            "env": base.get("env", []),
            "radar": base.get("radar", []),
        })

    data_out = {
        "layers": LAYERS,
        "catalog": base_data.get("catalog", "1.4.0"),
        "scenarios": scenarios_out,
    }
    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(data_out, f, ensure_ascii=False, separators=(",", ":"))
    print(f"[4] DATA 書き出し: {OUT_JSON}  ({os.path.getsize(OUT_JSON)} bytes)")

    # --- 層別 acc(既定 / 学習 in-sample)+ 弱層 top 混同 ---
    def _acc_pairs(pairs):
        if not pairs:
            return None
        return sum(1 for g, p in pairs if g == p) / len(pairs)

    print("\n[5] 層別 acc(GT=None は NA 除外・分母は GT 非 null フレーム)")
    print(f"    {'layer':16s} {'既定':>8s} {'学習(in-sample)':>16s}  n")
    for ly in LAYERS:
        ad = _acc_pairs(default_cells[ly])
        at = _acc_pairs(trained_cells[ly])
        print(f"    {ly:16s} {ad:8.4f} {at:16.4f}  {len(trained_cells[ly])}")
    overall_d = sum(_acc_pairs(default_cells[ly]) for ly in LAYERS) / 8
    overall_t = sum(_acc_pairs(trained_cells[ly]) for ly in LAYERS) / 8
    print(f"    {'overall(8層平均)':16s} {overall_d:8.4f} {overall_t:16.4f}")

    print("\n[6] 弱5層の top 混同(学習 in-sample・診断図用 GT→pred ×件数)")
    weak = ("t2_mode", "t2_relation", "t3_hypothesis", "scene_regime", "quality_regime")
    confusions = {}
    for ly in weak:
        bad = {}
        for g, p in trained_cells[ly]:
            if g != p:
                bad[(g, p)] = bad.get((g, p), 0) + 1
        top = sorted(bad.items(), key=lambda kv: -kv[1])[:5]
        confusions[ly] = [[f"{g} → {p}", n] for (g, p), n in top]
        print(f"    {ly}: " + ", ".join(f"{g}→{p}×{n}" for (g, p), n in top))

    # 診断用に混同も別ファイルへ(レポート診断節の根拠)
    with open(OUT_JSON.replace(".json", "_confusions.json"), "w", encoding="utf-8") as f:
        json.dump({"layer_acc_trained": {ly: _acc_pairs(trained_cells[ly]) for ly in LAYERS},
                   "layer_acc_default": {ly: _acc_pairs(default_cells[ly]) for ly in LAYERS},
                   "confusions": confusions}, f, ensure_ascii=False, indent=2)
    print("\n[done] DATA + confusions 生成完了")


if __name__ == "__main__":
    main()
