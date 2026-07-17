"""author 合成 CV 実験 — 多様な合成シナリオが t3/scene の held-out 学習に効くかを測る。

狙い(指示):
  t3 の lose は練習データの **多様性不足** の疑い(量増し=増強は効かないと確定済み・
  reports/cv-augment-*.md)。本実験は **多様な合成シナリオ**(author・scripts/author_scenarios.py)
  を train に足し、**実 v021_core の held-out CV** で t3/scene が改善するかを経験的に測る。
  改善するなら「合成多様化が効く」、しないなら「合成では真の多様性を作れない=人手領分」
  (どちらも正しい成果・捏造しない)。

最重要規律(円環回避・捏造防止・指示):
  - 検証は **実 v021_core の held-out のみ**(合成は train だけ・検証に混ぜない=リーク禁止)。
    合成 GT が悪ければ実 held-out が改善しない設計(=合成 GT の悪さは自動検出される)。
  - 合成 GT は **意味論で構成的に決めたラベル**(author_scenarios・baseline 規則/GT_SCHEMA)。
    **supreme.run_supreme でラベル付けしない**(円環禁止)。GT は学習信号のみ・verdict/封印に
    絶対使わない(穴5)。
  - lineage-disjoint 5-fold(実 v021_core)。各 fold の train = 実 train16 + **全 author 合成**、
    validation = 実 held-out 4(合成は検証に入れない)。author 件数を振って効果曲線。
  - F-014: learnable param(t3=6+scene=3=9)≪ train フレーム数を確認。
  - core/モジュール/テスト無改変。決定的(2回走行一致)・stdlib+pyyaml・baseline import しない。

方法(run_cv_train / run_cv_augment を再利用):
  - データ読み込み・正準化・fold 分割・micro acc は既存 CV から再利用(二重実装しない)。
  - 各 fold で core.fit_supreme(train=実16+author, gt) で学習し、validation(実4)の
    t3_hypothesis / scene_regime を学習 params 注入の run_supreme で採点(NA 分母除外)。
  - 比較: 実のみ(author 0)vs 実+author(author n 件)。n を振って効果曲線。
  - 機構診断: author 投入で学習 params が変わる fold 数(変わらない=合成が学習に効かない直接証拠)。

出力: reports/cv-author-<YYYYMMDD-HHMM>.md + 標準出力。
"""

from __future__ import annotations

import argparse
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

# データ読み込み・正準化・fold・micro acc・採点は既存 CV から再利用(二重実装しない)。
import run_dev_eval as dev
import run_dev_eval_diagnose as diag
import run_cv_train as cvt              # make_folds / micro_acc / _fmt / _fmt_delta。
import run_cv_augment as cva            # score_layer_on_scenarios / count_train_frames / SCORED_LAYERS。
import author_scenarios as author       # 多様シナリオ生成器(本実験の合成 generator)。


DEFAULT_PSO_DIR = dev.DEFAULT_PSO_DIR
DEFAULT_GT_DIR = dev.DEFAULT_GT_DIR
DEFAULT_OUT_DIR = "reports"

N_FOLDS = 5
SCORED_LAYERS = cva.SCORED_LAYERS  # ("t3_hypothesis", "scene_regime")


class AuthorCVStop(Exception):
    """author CV の不整合・利得不明・リーク疑い(=数字を捏造せず停止して報告)。"""


# ===========================================================================
# train 構成(実 train16 + author 合成 n 件)
# ===========================================================================

def build_author_train(train_sids, snaps_by_sid, gt_by_sid, author_kept, n_author):
    """実 train シナリオ + 先頭 n_author 件の author 合成シナリオで train を組む。

    - 実 train は v021_core の他 fold シナリオ(held-out 親は入れない=リーク防止)。
    - author 合成は **train 親に依存しない独立 root**(lineage-disjoint・held-out と非交差。
      合成 scenario_id は "author-*" で v021_core と衝突しない=親系統 disjoint が自明)。
    - author GT は **意味論で構成的に決めたラベル**(author_scenarios・run_supreme 非経由)。

    Returns:
        (scenarios, gt, n_added):
          scenarios = {sid: snaps}(実 train + author n 件)
          gt        = {sid: gt_views}(実 train GT + author 構成 GT)
          n_added   = 実際に追加した author 件数(min(n_author, len(author_kept)))。
    """
    scenarios = {}
    gt = {}
    # 実 train を入れる。
    for sid in train_sids:
        scenarios[sid] = snaps_by_sid[sid]
        gt[sid] = gt_by_sid[sid]

    # author 合成を先頭 n_author 件だけ足す(決定的な順序=構成定義順)。
    n_added = 0
    for sc in author_kept[:n_author]:
        aid = sc["scenario_id"]
        if aid in scenarios:
            raise AuthorCVStop(
                f"author scenario_id '{aid}' が実 train と衝突(リネージ非交差が壊れる)。停止する。"
            )
        scenarios[aid] = sc["snaps"]
        gt[aid] = sc["gt_views"]
        n_added += 1
    return scenarios, gt, n_added


# ===========================================================================
# author 件数 n を振った 5-fold CV(効果曲線)
# ===========================================================================

def run_cv_for_n(sids_sorted, snaps_by_sid, gt_by_sid, author_kept, n_author):
    """author n 件を train に足した 5-fold CV を実行し held-out(実4)の t3/scene acc を出す。

    各 fold:
      train = 実 train16 + author 先頭 n 件。validation = 実 held-out 4(合成は入れない)。
      learned = core.fit_supreme(train, gt)。
      held-out 採点 = core.run_supreme(val 実 snaps, params=learned) の t3/scene micro acc。

    Returns:
        dict(held 全体 acc・fold 行・F-014 行・追加 author 件数)。
    """
    folds = cvt.make_folds(sids_sorted, N_FOLDS)
    held_pairs = {layer: [] for layer in SCORED_LAYERS}
    fold_rows = []
    fb_rows = []
    n_added_total = 0

    for k, val_sids in enumerate(folds):
        train_sids = [s for s in sids_sorted if s not in set(val_sids)]
        train_scenarios, train_gt, n_added = build_author_train(
            train_sids, snaps_by_sid, gt_by_sid, author_kept, n_author)
        n_added_total += n_added

        # 学習(実16 + author 合成込み・end-to-end の学習配線)。
        learned = core.fit_supreme(train_scenarios, train_gt)

        # held-out(実4 シナリオのみ・合成は検証に入れない=リーク禁止)。
        val_scenarios = {s: snaps_by_sid[s] for s in val_sids}
        fold_layer_acc = {}
        for layer in SCORED_LAYERS:
            acc, c, t = cva.score_layer_on_scenarios(
                val_scenarios, gt_by_sid, learned, layer)
            fold_layer_acc[layer] = (acc, t)
        # held-out 全体ペア集約(層別)。
        for sid in val_sids:
            views = core.run_supreme(snaps_by_sid[sid], params=learned)
            for layer in SCORED_LAYERS:
                for v, gv in zip(views, gt_by_sid[sid]):
                    held_pairs[layer].append((v.get(layer), gv.get(layer)))

        fold_rows.append({
            "fold": k,
            "val_sids": list(val_sids),
            "n_author": n_added,
            "layer_acc": fold_layer_acc,
        })

        # F-014: learnable param(9)vs train 採点フレーム数。
        t3_scored, _ = cva.count_train_frames(train_scenarios, train_gt, "t3_hypothesis")
        scene_scored, _ = cva.count_train_frames(train_scenarios, train_gt, "scene_regime")
        fb_rows.append({
            "fold": k,
            "param_count": learned.learnable_param_count(),
            "t3_train_scored": t3_scored,
            "scene_train_scored": scene_scored,
        })

    held = {}
    for layer in SCORED_LAYERS:
        acc, c, t = cvt.micro_acc(held_pairs[layer])
        held[layer] = {"acc": acc, "correct": c, "total": t}

    return {
        "n_author": n_author,
        "n_added_per_fold": n_added_total // N_FOLDS if N_FOLDS else 0,
        "held": held,
        "fold_rows": fold_rows,
        "fb_rows": fb_rows,
    }


def diagnose_param_change(sids_sorted, snaps_by_sid, gt_by_sid, author_kept, n_max):
    """各 fold で「author 0 件 と n_max 件で学習 params が変わるか」を実測する(機構診断)。

    合成シナリオが学習に効くなら、fit_supreme の learned t3 重み / scene 閾値が author 投入で
    変わるはず。変わらない fold 数を数える(全 fold で不変=合成が決定的 fit を一切動かさない
    =学習に効かない の直接証拠)。

    Returns:
        {"t3_changed_folds","scene_changed_folds","n_folds","rows":[...]}。
    """
    folds = cvt.make_folds(sids_sorted, N_FOLDS)
    t3_changed = 0
    scene_changed = 0
    rows = []
    for k, val_sids in enumerate(folds):
        train_sids = [s for s in sids_sorted if s not in set(val_sids)]
        sc0, gt0, _ = build_author_train(
            train_sids, snaps_by_sid, gt_by_sid, author_kept, 0)
        scn, gtn, n_added = build_author_train(
            train_sids, snaps_by_sid, gt_by_sid, author_kept, n_max)
        p0 = core.fit_supreme(sc0, gt0)
        pn = core.fit_supreme(scn, gtn)
        t3_same = getattr(p0.t3, "weights", None) == getattr(pn.t3, "weights", None)
        scene_same = p0.scene.thresholds == pn.scene.thresholds
        if not t3_same:
            t3_changed += 1
        if not scene_same:
            scene_changed += 1
        rows.append({
            "fold": k,
            "n_train_0": len(sc0),
            "n_train_n": len(scn),
            "n_author": n_added,
            "t3_changed": not t3_same,
            "scene_changed": not scene_same,
        })
    return {
        "t3_changed_folds": t3_changed,
        "scene_changed_folds": scene_changed,
        "n_folds": len(folds),
        "rows": rows,
    }


# ===========================================================================
# メイン
# ===========================================================================

def run(pso_dir, gt_dir, out_path, n_grid):
    print(f"[1/8] データ読み込み(run_dev_eval 経路の再利用): PSO={pso_dir}")
    print(f"                                              GT ={gt_dir}")
    views_by_sid, gt_by_sid, dir_to_sid, dirs = diag.load_views_and_gt(pso_dir, gt_dir)
    sids_sorted = sorted(views_by_sid.keys())
    print(f"      実シナリオ数: {len(sids_sorted)}(各独立 root・lineage-disjoint)")
    if len(sids_sorted) != 20:
        raise AuthorCVStop(
            f"実シナリオ数が 20 でない: {len(sids_sorted)}。v021_core 20 件前提のため停止する。"
        )

    snaps_by_sid = {}
    for dir_name in dirs:
        snaps = dev._load_pso(os.path.join(pso_dir, dir_name, "pso_input.jsonl"))
        sid = dir_to_sid[dir_name]
        snaps_by_sid[sid] = snaps
        if len(snaps) != len(views_by_sid[sid]):
            raise AuthorCVStop(
                f"[{sid}] snaps 長 {len(snaps)} と view 長 {len(views_by_sid[sid])} が不一致。停止する。"
            )

    # --- author 合成シナリオの生成 + 構成妥当性自己検査 ---
    print()
    print("[2/8] author 合成シナリオを構成的に生成(意味論で GT 構成・run_supreme 非依存)")
    author_res = author.generate_authored_scenarios()
    author_kept = author_res["kept"]
    author_rejected = author_res["rejected"]
    print(f"      構成定義 {author_res['n_specs']} 件 → 採用(自己検査 OK)= {len(author_kept)} / "
          f"破棄(構成不一致)= {len(author_rejected)}")
    if author_rejected:
        for r in author_rejected:
            print(f"        破棄: {r['scenario_id']} — {r['detail'].get('reason')} "
                  f"layer={r['detail'].get('layer')} frame={r['detail'].get('frame')}")
    if not author_kept:
        raise AuthorCVStop(
            "構成妥当な author シナリオが 0 件(全破棄)。合成では一意な GT を作れていない。"
            "無効データで水増ししないため停止する。"
        )
    t3_counts = author.t3_gt_class_counts(author_kept)
    scene_counts = author.scene_gt_class_counts(author_kept)
    print(f"      author t3 GT クラス分布: {t3_counts}")
    print(f"      author scene GT クラス分布: {scene_counts}")

    # --- 合成リーク防止の検証(author の scenario_id が v021_core と衝突しない)---
    print()
    print("[3/8] リーク防止検証(author 合成 ID が実 v021_core と非交差・検証は実のみ)")
    overlap = set(sc["scenario_id"] for sc in author_kept) & set(sids_sorted)
    if overlap:
        raise AuthorCVStop(
            f"author 合成 ID が実 v021_core と衝突: {sorted(overlap)!r}。リーク防止のため停止する。"
        )
    print(f"      OK: author {len(author_kept)} 件は全て独立 root(実 v021_core と非交差)。"
          "検証は実 held-out のみ・合成は train だけ。")

    # --- author 件数 n を振った効果曲線 ---
    n_max = max(n_grid)
    n_grid_eff = tuple(min(n, len(author_kept)) for n in n_grid)
    # 重複を保ちつつ昇順ユニーク化(0 を含む・件数上限でクリップ)。
    seen = set()
    n_grid_use = []
    for n in n_grid_eff:
        if n not in seen:
            seen.add(n)
            n_grid_use.append(n)
    n_grid_use.sort()
    print()
    print(f"[4/8] author CV(投入件数 n={n_grid_use} を振り効果曲線)を実行します")
    print("      train = 実 train16 + author 合成 n 件 / validation = 実 held-out 4(合成は検証に入れない)")
    print("      学習 = core.fit_supreme(実+author)/ 採点 = run_supreme(val 実, params=learned)")
    results_by_n = {}
    for n in n_grid_use:
        res = run_cv_for_n(sids_sorted, snaps_by_sid, gt_by_sid, author_kept, n)
        results_by_n[n] = res
        t3 = res["held"]["t3_hypothesis"]["acc"]
        scene = res["held"]["scene_regime"]["acc"]
        print(f"      n={n:2d}(/fold +{res['n_added_per_fold']}): "
              f"held-out t3={cvt._fmt(t3)} scene={cvt._fmt(scene)}")

    # --- 効果(実のみ n=0 基準の held-out Δ)---
    print()
    print("[5/8] 効果(実のみ n=0 基準の held-out Δ)")
    base = results_by_n[0]["held"]
    for layer in SCORED_LAYERS:
        b = base[layer]["acc"]
        print(f"      {layer}: 実のみ(n=0)= {cvt._fmt(b)}")
        for n in n_grid_use:
            if n == 0:
                continue
            a = results_by_n[n]["held"][layer]["acc"]
            d = (None if (a is None or b is None) else a - b)
            print(f"        n={n:2d}: {cvt._fmt(a)}({cvt._fmt_delta(d)})")

    # --- 機構診断(author 投入で学習 params が変わるか)---
    print()
    print(f"[6/8] 機構診断(author 0 vs {n_max} 件で学習 params が変わるか・fold 別)")
    inv = diagnose_param_change(
        sids_sorted, snaps_by_sid, gt_by_sid, author_kept, min(n_max, len(author_kept)))
    print(f"      t3 学習 params が変化した fold: {inv['t3_changed_folds']}/{inv['n_folds']}")
    print(f"      scene 学習 params が変化した fold: {inv['scene_changed_folds']}/{inv['n_folds']}")

    # --- 決定性検査(2 回走行で一致)---
    print()
    print("[7/8] 決定性検査(author CV を 2 回走行し held-out acc が完全一致するか)")
    results_by_n_2 = {}
    for n in n_grid_use:
        results_by_n_2[n] = run_cv_for_n(
            sids_sorted, snaps_by_sid, gt_by_sid, author_kept, n)
    _assert_results_equal(results_by_n, results_by_n_2)
    print("      決定性 OK: 2 回走行で全 n の held-out acc が完全一致")

    # --- F-014 ガード(param 9 ≪ train フレーム数)---
    print()
    print("[8/8] F-014 ガードレール①(learnable param 9 ≪ train 採点フレーム数)")
    for n in n_grid_use:
        fb = results_by_n[n]["fb_rows"]
        pc = fb[0]["param_count"]
        t3min = min(r["t3_train_scored"] for r in fb)
        scmin = min(r["scene_train_scored"] for r in fb)
        ok = "OK" if pc < min(t3min, scmin) else "要確認"
        print(f"      n={n:2d}: param={pc} << t3_train_frames(min)={t3min} / "
              f"scene_train_frames(min)={scmin} -> {ok}")

    # --- レポート ---
    print()
    print(f"レポート書き出し: {out_path}")
    report_md = _render_report(
        sids_sorted=sids_sorted, n_grid=n_grid_use, results_by_n=results_by_n,
        author_kept=author_kept, author_rejected=author_rejected,
        author_specs=author_res["n_specs"], t3_counts=t3_counts, scene_counts=scene_counts,
        inv=inv, n_max=min(n_max, len(author_kept)),
        folds=cvt.make_folds(sids_sorted, N_FOLDS),
    )
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report_md)
    print(f"      出力完了: {out_path}")
    return results_by_n


def _assert_results_equal(a_by_n, b_by_n):
    """2 回走行の author CV 結果が完全一致するか(決定性・不一致なら停止)。"""
    if set(a_by_n) != set(b_by_n):
        raise AuthorCVStop("決定性違反: 2 回走行で n の集合が異なる。停止する。")
    for n in a_by_n:
        a = a_by_n[n]
        b = b_by_n[n]
        for layer in SCORED_LAYERS:
            if a["held"][layer]["acc"] != b["held"][layer]["acc"]:
                raise AuthorCVStop(
                    f"決定性違反: n={n}・{layer} で held-out acc が 2 回走行で不一致。停止する。"
                )


# ===========================================================================
# 効果曲線の判定(run_cv_augment._verdict_curve と同方針)
# ===========================================================================

def _verdict_curve(curve):
    """効果曲線(n→acc)から、合成多様化が単調に効くか / 平坦か / 揺れかを判定する。

    curve: [(n, acc), ...](n 昇順・先頭 n=0=実のみ)。
    - 全 acc が n=0 と同値 → "no(全 n 同値・平坦=合成は効かない)"。
    - 単調非減少で末端>n=0 → "限定的(単調増 +Δ)"。
    - 非単調(山谷)→ "no(非単調=合成多様化でなく tie-break 揺れ)"。
    """
    accs = [a for _, a in curve]
    if any(a is None for a in accs):
        return "判定不能(NA)", None
    base = accs[0]
    d_max = max(accs) - base
    if all(abs(a - base) < 1e-12 for a in accs):
        return "no(全 n 同値・平坦)", 0.0
    monotone = all(accs[i + 1] >= accs[i] - 1e-12 for i in range(len(accs) - 1))
    final_delta = accs[-1] - base
    if monotone and accs[-1] > base + 1e-12:
        return f"限定的(単調増 +{final_delta:.4f})", final_delta
    return f"no(非単調・tie-break 揺れ・最大Δ {d_max:+.4f})", final_delta


# ===========================================================================
# レポート生成
# ===========================================================================

def _render_report(*, sids_sorted, n_grid, results_by_n, author_kept, author_rejected,
                   author_specs, t3_counts, scene_counts, inv, n_max, folds):
    now = datetime.datetime.now()
    stamp = now.strftime("%Y-%m-%d %H:%M")
    L = []
    a = L.append

    a("# author 合成 CV 実験レポート — 多様な合成シナリオは t3/scene の held-out に効くか")
    a("")
    a(f"- 生成時刻: {stamp}")
    a("- 対象(検証): v021_core 20 シナリオ(各独立 root・lineage-disjoint)の **実 held-out**")
    a("- PSO 入力: planA-baseline/scenarios/v021_core ／ GT: n04-feat/scenarios/v021_core(catalog 1.4.0)")
    a("- generator: 多様シナリオ生成器(`scripts/author_scenarios.py`・決定的・乱数なし)")
    a("- 合成 GT: **baseline 規則 / GT_SCHEMA の文書化済み意味論で構成的に決めたラベル**"
      "(supreme.run_supreme 非依存=円環回避)。")
    a("- 学習: `core.fit_supreme(実16+author, gt)`(end-to-end 学習配線)。検証: **実 held-out のみ**。")
    a("- **本実験は分析専用**: src/supreme/*.py(core/モジュール/テスト)は無改変。")
    a("  supreme.* 公開 API + core 内部関数の import 再利用のみ。baseline は import していない(独立性)。")
    a("- **合成 GT は穴5(合成)= 学習信号のみ。verdict / 封印には使わない**。")
    a("")

    # ----- 結論 -----
    a("## 結論(author 合成多様化は t3/scene の held-out に効くか)")
    a("")
    base = results_by_n[0]["held"]
    a(f"実のみ(n=0)を基準に、author 合成 {n_max} 件投入での held-out 改善 Δ:")
    a("")
    a(f"| 層 | 実のみ(n=0) | 実+author(n={n_max}) | 最終Δ | 効くか(効果曲線で判定) |")
    a("|---|---:|---:|---:|---|")
    verdicts = {}
    for layer in SCORED_LAYERS:
        b = base[layer]["acc"]
        aug = results_by_n[n_grid[-1]]["held"][layer]["acc"]
        curve = [(n, results_by_n[n]["held"][layer]["acc"]) for n in n_grid]
        verdict, d = _verdict_curve(curve)
        verdicts[layer] = verdict
        a(f"| {layer} | {cvt._fmt(b)} | {cvt._fmt(aug)} | {cvt._fmt_delta(d)} | **{verdict}** |")
    a("")
    a("> 「効くか」は **n=max の単発比較でなく効果曲線全体**で判定する(非単調=合成多様化でなく")
    a("> 決定的 tie-break の揺れ・単調増=多様化が効く・全 n 同値=平坦)。")
    a("")
    a("> held-out 採点分母: "
      + " / ".join(f"{layer}={base[layer]['total']}" for layer in SCORED_LAYERS) + " フレーム")
    a("> 検証は **実 held-out のみ**(合成は train だけ・検証に混ぜない=リーク禁止)。")
    a("> 合成 GT が悪ければ実 held-out の改善が出ない設計(=合成 GT の悪さは自動検出される)。")
    a("")

    # ----- なぜ効く/効かないか(機構診断) -----
    a("### なぜこの結果か(機構診断)")
    a("")
    a(f"- author 投入(0→{n_max} 件)で **t3 学習 params が変化した fold = "
      f"{inv['t3_changed_folds']}/{inv['n_folds']}**、"
      f"**scene 学習 params が変化した fold = {inv['scene_changed_folds']}/{inv['n_folds']}**。")
    a("- 合成が決定的 fit を動かさない(params 不変)なら held-out は変わりようがない"
      "(=合成は学習に効かない の直接証拠)。")
    a("- **重要な構造的事実**: 本生成器が厚くした t3 クラス(sustained_alert / crowd_tendency /")
    a("  alert_required / env_shift)は t3 の **規則層**(`t3._rule_hypothesis`=baseline `_classify_t3`")
    a("  の忠実再現)が mode 窓比率から決める **固定規則** であり、**学習対象(conv/traffic/quiet")
    a("  境界のロジスティック重み)ではない**。よって、これらのクラスを構成的に厚くしても、")
    a("  学習可能 param(t3=6個=conv/traffic/quiet 境界)を動かす材料にはならない"
      "(規則層は学習で変わらない)。")
    a("")

    # ----- 効果曲線 -----
    a("## 効果曲線(author 投入件数 n と held-out acc)")
    a("")
    a("| 層 | " + " | ".join(f"n={n}" for n in n_grid) + " |")
    a("|---|" + "---:|" * len(n_grid))
    for layer in SCORED_LAYERS:
        cells = [cvt._fmt(results_by_n[n]["held"][layer]["acc"]) for n in n_grid]
        a(f"| {layer} | " + " | ".join(cells) + " |")
    a("")
    a("各 fold に追加した author 件数(/fold):")
    a("")
    a("| n | /fold 追加 author |")
    a("|---:|---:|")
    for n in n_grid:
        a(f"| {n} | {results_by_n[n]['n_added_per_fold']} |")
    a("")

    # ----- author 構成と GT 根拠 -----
    a("## author シナリオの構成(どのクラスをどう構成的に作ったか)")
    a("")
    a(f"構成定義 {author_specs} 件 → 構成妥当性自己検査 OK で採用 **{len(author_kept)}** 件 / "
      f"破棄 **{len(author_rejected)}** 件。")
    a("")
    a("**GT 構成の根拠(各層・意味論)**:")
    a("- t2_mode = 作者が固定した intent mode(R チャネル証拠を core._mode_logits の発火条件へ")
    a("  排他的に当てて一意化:siren ttc≤2→emergency / 2<ttc≤12→alert_required / "
      "speech∧speaking>0.7∧range<5→conv_ongoing / humans≥3→surround_activity / 低 QoS→env_change)。")
    a("- t3_hypothesis = mode 系列(6 フレーム窓)へ baseline `_classify_t3` 意味論")
    a("  (`t3._rule_hypothesis` の規則 + `classify_t3` の conv/traffic/quiet 境界・default_params)を")
    a("  **構成的に適用**(run_supreme 非経由=円環回避)。")
    a("- risk_tier/t1_state/t2_role/t2_relation/quality_regime = 各 per-frame 証拠の決定論的判定規則")
    a("  (t0/t1/role/relation/quality の文書化済み意味論)から構成。")
    a("- scene_regime = 構成的に一意な **定常端点のみ**(全フレーム高 QoS→STABLE / 全フレーム低 QoS→")
    a("  DEGRADING)。混在(過渡)は HGF 系列依存で一意でないため **GT を付けない(None=学習サンプル外)**。")
    a("")
    a("**author t3 GT クラス分布(フレーム数)**:")
    a("")
    a("| t3 クラス | フレーム数 | v021_core での GT 頻度(診断) |")
    a("|---|---:|---|")
    _v021_t3 = {
        "quiet_stable": 84, "conv_participating": 29, "traffic_unstable": 23,
        "sustained_alert": 23, "env_shift": 15, "crowd_tendency": 14,
        "uncertain_context": 9, "env_start": 7, "alert_required": 4, "hazard_declining": 2,
    }
    for cls in sorted(t3_counts, key=lambda c: -t3_counts[c]):
        v021 = _v021_t3.get(cls, 0)
        thin = " ⚠️ 薄い" if v021 <= 7 else ""
        a(f"| {cls} | {t3_counts[cls]} | {v021}{thin} |")
    a("")
    a(f"**author scene GT クラス分布(フレーム数)**: {scene_counts}"
      "(混在=過渡は None で付けない=曖昧水増し回避)。")
    a("")

    # ----- 構成妥当性自己検査の結果 -----
    a("## 構成妥当性の自己検査(意図した mode-sequence/evidence が実際に出る入力か)")
    a("")
    a("各 author シナリオを **core.run_supreme(snaps) に流し、得た各層が構成的 GT と一致するか** を")
    a("確認した。これは「意図した evidence/mode-sequence がその入力から一意に実現するか」の")
    a("**健全性チェック**であって、GT のラベル付けではない(GT は意味論で構成済み)。一致しない")
    a("(構成が一意でない)シナリオは **採用しない=捨てて報告**(無効ラベルで水増ししない)。")
    a("")
    a(f"- 採用(自己検査で全層 intent 一致)= **{len(author_kept)}** / "
      f"破棄(構成不一致)= **{len(author_rejected)}**")
    if author_rejected:
        a("")
        a("**破棄したシナリオ(構成が一意に実現しなかった=honest finding)**:")
        a("")
        a("| scenario_id | 不一致層 | frame | 構成的 intent | supreme 実出力 |")
        a("|---|---|---:|---|---|")
        for r in author_rejected:
            d = r["detail"]
            a(f"| {r['scenario_id']} | {d.get('layer','-')} | {d.get('frame','-')} "
              f"| {d.get('intent_gt','-')} | {d.get('supreme','-')} |")
    else:
        a("")
        a("(全 14 構成定義が自己検査 OK。env の立ち上がり(env_start)・env を中途に挟む遷移は")
        a("HGF 遅延で構成的に一意化できないため **そもそも構成定義に含めない**=作る前に除外した。)")
    a("")
    a("> **構成上の honest finding(HGF 遅延)**: env_change は h_q<0.5 で立つが、h_q は観測 logit を")
    a("> HGF で平滑化した量のため、高 QoS の **後** に低 QoS を置いても h_q が即座に 0.5 を割らない")
    a("> (2 フレームの過渡)。よって「quiet→env の立ち上がり(env_start)」は構成的に一意に作れない")
    a("> (過渡で mode 系列が intent と食い違う)。**全フレーム env_change の定常列だけ**が構成的に")
    a("> 一意(env_shift)。env_start を合成で厚くできないのは合成の原理的限界の一例である。")
    a("")

    # ----- fold 別(各 n)-----
    for n in n_grid:
        a(f"## fold 別 held-out acc(author n={n})")
        a("")
        a("| fold | validation(実4) | author追加 | "
          + " | ".join(SCORED_LAYERS) + " |")
        a("|---|---|---:|" + "---:|" * len(SCORED_LAYERS))
        for r in results_by_n[n]["fold_rows"]:
            accs = " | ".join(
                cvt._fmt(r["layer_acc"][layer][0]) for layer in SCORED_LAYERS)
            val_short = ", ".join(s.split("-")[-1] for s in r["val_sids"])
            a(f"| {r['fold']} | {val_short} | {r['n_author']} | {accs} |")
        held = results_by_n[n]["held"]
        held_accs = " | ".join(cvt._fmt(held[layer]["acc"]) for layer in SCORED_LAYERS)
        a(f"| **held 全体** | (5 fold 集約) | {results_by_n[n]['n_added_per_fold']} | {held_accs} |")
        a("")

    # ----- 機構診断(param 変化) -----
    a(f"## 機構診断: author 投入で学習 params は変わるか(0 vs {n_max} 件)")
    a("")
    a("合成シナリオが学習に効くなら、決定的 fit の learned t3 重み / scene 閾値が author 投入で")
    a("動くはず。各 fold で実測した(**動かない=合成は学習に効かない** の直接証拠)。")
    a("")
    a(f"| fold | train(0件) | train({n_max}件) | author追加 | t3 params 変化 | scene 閾値 変化 |")
    a("|---|---:|---:|---:|---|---|")
    for r in inv["rows"]:
        a(f"| {r['fold']} | {r['n_train_0']} | {r['n_train_n']} | {r['n_author']} "
          f"| {'変化' if r['t3_changed'] else '不変'} | {'変化' if r['scene_changed'] else '不変'} |")
    a(f"| **計** | — | — | — | **変化 {inv['t3_changed_folds']}/{inv['n_folds']} fold** "
      f"| **変化 {inv['scene_changed_folds']}/{inv['n_folds']} fold** |")
    a("")

    # ----- F-014 -----
    a("## F-014 ガードレール①(learnable param 9 ≪ train 採点フレーム数)")
    a("")
    a("学習可能パラメータ(t3=6 + scene=3 = 9・U24/ADR 0025)が train 採点フレーム数より十分小さい")
    a("ことを各 n で確認(author 投入で train フレーム数は増え、param は不変=マージン拡大)。")
    a("")
    a("| n | learnable param | t3 train フレーム(最小fold) | scene train フレーム(最小fold) | param ≪ data |")
    a("|---:|---:|---:|---:|---|")
    for n in n_grid:
        fb = results_by_n[n]["fb_rows"]
        pc = fb[0]["param_count"]
        t3min = min(r["t3_train_scored"] for r in fb)
        scmin = min(r["scene_train_scored"] for r in fb)
        ok = "OK" if pc < min(t3min, scmin) else "要確認"
        a(f"| {n} | {pc} | {t3min} | {scmin} | {ok} |")
    a("")

    # ----- caveat -----
    a("## caveat(厳密性に関する注記)")
    a("")
    a("1. **合成 GT は穴5(合成)・円環回避**: author の GT は baseline 規則 / GT_SCHEMA の")
    a("   **文書化済み意味論**で構成的に決めたラベルであり、**supreme.run_supreme でラベル付け")
    a("   していない**(自己ラベル=円環は禁止)。GT は学習信号のみ・verdict / 封印には使わない。")
    a("2. **検証は実 held-out のみ**: author 合成は train だけに入れ、検証(採点)には一切入れない")
    a("   (リーク禁止)。合成 ID は独立 root(実 v021_core と非交差)。合成 GT が悪ければ実 held-out の")
    a("   改善が出ない=合成 GT の悪さは自動検出される。")
    a("3. **構成的に一意な範囲のみ**: GT が一意に定まらない状況(env の過渡・HGF 系列依存の scene")
    a("   遷移)は **作らない / GT を付けない**(無効ラベルで水増ししない)。env_start を合成で厚く")
    a("   できないのは合成の原理的限界。")
    a("4. **規則層と学習層の区別(最重要)**: 厚くした t3 クラスの多くは t3 規則層(固定・学習対象外)の")
    a("   出力。学習可能 param(conv/traffic/quiet 境界)を動かすには、その 3 境界が誤る多様な状況が")
    a("   要る。合成でそこを的確に作れているか自体が本実験の問い。")
    a("5. **in-sample 性**: v021_core は F-005 エラー分析に使用済み。本 CV は v021_core 内の分割であり")
    a("   人手封印(F-013)ではない。汚染ゼロの最終 verdict ではなく「合成多様化が CV で効くか」の分析。")
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
    a("合成 GT は意味論で構成的に決めたもので run_supreme でラベル付けしていない(円環回避)。")
    a("2 回走行で held-out acc が完全一致することを確認済み(決定性)。_")
    a("")
    return "\n".join(L)


# ===========================================================================
# エントリポイント
# ===========================================================================

def main():
    parser = argparse.ArgumentParser(
        description="author 合成 CV 実験: 多様な合成シナリオが t3/scene の held-out に効くかを測る"
    )
    parser.add_argument("--pso-dir", default=DEFAULT_PSO_DIR)
    parser.add_argument("--gt-dir", default=DEFAULT_GT_DIR)
    parser.add_argument("--out", default=None,
                        help="出力 Markdown パス(既定: reports/cv-author-<YYYYMMDD-HHMM>.md)")
    parser.add_argument("--n-grid", default=None,
                        help="author 投入件数グリッド(カンマ区切り・既定 0,3,7,14)")
    args = parser.parse_args()

    n_grid = (0, 3, 7, 14)
    if args.n_grid:
        n_grid = tuple(int(x) for x in args.n_grid.split(","))
        if 0 not in n_grid:
            n_grid = (0,) + n_grid

    out_path = args.out
    if out_path is None:
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M")
        out_path = os.path.join(DEFAULT_OUT_DIR, f"cv-author-{stamp}.md")

    try:
        run(args.pso_dir, args.gt_dir, out_path, n_grid)
    except (AuthorCVStop, author.AuthorError, cvt.CVStop, cva.AugStop,
            dev.V13LabelError, dev.DataMismatch) as e:
        print(file=sys.stderr)
        print("=" * 70, file=sys.stderr)
        print("STOP(数字を捏造せず停止しました)。", file=sys.stderr)
        print(f"  種別: {type(e).__name__}", file=sys.stderr)
        print(f"  内容: {e}", file=sys.stderr)
        print("=" * 70, file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
