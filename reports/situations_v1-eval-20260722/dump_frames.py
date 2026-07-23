"""F-015 補助: situations_v1 eval の per-frame GT-vs-pred ダンプ(3-way viewer 用)。

run_supreme_situations.py(supreme8/NeuPSL)の enumeration/preflight/prepare_snaps/
gt_view/fit(N3 手配線レシピ・段階キャッシュ)と**全く同じコードパス**を import して
再利用する(ロジック複製なし)。results.json は一切変更・マージしない(provenance 分離。
dump は独立の成果物・cache/*.pkl も通常運転時と同じ manifest 検証で読む)。

出力(<out>/frames-N3.json)は 3 システム(planA-supreme2 / supreme8 / 将来分)共通の
viewer スキーマ:
  {"meta": {system, config, strict, engine_repo_head, data_repo_head, date, code_state},
   "scenarios": {sid: {suite, motif, frames: [[ts, gt8, pred8], ...]}},
   "violations": [{"sid","suite","injected_ops","detected_reason","detail"}, ...]}

scope: eval split・非違反 235 シナリオ(frames 付き)・違反 5 件は violations[] のみ。

injected_ops のみ situations_common.py に既存関数が無いため、本ファイル内で
scenario.yaml の corruption.ops を読む小さな補助関数を持つ(採点・preflight 判定には
一切使わない informational メタ・enumeration/preflight/gt_view 本体は再利用のまま)。

INTEGRITY ASSERTION: ダンプしたフレームから8層 pooled acc を再計算し、results.json の
N3 pooled 値(层別・overall)と一致することを検証する(不一致なら例外で停止・数値を丸めない)。

使い方:
  python dump_frames.py [--data-root PATH] [--out DIR] [--cache-dir DIR]
"""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(_HERE, "..", "..", "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from supreme import core, harness  # noqa: E402
import situations_common as sc  # noqa: E402
import run_supreme_situations as rsw  # noqa: E402

try:
    import yaml
except Exception:  # pragma: no cover - 環境依存
    yaml = None

SYSTEM = "supreme8"
DUMP_CONFIG = "N3"
MEASURE_DATE = rsw.MEASUREMENT_DATE

# 比較元(results.json の記録値・INTEGRITY ASSERTION 用)。数値は既存 results.json から
# 機械転記(丸めない・float 全精度)。ズレたら停止して調査する(paper over しない)。
_RECORDED_N3_POOLED = {
    "overall": 0.6256162188809465,
    "layers": {
        "risk_tier": 0.7012570865171309,
        "t1_state": 0.8198175992112399,
        "t2_mode": 0.3268424944540301,
        "t2_role": 0.7034754744885383,
        "t2_relation": 0.6586147399556322,
        "t3_hypothesis": 0.3497658368252403,
        "quality_regime": 0.963766329800345,
        "scene_regime": 0.4813901897954153,
    },
}
_TOL = 1e-9


def _code_state(repo_dir):
    try:
        out = subprocess.check_output(
            ["git", "-C", repo_dir, "status", "--porcelain"], stderr=subprocess.DEVNULL
        )
        return "dirty" if out.strip() else "clean"
    except Exception:
        return "unknown"


def _injected_ops(scenario_dir):
    """scenario.yaml の corruption.ops(注入 op 名の列)を返す(informational・非採点)。

    situations_common.py には無い補助読み(preflight/gt_view/enumeration 本体は不変)。
    形式は planA-supreme2 側の ScenarioMeta.ops と同一(dict なら 'op' キー・str ならそのまま)。
    """
    if yaml is None:
        return ()
    ypath = os.path.join(scenario_dir, "scenario.yaml")
    if not os.path.exists(ypath):
        return ()
    with open(ypath, encoding="utf-8") as f:
        y = yaml.safe_load(f) or {}
    corr = y.get("corruption") or {}
    return tuple(
        (o.get("op") if isinstance(o, dict) else str(o))
        for o in (corr.get("ops") or [])
    )


def _nan_to_none(x):
    return None if (isinstance(x, float) and math.isnan(x)) else x


def build_dump(data_root, cache_dir):
    """N3(ADR 0057 手配線レシピ)で eval を実走し dump 構造を作る。

    main() の N3 分岐と全く同じ関数呼び出し列(enumerate_scenarios→load_caches→
    build_train_inputs→cache_manifests→migrate_legacy_caches→build_handwired_params→
    preflight_validate→prepare_snaps→run_supreme_scenarios→assemble_trace_frames)。
    """
    train_recs = sc.enumerate_scenarios(data_root, split="train")
    eval_recs = sc.enumerate_scenarios(data_root, split="eval")
    train_viol = [r for r in train_recs if r["contract_violation"]]
    train_nonviol = [r for r in train_recs if not r["contract_violation"]]
    eval_viol = [r for r in eval_recs if r["contract_violation"]]
    eval_nonviol = [r for r in eval_recs if not r["contract_violation"]]

    pso_cache, gt_cache = rsw.load_caches(train_recs + eval_recs)
    print(f"[dump_frames] enum train={len(train_recs)}(viol {len(train_viol)}) "
          f"eval={len(eval_recs)}(viol {len(eval_viol)})", flush=True)

    train_all_snaps, train_all_gt, train_incidents = rsw.build_train_inputs(
        train_nonviol, pso_cache, gt_cache
    )
    print(f"[dump_frames] preflight train accepted={len(train_all_snaps)}/{len(train_nonviol)} "
          f"false_reject={len(train_incidents)}", flush=True)

    engine_head = rsw.git_head(_HERE)
    data_head = rsw.git_head(data_root)
    all_manifests = rsw.cache_manifests("all", engine_head, data_root, data_head)
    migration = rsw.migrate_legacy_caches(
        cache_dir, "all", rsw.build_t2_scens(train_all_snaps, train_all_gt), all_manifests
    )
    print(f"[dump_frames] cache-migration(all): {migration}", flush=True)
    if migration["training_blocked"]:
        raise RuntimeError(
            "legacy t2scens mismatch; caches were discarded and long training was not "
            "started for N3 (dump aborted; investigate before re-running)"
        )

    t_fit = __import__("time").perf_counter()
    params, fit_info = rsw.build_handwired_params(
        "all", train_all_snaps, train_all_gt, len(train_all_snaps), cache_dir, all_manifests
    )
    fit_info["fit_wall_seconds"] = __import__("time").perf_counter() - t_fit
    print(f"[dump_frames] fit(N3) done: {fit_info}", flush=True)

    scenarios = {}
    pooled_trace = {}
    n_false_reject = 0
    for r in eval_nonviol:
        sid = r["sid"]
        pso = pso_cache[sid]
        gtf = gt_cache[sid]
        pf = sc.preflight_validate(pso, len(gtf))
        if not pf["ok"]:
            n_false_reject += 1
            continue
        snaps = sc.prepare_snaps(pso)
        views = core.run_supreme_scenarios({sid: snaps}, params, config=rsw.STRICT_OFF)[sid]
        frames = sc.assemble_trace_frames(views, gtf)
        scenarios[sid] = {
            "suite": r["suite"],
            "motif": r["motif"],
            "frames": [[fr["ts"], fr["gt"], fr["view"]] for fr in frames],
        }
        pooled_trace[sid] = frames

    violations = []
    for r in eval_viol:
        sid = r["sid"]
        pf = sc.preflight_validate(pso_cache[sid], len(gt_cache[sid]))
        violations.append({
            "sid": sid,
            "suite": r["suite"],
            "injected_ops": list(_injected_ops(r["dir"])),
            "detected_reason": pf["reason"],
            "detail": pf["detail"],
        })

    return scenarios, violations, pooled_trace, n_false_reject, fit_info


def integrity_check(pooled_trace):
    spec = harness.canonical_metric_spec()
    res = harness.score(pooled_trace, spec)
    recomputed = {
        "overall": _nan_to_none(res.overall()),
        "layers": {L: _nan_to_none(res.layer_score(L)) for L in sc.LAYERS},
    }

    print("=== INTEGRITY ASSERTION (N3 pooled) ===")
    print(f"{'layer':<16} {'recomputed':>14} {'recorded':>14} {'diff':>12}")
    mismatches = []
    for L in sc.LAYERS:
        a, b = recomputed["layers"][L], _RECORDED_N3_POOLED["layers"][L]
        diff = abs(a - b)
        print(f"{L:<16} {a:>14.10f} {b:>14.10f} {diff:>12.2e}")
        if diff > _TOL:
            mismatches.append((L, a, b, diff))
    a, b = recomputed["overall"], _RECORDED_N3_POOLED["overall"]
    diff = abs(a - b)
    print(f"{'overall':<16} {a:>14.10f} {b:>14.10f} {diff:>12.2e}")
    if diff > _TOL:
        mismatches.append(("overall", a, b, diff))

    if mismatches:
        raise AssertionError(
            "INTEGRITY ASSERTION 不一致(recomputed vs results.json 記録値): "
            + "; ".join(f"{m[0]}: {m[1]!r} != {m[2]!r} (diff={m[3]!r})" for m in mismatches)
        )
    print("=== INTEGRITY ASSERTION: PASS(recomputed == recorded, tol=%.0e) ===" % _TOL)
    return recomputed


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="F-015 situations_v1 per-frame GT-vs-pred dump(N3・3-way viewer 用)"
    )
    ap.add_argument("--data-root", default=sc.DEFAULT_DATA_ROOT)
    ap.add_argument("--out", default=_HERE, help="frames-N3.json の出力ディレクトリ")
    ap.add_argument("--cache-dir", default=os.path.join(_HERE, "cache"),
                     help="学習段階の pickle キャッシュ(通常運転と同じ manifest 検証で読む)")
    args = ap.parse_args(argv)

    data_root = args.data_root
    engine_head = rsw.git_head(_HERE)
    data_head = rsw.git_head(data_root)
    code_state = _code_state(_HERE)

    print(f"[dump_frames] system={SYSTEM} config={DUMP_CONFIG} data_root={data_root}")
    print(f"[dump_frames] engine_repo_head={engine_head} code_state={code_state}")

    scenarios, violations, pooled_trace, n_false_reject, fit_info = build_dump(
        data_root, args.cache_dir
    )
    print(f"[dump_frames] scenarios(non-violation, frames)={len(scenarios)} "
          f"violations={len(violations)} false_reject={n_false_reject}")

    integrity_check(pooled_trace)

    meta = {
        "system": SYSTEM,
        "config": DUMP_CONFIG,
        "strict": False,
        "engine_repo_head": engine_head,
        "data_repo_head": data_head,
        "date": MEASURE_DATE,
        "code_state": code_state,
    }
    out = {"meta": meta, "scenarios": scenarios, "violations": violations}

    os.makedirs(args.out, exist_ok=True)
    out_path = os.path.join(args.out, "frames-N3.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, allow_nan=False)
    print(f"[dump_frames] wrote {out_path} "
          f"({sum(len(s['frames']) for s in scenarios.values())} frames)")


if __name__ == "__main__":
    main()
