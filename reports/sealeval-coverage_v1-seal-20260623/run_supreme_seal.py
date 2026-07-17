"""F-013 封印評価(真値) — supreme2 を coverage_v1/train で学習し seal で予測。

- 入力: N04-scenario-contract@main の coverage_v1(train で fit, seal で評価)。
- supreme 本体は無変更(train_on_coverage.py と同じアダプタ規約)。
- 出力: pred_supreme.json {sid:[{layer:pred},...]} と gt_seal.json {sid:[{layer:gt or None},...]}。
"""
import glob
import json
import os
import sys

SUP_SRC = r"C:\work\L04-planA\supreme\planA-supreme2\src"
sys.path.insert(0, SUP_SRC)
import yaml  # noqa: E402
from supreme import core  # noqa: E402

DATA = r"C:\Users\R00507~1\AppData\Local\Temp\claude\C--work-L04-planA\b2e3b4be-249d-4b45-8a27-1ee8a7738643\scratchpad\data\scenarios\coverage_v1"
OUT = r"C:\Users\R00507~1\AppData\Local\Temp\claude\C--work-L04-planA\b2e3b4be-249d-4b45-8a27-1ee8a7738643\scratchpad"
_ORIGIN = {"x_m": 0.0, "y_m": 0.0, "yaw_deg": 0.0}
LAYERS = ["risk_tier", "t1_state", "t2_mode", "t2_role",
          "t2_relation", "t3_hypothesis", "quality_regime", "scene_regime"]


def load_snaps(d):
    with open(os.path.join(d, "pso_input.jsonl"), encoding="utf-8") as f:
        snaps = [json.loads(line) for line in f if line.strip()]
    for s in snaps:
        s.setdefault("origin", _ORIGIN)
        s["version"] = "PSO-Snapshot/1.4"
        g = s.get("geom") or {}
        if g.get("min_TTC_s") is None:
            g["min_TTC_s"] = 999.0
        g.setdefault("overlap_path", False)
        g.setdefault("lane_alignment", False)
        s["geom"] = g
    return snaps


def gt_view(fr):
    """8層 GT を取り出す。欠損/null は None(=採点除外)。"""
    t0, t1, t2, t3 = (fr.get(k) or {} for k in ("t0", "t1", "t2", "t3"))
    return {
        "risk_tier": t0.get("risk_tier"),
        "t1_state": t1.get("state"),
        "t2_mode": t2.get("mode"),
        "t2_role": t2.get("role"),
        "t2_relation": t2.get("relation"),
        "t3_hypothesis": t3.get("hypothesis"),
        "quality_regime": t3.get("quality_regime"),
        "scene_regime": t3.get("scene_regime"),
    }


def load_split(split):
    snaps, gts = {}, {}
    for d in sorted(glob.glob(os.path.join(DATA, split, "*"))):
        sid = os.path.basename(d)
        snaps[sid] = load_snaps(d)
        with open(os.path.join(d, "ground_truth.yaml"), encoding="utf-8") as f:
            gt = yaml.safe_load(f)
        gts[sid] = [gt_view(fr) for fr in gt["frames"]]
    return snaps, gts


def main():
    tr_snaps, tr_gt = load_split("train")
    se_snaps, se_gt = load_split("seal")
    print(f"train={len(tr_snaps)}  seal={len(se_snaps)}")

    # fit は train のみ(封印は学習に使わない)。GT は全8層を渡す。
    params = core.fit_supreme(tr_snaps, tr_gt)
    print("fit_supreme done")

    views = core.run_supreme_scenarios(se_snaps, params)
    pred = {sid: [{k: v.get(k) for k in LAYERS} for v in views[sid]] for sid in se_snaps}

    with open(os.path.join(OUT, "pred_supreme.json"), "w", encoding="utf-8") as f:
        json.dump(pred, f)
    with open(os.path.join(OUT, "gt_seal.json"), "w", encoding="utf-8") as f:
        json.dump(se_gt, f)
    # 長さ整合チェック
    bad = [sid for sid in se_snaps if len(pred[sid]) != len(se_gt[sid])]
    print("length-mismatch scenarios:", bad[:5], "count", len(bad))
    print("wrote pred_supreme.json + gt_seal.json")


if __name__ == "__main__":
    main()
