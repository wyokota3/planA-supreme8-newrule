"""F-013 封印評価(真値) — planA-baseline(ns_epi) を coverage_v1/seal で実走。

- baseline 本体(src/ns_epi)は無変更。evaluate.py と同じ駆動:
  state=initial_state(); state,_=run_tick(state, frame); pred=state["view"]。
- 出力: pred_baseline.json {sid:[{layer:pred},...]}(seal の各フレーム)。
"""
import glob
import json
import os
import sys

BASE_SRC = r"C:\work\L04-planA\supreme\external-data\planA-baseline\src"
sys.path.insert(0, BASE_SRC)
from ns_epi.runner import run_tick          # noqa: E402
from ns_epi.state import initial_state      # noqa: E402

DATA = r"C:\Users\R00507~1\AppData\Local\Temp\claude\C--work-L04-planA\b2e3b4be-249d-4b45-8a27-1ee8a7738643\scratchpad\data\scenarios\coverage_v1"
OUT = r"C:\Users\R00507~1\AppData\Local\Temp\claude\C--work-L04-planA\b2e3b4be-249d-4b45-8a27-1ee8a7738643\scratchpad"
LAYERS = ["risk_tier", "t1_state", "t2_mode", "t2_role",
          "t2_relation", "t3_hypothesis", "quality_regime", "scene_regime"]


_ORIGIN = {"x_m": 0.0, "y_m": 0.0, "yaw_deg": 0.0}


def normalize(snaps):
    """supreme アダプタと同一の入力正規化。ただし baseline gate が知る
    version 'PSO-Snapshot/1.3' は維持(1.4 にすると未知 version で拒否される)。"""
    for s in snaps:
        s.setdefault("origin", _ORIGIN)        # gate required(coverage_v1 は欠落)
        g = s.get("geom") or {}
        if g.get("min_TTC_s") is None:
            g["min_TTC_s"] = 999.0
        g.setdefault("overlap_path", False)
        g.setdefault("lane_alignment", False)
        s["geom"] = g
    return snaps


def run_scenario(snaps):
    """evaluate.py と同一規約: epi=[] か view 無しの拒否フレームは None(採点除外)。"""
    snaps = normalize(snaps)
    state = initial_state()
    out = []
    nrej = 0
    for frame in snaps:
        state, epi = run_tick(state, frame)
        if not epi or "view" not in state:
            out.append(None)
            nrej += 1
        else:
            view = state["view"]
            out.append({k: view.get(k) for k in LAYERS})
    return out, nrej


def main():
    pred = {}
    nframes = nrej_total = 0
    for d in sorted(glob.glob(os.path.join(DATA, "seal", "*"))):
        sid = os.path.basename(d)
        with open(os.path.join(d, "pso_input.jsonl"), encoding="utf-8") as f:
            snaps = [json.loads(line) for line in f if line.strip()]
        pred[sid], nrej = run_scenario(snaps)
        nframes += len(snaps)
        nrej_total += nrej
    with open(os.path.join(OUT, "pred_baseline.json"), "w", encoding="utf-8") as f:
        json.dump(pred, f)
    s0 = sorted(pred)[0]
    first_view = next((v for v in pred[s0] if v is not None), None)
    print(f"seal scenarios={len(pred)} frames={nframes} rejected(view無し)={nrej_total} "
          f"({100*nrej_total/nframes:.1f}%)")
    print(f"sample {s0} first non-rejected view = {first_view}")
    print("wrote pred_baseline.json")


if __name__ == "__main__":
    main()
