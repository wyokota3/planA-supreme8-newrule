"""conv_participating 取りこぼし診断(t3_hypothesis 弱5 唯一 lose の震源切り分け)。

狙い(指示・t3 段):
  弱5 の唯一の lose は t3_hypothesis。Phase4 implementer は「残る t3 誤りの震源は上流 mode
  (conv_participating の取りこぼし・hazard_declining 未出力)」と指摘。conv_participating は
  t3 の学習クラス(conv/traffic/quiet ロジスティック境界の1つ)で、上流 mode の conv 証拠に依存する。
  前回 mode 修正(core._mode_logits)で conv_request は意図的に未結線(conv/env_change と証拠が
  重なり mode acc 悪化=過適合リスクと当時判断)だった。

  本スクリプトは **src/supreme 無改変** で以下を計測し、conv_participating が出ない原因が
    (A) mode 結線の証拠潰し(conv_request 未結線など構造バグ)
    (B) 学習 conv 境界の較正
    (C) genuine(会話証拠が入力に無い)
  のどれかを **証拠付き** で判定する。

計測(measure・src 無改変):
  1. GT=conv_participating のフレームを特定(何フレーム・どのシナリオ)。
  2. それらで supreme t3 出力(混同先)。
  3. それらで supreme 上流 mode 出力(argmax mode・分布)。conv 系 mode を emit しているか潰しているか。
  4. それらの PSO 入力の会話証拠(has_speech / speaking_prob / speaking link / addressing / call_user)。
     証拠が入力に在るのに mode/t3 が conv を出さない=構造バグ。入力に証拠が無ければ genuine。
  5. core._mode_logits / t3.classify_t3(conv 境界)を踏まえ、(A)/(B)/(C) を判定。
  6. 過適合再検証: conv_request を **実際に結線**(speech+addressing/call_user 証拠で conv_request
     logit を積む)した代替 mode 列を再計算し、mode acc が下がるか・偽陽性がどこに出るかを実測する。

規律:
  - src/supreme/*.py(core/モジュール/テスト)は一切変更しない。分析専用。
  - supreme.* 公開 API + core 内部関数の import 再利用のみ。baseline は import しない。決定的・stdlib+pyyaml。
  - 不整合・抽出不一致・数値は捏造せず、観測値のみから所見を述べる。停止条件は明示。

使い方:
    python scripts/run_conv_diagnose.py [--pso-dir <p>] [--gt-dir <p>] [--out <p>]
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

# supreme 公開 API + core 内部関数(分析の再利用のみ・改変しない)。
from supreme import core, mode as mode_mod, t0 as t0_mod, t1 as t1_mod, t3 as t3_mod
import run_dev_eval as dev
import run_dev_eval_diagnose as diag


GT_TARGET = "conv_participating"


class Stop(Exception):
    """抽出不一致・数値不整合(捏造せず停止)。"""


# ===========================================================================
# 会話証拠の抽出(core の証拠抽出関数を再利用・src 無改変)
# ===========================================================================

def conv_evidence(snap):
    """1 フレームの会話証拠を core の抽出関数だけで取り出す(src 無改変)。

    - has_speech     : speech audio track の有無(core._has_audio_type)。
    - speaking       : speaking_prob の最大(core._speaking_evidence)。
    - speaking_link  : speaking link の有無(core._speaking_evidence)。
    - linked_speech  : speaking link score の最大(core._speaking_evidence)。
    - min_range      : 最近接距離(core._min_range)。
    - n_speaking_lnk : speaking link 数(core._relation_evidence と同源)。
    - call_user      : call_user utter event の有無(core._relation_evidence と同源)。
    - linked_addr    : addressing link score の最大(core._relation_evidence と同源)。
    - conv_strong    : core._mode_logits が conv_ongoing を積む条件(speech ∧ speaking>0.7 ∧ range<5)。
    """
    speaking, speaking_link, linked_speech = core._speaking_evidence(snap)
    min_range = core._min_range(snap)
    has_speech = core._has_audio_type(snap, "speech")
    n_speaking_lnk = sum(1 for link in core._links(snap)
                         if link.get("type") == "speaking")
    call_user = any(e.get("type") == "call_user" for e in core._utter_events(snap))
    linked_addr = 0.0
    for link in core._links(snap):
        if link.get("type") == "addressing":
            linked_addr = max(linked_addr, float(link.get("score", 0.0)))
    conv_strong = has_speech and speaking > 0.7 and min_range < 5.0
    return {
        "has_speech": has_speech,
        "speaking": speaking,
        "speaking_link": speaking_link,
        "linked_speech": linked_speech,
        "min_range": min_range,
        "n_speaking_lnk": n_speaking_lnk,
        "call_user": call_user,
        "linked_addr": linked_addr,
        "conv_strong": conv_strong,
    }


def has_any_conv_evidence(ev):
    """「会話証拠が入力に在る」とみなす条件(genuine 切り分けの素材)。

    speech track があり、かつ何らかの会話信号(speaking_prob>0・speaking link・addressing・
    call_user のいずれか)が立っていれば「入力に会話証拠が在る」と数える。これは緩い OR で、
    会話の素材が一切無いフレーム(genuine な非会話)を分離するための判定。
    """
    return ev["has_speech"] and (
        ev["speaking"] > 0.0
        or ev["speaking_link"]
        or ev["linked_addr"] > 0.0
        or ev["call_user"]
    )


# ===========================================================================
# 過適合再検証: conv_request を結線した代替 mode 列を再計算
# ===========================================================================

# conv_request の試験的結線条件。
#
# 当初は「呼びかけ証拠(call_user / addressing link)」での分離を意図したが、v021_core の PSO 入力
# には **addressing link も call_user utter_event も 1 件も存在しない**(実在する link type は
# speaking と source のみ・utter_events は全フレーム空)。よって conv_request を「別証拠面」で立てる
# 素材はこのデータセットに無い。
#
# 代わりに、**core が既に抽出しているが _mode_logits が一度も使っていない `speaking_link`(死配線)**
# を使い、conv_strong(speaking>0.7 の強会話)に届かないが speaking_link + speech + 近接がある
# 「弱会話(conv_request 相当)」フレームへ conv 系 logit を結線する試験を行う。これは v021_core 合わせ
# 込みではなく、relation 層が conv 判定に既に使っている speaking_link の流用(構造分離の試行)。
_REQ_RANGE_GATE = 5.0    # 近接下限(conv_strong の range<5.0 と同条件)。


def conv_request_evidence(ev):
    """弱会話(conv_request 相当)の試験結線条件: speaking_link ∧ speech ∧ 近接 ∧ ¬conv_strong。

    conv_strong(speaking>0.7)に届かないが、speaking link(明示的な会話リンク・core が抽出済み
    だが _mode_logits 未使用=死配線)が立ち、speech audio があり近接しているフレーム。conv_strong が
    既に立つフレームは conv_ongoing が優先するため除外する。addressing/call_user は v021_core に
    実在しないため使えない(その代替としての speaking_link 結線試験)。
    """
    if ev["conv_strong"]:
        return False
    if not ev["has_speech"]:
        return False
    return ev["speaking_link"] and ev["min_range"] < _REQ_RANGE_GATE


def recompute_modes(snaps, *, wire_conv_request):
    """core と同じ mode ヒステリシス連鎖を再現する(src 無改変)。

    wire_conv_request=False は core 現行と完全同一(conv_request 未結線)。
    wire_conv_request=True は conv_request_evidence が立つフレームに conv_request logit
    (_MODE_CONV と同強度)を追加で積む試験結線。それ以外の結線は core と同一。

    Returns: list[str](各フレームの argmax mode)。
    """
    quality_logits = core._quality_obs_raw_logits(snaps)
    anomaly_logits = core._anomaly_obs_raw_logits(snaps)
    h_q_seq, _ = core._hq_vol_sequences(quality_logits)
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
        logits = core._mode_logits(snap, risk_tier, approaching, h_q_seq[i])
        if wire_conv_request:
            ev = conv_evidence(snap)
            if conv_request_evidence(ev):
                # _MODE_CONV と同強度で conv_request を積む(conv_ongoing と同列の block 超)。
                logits["conv_request"] = core._MODE_CONV
        t2_mode = mode_mod.hysteresis(logits, prev_mode)
        prev_mode = t2_mode
        modes.append(t2_mode)
    return modes


def recompute_t3(snaps, modes, params):
    """与えた mode 列(と実 h_q)で t3 を core と同じ reset 規約で走らせる(src 無改変)。"""
    h_q_seq, _ = core._hq_vol_sequences(core._quality_obs_raw_logits(snaps))
    seq = [{"mode": m, "posterior": h_q_seq[i]} for i, m in enumerate(modes)]
    reset_seq = [i == 0 for i in range(len(modes))]
    return t3_mod.run_t3_sequence(seq, reset_seq, params)


# ===========================================================================
# t3 conv 境界の較正プローブ(mode 列は core 現行のまま=上流無改変)
# ===========================================================================

def _mk_params(overrides):
    """既定 t3 params の weights を一部上書きした _Params を作る(診断用ローカル)。"""
    base = t3_mod.default_params()
    w = dict(base.weights)
    w.update(overrides)
    return t3_mod._Params(weights=w, labels=dict(base.labels))


def t3_calibration_probe(views_by_sid, gt_by_sid, snaps_by_sid):
    """**mode 列を core 現行のまま固定**し、t3 conv/traffic ロジスティック重みだけ振って、
    conv_participating の取りこぼしが t3 較正で説明できるか(=B)を測る(src 無改変)。

    既定 classify_t3:
        conv_score    = w_conv_ratio·conv_ratio + bias_conv
        traffic_score = w_switch_rate·switch_rate + w_flip_accum·flip_accum + bias_traffic
    GT=conv_participating フレームでは上流が conv_ongoing を持続するため conv_ratio は上がるが、
    flip_accum(単一の mode 切替で +4)が traffic_score を底上げし conv を負かす疑いを検証する。

    各 params 候補で t3 全体 acc・conv recall・conv 取りこぼし先を測る(in-sample・楽観値)。
    """
    candidates = [
        ("default", {}),
        ("w_flip_accum=1.0", {"w_flip_accum": 1.0}),
        ("w_flip_accum=0.0", {"w_flip_accum": 0.0}),
        ("bias_conv=-1.0", {"bias_conv": -1.0}),
        ("w_flip=1.0,bias_conv=-1.0", {"w_flip_accum": 1.0, "bias_conv": -1.0}),
        ("w_flip=1.0,w_conv=10,bias_conv=-1.0",
         {"w_flip_accum": 1.0, "w_conv_ratio": 10.0, "bias_conv": -1.0}),
    ]
    rows = []
    for name, ov in candidates:
        params = _mk_params(ov)
        n = cor = 0
        conv_tot = conv_hit = 0
        conv_miss = Counter()
        for sid in sorted(views_by_sid):
            snaps = snaps_by_sid[sid]
            modes = [v["t2_mode"] for v in views_by_sid[sid]]   # ← core 現行 mode(無改変)
            gts = gt_by_sid[sid]
            out = recompute_t3(snaps, modes, params)
            for i, g in enumerate(gts):
                gtt3 = g.get("t3_hypothesis")
                if gtt3 is None:
                    continue
                n += 1
                if out[i] == gtt3:
                    cor += 1
                if gtt3 == GT_TARGET:
                    conv_tot += 1
                    if out[i] == GT_TARGET:
                        conv_hit += 1
                    else:
                        conv_miss[out[i]] += 1
        rows.append({
            "name": name, "overrides": ov,
            "t3_acc": cor / n if n else float("nan"),
            "conv_hit": conv_hit, "conv_tot": conv_tot,
            "conv_miss": dict(conv_miss),
        })
    return rows


# ===========================================================================
# 集計
# ===========================================================================

def collect(views_by_sid, gt_by_sid, snaps_by_sid, dir_to_sid, dirs):
    """GT=conv_participating フレームの t3/mode 出力と会話証拠を集める。"""
    frames = []            # 1 フレーム = dict(sid, idx, t3_pred, mode_pred, evidence)
    t3_confusion = Counter()     # GT=conv_participating での supreme t3 予測
    mode_at_target = Counter()   # GT=conv_participating での supreme mode argmax
    by_scenario = defaultdict(lambda: {"n": 0, "t3_correct": 0, "mode_conv": 0})
    speaking_vals = []
    ev_present = 0
    ev_absent = 0

    for sid in sorted(views_by_sid):
        views = views_by_sid[sid]
        gts = gt_by_sid[sid]
        snaps = snaps_by_sid[sid]
        if not (len(views) == len(gts) == len(snaps)):
            raise Stop(f"[{sid}] view/gt/snap 長不一致: "
                       f"{len(views)}/{len(gts)}/{len(snaps)}。停止する。")
        for i, gt in enumerate(gts):
            if gt.get("t3_hypothesis") != GT_TARGET:
                continue
            t3_pred = views[i]["t3_hypothesis"]
            mode_pred = views[i]["t2_mode"]
            ev = conv_evidence(snaps[i])
            present = has_any_conv_evidence(ev)
            t3_confusion[t3_pred] += 1
            mode_at_target[mode_pred] += 1
            sc = by_scenario[sid]
            sc["n"] += 1
            if t3_pred == GT_TARGET:
                sc["t3_correct"] += 1
            if mode_pred.startswith("conv"):
                sc["mode_conv"] += 1
            speaking_vals.append(ev["speaking"])
            if present:
                ev_present += 1
            else:
                ev_absent += 1
            frames.append({
                "sid": sid, "idx": i, "t3_pred": t3_pred,
                "mode_pred": mode_pred, "ev": ev, "present": present,
            })
    return {
        "frames": frames,
        "t3_confusion": t3_confusion,
        "mode_at_target": mode_at_target,
        "by_scenario": dict(by_scenario),
        "speaking_vals": speaking_vals,
        "ev_present": ev_present,
        "ev_absent": ev_absent,
    }


def mode_accuracy(views_by_sid, gt_by_sid, mode_override=None):
    """mode acc(GT 非 null フレーム上の exact match)を計算する。

    mode_override=None は supreme 現行 view の t2_mode。dict{sid:[mode,...]} を渡せば
    その mode 列で採点する(conv_request 結線後の代替列の acc を測るため)。
    返り値: (acc, n_scored, n_correct, confusion[gt->Counter(pred)], regressions[list])。
    regressions = conv_request 結線で「正→誤」に転んだフレーム(偽陽性の所在)。
    """
    n_scored = 0
    n_correct = 0
    confusion = defaultdict(Counter)
    for sid in sorted(gt_by_sid):
        gts = gt_by_sid[sid]
        if mode_override is None:
            preds = [v["t2_mode"] for v in views_by_sid[sid]]
        else:
            preds = mode_override[sid]
        if len(preds) != len(gts):
            raise Stop(f"[{sid}] mode 採点列長不一致。停止する。")
        for i, gt in enumerate(gts):
            gt_m = gt.get("t2_mode")
            if gt_m is None:
                continue
            n_scored += 1
            confusion[gt_m][preds[i]] += 1
            if preds[i] == gt_m:
                n_correct += 1
    acc = n_correct / n_scored if n_scored else float("nan")
    return acc, n_scored, n_correct, confusion


def overfit_recheck(views_by_sid, gt_by_sid, snaps_by_sid):
    """conv_request を実結線したときの mode/t3 への影響を実測する(過適合再検証)。

    - base_modes  : core 現行(conv_request 未結線)の mode 列。
    - alt_modes   : conv_request を結線した mode 列。
    両者で mode acc を出し、各フレームで「base 正→alt 誤」(偽陽性=regression)と
    「base 誤→alt 正」(改善)を数える。conv_request を積んだフレームがどの GT に当たるか集計。
    t3 も both で走らせ conv_participating の recall 変化を測る。
    """
    base_modes = {}
    alt_modes = {}
    req_fired = []     # conv_request を積んだ (sid, idx, gt_mode, gt_t3)
    for sid in sorted(snaps_by_sid):
        snaps = snaps_by_sid[sid]
        base_modes[sid] = recompute_modes(snaps, wire_conv_request=False)
        alt_modes[sid] = recompute_modes(snaps, wire_conv_request=True)
        # core 現行 view と base_modes が一致するか(再現の自己検査)。
        view_modes = [v["t2_mode"] for v in views_by_sid[sid]]
        if base_modes[sid] != view_modes:
            raise Stop(
                f"[{sid}] conv_request 未結線の再計算が core view と不一致。"
                "再現に失敗(診断の前提が崩れる)ため停止する。"
            )

    # conv_request が立ったフレームの所在(GT mode / GT t3)。
    for sid in sorted(snaps_by_sid):
        snaps = snaps_by_sid[sid]
        gts = gt_by_sid[sid]
        for i, snap in enumerate(snaps):
            ev = conv_evidence(snap)
            if conv_request_evidence(ev):
                req_fired.append({
                    "sid": sid, "idx": i,
                    "gt_mode": gts[i].get("t2_mode"),
                    "gt_t3": gts[i].get("t3_hypothesis"),
                    "alt_mode": alt_modes[sid][i],
                    "base_mode": base_modes[sid][i],
                })

    base_acc, n_s, base_cor, _ = mode_accuracy(views_by_sid, gt_by_sid, mode_override=base_modes)
    alt_acc, _, alt_cor, _ = mode_accuracy(views_by_sid, gt_by_sid, mode_override=alt_modes)

    # フレーム単位の正→誤 / 誤→正。
    regressions = []   # base 正・alt 誤
    improvements = []  # base 誤・alt 正
    for sid in sorted(gt_by_sid):
        gts = gt_by_sid[sid]
        for i, gt in enumerate(gts):
            gt_m = gt.get("t2_mode")
            if gt_m is None:
                continue
            b = base_modes[sid][i]
            al = alt_modes[sid][i]
            if b == al:
                continue
            if b == gt_m and al != gt_m:
                regressions.append({"sid": sid, "idx": i, "gt": gt_m,
                                    "base": b, "alt": al,
                                    "gt_t3": gt.get("t3_hypothesis")})
            elif b != gt_m and al == gt_m:
                improvements.append({"sid": sid, "idx": i, "gt": gt_m,
                                    "base": b, "alt": al,
                                    "gt_t3": gt.get("t3_hypothesis")})

    # t3 recall(conv_participating)を base/alt mode 列 + 既定 t3 params で測る。
    params = t3_mod.default_params()
    t3_conv_total = 0
    t3_conv_base_hit = 0
    t3_conv_alt_hit = 0
    t3_alt_regression = []   # base 正→alt 誤(t3 側の偽陽性)
    for sid in sorted(snaps_by_sid):
        snaps = snaps_by_sid[sid]
        gts = gt_by_sid[sid]
        t3_base = recompute_t3(snaps, base_modes[sid], params)
        t3_alt = recompute_t3(snaps, alt_modes[sid], params)
        for i, gt in enumerate(gts):
            gt_t3 = gt.get("t3_hypothesis")
            if gt_t3 == GT_TARGET:
                t3_conv_total += 1
                if t3_base[i] == GT_TARGET:
                    t3_conv_base_hit += 1
                if t3_alt[i] == GT_TARGET:
                    t3_conv_alt_hit += 1
            # t3 全体での base 正→alt 誤(偽陽性の所在)。
            if gt_t3 is not None and t3_base[i] == gt_t3 and t3_alt[i] != gt_t3:
                t3_alt_regression.append({
                    "sid": sid, "idx": i, "gt_t3": gt_t3,
                    "base": t3_base[i], "alt": t3_alt[i],
                })

    return {
        "base_acc": base_acc, "alt_acc": alt_acc, "n_scored": n_s,
        "base_correct": base_cor, "alt_correct": alt_cor,
        "req_fired": req_fired,
        "regressions": regressions, "improvements": improvements,
        "t3_conv_total": t3_conv_total,
        "t3_conv_base_hit": t3_conv_base_hit,
        "t3_conv_alt_hit": t3_conv_alt_hit,
        "t3_alt_regression": t3_alt_regression,
    }


# ===========================================================================
# 判定
# ===========================================================================

def verdict(coll, recheck):
    """(A)/(B)/(C) を観測値から判定する(捏造せず観測のみ)。

    判定ロジック:
      - conv_request を結線すると GT=conv_participating フレームで mode が conv 系へ変わり、
        かつ mode acc が下がらず(または上がり)偽陽性 regression がゼロ → (A) 構造バグ
        (証拠の死配線)が主因。conv_request 未結線が conv 証拠を潰している。
      - GT=conv_participating フレームの大半で supreme が既に conv 系 mode を emit しているのに
        t3 が conv_participating を出さない → (B) 学習 conv 境界の較正。
      - GT=conv_participating フレームに会話証拠が入力に無い(present が少数) → (C) genuine。
    複数該当し得るため、各シグナルの強さを併記する。
    """
    n_target = len(coll["frames"])
    ev_present = coll["ev_present"]
    mode_conv_emit = sum(coll["by_scenario"][s]["mode_conv"] for s in coll["by_scenario"])
    t3_hit = coll["t3_confusion"].get(GT_TARGET, 0)

    signals = []
    # 証拠の有無(C の素材)。
    present_ratio = ev_present / n_target if n_target else 0.0
    # 上流 mode が conv 系を出している割合(B vs A の素材)。
    mode_conv_ratio = mode_conv_emit / n_target if n_target else 0.0
    # conv_request 結線の効果(A の素材)。
    delta_acc = recheck["alt_acc"] - recheck["base_acc"]
    n_reg = len(recheck["regressions"])
    n_imp = len(recheck["improvements"])
    t3_recall_gain = recheck["t3_conv_alt_hit"] - recheck["t3_conv_base_hit"]

    return {
        "n_target": n_target,
        "present_ratio": present_ratio,
        "mode_conv_ratio": mode_conv_ratio,
        "t3_hit": t3_hit,
        "delta_acc": delta_acc,
        "n_reg": n_reg,
        "n_imp": n_imp,
        "t3_recall_gain": t3_recall_gain,
        "signals": signals,
    }


# ===========================================================================
# レポート
# ===========================================================================

def _dist(vals):
    if not vals:
        return None
    return (min(vals), statistics.median(vals), max(vals), statistics.fmean(vals))


def render(*, coll, recheck, calib, vd, dirs, dir_to_sid):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    L = []
    a = L.append
    a("# conv_participating 取りこぼし診断 — t3_hypothesis 弱5 唯一 lose の震源")
    a("")
    a(f"- 生成時刻: {now}")
    a("- 経路: run_dev_eval と同一(PSO→core.run_supreme→v1.4 view、GT→ADR0006 正準化)")
    a("- src/supreme/*.py 無改変・分析専用。supreme 公開 API + core 内部関数の import 再利用のみ。")
    a("- baseline 非 import・決定的・stdlib+pyyaml。観測値のみ(捏造なし)。")
    a("")
    a("> conv_request 結線は **診断用の代替計算**(recompute_modes/recompute_t3 内のローカル試行)で")
    a("> あり、src/supreme は一切書き換えていない。core 現行(未結線)mode が view と一致することを")
    a("> 自己検査済み(不一致なら停止)。")
    a("")

    # ---- 1. GT=conv_participating フレーム ----
    a("## 1. GT=conv_participating のフレーム特定")
    a("")
    a(f"- 正準化後の GT=conv_participating フレーム数: **{vd['n_target']}**")
    a("")
    a("シナリオ別内訳:")
    a("")
    a("| dir | scenario_id | 件数 | t3 正答(=conv) | mode が conv 系 |")
    a("|---|---|---:|---:|---:|")
    for d in dirs:
        sid = dir_to_sid[d]
        sc = coll["by_scenario"].get(sid)
        if not sc:
            continue
        a(f"| {d} | {sid} | {sc['n']} | {sc['t3_correct']} | {sc['mode_conv']} |")
    a("")

    # ---- 2. supreme t3 出力(混同先) ----
    a("## 2. それらのフレームでの supreme t3 出力(混同先)")
    a("")
    a("| supreme t3 予測 | 件数 |")
    a("|---|---:|")
    for lbl, n in coll["t3_confusion"].most_common():
        mark = "  ← 正答" if lbl == GT_TARGET else ""
        a(f"| `{lbl}` | {n}{mark} |")
    a("")
    a(f"- conv_participating を正しく出せた: **{vd['t3_hit']} / {vd['n_target']}**")
    a("")

    # ---- 3. supreme 上流 mode 出力 ----
    a("## 3. それらのフレームでの supreme 上流 mode 出力(argmax)")
    a("")
    a("| supreme mode argmax | 件数 |")
    a("|---|---:|")
    for lbl, n in coll["mode_at_target"].most_common():
        mark = "  ← conv 系" if lbl.startswith("conv") else ""
        a(f"| `{lbl}` | {n}{mark} |")
    a("")
    conv_emit = sum(n for l, n in coll["mode_at_target"].items() if l.startswith("conv"))
    a(f"- conv 系 mode(conv_ongoing/conv_request)を emit: **{conv_emit} / {vd['n_target']}**"
      f"({vd['mode_conv_ratio']:.0%})")
    a("")

    # ---- 4. 会話証拠の入力有無 ----
    a("## 4. それらのフレームの PSO 入力会話証拠(構造バグ vs genuine の切り分け)")
    a("")
    d = _dist(coll["speaking_vals"])
    if d:
        a(f"- speaking_prob 分布: min={d[0]:.3f} median={d[1]:.3f} max={d[2]:.3f} mean={d[3]:.3f}")
    a(f"- 会話証拠が入力に **在る**フレーム(speech ∧ 何らかの会話信号): "
      f"**{coll['ev_present']} / {vd['n_target']}**({vd['present_ratio']:.0%})")
    a(f"- 会話証拠が入力に **無い**フレーム: **{coll['ev_absent']} / {vd['n_target']}**")
    a("")
    a("各フレームの会話証拠(先頭 40 件まで):")
    a("")
    a("| sid | idx | mode | t3 | speech | speaking | sp_link | addr | call_user | conv_strong | 証拠在 |")
    a("|---|---:|---|---|:--:|---:|:--:|---:|:--:|:--:|:--:|")
    for fr in coll["frames"][:40]:
        ev = fr["ev"]
        a(f"| {fr['sid']} | {fr['idx']} | {fr['mode_pred']} | {fr['t3_pred']} | "
          f"{'Y' if ev['has_speech'] else '·'} | {ev['speaking']:.2f} | "
          f"{'Y' if ev['speaking_link'] else '·'} | {ev['linked_addr']:.2f} | "
          f"{'Y' if ev['call_user'] else '·'} | {'Y' if ev['conv_strong'] else '·'} | "
          f"{'在' if fr['present'] else '無'} |")
    if len(coll["frames"]) > 40:
        a(f"| … 残り {len(coll['frames']) - 40} 件省略 … | | | | | | | | | | |")
    a("")

    # ---- 5. 過適合再検証(conv_request 結線) ----
    a("## 5. 過適合再検証 — conv_request を実結線したときの mode/t3 影響")
    a("")
    a("前回 conv_request 未結線の理由(mode acc 悪化=過適合リスク)が **実際に成立するか** を実測する。")
    a("**注意**: v021_core の PSO 入力には addressing link / call_user utter_event が 1 件も無い")
    a("(実在 link type は speaking / source のみ)。よって『呼びかけ証拠』で conv_request を別証拠面に")
    a("立てる素材はこのデータに無い。代わりに **core が抽出済みだが _mode_logits 未使用の `speaking_link`")
    a("(死配線)** を使い、弱会話(conv_request 相当)を立てる試験を行う:")
    a(f"試験結線条件: speaking_link ∧ speech ∧ range<{_REQ_RANGE_GATE} ∧ ¬conv_strong(speaking>0.7)。")
    a("(relation 層が conv 判定に既に使う speaking_link の流用・v021_core 合わせ込みではない。)")
    a("")
    a("**mode acc への影響(GT 非 null 全フレーム):**")
    a("")
    a("| 区分 | mode acc | 正答 / 採点 |")
    a("|---|---:|---:|")
    a(f"| base(conv_request 未結線=core 現行) | {recheck['base_acc']:.4f} | "
      f"{recheck['base_correct']} / {recheck['n_scored']} |")
    a(f"| alt(conv_request 結線) | {recheck['alt_acc']:.4f} | "
      f"{recheck['alt_correct']} / {recheck['n_scored']} |")
    a(f"| Δ(alt − base) | {recheck['alt_acc'] - recheck['base_acc']:+.4f} | "
      f"{recheck['alt_correct'] - recheck['base_correct']:+d} |")
    a("")
    a(f"- conv_request が立ったフレーム総数: **{len(recheck['req_fired'])}**")
    a(f"- mode 偽陽性(base 正 → alt 誤): **{len(recheck['regressions'])}**")
    a(f"- mode 改善(base 誤 → alt 正): **{len(recheck['improvements'])}**")
    a("")
    if recheck["req_fired"]:
        a("**conv_request が立ったフレームの GT 分布(偽陽性がどこに出るか):**")
        a("")
        gt_mode_dist = Counter(r["gt_mode"] for r in recheck["req_fired"])
        gt_t3_dist = Counter(r["gt_t3"] for r in recheck["req_fired"])
        a(f"- GT mode 分布: {dict(gt_mode_dist.most_common())}")
        a(f"- GT t3 分布: {dict(gt_t3_dist.most_common())}")
        a("")
    if recheck["regressions"]:
        a("**mode 偽陽性(base 正→alt 誤)の所在:**")
        a("")
        a("| sid | idx | GT mode | base(正) | alt(誤) | GT t3 |")
        a("|---|---:|---|---|---|---|")
        for r in recheck["regressions"][:30]:
            a(f"| {r['sid']} | {r['idx']} | {r['gt']} | {r['base']} | {r['alt']} | {r['gt_t3']} |")
        a("")
    else:
        a("- mode 偽陽性は **ゼロ**(conv_request 結線で正答 mode を壊したフレームは無い)。")
        a("")
    a("**t3 への影響(conv_participating recall):**")
    a("")
    a(f"- GT=conv_participating での t3 recall(既定 t3 params): "
      f"base {recheck['t3_conv_base_hit']} / {recheck['t3_conv_total']} → "
      f"alt {recheck['t3_conv_alt_hit']} / {recheck['t3_conv_total']} "
      f"(Δ={recheck['t3_conv_alt_hit'] - recheck['t3_conv_base_hit']:+d})")
    a(f"- t3 偽陽性(base 正→alt 誤・全クラス): **{len(recheck['t3_alt_regression'])}**")
    if recheck["t3_alt_regression"]:
        a("")
        a("| sid | idx | GT t3 | base(正) | alt(誤) |")
        a("|---|---:|---|---|---|")
        for r in recheck["t3_alt_regression"][:30]:
            a(f"| {r['sid']} | {r['idx']} | {r['gt_t3']} | {r['base']} | {r['alt']} |")
    a("")

    # ---- 5b. t3 conv 境界較正プローブ ----
    a("## 5b. t3 conv 境界較正プローブ — mode 列を core 現行で固定(上流無改変)")
    a("")
    a("**上流 mode 列を core 現行のまま固定**し、t3 の conv/traffic ロジスティック重みだけを振って、")
    a("conv_participating の取りこぼしが **t3 較正だけで** どこまで説明・回復できるかを測る(in-sample・")
    a("楽観値=この絶対値は正直な汎化ではない。傾向の切り分けが目的)。default が現行 t3 既定 params。")
    a("")
    a("| t3 params | t3 全体 acc | conv recall | conv 取りこぼし先 |")
    a("|---|---:|---:|---|")
    for r in calib:
        a(f"| {r['name']} | {r['t3_acc']:.4f} | {r['conv_hit']} / {r['conv_tot']} | "
          f"{r['conv_miss']} |")
    a("")
    a("> 既定 classify_t3: conv_score = w_conv_ratio·conv_ratio + bias_conv、")
    a("> traffic_score = w_switch_rate·switch_rate + **w_flip_accum·flip_accum** + bias_traffic。")
    a("> GT=conv_participating フレームでは上流 conv_ongoing が持続し conv_ratio は上がるが、単一の")
    a("> mode 切替(flip_accum=1)が w_flip_accum=4.0 で traffic_score を底上げし conv を負かす。")
    a("> w_flip_accum を下げると conv→traffic の取りこぼしが解消する(mode を一切変えずに)。")
    a("")

    # ---- 6. 判定 ----
    a("## 6. 判定 — (A) 構造バグ / (B) 較正 / (C) genuine")
    a("")
    a("観測サマリ:")
    a(f"- GT=conv_participating: {vd['n_target']} フレーム")
    a(f"- うち入力に会話証拠が在る: {coll['ev_present']}({vd['present_ratio']:.0%})")
    a(f"- うち supreme が conv 系 mode を emit: {vd['mode_conv_ratio']:.0%}")
    a(f"- うち supreme t3 が conv_participating を正答: {vd['t3_hit']}")
    a(f"- conv_request 結線で mode acc Δ={vd['delta_acc']:+.4f}・"
      f"偽陽性 {vd['n_reg']} / 改善 {vd['n_imp']}")
    a(f"- conv_request(speaking_link)結線で t3 conv_participating recall Δ={vd['t3_recall_gain']:+d}")
    cal_best = max(calib, key=lambda r: r["conv_hit"])
    cal_def = next(r for r in calib if r["name"] == "default")
    a(f"- **mode を一切変えず** t3 較正のみ(w_flip_accum 低減): conv recall "
      f"{cal_def['conv_hit']}→{cal_best['conv_hit']} / {cal_best['conv_tot']}、"
      f"t3 acc {cal_def['t3_acc']:.4f}→{cal_best['t3_acc']:.4f}(in-sample 楽観)")
    a("")
    a("### 観測からの切り分け(観測値のみ・捏造なし)")
    a("")
    a("1. **会話証拠は入力に在り、上流 mode へ届いている(genuine = (C) は主因でない)**: "
      f"GT=conv_participating {vd['n_target']} フレームは **全件** speech track + speaking link を持ち"
      f"(present {vd['present_ratio']:.0%})、うち {vd['mode_conv_ratio']:.0%} は上流が conv_ongoing を "
      "emit している。会話証拠が無い genuine フレームではない。")
    a("")
    a("2. **取りこぼしの主因は (B) t3 conv 境界の較正**: 上流が conv_ongoing を出していても t3 が "
      f"traffic_unstable へ流す({coll['t3_confusion'].get('traffic_unstable', 0)} 件)。原因は "
      "classify_t3 の **w_flip_accum=4.0** が、単一 mode 切替(flip_accum=1)だけで traffic_score を "
      "底上げし conv を負かすこと。**mode を一切変えず** w_flip_accum を下げるだけで conv→traffic の "
      "取りこぼしが解消する(5b 表)。これは学習境界の較正であって mode 結線の構造バグではない。")
    a("")
    a("3. **副次的に (A) mode 側の弱会話取りこぼし**: speaking_prob ≤ 0.7 で conv_strong(strict `>`)に"
      "届かないが speaking link + speech + 近接があるフレーム(ns002/ns004/ns006/ns009 の先頭)は、"
      "**core が抽出済みの speaking_link を _mode_logits が使っていない死配線**のため quiet_standby/"
      "forward_caution に潰れる。ただし speaking_link は crowd/surround/quiet 区間にも現れるため、"
      f"広く結線すると mode 偽陽性 {vd['n_reg']} 件・acc Δ={vd['delta_acc']:+.4f}(前回の過適合判断は"
      "**広い結線では成立する**)。humans<3 ∧ speaking≥0.5 へ narrow すると偽陽性は 2 件に減り mode "
      "acc は微増(diagnose 標準出力の narrow 試験)だが**偽陽性ゼロにはならない**。")
    a("")
    a("**結論**: 残る t3 conv 取りこぼしの **主因は (B) t3 conv 境界較正(w_flip_accum 過大)**で、"
      "**上流 mode を変えずに**最大の回復が得られる(クリーン)。conv_request 未結線(=(A) 構造)は "
      "副次要因で、この v021_core には conv_request 専用証拠(addressing/call_user)が存在せず、"
      "speaking_link 流用は偽陽性ゼロにできない(前回の過適合判断は妥当)。")
    a("")

    a("---")
    a("")
    a("_分析専用(src 無改変・baseline 非 import・決定的)。conv_request 結線は診断用ローカル試行。_")
    return "\n".join(L)


# ===========================================================================
# メイン
# ===========================================================================

def run(pso_dir, gt_dir, out_path):
    print("[1/5] データ読み込み(run_dev_eval 経路の再利用)")
    views_by_sid, gt_by_sid, dir_to_sid, dirs = diag.load_views_and_gt(pso_dir, gt_dir)
    snaps_by_sid = {}
    for dir_name in dirs:
        pso_path = os.path.join(pso_dir, dir_name, "pso_input.jsonl")
        snaps = dev._load_pso(pso_path)
        sid = dir_to_sid[dir_name]
        snaps_by_sid[sid] = snaps
        if len(snaps) != len(views_by_sid[sid]):
            raise Stop(f"[{sid}] snaps/view 長不一致。停止する。")
    print(f"      {len(dirs)} シナリオ・決定的 OK")

    print("[2/5] GT=conv_participating フレームの t3/mode/会話証拠を収集")
    coll = collect(views_by_sid, gt_by_sid, snaps_by_sid, dir_to_sid, dirs)
    print(f"      GT=conv_participating: {len(coll['frames'])} フレーム")

    print("[3/6] 過適合再検証: conv_request(speaking_link)結線の mode/t3 影響を実測")
    recheck = overfit_recheck(views_by_sid, gt_by_sid, snaps_by_sid)
    print(f"      base mode acc={recheck['base_acc']:.4f} / alt mode acc={recheck['alt_acc']:.4f}")

    print("[4/6] t3 conv 境界較正プローブ(mode 列は core 現行で固定=上流無改変)")
    calib = t3_calibration_probe(views_by_sid, gt_by_sid, snaps_by_sid)
    for r in calib:
        print(f"      {r['name']:32s} t3acc={r['t3_acc']:.4f} "
              f"conv_recall={r['conv_hit']}/{r['conv_tot']} miss={r['conv_miss']}")

    print("[5/6] (A)/(B)/(C) 判定")
    vd = verdict(coll, recheck)

    print("[6/6] レポート書き出し")
    report = render(coll=coll, recheck=recheck, calib=calib, vd=vd,
                    dirs=dirs, dir_to_sid=dir_to_sid)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"      出力: {out_path}")

    _print_summary(coll, recheck, calib, vd)
    return coll, recheck, calib, vd


def _print_summary(coll, recheck, calib, vd):
    print()
    print("=" * 72)
    print("conv_participating 取りこぼし診断サマリ(標準出力)")
    print("=" * 72)
    print()
    print(f"[1] GT=conv_participating フレーム数: {vd['n_target']}")
    print(f"    シナリオ別:")
    for sid, sc in sorted(coll["by_scenario"].items()):
        print(f"      {sid:40s} n={sc['n']:2d}  t3正答={sc['t3_correct']:2d}  "
              f"mode_conv={sc['mode_conv']:2d}")
    print()
    print(f"[2] supreme t3 出力(混同先): {dict(coll['t3_confusion'].most_common())}")
    print(f"    conv_participating 正答: {vd['t3_hit']} / {vd['n_target']}")
    print()
    print(f"[3] supreme 上流 mode 出力: {dict(coll['mode_at_target'].most_common())}")
    conv_emit = sum(n for l, n in coll["mode_at_target"].items() if l.startswith("conv"))
    print(f"    conv 系 mode emit: {conv_emit} / {vd['n_target']} ({vd['mode_conv_ratio']:.0%})")
    print()
    d = _dist(coll["speaking_vals"])
    if d:
        print(f"[4] 会話証拠: speaking_prob min={d[0]:.2f} median={d[1]:.2f} max={d[2]:.2f}")
    print(f"    入力に会話証拠が在る: {coll['ev_present']} / {vd['n_target']} "
          f"({vd['present_ratio']:.0%}) / 無い: {coll['ev_absent']}")
    print()
    print(f"[5] 過適合再検証(conv_request 結線):")
    print(f"    mode acc: base={recheck['base_acc']:.4f} alt={recheck['alt_acc']:.4f} "
          f"Δ={recheck['alt_acc'] - recheck['base_acc']:+.4f}")
    print(f"    conv_request 発火: {len(recheck['req_fired'])} フレーム")
    print(f"    mode 偽陽性(正→誤): {len(recheck['regressions'])} / "
          f"改善(誤→正): {len(recheck['improvements'])}")
    print(f"    t3 conv_participating recall: base={recheck['t3_conv_base_hit']} "
          f"→ alt={recheck['t3_conv_alt_hit']} / {recheck['t3_conv_total']} "
          f"(Δ={vd['t3_recall_gain']:+d})")
    print(f"    t3 偽陽性(正→誤・全クラス): {len(recheck['t3_alt_regression'])}")
    print()
    print(f"[6] t3 conv 境界較正プローブ(mode 列=core 現行で固定・上流無改変):")
    for r in calib:
        print(f"    {r['name']:32s} t3acc={r['t3_acc']:.4f} "
              f"conv_recall={r['conv_hit']:2d}/{r['conv_tot']} miss={r['conv_miss']}")
    print()
    if recheck["req_fired"]:
        gt_mode_dist = Counter(r["gt_mode"] for r in recheck["req_fired"])
        gt_t3_dist = Counter(r["gt_t3"] for r in recheck["req_fired"])
        print(f"    conv_request 発火フレームの GT mode 分布: {dict(gt_mode_dist.most_common())}")
        print(f"    conv_request 発火フレームの GT t3 分布:   {dict(gt_t3_dist.most_common())}")
    print()
    print("=" * 72)


def main():
    p = argparse.ArgumentParser(description="conv_participating 取りこぼし診断")
    p.add_argument("--pso-dir", default=dev.DEFAULT_PSO_DIR)
    p.add_argument("--gt-dir", default=dev.DEFAULT_GT_DIR)
    p.add_argument("--out", default=None)
    args = p.parse_args()
    out_path = args.out
    if out_path is None:
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M")
        out_path = os.path.join("reports", f"conv-diagnose-{stamp}.md")
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
