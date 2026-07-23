# -*- coding: utf-8 -*-
"""F-015 補助: 1 フレーム分の NeuPSL 実測トレースを決定的にダンプする。

architecture-explainer.html の「実測トレース例」パネル用。dump_frames.py と同じ
段階キャッシュ(cache/*.pkl)から学習済み N3 params を **そのまま読み込み**(再学習しない)、
eval の 1 シナリオを本番と全く同じ経路(core.run_supreme_scenarios(..., STRICT_OFF))で
実走させ、その内部で NeuPSL が実際に使った値を横取り(monkeypatch capture)して記録する。

捕捉する内容(1 フレーム):
  - 述語真理値: 観測述語 14 個 + ニューラル述語 12 個(_predicate_values の実出力)
  - ターゲット分布: 結合 MAP 解 y の Mode10 / Role6 / Rel6 = 22 値(単体)
  - argmax ラベル: mode / role / rel
  - ルール寄与 top: 当該フレームに接地したルールの w·viol²(解 y における違反量)上位

再学習しない根拠:
  - cache/all_t3scene.pkl(value = SupremeParams)と cache/all_t2final.pkl(value["t2"] =
    NeuPSLParams)を直接 unpickle し、build_handwired_params と同じく
    dataclasses.replace(t3scene, t2=t2final["t2"]) で params を組み立てる。
  - これらの pkl は frames-N3.json を生成した時と同一 manifest(engine_repo_head
    5b544318…)のもの。以後 src/supreme/* は無変更(docs/reports のみ変更)のため、
    現在のエンジンコードで再走させても frames-N3.json と数値一致する。
  - INTEGRITY: 捕捉した MAP 解の argmax(mode/role/rel)が frames-N3.json の当該
    フレーム pred と一致することを assert(不一致なら停止・数値を丸めない)。

選択規則(決定的):
  suite=emg・split=eval の非違反シナリオを sid 昇順に走らせ、
  「pred t2_mode == GT t2_mode == 'emergency' となるフレームを 1 つ以上もつ」
  最初のシナリオを採用。そのシナリオ内で当該条件を満たす **最小 index** のフレームを採る。
  → emg-alarm_while_degraded / emg-crowd_panic は該当フレーム無しでスキップされ、
     emg-emergency_passing-eval-02 の frame index 1(ts 0.5)が選ばれる。

使い方:
  python dump_neupsl_trace.py [--data-root PATH] [--cache-dir DIR] [--out DIR]
"""

from __future__ import annotations

import argparse
import copy
import dataclasses
import json
import os
import pickle
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(_HERE, "..", "..", "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from supreme import core, neupsl as neupsl_mod  # noqa: E402
import situations_common as sc  # noqa: E402
import run_supreme_situations as rsw  # noqa: E402

SYSTEM = "supreme8"
DUMP_CONFIG = "N3"
TARGET_SUITE = "emg"
TARGET_MODE = "emergency"


def load_cached_params(cache_dir):
    """段階キャッシュから N3 の学習済み params を直接読み込む(再学習しない)。"""
    def _load(name):
        with open(os.path.join(cache_dir, name), "rb") as f:
            return pickle.load(f)
    t3_blob = _load("all_t3scene.pkl")
    final_blob = _load("all_t2final.pkl")
    t3scene = t3_blob["value"]
    stage_c = final_blob["value"]
    params = dataclasses.replace(t3scene, t2=stage_c["t2"])
    prov = {
        "source": "cache/all_t3scene.pkl + cache/all_t2final.pkl (unpickled; no refit)",
        "t2final_manifest": final_blob.get("manifest"),
        "t3scene_manifest": t3_blob.get("manifest"),
        "guard_choice": stage_c.get("choice"),
        "guard": stage_c.get("guard"),
    }
    return params, prov


def _rule_formula(name, body, head):
    """RULES の (body, head) を可読な論理式文字列にする(図・パネル表示用)。"""
    def atom_str(atom, neg):
        if atom == "PREV_MODE":
            s = "Mode(f−1,m)"
        elif isinstance(atom, tuple):
            layer, cls = atom
            s = f"{layer.capitalize()}({cls})"
        else:
            s = str(atom)
        return ("¬" + s) if neg else s

    hl, hc = head
    if name == "t_persist_mode":
        return "Mode(f−1,m) → Mode(f,m)"
    body_s = " ∧ ".join(atom_str(a, n) for a, n in body) if body else "⊤"
    return f"{body_s} → {hl.capitalize()}({hc})"


def frame_rule_contributions(f, vals_seq, y, weights):
    """フレーム f に接地した各ルールの w·viol²(解 y における違反量)を返す。

    neupsl の内部関数(_rule_instances / _atom_value / FLAGS)をそのまま再利用する。
    エネルギー式 E += w·viol·(viol if p2 else 1) と同一の寄与量を再現する。
    """
    p2 = neupsl_mod.FLAGS["p2"]
    idx = neupsl_mod._IDX
    inst = neupsl_mod._rule_instances(len(y))
    # ルール名 -> (body, head) を引くための辞書(可読式生成用)
    body_by_name = {nm: (bd, hd) for nm, _w, bd, hd in neupsl_mod.RULES}

    agg = {}  # name -> {"w","viol","contribution","formula","head"}
    for name, inst_f, body, (hl, hi), prev in inst:
        if inst_f != f:
            continue
        w = weights[name]
        head_v = y[f][hl][hi]
        if prev is not None:
            pf, mi = prev
            body_v = y[pf]["mode"][mi]
        else:
            s = 0.0
            for atom, neg in body:
                v, _key = neupsl_mod._atom_value(atom, neg, f, vals_seq, y)
                s += v
            body_v = max(0.0, s - (len(body) - 1)) if body else 1.0
        viol = body_v - head_v
        if viol <= 0:
            continue
        contribution = w * viol * (viol if p2 else 1.0)
        rec = agg.get(name)
        if rec is None:
            bd, hd = body_by_name[name]
            agg[name] = {
                "rule": name,
                "w": w,
                "viol": viol,
                "contribution": contribution,
                "formula": _rule_formula(name, bd, hd),
                "head_layer": hl,
                "head_class_idx": hi,
            }
        else:
            # 時間持続(mode ごとに 10 接地)などは合算する
            rec["viol"] += viol
            rec["contribution"] += contribution
    ranked = sorted(agg.values(), key=lambda r: r["contribution"], reverse=True)
    return ranked


def build_trace(data_root, cache_dir):
    params, params_prov = load_cached_params(cache_dir)

    eval_recs = sc.enumerate_scenarios(data_root, split="eval")
    eval_emg = sorted(
        (r for r in eval_recs
         if r["suite"] == TARGET_SUITE and not r["contract_violation"]),
        key=lambda r: r["sid"],
    )

    # NeuPSL が実際に使った vals_seq と MAP 解 y を横取りする
    captured = {"calls": []}
    orig_map = neupsl_mod.map_inference

    def _patched_map(vals_seq, mparams, iters=160, margin_gt=None, init=None, prox=None):
        y = orig_map(vals_seq, mparams, iters=iters, margin_gt=margin_gt, init=init, prox=prox)
        captured["calls"].append((copy.deepcopy(vals_seq), copy.deepcopy(y)))
        return y

    chosen = None
    skipped = []
    try:
        neupsl_mod.map_inference = _patched_map
        for r in eval_emg:
            sid = r["sid"]
            pso = sc.load_pso_frames(r["dir"])
            gtf = sc.load_gt_frames(r["dir"])
            pf = sc.preflight_validate(pso, len(gtf))
            if not pf["ok"]:
                skipped.append((sid, "preflight_reject"))
                continue
            snaps = sc.prepare_snaps(pso)
            captured["calls"] = []
            views = core.run_supreme_scenarios(
                {sid: snaps}, params, config=rsw.STRICT_OFF)[sid]
            gt_views = [sc.gt_view(fr) for fr in gtf]
            # pred==GT=='emergency' の最小 index フレーム
            hit = None
            for i, vw in enumerate(views):
                if i >= len(gt_views):
                    break
                if vw["t2_mode"] == TARGET_MODE and gt_views[i].get("t2_mode") == TARGET_MODE:
                    hit = i
                    break
            if hit is None:
                skipped.append((sid, "no emergency==GT frame"))
                continue
            # このシナリオを採用。捕捉は 1 シナリオ=1 回の map_inference のはず
            assert len(captured["calls"]) == 1, (
                f"expected 1 map_inference call, got {len(captured['calls'])}")
            vals_seq, y = captured["calls"][0]
            assert len(vals_seq) == len(views), "vals_seq/views length mismatch"
            # ts は frames-N3.json と同じく GT フレーム由来(assemble_trace_frames と一致)
            ts = float(gtf[hit].get("ts", float(hit)))
            chosen = {
                "rec": r, "sid": sid, "frame": hit, "ts": ts,
                "views": views, "gt_views": gt_views,
                "vals_seq": vals_seq, "y": y, "gtf": gtf,
            }
            break
    finally:
        neupsl_mod.map_inference = orig_map

    if chosen is None:
        raise RuntimeError("no emg/eval scenario had a pred==GT=='emergency' frame")

    return params, params_prov, chosen, skipped


def assemble_output(params, params_prov, chosen, skipped, data_root):
    f = chosen["frame"]
    vals_seq = chosen["vals_seq"]
    y = chosen["y"]
    views = chosen["views"]
    gt_views = chosen["gt_views"]
    valf = vals_seq[f]

    MODES, ROLES, RELS = neupsl_mod.MODES, neupsl_mod.ROLES, neupsl_mod.RELS

    predicates = {p: valf[p] for p in neupsl_mod.PREDICATES}
    observed = {p: valf[p] for p in neupsl_mod.OBSERVED}

    dist = {
        "mode": {MODES[i]: y[f]["mode"][i] for i in range(len(MODES))},
        "role": {ROLES[i]: y[f]["role"][i] for i in range(len(ROLES))},
        "rel": {RELS[i]: y[f]["rel"][i] for i in range(len(RELS))},
    }
    argmax = {
        "mode": neupsl_mod._argmax(y[f]["mode"], MODES),
        "role": neupsl_mod._argmax(y[f]["role"], ROLES),
        "rel": neupsl_mod._argmax(y[f]["rel"], RELS),
    }

    weights = params.t2.weights
    rule_contrib = frame_rule_contributions(f, vals_seq, y, weights)

    # --- INTEGRITY: argmax が frames-N3.json / 現走行 view と一致することを検証 ---
    view = views[f]
    mismatches = []
    for layer, key in (("mode", "t2_mode"), ("role", "t2_role"), ("rel", "t2_relation")):
        if argmax[layer] != view[key]:
            mismatches.append((layer, argmax[layer], view[key]))
    if mismatches:
        raise AssertionError(
            "INTEGRITY: MAP argmax != engine view: " + "; ".join(
                f"{m[0]} argmax={m[1]} view={m[2]}" for m in mismatches))
    # 選択条件の再確認
    assert view["t2_mode"] == TARGET_MODE == gt_views[f].get("t2_mode"), \
        "chosen frame is not pred==GT==emergency"

    engine_head = rsw.git_head(_HERE)
    data_head = rsw.git_head(data_root)

    n_frames = len(views)
    out = {
        "meta": {
            "system": SYSTEM,
            "config": DUMP_CONFIG,
            "strict": False,
            "purpose": "architecture-explainer.html 実測トレース例(1 フレーム)",
            "selection_rule": (
                "suite=emg・eval 非違反を sid 昇順で走らせ、pred t2_mode==GT t2_mode=="
                "'emergency' のフレームをもつ最初のシナリオの、その条件を満たす最小 index フレーム。"),
            "sid": chosen["sid"],
            "suite": chosen["rec"]["suite"],
            "motif": chosen["rec"]["motif"],
            "frame_index": f,
            "frame_ts": chosen["ts"],
            "n_frames": n_frames,
            "engine_repo_head": engine_head,
            "data_repo_head": data_head,
            "params_provenance": params_prov,
            "skipped_scenarios": [{"sid": s, "reason": rz} for s, rz in skipped],
            "integrity": "MAP argmax == engine view == frames-N3.json pred (mode/role/rel)。",
        },
        "frame": {
            "ts": chosen["ts"],
            "observed": observed,
            "predicates": predicates,
            "target_distributions": dist,
            "argmax": argmax,
            "gt_t2": {
                "t2_mode": gt_views[f].get("t2_mode"),
                "t2_role": gt_views[f].get("t2_role"),
                "t2_relation": gt_views[f].get("t2_relation"),
            },
            "view_full": view,
            "gt_full": gt_views[f],
            "rule_contributions": rule_contrib,
        },
    }
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="1 フレームの NeuPSL 実測トレースを決定的にダンプする(N3・再学習なし)")
    ap.add_argument("--data-root", default=sc.DEFAULT_DATA_ROOT)
    ap.add_argument("--cache-dir", default=os.path.join(_HERE, "cache"))
    ap.add_argument("--out", default=_HERE, help="neupsl_trace-N3.json の出力ディレクトリ")
    args = ap.parse_args(argv)

    print(f"[dump_trace] system={SYSTEM} config={DUMP_CONFIG} data_root={args.data_root}")
    params, params_prov, chosen, skipped = build_trace(args.data_root, args.cache_dir)
    print(f"[dump_trace] skipped {len(skipped)} emg scenarios before match:")
    for s, rz in skipped:
        print(f"    - {s}: {rz}")
    print(f"[dump_trace] chosen sid={chosen['sid']} frame={chosen['frame']} ts={chosen['ts']}")

    out = assemble_output(params, params_prov, chosen, skipped, args.data_root)

    fr = out["frame"]
    print("[dump_trace] argmax:", fr["argmax"])
    print("[dump_trace] top rule contributions:")
    for rc in fr["rule_contributions"][:5]:
        print(f"    {rc['rule']:<18} w={rc['w']:<4} viol={rc['viol']:.4f} "
              f"contrib={rc['contribution']:.4f}  {rc['formula']}")

    out_path = os.path.join(args.out, "neupsl_trace-N3.json")
    with open(out_path, "w", encoding="utf-8") as fp:
        json.dump(out, fp, ensure_ascii=False, indent=2, allow_nan=False)
    print(f"[dump_trace] wrote {out_path}")


if __name__ == "__main__":
    main()
