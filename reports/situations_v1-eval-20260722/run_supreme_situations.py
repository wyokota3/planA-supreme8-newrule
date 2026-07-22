"""F-015: situations_v1 能力評価キャンペーン・ランナー(supreme8 / NeuPSL)。

situations_v1(world-first 生成の std/emg/crw/bst/dcp/crp)で supreme8 を評価する。
**strict OFF 必須**(ADR 0049/0050: 能力評価では config={"strict_gt_conformance": False})。
src/supreme/*.py は無変更(アダプタ規約=ADR 0058)。契約違反シナリオは preflight で明示拒否し
rejection_acc として別採点する(8 層採点の分母から除外)。

構成(--configs で選択・既定 all):
  N1     : params=None(事前重みベースライン=NeuPSL 既定 + t3/scene 既定)。
  N2     : params=core.fit_supreme(train_all)(既定 10 エポック T2・bilevel なし)。
  N3     : ADR 0057 レシピ(PRIMARY)。t3/scene は core.fit_supreme、T2 のみ手配線で
           基礎 6 エポック(neupsl.fit)+ bilevel 2 エポック(neupsl.fit_bilevel・MLP 凍結)。
           N2 と同一の core.fit_supreme(train_all) を共有し、dataclasses.replace で T2 差替。
  N3-std : N3 と同レシピを std/train(80 本・違反なし)だけで学習(生成器スモークと可比)。

学習データ = 各 suite の train split から契約違反 13 本を除外(N3-std は std/train のみ)。
評価データ = 各 suite の eval split。違反 5 本(全 crp/eval)は preflight→拒否集計のみ、
非違反 235 本は engine 実走。train 側違反 13 本も preflight して情報として別掲する。

使い方:
    python run_supreme_situations.py --configs N1,N2,N3,N3-std
    python run_supreme_situations.py --configs N3        # 分割実行(results.json へマージ)

依存: stdlib + pyyaml(GT 読込)。決定的(乱数・時刻に依存する採点経路なし。timings は metadata)。
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import math
import os
import pickle
import subprocess
import sys
import time
import traceback

# --- src/supreme を import 解決(スクリプト位置からの相対・絶対 scratchpad パス禁止)---
_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(_HERE, "..", "..", "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from supreme import core, harness  # noqa: E402
from supreme import neupsl as neupsl_mod  # noqa: E402
import situations_common as sc  # noqa: E402

MEASUREMENT_DATE = "2026-07-22"
STRICT_OFF = {"strict_gt_conformance": False}
ALL_CONFIGS = ("N1", "N2", "N3", "N3-std")

# ADR 0054/0057 の bilevel 微調整レシピ(MLP 凍結・保守設定)。
_BILEVEL_KW = dict(epochs=2, rho=0.6, mu=1.0, lr_y=0.2, lr_w=0.08, lr_n=0.0)
_BASE_EPOCHS = 6  # ADR 0057: 基礎 6 エポック + bilevel 2 = 8 エポック。


# ---------------------------------------------------------------------------
# データ読込(生 PSO / GT のキャッシュ)
# ---------------------------------------------------------------------------
def load_caches(recs):
    """recs のシナリオを生 PSO フレーム列・生 GT フレーム列でキャッシュする。"""
    pso, gt = {}, {}
    for r in recs:
        pso[r["sid"]] = sc.load_pso_frames(r["dir"])
        gt[r["sid"]] = sc.load_gt_frames(r["dir"])
    return pso, gt


def build_train_inputs(recs_train_nonviol, pso_cache, gt_cache):
    """core.fit_supreme 用の {sid: prepared_snaps} と {sid: [gt_view,...]} を作る。"""
    snaps = {r["sid"]: sc.prepare_snaps(pso_cache[r["sid"]]) for r in recs_train_nonviol}
    gt = {r["sid"]: [sc.gt_view(fr) for fr in gt_cache[r["sid"]]] for r in recs_train_nonviol}
    return snaps, gt


# ---------------------------------------------------------------------------
# t3/scene のみ学習(core.fit_supreme の t3/scene 部分を逐語再現)
# ---------------------------------------------------------------------------
def fit_t3_scene_only(train_snaps, train_gt):
    """core.fit_supreme(core.py:1574-1608)の t3/scene 学習部分を逐語再現する。

    N3 は core.fit_supreme の 10 エポック T2 を破棄して T2 を手配線するため、その 10 エポック
    再学習は純粋な冗長コスト(base_all で ~37 分の大半)。本関数は core と**同一のヘルパ・同一の
    順序・同一の ≥ガード**で t3/scene だけを決定的に学習するので、返り値の t3/scene は
    core.fit_supreme(train_all) が返す t3/scene と**数値的に完全一致**する(t2=None)。純粋な
    性能最適化であり結果は不変(ADR 0058 に明記)。
    """
    t3_samples, scene_samples = [], []
    for sid, snaps in train_snaps.items():
        snaps = list(snaps)
        gt_views = list(train_gt.get(sid, []))
        views = core._run_one_scenario(snaps, None, None)  # config=None → strict(supreme2)経路
        t3_samples.append(core._t3_practice_from_scenario(snaps, views, gt_views))
        scene_samples.append(core._scene_practice_from_scenario(snaps, gt_views))

    t3_default = core.t3_mod.default_params()
    t3_learned = core.t3_mod.fit(t3_samples)
    acc_d = core._t3_train_acc(t3_default, t3_samples)
    acc_l = core._t3_train_acc(t3_learned, t3_samples)
    t3_chosen = t3_default if (acc_d is not None and (acc_l is None or acc_l < acc_d)) else t3_learned

    scene_learned = core.scene_mod.fit(scene_samples)
    acc_sd = core._scene_train_acc(None, scene_samples)
    acc_sl = core._scene_train_acc(scene_learned, scene_samples)
    if acc_sd is not None and (acc_sl is None or acc_sl < acc_sd):
        scene_chosen = core.dataclasses.replace(
            core.scene_mod.fit([]), thresholds=dict(core._SCENE_THRESHOLDS))
    else:
        scene_chosen = scene_learned

    return core.SupremeParams(t3=t3_chosen, scene=scene_chosen, t2=None)


# ---------------------------------------------------------------------------
# 段階 pickle キャッシュ(killed からの再開用・compute 秒も同梱)
# ---------------------------------------------------------------------------
def cached(cache_dir, key, fn):
    """cache_dir/key.pkl があれば載せ、無ければ fn() を計算して保存する。

    返り値 (value, compute_seconds)。compute_seconds は初回計算時の実測を pickle に同梱し、
    再開ロード時も真の学習所要秒を返す(timings の metadata を再開に依存させない)。
    """
    if cache_dir:
        path = os.path.join(cache_dir, key + ".pkl")
        if os.path.exists(path):
            with open(path, "rb") as f:
                blob = pickle.load(f)
            print(f"[cache] load {key} (compute was {blob['compute_seconds']:.1f}s)", flush=True)
            return blob["value"], blob["compute_seconds"]
        ts = time.perf_counter()
        val = fn()
        sec = time.perf_counter() - ts
        os.makedirs(cache_dir, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump({"value": val, "compute_seconds": sec}, f)
        print(f"[cache] save {key} ({sec:.1f}s)", flush=True)
        return val, sec
    ts = time.perf_counter()
    val = fn()
    return val, time.perf_counter() - ts


# ---------------------------------------------------------------------------
# T2 手配線(ADR 0057: 基礎 6 + bilevel 2・core と同じ t2_scens 構築 + ≥ガード)
# ---------------------------------------------------------------------------
def build_t2_scens(train_snaps, train_gt):
    """core.fit_supreme(core.py:1611-1622)と同一手順で T2 学習入力 [(feats, gts)] を作る。"""
    sids_all = sorted(train_snaps.keys())
    stride = max(1, len(sids_all) // core._T2_FIT_MAX_SCENARIOS)
    t2_scens = []
    for sid in sids_all[::stride][:core._T2_FIT_MAX_SCENARIOS]:
        snaps_s = list(train_snaps[sid])
        gt_views = list(train_gt.get(sid, []))
        feats = core._neupsl_inputs_from_scenario(snaps_s)
        gts = [{"mode": (gt_views[i] or {}).get("t2_mode") if i < len(gt_views) else None,
                "role": (gt_views[i] or {}).get("t2_role") if i < len(gt_views) else None,
                "rel": (gt_views[i] or {}).get("t2_relation") if i < len(gt_views) else None}
               for i in range(len(feats))]
        t2_scens.append((feats, gts))
    return t2_scens


def _fit_t2_final(t2_scens, t2_base6):
    """bilevel 2 エポック微調整 + core と同一の ≥ガードを適用し最終 T2 を選ぶ。

    fit_bilevel は params を in-place 変更するため base6 のコピーを渡す(base6 の再利用を守る)。
    ≥ガード = 学習(base6+bilevel2)vs 既定(事前重み)を最大 400 練習シナリオで比較し良い方 >=。
    """
    base_copy = pickle.loads(pickle.dumps(t2_base6))
    t2_tuned = neupsl_mod.fit_bilevel(t2_scens, base_copy, **_BILEVEL_KW)

    t2_default = neupsl_mod.default_params()
    g_stride = max(1, len(t2_scens) // core._T2_GUARD_MAX_SCENARIOS)
    guard_scens = t2_scens[::g_stride][:core._T2_GUARD_MAX_SCENARIOS]
    acc_tuned = core._t2_train_acc(t2_tuned, guard_scens)
    acc_default = core._t2_train_acc(t2_default, guard_scens)
    guard = {"acc_tuned": acc_tuned, "acc_default": acc_default,
             "guard_scenarios": len(guard_scens)}
    if acc_default is not None and (acc_tuned is None or acc_tuned < acc_default):
        return {"t2": t2_default, "guard": guard, "choice": "default(prior)"}
    return {"t2": t2_tuned, "guard": guard, "choice": "tuned(base6+bilevel2)"}


def build_handwired_params(train_key, train_snaps, train_gt, n_train, cache_dir):
    """ADR 0057 手配線 params を段階キャッシュ付きで構築する(killed から再開可能)。

    段階(各段を pickle 保存): t3scene(core と数値同一)→ t2scens 構築 → t2_base6(neupsl.fit 6ep)
    → t2final(neupsl.fit_bilevel 2ep + ≥ガード)。dataclasses.replace で t3scene に t2 を差替。
    """
    t3scene, a_sec = cached(cache_dir, f"{train_key}_t3scene",
                            lambda: fit_t3_scene_only(train_snaps, train_gt))
    t2_scens, s_sec = cached(cache_dir, f"{train_key}_t2scens",
                             lambda: build_t2_scens(train_snaps, train_gt))
    t2_base6, b_sec = cached(cache_dir, f"{train_key}_t2base6",
                             lambda: neupsl_mod.fit(t2_scens, epochs=_BASE_EPOCHS))
    stage_c, c_sec = cached(cache_dir, f"{train_key}_t2final",
                            lambda: _fit_t2_final(t2_scens, t2_base6))

    params = dataclasses.replace(t3scene, t2=stage_c["t2"])
    fit_info = {
        "train_scenarios": n_train,
        "seconds": a_sec + s_sec + b_sec + c_sec,
        "t3scene_seconds": a_sec,
        "t2scens_seconds": s_sec,
        "t2_base6_seconds": b_sec,
        "t2_bilevel_guard_seconds": c_sec,
        "t2_scenarios": len(t2_scens),
        "t2_guard": stage_c["guard"],
        "t2_choice": stage_c["choice"],
        "note": "t3/scene は core.fit_supreme の t3/scene 部分を逐語再現(core と数値同一)。"
                "10ep T2 の冗長再学習を回避するための最適化。基礎6+bilevel2 は ADR 0057 レシピ。",
    }
    return params, fit_info


# ---------------------------------------------------------------------------
# 評価(非違反 engine 実走 → trace → per-suite/pooled 採点)
# ---------------------------------------------------------------------------
def run_eval(params, recs_eval_nonviol, pso_cache, gt_cache):
    """非違反 eval シナリオを engine 実走して trace を組み、crash は握り潰さず記録する。"""
    trace, crashes = {}, []
    for r in recs_eval_nonviol:
        sid = r["sid"]
        pso = pso_cache[sid]
        gtf = gt_cache[sid]
        pf = sc.preflight_validate(pso, len(gtf))
        if not pf["ok"]:
            # 非違反が preflight で弾かれるのは想定外(データ側の異常)。捏造せず incident 化。
            crashes.append({"sid": sid, "kind": "unexpected_preflight_reject",
                            "reason": pf["reason"], "detail": pf["detail"]})
            continue
        snaps = sc.prepare_snaps(pso)
        try:
            views = core.run_supreme_scenarios({sid: snaps}, params, config=STRICT_OFF)[sid]
        except Exception as e:  # noqa: BLE001 - robustness finding として記録
            tb = traceback.format_exc().strip().splitlines()
            crashes.append({"sid": sid, "kind": "engine_crash", "error": repr(e),
                            "traceback_tail": tb[-3:]})
            continue
        trace[sid] = sc.assemble_trace_frames(views, gtf)
    return trace, crashes


def score_trace(trace):
    """trace を pooled + per-suite で 8 層採点する(harness.score・変更なし)。"""
    spec = harness.canonical_metric_spec()

    def _score(sub):
        res = harness.score(sub, spec)
        return {
            "overall": res.overall(),
            "layers": {ly: res.layer_score(ly) for ly in sc.LAYERS},
            "n_scenarios": len(sub),
            "n_frames": sum(len(v) for v in sub.values()),
        }

    pooled = _score(trace)
    per_suite = {suite: _score(sub)
                 for suite, sub in sorted(sc.partition_by_suite(trace).items())}
    return pooled, per_suite


# ---------------------------------------------------------------------------
# rejection_acc(EVALUATION.md §7)
# ---------------------------------------------------------------------------
def rejection_tally(recs_viol, pso_cache, gt_cache):
    """契約違反シナリオを preflight して明示拒否率を集計する(config 非依存)。"""
    detail, rejected = [], 0
    by_reason = {}
    for r in recs_viol:
        sid = r["sid"]
        pf = sc.preflight_validate(pso_cache[sid], len(gt_cache[sid]))
        rj = not pf["ok"]
        rejected += 1 if rj else 0
        if rj:
            by_reason[pf["reason"]] = by_reason.get(pf["reason"], 0) + 1
        detail.append({"sid": sid, "rejected": rj,
                       "reason": pf["reason"], "detail": pf["detail"]})
    total = len(recs_viol)
    return {
        "total": total,
        "rejected": rejected,
        "rejection_acc": (rejected / total) if total else float("nan"),
        "by_reason": by_reason,
        "detail": detail,
    }


# ---------------------------------------------------------------------------
# 決定性チェック(std/eval 先頭 5 本を 2 回流して view 一致を確認)
# ---------------------------------------------------------------------------
def determinism_check(params, recs_eval_nonviol, pso_cache):
    sub = [r for r in recs_eval_nonviol if r["suite"] == "std"][:5]

    def _run():
        out = {}
        for r in sub:
            snaps = sc.prepare_snaps(pso_cache[r["sid"]])
            out[r["sid"]] = core.run_supreme_scenarios(
                {r["sid"]: snaps}, params, config=STRICT_OFF)[r["sid"]]
        return out

    a, b = _run(), _run()
    return {"subset": [r["sid"] for r in sub], "identical": (a == b)}


# ---------------------------------------------------------------------------
# JSON サニタイズ(NaN → None で valid JSON にする)
# ---------------------------------------------------------------------------
def sanitize(obj):
    if isinstance(obj, float):
        return None if math.isnan(obj) else obj
    if isinstance(obj, dict):
        return {k: sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize(v) for v in obj]
    return obj


def git_head(repo_dir):
    try:
        return subprocess.check_output(
            ["git", "-C", repo_dir, "rev-parse", "HEAD"],
            stderr=subprocess.DEVNULL).decode().strip()
    except Exception:  # pragma: no cover
        return None


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="situations_v1 能力評価(supreme8/F-015)")
    ap.add_argument("--data-root", default=sc.DEFAULT_DATA_ROOT)
    ap.add_argument("--out", default=_HERE, help="results.json の出力ディレクトリ")
    ap.add_argument("--configs", default="all",
                    help="カンマ区切り: N1,N2,N3,N3-std または all")
    ap.add_argument("--cache-dir", default=os.path.join(_HERE, "cache"),
                    help="学習段階の pickle キャッシュ(killed からの再開用)。空文字で無効化")
    args = ap.parse_args()
    if args.cache_dir == "":
        args.cache_dir = None

    if args.configs.strip().lower() == "all":
        configs = list(ALL_CONFIGS)
    else:
        configs = [c.strip() for c in args.configs.split(",") if c.strip()]
    for c in configs:
        if c not in ALL_CONFIGS:
            ap.error(f"未知の config: {c}(有効: {ALL_CONFIGS})")

    data_root = args.data_root
    out_path = os.path.join(args.out, "results.json")

    # --- 列挙・キャッシュ ---
    t0 = time.perf_counter()
    train_recs = sc.enumerate_scenarios(data_root, split="train")
    eval_recs = sc.enumerate_scenarios(data_root, split="eval")
    train_viol = [r for r in train_recs if r["contract_violation"]]
    train_nonviol = [r for r in train_recs if not r["contract_violation"]]
    eval_viol = [r for r in eval_recs if r["contract_violation"]]
    eval_nonviol = [r for r in eval_recs if not r["contract_violation"]]
    std_train_nonviol = [r for r in train_nonviol if r["suite"] == "std"]

    pso_cache, gt_cache = load_caches(train_recs + eval_recs)
    print(f"[enum] train={len(train_recs)}(viol {len(train_viol)}) "
          f"eval={len(eval_recs)}(viol {len(eval_viol)}) "
          f"load={time.perf_counter()-t0:.1f}s", flush=True)

    # rejection は config 非依存 → 一度だけ計算。
    rej_eval = rejection_tally(eval_viol, pso_cache, gt_cache)
    rej_train = rejection_tally(train_viol, pso_cache, gt_cache)
    print(f"[reject] eval acc={rej_eval['rejection_acc']:.3f} "
          f"({rej_eval['rejected']}/{rej_eval['total']}) "
          f"train acc={rej_train['rejection_acc']:.3f} "
          f"({rej_train['rejected']}/{rej_train['total']})", flush=True)

    # --- 共有学習(base_all=N2 かつ N3 の t3/scene 源。std は N3-std 用)---
    shared = {}

    def base_all():
        if "base_all" not in shared:
            snaps, gt = build_train_inputs(train_nonviol, pso_cache, gt_cache)
            ts = time.perf_counter()
            shared["base_all"] = core.fit_supreme(snaps, gt)
            shared["base_all_sec"] = time.perf_counter() - ts
            shared["train_all_snaps"], shared["train_all_gt"] = snaps, gt
            print(f"[fit] base_all(core.fit_supreme, {len(snaps)} scen) "
                  f"{shared['base_all_sec']:.1f}s", flush=True)
        return shared["base_all"]

    def base_std():
        if "base_std" not in shared:
            snaps, gt = build_train_inputs(std_train_nonviol, pso_cache, gt_cache)
            ts = time.perf_counter()
            shared["base_std"] = core.fit_supreme(snaps, gt)
            shared["base_std_sec"] = time.perf_counter() - ts
            shared["train_std_snaps"], shared["train_std_gt"] = snaps, gt
            print(f"[fit] base_std(core.fit_supreme, {len(snaps)} scen) "
                  f"{shared['base_std_sec']:.1f}s", flush=True)
        return shared["base_std"]

    descriptions = {
        "N1": "params=None(事前重みベースライン=NeuPSL 既定 + t3/scene 既定)",
        "N2": "core.fit_supreme(train_all)(既定 10 エポック T2・bilevel なし)",
        "N3": "ADR 0057 レシピ(PRIMARY): t3/scene=core.fit_supreme(train_all)、"
              "T2=基礎6(neupsl.fit)+bilevel2(neupsl.fit_bilevel・MLP凍結)、"
              "dataclasses.replace で T2 差替",
        "N3-std": "N3 と同レシピを std/train(80本)だけで学習(生成器スモークと可比)",
    }

    results = _load_existing(out_path)
    results["meta"] = {
        "feature": "F-015",
        "measurement_date": MEASUREMENT_DATE,
        "data_root": data_root,
        "data_repo_head": git_head(data_root),
        "engine_repo_head": git_head(_HERE),
        "strict_gt_conformance": False,
        "suites": list(sc.SUITES),
        "counts": {
            "train_total": len(train_recs), "train_violation": len(train_viol),
            "train_nonviolation": len(train_nonviol),
            "eval_total": len(eval_recs), "eval_violation": len(eval_viol),
            "eval_nonviolation": len(eval_nonviol),
            "std_train_nonviolation": len(std_train_nonviol),
        },
        "rejection_eval": rej_eval,
        "rejection_train_informational": rej_train,
        "note": "situations_v1 は world-first 土俵。coverage 系スコアと直接比較しない(別土俵)。"
                "引用は suite+split+測定日を併記。",
    }
    results.setdefault("configs", {})

    # --- config 実行 ---
    for name in configs:
        print(f"\n==== config {name} ====", flush=True)
        fit_info = {}
        t_fit = time.perf_counter()
        if name == "N1":
            params = None
            fit_info = {"train_scenarios": 0, "seconds": 0.0, "t2_choice": "default(prior)"}
        elif name == "N2":
            params = base_all()
            fit_info = {"train_scenarios": len(train_nonviol),
                        "seconds": shared["base_all_sec"],
                        "t2_choice": "core.fit_supreme(10ep, no bilevel)"}
        elif name == "N3":
            snaps, gt = build_train_inputs(train_nonviol, pso_cache, gt_cache)
            params, fit_info = build_handwired_params(
                "all", snaps, gt, len(train_nonviol), args.cache_dir)
        elif name == "N3-std":
            snaps, gt = build_train_inputs(std_train_nonviol, pso_cache, gt_cache)
            params, fit_info = build_handwired_params(
                "std", snaps, gt, len(std_train_nonviol), args.cache_dir)
        fit_info["fit_wall_seconds"] = time.perf_counter() - t_fit

        # --- eval ---
        t_ev = time.perf_counter()
        trace, crashes = run_eval(params, eval_nonviol, pso_cache, gt_cache)
        pooled, per_suite = score_trace(trace)
        eval_sec = time.perf_counter() - t_ev
        det = determinism_check(params, eval_nonviol, pso_cache)

        print(f"[{name}] pooled 8層平均={pooled['overall']:.4f}  "
              f"scen={pooled['n_scenarios']} frames={pooled['n_frames']}  "
              f"crashes={len(crashes)}  eval={eval_sec:.1f}s  "
              f"det.identical={det['identical']}", flush=True)
        for suite in sc.SUITES:
            if suite in per_suite:
                print(f"    {suite}: overall={per_suite[suite]['overall']:.4f} "
                      f"(n={per_suite[suite]['n_scenarios']})", flush=True)

        results["configs"][name] = {
            "description": descriptions[name],
            "fit": fit_info,
            "eval": {
                "n_scenarios": pooled["n_scenarios"],
                "n_frames": pooled["n_frames"],
                "pooled": pooled,
                "per_suite": per_suite,
                "seconds": eval_sec,
            },
            "rejection": {
                "eval": rej_eval,
                "train_informational": rej_train,
            },
            "crash_incidents": crashes,
            "n_crash_incidents": len(crashes),
            "determinism": det,
        }
        _write(out_path, results)

    print(f"\n[done] {out_path}", flush=True)


def _load_existing(path):
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:  # pragma: no cover
            pass
    return {}


def _write(path, results):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(sanitize(results), f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
