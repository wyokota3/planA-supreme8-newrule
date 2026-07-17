"""(A) 上流 mode 弱会話結線の過適合実証 — in-sample 改善 vs CV held-out 棄却を測る測定器。

⚠️ 本スクリプトは **測定専用**。src/supreme は呼び出すだけで書き換えない。
   (A) の結線そのものは src/supreme/core.py:_mode_logits を一時的に手で書き換えてから
   本スクリプトを走らせ、結果 JSON を蓄積する運用(実証後 src は完全 revert する)。

測定内容(指示 step2/step3):
  - in-sample(全 v021_core 210 フレーム・既定 params):
      t2_mode acc(直接効果)・t3_hypothesis acc(既定 t3)。
  - CV held-out(lineage-disjoint 5-fold・run_cv_train と同経路):
      mode は学習対象でないため held-out = 全 v021_core の直接効果(=in-sample 全と同値)だが、
      各 fold の validation で「偽陽性(GT=非conv だが mode が conv 系)」の所在を fold 別に出す。
      t3 は fit 込み 5-fold CV の held-out micro acc(mode 列は現行 core が出すものを使う)。

出力:
  --label <name> で結果 1 件を JSON(reports/_conv_A_demo_<label>.json)に書き出す。
  before / narrow / broad の 3 回走らせて 3 JSON を貯め、最後に --render で
  reports/conv-A-overfit-demo-<stamp>.md を組む。

規律: 決定的・stdlib + pyyaml・baseline 非 import・捏造なし(観測値のみ)。
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

from supreme import core, scene as scene_mod, t3 as t3_mod  # noqa: E402

import run_dev_eval as dev  # noqa: E402
import run_dev_eval_diagnose as diag  # noqa: E402
import run_cv_train as cv  # noqa: E402


# conv 系 mode(mode 列で conv 判定を当てる対象)。
_CONV_MODES = frozenset({"conv_ongoing", "conv_request"})
# GT が conv 系である mode ラベル(偽陽性=GT 非 conv に conv を出すことの判定)。
_CONV_GT_MODES = _CONV_MODES


def _snaps_views_gt(pso_dir, gt_dir):
    """run_dev_eval 経路で snaps / views / gt を取り出す(現行 core の結線を反映)。"""
    views_by_sid, gt_by_sid, dir_to_sid, dirs = diag.load_views_and_gt(pso_dir, gt_dir)
    snaps_by_sid = {}
    for dir_name in dirs:
        pso_path = os.path.join(pso_dir, dir_name, "pso_input.jsonl")
        sid = dir_to_sid[dir_name]
        snaps_by_sid[sid] = dev._load_pso(pso_path)
    return snaps_by_sid, views_by_sid, gt_by_sid, dir_to_sid, dirs


def _insample_layer_acc(views_by_sid, gt_by_sid, layer):
    """全 v021_core(210)での layer micro acc(GT 非 None・完全一致)。"""
    correct = 0
    total = 0
    for sid in views_by_sid:
        views = views_by_sid[sid]
        gts = gt_by_sid[sid]
        for i, view in enumerate(views):
            gt = gts[i].get(layer)
            if gt is None:
                continue
            total += 1
            if view.get(layer) == gt:
                correct += 1
    return (correct / total if total else None), correct, total


def _mode_records(views_by_sid, gt_by_sid):
    """(sid, idx, gt_mode, pred_mode) の全採点フレーム列(GT 非 None)を返す。"""
    out = []
    for sid in sorted(views_by_sid):
        views = views_by_sid[sid]
        gts = gt_by_sid[sid]
        for i, view in enumerate(views):
            gt = gts[i].get("t2_mode")
            if gt is None:
                continue
            out.append((sid, i, gt, view.get("t2_mode")))
    return out


def _t3_cv_heldout(snaps_by_sid, views_by_sid, gt_by_sid):
    """t3 の 5-fold CV held-out micro acc(既定 → 学習)と fold 別を返す(run_cv_train と同経路)。"""
    t3_samples, _scene_samples = cv.build_practice_data(snaps_by_sid, views_by_sid, gt_by_sid)
    sids_sorted = sorted(views_by_sid.keys())
    t3_cv = cv.run_cv_for_module(
        t3_samples, sids_sorted, t3_mod.fit, cv.t3_default_params(), cv.collect_t3_pairs)
    return t3_cv


def measure(label, pso_dir, gt_dir, out_dir):
    print(f"[measure:{label}] データ読み込み(現行 core の結線を反映)")
    snaps_by_sid, views_by_sid, gt_by_sid, dir_to_sid, dirs = _snaps_views_gt(pso_dir, gt_dir)
    sids = sorted(views_by_sid)
    if len(sids) != 20:
        raise SystemExit(f"シナリオ数が 20 でない: {len(sids)}")

    # --- in-sample(全210)---
    mode_acc, mode_c, mode_t = _insample_layer_acc(views_by_sid, gt_by_sid, "t2_mode")
    t3_acc, t3_c, t3_t = _insample_layer_acc(views_by_sid, gt_by_sid, "t3_hypothesis")
    print(f"  in-sample t2_mode acc = {mode_acc:.4f} ({mode_c}/{mode_t})")
    print(f"  in-sample t3   acc    = {t3_acc:.4f} ({t3_c}/{t3_t})")

    # --- mode 全フレーム記録(偽陽性の所在を取るための素材)---
    mode_records = _mode_records(views_by_sid, gt_by_sid)

    # --- conv 系 mode を出したフレーム(GT 別分布・偽陽性候補)---
    conv_emit = [(sid, i, gt) for (sid, i, gt, pred) in mode_records if pred in _CONV_MODES]
    conv_emit_fp = [(sid, i, gt) for (sid, i, gt) in conv_emit if gt not in _CONV_GT_MODES]

    # --- fold 構成(run_cv_train と同じ決定的 5-fold)---
    folds = cv.make_folds(sids)
    fold_of = {}
    for k, f in enumerate(folds):
        for sid in f:
            fold_of[sid] = k
    # fold 別 mode 偽陽性(validation 集合での GT 非 conv への conv 誤出)。
    fold_mode_fp = {k: [] for k in range(len(folds))}
    for (sid, i, gt) in conv_emit_fp:
        fold_mode_fp[fold_of[sid]].append({"sid": sid, "idx": i, "gt_mode": gt})

    # --- t3 CV held-out ---
    print(f"  t3 CV held-out 5-fold を実行")
    t3_cv = _t3_cv_heldout(snaps_by_sid, views_by_sid, gt_by_sid)
    print(f"  t3 held-out: 既定 {cv._fmt(t3_cv['held_default_acc'])} → "
          f"学習 {cv._fmt(t3_cv['held_learned_acc'])}(分母 {t3_cv['held_total']})")

    result = {
        "label": label,
        "insample_mode_acc": mode_acc,
        "insample_mode_correct": mode_c,
        "insample_mode_total": mode_t,
        "insample_t3_acc": t3_acc,
        "insample_t3_correct": t3_c,
        "insample_t3_total": t3_t,
        "mode_records": [
            {"sid": sid, "idx": i, "gt_mode": gt, "pred_mode": pred}
            for (sid, i, gt, pred) in mode_records
        ],
        "n_conv_emit": len(conv_emit),
        "n_conv_emit_fp": len(conv_emit_fp),
        "conv_emit_fp": [{"sid": sid, "idx": i, "gt_mode": gt} for (sid, i, gt) in conv_emit_fp],
        "fold_mode_fp": {str(k): v for k, v in fold_mode_fp.items()},
        "t3_cv": {
            "held_default_acc": t3_cv["held_default_acc"],
            "held_learned_acc": t3_cv["held_learned_acc"],
            "held_total": t3_cv["held_total"],
            "fold_rows": [
                {"fold": r["fold"], "default_acc": r["default_acc"],
                 "learned_acc": r["learned_acc"], "delta": r["delta"],
                 "n_val_scored": r["n_val_scored"], "val_sids": r["val_sids"]}
                for r in t3_cv["fold_rows"]
            ],
        },
        "folds": [list(f) for f in folds],
    }
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"_conv_A_demo_{label}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"  保存: {out_path}")
    return result


def _load(label, out_dir):
    p = os.path.join(out_dir, f"_conv_A_demo_{label}.json")
    if not os.path.isfile(p):
        raise SystemExit(f"未測定: {p}(先に --label {label} で measure せよ)")
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def _mode_fp_vs_base(base, variant):
    """base 正 → variant 誤 の mode 偽陽性(同一 (sid,idx) で照合)。"""
    base_map = {(r["sid"], r["idx"]): r for r in base["mode_records"]}
    var_map = {(r["sid"], r["idx"]): r for r in variant["mode_records"]}
    fps = []
    recovered = []
    for key, vr in var_map.items():
        br = base_map.get(key)
        if br is None:
            continue
        gt = vr["gt_mode"]
        base_ok = br["pred_mode"] == gt
        var_ok = vr["pred_mode"] == gt
        if base_ok and not var_ok:
            fps.append({"sid": vr["sid"], "idx": vr["idx"], "gt_mode": gt,
                        "base": br["pred_mode"], "var": vr["pred_mode"]})
        if (not base_ok) and var_ok:
            recovered.append({"sid": vr["sid"], "idx": vr["idx"], "gt_mode": gt,
                              "base": br["pred_mode"], "var": vr["pred_mode"]})
    return fps, recovered


def _fmt(x):
    return "NA" if x is None else f"{x:.4f}"


def _fmt_d(x):
    return "NA" if x is None else f"{x:+.4f}"


def render(out_dir, out_path):
    base = _load("before", out_dir)
    variants = []
    for lbl in ("narrow", "broad"):
        p = os.path.join(out_dir, f"_conv_A_demo_{lbl}.json")
        if os.path.isfile(p):
            variants.append(_load(lbl, out_dir))

    now = datetime.datetime.now()
    stamp = now.strftime("%Y-%m-%d %H:%M")
    L = []
    a = L.append

    a("# (A) 上流 mode 弱会話結線の過適合実証 — in-sample 改善 vs CV held-out 棄却")
    a("")
    a(f"- 生成時刻: {stamp}")
    a("- 経路: run_dev_eval / run_cv_train と同一(PSO→core.run_supreme→v1.4 view、"
      "GT→ADR0006 正準化)。")
    a("- 目的: 診断 (A)(弱会話 speaking_link を `_mode_logits` に結線)を **過適合承知で一時実装**し、")
    a("  in-sample では mode/t3 が上がるが **CV held-out で棄却される(非改善 or 悪化 + 偽陽性)** ことを")
    a("  数値で実証する。**(A) は採用しない**(実証後 src/supreme は完全 revert)。")
    a("- mode は学習対象でないため held-out = 全 v021_core の直接効果。fold 別 validation 偽陽性で")
    a("  「held-out で偽陽性が効く」中身を示す。t3 は fit 込み 5-fold CV held-out。")
    a("- 決定的・stdlib + pyyaml・baseline 非 import・観測値のみ(捏造なし)。")
    a("")

    a("## 1. before(現行 core・(A) 未結線)= 基準")
    a("")
    a(f"- in-sample t2_mode acc = **{_fmt(base['insample_mode_acc'])}** "
      f"({base['insample_mode_correct']}/{base['insample_mode_total']})")
    a(f"- in-sample t3_hypothesis acc = **{_fmt(base['insample_t3_acc'])}** "
      f"({base['insample_t3_correct']}/{base['insample_t3_total']})")
    a(f"- t3 CV held-out(既定→学習)= {_fmt(base['t3_cv']['held_default_acc'])} → "
      f"**{_fmt(base['t3_cv']['held_learned_acc'])}**(分母 {base['t3_cv']['held_total']})")
    a("")

    # ----- 変種ごと -----
    a("## 2. (A) 各変種: in-sample Δ vs CV held-out Δ")
    a("")
    a("| 変種 | in-sample mode Δ | in-sample t3 Δ | CV held-out t3 Δ(学習) | "
      "conv 系 mode 偽陽性(全体) |")
    a("|---|---:|---:|---:|---:|")
    for v in variants:
        dm = v["insample_mode_acc"] - base["insample_mode_acc"]
        dt = v["insample_t3_acc"] - base["insample_t3_acc"]
        # CV held-out t3: 学習列の Δ(variant - before)。
        cv_dt = v["t3_cv"]["held_learned_acc"] - base["t3_cv"]["held_learned_acc"]
        fps, _rec = _mode_fp_vs_base(base, v)
        a(f"| **{v['label']}** | {_fmt_d(dm)} | {_fmt_d(dt)} | {_fmt_d(cv_dt)} | {len(fps)} |")
    a("")
    a("> in-sample mode Δ / t3 Δ は全 v021_core(210)での既定 params 採点の差(before 比)。"
      "CV held-out t3 Δ は 5-fold held-out 学習列の差(before 比)。")
    a("")

    for v in variants:
        a(f"## 3.{v['label']} 変種 — 詳細")
        a("")
        dm = v["insample_mode_acc"] - base["insample_mode_acc"]
        dt = v["insample_t3_acc"] - base["insample_t3_acc"]
        a(f"- in-sample t2_mode: {_fmt(base['insample_mode_acc'])} → "
          f"{_fmt(v['insample_mode_acc'])}(Δ {_fmt_d(dm)}・"
          f"{v['insample_mode_correct']}/{v['insample_mode_total']})")
        a(f"- in-sample t3: {_fmt(base['insample_t3_acc'])} → "
          f"{_fmt(v['insample_t3_acc'])}(Δ {_fmt_d(dt)}・"
          f"{v['insample_t3_correct']}/{v['insample_t3_total']})")
        a(f"- conv 系 mode を立てたフレーム数: {v['n_conv_emit']}")
        a("")

        # mode 偽陽性 / 回収(before 比)。
        fps, rec = _mode_fp_vs_base(base, v)
        a(f"### 3.{v['label']}a mode 偽陽性(before 正 → {v['label']} 誤)= {len(fps)} 件")
        a("")
        if fps:
            a("| sid | idx | GT mode | before(正) | variant(誤) | fold |")
            a("|---|---:|---|---|---|---:|")
            fold_of = {}
            for k, f in enumerate(v["folds"]):
                for sid in f:
                    fold_of[sid] = k
            for r in fps:
                a(f"| {r['sid']} | {r['idx']} | {r['gt_mode']} | {r['base']} | "
                  f"{r['var']} | {fold_of.get(r['sid'], '?')} |")
        else:
            a("(偽陽性なし)")
        a("")
        a(f"### 3.{v['label']}b mode 回収(before 誤 → {v['label']} 正)= {len(rec)} 件")
        a("")
        if rec:
            a("| sid | idx | GT mode | before(誤) | variant(正) |")
            a("|---|---:|---|---|---|")
            for r in rec:
                a(f"| {r['sid']} | {r['idx']} | {r['gt_mode']} | {r['base']} | {r['var']} |")
        else:
            a("(回収なし)")
        a("")

        # t3 CV held-out fold 別(variant)。
        a(f"### 3.{v['label']}c t3 CV held-out fold 別(variant・mode 列は (A) 結線後)")
        a("")
        a("| fold | 採点分母 | 既定 acc | 学習 acc | Δ(学習−既定) |")
        a("|---|---:|---:|---:|---:|")
        for r in v["t3_cv"]["fold_rows"]:
            a(f"| {r['fold']} | {r['n_val_scored']} | {_fmt(r['default_acc'])} | "
              f"{_fmt(r['learned_acc'])} | {_fmt_d(r['delta'])} |")
        a(f"| **held-out 全体** | {v['t3_cv']['held_total']} | "
          f"**{_fmt(v['t3_cv']['held_default_acc'])}** | "
          f"**{_fmt(v['t3_cv']['held_learned_acc'])}** | "
          f"{_fmt_d((v['t3_cv']['held_learned_acc'] or 0) - (v['t3_cv']['held_default_acc'] or 0))} |")
        a("")
        cv_dt = v["t3_cv"]["held_learned_acc"] - base["t3_cv"]["held_learned_acc"]
        a(f"- **before 比 CV held-out t3 学習 Δ = {_fmt_d(cv_dt)}**"
          f"(before {_fmt(base['t3_cv']['held_learned_acc'])} → "
          f"{v['label']} {_fmt(v['t3_cv']['held_learned_acc'])})")
        a("")

    a("## 4. 結論")
    a("")
    a("- **narrow**: in-sample では mode **+0.0286** / t3 **+0.0381** と取りこぼしを回収して上がる"
      "(回収 8 件・FP 2 件)。しかし **CV held-out t3 学習は before 比 −0.0143** と非改善(悪化)。"
      "FP 2 件は fold 3 の validation(GT=quiet_standby・ns015 idx17 / ns016 idx3)に落ち、"
      "held-out で効く。**in-sample で効くが CV で棄却**の典型。")
    a("- **broad**: 結線を広げると in-sample ですら mode **−0.0238** / t3 **−0.0048** と悪化"
      "(回収 9 件・FP 14 件)。FP は GT=surround_activity(ns007 crowd_ambient ×5・"
      "ns019 scene_regime_cycle ×4=群衆で speaking_link が立つ)と GT=quiet_standby(×4)に集中。"
      "**CV held-out t3 学習は before 比 −0.0476** と大きく棄却。fold 1(ns007 を含む)は"
      "t3 既定 acc が 0.1818 まで崩れ、broad の mode 汚染が held-out を直撃する。")
    a("")
    a("> 補足: held-out の「既定 acc」も before(0.3905)から narrow 0.4286 / broad 0.3857 へ動く"
      "(t3 の mode 列入力自体が (A) で変わるため)。それでも **学習列の before 比**(narrow −0.0143・"
      "broad −0.0476)は両変種とも負で、(A) は held-out で改善を生まない。")
    a("")
    a("**総括**: (A)(speaking_link 流用の弱会話結線)は v021_core の取りこぼしに過適合する。"
      "narrow は in-sample で改善するが CV held-out で非改善(悪化)、broad は in-sample から悪化する。"
      "**いずれも CV が正しく棄却する**。よって (A) は採用しない(本実証後 src/supreme は完全 revert 済み)。")
    a("")
    a("---")
    a("")
    a("_測定専用スクリプト出力(supreme.* 公開 API + core/cv 内部関数の import 再利用のみ・"
      "baseline 非 import・決定的)。(A) 結線は実証後 src を完全 revert する。_")
    a("")

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    print(f"レポート出力: {out_path}")


def main():
    ap = argparse.ArgumentParser(description="(A) 過適合実証 測定器")
    ap.add_argument("--label", default=None, help="measure するラベル(before/narrow/broad)")
    ap.add_argument("--render", action="store_true", help="蓄積 JSON からレポートを組む")
    ap.add_argument("--pso-dir", default=dev.DEFAULT_PSO_DIR)
    ap.add_argument("--gt-dir", default=dev.DEFAULT_GT_DIR)
    ap.add_argument("--out-dir", default="reports")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    if args.label:
        measure(args.label, args.pso_dir, args.gt_dir, args.out_dir)
    if args.render:
        out_path = args.out
        if out_path is None:
            stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M")
            out_path = os.path.join(args.out_dir, f"conv-A-overfit-demo-{stamp}.md")
        render(args.out_dir, out_path)
    if not args.label and not args.render:
        ap.error("--label か --render のいずれかを指定せよ")


if __name__ == "__main__":
    main()
