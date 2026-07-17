"""F-005 実データ分析ランナー。

baseline trace (trace.json) と catalog 1.4.0 GT (ground_truth.yaml × 20件) を読み込み、
erroran ライブラリで弱い5項目のエラー分析を行い Markdown レポートを生成する。

使い方:
    python scripts/run_erroran.py [--trace <path>] [--gt-dir <path>] [--out <path>]

既定値:
    --trace  C:\\work\\L04-planA\\supreme\\external-data\\planA-baseline\\results\\trace\\trace.json
    --gt-dir C:\\work\\L04-planA\\supreme\\external-data\\n04-feat\\scenarios\\v021_core
    --out    reports/erroran-20260612-F005.md
"""

from __future__ import annotations

import argparse
import json
import os
import sys

# プロジェクト src を Python パスに追加（インストール不要で実行できるように）
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_SRC_DIR = os.path.join(os.path.dirname(_SCRIPT_DIR), "src")
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

try:
    import yaml
except ImportError:
    print("ERROR: pyyaml が必要です。pip install pyyaml>=6.0 でインストールしてください。", file=sys.stderr)
    sys.exit(1)

from supreme import datagov, erroran

# ---------------------------------------------------------------------------
# 定数
# ---------------------------------------------------------------------------

DEFAULT_TRACE = (
    r"C:\work\L04-planA\supreme\external-data\planA-baseline\results\trace\trace.json"
)
DEFAULT_GT_DIR = (
    r"C:\work\L04-planA\supreme\external-data\n04-feat\scenarios\v021_core"
)
DEFAULT_OUT = "reports/erroran-20260612-F005.md"

# 検算用 per_layer.json のパス（baseline 計算値との突合に使用）
_PER_LAYER_JSON = (
    r"C:\work\L04-planA\supreme\external-data\planA-baseline\results\l04-ours\per_layer.json"
)

# 弱い5項目の検算基準値（per_layer.json より）
_EXPECTED_ACC = {
    "t2_mode": 0.62381,
    "t2_relation": 0.747619,
    "t3_hypothesis": 0.585714,
    "quality_regime": 0.761905,
    "scene_regime": 0.528571,
}

# GT_SCHEMA.md 上は必須だが ns016-ns020 の ground_truth.yaml に存在しない
# t3 フィールドに対してデフォルト値を補完する。
# これらは erroran の突合対象外フィールド（弱い5項目突合には影響しない）。
_T3_DEFAULTS = {
    "scene_label": "unknown",
    "outdoor_prob": 0.5,
    "vehicle_present": False,
    "stability": 0.5,
    "next_beat": {"state": "unknown", "p": 0.5},
}

# ns016-ns020 は t2 の hazard / dynamics / episode が省略されているため
# 均等分布でデフォルト補完する（突合対象外フィールド）。
_T2_DIST_DEFAULTS = {
    "hazard": {
        "safe": round(1 / 3, 10),
        "caution": round(1 / 3, 10),
        "danger": round(1 / 3, 10),
    },
    "dynamics": {
        "approach": 0.2,
        "pass": 0.2,
        "depart": 0.2,
        "stop": 0.2,
        "idle": 0.2,
    },
    "episode": {
        "ongoing": round(1 / 3, 10),
        "ending": round(1 / 3, 10),
        "regime_change": round(1 / 3, 10),
    },
}


# ---------------------------------------------------------------------------
# catalog.yaml 読み込み・キーマッピング構築
# ---------------------------------------------------------------------------

def load_catalog(gt_dir: str) -> dict[str, dict]:
    """catalog.yaml を読み込み、dir_name -> {scenario_id, ground_truth_path} を返す。

    catalog.yaml の scenarios[].manifest_path からディレクトリ名を抽出し、
    trace.json のキー (例: "ns001_boot_sanity") → scenario_id の変換に使う。
    """
    catalog_path = os.path.join(gt_dir, "catalog.yaml")
    with open(catalog_path, "r", encoding="utf-8") as f:
        catalog = yaml.safe_load(f)

    mapping = {}  # dir_name -> {scenario_id, ground_truth_path}
    for entry in catalog.get("scenarios", []):
        manifest_path = entry.get("manifest_path", "")
        # "ns001_boot_sanity/scenario.yaml" -> "ns001_boot_sanity"
        dir_name = manifest_path.split("/")[0].strip()
        scenario_id = entry["scenario_id"]
        ground_truth_path = entry.get("ground_truth_path", "")
        mapping[dir_name] = {
            "scenario_id": scenario_id,
            "ground_truth_path": ground_truth_path,
        }
    return mapping


# ---------------------------------------------------------------------------
# ground_truth.yaml -> canonical record 変換
# ---------------------------------------------------------------------------

def _build_t3_frame(raw_t3: dict | None) -> dict:
    """GT の t3 フィールドを canonical t3 形式に変換・補完する。

    ns016-ns020 では scene_label / outdoor_prob / vehicle_present / stability /
    next_beat が省略されているため、_T3_DEFAULTS で補完する。
    """
    if raw_t3 is None:
        raw_t3 = {}
    t3 = dict(raw_t3)
    for key, default in _T3_DEFAULTS.items():
        if key not in t3:
            # dict 型のデフォルト値はコピーして共有を防ぐ
            t3[key] = dict(default) if isinstance(default, dict) else default
    return t3


def _build_canonical_frame(raw_frame: dict) -> dict:
    """ground_truth.yaml の1フレームを canonical GT frame dict に変換する。"""
    ts = raw_frame["ts"]
    raw_t0 = raw_frame.get("t0", {})
    raw_t1 = raw_frame.get("t1", {})
    raw_t2 = raw_frame.get("t2", {})
    raw_t3 = raw_frame.get("t3", {})

    return {
        "ts": float(ts),
        "t0": {
            "risk_tier": raw_t0.get("risk_tier"),
            "kind": raw_t0.get("kind"),
            "range_m": raw_t0.get("range_m"),
        },
        "t1": {
            "state": raw_t1.get("state", ""),
            "ttc_s": float(raw_t1.get("ttc_s") or 0.0),
            "min_range_m": float(raw_t1.get("min_range_m") or 0.0),
        },
        "t2": {
            "mode": dict(raw_t2.get("mode", {})),
            "relations": dict(raw_t2.get("relations", {})),
            "roles": dict(raw_t2.get("roles", {})),
            "hazard": dict(raw_t2.get("hazard", _T2_DIST_DEFAULTS["hazard"])),
            "dynamics": dict(raw_t2.get("dynamics", _T2_DIST_DEFAULTS["dynamics"])),
            "episode": dict(raw_t2.get("episode", _T2_DIST_DEFAULTS["episode"])),
        },
        "t3": _build_t3_frame(raw_t3),
    }


def ground_truth_to_canonical(
    gt_data: dict,
    scenario_id: str,
    rel_path: str,
) -> dict:
    """ground_truth.yaml の dict を canonical GT record に変換する。

    meta, gt, custom の3層構造を構築する。
    SPEC.md F-005 の仕様に従い meta フィールドを付与する:
      - source.repo / commit / path は仕様書固定値
      - parents=[], generation=0, parent_lineage_id=自身 (root 宣言)
      - split="train", gt_origin="ai_generated", registered_at="2026-06-12T00:00:00+09:00"

    gt: scenario_id / version / description / frames を ground_truth.yaml から変換。
    custom: ground_truth.yaml の custom フィールド（あれば）と、
            スキーマ外キー（meta/gt 以外のトップレベルキー）。
    """
    # --- meta 層 ---
    meta = {
        "scenario_id": scenario_id,
        "source": {
            "repo": "https://github.com/wyokota3/N04-scenario-contract.git",
            "commit": "a0b882215e4bd4320b878853fa23b30a0661baab",
            "path": rel_path,
        },
        "parents": [],
        "parent_lineage_id": scenario_id,
        "generation": 0,
        "split": "train",
        "gt_origin": "ai_generated",
        "registered_at": "2026-06-12T00:00:00+09:00",
    }

    # --- gt 層 ---
    raw_scenario_id = str(gt_data.get("scenario_id", scenario_id))
    version = str(gt_data.get("version", ""))
    description = str(gt_data.get("description", "")) if "description" in gt_data else ""

    timeline = gt_data.get("timeline", [])
    frames = [_build_canonical_frame(fr) for fr in timeline]

    gt_body = {
        "scenario_id": raw_scenario_id,
        "version": version,
        "description": description,
        "frames": frames,
    }

    # --- custom 層: ground_truth.yaml の custom + スキーマ外キー ---
    known_keys = {"scenario_id", "version", "description", "timeline", "custom"}
    extra_keys = {k: v for k, v in gt_data.items() if k not in known_keys}
    custom_from_gt = dict(gt_data.get("custom", {}) or {})
    custom = {**custom_from_gt, **extra_keys}

    return {
        "meta": meta,
        "gt": gt_body,
        "custom": custom,
    }


# ---------------------------------------------------------------------------
# trace のキー変換（dir_name -> scenario_id）
# ---------------------------------------------------------------------------

def remap_trace_keys(trace: dict, catalog_mapping: dict[str, dict]) -> tuple[dict, list[str]]:
    """trace のキー（dir_name）を catalog 由来の scenario_id に変換した新 dict を返す。

    変換できないキーは warnings に記録してスキップする。
    戻り値: (remapped_trace, warnings)
    """
    remapped = {}
    warnings = []
    for dir_name, frames in trace.items():
        if dir_name in catalog_mapping:
            sid = catalog_mapping[dir_name]["scenario_id"]
            remapped[sid] = frames
        else:
            warnings.append(
                f"WARNING: trace キー '{dir_name}' が catalog に存在しない。スキップ。"
            )
    return remapped, warnings


# ---------------------------------------------------------------------------
# メイン処理
# ---------------------------------------------------------------------------

def run(trace_path: str, gt_dir: str, out_path: str) -> None:
    print(f"[1/7] catalog.yaml を読み込みます: {gt_dir}")
    catalog_mapping = load_catalog(gt_dir)
    print(f"      シナリオ数: {len(catalog_mapping)}")

    # dir_name -> scenario_id の対応表を表示
    print("      catalog キーマッピング (dir_name -> scenario_id):")
    for dn, info in sorted(catalog_mapping.items()):
        print(f"        {dn} -> {info['scenario_id']}")

    print()
    print(f"[2/7] ground_truth.yaml を canonical record に変換・バリデーションします")
    canonical_records = []
    for dir_name, info in sorted(catalog_mapping.items()):
        scenario_id = info["scenario_id"]
        gt_rel_path = info["ground_truth_path"]
        gt_abs_path = os.path.join(gt_dir, gt_rel_path)

        with open(gt_abs_path, "r", encoding="utf-8") as f:
            gt_data = yaml.safe_load(f)

        # canonical 変換: rel_path は "scenarios/v021_core/<dir_name>"
        rel_path = f"scenarios/v021_core/{dir_name}"
        record = ground_truth_to_canonical(gt_data, scenario_id, rel_path)

        # datagov でバリデーション
        vr = datagov.validate_record(record)
        if vr.warnings:
            for w in vr.warnings:
                print(f"      WARNING [{scenario_id}]: {w}")
        if not vr.ok:
            print(f"ERROR: シナリオ '{scenario_id}' のバリデーション失敗。中断します。", file=sys.stderr)
            for e in vr.errors:
                print(f"       - {e}", file=sys.stderr)
            sys.exit(1)

        canonical_records.append(record)

    print(f"      変換・バリデーション完了: {len(canonical_records)} 件")

    print()
    print(f"[3/7] trace.json を読み込みます: {trace_path}")
    with open(trace_path, "r", encoding="utf-8") as f:
        raw_trace = json.load(f)
    print(f"      trace シナリオ数: {len(raw_trace)}, フレーム合計: {sum(len(v) for v in raw_trace.values())}")

    print()
    print("[3b]  trace キーを scenario_id に変換します（catalog 経由）")
    trace, remap_warnings = remap_trace_keys(raw_trace, catalog_mapping)
    for w in remap_warnings:
        print(f"      {w}")
    print(f"      変換後シナリオ数: {len(trace)}")

    print()
    print("[4/7] erroran.ingest を実行します")
    ingest_result = erroran.ingest(trace, canonical_records)
    if not ingest_result.ok:
        print(
            f"ERROR: ingest 不整合。中断します。\n"
            f"  mismatches: {len(ingest_result.mismatches)} 件\n"
            f"  missing_frames: {len(ingest_result.missing_frames)} 件\n"
            f"  extra_frames: {len(ingest_result.extra_frames)} 件",
            file=sys.stderr,
        )
        # 先頭20件を表示
        for m in ingest_result.mismatches[:20]:
            print(
                f"  [mismatch] scenario_id={m['scenario_id']} ts={m['ts']} "
                f"layer={m['layer']} trace_gt={m['trace_gt']!r} canonical={m['canonical']}",
                file=sys.stderr,
            )
        for m in ingest_result.missing_frames[:20]:
            print(f"  [missing] scenario_id={m['scenario_id']} ts={m['ts']}", file=sys.stderr)
        for m in ingest_result.extra_frames[:20]:
            print(f"  [extra] scenario_id={m['scenario_id']} ts={m['ts']}", file=sys.stderr)
        sys.exit(1)
    print(f"      ingest: OK ({sum(len(v) for v in trace.values())} フレーム整合)")

    print()
    print("[5/7] erroran.analyze を実行します")
    analysis = erroran.analyze(trace, canonical_records)

    weak5 = ["t2_mode", "t2_relation", "t3_hypothesis", "quality_regime", "scene_regime"]
    print()
    print("--- 弱い5項目 accuracy ---")

    # per_layer.json を読み込んで検算
    with open(_PER_LAYER_JSON, "r", encoding="utf-8") as f:
        per_layer_ref = json.load(f)

    diff_count = 0
    acc_results = {}
    for layer in weak5:
        acc = analysis.accuracy(layer)
        acc_results[layer] = acc
        expected = _EXPECTED_ACC[layer]
        diff = acc - expected
        diff_str = f"{diff:+.6f}"
        match_str = "OK" if abs(diff) < 1e-5 else f"DIFF({diff_str})"
        print(f"  {layer:25s}: acc={acc:.6f}  per_layer={expected:.6f}  diff={diff_str}  [{match_str}]")
        if abs(diff) >= 1e-5:
            diff_count += 1

    print()
    if diff_count == 0:
        print("  突合結果: OK - 全5項目が per_layer.json と一致 (変換チェーン全体の正しさの証明)")
    else:
        print(f"  突合結果: 不整合 {diff_count} 項目が per_layer.json と差あり")

    print()
    print("--- 各項目の混同行列・上位誤りパターン (GT->予測, 件数上位3) ---")
    for layer in weak5:
        cm = analysis.confusion_matrix(layer)
        error_frames = analysis.error_frames(layer)
        print(f"\n  [{layer}]  accuracy={acc_results[layer]:.4f}  errors={len(error_frames)}")

        # 誤りパターン集計 (gt != pred)
        counts: dict = {}
        for fr in error_frames:
            pair = (fr["gt"], fr["pred"])
            counts[pair] = counts.get(pair, 0) + 1

        if not counts:
            print("    誤りパターン: なし")
        else:
            top3 = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:3]
            for (gt_cls, pred_cls), cnt in top3:
                print(f"    gt={gt_cls} -> pred={pred_cls}: {cnt} 件")

    print()
    print("[6/7] erroran.generate_report を実行します")
    report_md = erroran.generate_report(trace, canonical_records)

    print(f"[7/7] レポートを書き出します: {out_path}")
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report_md)
    print(f"      出力完了: {out_path}")


# ---------------------------------------------------------------------------
# エントリポイント
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="F-005 実データ分析ランナー: baseline trace × GT で erroran を実行する"
    )
    parser.add_argument(
        "--trace",
        default=DEFAULT_TRACE,
        help=f"trace.json のパス (既定: {DEFAULT_TRACE})",
    )
    parser.add_argument(
        "--gt-dir",
        default=DEFAULT_GT_DIR,
        help=f"catalog.yaml を含む GT ディレクトリ (既定: {DEFAULT_GT_DIR})",
    )
    parser.add_argument(
        "--out",
        default=DEFAULT_OUT,
        help=f"出力 Markdown パス (既定: {DEFAULT_OUT})",
    )
    args = parser.parse_args()
    run(args.trace, args.gt_dir, args.out)


if __name__ == "__main__":
    main()
