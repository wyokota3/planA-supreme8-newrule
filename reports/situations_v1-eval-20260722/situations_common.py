"""F-015: situations_v1 能力評価アダプタの純ロジック(importable)。

world-first 生成の situations_v1 スイート群(std/emg/crw/bst/dcp/crp・各 train80/eval40)を
supreme8(NeuPSL エンジン)へ流すためのアダプタ側ロジックだけを持つ。**src/supreme/*.py は
一切変更しない**(ADR 0050 の strict ゲート・core.py のテスト規律を尊重し、検証はアダプタ
ローカルで行う=ADR 0058)。

本モジュールが提供するもの(すべて決定的・乱数/時刻なし):
  - enumerate_scenarios : manifest.jsonl 走査(無ければ dir walk)でシナリオを列挙。
  - load_pso_frames / load_gt_frames : 生フレーム読込(version は書き換えない)。
  - gt_view              : ラベル形 GT(format: label)→ 8 層採点 view(hazard/dynamics は無視)。
  - preflight_validate   : engine 実行**前**の契約検証。version 接頭辞(書換なし)・ts 単調・
                           tracks.audio/humans/objects の型・PSO/GT フレーム数一致を検査し、
                           構造化 verdict(ok / rejected + reason)を返す。
  - prepare_snaps        : 非違反シナリオの geom 欠落補完(min_TTC_s=999.0)。version 不変。
  - assemble_trace_frames: engine views + 生 GT フレーム → harness.score 用のフレーム列。
                           長さ不一致は切り詰めず例外にする。
  - partition_by_suite   : trace を suite 別に分割(per-suite 採点用)。

契約違反(corruption.contract_violation: true)シナリオは 8 層採点から除外し、preflight で
明示拒否できたかを rejection_acc(EVALUATION.md §7)として別採点する。

依存: stdlib(glob/json/os) + pyyaml(GT 読込のみ)。src/supreme への依存はここには無い。
"""

from __future__ import annotations

import glob
import json
import os

try:  # pyyaml は analysis extra。GT 読込にのみ使う。
    import yaml
except Exception:  # pragma: no cover - 環境依存
    yaml = None


# データルート既定(read-only 外部データ・絶対に書き換えない)。--data-root で上書き可。
DEFAULT_DATA_ROOT = (
    r"C:\work\_audit-harness-retrofit\otokankyo-scenario-contract"
    r"\scenarios\situations_v1"
)

SUITES = ("std", "emg", "crw", "bst", "dcp", "crp")

# 採点 8 層(harness の _CANONICAL_SCORED_LAYERS と同順)。
LAYERS = (
    "risk_tier", "t1_state", "t2_mode", "t2_role",
    "t2_relation", "t3_hypothesis", "quality_regime", "scene_regime",
)

# core._validate_snapshot と同じ受理接頭辞(1.3/1.4 とも startswith で通る)。
_SNAPSHOT_PREFIX = "PSO-Snapshot/"

# 契約違反の分類(EVALUATION.md §7 / situations_v1 README §5 crp)。
REJECT_REASONS = (
    "bad_version", "ts_regression", "frame_count_mismatch", "type_break", "other",
)


# ---------------------------------------------------------------------------
# 列挙(manifest.jsonl 優先・無ければ dir walk)
# ---------------------------------------------------------------------------
def suite_of(sid: str) -> str:
    """scenario_id 先頭の suite タグ(例 'crp-violation-eval-02' → 'crp')。"""
    return sid.split("-", 1)[0]


def enumerate_scenarios(data_root=DEFAULT_DATA_ROOT, split=None, suites=SUITES):
    """situations_v1 のシナリオを列挙して決定的順序のレコード列で返す。

    優先: 各 suite の manifest.jsonl(meta.scenario_id / meta.split / suite / motif /
    contract_violation を持つ)。manifest が無ければ dir walk + scenario.yaml で復元する。

    Args:
        data_root: situations_v1 ルート(<root>/<suite>/{train,eval}/<sid>/)。
        split    : 'train' / 'eval' で絞る(None は両方)。
        suites   : 対象 suite タプル。

    Returns:
        [{"sid","suite","split","motif","contract_violation":bool,"dir"}, ...]
        (suite, split, sid の昇順で決定的にソート)。
    """
    recs = []
    for suite in suites:
        mpath = os.path.join(data_root, suite, "manifest.jsonl")
        if os.path.exists(mpath):
            recs.extend(_enum_from_manifest(mpath, data_root, suite, split))
        else:  # フォールバック: dir walk
            recs.extend(_enum_from_walk(data_root, suite, split))
    recs.sort(key=lambda r: (r["suite"], r["split"], r["sid"]))
    return recs


def _enum_from_manifest(mpath, data_root, suite, split):
    out = []
    with open(mpath, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            m = json.loads(line)
            meta = m.get("meta", {}) or {}
            sid = meta.get("scenario_id")
            sp = meta.get("split")
            if sid is None or sp is None:
                continue
            if split is not None and sp != split:
                continue
            out.append({
                "sid": sid,
                "suite": m.get("suite", suite),
                "split": sp,
                "motif": m.get("motif"),
                "contract_violation": bool(m.get("contract_violation", False)),
                "dir": os.path.join(data_root, suite, sp, sid),
            })
    return out


def _enum_from_walk(data_root, suite, split):
    out = []
    splits = ("train", "eval") if split is None else (split,)
    for sp in splits:
        base = os.path.join(data_root, suite, sp)
        if not os.path.isdir(base):
            continue
        for d in sorted(glob.glob(os.path.join(base, "*"))):
            if not os.path.isdir(d):
                continue
            sid = os.path.basename(d)
            cv, motif = False, None
            ypath = os.path.join(d, "scenario.yaml")
            if yaml is not None and os.path.exists(ypath):
                with open(ypath, encoding="utf-8") as f:
                    y = yaml.safe_load(f) or {}
                motif = y.get("motif")
                cv = bool((y.get("corruption") or {}).get("contract_violation", False))
            out.append({
                "sid": sid, "suite": suite, "split": sp, "motif": motif,
                "contract_violation": cv, "dir": d,
            })
    return out


# ---------------------------------------------------------------------------
# 生フレーム読込(version は絶対に書き換えない)
# ---------------------------------------------------------------------------
def load_pso_frames(scenario_dir):
    """pso_input.jsonl を 1 行 1 フレームの JSON として読む(順序保存・非空行のみ)。"""
    frames = []
    with open(os.path.join(scenario_dir, "pso_input.jsonl"), encoding="utf-8") as f:
        for line in f:
            if line.strip():
                frames.append(json.loads(line))
    return frames


def load_gt_frames(scenario_dir):
    """ground_truth.yaml(format: label)の frames リスト(生 dict)を返す。"""
    if yaml is None:
        raise RuntimeError("pyyaml 未導入: GT(ラベル形)を読むには pyyaml が要る")
    with open(os.path.join(scenario_dir, "ground_truth.yaml"), encoding="utf-8") as f:
        g = yaml.safe_load(f) or {}
    return g.get("frames", []) or []


def gt_view(fr):
    """ラベル形 GT の 1 フレーム → 8 層採点 view(欠損/null は None=採点除外)。

    situations_v1 のラベル形は quality_regime / scene_regime を **t3 配下**に持つ
    (t3.quality_regime / t3.scene_regime)。補助分布 t2.hazard / t2.dynamics は
    採点対象外なので取り出さない(README §2)。
    """
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


# ---------------------------------------------------------------------------
# preflight 契約検証(engine 実行**前**・明示拒否)
# ---------------------------------------------------------------------------
def preflight_validate(pso_frames, gt_frame_count=None):
    """PSO フレーム列を engine 実行前に契約検証し、構造化 verdict を返す(F-015 (b))。

    検査(決定的な固定順・最初に見つかった違反で拒否):
      1. bad_version         : どれかのフレームの version が 'PSO-Snapshot/' 始まりでない。
                               **version は書き換えない**(bad_version の洗浄を防ぐ)。
      2. ts_regression       : ts が前フレームより後退(単調非減少違反)。
      3. type_break          : tracks が dict でない / tracks.audio・humans・objects が
                               存在するのに list でない、または要素が dict でない。
      4. frame_count_mismatch: gt_frame_count 指定時に PSO 行数と一致しない。

    Args:
        pso_frames     : load_pso_frames の返り値(生フレーム列)。
        gt_frame_count : GT フレーム数(None ならフレーム数一致検査をスキップ)。

    Returns:
        {"ok": bool, "reason": str|None, "detail": str}
        reason は ok のとき None、拒否時は REJECT_REASONS のいずれか。
    """
    # 前提: 各フレームは dict。
    for i, fr in enumerate(pso_frames):
        if not isinstance(fr, dict):
            return _rej("other", f"frame {i} が dict でない: {type(fr).__name__}")

    # 1. version 接頭辞(書き換えない)。
    for i, fr in enumerate(pso_frames):
        v = fr.get("version")
        if not (isinstance(v, str) and v.startswith(_SNAPSHOT_PREFIX)):
            return _rej("bad_version", f"frame {i} version={v!r}")

    # 2. ts 単調非減少。
    prev = None
    for i, fr in enumerate(pso_frames):
        ts = fr.get("ts")
        try:
            tsf = float(ts)
        except (TypeError, ValueError):
            return _rej("other", f"frame {i} ts が数値でない: {ts!r}")
        if prev is not None and tsf < prev:
            return _rej("ts_regression", f"frame {i} ts {tsf} < 前 {prev}")
        prev = tsf

    # 3. tracks 型(audio/humans/objects は存在時 list[dict])。
    for i, fr in enumerate(pso_frames):
        tr = fr.get("tracks")
        if tr is None:
            continue
        if not isinstance(tr, dict):
            return _rej("type_break", f"frame {i} tracks が dict でない: {type(tr).__name__}")
        for key in ("audio", "humans", "objects"):
            if key not in tr:
                continue
            lst = tr[key]
            if not isinstance(lst, list):
                return _rej("type_break",
                            f"frame {i} tracks.{key} が list でない: {type(lst).__name__}")
            for j, el in enumerate(lst):
                if not isinstance(el, dict):
                    return _rej("type_break",
                                f"frame {i} tracks.{key}[{j}] が dict でない: {type(el).__name__}")

    # 4. PSO/GT フレーム数一致。
    if gt_frame_count is not None and len(pso_frames) != gt_frame_count:
        return _rej("frame_count_mismatch",
                    f"PSO {len(pso_frames)} 行 != GT {gt_frame_count} フレーム")

    return {"ok": True, "reason": None, "detail": ""}


def _rej(reason, detail):
    return {"ok": False, "reason": reason, "detail": detail}


# ---------------------------------------------------------------------------
# engine 入力の整形(非違反のみ・geom 欠落補完・version 不変)
# ---------------------------------------------------------------------------
def prepare_snaps(pso_frames):
    """非違反シナリオの PSO フレームを engine 実行用に整える(浅いコピー・原本不変)。

    geom が無い/min_TTC_s が None のフレームだけ min_TTC_s=999.0 で補完する(破損仕様の
    TTC 供給停止=既定値で埋めてよい・README §8。seal/cv3 の慣習に一致)。それ以外の
    geom キーは補完しない。**version・origin は一切書き換えない**
    (bad_version の洗浄禁止・README §8: origin/version の補完は不要)。
    """
    out = []
    for s in pso_frames:
        s = dict(s)
        g = dict(s.get("geom") or {})
        if g.get("min_TTC_s") is None:
            g["min_TTC_s"] = 999.0
        s["geom"] = g
        out.append(s)
    return out


# ---------------------------------------------------------------------------
# trace 組み立て(engine views + 生 GT → harness フレーム)
# ---------------------------------------------------------------------------
def assemble_trace_frames(views, gt_frames):
    """engine の 8 層 view 列と生 GT フレーム列を harness.score 用フレーム列へ。

    フレーム i を index 対応で突合する。engine view 数と GT 数が異なる場合に短い側へ
    切り詰めると採点分母が変わるため、呼び出し側が incident 化できるよう ValueError にする。
    """
    if len(views) != len(gt_frames):
        raise ValueError(
            f"engine views {len(views)} != GT frames {len(gt_frames)}"
        )
    frames = []
    for i in range(len(gt_frames)):
        gf = gt_frames[i]
        ts = gf.get("ts", float(i))
        frames.append({
            "ts": float(ts),
            "view": dict(views[i]),
            "gt": gt_view(gf),
        })
    return frames


def partition_by_suite(trace):
    """trace {sid: frames} を suite 別サブ trace へ分割する(per-suite 採点用)。"""
    parts = {}
    for sid, frames in trace.items():
        parts.setdefault(suite_of(sid), {})[sid] = frames
    return parts
