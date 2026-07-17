"""t3 research: train 内 5-fold lineage-disjoint CV で t3 を測る(seal/eval 非接触)。
per-GT-class acc と混同で、学習層(conv/traffic/quiet)と規則層のどちらが落としているか診断。
"""
import copy, glob, json, os, sys
from collections import Counter, defaultdict
SUP=r"C:\work\L04-planA\supreme\planA-supreme2\src"
DATA="data/scenarios/coverage_v1"; O={"x_m":0.0,"y_m":0.0,"yaw_deg":0.0}
import yaml
sys.path.insert(0,SUP); from supreme import core

def norm(snaps):
    out=[]
    for s in snaps:
        s=copy.deepcopy(s); s.setdefault("origin",O); s["version"]="PSO-Snapshot/1.4"
        g=s.get("geom") or {}
        if g.get("min_TTC_s") is None: g["min_TTC_s"]=999.0
        g.setdefault("overlap_path",False); g.setdefault("lane_alignment",False); s["geom"]=g; out.append(s)
    return out
def load_train():
    raw,gt={},{}
    for d in sorted(glob.glob(os.path.join(DATA,"train","*"))):
        sid=os.path.basename(d)
        raw[sid]=norm([json.loads(l) for l in open(os.path.join(d,"pso_input.jsonl"),encoding="utf-8") if l.strip()])
        fr=yaml.safe_load(open(os.path.join(d,"ground_truth.yaml"),encoding="utf-8"))["frames"]
        gt[sid]=[{"risk_tier":(f.get("t0") or {}).get("risk_tier"),"t1_state":(f.get("t1") or {}).get("state"),
                  "t2_mode":(f.get("t2") or {}).get("mode"),"t2_role":(f.get("t2") or {}).get("role"),
                  "t2_relation":(f.get("t2") or {}).get("relation"),"t3_hypothesis":(f.get("t3") or {}).get("hypothesis"),
                  "quality_regime":(f.get("t3") or {}).get("quality_regime"),"scene_regime":(f.get("t3") or {}).get("scene_regime")} for f in fr]
    return raw,gt

def cv(raw,gt,k=5):
    sids=sorted(raw); fold={s:i%k for i,s in enumerate(sids)}
    perclass=defaultdict(lambda:[0,0]); conf=Counter(); c=t=0
    for h in range(k):
        tr=[s for s in sids if fold[s]!=h]; te=[s for s in sids if fold[s]==h]
        params=core.fit_supreme({s:raw[s] for s in tr},{s:gt[s] for s in tr})
        pv=core.run_supreme_scenarios({s:raw[s] for s in te},params)
        for s in te:
            for i,gv in enumerate(gt[s]):
                y=gv["t3_hypothesis"]
                if y is None: continue
                p=pv[s][i].get("t3_hypothesis"); t+=1; c+=int(p==y)
                perclass[y][1]+=1; perclass[y][0]+=int(p==y)
                if p!=y: conf[f"{y} -> {p}"]+=1
    return c/t, perclass, conf

if __name__=="__main__":
    raw,gt=load_train(); print(f"train={len(raw)} scenarios")
    acc,pc,conf=cv(raw,gt)
    print(f"\n=== t3 train-CV acc(現状) = {acc:.4f} ===")
    print("per-GT-class acc:")
    for cls,(cc,tt) in sorted(pc.items(),key=lambda x:-x[1][1]):
        print(f"  {cls:20s} {cc/tt:.3f}  (n={tt})")
    print("混同 top:")
    for kk,n in conf.most_common(10): print(f"  {n:4d}  {kk}")
