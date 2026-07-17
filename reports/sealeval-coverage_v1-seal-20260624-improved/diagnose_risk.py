"""risk_tier(両モデル同一)の誤分類を入力信号と突き合わせる。eval。
特に min_TTC_s=None フレームの GT 分布と、danger/caution 取りこぼしの原因を見る。
"""
import copy, glob, json, os, sys
from collections import Counter, defaultdict
SUP=r"C:\work\L04-planA\supreme\planA-supreme2\src"; DATA="data/scenarios/coverage_v1"; O={"x_m":0.0,"y_m":0.0,"yaw_deg":0.0}
import yaml; sys.path.insert(0,SUP); from supreme import core
def norm(snaps):
    out=[]
    for s in snaps:
        s=copy.deepcopy(s); s.setdefault("origin",O); s["version"]="PSO-Snapshot/1.4"
        g=s.get("geom") or {}
        if g.get("min_TTC_s") is None: g["min_TTC_s"]=999.0
        g.setdefault("overlap_path",False); g.setdefault("lane_alignment",False); s["geom"]=g; out.append(s)
    return out
def load():
    raw,gt,rawsnaps={},{},{}
    for d in sorted(glob.glob(os.path.join(DATA,"eval","*"))):
        sid=os.path.basename(d)
        snaps=[json.loads(l) for l in open(os.path.join(d,"pso_input.jsonl"),encoding="utf-8") if l.strip()]
        rawsnaps[sid]=snaps; raw[sid]=norm(snaps)
        fr=yaml.safe_load(open(os.path.join(d,"ground_truth.yaml"),encoding="utf-8"))["frames"]
        gt[sid]=[{"risk_tier":(f.get("t0") or {}).get("risk_tier")} for f in fr]
    return raw,gt,rawsnaps
raw,gt,rawsnaps=load()
fg={}
for d in sorted(glob.glob(os.path.join(DATA,"eval","*"))):
    sid=os.path.basename(d); fr=yaml.safe_load(open(os.path.join(d,"ground_truth.yaml"),encoding="utf-8"))["frames"]
    fg[sid]=[{"risk_tier":(f.get("t0") or {}).get("risk_tier")} for f in fr]
# fit on train for run (risk は学習非依存だが API 上 params 要)
import glob as g2
tr_raw,tr_gt={},{}
for d in sorted(glob.glob(os.path.join(DATA,"train","*"))):
    sid=os.path.basename(d); tr_raw[sid]=norm([json.loads(l) for l in open(os.path.join(d,"pso_input.jsonl"),encoding="utf-8") if l.strip()])
    fr=yaml.safe_load(open(os.path.join(d,"ground_truth.yaml"),encoding="utf-8"))["frames"]
    tr_gt[sid]=[{"risk_tier":(f.get("t0") or {}).get("risk_tier"),"t1_state":(f.get("t1") or {}).get("state"),"t2_mode":(f.get("t2") or {}).get("mode"),"t2_role":(f.get("t2") or {}).get("role"),"t2_relation":(f.get("t2") or {}).get("relation"),"t3_hypothesis":(f.get("t3") or {}).get("hypothesis"),"quality_regime":(f.get("t3") or {}).get("quality_regime"),"scene_regime":(f.get("t3") or {}).get("scene_regime")} for f in fr]
params=core.fit_supreme(tr_raw,tr_gt)
sv=core.run_supreme_scenarios(raw,params)
conf=Counter(); none_gt=Counter(); have_gt=Counter(); c=t=0
miss_danger=[]
for sid in raw:
    for i,gv in enumerate(gt[sid]):
        y=gv["risk_tier"]; p=sv[sid][i].get("risk_tier"); t+=1; c+=int(p==y)
        if p!=y: conf[f"{y} -> {p}"]+=1
        gm=(rawsnaps[sid][i].get("geom") or {}).get("min_TTC_s")
        if gm is None: none_gt[y]+=1
        else: have_gt[y]+=1
        if y=="danger" and p!=y and len(miss_danger)<8:
            au=[(a.get("type"),a.get("r_m")) for a in (rawsnaps[sid][i].get("tracks") or {}).get("audio") or []]
            miss_danger.append((sid,i,"pred="+str(p),"min_TTC="+str(gm),"audio="+str(au)))
print(f"risk_tier acc = {c/t:.4f}")
print("混同 top:")
for k,n in conf.most_common(8): print(f"  {n:4d}  {k}")
print(f"\nmin_TTC_s=None フレームの GT 分布: {dict(none_gt)}")
print(f"min_TTC_s=有 フレームの GT 分布: {dict(have_gt)}")
print("\ndanger 取りこぼしサンプル:")
for m in miss_danger: print("  ",m)
