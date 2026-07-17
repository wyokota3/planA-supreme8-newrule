"""残る伸びしろの診断: mode の uncertain/side_rear_caution 署名 と t3 の内訳。eval split。"""
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
def fullgt(split):
    raw,g={},{}
    for d in sorted(glob.glob(os.path.join(DATA,split,"*"))):
        sid=os.path.basename(d)
        raw[sid]=[json.loads(l) for l in open(os.path.join(d,"pso_input.jsonl"),encoding="utf-8") if l.strip()]
        fr=yaml.safe_load(open(os.path.join(d,"ground_truth.yaml"),encoding="utf-8"))["frames"]
        g[sid]=[{"t2_mode":(f.get("t2") or {}).get("mode"),"t3_hypothesis":(f.get("t3") or {}).get("hypothesis"),
                 "risk_tier":(f.get("t0") or {}).get("risk_tier"),"t1_state":(f.get("t1") or {}).get("state"),
                 "t2_role":(f.get("t2") or {}).get("role"),"t2_relation":(f.get("t2") or {}).get("relation"),
                 "quality_regime":(f.get("t3") or {}).get("quality_regime"),"scene_regime":(f.get("t3") or {}).get("scene_regime")} for f in fr]
    return raw,g
tr_raw,tr_gt=fullgt("train"); ev_raw,ev_gt=fullgt("eval")

def sig(snap):
    tr=snap.get("tracks") or {}; allt=(tr.get("audio") or [])+(tr.get("humans") or [])+(tr.get("objects") or [])
    thetas=[t.get("theta_deg") for t in allt if t.get("theta_deg") is not None]
    sr=any(abs(t)>90 for t in thetas) if thetas else False
    ss=snap.get("scene_state") or {}
    return {"n_audio":len(tr.get("audio") or []),"n_hum":len(tr.get("humans") or []),"n_obj":len(tr.get("objects") or []),
            "side_rear":sr,"QoS":ss.get("QoS"),"links":[l.get("type") for l in (snap.get("links") or [])],
            "frame":snap.get("frame")}

print("=== uncertain GT フレームの証拠署名(eval) ===")
cu=Counter()
for sid in ev_raw:
    for i,gv in enumerate(ev_gt[sid]):
        if gv["t2_mode"]=="uncertain" and i<len(ev_raw[sid]):
            s=sig(ev_raw[sid][i]); cu[(s["n_audio"],s["n_hum"],s["n_obj"],s["side_rear"],s["frame"],tuple(sorted(set(s["links"]))))]+=1
for k,n in cu.most_common(8): print(f"  {n:4d}  n_aud/hum/obj={k[0]}/{k[1]}/{k[2]} side_rear={k[3]} frame={k[4]} links={k[5]}")

print("\n=== side_rear_caution GT フレームの署名 ===")
cs=Counter()
for sid in ev_raw:
    for i,gv in enumerate(ev_gt[sid]):
        if gv["t2_mode"]=="side_rear_caution" and i<len(ev_raw[sid]):
            s=sig(ev_raw[sid][i]); cs[(s["side_rear"],s["n_audio"],s["n_obj"],s["frame"])]+=1
for k,n in cs.most_common(8): print(f"  {n:4d}  side_rear={k[0]} n_aud={k[1]} n_obj={k[2]} frame={k[3]}")

# t3: supreme(fit) vs baseline 内訳 + 混同
sys.path.insert(0,SUP); from supreme import core
params=core.fit_supreme({s:norm(tr_raw[s],"PSO-Snapshot/1.4") for s in tr_raw}, tr_gt)
sv=core.run_supreme_scenarios({s:norm(ev_raw[s],"PSO-Snapshot/1.4") for s in ev_raw}, params)
sup_t3={s:[f.get("t3_hypothesis") for f in sv[s]] for s in ev_raw}
sys.path.insert(0,BASE); from ns_epi.runner import run_tick; from ns_epi.state import initial_state
bas_t3={}
for s,snaps in ev_raw.items():
    st=initial_state(); o=[]
    for fr in norm(snaps,"PSO-Snapshot/1.3"):
        st,epi=run_tick(st,fr); o.append(st["view"].get("t3_hypothesis") if (epi and "view" in st) else None)
    bas_t3[s]=o
br=sw=tie=0; conf=Counter()
for s in ev_raw:
    for i,gv in enumerate(ev_gt[s]):
        y=gv["t3_hypothesis"]
        if y is None: continue
        ps,pb=sup_t3[s][i],bas_t3[s][i]
        if ps!=y: conf[f"{y} -> {ps}"]+=1
        if ps==pb: tie+=1
        elif pb==y and ps!=y: br+=1
        elif ps==y and pb!=y: sw+=1
print(f"\n=== t3: supreme vs baseline 内訳 === 一致={tie} baseline正&supreme誤={br} supreme正&baseline誤={sw}")
print("=== t3: supreme 誤り top (gt->pred) ===")
for k,n in conf.most_common(8): print(f"  {n:4d}  {k}")
