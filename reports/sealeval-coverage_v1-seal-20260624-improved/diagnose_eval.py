"""eval split(クリーン held-out)で supreme vs baseline を診断。seal は触らない。
- 層別 acc
- 負け層(mode/role/relation/t3)の混同 top と、role の supreme≠baseline 内訳。
"""
import copy
import glob
import json
import os
import sys
from collections import Counter

SUP_SRC = r"C:\work\L04-planA\supreme\planA-supreme2\src"
BASE_SRC = r"C:\work\L04-planA\supreme\external-data\planA-baseline\src"
DATA = r"C:\Users\R00507~1\AppData\Local\Temp\claude\C--work-L04-planA\b2e3b4be-249d-4b45-8a27-1ee8a7738643\scratchpad\data\scenarios\coverage_v1"
LAYERS = ["risk_tier", "t1_state", "t2_mode", "t2_role",
          "t2_relation", "t3_hypothesis", "quality_regime", "scene_regime"]
_ORIGIN = {"x_m": 0.0, "y_m": 0.0, "yaw_deg": 0.0}


def norm(snaps, version):
    out = []
    for s in snaps:
        s = copy.deepcopy(s)
        s.setdefault("origin", _ORIGIN)
        s["version"] = version
        g = s.get("geom") or {}
        if g.get("min_TTC_s") is None:
            g["min_TTC_s"] = 999.0
        g.setdefault("overlap_path", False)
        g.setdefault("lane_alignment", False)
        s["geom"] = g
        out.append(s)
    return out


def gt_view(fr):
    t0, t1, t2, t3 = (fr.get(k) or {} for k in ("t0", "t1", "t2", "t3"))
    return {"risk_tier": t0.get("risk_tier"), "t1_state": t1.get("state"),
            "t2_mode": t2.get("mode"), "t2_role": t2.get("role"),
            "t2_relation": t2.get("relation"), "t3_hypothesis": t3.get("hypothesis"),
            "quality_regime": t3.get("quality_regime"), "scene_regime": t3.get("scene_regime")}


def load(split):
    import yaml
    raw, gts = {}, {}
    for d in sorted(glob.glob(os.path.join(DATA, split, "*"))):
        sid = os.path.basename(d)
        with open(os.path.join(d, "pso_input.jsonl"), encoding="utf-8") as f:
            raw[sid] = [json.loads(l) for l in f if l.strip()]
        with open(os.path.join(d, "ground_truth.yaml"), encoding="utf-8") as f:
            gts[sid] = [gt_view(fr) for fr in yaml.safe_load(f)["frames"]]
    return raw, gts


def run_supreme(train_raw, train_gt, eval_raw):
    sys.path.insert(0, SUP_SRC)
    from supreme import core
    params = core.fit_supreme({s: norm(v, "PSO-Snapshot/1.4") for s, v in train_raw.items()}, train_gt)
    views = core.run_supreme_scenarios({s: norm(v, "PSO-Snapshot/1.4") for s, v in eval_raw.items()}, params)
    return {s: [{k: fr.get(k) for k in LAYERS} for fr in views[s]] for s in eval_raw}


def run_baseline(eval_raw):
    sys.path.insert(0, BASE_SRC)
    from ns_epi.runner import run_tick
    from ns_epi.state import initial_state
    pred = {}
    for s, snaps in eval_raw.items():
        st = initial_state(); out = []
        for fr in norm(snaps, "PSO-Snapshot/1.3"):
            st, epi = run_tick(st, fr)
            out.append({k: st["view"].get(k) for k in LAYERS} if (epi and "view" in st) else None)
        pred[s] = out
    return pred


def acc(pred, gt, layer):
    c = t = 0
    for s, gframes in gt.items():
        for i, gv in enumerate(gframes):
            y = gv.get(layer)
            if y is None or i >= len(pred[s]) or pred[s][i] is None:
                continue
            t += 1; c += int(pred[s][i].get(layer) == y)
    return c, t, (c / t if t else float("nan"))


def main():
    tr_raw, tr_gt = load("train")
    ev_raw, ev_gt = load("eval")
    print(f"train={len(tr_raw)} eval={len(ev_raw)}")
    sup = run_supreme(tr_raw, tr_gt, ev_raw)
    bas = run_baseline(ev_raw)

    print("\n=== eval split 層別 acc ===")
    print(f"{'layer':16s} {'baseline':>9s} {'supreme':>9s} {'Δ':>9s}")
    for ly in LAYERS:
        b = acc(bas, ev_gt, ly)[2]; s = acc(sup, ev_gt, ly)[2]
        print(f"{ly:16s} {b:9.4f} {s:9.4f} {s-b:+9.4f}")

    # 混同 top(gt -> supreme_pred)
    for ly in ("t2_mode", "t2_role", "t2_relation", "t3_hypothesis"):
        conf = Counter()
        for s, gframes in ev_gt.items():
            for i, gv in enumerate(gframes):
                y = gv.get(ly)
                if y is None or pred_none(sup, s, i):
                    continue
                p = sup[s][i].get(ly)
                if p != y:
                    conf[f"{y} -> {p}"] += 1
        print(f"\n=== {ly}: supreme 誤り top (gt -> pred) ===")
        for k, n in conf.most_common(6):
            print(f"  {n:4d}  {k}")

    # role の supreme≠baseline 内訳
    print("\n=== t2_role: supreme≠baseline の内訳 ===")
    both = base_right_sup_wrong = sup_right_base_wrong = both_wrong_diff = 0
    for s, gframes in ev_gt.items():
        for i, gv in enumerate(gframes):
            y = gv.get("t2_role")
            if y is None or pred_none(sup, s, i) or pred_none(bas, s, i):
                continue
            ps, pb = sup[s][i].get("t2_role"), bas[s][i].get("t2_role")
            if ps == pb:
                both += 1; continue
            if pb == y and ps != y:
                base_right_sup_wrong += 1
            elif ps == y and pb != y:
                sup_right_base_wrong += 1
            else:
                both_wrong_diff += 1
    print(f"  一致={both}  baseline正&supreme誤(=回帰)={base_right_sup_wrong}  "
          f"supreme正&baseline誤={sup_right_base_wrong}  両誤(別ラベル)={both_wrong_diff}")


def pred_none(pred, s, i):
    return i >= len(pred[s]) or pred[s][i] is None


if __name__ == "__main__":
    main()
