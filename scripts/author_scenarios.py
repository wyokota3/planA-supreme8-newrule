"""多様な合成練習シナリオ生成器(決定的・乱数なし・分析専用)。

狙い(指示):
  t3 の lose は練習データの **多様性不足** の疑い(量増し=増強は効かないと確定済み・
  reports/cv-augment-*.md)。実シナリオは v021_core 20件のみ。だから **合成で多様な
  シナリオを作り**、t3/scene 学習に効くかを実 held-out CV で経験的に測る。

最重要規律(円環回避・捏造防止・指示):
  - 合成シナリオの GT は **baseline 規則 / GT_SCHEMA の文書化済み意味論で構成的に決める**。
    具体的には baseline `_classify_t3`(supreme.t3._rule_hypothesis が忠実再現する条件)と
    各層の決定論的判定規則(t0/t1/role/relation/quality)で **一意に正解が定まる** 入力だけを作る。
  - **supreme.run_supreme を走らせてラベルを付けない**(自己ラベル=円環は禁止)。GT は
    意味論から構成的に決める。run_supreme は **入力の健全性チェック**(意図した mode-sequence /
    evidence が実際に出る入力か)にのみ使い、**GT のラベル付けには使わない**。
  - 構成的に正解が一意にならない・意図と食い違うシナリオは **捨てて報告**(無効ラベルで
    水増ししない)。
  - core/モジュール/テストは一切変更しない(supreme.* の公開 API + core 内部関数の
    import 再利用のみ・baseline は import しない=独立性)。決定的(2回生成で bit 一致)。

=== なぜ「構成的に GT を決められる」か(意味論の根拠)===

supreme(と baseline)の 8 層は PSO-Snapshot の **少数フィールドから決定論的に** 導かれる
(core.py の証拠抽出・各モジュールの判定規則を精読して同定):

  t0.risk_tier  = 主トラック(siren 優先 / 最近傍)の kind 別 TTC 閾値判定(t0.py)。
                  siren ttc<=2→danger / <=12→caution(下限 caution)。speech/vehicle 等同様。
  t1_state      = ttc<12(+pw_anom)→approach / 発散+増加→pass/depart(t1.py・状態機械)。
  t2_mode       = 証拠 → mode logits(core._mode_logits)→ quiet 起点ヒステリシス(mode.py):
                    danger→emergency / caution→alert_required(安全 mode=即発火)
                    conv_strong(speech∧speaking>0.7∧min_range<5)→conv_ongoing
                    humans>=3(非 conv_strong・非危険)→surround_activity
                    approaching(t1)→forward_caution / h_q<0.5→env_change
                    無証拠→quiet_standby
  t2_role       = role logits argmax(role.py): siren/alarm→source_alarm / vehicle→source_vehicle
                    conv_strong→source_speech / 無証拠→unknown。
  t2_relation   = relation logits argmax(relation.py): conv_strong→near_user /
                    approaching→approaching / 無証拠→grouped(既定強化 2.0)。
  t3_hypothesis = mode argmax 系列(直近 6 フレーム窓)の構造条件(t3._rule_hypothesis・
                    baseline `_classify_t3` §3.9 の忠実再現)+ conv/traffic/quiet 境界:
                    alert_required 比率>0.25 ∧ emergency 比率<0.2 → alert_required
                    (alert+emergency)比率>0.3 → sustained_alert
                    surround 比率>0.25 → crowd_tendency
                    env_change 比率>0.15 ∧ 立ち上がり → env_start / 継続 → env_shift
                    conv 持続 → conv_participating / 切替・flip → traffic_unstable / 静穏 → quiet_stable
  quality_regime= (h_q, vol) の閾値(quality.py): h_q<0.55→BLOCK / h_q>=0.93∧vol<0.01→GOOD /
                    その他→DEGRADED。h_q は QoS/latency の観測式+HGF(高 QoS→h_q≈1)。
  scene_regime  = health 信号(=sigmoid(観測 logit))の HGF level/vol + 持続逸脱の閾値
                    (scene.classify_scene)。**HGF は系列依存** のため、構成的に一意に決まる
                    のは「定常高 QoS=STABLE」「定常低 QoS=DEGRADING」など端点に限る。

これらのうち t3 は **mode 系列だけで一意に決まる**(R チャネル証拠を固定すれば mode 系列が
決まり、6 フレーム窓比率で t3 規則が一意に発火する)。よって t3 を主目標に、v021_core が
手薄な t3 クラス(sustained_alert / env_shift / crowd_tendency / env_start 等)を構成的に作る。

=== GT は「構成的=意味論で決める」/ run_supreme は「健全性チェックのみ」===

各シナリオは
  (1) **意図(intent)**: 作者が狙った各層のラベル系列(意味論から構成的に書き下したもの)。
  (2) **PSO 入力**: その intent を一意に出す決定的な証拠を持つ snapshot 系列。
  (3) **自己検査**: core.run_supreme(snaps) を流し、得た mode 系列・各層が intent と一致するか。
      一致 = 「意図した evidence/mode-sequence が実際に出る健全な入力」。
      不一致 = 構成が一意でない(または作者の意味論誤り)→ **捨てて報告**。
GT(train ラベル)は **(1) の intent から構成**する(run_supreme の出力ではない)。自己検査は
「入力が intent を一意に実現するか」の健全性確認であって、GT のラベル付けではない。

=== 多様性の出し方(v021_core が手薄なクラスを構成的に厚くする)===

診断(reports/dev-eval-diagnose-*.md)で t3 GT 頻度が薄いクラス:
  alert_required(4)/ hazard_declining(2)/ env_start(7)/ uncertain_context(9)。
これらと、多様な mode/scene 遷移(quiet→alert 立ち上がり・conv 持続・env 立ち上がり/継続・
crowd 群衆・traffic 切替・複合遷移)を構成的に作る。各シナリオは GT が一意な範囲に限る
(曖昧な境界・HGF 依存で一意でない t3 は作らない)。

決定的・乱数なし: すべての証拠値・系列は固定テーブルから構成する。
"""

from __future__ import annotations

import copy
import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_SRC_DIR = os.path.join(os.path.dirname(_SCRIPT_DIR), "src")
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

# supreme 公開 API + core 内部関数(baseline は import しない=独立性)。
# t3/mode 等は **意味論の根拠を読む** ために import するが、GT のラベル付けに run_supreme は使わない。
from supreme import core, t3 as t3_mod, mode as mode_mod


# ===========================================================================
# 構成妥当性エラー
# ===========================================================================

class AuthorError(Exception):
    """シナリオ構成の不整合(意図と意味論の食い違い等・捏造せず停止/破棄して報告)。"""


# ===========================================================================
# PSO-Snapshot フレーム構成(fixtures_pso 流儀の v1.4 形・R チャネルで mode を一意化)
# ===========================================================================

_VERSION = "PSO-Snapshot/1.4"
_FRAME = "W2D"
_DT = 0.5  # フレーム間隔(ts は狭義単調増加・GT_SCHEMA 要件)。

# 「無証拠=quiet」フレームで使う高 QoS(h_q≈1・GOOD・scene STABLE 側)。
_QOS_GOOD = 0.97
_LATENCY_GOOD = 38.0
# 観測品質劣化(h_q<0.5 → env_change mode・quality DEGRADED/BLOCK・scene DEGRADING 側)。
_QOS_BAD = 0.05
_LATENCY_BAD = 180.0


def _base_frame(ts, qos=_QOS_GOOD, latency=_LATENCY_GOOD, min_ttc=100.0):
    """無証拠の基準フレーム(quiet_standby・高 QoS)。R チャネルは空。"""
    return {
        "version": _VERSION,
        "ts": float(ts),
        "frame": _FRAME,
        "origin": {"x_m": 0, "y_m": 0, "yaw_deg": 0},
        "tracks": {"audio": [], "humans": [], "objects": []},
        "links": [],
        "geom": {"overlap_path": False, "lane_alignment": True, "min_TTC_s": float(min_ttc)},
        "utter_events": [],
        "scene_state": {"latency_ms": float(latency), "QoS": float(qos)},
    }


# --- 各「フレーム種(intent mode)」を一意に出す証拠構成(core._mode_logits を逆算)---
#
# core._mode_logits の発火条件を「排他的に」満たす最小証拠を置く。ヒステリシス(quiet 起点で
# 非安全 mode を block=2.6 減衰)を考慮しても、logit 4.0-2.6=1.4 > quiet 0.0 なので非安全 mode
# も初手から発火する(safety mode は即発火)。よって per-frame の intent mode は R チャネルで一意。

# siren フレームの r_m は emergency/alert で **共通(10.0)** に固定する。理由(自己検査で判明):
# t1 状態機械は prev=approach のとき range の発散(cur-min_seen>1.0 ∧ 増加>0.3)で pass/depart を
# 出す。emergency と alert で r_m を変えると(例 8↔20)交互系列で range が発散し t1 が depart に
# なって intent(approach)と食い違う。r_m を共通にすれば range は不変で t1 は一意に approach 継続。
# danger/caution の差は **ttc のみ**(emergency: ttc<=2 / alert: 2<ttc<=12)で付ける(構成的に分離)。
_SIREN_RANGE = 10.0


def _frame_emergency(ts):
    """danger(siren ttc<=2)→ emergency(安全 mode・即発火)。r_m は alert と共通(t1 一意化)。"""
    f = _base_frame(ts, min_ttc=1.0)
    f["tracks"]["audio"] = [{"aid": "A1", "type": "siren", "r_m": _SIREN_RANGE, "w_obs": 0.6}]
    return f


def _frame_alert(ts):
    """caution(siren ttc=8: 2<ttc<=12)→ alert_required(安全 mode・即発火)。

    siren は ttc 8 で caution(下限規則でも caution)。emergency にしないため ttc>2。
    r_m は emergency と共通(交互系列で t1 が発散して depart にならないため)。
    """
    f = _base_frame(ts, min_ttc=8.0)
    f["tracks"]["audio"] = [{"aid": "A1", "type": "siren", "r_m": _SIREN_RANGE, "w_obs": 0.6}]
    return f


def _frame_conv(ts):
    """conv_strong(speech ∧ speaking>0.7 ∧ min_range<5)→ conv_ongoing。"""
    f = _base_frame(ts, min_ttc=100.0)
    f["tracks"]["audio"] = [{"aid": "A1", "type": "speech", "r_m": 3.0, "w_obs": 0.6}]
    f["tracks"]["humans"] = [
        {"hid": "H1", "r_m": 3.0, "theta_deg": 0, "speaking_prob": 0.9, "w_obs": 0.6}
    ]
    f["links"] = [{"from": "A1", "to": "H1", "type": "speaking", "score": 0.8}]
    return f


def _frame_surround(ts):
    """humans>=3(非 conv_strong・非危険)→ surround_activity。

    speaking_prob を低く(<=0.7)し min_range を大きく(>=5)して conv_strong を外す。
    """
    f = _base_frame(ts, min_ttc=100.0)
    f["tracks"]["humans"] = [
        {"hid": "H1", "r_m": 6.0, "theta_deg": -30, "speaking_prob": 0.2, "w_obs": 0.6},
        {"hid": "H2", "r_m": 7.0, "theta_deg": 45, "speaking_prob": 0.15, "w_obs": 0.6},
        {"hid": "H3", "r_m": 6.5, "theta_deg": 120, "speaking_prob": 0.25, "w_obs": 0.6},
    ]
    return f


def _frame_env(ts):
    """観測品質劣化(h_q<0.5)→ env_change。低 QoS・高 latency。

    R チャネルは空(危険・接近・会話・群衆を出さない)ので env_change のみが立つ。
    """
    return _base_frame(ts, qos=_QOS_BAD, latency=_LATENCY_BAD, min_ttc=100.0)


def _frame_quiet(ts):
    """無証拠 → quiet_standby(高 QoS)。"""
    return _base_frame(ts, min_ttc=100.0)


# intent mode ラベル → フレーム生成器(構成的・一意)。
_FRAME_BUILDERS = {
    "emergency": _frame_emergency,
    "alert_required": _frame_alert,
    "conv_ongoing": _frame_conv,
    "surround_activity": _frame_surround,
    "env_change": _frame_env,
    "quiet_standby": _frame_quiet,
}


# ===========================================================================
# t3 hypothesis を mode 系列から構成的に決める(baseline `_classify_t3` 意味論)
#   ※ これは t3.py の規則を import して「読む」が、run_supreme でラベル付けはしない。
#   ※ t3._rule_hypothesis / classify_t3 / step は **公開された決定論的判定** であり、
#      これを mode 系列(=こちらが構成した intent)に適用するのは「意味論で構成的に GT を
#      決める」ことであって「supreme に自己ラベルさせる」ことではない(run_supreme 非経由・
#      証拠抽出やヒステリシスを通さず、作者が固定した mode 系列へ規則を当てるだけ)。
# ===========================================================================

def _t3_gt_from_mode_sequence(mode_seq_labels, posterior_seq, reset_seq):
    """intent mode ラベル系列(+ posterior + reset)から t3 hypothesis GT を構成的に決める。

    baseline `_classify_t3` の意味論(t3._rule_hypothesis の規則層 + classify_t3 の
    conv/traffic/quiet 境界)を、**作者が固定した mode 系列**へ決定論的に適用する。
    これは「意味論で GT を構成する」操作であり、PSO 証拠抽出・mode ヒステリシスを通す
    run_supreme とは独立(円環でない)。

    t3 の規則は default_params() の重み(conv/traffic/quiet 境界の代表値)を使う。GT を
    「学習の正解信号」として与えるので、**学習前の意味論既定**(default_params)で構成する
    のが筋(学習で動かす対象の正解を、学習結果で決めない)。

    Returns:
        t3 hypothesis ラベル列(list[str]・mode_seq_labels と同長)。
    """
    mode_frames = [
        {"mode": lbl, "posterior": float(p)}
        for lbl, p in zip(mode_seq_labels, posterior_seq)
    ]
    # t3.run_t3_sequence は step を初期状態から連鎖する公開 API。mode 系列はこちらが固定した
    # intent(run_supreme の証拠抽出を通さない)。default_params で意味論の素の判定を得る。
    return t3_mod.run_t3_sequence(mode_frames, reset_seq, t3_mod.default_params())


# ===========================================================================
# 各層の per-frame GT を mode intent から構成的に決める(意味論)
# ===========================================================================

# intent mode → (risk_tier, t1_state[tick0近似], role, relation, quality, scene)を
# 構成的に与える写像。**各フレームを単独で見たときの一意な値**(系列効果のある t1/t3 は別途)。
#
# 注意: t1_state は状態機械(系列依存)。本生成器は t1 が系列で曖昧にならないよう、
# 接近フレーム(forward_caution)を作らず ttc を 100(idle 一意)か危険専用に限る。
# よって t1 は全フレーム idle(危険フレームでも min_TTC が小さいと approach になりうるため、
# 危険は siren で表現し ttc を danger 閾値に置く=t1 は approach。下表で対応)。

def _per_frame_static_gt(mode_label, frame):
    """1 フレームの intent mode と PSO 証拠から、系列非依存層の GT を構成的に決める。

    risk_tier / t2_role / t2_relation / quality_regime は **そのフレームの証拠だけ** で
    決まる(系列非依存)。t1_state / scene_regime / t3_hypothesis は系列依存のため別経路。

    Returns:
        {"risk_tier","t2_role","t2_relation","quality_regime"} の dict。
    """
    # --- risk_tier(t0 意味論)---
    if mode_label == "emergency":
        risk = "danger"          # siren ttc<=2 → danger
    elif mode_label == "alert_required":
        risk = "caution"         # siren 2<ttc<=12 → caution(siren 下限)
    else:
        risk = "info"            # 危険トラック無し → info

    # --- t2_role(role 意味論)---
    if mode_label in ("emergency", "alert_required"):
        role = "source_alarm"    # siren → source_alarm(_W_ALARM)
    elif mode_label == "conv_ongoing":
        role = "source_speech"   # conv_strong → source_speech(_W_CONV_STRONG)
    else:
        role = "unknown"         # 無証拠 → unknown(既定 _W_UNKNOWN)

    # --- t2_relation(relation 意味論)---
    #   conv_strong → near_user(_W_NEAR_USER)。
    #   emergency/alert は siren ttc<12 → t1=approach → relation evidence approaching=True →
    #     approaching(_W_APPROACHING=2.0・argmax で grouped 既定 2.0 と同値だが _LABEL_ORDER で
    #     approaching が先=決定的 tie-break で approaching が勝つ)。
    #   surround/quiet(危険・接近・会話なし)→ grouped(既定強化 2.0)。
    #   ※ この対応は core.run_supreme で実測確認済み(自己検査が一致を担保する)。
    if mode_label == "conv_ongoing":
        rel = "near_user"
    elif mode_label in ("emergency", "alert_required"):
        rel = "approaching"
    else:
        rel = "grouped"

    # --- quality_regime(quality 意味論・h_q は QoS/latency から)---
    qos = float(frame["scene_state"]["QoS"])
    if mode_label == "env_change":
        quality = "BLOCK"        # 低 QoS(0.05)→ h_q<0.25 → BLOCK
    elif qos >= _QOS_GOOD:
        quality = "GOOD"         # 高 QoS(0.97)→ h_q≈1・vol<0.01 → GOOD
    else:
        quality = "DEGRADED"
    return {
        "risk_tier": risk,
        "t2_role": role,
        "t2_relation": rel,
        "quality_regime": quality,
    }


# ===========================================================================
# シナリオ定義(構成的・多様性: v021_core が手薄な t3 クラスを厚くする)
#   各定義 = (suffix, mode_intent_labels)。mode 系列から全層 GT を構成的に決める。
#   多様な mode/scene 遷移を含む。GT が一意な範囲のみ(曖昧な境界は作らない)。
# ===========================================================================

# 6 フレーム窓(t3 規則の _RULE_MODE_WINDOW)を満たすため各シナリオは >=6 フレーム。
# t3 規則の発火比率(alert>0.25・surround>0.25・env>0.15 等)を一意に満たすよう構成する。

#  ⚠️ 構成上の制約(自己検査で実測判明・honest finding):
#    env_change は観測品質劣化(h_q<0.5)で立つが、h_q は観測式 logit を HGF で平滑化した量。
#    高 QoS フレームの **後** に低 QoS フレームを置いても、HGF の遅延で h_q が即座に 0.5 を
#    割らない(2 フレームの過渡)。よって「quiet→env への立ち上がり(env_start)」は構成的に
#    一意に作れない(過渡で mode 系列が intent と食い違う)。**全フレーム env_change** の定常列
#    だけが構成的に一意(h_q が初手から低位で安定)→ env_shift のみ作る(env_start は作れない=
#    捨てて報告)。同様に env を中途に挟む traffic/compound は構成不能のため作らない。

_SCENARIO_SPECS = [
    # --- alert_required(GT 薄い=4): alert が窓内で持続(比率>0.25・emergency なし)---
    ("alert-sustain",
     ["quiet_standby", "alert_required", "alert_required", "alert_required",
      "alert_required", "alert_required"]),
    ("alert-onset",
     ["quiet_standby", "quiet_standby", "alert_required", "alert_required",
      "alert_required", "alert_required"]),

    # --- sustained_alert: alert+emergency 比率>0.3(emergency 混在で alert_required 排他を外す)---
    ("sustained-emergency",
     ["alert_required", "emergency", "alert_required", "emergency",
      "emergency", "emergency"]),
    ("sustained-mixed",
     ["quiet_standby", "alert_required", "emergency", "alert_required",
      "emergency", "alert_required"]),

    # --- crowd_tendency: surround_activity 比率>0.25(群衆持続)---
    ("crowd-sustain",
     ["quiet_standby", "surround_activity", "surround_activity", "surround_activity",
      "surround_activity", "surround_activity"]),
    ("crowd-onset",
     ["quiet_standby", "quiet_standby", "surround_activity", "surround_activity",
      "surround_activity", "surround_activity"]),

    # --- env_shift: env_change 継続(全フレーム低 QoS=構成的に一意な唯一の env パターン)---
    ("env-shift-sustain",
     ["env_change", "env_change", "env_change", "env_change",
      "env_change", "env_change"]),

    # --- conv_participating: conv 持続(conv 比率高)---
    ("conv-sustain",
     ["quiet_standby", "conv_ongoing", "conv_ongoing", "conv_ongoing",
      "conv_ongoing", "conv_ongoing"]),

    # --- quiet_stable: 静穏持続 ---
    ("quiet-long",
     ["quiet_standby", "quiet_standby", "quiet_standby", "quiet_standby",
      "quiet_standby", "quiet_standby"]),

    # --- traffic_unstable: mode の切替/flip 多い(conv/surround/quiet を交互=切替率高・env 不使用)---
    ("traffic-switch",
     ["quiet_standby", "conv_ongoing", "surround_activity", "quiet_standby",
      "conv_ongoing", "surround_activity"]),
    ("traffic-switch2",
     ["conv_ongoing", "surround_activity", "conv_ongoing", "surround_activity",
      "conv_ongoing", "surround_activity"]),

    # --- 複合遷移(多様な mode/scene 遷移・env を中途に挟まない=構成的に一意)---
    ("compound-alert-to-crowd",
     ["alert_required", "alert_required", "alert_required",
      "surround_activity", "surround_activity", "surround_activity"]),
    ("compound-conv-to-crowd",
     ["conv_ongoing", "conv_ongoing", "conv_ongoing",
      "surround_activity", "surround_activity", "surround_activity"]),
    ("compound-quiet-alert-onset",
     ["quiet_standby", "quiet_standby", "quiet_standby",
      "alert_required", "alert_required", "alert_required"]),
]


def _scene_gt_for_modes(mode_labels):
    """intent mode 系列から scene_regime GT を構成的に決める(端点のみ・一意な範囲に限る)。

    scene_regime は health 信号(QoS/latency 由来)の HGF level/vol + 持続逸脱で決まる(系列依存)。
    構成的に一意なのは **定常端点** に限る:
      - 全フレーム高 QoS(env_change を含まない・QoS=0.97)→ 定常高 health → **STABLE**
        (HGF level 高・vol 低・持続逸脱 ≈0=変化兆候も下降兆候も無い・自己検査で実測確認)。
      - 全フレーム低 QoS(env_change のみ・QoS=0.05)→ 定常低 health → **DEGRADING**
        (HGF level が level_low(0.30)未満で安定=自己検査で実測確認)。
      - 混在(高 QoS と低 QoS の遷移を含む)→ health が下降/急変 → 一意でない
        (CHANGING/DEGRADING のどちらにも倒れうる・HGF 系列依存・onset で過渡が出る)→
        **None(GT を付けない=曖昧クラスを作らない)**。
    曖昧な scene は GT を付けず(None)、その層は学習サンプル外にする(無効ラベルで水増し
    しない=指示「GT は構成的に一意な範囲のみ」)。

    Returns:
        scene_regime ラベル列(list[str or None]・mode_labels と同長)。
    """
    has_env = any(m == "env_change" for m in mode_labels)
    all_env = all(m == "env_change" for m in mode_labels)
    if all_env:
        # 全フレーム低 QoS の定常列 → 構成的に DEGRADING(level_low 未満で安定)。
        return [core.scene_mod.DEGRADING] * len(mode_labels)
    if has_env:
        # 高 QoS と低 QoS が混在 → 過渡で一意でない → GT を付けない(None)。
        return [None] * len(mode_labels)
    # 全フレーム高 QoS の定常列 → 構成的に STABLE(変化兆候・下降兆候なし)。
    return [core.scene_mod.STABLE] * len(mode_labels)


def _t1_gt_for_modes(mode_labels):
    """intent mode 系列から t1_state GT を構成的に決める(t1 状態機械の意味論)。

    本生成器は接近(forward_caution)フレームを作らない。t1 入力は:
      - emergency フレーム: siren ttc=1.0(<12)→ approach。
      - alert_required フレーム: siren ttc=8.0(<12)→ approach。
      - その他: min_TTC=100(>=12)→ idle。
    ただし t1 は状態機械(prev=approach から発散判定で pass/depart)。本生成器は range を
    フレーム内で固定し発散(cur-min_seen>1.0 ∧ 増加>0.3)を起こさないため、approach/idle の
    どちらかに一意に決まる(pass/depart は出ない)。tick0 も閾値のみ=一意。

    Returns:
        t1_state ラベル列(list[str]・mode_labels と同長)。
    """
    out = []
    for m in mode_labels:
        if m in ("emergency", "alert_required"):
            out.append("approach")   # siren ttc<12 → approach(発散しないので継続 approach)
        else:
            out.append("idle")       # ttc>=12 → idle
    return out


def build_scenario(suffix, mode_labels):
    """1 シナリオの (snaps, gt_views, intent) を構成的に作る(run_supreme 非依存の GT)。

    - snaps: intent mode を一意に出す PSO-Snapshot 系列(_FRAME_BUILDERS)。
    - gt_views: **意味論から構成した 8 層 GT**(supreme 出力ではない):
        t3_hypothesis = _t3_gt_from_mode_sequence(意味論規則を intent mode 系列へ適用)
        scene_regime  = 構成的に一意な端点のみ(env 含む系列は None)
        t1_state      = t1 状態機械の意味論
        risk_tier/role/relation/quality = per-frame 証拠から構成
        t2_mode       = intent mode(=作者が固定した mode)
    - intent: 自己検査で run_supreme と突合する作者の意図(健全性チェック用)。

    Returns:
        (scenario_id, snaps, gt_views, intent_modes)。
    """
    scenario_id = f"author-{suffix}"
    snaps = []
    for i, m in enumerate(mode_labels):
        builder = _FRAME_BUILDERS[m]
        snaps.append(builder(i * _DT))

    # posterior(h_q)系列: 高 QoS→≈1 / env_change(低 QoS)→≈0。t3 の posterior は集約特徴に
    # 入るが、conv/traffic/quiet 境界は conv_ratio/switch_rate/flip_accum 主導(default_params の
    # 重みは posterior 非依存=w_conv_ratio/w_switch_rate/w_flip_accum のみ)。intent と整合させる。
    posterior_seq = [0.05 if m == "env_change" else 0.97 for m in mode_labels]
    reset_seq = [i == 0 for i in range(len(mode_labels))]

    # --- t3 GT(意味論で構成・run_supreme 非経由)---
    t3_gt = _t3_gt_from_mode_sequence(mode_labels, posterior_seq, reset_seq)
    # --- scene / t1 GT(構成的・一意範囲のみ)---
    scene_gt = _scene_gt_for_modes(mode_labels)
    t1_gt = _t1_gt_for_modes(mode_labels)

    gt_views = []
    for i, m in enumerate(mode_labels):
        static = _per_frame_static_gt(m, snaps[i])
        gt_views.append({
            "risk_tier": static["risk_tier"],
            "t1_state": t1_gt[i],
            "t2_mode": m,                       # intent mode(作者固定)
            "t2_role": static["t2_role"],
            "t2_relation": static["t2_relation"],
            "t3_hypothesis": t3_gt[i],          # 意味論で構成
            "quality_regime": static["quality_regime"],
            "scene_regime": scene_gt[i],        # 構成的端点のみ(env 含む列は None)
        })

    return scenario_id, snaps, gt_views, list(mode_labels)


# ===========================================================================
# 構成妥当性の自己検査(意図した mode-sequence/evidence が実際に出る入力か)
#   ※ run_supreme は **入力の健全性チェック** に使う(GT のラベル付けではない)。
# ===========================================================================

# 自己検査で intent と突合する層(構成的に一意に決めた層のみ)。scene は env を含む列で
# None(GT 無し)にしているので、その層は intent 突合の対象から外す(None は突合しない)。
_INTENT_CHECK_LAYERS = (
    "risk_tier", "t1_state", "t2_mode", "t2_role", "t2_relation",
    "t3_hypothesis", "quality_regime", "scene_regime",
)


def self_check_scenario(scenario_id, snaps, gt_views):
    """構成妥当性の自己検査: core.run_supreme(snaps) が intent(=構成的 GT)と一致するか。

    これは「意図した mode-sequence/evidence が実際にその入力から出るか」の **健全性チェック**
    であって、GT のラベル付けではない(GT は build_scenario が意味論で構成済み)。

    判定:
      - run_supreme の各層が、None でない構成的 GT と **完全一致** すれば「構成は一意に実現」。
      - 1 つでも食い違えば「構成が一意でない / 作者の意味論誤り」→ ok=False(捨てて報告)。
        scene_regime の構成的 GT は None(env 列)/STABLE(定常列)。None の層は突合しない
        (GT を付けていない=学習サンプル外なので、supreme が何を出してもよい)。

    Returns:
        (ok: bool, detail: dict)。detail は不一致時に最初の不一致層・フレーム・両値を持つ。
    """
    views = core.run_supreme(snaps)
    if len(views) != len(gt_views):
        return False, {
            "scenario_id": scenario_id,
            "reason": "frame_count_mismatch",
            "n_views": len(views),
            "n_gt": len(gt_views),
        }
    for i, (v, g) in enumerate(zip(views, gt_views)):
        for layer in _INTENT_CHECK_LAYERS:
            gt_label = g.get(layer)
            if gt_label is None:
                continue  # GT を付けていない層(曖昧・一意でない)は突合しない。
            if v.get(layer) != gt_label:
                return False, {
                    "scenario_id": scenario_id,
                    "reason": "intent_mismatch",
                    "layer": layer,
                    "frame": i,
                    "intent_gt": gt_label,
                    "supreme": v.get(layer),
                }
    return True, {"scenario_id": scenario_id, "reason": "ok", "frames": len(views)}


# ===========================================================================
# 公開: 全 author シナリオを生成し、構成妥当な(自己検査 OK)もののみ返す
# ===========================================================================

def generate_authored_scenarios(specs=None):
    """全 author シナリオを構成的に生成し、自己検査 OK のものだけを採用して返す。

    - specs=None は _SCENARIO_SPECS(既定の構成シナリオ集合)。
    - 各シナリオを build_scenario(意味論で GT 構成)→ self_check_scenario(健全性チェック)。
    - 自己検査 NG(構成が一意に実現しない)シナリオは **採用しない**(捨てて報告)。

    Returns:
        {
          "kept":    [{"scenario_id","snaps","gt_views","intent_modes"}, ...],  # 採用
          "rejected":[{"scenario_id","detail"}, ...],                          # 破棄(報告)
          "n_specs": len(specs),
        }
    """
    if specs is None:
        specs = _SCENARIO_SPECS

    kept = []
    rejected = []
    seen_ids = set()
    for suffix, mode_labels in specs:
        scenario_id, snaps, gt_views, intent = build_scenario(suffix, mode_labels)
        if scenario_id in seen_ids:
            raise AuthorError(f"scenario_id が重複: {scenario_id}(構成定義の重複)。停止する。")
        seen_ids.add(scenario_id)

        ok, detail = self_check_scenario(scenario_id, snaps, gt_views)
        if ok:
            kept.append({
                "scenario_id": scenario_id,
                "snaps": snaps,
                "gt_views": gt_views,
                "intent_modes": intent,
            })
        else:
            rejected.append({"scenario_id": scenario_id, "detail": detail})

    return {"kept": kept, "rejected": rejected, "n_specs": len(specs)}


def t3_gt_class_counts(kept):
    """採用シナリオの t3_hypothesis GT クラス別フレーム数(多様性=どのクラスを厚くしたか)。"""
    from collections import Counter
    c = Counter()
    for sc in kept:
        for gv in sc["gt_views"]:
            lbl = gv.get("t3_hypothesis")
            if lbl is not None:
                c[lbl] += 1
    return dict(c)


def scene_gt_class_counts(kept):
    """採用シナリオの scene_regime GT クラス別フレーム数(None=曖昧で付けない層は除外)。"""
    from collections import Counter
    c = Counter()
    for sc in kept:
        for gv in sc["gt_views"]:
            lbl = gv.get("scene_regime")
            if lbl is not None:
                c[lbl] += 1
    return dict(c)


if __name__ == "__main__":
    # 単体実行: 生成と自己検査の結果サマリを表示(CV は run_cv_author.py)。
    res = generate_authored_scenarios()
    print(f"author シナリオ構成定義: {res['n_specs']} 件")
    print(f"  採用(自己検査 OK)= {len(res['kept'])} / 破棄(構成不一致)= {len(res['rejected'])}")
    if res["rejected"]:
        print("  破棄の内訳:")
        for r in res["rejected"]:
            print(f"    - {r['scenario_id']}: {r['detail']}")
    print(f"  t3 GT クラス分布: {t3_gt_class_counts(res['kept'])}")
    print(f"  scene GT クラス分布: {scene_gt_class_counts(res['kept'])}")
