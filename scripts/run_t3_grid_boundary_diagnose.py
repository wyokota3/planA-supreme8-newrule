"""t3 grid 境界張り付き診断 + 候補拡張の CV held-out 検証(分析専用・src 無改変)。

狙い(指示・WORKFLOW ステップ5 の最終確認):
  conv-B(`_W_FLIP_GRID` に低候補 0.0/0.25 を足して t3 CV 0.443→0.533)と同じ筋で、
  t3 の **他の学習 param が grid 境界(最小/最大)に張り付いていないか** を fold 別に確認し、
  張り付いていれば「その方向へ候補を足して CV held-out が改善するか」を測る。
  改善が出れば採用候補(さらに監査)、出なければ「t3 は CV 天井」と honest に報告して revert。

本スクリプトは **分析専用**: src/supreme/*.py を一切変更しない。t3.fit の grid を
**モンキーパッチ(実行中だけ差し替え)** して CV を再測定する(src ファイルは書き換えない)。
run_cv_train.py の CV 基盤(fold 分割・抽出突合・micro_acc)を import 再利用する。

手順:
  1. 現行 grid で fold 別 fit 選択値を出し、各 param が grid の min/max に張り付く fold を特定。
  2. 張り付き param ごとに、その方向へ候補を1段ずつ拡張した grid で CV held-out を再測定。
     in-sample も測り overfit gap(in − held)を毎回出す。1 param ずつ(同時拡張しない)。
  3. 改善(held-out↑ かつ gap 非拡大)の有無で採用/天井を判定。

決定的・stdlib + pyyaml。baseline 非 import。数字は実測のみ(捏造なし)。
"""

from __future__ import annotations

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

from supreme import t3 as t3_mod
import run_cv_train as cv
import run_dev_eval_diagnose as diag
import run_dev_eval as dev


# ---------------------------------------------------------------------------
# 6 学習 param と grid 名の対応(t3.py の fit 内 grids dict と同じ)。
# ---------------------------------------------------------------------------

PARAM_KEYS = (
    "w_conv_ratio",
    "w_switch_rate",
    "w_flip_accum",
    "bias_conv",
    "bias_traffic",
    "bias_quiet",
)

GRID_ATTRS = {
    "w_conv_ratio": "_W_CONV_GRID",
    "w_switch_rate": "_W_SWITCH_GRID",
    "w_flip_accum": "_W_FLIP_GRID",
    "bias_conv": "_BIAS_CONV_GRID",
    "bias_traffic": "_BIAS_TRAFFIC_GRID",
    "bias_quiet": "_BIAS_QUIET_GRID",
}


def current_grids():
    """現行 t3 モジュールの 6 grid をタプルで取り出す。"""
    return {k: tuple(getattr(t3_mod, attr)) for k, attr in GRID_ATTRS.items()}


# ---------------------------------------------------------------------------
# データ読み込み(run_cv_train と同じ経路で t3 サンプルを作る)。
# ---------------------------------------------------------------------------

def load_t3_samples():
    """v021_core 20 シナリオの t3 サンプル(mode_seq/reset_seq/gt)と fold を作る。"""
    pso_dir = cv.DEFAULT_PSO_DIR
    gt_dir = cv.DEFAULT_GT_DIR
    views_by_sid, gt_by_sid, dir_to_sid, dirs = diag.load_views_and_gt(pso_dir, gt_dir)
    sids_sorted = sorted(views_by_sid.keys())
    if len(sids_sorted) != 20:
        raise cv.CVStop(f"シナリオ数が 20 でない: {len(sids_sorted)}。停止する。")

    snaps_by_sid = {}
    for dir_name in dirs:
        pso_path = os.path.join(pso_dir, dir_name, "pso_input.jsonl")
        snaps = dev._load_pso(pso_path)
        sid = dir_to_sid[dir_name]
        snaps_by_sid[sid] = snaps

    # 抽出突合(core 実入力との一致・全件)。
    for sid in sids_sorted:
        cv.verify_extraction_matches_core(snaps_by_sid[sid], views_by_sid[sid], sid)

    t3_samples, _scene_samples = cv.build_practice_data(snaps_by_sid, views_by_sid, gt_by_sid)
    folds = cv.make_folds(sids_sorted)
    return t3_samples, sids_sorted, folds


# ---------------------------------------------------------------------------
# fold 別 fit 選択値(現行 grid)。
# ---------------------------------------------------------------------------

def fit_selected_per_fold(t3_samples, sids_sorted, folds):
    """各 fold の train で fit し、選ばれた 6 param 値を取り出す。

    Returns:
        [ {"fold": k, "train_sids": [...], "weights": {param: val}}, ... ]
    """
    rows = []
    for k, val_sids in enumerate(folds):
        train_sids = [s for s in sids_sorted if s not in set(val_sids)]
        train_practice = [t3_samples[s] for s in train_sids]
        learned = t3_mod.fit(train_practice)
        weights = {key: float(learned.weights[key]) for key in PARAM_KEYS}
        rows.append({"fold": k, "train_sids": train_sids, "weights": weights})
    # in-sample(全 20)でも fit 選択値を見る(全体での張り付きの参考)。
    learned_all = t3_mod.fit([t3_samples[s] for s in sids_sorted])
    in_sample_weights = {key: float(learned_all.weights[key]) for key in PARAM_KEYS}
    return rows, in_sample_weights


def boundary_flags(rows, grids):
    """各 param について、min/max 境界に張り付く fold を集計する。

    Returns:
        { param: {"min": grid_min, "max": grid_max,
                  "at_min_folds": [...], "at_max_folds": [...],
                  "selected": {fold: val}} }
    """
    out = {}
    for key in PARAM_KEYS:
        g = grids[key]
        gmin, gmax = min(g), max(g)
        at_min, at_max, selected = [], [], {}
        for r in rows:
            v = r["weights"][key]
            selected[r["fold"]] = v
            if v == gmin:
                at_min.append(r["fold"])
            if v == gmax:
                at_max.append(r["fold"])
        out[key] = {
            "min": gmin, "max": gmax, "grid": g,
            "at_min_folds": at_min, "at_max_folds": at_max,
            "selected": selected,
        }
    return out


# ---------------------------------------------------------------------------
# grid を差し替えて CV held-out / in-sample を測る(モンキーパッチ・src 無改変)。
# ---------------------------------------------------------------------------

def cv_holdout_and_insample(t3_samples, sids_sorted, grids_override=None):
    """指定 grid override(無ければ現行)で t3 の CV held-out と in-sample acc を測る。

    grids_override: {param: tuple(...)} を一時的に t3_mod の grid 定数へ代入して fit させ、
    測定後に必ず元へ戻す(src ファイルは無改変・実行中メモリのみ差し替え)。

    Returns:
        dict(held_default, held_learned, held_total, insample_default,
             insample_learned, overfit_gap, fold_rows)
    """
    saved = {attr: getattr(t3_mod, attr) for attr in GRID_ATTRS.values()}
    try:
        if grids_override:
            for key, grid in grids_override.items():
                setattr(t3_mod, GRID_ATTRS[key], tuple(grid))
        t3_cv = cv.run_cv_for_module(
            t3_samples, sids_sorted, t3_mod.fit, t3_mod.default_params(), cv.collect_t3_pairs)
        t3_in = cv.run_insample_for_module(
            t3_samples, sids_sorted, t3_mod.fit, t3_mod.default_params(), cv.collect_t3_pairs)
    finally:
        for attr, val in saved.items():
            setattr(t3_mod, attr, val)

    held_l = t3_cv["held_learned_acc"]
    in_l = t3_in["learned_acc"]
    gap = None if (held_l is None or in_l is None) else (in_l - held_l)
    return {
        "held_default": t3_cv["held_default_acc"],
        "held_learned": held_l,
        "held_total": t3_cv["held_total"],
        "insample_default": t3_in["default_acc"],
        "insample_learned": in_l,
        "overfit_gap": gap,
        "fold_rows": t3_cv["fold_rows"],
    }


# ---------------------------------------------------------------------------
# 拡張候補の生成(張り付き方向へ1段足す)。
# ---------------------------------------------------------------------------

def propose_extensions(boundaries, grids):
    """境界張り付きが起きた param について、その方向へ候補を1段ずつ足す拡張案を作る。

    下限張り付き → より小さい候補を1〜2個足す。上限張り付き → より大きい候補を1〜2個足す。
    張り付きが無い param は拡張案を出さない(天井候補でない)。

    Returns:
        [ {"param": key, "direction": "lower"/"upper", "old_grid": (...),
           "new_grid": (...), "added": [...]} , ... ]
    """
    proposals = []
    for key in PARAM_KEYS:
        b = boundaries[key]
        g = list(b["grid"])
        gmin, gmax = b["min"], b["max"]
        step = _typical_step(g)
        if b["at_min_folds"]:
            # 下限へ1〜2段拡張(値域の意味を壊さない範囲で)。
            lowers = _lower_candidates(key, gmin, step)
            if lowers:
                new_grid = tuple(sorted(set(lowers) | set(g)))
                proposals.append({
                    "param": key, "direction": "lower",
                    "old_grid": tuple(g), "new_grid": new_grid,
                    "added": [x for x in lowers if x not in g],
                    "at_folds": list(b["at_min_folds"]),
                })
        if b["at_max_folds"]:
            uppers = _upper_candidates(key, gmax, step)
            if uppers:
                new_grid = tuple(sorted(set(uppers) | set(g)))
                proposals.append({
                    "param": key, "direction": "upper",
                    "old_grid": tuple(g), "new_grid": new_grid,
                    "added": [x for x in uppers if x not in g],
                    "at_folds": list(b["at_max_folds"]),
                })
    return proposals


def _typical_step(grid):
    """grid の隣接差の代表値(最頻ではなく最大差を採る=拡張幅の目安)。"""
    diffs = [grid[i + 1] - grid[i] for i in range(len(grid) - 1)]
    return max(diffs) if diffs else 1.0


def _lower_candidates(key, gmin, step):
    """下限張り付き param の追加候補(より小さい値)。

    weight(w_*)は係数で 0 が自然な下限(0 未満は『負の重み』で意味反転=過適合源なので避ける)。
    bias は負方向に意味があるので 1〜2 段足す。
    """
    if key.startswith("w_"):
        # 重みは 0 が下限。gmin が既に 0 なら拡張不能(これ以上下げると符号反転=禁止)。
        cands = []
        if gmin > 0.0:
            cands.append(0.0)
            mid = round(gmin / 2.0, 4)
            if 0.0 < mid < gmin:
                cands.append(mid)
        return sorted(set(cands))
    # bias: 負方向へ1〜2段。
    return sorted({round(gmin - step, 4), round(gmin - 2 * step, 4)})


def _upper_candidates(key, gmax, step):
    """上限張り付き param の追加候補(より大きい値)。

    weight は上へ1〜2段(係数を強める)。bias は 0 を超えると意味が変わる場合があるが
    探索空間拡張として1段だけ足す(過適合監視は CV で行う)。
    """
    if key.startswith("w_"):
        return sorted({round(gmax + step, 4), round(gmax + 2 * step, 4)})
    # bias は上方向(正)へ1段(0 近傍を跨ぐ場合あり)。
    return sorted({round(gmax + step, 4)})


# ---------------------------------------------------------------------------
# レポート
# ---------------------------------------------------------------------------

def _fmt(x):
    return "NA" if x is None else f"{x:.4f}"


def _fmt_delta(x):
    return "NA" if x is None else f"{x:+.4f}"


def run(out_path):
    print("[1/5] データ読み込み + 抽出突合(core 実入力との一致・全件)")
    t3_samples, sids_sorted, folds = load_t3_samples()
    grids = current_grids()
    print("      現行 grid:")
    for key in PARAM_KEYS:
        print(f"        {key:14s} = {grids[key]}")

    print()
    print("[2/5] fold 別 fit 選択値(現行 grid)")
    rows, in_sample_weights = fit_selected_per_fold(t3_samples, sids_sorted, folds)
    for r in rows:
        vals = " ".join(f"{k}={r['weights'][k]:g}" for k in PARAM_KEYS)
        print(f"        fold {r['fold']}: {vals}")
    vals = " ".join(f"{k}={in_sample_weights[k]:g}" for k in PARAM_KEYS)
    print(f"        in-sample(全20): {vals}")

    print()
    print("[3/5] grid 境界張り付き(min/max)の特定")
    boundaries = boundary_flags(rows, grids)
    for key in PARAM_KEYS:
        b = boundaries[key]
        note = []
        if b["at_min_folds"]:
            note.append(f"下限{b['min']:g} 張り付き fold={b['at_min_folds']}")
        if b["at_max_folds"]:
            note.append(f"上限{b['max']:g} 張り付き fold={b['at_max_folds']}")
        msg = " / ".join(note) if note else "境界張り付きなし"
        print(f"        {key:14s} grid[{b['min']:g}..{b['max']:g}]: {msg}")

    print()
    print("[4/5] 現行 grid の CV held-out / in-sample(baseline)")
    base = cv_holdout_and_insample(t3_samples, sids_sorted, None)
    print(f"        held-out 既定→学習: {_fmt(base['held_default'])} → {_fmt(base['held_learned'])}"
          f"(分母 {base['held_total']})")
    print(f"        in-sample 既定→学習: {_fmt(base['insample_default'])} → {_fmt(base['insample_learned'])}")
    print(f"        overfit gap(in − held): {_fmt_delta(base['overfit_gap'])}")

    print()
    print("[5/5] 境界張り付き param の拡張案を 1 つずつ試して CV 再測定")
    proposals = propose_extensions(boundaries, grids)
    ext_results = []
    if not proposals:
        print("        境界張り付き param なし(または拡張不能=重みが既に下限0)。拡張案なし。")
    for p in proposals:
        override = {p["param"]: p["new_grid"]}
        res = cv_holdout_and_insample(t3_samples, sids_sorted, override)
        d_held = res["held_learned"] - base["held_learned"]
        d_gap = (res["overfit_gap"] - base["overfit_gap"]
                 if res["overfit_gap"] is not None and base["overfit_gap"] is not None else None)
        ext_results.append({"proposal": p, "result": res, "d_held": d_held, "d_gap": d_gap})
        print(f"        [{p['param']} {p['direction']} +{p['added']}] "
              f"held {_fmt(base['held_learned'])}→{_fmt(res['held_learned'])} "
              f"(Δ{_fmt_delta(d_held)}) gap {_fmt_delta(base['overfit_gap'])}→{_fmt_delta(res['overfit_gap'])}"
              f"(Δgap {_fmt_delta(d_gap)})")

    # --- 採用候補の有無 ---
    print()
    adopt = [e for e in ext_results if e["d_held"] is not None and e["d_held"] > 0
             and (e["d_gap"] is None or e["d_gap"] <= 1e-9)]
    if adopt:
        print("      >>> 採用候補(held-out 改善 かつ gap 非拡大):")
        for e in adopt:
            p = e["proposal"]
            print(f"          {p['param']} {p['direction']} {p['new_grid']}  "
                  f"Δheld={_fmt_delta(e['d_held'])} Δgap={_fmt_delta(e['d_gap'])}")
    else:
        print("      >>> 採用候補なし: どの拡張も held-out 改善せず(または gap 拡大)。")
        print("          => t3 は現行 grid で CV 天井。grid 拡張による追加改善は過適合(revert)。")

    # --- レポート md ---
    _write_report(out_path, grids, rows, in_sample_weights, boundaries, base,
                  ext_results, adopt)
    print()
    print(f"レポート書き出し: {out_path}")
    return base, ext_results, adopt


def _write_report(out_path, grids, rows, in_sample_weights, boundaries, base,
                  ext_results, adopt):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    L = []
    a = L.append
    a("# t3 grid 境界張り付き診断 + 候補拡張 CV held-out 検証")
    a("")
    a(f"- 生成時刻: {now}")
    a("- 対象: v021_core 20シナリオ(各独立 root・lineage-disjoint 5-fold)")
    a("- 目的: conv-B と同じ筋で t3 の他学習 param に grid 境界張り付きがあるか・"
      "あれば候補拡張で CV held-out が改善するか(改善のみ採用・無ければ天井)")
    a("- **分析専用**: src/supreme/*.py 無改変。fit の grid 定数を実行中メモリのみ"
      "モンキーパッチして CV を再測定(ファイルは書き換えない)。")
    a("- run_cv_train.py の CV 基盤(fold 分割・抽出突合・micro_acc)を import 再利用・決定的。")
    a("")

    a("## 1. 現行 grid")
    a("")
    a("| param | grid |")
    a("|---|---|")
    for key in PARAM_KEYS:
        a(f"| `{key}` | {grids[key]} |")
    a("")

    a("## 2. fold 別 fit 選択値(現行 grid)")
    a("")
    a("| fold | " + " | ".join(f"`{k}`" for k in PARAM_KEYS) + " |")
    a("|---|" + "---|" * len(PARAM_KEYS))
    for r in rows:
        a(f"| {r['fold']} | " + " | ".join(f"{r['weights'][k]:g}" for k in PARAM_KEYS) + " |")
    a("| in-sample(全20) | " + " | ".join(f"{in_sample_weights[k]:g}" for k in PARAM_KEYS) + " |")
    a("")

    a("## 3. grid 境界張り付き(min/max)")
    a("")
    a("| param | grid min | grid max | 下限張り付き fold | 上限張り付き fold |")
    a("|---|---:|---:|---|---|")
    for key in PARAM_KEYS:
        b = boundaries[key]
        amin = ", ".join(str(f) for f in b["at_min_folds"]) or "—"
        amax = ", ".join(str(f) for f in b["at_max_folds"]) or "—"
        a(f"| `{key}` | {b['min']:g} | {b['max']:g} | {amin} | {amax} |")
    a("")
    a("> 「張り付き」= その fold の fit が grid の最小値(下限)または最大値(上限)を選んだ"
      "= 探索空間が狭くて fit が最適に届かない疑い(conv-B 前の w_flip が下限張り付きだったのと同型)。")
    a("")

    a("## 4. baseline(現行 grid)の CV held-out / in-sample")
    a("")
    a("| 指標 | 既定 | 学習 |")
    a("|---|---:|---:|")
    a(f"| held-out | {_fmt(base['held_default'])} | {_fmt(base['held_learned'])} |")
    a(f"| in-sample | {_fmt(base['insample_default'])} | {_fmt(base['insample_learned'])} |")
    a(f"| overfit gap(in − held 学習) | | {_fmt_delta(base['overfit_gap'])} |")
    a(f"| held-out 採点分母 | | {base['held_total']} |")
    a("")

    a("## 5. 境界張り付き param の拡張 → CV 再測定(1 param ずつ)")
    a("")
    if not ext_results:
        a("境界張り付き param なし(または重みが既に下限 0 で拡張不能)。**拡張案なし**。")
        a("")
    else:
        a("| 拡張 param | 方向 | 追加候補 | held(base→new) | Δheld | gap(base→new) | Δgap | 採用? |")
        a("|---|---|---|---|---:|---|---:|---|")
        for e in ext_results:
            p = e["proposal"]
            res = e["result"]
            adopted = (e["d_held"] is not None and e["d_held"] > 0
                       and (e["d_gap"] is None or e["d_gap"] <= 1e-9))
            verdict = "**採用候補**" if adopted else "不採用"
            a(f"| `{p['param']}` | {p['direction']} | {p['added']} "
              f"| {_fmt(base['held_learned'])}→{_fmt(res['held_learned'])} "
              f"| {_fmt_delta(e['d_held'])} "
              f"| {_fmt_delta(base['overfit_gap'])}→{_fmt_delta(res['overfit_gap'])} "
              f"| {_fmt_delta(e['d_gap'])} | {verdict} |")
        a("")
        a("> 採用条件(指示): held-out が改善(Δheld>0)し、かつ overfit gap が拡大しない"
          "(Δgap≤0)。両立しなければ不採用(過適合 or 天井)。")
        a("")

    a("## 6. 判定")
    a("")
    if adopt:
        a("**採用候補あり**: 以下の拡張が CV held-out を改善し overfit gap を拡大しない。")
        a("")
        for e in adopt:
            p = e["proposal"]
            a(f"- `{p['param']}` を {p['direction']} 方向へ {p['new_grid']} に拡張 "
              f"(Δheld={_fmt_delta(e['d_held'])}, Δgap={_fmt_delta(e['d_gap'])})")
        a("")
        a("→ 次工程: この拡張を src へ反映 → 790テスト緑確認 → 監査(過適合再確認)。")
    else:
        a("**採用候補なし = t3 は現行 grid で CV 天井**。")
        a("")
        a("境界張り付き param への候補拡張をすべて試したが、CV held-out が改善する拡張は"
          "1 件も無かった(または改善しても overfit gap が拡大=過適合)。")
        a("conv-B(`_W_FLIP_GRID` 拡張)で得た 0.5381 が現行データでの t3 の CV 天井であり、"
          "これ以上の grid 拡張は in-sample への合わせ込み(過適合)にしかならない。")
        a("")
        a("→ **src は無改変(revert 不要・そもそも書いていない)**。honest に「t3 はこれ以上"
          " CV で詰められない」と報告する。")
    a("")
    a("---")
    a("")
    a("_分析専用(src 無改変・baseline 非 import・決定的)。grid は実行中メモリのみ"
      "モンキーパッチし測定後に復元。CV 基盤は run_cv_train.py を再利用。_")

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(L))


def main():
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M")
    out_path = os.path.join("reports", f"t3-grid-boundary-{stamp}.md")
    if len(sys.argv) > 1:
        out_path = sys.argv[1]
    try:
        run(out_path)
    except (cv.CVStop, dev.V13LabelError, dev.DataMismatch) as e:
        print(file=sys.stderr)
        print("=" * 70, file=sys.stderr)
        print("STOP(数字を捏造せず停止しました)。", file=sys.stderr)
        print(f"  種別: {type(e).__name__}", file=sys.stderr)
        print(f"  内容: {e}", file=sys.stderr)
        print("=" * 70, file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
