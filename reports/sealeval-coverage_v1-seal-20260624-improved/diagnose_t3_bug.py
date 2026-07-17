"""conv_participating->alert_required の機序特定。eval。
GT t3=conv_participating ∧ supreme t3=alert_required のフレームで、
supreme mode / baseline mode / baseline t3 を突き合わせる。
"""
import copy, glob, json, os, sys
from collections import Counter
SUP=r"C:\work\L04-planA\supreme\planA-supreme2\src"; BASE=r"C:\work\L04-planA\supreme\external-data\planA-baseline\src"
DATA="data/scenarios/coverage_v1"; O={"x_m":0.0,"y_m":0.0,"yaw_deg":0.0}
import yaml
def norm(snaps,v):
    out=[]
    for s in snaps:
        s=copy.deepcopy(s); s.setdefault("origin",O); s["version"]=v
        g=s.get("geom") or {}
        if g.get("min_TTC_s") is None: g["min_TTC_s"]=999.0
        g.setdefault("overlap_path",False); g.setdefault("lane_alignment",False); s["geom"]=g; out.append(s)
    return out
def load(split):
    raw,g={},{}
    for d in sorted(glob.glob(os.path.join(DATA,split,"*"))):
        sid=os.path.basename(d)
        raw[sid]=[json.loads(l) for l in open(os.path.join(d,"pso_input.jsonl"),encoding="utf-8") if l.strip()]
        fr=yaml.safe_load(open(os.path.join(d,"ground_truth.yaml"),encoding="utf-8"))["frames"]
        g[sid]=[{"t3":(f.get("t3") or {}).get("hypothesis"),"mode":(f.get("t2") or {}).get("mode"),
                 "risk":(f.get("t0") or {}).get("risk_tier")} for f in fr]
    return raw,g
tr_raw,tr_gtfull=load("train"); ev_raw,ev_gt=load("eval")
# full GT for fit
def fg(split):
    g={}
    for d in sorted(glob.glob(os.path.join(DATA,split,"*"))):
        sid=os.path.basename(d); fr=yaml.safe_load(open(os.path.join(d,"ground_truth.yaml"),encoding="utf-8"))["frames"]
        g[sid]=[{"risk_tier":(f.get("t0") or {}).get("risk_tier"),"t1_state":(f.get("t1") or {}).get("state"),
                 "t2_mode":(f.get("t2") or {}).get("mode"),"t2_role":(f.get("t2") or {}).get("role"),
                 "t2_relation":(f.get("t2") or {}).get("relation"),"t3_hypothesis":(f.get("t3") or {}).get("hypothesis"),
                 "quality_regime":(f.get("t3") or {}).get("quality_regime"),"scene_regime":(f.get("t3") or {}).get("scene_regime")} for f in fr]
    return g
sys.path.insert(0,SUP); from supreme import core
params=core.fit_supreme({s:norm(tr_raw[s],"PSO-Snapshot/1.4") for s in tr_raw}, fg("train"))
sv=core.run_supreme_scenarios({s:norm(ev_raw[s],"PSO-Snapshot/1.4") for s in ev_raw}, params)
sup={s:[{"t3":f.get("t3_hypothesis"),"mode":f.get("t2_mode")} for f in sv[s]] for s in ev_raw}
sys.path.insert(0,BASE); from ns_epi.runner import run_tick; from ns_epi.state import initial_state
bas={}
for s,snaps in ev_raw.items():
    st=initial_state(); o=[]
    for fr in norm(snaps,"PSO-Snapshot/1.3"):
        st,epi=run_tick(st,fr)
        o.append({"t3":st["view"].get("t3_hypothesis"),"mode":st["view"].get("t2_mode")} if (epi and "view" in st) else {"t3":None,"mode":None})
    bas[s]=o
# 対象: GT t3=conv_participating ∧ supreme t3=alert_required
sup_mode=Counter(); bas_mode=Counter(); bas_t3=Counter(); risk_c=Counter(); n=0
for s in ev_raw:
    for i,gv in enumerate(ev_gt[s]):
        if gv["t3"]=="conv_participating" and sup[s][i]["t3"]=="alert_required":
            n+=1; sup_mode[sup[s][i]["mode"]]+=1; bas_mode[bas[s][i]["mode"]]+=1
            bas_t3[bas[s][i]["t3"]]+=1; risk_c[gv["risk"]]+=1
print(f"対象フレーム(GT=conv_participating ∧ supreme t3=alert_required): {n}")
print("  supreme mode:", dict(sup_mode))
print("  baseline mode:", dict(bas_mode))
print("  baseline t3 :", dict(bas_t3))
print("  GT risk_tier:", dict(risk_c))
