"""Phase 4 診断: 観測式/HGF が t3_hypothesis に効くか(構造バグ/較正の切り分け)。

狙い(指示):
  弱5の唯一の lose は t3_hypothesis。観測式/HGF は h_q を作り t3 の posterior 入力に流れる。
  本スクリプトは「観測式/HGF(h_q)が t3 判別にどう寄与しているか」を **src 無改変** で計測し、
    (A) 構造バグ(特定入力で証拠が壊れる・h_q が t3 に届かない)か
    (B) 較正(h_q スケールずれ)か
    (C) どちらでも t3 が上がらない(観測式/HGF は t3 に効かない)か
  を **証拠付き** で判定する。

計測点(3点・指示):
  1. ADR 0014 積み残し(h_q 過敏): h_q 分布を GT quality クラス別に出し、DEGRADED 相当入力で
     h_q を ~0 まで潰しているか(過敏)を測る。BLOCK 誤射(GOOD/DEGRADED→BLOCK)も数える。
  2. t3 への h_q 寄与: t3 の分類器(classify_t3)が実際に posterior(h_q)特徴を使っているかを
     **感度実験** で測る。h_q を 0→1 に振っても t3 出力が変わらなければ「h_q は t3 に届いていない」。
     さらに「h_q→mode→t3」の間接経路(env_change logit)が t3 を動かすかも測る。
  3. t3 入力の証拠品質: core が t3 に渡す posterior(h_q)列が t3 hypothesis 判別に有用な信号か
     (GT t3 クラスと h_q に相関があるか=潰れていないか)。

規律:
  - src/supreme/*.py(core/モジュール/テスト)は一切変更しない。分析専用。
  - supreme.* 公開 API + core 内部関数の import 再利用のみ。baseline は import しない。決定的・stdlib。
  - 不整合・抽出不一致は数字を捏造せず停止して報告。

使い方:
    python scripts/run_phase4_hgf_diagnose.py [--pso-dir <p>] [--gt-dir <p>] [--out <p>]
"""

from __future__ import annotations

import argparse
import datetime
import os
import statistics
import sys
from collections import Counter, defaultdict

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_SRC_DIR = os.path.join(os.path.dirname(_SCRIPT_DIR), "src")
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from supreme import core, t3 as t3_mod, mode as mode_mod
import run_dev_eval as dev
import run_dev_eval_diagnose as diag


class Stop(Exception):
    pass


def _fmt(x):
    return "NA" if x is None else f"{x:.4f}"


# ---------------------------------------------------------------------------
# 計測1: h_q 分布(GT quality クラス別)+ BLOCK 誤射
# ---------------------------------------------------------------------------

def measure_hq_distribution(snaps_by_sid, gt_by_sid):
    """GT quality_regime クラス別に h_q の分布(min/median/max/mean)を出す。

    h_q を ~0 まで潰しているか(過敏)を DEGRADED/BLOCK 相当入力で確認する。
    """
    hq_by_gtclass = defaultdict(list)
    # quality 予測(h_q,vol→classify)と GT の混同(BLOCK 誤射の規模)。
    quality_confusion = defaultdict(Counter)
    for sid in sorted(snaps_by_sid):
        snaps = snaps_by_sid[sid]
        gts = gt_by_sid[sid]
        qlogits = core._quality_obs_raw_logits(snaps)
        h_q_seq, vol_seq = core._hq_vol_sequences(qlogits)
        for i, gt in enumerate(gts):
            gt_q = gt.get("quality_regime")
            if gt_q is None:
                continue
            hq_by_gtclass[gt_q].append(h_q_seq[i])
            from supreme import quality as quality_mod
            pred_q = quality_mod.classify(h_q_seq[i], vol_seq[i])
            quality_confusion[gt_q][pred_q] += 1
    return hq_by_gtclass, quality_confusion


# ---------------------------------------------------------------------------
# 計測2: t3 への h_q 寄与(感度実験)
# ---------------------------------------------------------------------------

def measure_t3_hq_sensitivity(snaps_by_sid, views_by_sid):
    """t3 の分類器が posterior(h_q)を使っているかを感度実験で測る。

    実験A(直接経路): core が t3 に渡す mode_seq の posterior(h_q)だけを 0.0 / 1.0 / 実値 に
      置き換え、mode ラベル列は固定したまま t3 を走らせて hypothesis 列が変わるかを測る。
      → 変わらなければ「h_q は t3 分類に一切使われていない」(構造: posterior 特徴が未使用)。

    実験B(間接経路 h_q→mode→t3): core の _mode_logits は h_q<0.5 で env_change logit を積む。
      この経路で h_q が mode を変え、mode が t3 を変えるか。core の実 mode 列(h_q 実値)と、
      h_q を全フレーム 1.0 に固定して mode を再計算した列を比べ、mode 差・t3 差を数える。
    """
    # --- 実験A: t3 直接経路(mode 固定・posterior だけ振る)---
    direct_changed_frames = 0
    direct_total_frames = 0
    for sid in sorted(snaps_by_sid):
        snaps = snaps_by_sid[sid]
        views = views_by_sid[sid]
        mode_seq, reset_seq = build_t3_mode_seq(snaps, views)
        params = t3_mod.default_params()
        base = t3_mod.run_t3_sequence(mode_seq, reset_seq, params)
        # posterior を 0.0 / 1.0 に置換(mode ラベルは固定)。
        for pval in (0.0, 1.0):
            alt = [{"mode": m["mode"], "posterior": pval} for m in mode_seq]
            out = t3_mod.run_t3_sequence(alt, reset_seq, params)
            direct_total_frames += len(out)
            direct_changed_frames += sum(1 for a, b in zip(base, out) if a != b)

    # --- 実験B: 間接経路 h_q→mode→t3 ---
    indirect_mode_changed = 0
    indirect_t3_changed = 0
    indirect_total = 0
    for sid in sorted(snaps_by_sid):
        snaps = snaps_by_sid[sid]
        views = views_by_sid[sid]
        # core 実 mode 列(h_q 実値)。
        real_modes = [v["t2_mode"] for v in views]
        # h_q を全フレーム 1.0 に固定して mode を再計算(env_change 経路を殺す)。
        alt_modes = recompute_modes_with_fixed_hq(snaps, hq_fixed=1.0)
        if len(alt_modes) != len(real_modes):
            raise Stop(f"[{sid}] mode 再計算列長不一致。停止する。")
        indirect_total += len(real_modes)
        mode_diff = sum(1 for a, b in zip(real_modes, alt_modes) if a != b)
        indirect_mode_changed += mode_diff
        # t3 を両 mode 列で走らせて差を測る(posterior は実 h_q を使う・mode だけ違う)。
        h_q_seq, _ = core._hq_vol_sequences(core._quality_obs_raw_logits(snaps))
        reset_seq = [i == 0 for i in range(len(real_modes))]
        real_seq = [{"mode": m, "posterior": h_q_seq[i]} for i, m in enumerate(real_modes)]
        alt_seq = [{"mode": m, "posterior": h_q_seq[i]} for i, m in enumerate(alt_modes)]
        params = t3_mod.default_params()
        t3_real = t3_mod.run_t3_sequence(real_seq, reset_seq, params)
        t3_alt = t3_mod.run_t3_sequence(alt_seq, reset_seq, params)
        indirect_t3_changed += sum(1 for a, b in zip(t3_real, t3_alt) if a != b)

    return {
        "direct_changed_frames": direct_changed_frames,
        "direct_total_frames": direct_total_frames,
        "indirect_mode_changed": indirect_mode_changed,
        "indirect_t3_changed": indirect_t3_changed,
        "indirect_total": indirect_total,
    }


def build_t3_mode_seq(snaps, views):
    """core が t3 に渡すのと同じ mode_seq/reset_seq を再構成する(diag と同義)。"""
    h_q_seq, _ = core._hq_vol_sequences(core._quality_obs_raw_logits(snaps))
    mode_seq = [{"mode": v["t2_mode"], "posterior": h_q_seq[i]} for i, v in enumerate(views)]
    reset_seq = [i == 0 for i in range(len(views))]
    return mode_seq, reset_seq


def recompute_modes_with_fixed_hq(snaps, hq_fixed):
    """h_q を固定値にして core と同じ mode ヒステリシス連鎖を再現する(env_change 経路を測る)。

    core._run_one_scenario の mode 結線を h_q だけ差し替えて再現:
      logits = _mode_logits(snap, risk_tier, approaching, h_q_fixed)
      t2_mode = mode.hysteresis(logits, prev_mode)
    その他(risk_tier/approaching)は実値を core 経路と同じ式で算出する。
    """
    from supreme import t0 as t0_mod, t1 as t1_mod
    qlogits = core._quality_obs_raw_logits(snaps)
    anomaly_logits = core._anomaly_obs_raw_logits(snaps)
    pw_anom_seq = core._pw_anom_sequence(anomaly_logits)
    modes = []
    prev_mode = mode_mod.QUIET
    prev_t1 = None
    for i, snap in enumerate(snaps):
        risk_tier = t0_mod.risk_tier(core._t0_tracks(snap))
        ttc = core._min_ttc(snap)
        min_range = core._min_range(snap)
        t1_label, prev_t1 = t1_mod.t1_state(ttc, min_range, pw_anom_seq[i], prev_t1)
        approaching = t1_label == t1_mod.APPROACH
        logits = core._mode_logits(snap, risk_tier, approaching, hq_fixed)
        t2_mode = mode_mod.hysteresis(logits, prev_mode)
        prev_mode = t2_mode
        modes.append(t2_mode)
    return modes


# ---------------------------------------------------------------------------
# 計測3: t3 入力の証拠品質(h_q と GT t3 クラスの相関)
# ---------------------------------------------------------------------------

def measure_t3_evidence_quality(snaps_by_sid, gt_by_sid):
    """GT t3_hypothesis クラス別に h_q の分布を出す(h_q が t3 判別に有用な信号か)。

    t3 クラスが h_q で分離できるなら「h_q を t3 が使えば効く可能性」がある。
    分離できない(全クラスで h_q≈一定)なら「h_q は t3 判別の証拠でない」。
    """
    hq_by_t3 = defaultdict(list)
    for sid in sorted(snaps_by_sid):
        snaps = snaps_by_sid[sid]
        gts = gt_by_sid[sid]
        h_q_seq, _ = core._hq_vol_sequences(core._quality_obs_raw_logits(snaps))
        for i, gt in enumerate(gts):
            gt_t3 = gt.get("t3_hypothesis")
            if gt_t3 is None:
                continue
            hq_by_t3[gt_t3].append(h_q_seq[i])
    return hq_by_t3


# ---------------------------------------------------------------------------
# 補助統計
# ---------------------------------------------------------------------------

def _dist(vals):
    if not vals:
        return None
    return {
        "n": len(vals),
        "min": min(vals),
        "median": statistics.median(vals),
        "max": max(vals),
        "mean": statistics.fmean(vals),
    }


def run(pso_dir, gt_dir, out_path):
    print("[1/5] データ読み込み(run_dev_eval 経路の再利用)")
    views_by_sid, gt_by_sid, dir_to_sid, dirs = diag.load_views_and_gt(pso_dir, gt_dir)
    sids = sorted(views_by_sid)
    snaps_by_sid = {}
    for dir_name in dirs:
        pso_path = os.path.join(pso_dir, dir_name, "pso_input.jsonl")
        snaps = dev._load_pso(pso_path)
        sid = dir_to_sid[dir_name]
        snaps_by_sid[sid] = snaps
        if len(snaps) != len(views_by_sid[sid]):
            raise Stop(f"[{sid}] snaps/view 長不一致。停止する。")
    print(f"      {len(sids)} シナリオ・決定的 OK")

    print("[2/5] 計測1: h_q 分布(GT quality クラス別)+ quality 混同(BLOCK 誤射)")
    hq_by_q, q_conf = measure_hq_distribution(snaps_by_sid, gt_by_sid)

    print("[3/5] 計測2: t3 への h_q 寄与(直接経路 posterior 感度 + 間接経路 h_q→mode→t3)")
    sens = measure_t3_hq_sensitivity(snaps_by_sid, views_by_sid)

    print("[4/5] 計測3: t3 入力の証拠品質(GT t3 クラス別 h_q 分布)")
    hq_by_t3 = measure_t3_evidence_quality(snaps_by_sid, gt_by_sid)

    print("[5/5] レポート書き出し")
    report = render(
        sids=sids, hq_by_q=hq_by_q, q_conf=q_conf, sens=sens, hq_by_t3=hq_by_t3,
    )
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"      出力: {out_path}")

    # 標準出力サマリ(核心の結論)。
    print()
    print("=" * 72)
    print("Phase 4 HGF/観測式 → t3 診断サマリ")
    print("=" * 72)
    print()
    print("[計測1] h_q 分布(GT quality クラス別):")
    for q in ("GOOD", "DEGRADED", "BLOCK"):
        d = _dist(hq_by_q.get(q, []))
        if d:
            print(f"  GT={q:9s} n={d['n']:3d}  h_q min={d['min']:.4f} "
                  f"median={d['median']:.4f} max={d['max']:.4f} mean={d['mean']:.4f}")
    print()
    print("[計測2] t3 への h_q 寄与(感度実験):")
    print(f"  直接経路(posterior を 0/1 に振っても t3 が変わるフレーム): "
          f"{sens['direct_changed_frames']} / {sens['direct_total_frames']}")
    print(f"  間接経路 h_q→mode(h_q=1 固定で変わる mode フレーム): "
          f"{sens['indirect_mode_changed']} / {sens['indirect_total']}")
    print(f"  間接経路 →t3(その mode 差が t3 を変えるフレーム): "
          f"{sens['indirect_t3_changed']} / {sens['indirect_total']}")
    print()
    print("[計測3] t3 入力の証拠品質(GT t3 クラス別 h_q 分布):")
    for t3c in sorted(hq_by_t3, key=lambda k: -len(hq_by_t3[k])):
        d = _dist(hq_by_t3[t3c])
        print(f"  GT={t3c:20s} n={d['n']:3d}  h_q median={d['median']:.4f} "
              f"[{d['min']:.4f}, {d['max']:.4f}]")
    print()
    print("=" * 72)
    return hq_by_q, q_conf, sens, hq_by_t3


def render(*, sids, hq_by_q, q_conf, sens, hq_by_t3):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    L = []
    a = L.append
    a("# Phase 4 診断 — 観測式/HGF は t3_hypothesis に効くか")
    a("")
    a(f"- 生成時刻: {now}")
    a(f"- 対象: v021_core {len(sids)} シナリオ(in-sample 診断)")
    a("- src/supreme/*.py 無改変・分析専用。supreme 公開 API + core 内部関数の import 再利用のみ。")
    a("- baseline 非 import・決定的・stdlib。")
    a("")
    a("## 計測1: h_q 分布(GT quality クラス別)— ADR 0014 積み残し(h_q 過敏)の確認")
    a("")
    a("| GT quality | n | h_q min | median | max | mean |")
    a("|---|---:|---:|---:|---:|---:|")
    for q in ("GOOD", "DEGRADED", "BLOCK"):
        d = _dist(hq_by_q.get(q, []))
        if d:
            a(f"| {q} | {d['n']} | {d['min']:.4f} | {d['median']:.4f} | {d['max']:.4f} | {d['mean']:.4f} |")
    a("")
    a("**quality 混同(GT 行 → h_q,vol→classify 予測 列):**")
    a("")
    preds = sorted({p for c in q_conf.values() for p in c})
    a("| GT＼予測 | " + " | ".join(preds) + " |")
    a("|---|" + "|".join(["---:"] * len(preds)) + "|")
    for q in ("GOOD", "DEGRADED", "BLOCK"):
        if q in q_conf:
            cells = [str(q_conf[q].get(p, 0)) for p in preds]
            a(f"| {q} | " + " | ".join(cells) + " |")
    a("")
    a("## 計測2: t3 への h_q 寄与(感度実験)")
    a("")
    a("**実験A(直接経路)**: t3 に渡す mode 列の posterior(h_q)だけを 0.0 / 1.0 に置換し")
    a("(mode ラベルは固定)、t3 hypothesis 列が変わるフレーム数を数える。")
    a("")
    a(f"- posterior を 0/1 に振っても t3 が変わったフレーム: "
      f"**{sens['direct_changed_frames']} / {sens['direct_total_frames']}**")
    a("")
    a("**実験B(間接経路 h_q→mode→t3)**: h_q<0.5 で env_change logit を積む `_mode_logits` 経路。")
    a("h_q を全フレーム 1.0 固定で mode を再計算し、mode 差と t3 差を数える。")
    a("")
    a(f"- h_q=1 固定で変わった mode フレーム: **{sens['indirect_mode_changed']} / {sens['indirect_total']}**")
    a(f"- その mode 差が t3 を変えたフレーム: **{sens['indirect_t3_changed']} / {sens['indirect_total']}**")
    a("")
    a("## 計測3: t3 入力の証拠品質(GT t3 クラス別 h_q 分布)")
    a("")
    a("| GT t3_hypothesis | n | h_q min | median | max |")
    a("|---|---:|---:|---:|---:|")
    for t3c in sorted(hq_by_t3, key=lambda k: -len(hq_by_t3[k])):
        d = _dist(hq_by_t3[t3c])
        a(f"| {t3c} | {d['n']} | {d['min']:.4f} | {d['median']:.4f} | {d['max']:.4f} |")
    a("")
    a("---")
    a("")
    a("_分析専用(src 無改変・baseline 非 import・決定的)。_")
    return "\n".join(L)


def main():
    p = argparse.ArgumentParser(description="Phase4: 観測式/HGF→t3 診断")
    p.add_argument("--pso-dir", default=dev.DEFAULT_PSO_DIR)
    p.add_argument("--gt-dir", default=dev.DEFAULT_GT_DIR)
    p.add_argument("--out", default=None)
    args = p.parse_args()
    out_path = args.out
    if out_path is None:
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M")
        out_path = os.path.join("reports", f"phase4-hgf-diagnose-{stamp}.md")
    try:
        run(args.pso_dir, args.gt_dir, out_path)
    except (Stop, dev.V13LabelError, dev.DataMismatch) as e:
        print(file=sys.stderr)
        print("=" * 70, file=sys.stderr)
        print("STOP(数字を捏造せず停止)。", file=sys.stderr)
        print(f"  {type(e).__name__}: {e}", file=sys.stderr)
        print("=" * 70, file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
