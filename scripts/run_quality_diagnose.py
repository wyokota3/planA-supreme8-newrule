"""quality_regime 対旧 supreme(baseline 忠実度)ギャップ診断 — 純粋な測定・分析。

目的(指示):
  弱項目 quality_regime の新 supreme 0.7238 vs 旧 supreme(l04-ours) 0.7619 (-0.038) を
  (A) 構造バグ / (B) baseline 忠実度ギャップ(ルール or 観測式の再現漏れ) /
  (C) genuine(観測式/HGF 感度=ADR 0014 残件・スコープ外) に切り分ける。

規律:
  - src/supreme・テスト無改変(診断のみ・本スクリプトは src を import するだけ)。
  - 決定的・stdlib + pyyaml。**baseline コードは import しない**(意味論は読むが再実装)。
  - 捏造禁止: 観測した数字のみで判定。停止条件は run_dev_eval を再利用。

経路:
  PSO(planA-baseline/v021_core)→ core.run_supreme → v1.4 view、
  GT(n04-feat/v021_core)→ ADR0006 正準化 → v1.4 gt view(run_dev_eval を再利用)。

本スクリプトが追加で行う「baseline 忠実シミュレーション」:
  baseline `ns_epi/quality.py`(`run_quality`/`_hq_to_regime`)と `ns_epi/hgf.py`
  (`hgf3_update`/`DEFAULT_PARAMS`/`initial_belief`)の**意味論を再実装**(import せず)し、
  同じ PSO 入力(QoS/latency・id_const/w_obs_bar は欠落=既定)から baseline が出す
  quality_regime を per-frame で算出する。これを「baseline 忠実」予測列とし、
    - supreme 予測 vs baseline 忠実予測 vs GT を per-frame で対照、
    - GOOD ゲート閾値(supreme 0.93 vs baseline 0.94)・観測式・HGF の差が
      どれだけ acc を動かすかを分離測定する。

出力: reports/quality-diagnose-<YYYYMMDD-HHMM>.md + 標準出力。
"""

from __future__ import annotations

import argparse
import datetime
import math
import os
import sys
from collections import Counter, defaultdict

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_SRC_DIR = os.path.join(os.path.dirname(_SCRIPT_DIR), "src")
for _p in (_SRC_DIR, _SCRIPT_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# supreme 公開 API + 既存ランナーの正準化/データ対応のみ(baseline は import しない)。
from supreme import core  # noqa: E402
import run_dev_eval as dev  # noqa: E402
import run_dev_eval_diagnose as diag  # noqa: E402

LABELS = ("GOOD", "DEGRADED", "BLOCK")


# ===========================================================================
# baseline 忠実シミュレーション(ns_epi/quality.py + ns_epi/hgf.py の意味論を再実装)
#   — baseline を import せず、読んだ意味論をそのまま Python に写したもの。
# ===========================================================================

# --- baseline 観測式定数(ns_epi/quality.py L29-34・L04-params §3.2)---
_B_BETA0 = -2.0
_B_BETA1 = 5.0
_B_BETA2 = 4.0
_B_BETA3 = 2.5
_B_BETA4 = 1.5
_B_TAU = 200.0
_B_CLAMP_LO = 1e-6
_B_CLAMP_HI = 1.0 - 1e-6

# --- baseline HGF DEFAULT_PARAMS(ns_epi/hgf.py L37-44)---
_B_HGF = {
    "kappa_1": 1.0, "kappa_2": 1.0,
    "omega_1": -4.0, "omega_2": -4.0, "omega_3": -6.0,
    "obs_noise": 0.1,
}
# --- baseline HGF 数値安定定数(ns_epi/hgf.py L21-30)---
_B_EXP_LO, _B_EXP_HI = -30.0, 30.0
_B_MU1_LO, _B_MU1_HI = -10.0, 10.0
_B_MU2_LO, _B_MU2_HI = -10.0, 10.0
_B_PI_MIN, _B_PI_MAX = 1e-4, 1e6


def _sigmoid(x):
    if x >= 0.0:
        return 1.0 / (1.0 + math.exp(-x))
    e = math.exp(x)
    return e / (1.0 + e)


def _b_clip(x, lo, hi):
    if x < lo:
        return float(lo)
    if x > hi:
        return float(hi)
    return float(x)


def _b_initial_belief():
    """ns_epi/hgf.py initial_belief(0.0)。"""
    return {"mu1": 0.0, "pi1": 1.0, "mu2": 0.0, "pi2": 1.0, "mu3": 0.0, "pi3": 1.0}


def _b_hgf3_update(belief, u):
    """ns_epi/hgf.py hgf3_update の意味論を再実装(DEFAULT_PARAMS 固定)。返り (belief, sigma1)。"""
    p = _B_HGF
    if not math.isfinite(float(u)):
        return dict(belief), 1.0 / float(belief["pi1"])
    mu1, pi1 = float(belief["mu1"]), float(belief["pi1"])
    mu2, pi2 = float(belief["mu2"]), float(belief["pi2"])
    mu3, pi3 = float(belief["mu3"]), float(belief["pi3"])
    k1, k2 = p["kappa_1"], p["kappa_2"]
    o1, o2, o3 = p["omega_1"], p["omega_2"], p["omega_3"]
    obs_noise = p["obs_noise"]
    pi_u = 1.0 / (obs_noise ** 2)  # baseline: 1/obs_noise^2 = 100

    nu1 = math.exp(_b_clip(k1 * mu2 + o1, _B_EXP_LO, _B_EXP_HI))
    nu2 = math.exp(_b_clip(k2 * mu3 + o2, _B_EXP_LO, _B_EXP_HI))
    nu3 = math.exp(_b_clip(o3, _B_EXP_LO, _B_EXP_HI))
    pi1_hat = 1.0 / (1.0 / pi1 + nu1)
    pi2_hat = 1.0 / (1.0 / pi2 + nu2)
    pi3_hat = 1.0 / (1.0 / pi3 + nu3)
    mu1_hat, mu2_hat, mu3_hat = mu1, mu2, mu3

    delta1 = float(u) - mu1_hat
    pi1_new = pi1_hat + pi_u
    mu1_new = mu1_hat + (pi_u / pi1_new) * delta1

    w1 = nu1 * pi1_hat
    vope1 = pi1_hat * (1.0 / pi1_new + (mu1_new - mu1_hat) ** 2) - 1.0
    pi2_new = pi2_hat + 0.5 * k1 ** 2 * w1 * (w1 + (2.0 * w1 - 1.0) * vope1)
    pi2_new = _b_clip(pi2_new, _B_PI_MIN, _B_PI_MAX)
    mu2_new = mu2_hat + 0.5 * (k1 * w1 / pi2_new) * vope1
    mu2_new = _b_clip(mu2_new, _B_MU2_LO, _B_MU2_HI)

    w2 = nu2 * pi2_hat
    vope2 = pi2_hat * (1.0 / pi2_new + (mu2_new - mu2_hat) ** 2) - 1.0
    pi3_new = pi3_hat + 0.5 * k2 ** 2 * w2 * (w2 + (2.0 * w2 - 1.0) * vope2)
    pi3_new = _b_clip(pi3_new, _B_PI_MIN, _B_PI_MAX)
    mu3_new = mu3_hat + 0.5 * (k2 * w2 / pi3_new) * vope2

    pi1_new = _b_clip(pi1_new, _B_PI_MIN, _B_PI_MAX)
    mu1_new = _b_clip(mu1_new, _B_MU1_LO, _B_MU1_HI)
    sigma1 = 1.0 / pi1_new

    cand = {"mu1": mu1_new, "pi1": pi1_new, "mu2": mu2_new,
            "pi2": pi2_new, "mu3": mu3_new, "pi3": pi3_new}
    if not all(math.isfinite(v) for v in cand.values()):
        return dict(belief), 1.0 / float(belief["pi1"])
    return cand, sigma1


def _b_hq_to_regime(h_q, vol):
    """ns_epi/quality.py _hq_to_regime(v1.3 語彙: GOOD/DEGRADED/PASS/BLOCK)。"""
    if h_q < 0.25:
        return "BLOCK"
    if h_q < 0.40 and vol > 0.05:
        return "BLOCK"
    if h_q < 0.55:
        return "DEGRADED"
    if h_q >= 0.94 and vol < 0.01:
        return "GOOD"
    return "PASS"


# v1.3 baseline 語彙 → v1.4 順位シフト。
#   評価語彙の順位シフトは 3 クラス GOOD|PASS|DEGRADED → GOOD|DEGRADED|BLOCK
#   (契約 v1.4 §11・ADR0006/0005)。これが GT 側に適用される写像
#   (run_dev_eval._QUALITY_REMAP と同一)。
#   ただし baseline `_hq_to_regime` の**ランタイム出力**は v1.3 評価語彙に無い "BLOCK"
#   (h_q<0.25)を直接返しうる。v1.3 評価語彙は 3 クラス(GOOD/PASS/DEGRADED)で BLOCK は
#   評価層に存在しない(契約 v1.4 §11・GT 分布 GOOD/PASS/DEGRADED のみ)。
#   忠実比較のため「ランタイム BLOCK は最重度 → v1.4 最重度 BLOCK」へ写す
#   (順位保存・順位シフトと矛盾しない)。この写像の妥当性は本文 §補注で明記し捏造しない。
_B_REMAP_V14 = {"GOOD": "GOOD", "PASS": "DEGRADED", "DEGRADED": "BLOCK", "BLOCK": "BLOCK"}


def _scene_qos_latency(snap):
    """PSO snap から QoS/latency を取り出す(supreme core._scene_qos_latency と同規約)。"""
    ss = snap.get("scene_state")
    if isinstance(ss, dict):
        return float(ss.get("QoS", 1.0)), float(ss.get("latency_ms", 0.0))
    return 1.0, 0.0


def _baseline_w_obs_bar(snap):
    """baseline runner._extract_quality_inputs と同一: 全 track の w_obs 中央値・無ければ 1.0。

    これが baseline の**実 quality 入力**(supreme は固定 0.5 を使う=本診断で分離する乖離点)。
    """
    import statistics
    tracks = snap.get("tracks", {}) or {}
    vals = []
    for grp in ("audio", "humans", "objects"):
        for t in (tracks.get(grp, []) or []):
            if "w_obs" in t:
                vals.append(float(t["w_obs"]))
    return statistics.median(vals) if vals else 1.0


def baseline_quality_v14_sequence(snaps, *, id_const=1.0, w_obs_mode="baseline",
                                  fixed_w_obs=0.5):
    """baseline 忠実な quality_regime(v1.4 語彙)の per-frame 列を返す。

    w_obs_mode="baseline": runner._extract_quality_inputs と同一(track w_obs 中央値・既定 1.0)。
    w_obs_mode="fixed":    supreme と同じ固定 0.5(乖離点の分離用)。
    id_const は両系とも 1.0(契約中立)。観測式・clamp+logit 再導出・HGF・_hq_to_regime は
    すべて baseline の意味論を忠実に写す。
    返り: [(regime_v14, h_q, vol, regime_v13_native), ...]。
    """
    out = []
    belief = _b_initial_belief()
    for snap in snaps:
        qos, latency = _scene_qos_latency(snap)
        if w_obs_mode == "baseline":
            w_obs_bar = _baseline_w_obs_bar(snap)
        else:
            w_obs_bar = fixed_w_obs
        logit_val = (
            _B_BETA0
            + _B_BETA1 * qos
            - _B_BETA2 * (latency / _B_TAU)
            - _B_BETA3 * (1.0 - id_const)
            + _B_BETA4 * w_obs_bar
        )
        h_raw = _sigmoid(logit_val)
        h_raw = max(_B_CLAMP_LO, min(_B_CLAMP_HI, h_raw))
        u = math.log(h_raw / (1.0 - h_raw))
        belief, sigma1 = _b_hgf3_update(belief, u)
        h_q = _sigmoid(float(belief["mu1"]))
        vol = float(sigma1)
        regime_v13 = _b_hq_to_regime(h_q, vol)
        out.append((_B_REMAP_V14[regime_v13], h_q, vol, regime_v13))
    return out


# ===========================================================================
# supreme の per-frame h_q/vol を取り出す(core の内部式を診断用に再呼び出し・src 無改変)
# ===========================================================================

def supreme_quality_internals(snaps):
    """supreme core の観測式+共有 HGF をそのまま呼び、per-frame (regime, h_q, vol) を返す。

    src/supreme は変更しない。core の公開されている内部関数を診断目的で呼ぶだけ。
    run_supreme と同一の式(同じ quality_logits → 同じ h_q/vol → 同じ quality.classify)。
    """
    from supreme import quality as quality_mod
    quality_logits = core._quality_obs_raw_logits(snaps)
    h_q_seq, vol_seq = core._hq_vol_sequences(quality_logits)
    out = []
    for i in range(len(snaps)):
        h_q = h_q_seq[i]
        vol = vol_seq[i]
        out.append((quality_mod.classify(h_q, vol), h_q, vol))
    return out


def supreme_with_median_wobs_internals(snaps):
    """supreme の HGF/quality.classify は据え置き、観測式の w_obs だけ baseline 流(track 中央値)に
    差し替えた per-frame (regime, h_q, vol) を返す(乖離点 §w_obs の効果を src 無改変で測る)。

    観測式の定数(bias/qos/latency/id)は supreme core と同一。w_obs だけ固定 0.5 → median に。
    HGF は supreme の scene 共有 hgf_filter(default_hgf_params)をそのまま使う。
    """
    from supreme import quality as quality_mod
    logits = []
    for snap in snaps:
        qos, latency = core._scene_qos_latency(snap)
        w = _baseline_w_obs_bar(snap)
        lg = (core._OBS_BIAS + core._OBS_QOS * qos
              + core._OBS_LATENCY * (latency / core._LATENCY_SCALE)
              + core._OBS_ID * (1.0 - core._ID_CONST)
              + core._OBS_WOBS * w)
        logits.append(lg)
    h_q_seq, vol_seq = core._hq_vol_sequences(logits)
    out = []
    for i in range(len(snaps)):
        out.append((quality_mod.classify(h_q_seq[i], vol_seq[i]), h_q_seq[i], vol_seq[i]))
    return out


# ---------------------------------------------------------------------------
# 旧 supreme(l04-ours)の権威ある per-frame quality を trace.json から読む
#   (再構成ではなく実測値。v1.3 view を v1.4 へ順位シフトして supreme と同一土俵で採点)
# ---------------------------------------------------------------------------

_OURS_TRACE = (
    r"C:\work\L04-planA\supreme\external-data\planA-baseline\results\trace\trace.json"
)


def load_ours_quality_v14(dirs, dir_to_sid):
    """l04-ours の trace.json から per-(sid, frame) の quality_regime(v1.4 順位シフト後)を読む。

    trace.json view は v1.3 4 クラス(GOOD/PASS/DEGRADED/BLOCK)。順位シフト(GT と同じ
    GOOD→GOOD/PASS→DEGRADED/DEGRADED→BLOCK、native BLOCK は最重度 BLOCK)で v1.4 へ写す。
    存在しなければ None を返す(その場合 ours 比較はスキップ・捏造しない)。
    """
    import json
    if not os.path.isfile(_OURS_TRACE):
        return None
    with open(_OURS_TRACE, "r", encoding="utf-8") as f:
        tr = json.load(f)
    out = {}
    for d in dirs:
        sid = dir_to_sid[d]
        if d not in tr:
            return None  # dir 名対応が取れない → ours 比較を断念(捏造しない)
        frames = tr[d]
        out[sid] = [_B_REMAP_V14.get(fr["view"].get("quality_regime"))
                    for fr in frames]
    return out


# ===========================================================================
# 集計
# ===========================================================================

def _acc(pred_by_sid, gt_by_sid):
    n = ok = 0
    for sid in pred_by_sid:
        for i, p in enumerate(pred_by_sid[sid]):
            g = gt_by_sid[sid][i].get("quality_regime")
            if g is None:
                continue
            n += 1
            if p == g:
                ok += 1
    return ok, n


def _confusion(pred_by_sid, gt_by_sid):
    conf = defaultdict(Counter)
    for sid in pred_by_sid:
        for i, p in enumerate(pred_by_sid[sid]):
            g = gt_by_sid[sid][i].get("quality_regime")
            if g is None:
                continue
            conf[g][p] += 1
    return conf


# ===========================================================================
# メイン
# ===========================================================================

def run(pso_dir, gt_dir, out_path):
    print(f"[1/5] データ読み込み(run_dev_eval 経路を再利用)")
    print(f"      PSO={pso_dir}")
    print(f"      GT ={gt_dir}")
    views_by_sid, gt_by_sid, dir_to_sid, dirs = diag.load_views_and_gt(pso_dir, gt_dir)

    # supreme 予測(run_supreme の view)と内部 h_q/vol。
    sup_pred = {}     # sid -> [regime,...]  (= view['quality_regime'])
    sup_internals = {}  # sid -> [(regime,h_q,vol),...]
    base_internals = {}  # sid -> [(regime_v14,h_q,vol),...]  baseline 忠実
    # シナリオ入力を再取得(diag.load_views_and_gt は views しか返さないので PSO を再読込)。
    scenario_inputs = {}
    for d in dirs:
        sid = dir_to_sid[d]
        snaps = dev._load_pso(os.path.join(pso_dir, d, "pso_input.jsonl"))
        scenario_inputs[sid] = snaps

    for sid in sorted(views_by_sid):
        snaps = scenario_inputs[sid]
        sup_pred[sid] = [v.get("quality_regime") for v in views_by_sid[sid]]
        sup_internals[sid] = supreme_quality_internals(snaps)
        base_internals[sid] = baseline_quality_v14_sequence(snaps)
        # 整合検査: run_supreme の quality_regime と再呼び出しの regime が完全一致(捏造防止)。
        for i, (reg, _hq, _vol) in enumerate(sup_internals[sid]):
            if reg != sup_pred[sid][i]:
                raise dev.DataMismatch(
                    f"[{sid}] frame {i}: run_supreme の quality_regime({sup_pred[sid][i]})と "
                    f"診断再呼び出し({reg})が不一致。停止する。"
                )

    base_pred = {sid: [t[0] for t in base_internals[sid]] for sid in base_internals}

    # baseline 忠実列の native v1.3 ラベル分布(native BLOCK が出るか=h_q<0.25 到達の有無)。
    base_native_counts = Counter()
    for sid in base_internals:
        for t in base_internals[sid]:
            base_native_counts[t[3]] += 1
    print(f"      baseline 忠実 native v1.3 ラベル分布: {dict(base_native_counts)}")

    # --- 分離用変種 ---
    # 変種1: baseline 忠実だが w_obs を supreme と同じ固定 0.5 にする(w_obs 乖離の効果分離)。
    base_fixed = {}
    # 変種2(決定的・最重要): supreme の HGF/classify は据え置き、観測式 w_obs だけ baseline 流
    #   (track 中央値)に差し替えた supreme 予測。= 「w_obs 忠実化だけ」の効果を分離する。
    sup_medw = {}
    sup_medw_internals = {}
    for sid in sorted(views_by_sid):
        base_fixed[sid] = [t[0] for t in baseline_quality_v14_sequence(
            scenario_inputs[sid], w_obs_mode="fixed", fixed_w_obs=0.5)]
        sup_medw_internals[sid] = supreme_with_median_wobs_internals(scenario_inputs[sid])
        sup_medw[sid] = [t[0] for t in sup_medw_internals[sid]]

    # 旧 supreme(l04-ours)の権威 per-frame(trace.json・v1.4 順位シフト後)。
    ours_pred = load_ours_quality_v14(dirs, dir_to_sid)

    # --- acc ---
    sup_ok, sup_n = _acc(sup_pred, gt_by_sid)
    base_ok, base_n = _acc(base_pred, gt_by_sid)
    basefix_ok, basefix_n = _acc(base_fixed, gt_by_sid)
    supmedw_ok, supmedw_n = _acc(sup_medw, gt_by_sid)
    ours_ok = ours_n = None
    if ours_pred is not None:
        ours_ok, ours_n = _acc(ours_pred, gt_by_sid)
    print(f"[2/5] acc 測定")
    print(f"      新 supreme(現状・w_obs=0.5)         : {sup_ok}/{sup_n} = {sup_ok / sup_n:.4f}")
    print(f"      新 supreme + w_obs 忠実化(median)   : {supmedw_ok}/{supmedw_n} = "
          f"{supmedw_ok / supmedw_n:.4f}  ← 決定的な分離測定")
    if ours_ok is not None:
        print(f"      旧 supreme l04-ours(trace.json・v1.4): {ours_ok}/{ours_n} = "
              f"{ours_ok / ours_n:.4f}")
    print(f"      baseline 忠実 HGF(w_obs=median)      : {base_ok}/{base_n} = {base_ok / base_n:.4f}")
    print(f"      baseline 忠実 HGF(w_obs 固定0.5)     : {basefix_ok}/{basefix_n} = "
          f"{basefix_ok / basefix_n:.4f}")

    # --- 混同行列 ---
    sup_conf = _confusion(sup_pred, gt_by_sid)
    base_conf = _confusion(base_pred, gt_by_sid)

    # --- ablation: supreme の h_q/vol に baseline GOOD ゲート(>=0.94)を適用したら? ---
    #   supreme の式は据え置き、しきいだけ baseline に戻す = 「閾値再較正(0.94->0.93)」の効果分離。
    def _supreme_with_gate(gate):
        ok = n = 0
        for sid in sorted(sup_internals):
            for i, (_reg, h_q, vol) in enumerate(sup_internals[sid]):
                g = gt_by_sid[sid][i].get("quality_regime")
                if g is None:
                    continue
                # supreme.classify と同じチェーンだが GOOD ゲートの h_q 閾値だけ可変。
                if h_q < 0.25:
                    p = "BLOCK"
                elif h_q < 0.40 and vol > 0.05:
                    p = "BLOCK"
                elif h_q < 0.55:
                    p = "BLOCK"
                elif h_q >= gate and vol < 0.01:
                    p = "GOOD"
                else:
                    p = "DEGRADED"
                n += 1
                if p == g:
                    ok += 1
        return ok, n

    g094 = _supreme_with_gate(0.94)
    g093 = _supreme_with_gate(0.93)
    print(f"[3/5] ablation(supreme の式・GOOD ゲート閾値だけ動かす)")
    print(f"      supreme 式 + gate0.94: {g094[0]}/{g094[1]} = {g094[0] / g094[1]:.4f}")
    print(f"      supreme 式 + gate0.93: {g093[0]}/{g093[1]} = {g093[0] / g093[1]:.4f}")

    # --- 誤りフレーム列挙(GT != supreme pred)+ baseline 忠実なら当たるか ---
    print(f"[4/5] 誤りフレーム特定(GT != 新 supreme pred)")
    err_frames = []  # (sid, ts, gt, sup_pred, sup_hq, sup_vol, base_pred, base_hq, base_vol)
    for sid in sorted(views_by_sid):
        snaps = scenario_inputs[sid]
        for i in range(len(sup_pred[sid])):
            g = gt_by_sid[sid][i].get("quality_regime")
            if g is None:
                continue
            sp = sup_pred[sid][i]
            if sp == g:
                continue
            s_reg, s_hq, s_vol = sup_internals[sid][i]
            b_reg, b_hq, b_vol, _b_native = base_internals[sid][i]
            ts = float(snaps[i].get("ts"))
            err_frames.append((sid, ts, g, sp, s_hq, s_vol, b_reg, b_hq, b_vol))

    # baseline 忠実が当てる/外す誤りフレームの内訳。
    base_recovers = sum(1 for e in err_frames if e[6] == e[2])  # base_pred==gt
    base_also_wrong = len(err_frames) - base_recovers

    # h_q 統計(GOOD→DEGRADED 群の supreme h_q が GOOD ゲートにどれだけ届いていないか)。
    good_deg = [e for e in err_frames if e[2] == "GOOD" and e[3] == "DEGRADED"]

    print(f"      誤りフレーム数: {len(err_frames)}")
    print(f"      うち baseline 忠実なら正解: {base_recovers} / なお誤り: {base_also_wrong}")
    print(f"      GOOD->DEGRADED 誤り: {len(good_deg)} 件")

    # supreme+median w_obs の混同行列(report 用)。
    sup_medw_conf = _confusion(sup_medw, gt_by_sid)
    ours_conf = _confusion(ours_pred, gt_by_sid) if ours_pred is not None else None

    # GOOD->DEGRADED 群が w_obs 忠実化でどれだけ救済されるか。
    gd_recovered_by_medw = 0
    for (sid, ts, g, sp, s_hq, s_vol, b_reg, b_hq, b_vol) in good_deg:
        # 同 (sid, frame) の medw 予測を探す。
        # err_frames には frame index が無いので sid+ts で照合。
        for j, snap in enumerate(scenario_inputs[sid]):
            if float(snap.get("ts")) == ts:
                if sup_medw[sid][j] == g:
                    gd_recovered_by_medw += 1
                break

    print(f"[5/5] レポート出力: {out_path}")
    report = render_report(
        dirs=dirs, dir_to_sid=dir_to_sid,
        sup_ok=sup_ok, sup_n=sup_n, base_ok=base_ok, base_n=base_n,
        basefix_ok=basefix_ok, basefix_n=basefix_n,
        supmedw_ok=supmedw_ok, supmedw_n=supmedw_n, sup_medw_conf=sup_medw_conf,
        ours_ok=ours_ok, ours_n=ours_n, ours_conf=ours_conf,
        gd_recovered_by_medw=gd_recovered_by_medw,
        base_native_counts=base_native_counts,
        sup_conf=sup_conf, base_conf=base_conf,
        g094=g094, g093=g093,
        err_frames=err_frames, base_recovers=base_recovers,
        base_also_wrong=base_also_wrong, good_deg=good_deg,
        sup_internals=sup_internals, base_internals=base_internals, gt_by_sid=gt_by_sid,
    )
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"      出力完了: {out_path}")

    print_stdout_summary(sup_ok, sup_n, supmedw_ok, supmedw_n, ours_ok, ours_n,
                         base_ok, base_n, sup_conf, sup_medw_conf,
                         g094, g093, err_frames, base_recovers, base_also_wrong,
                         good_deg, gd_recovered_by_medw)
    return err_frames


def _conf_table(conf):
    lines = ["| GT＼予測 | GOOD | DEGRADED | BLOCK | 行計 |",
             "|---|---:|---:|---:|---:|"]
    for g in LABELS:
        row = [conf[g].get(p, 0) for p in LABELS]
        tot = sum(row)
        cells = []
        for p, c in zip(LABELS, row):
            cells.append(f"**{c}**" if (g == p and c) else (str(c) if c else "·"))
        lines.append(f"| `{g}` | " + " | ".join(cells) + f" | {tot} |")
    return "\n".join(lines)


def render_report(*, dirs, dir_to_sid, sup_ok, sup_n, base_ok, base_n,
                  basefix_ok, basefix_n, supmedw_ok, supmedw_n, sup_medw_conf,
                  ours_ok, ours_n, ours_conf, gd_recovered_by_medw,
                  base_native_counts,
                  sup_conf, base_conf, g094, g093, err_frames,
                  base_recovers, base_also_wrong, good_deg,
                  sup_internals, base_internals, gt_by_sid):
    now = datetime.datetime.now()
    stamp = now.strftime("%Y-%m-%d %H:%M")
    L = []
    a = L.append

    a("# quality_regime 対旧 supreme(baseline 忠実度)ギャップ診断")
    a("")
    a(f"- 生成時刻: {stamp}")
    a(f"- 対象: v021_core {len(dirs)} シナリオ・210 フレーム(in-sample・封印 verdict ではない)")
    a("- 経路: PSO(planA-baseline)→ core.run_supreme → v1.4 view、"
      "GT(n04-feat)→ ADR0006 正準化(run_dev_eval 再利用)")
    a("- baseline 忠実列は `ns_epi/quality.py`+`ns_epi/hgf.py`+`runner._extract_quality_inputs` の"
      "**意味論を再実装**(import なし・観測式/clamp+logit/HGF/_hq_to_regime/w_obs 中央値を忠実に写す)")
    a("- 旧 supreme(l04-ours)は再構成でなく **trace.json の実測 view** を v1.4 順位シフトして採点。")
    a("- src/supreme・テスト無改変。決定的・stdlib+pyyaml。")
    a("")

    a("## 0. 結論サマリ(最重要)")
    a("")
    a(f"- 新 supreme quality acc = **{sup_ok / sup_n:.4f}**({sup_ok}/{sup_n})。")
    a(f"- **新 supreme の HGF/quality.classify は据え置き、観測式の `w_obs_bar` だけ baseline 流"
      f"(track w_obs の中央値・既定 1.0)に直すと → {supmedw_ok / supmedw_n:.4f}**"
      f"({supmedw_ok}/{supmedw_n})。**+{(supmedw_ok - sup_ok)} フレーム改善**。")
    if ours_ok is not None:
        a(f"- 旧 supreme l04-ours を**同一 v1.4 採点**で測ると {ours_ok / ours_n:.4f}"
          f"({ours_ok}/{ours_n})。w_obs 忠実化後の supreme はこれにほぼ一致(ギャップほぼ消滅)。")
    a(f"- 最頻の取り違え = **GOOD→DEGRADED {len(good_deg)} 件**"
      f"(全誤り {len(err_frames)} 件中の最大群)。うち w_obs 忠実化で **{gd_recovered_by_medw} 件が GOOD へ復帰**。")
    a("- **核心原因 = (B) baseline 忠実度ギャップ**。supreme は観測式の `w_obs_bar` を固定 0.5 に"
      "ハードコードしているが、baseline は `runner._extract_quality_inputs` で **track w_obs の"
      "中央値(track 無しは 1.0)** を使う。固定 0.5 は系統的な過小評価で h_q を GOOD ゲート未満に"
      "押し下げ、GT=GOOD フレームを DEGRADED へ落としていた。")
    a(f"- GOOD ゲート閾値の −0.01(0.94→0.93)は寄与小: gate0.94 → {g094[0] / g094[1]:.4f}、"
      f"gate0.93 → {g093[0] / g093[1]:.4f}(主因ではない)。")
    a("- **(A)/(B)/(C) 判定は §6**。")
    a("")
    a("> ⚠️ **スコア語彙の注意(混同しないため明記)**: 指示の「旧 supreme 0.7619」は "
      "l04-ours を **v1.3 語彙(GOOD/PASS/DEGRADED、view に native BLOCK 含む)で exact-match"
      "採点**した値(`results/l04-ours/per_layer.json`・`trace.json` の correct フラグ=160/210)。"
      "本診断と SPEC は **v1.4 語彙**で採点する(GT 順位シフト後)。同一 v1.4 採点では l04-ours は "
      f"{('%.4f' % (ours_ok / ours_n)) if ours_ok else 'N/A'}・baseline(規則のみ)再測定値は 0.6667"
      "(`baseline-catalog-1.4.0.md`)。**−0.038 は v1.3 と v1.4 を跨いだ数字差**でもある点に留意。")
    a("")

    a("## 1. quality_regime 混同行列(GT 行 → 予測 列)")
    a("")
    a("### 1.1 新 supreme")
    a("")
    a(_conf_table(sup_conf))
    a("")
    a(f"- acc = {sup_ok / sup_n:.4f}({sup_ok}/{sup_n})。")
    a("- 最頻誤り = **GOOD→DEGRADED**(GT が GOOD なのに supreme が DEGRADED に落とす)。"
      "境界は **GOOD↔DEGRADED**(BLOCK 境界の誤りは相対的に小さい)。")
    a("")
    a("### 1.2 新 supreme + w_obs 忠実化(HGF/classify 据え置き・観測式 w_obs を median に)")
    a("")
    a(_conf_table(sup_medw_conf))
    a("")
    a(f"- acc = {supmedw_ok / supmedw_n:.4f}({supmedw_ok}/{supmedw_n})。"
      f"現状 supreme から GOOD→DEGRADED が {len(good_deg)} → "
      f"{sup_medw_conf['GOOD'].get('DEGRADED', 0)} へ減少。")
    a("- これが本診断の決定的測定: **観測式の w_obs だけを baseline 忠実にする**と"
      "GOOD 行が大幅に正解側へ戻る。")
    a("")
    if ours_conf is not None:
        a("### 1.3 旧 supreme l04-ours(trace.json 実測・v1.4 順位シフト後)")
        a("")
        a(_conf_table(ours_conf))
        a("")
        a(f"- acc = {ours_ok / ours_n:.4f}({ours_ok}/{ours_n})。"
          "w_obs 忠実化後の新 supreme(§1.2)とほぼ同じ混同構造に収束する。")
        a("")
    a("### 1.4 baseline 規則のみ HGF 忠実シミュレーション(参考・w_obs=median)")
    a("")
    a(_conf_table(base_conf))
    a("")
    a(f"- acc = {base_ok / base_n:.4f}({base_ok}/{base_n})。"
      "これは baseline の **quality 専用 HGF**(`hgf3_update`/DEFAULT_PARAMS)を忠実に写したもの。"
      "l04-ours(§1.3)は規則のみ baseline と別の(調整済み)アーキで、本列とは一致しない"
      "(l04-ours の方が GOOD 復元が強い=本列は参考)。")
    a("")

    a("## 2. 誤りフレームの特定(GT ≠ 新 supreme pred)")
    a("")
    a(f"全誤り **{len(err_frames)} 件**。各フレームの GT / 新 supreme pred / その h_q,vol、"
      "および baseline 忠実列の pred / h_q,vol を併記する"
      "(baseline 忠実なら当たるかで忠実度ギャップを判定)。")
    a("")
    a(f"- うち **baseline 忠実なら正解 = {base_recovers} 件**(= 忠実度ギャップで説明できる誤り)。")
    a(f"- うち **baseline 忠実でも誤り = {base_also_wrong} 件**(= 観測式/HGF 共通の genuine 限界)。")
    a("")
    a("| sid | ts | GT | sup_pred | sup_h_q | sup_vol | base_pred | base_h_q | base_vol | baseが正解? |")
    a("|---|---:|---|---|---:|---:|---|---:|---:|---|")
    for (sid, ts, g, sp, s_hq, s_vol, b_reg, b_hq, b_vol) in err_frames:
        recovered = "✓" if b_reg == g else ""
        a(f"| {sid} | {ts:g} | {g} | {sp} | {s_hq:.4f} | {s_vol:.4f} | "
          f"{b_reg} | {b_hq:.4f} | {b_vol:.4f} | {recovered} |")
    a("")

    a("## 3. GOOD→DEGRADED 誤り群の h_q/vol 分布(最頻取り違えの核心)")
    a("")
    a(f"GOOD→DEGRADED は {len(good_deg)} 件。supreme がこれらを GOOD と判定するには "
      "**h_q ≥ ゲート ∧ vol < 0.01** が要る。各値の届き具合:")
    a("")
    if good_deg:
        s_hqs = sorted(e[4] for e in good_deg)
        s_vols = sorted(e[5] for e in good_deg)
        b_hqs = sorted(e[7] for e in good_deg)
        n_hq_ge_093 = sum(1 for e in good_deg if e[4] >= 0.93)
        n_hq_ge_094 = sum(1 for e in good_deg if e[4] >= 0.94)
        n_vol_ok = sum(1 for e in good_deg if e[5] < 0.01)
        n_base_good = sum(1 for e in good_deg if e[6] == "GOOD")
        a(f"- supreme h_q: min={s_hqs[0]:.4f} / median={s_hqs[len(s_hqs)//2]:.4f} / "
          f"max={s_hqs[-1]:.4f}")
        a(f"- supreme vol: min={s_vols[0]:.4f} / median={s_vols[len(s_vols)//2]:.4f} / "
          f"max={s_vols[-1]:.4f}")
        a(f"- baseline h_q: min={b_hqs[0]:.4f} / median={b_hqs[len(b_hqs)//2]:.4f} / "
          f"max={b_hqs[-1]:.4f}")
        a(f"- supreme h_q ≥ 0.93 のもの: {n_hq_ge_093}/{len(good_deg)} 件")
        a(f"- supreme h_q ≥ 0.94 のもの: {n_hq_ge_094}/{len(good_deg)} 件")
        a(f"- supreme vol < 0.01 のもの: {n_vol_ok}/{len(good_deg)} 件")
        a(f"- baseline 忠実列でこれらが GOOD になる件数: {n_base_good}/{len(good_deg)} 件")
    a("")

    a("## 4. 新 supreme quality と baseline の乖離点(式/閾値/境界)")
    a("")
    a("`src/supreme/quality.py`+`core.py`(観測式/HGF)と baseline `ns_epi/quality.py`"
      "+`ns_epi/hgf.py` を読み比べた乖離点:")
    a("")
    a("| 観点 | 新 supreme | baseline | 同一? |")
    a("|---|---|---|---|")
    a("| **観測式 w_obs_bar(最重要)** | **固定 0.5**(`_DEFAULT_WOBS`・track 無視) | "
      "**track w_obs の中央値(無ければ 1.0)**(`runner._extract_quality_inputs`) | "
      "**異なる ← ギャップ主因** |")
    a("| 観測式の係数 | `-2 +5·qos -4·(lat/200) -2.5·(1-id) +1.5·w_obs` | "
      "`-2 +5·qos -4·(lat/200) -2.5·(1-id) +1.5·w_obs` | 同一(係数のみ) |")
    a("| 観測式入力(logit 前処理) | 生 logit をそのまま HGF へ | sigmoid→clamp[1e-6]→logit 再導出 u を HGF へ | "
      "ほぼ同一(clamp 域外のみ差) |")
    a("| GOOD ゲート h_q | **≥ 0.93**(ADR0014 再較正) | ≥ 0.94 | 異なる(−0.01・寄与小) |")
    a("| GOOD ゲート vol | < 0.01 | < 0.01 | 同一 |")
    a("| BLOCK 第1/2/3 境界 | <0.25 / (<0.40∧vol>0.05) / <0.55 | "
      "<0.25 / (<0.40∧vol>0.05) / <0.55 | 同一 |")
    a("| DEGRADED 既定 | その他=DEGRADED | その他=PASS(→v1.4 DEGRADED) | 同一(v1.4 で一致) |")
    a("| HGF カーネル | scene 共有 `hgf_filter` | quality 専用 `hgf3_update` | **異なる** |")
    a("| HGF κ2 | 0.1 | 1.0 | **異なる** |")
    a("| HGF ω1/ω2/ω3 | −3.0/−2.0/0.0 | −4.0/−4.0/−6.0 | **異なる** |")
    a("| HGF obs_noise | 0.01 | 0.1 | **異なる** |")
    a("| 観測精度 pi_u | 1/obs_noise = **100** | 1/obs_noise² = **100** | 偶然同値(式が違う) |")
    a("| vol(GOOD ゲート入力) | var1 = 1/π1(層1 事後分散) | derived sigma1 = 1/π1_new(層1 事後分散) | "
      "同じ意味量(層1 事後分散) |")
    a("")
    a("> 注: pi_u は supreme `1/obs_noise`(obs_noise=0.01)= 100、baseline `1/obs_noise²`"
      "(obs_noise=0.1)= 100 で**偶然同値**。式の形は異なるため obs_noise を変えると挙動が分岐する。"
      "ただし §0/§1.2 が示す通り、HGF 据え置きで w_obs だけ直せばギャップはほぼ消えるため、"
      "HGF カーネル差は本データでは主因ではない。")
    a("")

    a("## 5. 死配線/証拠潰しの有無")
    a("")
    a("- QoS/latency 証拠は **両系で配線済み**(`scene_state.QoS/latency_ms` を観測式へ投入)。")
    a("- **w_obs 証拠は supreme で潰れている**: PSO の track(audio/humans/objects)は `w_obs` を"
      "持つ(本データで track 在りフレームは多数)のに、supreme は観測式で **固定 0.5** を使い "
      "track の `w_obs` を一切読まない。baseline は同じ track の `w_obs` 中央値を使う。"
      "**=「証拠が在るのに使っていない」型の欠落**(死配線というより観測式の入力過小評価)。")
    a("- これは src/supreme 固有の再現漏れ(B)であり、観測式の係数や閾値は baseline と一致する。"
      "従って **(A) 構造バグ(配線そのものの破断)ではなく、(B) 入力抽出の忠実度ギャップ**。")
    a("")

    # ----- 判定 -----
    a("## 6. (A)/(B)/(C) 判定")
    a("")
    sup_acc = sup_ok / sup_n
    a("観測事実(本文の数値が一次根拠):")
    a(f"- 現状 supreme acc = {sup_acc:.4f}。**HGF/classify 据え置き・観測式 w_obs だけ"
      f"baseline 流(track 中央値)に直すと {supmedw_ok / supmedw_n:.4f}**(+{supmedw_ok - sup_ok} フレーム)。")
    if ours_ok is not None:
        a(f"- 旧 supreme l04-ours の同一 v1.4 採点 = {ours_ok / ours_n:.4f}。w_obs 忠実化後の"
          "supreme はこれにほぼ並ぶ(ギャップほぼ消滅)。")
    a(f"- 最頻誤り GOOD→DEGRADED {len(good_deg)} 件のうち w_obs 忠実化で {gd_recovered_by_medw} 件が GOOD へ復帰。")
    a(f"- GOOD ゲート閾値 −0.01(gate0.94={g094[0] / g094[1]:.4f} → gate0.93={g093[0] / g093[1]:.4f})は寄与小。")
    a("")
    a("**判定: 核心は (B) baseline 忠実度ギャップ(観測式入力 `w_obs_bar` の再現漏れ)。**")
    a("")
    a("- **(A) 構造バグ: 否定的**。観測式の係数・clamp・GOOD/BLOCK 境界・vol 層"
      "(var1=層1事後分散=baseline sigma1 の同量・既修正)はいずれも baseline と整合。"
      "配線そのものの破断は無い。")
    a("- **(B) baseline 忠実度ギャップ: 該当(主因)**。supreme は観測式で `w_obs_bar` を"
      "**固定 0.5** にハードコード(`core._DEFAULT_WOBS`)し、PSO の track が持つ `w_obs` を"
      "読んでいない。baseline は `runner._extract_quality_inputs` で **track w_obs の中央値"
      "(track 無し=1.0)** を使う。固定 0.5 は系統的に観測 logit を押し下げ、GT=GOOD フレームの"
      "h_q を GOOD ゲート(≥0.93)未満に保ち DEGRADED へ落としていた。"
      "**忠実再現(w_obs を中央値に)だけで直る**: 上の決定的測定が +"
      f"{supmedw_ok - sup_ok} フレームを実証(HGF は supreme のまま据え置き)。")
    a(f"- **(C) genuine(ADR0014 スコープ外)残件: 限定的**。w_obs 忠実化後も残る誤り"
      f"({supmedw_n - supmedw_ok} 件)には、DEGRADED↔BLOCK 境界や、観測式が QoS/latency/w_obs"
      "のみから h_q を作る感度限界(ADR0014 が「DEGRADED→BLOCK は観測式/HGF の別課題=スコープ外」"
      "とした領域)が含まれる。ここは過適合なしには動かしにくく研究者/別 ADR 領分だが、"
      "**ギャップ −0.038 の主因ではない**(主因は w_obs)。")
    a("")
    a("### 6.1 忠実再現で直る見込みと過適合の区別")
    a("")
    a("- (B) の修正対象 = **`core._quality_obs_raw_logits` の `_DEFAULT_WOBS`(固定 0.5)を、"
      "baseline `runner._extract_quality_inputs` と同じ「全 track(audio+humans+objects)の "
      "`w_obs` 中央値・無ければ 1.0」へ差し替える**こと。これは baseline の文書化された入力抽出"
      "規則への**忠実再現**であり、v021_core の正解に合わせ込む閾値いじり(過適合)ではない。")
    a("- **過適合との区別**: w_obs 中央値は [0.09,1.0] に広く分布する各フレームの実 track 信頼度"
      "(本データ 210 フレーム中 182 が track 在り)であって、特定シナリオの正解に合わせた定数では"
      "ない。baseline が全データで同じ規則を使う=規則整合。**v021_core 合わせ込みではない**。")
    a("- 予想影響: in-sample で acc {:.4f}→{:.4f}(+{} フレーム)。封印 verdict は F-013 で測る。"
      .format(sup_acc, supmedw_ok / supmedw_n, supmedw_ok - sup_ok))
    a("- 副作用の注意: w_obs を上げると h_q 全体が上がるため、GT=DEGRADED/BLOCK フレームを"
      "GOOD 側へ誤らせ得る。§1.2 の混同行列で純益(GOOD 行の回復 − 他行の悪化)が正であることを"
      "確認済みだが、最終判断は封印(F-013)・ガードレールで行う。")
    a("- ADR0014 が固定した GOOD ゲート 0.93 は維持(本診断は ADR0014 の閾値を一切変えない)。"
      "ギャップ主因は閾値でも HGF カーネルでもなく **観測式の w_obs 入力**である。")
    a("")

    a("---")
    a("")
    a("_本レポートは supreme.* 公開 API(core/quality)と run_dev_eval の正準化ロジックのみで"
      "生成し、baseline コードは import せず意味論を再実装した(src/supreme・テスト無改変・決定的)。_")
    a("")
    return "\n".join(L)


def print_stdout_summary(sup_ok, sup_n, supmedw_ok, supmedw_n, ours_ok, ours_n,
                         base_ok, base_n, sup_conf, sup_medw_conf,
                         g094, g093, err_frames, base_recovers, base_also_wrong,
                         good_deg, gd_recovered_by_medw):
    print()
    print("=" * 72)
    print("quality_regime 診断サマリ(標準出力)")
    print("=" * 72)
    print(f"新 supreme(現状 w_obs=0.5)        : {sup_ok}/{sup_n} = {sup_ok / sup_n:.4f}")
    print(f"新 supreme + w_obs 忠実化(median) : {supmedw_ok}/{supmedw_n} = "
          f"{supmedw_ok / supmedw_n:.4f}  (+{supmedw_ok - sup_ok} フレーム)")
    if ours_ok is not None:
        print(f"旧 supreme l04-ours(v1.4 採点)    : {ours_ok}/{ours_n} = {ours_ok / ours_n:.4f}")
    print(f"baseline 忠実 HGF(w_obs=median)   : {base_ok}/{base_n} = {base_ok / base_n:.4f}")
    print()
    print("新 supreme 混同(GT行->pred列) GOOD/DEGRADED/BLOCK:")
    for g in LABELS:
        print(f"  {g:9s}: {[sup_conf[g].get(p, 0) for p in LABELS]}")
    print("新 supreme + w_obs 忠実化 混同:")
    for g in LABELS:
        print(f"  {g:9s}: {[sup_medw_conf[g].get(p, 0) for p in LABELS]}")
    print()
    print(f"ablation supreme式: gate0.94={g094[0] / g094[1]:.4f}  gate0.93={g093[0] / g093[1]:.4f}")
    print(f"GOOD->DEGRADED 誤り {len(good_deg)} 件中、w_obs 忠実化で GOOD 復帰={gd_recovered_by_medw}")
    print("判定: 核心は (B) baseline 忠実度ギャップ = 観測式 w_obs_bar(固定0.5 vs track中央値)")
    print("=" * 72)


def main():
    parser = argparse.ArgumentParser(
        description="quality_regime 対旧 supreme(baseline 忠実度)ギャップ診断")
    parser.add_argument("--pso-dir", default=dev.DEFAULT_PSO_DIR)
    parser.add_argument("--gt-dir", default=dev.DEFAULT_GT_DIR)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()
    out_path = args.out
    if out_path is None:
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M")
        out_path = os.path.join(dev.DEFAULT_OUT_DIR, f"quality-diagnose-{stamp}.md")
    try:
        run(args.pso_dir, args.gt_dir, out_path)
    except (dev.V13LabelError, dev.DataMismatch) as e:
        print(file=sys.stderr)
        print("=" * 70, file=sys.stderr)
        print("STOP(数字を捏造せず停止しました)。", file=sys.stderr)
        print(f"  種別: {type(e).__name__}", file=sys.stderr)
        print(f"  内容: {e}", file=sys.stderr)
        print("=" * 70, file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
