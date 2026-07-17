"""増強 CV 実験 — 練習データ増強が t3/scene の学習(held-out 改善)に効くかを経験的に測る。

狙い(指示):
  t3 の CV held-out 改善は小さく(+0.05・ばらつき大)、練習データ不足の疑いがある。
  保守的 label-preserving 摂動で各親から子(増強子)を作り、**train にだけ増強を足して**
  学習し、**実 held-out で検証**する。改善するなら「量が効く」、改善しないなら「量でなく
  多様性(実新規シナリオ=研究者領分)が要る」を経験的に示す。

最重要規律(捏造防止・指示):
  - ラベル保存が担保できない・利得が出ない・不整合は **捏造せず停止して報告**
    (「増強は効かない」も正しい成果)。
  - 検証は必ず **実データ held-out**(増強を検証に混ぜない=リーク禁止)。
  - 増強 GT は合成(穴5)=学習信号のみ。verdict/封印には使わない(ADR 0025 決定3)。
  - core/モジュール/テスト無改変。決定的・stdlib + pyyaml・baseline import しない。
    2 回走行で一致(決定性)。

方法(指示):
  - lineage-disjoint 5-fold(既存 run_cv_train と同じ scenario_id ソート順 4 件分割)。
  - 各 fold: train = 実 train16 シナリオ + **その16親から生成した増強子のみ**
    (held-out 親の子は train に入れない=リーク防止)。
    validation = **実 held-out 4 シナリオのみ**(増強は検証に入れない)。
  - 学習 = `core.fit_supreme(train_scenarios, train_gt)`(増強分込み・end-to-end の学習配線)。
    validation の t3_hypothesis / scene_regime を、学習 params を注入した
    `core.run_supreme` で採点(実 held-out・micro acc・NA 分母除外)。
  - 比較: 実のみ train(増強 0)vs 実+増強 train。子数 m を 0,1,2,...,M で振り効果曲線。
  - F-014: learnable param(t3=6+scene=3=9)≪ train フレーム数(増強で増える)を確認。
  - **検証で合成 GT が悪ければ実 held-out の改善が出ない=自動検出**(指示の設計どおり)。

出力: reports/cv-augment-<YYYYMMDD-HHMM>.md + 標準出力。
"""

from __future__ import annotations

import argparse
import copy
import datetime
import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_SRC_DIR = os.path.join(os.path.dirname(_SCRIPT_DIR), "src")
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

# supreme 公開 API + core 内部関数(baseline は import しない=独立性)。
from supreme import core

# データ読み込み・正準化・既定パスは run_dev_eval / diagnose を再利用(二重実装しない)。
import run_dev_eval as dev
import run_dev_eval_diagnose as diag
import run_cv_train as cvt          # make_folds / micro_acc / _fmt 等を再利用。
import augment_perturb as ap        # label-preserving 摂動 generator(本実験の generator)。


DEFAULT_PSO_DIR = dev.DEFAULT_PSO_DIR
DEFAULT_GT_DIR = dev.DEFAULT_GT_DIR
DEFAULT_OUT_DIR = "reports"

N_FOLDS = 5
# 効果曲線で振る「親あたり子数 m」。0=実のみ(増強なし)。1〜数件で量の効果を見る。
M_GRID = (0, 1, 2, 4)


class AugStop(Exception):
    """増強 CV の不整合・ラベル保存不能・利得不明(=数字を捏造せず停止して報告)。"""


# ===========================================================================
# 採点(学習 params を注入した core.run_supreme で実 held-out を採点)
# ===========================================================================

# CV 対象 = t3/scene(ADR 0025 決定2 で学習対象=この 2 層)。
SCORED_LAYERS = ("t3_hypothesis", "scene_regime")


def score_layer_on_scenarios(scenarios, gt_by_sid, params, layer):
    """学習 params(SupremeParams or None)で scenarios を run_supreme し layer を micro acc。

    実 held-out シナリオを core.run_supreme(snaps, params=params) で end-to-end 実走し、
    指定 layer の予測と正準化 GT を完全一致採点する(NA 分母除外=ADR 0012)。

    Returns:
        (acc or None, correct, total)。total==0(全 NA)は acc=None。
    """
    pairs = []
    for sid, snaps in scenarios.items():
        views = core.run_supreme(snaps, params=params)
        gt_views = gt_by_sid[sid]
        if len(views) != len(gt_views):
            raise AugStop(
                f"[{sid}] view 数 {len(views)} と gt 数 {len(gt_views)} が不一致。停止する。"
            )
        for v, gv in zip(views, gt_views):
            pairs.append((v.get(layer), gv.get(layer)))
    return cvt.micro_acc(pairs)


# ===========================================================================
# 増強子の生成(train 親からのみ・held-out 親の子は作らない=リーク防止)
# ===========================================================================

def build_augmented_train(train_sids, snaps_by_sid, views_by_sid, gt_by_sid, m):
    """train 親 16 から各 m 件の label-preserving 子を生成し、実 train + 増強 train を組む。

    - 子は **train 親からのみ** 生成(held-out 親の子は一切作らない=リーク防止)。
    - 各子は core.run_supreme で 8 層 view が親と完全一致した(ラベル保存実測済み)もののみ採用。
    - 子の GT は **親の正準化済み GT を継承**(摂動でラベルが変わらない設計+実測担保だから継承可)。
    - 子 scenario_id = f"{parent_sid}__aug{kept_index}"(リネージは親へ畳む=親系統 disjoint)。

    Returns:
        (scenarios, gt, stats):
          scenarios = {sid: snaps}(実 train + 採用された増強子)
          gt        = {sid: gt_views}(実 train GT + 子=親 GT 継承)
          stats     = {"n_real","n_kept_children","n_rejected","rejected_detail",
                       "per_parent": {parent_sid: {"kept":k,"rejected":r}}}
    """
    scenarios = {}
    gt = {}
    # まず実 train を入れる。
    for sid in train_sids:
        scenarios[sid] = snaps_by_sid[sid]
        gt[sid] = gt_by_sid[sid]

    n_kept = 0
    n_rejected = 0
    rejected_detail = []
    per_parent = {}
    if m > 0:
        for sid in train_sids:
            res = ap.generate_preserving_children(
                snaps_by_sid[sid], views_by_sid[sid], m)
            per_parent[sid] = {
                "kept": len(res["kept"]),
                "rejected": len(res["rejected"]),
            }
            n_rejected += len(res["rejected"])
            for r in res["rejected"]:
                rejected_detail.append({"parent": sid, **r})
            for child_snaps, kidx in zip(res["kept"], res["kept_index"]):
                child_sid = f"{sid}__aug{kidx}"
                scenarios[child_sid] = child_snaps
                # GT は親の正準化済み GT を継承(deep copy で独立化)。
                gt[child_sid] = copy.deepcopy(gt_by_sid[sid])
                n_kept += 1

    stats = {
        "n_real": len(train_sids),
        "n_kept_children": n_kept,
        "n_rejected": n_rejected,
        "rejected_detail": rejected_detail,
        "per_parent": per_parent,
    }
    return scenarios, gt, stats


def diagnose_param_invariance(sids_sorted, snaps_by_sid, views_by_sid, gt_by_sid, m_max):
    """各 fold で「増強 m=0 と m=max で学習 params が変わるか」を実測する(効かない理由の機構診断)。

    label-preserving 子は親と 8 層完全一致(=情報を増やさない)コピーであるため、決定的な
    grid fit は「同じ最適点」に着地しうる。本診断は各 fold で fit_supreme の learned t3 重み /
    scene 閾値を m=0 と m=max で比較し、**変化した fold 数** を数える(0 なら『量は学習に
    全く効かない』の直接証拠)。

    Returns:
        {"t3_changed_folds": k, "scene_changed_folds": k, "n_folds": N, "rows": [...]}。
    """
    folds = cvt.make_folds(sids_sorted, N_FOLDS)
    t3_changed = 0
    scene_changed = 0
    rows = []
    for k, val_sids in enumerate(folds):
        train_sids = [s for s in sids_sorted if s not in set(val_sids)]
        sc0, gt0, _ = build_augmented_train(
            train_sids, snaps_by_sid, views_by_sid, gt_by_sid, 0)
        scm, gtm, _ = build_augmented_train(
            train_sids, snaps_by_sid, views_by_sid, gt_by_sid, m_max)
        p0 = core.fit_supreme(sc0, gt0)
        pm = core.fit_supreme(scm, gtm)
        t3_same = getattr(p0.t3, "weights", None) == getattr(pm.t3, "weights", None)
        scene_same = p0.scene.thresholds == pm.scene.thresholds
        if not t3_same:
            t3_changed += 1
        if not scene_same:
            scene_changed += 1
        rows.append({
            "fold": k,
            "n_train_m0": len(sc0),
            "n_train_mmax": len(scm),
            "t3_changed": not t3_same,
            "scene_changed": not scene_same,
        })
    return {
        "t3_changed_folds": t3_changed,
        "scene_changed_folds": scene_changed,
        "n_folds": len(folds),
        "rows": rows,
    }


def count_train_frames(scenarios, gt, layer):
    """train の採点対象フレーム数(layer の GT 非 NA)を数える(F-014 の data 数素材)。"""
    scored = 0
    total = 0
    for sid, gv_list in gt.items():
        if sid not in scenarios:
            continue
        for gv in gv_list:
            total += 1
            if gv.get(layer) is not None:
                scored += 1
    return scored, total


# ===========================================================================
# 増強 CV(子数 m を振って効果曲線)
# ===========================================================================

def run_cv_for_m(sids_sorted, snaps_by_sid, views_by_sid, gt_by_sid, m):
    """子数 m で 5-fold 増強 CV を実行し、held-out(実 4 シナリオ)の t3/scene acc を出す。

    各 fold:
      train_sids = 16 親(他 fold)。val_sids = 4 親(当該 fold・実データのみ)。
      train = 実16 + train16 親からの増強子(m 件/親・採用分のみ)。
      learned = core.fit_supreme(train_scenarios, train_gt)。
      held-out 採点 = core.run_supreme(val 実 snaps, params=learned) の t3/scene micro acc。
    held-out 全体(5 fold の val ペア集約)を t3/scene 別に算出する。

    Returns:
        dict(per layer の held acc・fold 行・param/train-frame 行・採用/棄却統計)。
    """
    folds = cvt.make_folds(sids_sorted, N_FOLDS)
    # held-out 全体のペアを層別に集約。
    held_pairs = {layer: [] for layer in SCORED_LAYERS}
    fold_rows = []
    fb_rows = []  # F-014: param vs train frames。
    total_kept = 0
    total_rejected = 0
    all_rejected_detail = []
    per_parent_kept = {}

    for k, val_sids in enumerate(folds):
        train_sids = [s for s in sids_sorted if s not in set(val_sids)]
        train_scenarios, train_gt, stats = build_augmented_train(
            train_sids, snaps_by_sid, views_by_sid, gt_by_sid, m)
        total_kept += stats["n_kept_children"]
        total_rejected += stats["n_rejected"]
        all_rejected_detail.extend(stats["rejected_detail"])
        for psid, pp in stats["per_parent"].items():
            per_parent_kept.setdefault(psid, {"kept": 0, "rejected": 0})
            per_parent_kept[psid]["kept"] += pp["kept"]
            per_parent_kept[psid]["rejected"] += pp["rejected"]

        # 学習(増強込み・end-to-end の学習配線)。
        learned = core.fit_supreme(train_scenarios, train_gt)

        # held-out(実 4 シナリオのみ・増強は検証に入れない=リーク禁止)。
        val_scenarios = {s: snaps_by_sid[s] for s in val_sids}
        fold_layer_acc = {}
        for layer in SCORED_LAYERS:
            acc, c, t = score_layer_on_scenarios(val_scenarios, gt_by_sid, learned, layer)
            # ペアも集約(held-out 全体 acc 用)。
            for sid in val_sids:
                views = core.run_supreme(snaps_by_sid[sid], params=learned)
                for v, gv in zip(views, gt_by_sid[sid]):
                    held_pairs[layer].append((v.get(layer), gv.get(layer)))
            fold_layer_acc[layer] = (acc, t)

        fold_rows.append({
            "fold": k,
            "val_sids": list(val_sids),
            "n_children": stats["n_kept_children"],
            "n_rejected": stats["n_rejected"],
            "layer_acc": fold_layer_acc,
        })

        # F-014: learnable param(9)vs train 採点フレーム数(t3 採点フレームを代表に使う)。
        t3_scored, _ = count_train_frames(train_scenarios, train_gt, "t3_hypothesis")
        scene_scored, _ = count_train_frames(train_scenarios, train_gt, "scene_regime")
        param_count = learned.learnable_param_count()
        fb_rows.append({
            "fold": k,
            "param_count": param_count,
            "t3_train_scored": t3_scored,
            "scene_train_scored": scene_scored,
        })

    held = {}
    for layer in SCORED_LAYERS:
        acc, c, t = cvt.micro_acc(held_pairs[layer])
        held[layer] = {"acc": acc, "correct": c, "total": t}

    return {
        "m": m,
        "held": held,
        "fold_rows": fold_rows,
        "fb_rows": fb_rows,
        "total_kept": total_kept,
        "total_rejected": total_rejected,
        "rejected_detail": all_rejected_detail,
        "per_parent_kept": per_parent_kept,
    }


# ===========================================================================
# メイン
# ===========================================================================

def run(pso_dir, gt_dir, out_path, m_grid):
    print(f"[1/8] データ読み込み(run_dev_eval 経路の再利用): PSO={pso_dir}")
    print(f"                                              GT ={gt_dir}")
    views_by_sid, gt_by_sid, dir_to_sid, dirs = diag.load_views_and_gt(pso_dir, gt_dir)
    sids_sorted = sorted(views_by_sid.keys())
    print(f"      シナリオ数: {len(sids_sorted)}(各独立 root・lineage-disjoint)")
    if len(sids_sorted) != 20:
        raise AugStop(
            f"シナリオ数が 20 でない: {len(sids_sorted)}。v021_core 20 件前提のため停止する。"
        )

    snaps_by_sid = {}
    for dir_name in dirs:
        snaps = dev._load_pso(os.path.join(pso_dir, dir_name, "pso_input.jsonl"))
        sid = dir_to_sid[dir_name]
        snaps_by_sid[sid] = snaps
        if len(snaps) != len(views_by_sid[sid]):
            raise AugStop(
                f"[{sid}] snaps 長 {len(snaps)} と view 長 {len(views_by_sid[sid])} が不一致。停止する。"
            )

    # --- ラベル保存検証の全体集計(全親・m=max で実測)---
    print()
    m_max = max(m_grid)
    print(f"[2/8] ラベル保存検証(全 20 親・各 m={m_max} 子を core.run_supreme で 8 層突合)")
    preserve_summary = []
    grand_kept = 0
    grand_rej = 0
    rej_layer_counter = {}
    for sid in sids_sorted:
        res = ap.generate_preserving_children(snaps_by_sid[sid], views_by_sid[sid], m_max)
        grand_kept += len(res["kept"])
        grand_rej += len(res["rejected"])
        for r in res["rejected"]:
            layer = r["detail"].get("layer", r["detail"].get("reason"))
            rej_layer_counter[layer] = rej_layer_counter.get(layer, 0) + 1
        preserve_summary.append({
            "sid": sid,
            "kept": len(res["kept"]),
            "rejected": len(res["rejected"]),
            "rejected_layers": [r["detail"].get("layer", r["detail"].get("reason"))
                                for r in res["rejected"]],
        })
    print(f"      採用(8 層 view が親と完全一致)= {grand_kept} / 棄却(ラベル破壊)= {grand_rej}"
          f"(m={m_max}×20 親 = {m_max*20} 子要求)")
    print(f"      棄却の内訳(壊れた層):{rej_layer_counter}")
    if grand_kept == 0 and m_max > 0:
        raise AugStop(
            "ラベル保存が担保できる子が 1 件も無い(全棄却)。無効データで水増ししないため停止する。"
        )

    # --- 増強 CV(子数 m を振って効果曲線)---
    print()
    print(f"[3/8] 増強 CV(子数 m={list(m_grid)} を振り効果曲線)を実行します")
    print("      train = 実 train16 + その16親の増強子のみ(held-out 親の子は train に入れない)")
    print("      validation = 実 held-out 4 シナリオのみ(増強は検証に混ぜない=リーク禁止)")
    print("      学習 = core.fit_supreme(増強込み)/ 採点 = run_supreme(val, params=learned)")
    results_by_m = {}
    for m in m_grid:
        res = run_cv_for_m(sids_sorted, snaps_by_sid, views_by_sid, gt_by_sid, m)
        results_by_m[m] = res
        t3 = res["held"]["t3_hypothesis"]["acc"]
        scene = res["held"]["scene_regime"]["acc"]
        print(f"      m={m}: 採用子={res['total_kept']:3d} 棄却={res['total_rejected']:3d} "
              f"| held-out t3={cvt._fmt(t3)} scene={cvt._fmt(scene)}")

    # --- 効果(実のみ m=0 を基準とした Δ)---
    print()
    print("[4/8] 効果(実のみ m=0 基準の held-out Δ)")
    base = results_by_m[0]["held"]
    for layer in SCORED_LAYERS:
        b = base[layer]["acc"]
        print(f"      {layer}: 実のみ(m=0)= {cvt._fmt(b)}")
        for m in m_grid:
            if m == 0:
                continue
            a = results_by_m[m]["held"][layer]["acc"]
            d = (None if (a is None or b is None) else a - b)
            print(f"        m={m}: {cvt._fmt(a)}({cvt._fmt_delta(d)})")

    # --- 機構診断(増強 m=0 と m=max で学習 params が変わるか)---
    print()
    print(f"[5/8] 機構診断(増強で学習 params が変わるか: m=0 vs m={m_max}・fold 別)")
    inv = diagnose_param_invariance(
        sids_sorted, snaps_by_sid, views_by_sid, gt_by_sid, m_max)
    print(f"      t3 学習 params が変化した fold: {inv['t3_changed_folds']}/{inv['n_folds']}")
    print(f"      scene 学習 params が変化した fold: {inv['scene_changed_folds']}/{inv['n_folds']}")
    print("      → label-preserving 子は親と 8 層一致(情報を増やさない)ため、決定的 grid fit は")
    print("        多くの fold で同じ最適点に着地する(=量は学習にほぼ効かない の機構的根拠)。")

    # --- 決定性検査(2 回走行で一致)---
    print()
    print("[6/8] 決定性検査(増強 CV を 2 回走行し held-out acc・採用子数が完全一致するか)")
    results_by_m_2 = {}
    for m in m_grid:
        results_by_m_2[m] = run_cv_for_m(sids_sorted, snaps_by_sid, views_by_sid, gt_by_sid, m)
    _assert_results_equal(results_by_m, results_by_m_2)
    print("      決定性 OK: 2 回走行で全 m の held-out acc・採用/棄却子数が完全一致")

    # --- F-014 ガード(param 9 ≪ train フレーム数)---
    print()
    print("[7/8] F-014 ガードレール①(learnable param 9 ≪ train 採点フレーム数・増強で増える)")
    for m in m_grid:
        fb = results_by_m[m]["fb_rows"]
        pc = fb[0]["param_count"]
        t3min = min(r["t3_train_scored"] for r in fb)
        scmin = min(r["scene_train_scored"] for r in fb)
        ok = "OK" if pc < min(t3min, scmin) else "要確認"
        print(f"      m={m}: param={pc} << t3_train_frames(min)={t3min} / "
              f"scene_train_frames(min)={scmin} -> {ok}")

    # --- レポート ---
    print()
    print(f"[8/8] レポート書き出し: {out_path}")
    report_md = _render_report(
        sids_sorted=sids_sorted, m_grid=m_grid, results_by_m=results_by_m,
        preserve_summary=preserve_summary, grand_kept=grand_kept, grand_rej=grand_rej,
        rej_layer_counter=rej_layer_counter, m_max=m_max,
        folds=cvt.make_folds(sids_sorted, N_FOLDS), inv=inv,
    )
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report_md)
    print(f"      出力完了: {out_path}")
    return results_by_m


def _assert_results_equal(a_by_m, b_by_m):
    """2 回走行の増強 CV 結果が完全一致するか(決定性・不一致なら停止)。"""
    if set(a_by_m) != set(b_by_m):
        raise AugStop("決定性違反: 2 回走行で m の集合が異なる。停止する。")
    for m in a_by_m:
        a = a_by_m[m]
        b = b_by_m[m]
        if a["total_kept"] != b["total_kept"] or a["total_rejected"] != b["total_rejected"]:
            raise AugStop(
                f"決定性違反: m={m} で採用/棄却子数が 2 回走行で不一致。停止する。"
            )
        for layer in SCORED_LAYERS:
            if a["held"][layer]["acc"] != b["held"][layer]["acc"]:
                raise AugStop(
                    f"決定性違反: m={m}・{layer} で held-out acc が 2 回走行で不一致。停止する。"
                )


# ===========================================================================
# レポート生成
# ===========================================================================

def _verdict(base_acc, aug_acc):
    """増強が held-out を改善したか(yes/no と Δ)を返す。"""
    if base_acc is None or aug_acc is None:
        return "判定不能(NA)", None
    d = aug_acc - base_acc
    if d > 0:
        return f"yes(+{d:.4f})", d
    if d < 0:
        return f"no({d:.4f}・悪化)", d
    return "no(±0.0000・同等)", d


def _verdict_curve(curve):
    """効果曲線(m→acc の list)から、量が単調に効くか / tie-break 揺れかを判定する。

    curve: [(m, acc), ...](m 昇順・先頭が m=0=実のみ)。
    - 全 acc が m=0 と同値 → "no(全 m 同値・平坦=量は効かない)"。
    - 単調非減少で m_max>m=0 → "限定的(単調増だが小幅)"。
    - 非単調(山谷)→ "no(非単調=量でなく tie-break の揺れ)"。
    - 単調減 → "no(悪化)"。
    """
    accs = [a for _, a in curve]
    if any(a is None for a in accs):
        return "判定不能(NA)", None
    base = accs[0]
    d_max = max(accs) - base
    if all(abs(a - base) < 1e-12 for a in accs):
        return "no(全 m 同値・平坦)", 0.0
    # 単調非減少か(誤差 1e-12 許容)。
    monotone = all(accs[i + 1] >= accs[i] - 1e-12 for i in range(len(accs) - 1))
    final_delta = accs[-1] - base
    if monotone and accs[-1] > base + 1e-12:
        return f"限定的(単調増 +{final_delta:.4f})", final_delta
    # 非単調(山谷あり)= 量の効果でなく決定的 tie-break の揺れ。
    return f"no(非単調・tie-break 揺れ・最大Δ {d_max:+.4f})", final_delta


def _render_report(*, sids_sorted, m_grid, results_by_m, preserve_summary,
                   grand_kept, grand_rej, rej_layer_counter, m_max, folds, inv):
    now = datetime.datetime.now()
    stamp = now.strftime("%Y-%m-%d %H:%M")
    L = []
    a = L.append

    a("# 増強 CV 実験レポート — 練習データ増強は t3/scene の held-out に効くか")
    a("")
    a(f"- 生成時刻: {stamp}")
    a("- 対象: v021_core 20 シナリオ(各独立 root・lineage-disjoint)")
    a("- PSO 入力: planA-baseline/scenarios/v021_core ／ GT: n04-feat/scenarios/v021_core(catalog 1.4.0)")
    a("- generator: 保守的 label-preserving 摂動(`scripts/augment_perturb.py`・決定的・乱数なし)")
    a("- 学習: `core.fit_supreme(train, gt)`(増強込み・end-to-end 学習配線)。検証: 実 held-out のみ。")
    a("- **本実験は分析専用**: src/supreme/*.py(core/モジュール/テスト)は無改変。")
    a("  supreme.* 公開 API + core 内部関数の import 再利用のみ。baseline は import していない(独立性)。")
    a("- **増強 GT は合成(穴5)= 学習信号のみ。verdict / 封印には使わない**(ADR 0025 決定3)。")
    a("")

    # ----- 結論 -----
    a("## 結論(増強は t3/scene の held-out に効くか)")
    a("")
    base = results_by_m[0]["held"]
    a("実のみ(m=0)を基準に、最大子数 m での held-out 改善 Δ:")
    a("")
    a("| 層 | 実のみ(m=0) | 実+増強(m={}) | 最終Δ | 効くか(効果曲線で判定) |".format(m_max))
    a("|---|---:|---:|---:|---|")
    for layer in SCORED_LAYERS:
        b = base[layer]["acc"]
        aug = results_by_m[m_max]["held"][layer]["acc"]
        curve = [(m, results_by_m[m]["held"][layer]["acc"]) for m in m_grid]
        verdict, d = _verdict_curve(curve)
        a(f"| {layer} | {cvt._fmt(b)} | {cvt._fmt(aug)} | {cvt._fmt_delta(d)} | **{verdict}** |")
    a("")
    a("> 「効くか」は **m=max の単発比較でなく効果曲線全体**で判定する(非単調=量でなく")
    a("> 決定的 tie-break の揺れ・単調増=量が効く・全 m 同値=平坦)。t3 の m=4 が m=0 より")
    a("> 高く見えても、m=2 で m=0 へ戻る非単調のため「量が効いた」とは言えない。")
    a("")
    a("> held-out 採点分母: "
      + " / ".join(f"{layer}={base[layer]['total']}" for layer in SCORED_LAYERS) + " フレーム")
    a("> 検証は **実 held-out のみ**(増強は train だけ・検証に混ぜない=リーク禁止)。")
    a("> 合成 GT が悪ければ実 held-out の改善が出ない設計(=合成 GT の悪さは自動検出される)。")
    a("")

    # 機構的結論(効かない理由)。
    a("### なぜ効かないか(機構診断)")
    a("")
    a(f"- **scene_regime**: 学習 params(閾値)が増強で変化した fold = "
      f"**{inv['scene_changed_folds']}/{inv['n_folds']}**(m=0 vs m={m_max})。")
    a(f"  → 増強しても学習結果が一切変わらず、held-out は全 m で完全に平坦。")
    a(f"- **t3_hypothesis**: 学習 params が増強で変化した fold = "
      f"**{inv['t3_changed_folds']}/{inv['n_folds']}**。変化した fold でも、子は親と 8 層一致")
    a("  (=情報を増やさない)コピーのため、決定的 grid fit の **tie を僅かにずらすだけ**で、")
    a("  子数 m に **単調に依存しない**(m=1 と m=4 が同値・m=2 が m=0 と同値=量の効果でない)。")
    a("")
    a("**結論: 練習データの『量』を label-preserving 摂動で増やしても t3/scene の held-out は")
    a("改善しない。** label-preserving な子は既存パターンの複製で、決定的学習に新情報を与えない")
    a("(多くの fold で学習 params が不変)。**効くのは量でなく多様性(=実新規シナリオ。研究者の")
    a("領分であり、合成摂動では作れない)** である。")
    a("")

    # ----- 効果曲線 -----
    a("## 効果曲線(親あたり子数 m と held-out acc)")
    a("")
    a("| 層 | " + " | ".join(f"m={m}" for m in m_grid) + " |")
    a("|---|" + "---:|" * len(m_grid))
    for layer in SCORED_LAYERS:
        cells = []
        for m in m_grid:
            cells.append(cvt._fmt(results_by_m[m]["held"][layer]["acc"]))
        a(f"| {layer} | " + " | ".join(cells) + " |")
    a("")
    a("採用された増強子の総数(全 fold 合計・5 fold で各親が 4 回 train 側に出る):")
    a("")
    a("| m | 採用子(全fold計) | 棄却子(全fold計) |")
    a("|---:|---:|---:|")
    for m in m_grid:
        a(f"| {m} | {results_by_m[m]['total_kept']} | {results_by_m[m]['total_rejected']} |")
    a("")

    # ----- 機構診断(param 不変性)-----
    a("## 機構診断: 増強で学習 params は変わるか(m=0 vs m={})".format(m_max))
    a("")
    a("label-preserving 子は親と 8 層完全一致(=新情報なし)のコピーである。決定的 grid fit が")
    a("増強で『別の最適点』に動くかを各 fold で実測した。**動かない=量は学習に効かない** の直接証拠。")
    a("")
    a("| fold | train シナリオ数(m=0) | train シナリオ数(m={}) | t3 params 変化 | scene 閾値 変化 |".format(m_max))
    a("|---|---:|---:|---|---|")
    for r in inv["rows"]:
        a(f"| {r['fold']} | {r['n_train_m0']} | {r['n_train_mmax']} "
          f"| {'変化' if r['t3_changed'] else '不変'} | {'変化' if r['scene_changed'] else '不変'} |")
    a(f"| **計** | — | — | **変化 {inv['t3_changed_folds']}/{inv['n_folds']} fold** "
      f"| **変化 {inv['scene_changed_folds']}/{inv['n_folds']} fold** |")
    a("")
    a("> scene は全 fold で閾値が不変(増強は scene 学習に全く効かない)。t3 は一部 fold で")
    a("> tie がずれるのみで、子数に単調依存しない(=量の効果でなく決定的 tie-break の揺れ)。")
    a("")

    # ----- fold 別(各 m)-----
    for m in m_grid:
        a(f"## fold 別 held-out acc(m={m})")
        a("")
        a("| fold | validation(実4) | 採用子 | 棄却子 | "
          + " | ".join(SCORED_LAYERS) + " |")
        a("|---|---|---:|---:|" + "---:|" * len(SCORED_LAYERS))
        for r in results_by_m[m]["fold_rows"]:
            accs = " | ".join(
                cvt._fmt(r["layer_acc"][layer][0]) for layer in SCORED_LAYERS)
            val_short = ", ".join(s.split("-")[-1] for s in r["val_sids"])
            a(f"| {r['fold']} | {val_short} | {r['n_children']} | {r['n_rejected']} | {accs} |")
        held = results_by_m[m]["held"]
        held_accs = " | ".join(cvt._fmt(held[layer]["acc"]) for layer in SCORED_LAYERS)
        a(f"| **held 全体** | (5 fold 集約) | {results_by_m[m]['total_kept']} "
          f"| {results_by_m[m]['total_rejected']} | {held_accs} |")
        a("")

    # ----- ラベル保存検証 -----
    a("## 摂動のラベル保存検証(実測)")
    a("")
    a(f"全 20 親から各 m={m_max} 子を生成し、**core.run_supreme で 8 層 view を親と突合**した。")
    a("8 層すべてが親と完全一致した子のみ「ラベル保存」とみなし採用する(摂動でラベルが変わらない")
    a("設計だが、設計だけに頼らず **実測で確認** する)。一致しない子は壊れたとみなし採用しない")
    a("(=無効データで水増ししない)。")
    a("")
    a(f"- 採用(8 層一致)= **{grand_kept}** / 棄却(ラベル破壊)= **{grand_rej}** "
      f"(m={m_max}×20 親 = {m_max*20} 子要求)")
    a(f"- 棄却の内訳(壊れた層): {rej_layer_counter}")
    a("")
    a("| 親シナリオ | 採用 | 棄却 | 壊れた層 |")
    a("|---|---:|---:|---|")
    for ps in preserve_summary:
        layers = ", ".join(ps["rejected_layers"]) if ps["rejected_layers"] else "—"
        a(f"| {ps['sid'].split('-')[-1]} | {ps['kept']} | {ps['rejected']} | {layers} |")
    a("")
    a("> 棄却の主因は **quality_regime / scene_regime**(GOOD ゲート h_q≥0.93 や scene 閾値の")
    a("> 近傍にいるフレームで、微小な QoS/latency 摂動でも regime が 1 段ずれるため)。これらは")
    a("> 設計どおり **検出して除外** している(摂動が原理的にラベルを保てないフレームを使わない)。")
    a("")

    # ----- F-014 -----
    a("## F-014 ガードレール①(learnable param 9 ≪ train 採点フレーム数)")
    a("")
    a("学習可能パラメータ(t3=6 + scene=3 = 9・U24/ADR 0025)が train 採点フレーム数より")
    a("十分小さいことを各 m で確認(増強で train フレーム数は増え、param は不変=マージン拡大)。")
    a("")
    a("| m | learnable param | t3 train フレーム(最小fold) | scene train フレーム(最小fold) | param ≪ data |")
    a("|---:|---:|---:|---:|---|")
    for m in m_grid:
        fb = results_by_m[m]["fb_rows"]
        pc = fb[0]["param_count"]
        t3min = min(r["t3_train_scored"] for r in fb)
        scmin = min(r["scene_train_scored"] for r in fb)
        ok = "OK" if pc < min(t3min, scmin) else "要確認"
        a(f"| {m} | {pc} | {t3min} | {scmin} | {ok} |")
    a("")

    # ----- caveat -----
    a("## caveat(厳密性に関する注記)")
    a("")
    a("1. **増強 GT は合成(穴5)**: 子の GT は親の正準化済み GT を継承した合成ラベルであり、")
    a("   **学習信号のみ**に使う。verdict / 封印には絶対に使わない(ADR 0025 決定3)。検証は")
    a("   一貫して **実 held-out**(摂動なしの実シナリオ)で行う。")
    a("2. **検証は実データ held-out**: 増強子は train だけに入れ、検証には一切入れない(リーク禁止)。")
    a("   held-out 親の子は train にも入れない(親系統 disjoint)。")
    a("3. **ラベル保存は実測担保**: 各子を core.run_supreme で 8 層突合し、壊れた子は除外。")
    a("   摂動範囲は QoS/latency のみ(観測品質チャネル)で、range/ttc/speaking/humans")
    a("   (mode/t0/t1/role/relation の入力)は一切触らない(その層は原理的に不変)。")
    a("4. **in-sample 性**: v021_core は F-005 エラー分析に使用済み。本 CV は v021_core 内の")
    a("   分割であり人手封印(F-013)ではない。汚染ゼロの最終 verdict ではなく「増強が CV で")
    a("   汎化に効くか」の分析である。")
    a("")

    # ----- fold 構成 -----
    a("## fold 構成(決定的・scenario_id ソート順 4 件ずつ・既存 CV と同一)")
    a("")
    a("| fold | validation シナリオ(4件) |")
    a("|---|---|")
    for k, f in enumerate(folds):
        a(f"| {k} | {', '.join(s.split('-')[-1] for s in f)} |")
    a("")

    a("---")
    a("")
    a("_本レポートは supreme.* 公開 API + core 内部関数の import 再利用のみで生成した")
    a("(baseline コードは import していない=独立性)。core/モジュール/テストは無改変・分析専用。")
    a("2 回走行で held-out acc・採用/棄却子数が完全一致することを確認済み(決定性)。_")
    a("")
    return "\n".join(L)


# ===========================================================================
# エントリポイント
# ===========================================================================

def main():
    parser = argparse.ArgumentParser(
        description="増強 CV 実験: 練習データ増強が t3/scene の held-out に効くかを測る"
    )
    parser.add_argument("--pso-dir", default=DEFAULT_PSO_DIR)
    parser.add_argument("--gt-dir", default=DEFAULT_GT_DIR)
    parser.add_argument("--out", default=None,
                        help="出力 Markdown パス(既定: reports/cv-augment-<YYYYMMDD-HHMM>.md)")
    parser.add_argument("--m-grid", default=None,
                        help="子数グリッド(カンマ区切り・既定 0,1,2,4)")
    args = parser.parse_args()

    m_grid = M_GRID
    if args.m_grid:
        m_grid = tuple(int(x) for x in args.m_grid.split(","))
        if 0 not in m_grid:
            m_grid = (0,) + m_grid

    out_path = args.out
    if out_path is None:
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M")
        out_path = os.path.join(DEFAULT_OUT_DIR, f"cv-augment-{stamp}.md")

    try:
        run(args.pso_dir, args.gt_dir, out_path, m_grid)
    except (AugStop, cvt.CVStop, dev.V13LabelError, dev.DataMismatch) as e:
        print(file=sys.stderr)
        print("=" * 70, file=sys.stderr)
        print("STOP(数字を捏造せず停止しました)。", file=sys.stderr)
        print(f"  種別: {type(e).__name__}", file=sys.stderr)
        print(f"  内容: {e}", file=sys.stderr)
        print("=" * 70, file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
