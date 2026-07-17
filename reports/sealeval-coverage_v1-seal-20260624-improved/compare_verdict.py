"""F-013 封印評価(真値) — supreme2 vs baseline を coverage_v1/seal で項目別対比。

metric: EVALUATION.md §3 の 8層 global acc(= Σ正答 / Σ GT非null, 完全一致)。
拒否(None)フレームは該当システムの分母から除外(evaluate.py 規約)。
"""
import json
import os

OUT = r"C:\Users\R00507~1\AppData\Local\Temp\claude\C--work-L04-planA\b2e3b4be-249d-4b45-8a27-1ee8a7738643\scratchpad"
LAYERS = ["risk_tier", "t1_state", "t2_mode", "t2_role",
          "t2_relation", "t3_hypothesis", "quality_regime", "scene_regime"]
WEAK = {"t2_mode", "t2_relation", "t3_hypothesis", "scene_regime", "quality_regime"}
STRONG = {"risk_tier", "t1_state", "t2_role"}
DELTA = 0.02


def load(name):
    with open(os.path.join(OUT, name), encoding="utf-8") as f:
        return json.load(f)


def global_acc(pred, gt):
    """層別 global acc。返り値: {layer:(correct,total,acc)} と各システムの拒否frame数。"""
    res = {ly: [0, 0] for ly in LAYERS}
    rejected = 0
    for sid, gframes in gt.items():
        pframes = pred.get(sid, [])
        for i, gv in enumerate(gframes):
            pv = pframes[i] if i < len(pframes) else None
            if pv is None:
                rejected += 1
                continue
            for ly in LAYERS:
                gval = gv.get(ly)
                if gval is None:
                    continue            # GT null = 採点除外
                res[ly][1] += 1
                if pv.get(ly) == gval:
                    res[ly][0] += 1
    return {ly: (c, t, (c / t if t else float("nan"))) for ly, (c, t) in res.items()}, rejected


def main():
    gt = load("gt_seal.json")
    sup = load("pred_supreme.json")
    bas = load("pred_baseline.json")
    sA, sRej = global_acc(sup, gt)
    bA, bRej = global_acc(bas, gt)

    print(f"seal scenarios={len(gt)}  (supreme rejected frames={sRej}, baseline rejected={bRej})\n")
    hdr = f"{'layer':16s} {'kind':6s} {'baseline':>9s} {'supreme':>9s} {'Δ(sup-bas)':>11s}  verdict"
    print(hdr); print("-" * len(hdr))
    rows = []
    sup_avg = bas_avg = 0.0
    for ly in LAYERS:
        b = bA[ly][2]; s = sA[ly][2]; d = s - b
        kind = "weak" if ly in WEAK else "strong"
        if kind == "weak":
            v = "WIN" if d > DELTA else ("LOSE" if d < -DELTA else "draw")
        else:
            drop = b - s
            v = "maintained" if drop <= DELTA else "DEGRADED"
        rows.append((ly, kind, b, s, d, v))
        sup_avg += s; bas_avg += b
        print(f"{ly:16s} {kind:6s} {b:9.4f} {s:9.4f} {d:+11.4f}  {v}")
    sup_avg /= len(LAYERS); bas_avg /= len(LAYERS)
    print("-" * len(hdr))
    print(f"{'8層平均':14s} {'':6s} {bas_avg:9.4f} {sup_avg:9.4f} {sup_avg-bas_avg:+11.4f}")

    weak_rows = [r for r in rows if r[1] == "weak"]
    win = sum(1 for r in weak_rows if r[5] == "WIN")
    lose = sum(1 for r in weak_rows if r[5] == "LOSE")
    draw = sum(1 for r in weak_rows if r[5] == "draw")
    strong_deg = [r[0] for r in rows if r[1] == "strong" and r[5] == "DEGRADED"]
    print(f"\n弱い5項目: WIN {win} / draw {draw} / LOSE {lose}")
    print(f"強い3項目: {'全 maintained' if not strong_deg else 'DEGRADED=' + ','.join(strong_deg)}")
    goal = (win + draw == len(weak_rows)) and not strong_deg and win >= 1
    print(f"成功目標(弱5↑∧強維持): {'達成' if (win==len(weak_rows) and not strong_deg) else '部分/未達'}")

    out = {
        "seal_scenarios": len(gt), "delta_strong": DELTA,
        "per_layer": {ly: {"kind": ("weak" if ly in WEAK else "strong"),
                            "baseline": bA[ly][2], "supreme": sA[ly][2],
                            "delta": sA[ly][2] - bA[ly][2],
                            "baseline_n": bA[ly][1], "supreme_n": sA[ly][1],
                            "verdict": rows[LAYERS.index(ly)][5]} for ly in LAYERS},
        "overall": {"baseline": bas_avg, "supreme": sup_avg, "delta": sup_avg - bas_avg},
        "weak_summary": {"win": win, "draw": draw, "lose": lose},
        "strong_degraded": strong_deg,
        "baseline_rejected_frames": bRej, "supreme_rejected_frames": sRej,
    }
    with open(os.path.join(OUT, "verdict_seal.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("\nwrote verdict_seal.json")


if __name__ == "__main__":
    main()
