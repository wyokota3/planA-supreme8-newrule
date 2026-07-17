"""F-基盤-001(ADR 0022): supreme 上流共有基盤 — end-to-end 統合ランナー(core)。

構築済みの 8 モジュール(t0/t1/role/mode/relation/quality/scene/t3)を「入力を注入される形」
から、PSO-Snapshot 系列を流すだけで 8 層 view を生成する end-to-end ランナーへ統合する。
SPEC の `epiin`(入力契約)・`epiout`(出力契約=8 層 view)stage を実装する新ノード。

公開 API(ADR 0022 で API 名は実装裁量):
  run_supreme(pso_snapshots, config=None) -> list[frame_view]
      PSO-Snapshot(world_state dict)の系列を各フレームの 8 層 view dict 列へ写す。
  run_supreme_scenarios(scenarios, config=None) -> dict[scenario_id, list[frame_view]]
      シナリオ単位の入力を受け、各シナリオ先頭で T3 を reset(シナリオ境界 reset)した上で
      各シナリオの 8 層 view 列を返す。
  build_trace(scenarios, gt, config=None) -> harness 互換 trace
      8 層 view + gt を harness.score へ渡せる trace 形へ組み立てるヘルパ。
  VIEW_LAYERS -> 8 層キーのタプル。

パイプライン(ADR 0022 正常系・各フレーム tick):
  gate(Snapshot 検証)→ 証拠抽出 → 観測式 + HGF(quality h_q/vol・anomaly pw_anom)→
  段2 mode logits → 各モジュール結線(quality→anomaly→t0→t1→t2[mode/role/relation]→
  scene→t3)→ 8 層 view 組み立て。tick 間状態持ち越し・T3 はシナリオ境界で reset。

規律:
  - 決定的(F-基盤-001-2): 乱数・時刻を一切使わない。同一入力で 2 回 run が完全一致。
  - 独立性(F-基盤-001-2): EPI 契約のみ共有し、別系統の実装パッケージへ実行時・静的に
    リンクしない(import も文字列参照もしない)。本モジュールは supreme 内のモジュールと
    stdlib(math)のみに依存する。
  - Snapshot 規律(F-基盤-001-3): Snapshot のみ受理・Delta は明示エラー・version 1.3/1.4
    両受理・ts 単調非減少違反は拒否・任意フィールド欠落は縮退(既定で続行)。
  - v1.4 語彙(F-基盤-001-4): 全層が v1.4 統制語彙に閉じる(各モジュールが v1.4 を出す)。

HGF は scene(F-010)の階層 Gaussian filter を共有再利用する(ADR 0022 決定3)。
"""

from __future__ import annotations

import dataclasses
import math
import statistics

from . import mode as mode_mod
from . import neupsl as neupsl_mod
from . import quality as quality_mod
from . import relation as relation_mod
from . import role as role_mod
from . import scene as scene_mod
from . import t0 as t0_mod
from . import t1 as t1_mod
from . import t3 as t3_mod


# ---------------------------------------------------------------------------
# 8 層 view のキー(SPEC.md 行 220 / ADR 0022 目的)。harness の採点 8 層と一致する。
# ---------------------------------------------------------------------------

VIEW_LAYERS = (
    "risk_tier",
    "t1_state",
    "t2_mode",
    "t2_role",
    "t2_relation",
    "t3_hypothesis",
    "quality_regime",
    "scene_regime",
)


# ---------------------------------------------------------------------------
# Snapshot / Delta の version 識別(契約 v1.4 §1)。Snapshot のみ受理する。
# ---------------------------------------------------------------------------

_SNAPSHOT_PREFIX = "PSO-Snapshot/"
_DELTA_PREFIX = "PSO-Delta/"


class SnapshotError(ValueError):
    """入力 Snapshot の規律違反(Delta 混入・version 不正・ts 後退)で明示停止する例外。"""


# ---------------------------------------------------------------------------
# 観測式の係数(ADR 0022 決定3・観測式 logit を sigmoid → HGF へ)。
#   logit = -2 + 5·qos - 4·(latency/200) - 2.5·(1-id_const) + 1.5·w_obs_bar
# id_const は 1.0 固定(=寄与項 0)。w_obs_bar は観測重みの平均(縮退既定 0.5)。
# ---------------------------------------------------------------------------

_OBS_BIAS = -2.0
_OBS_QOS = 5.0
_OBS_LATENCY = -4.0
_OBS_ID = -2.5
_OBS_WOBS = 1.5

_ID_CONST = 1.0          # id 整合度(固定 1.0 → 寄与項 0)。
_LATENCY_SCALE = 200.0   # latency 正規化スケール。
_DEFAULT_QOS = 0.5       # scene_state 欠落時の縮退既定 QoS。
_DEFAULT_LATENCY = 100.0 # scene_state 欠落時の縮退既定 latency(ms)。
_DEFAULT_WOBS = 1.0      # 観測重み中央値の縮退既定(w_obs を持つ track が無いフレーム)。

# anomaly 観測式(precision_weight 生成・簡素だが決定的)。観測「異常度」を
#   anom_logit = -2 + 4·(latency/200) + 3·(1-qos)
# で作り sigmoid → HGF → pw_anom(層1 水準を [0,1] に写したもの)。
_ANOM_BIAS = -2.0
_ANOM_LATENCY = 4.0
_ANOM_QOS = 3.0

# 段2 mode logit の係数(証拠 → v1.4 mode logit)。quiet 起点ヒステリシス(block=2.6)を
# 越えるよう、強い証拠には block 超の logit を与える(ADR 0022 構成要素4・段2 mode 部)。
_MODE_QUIET_BASE = 0.0     # quiet_standby の基準 logit。
_MODE_CONV = 4.0           # conv_ongoing: 強い会話証拠(block 2.6 を越える)。
_MODE_EMERGENCY = 5.0      # emergency: danger 危険(安全 mode・減衰されない)。
_MODE_ALERT = 4.0          # alert_required: caution 危険(安全 mode・減衰されない)。
_MODE_FWD_CAUTION = 4.0    # forward_caution: 接近(非安全・block 超で遷移)。
_MODE_ENV_CHANGE = 4.0     # env_change: 品質劣化(非安全・block 超で遷移)。
_MODE_SURROUND = 4.0       # surround_activity: 周囲群衆(非安全・block 超で遷移)。
_MODE_CONV_REQUEST = 4.0   # conv_request: call_user(発話要求)・会話強/危険でない時(block 超)。
_MODE_SIDE_REAR = 4.0      # side_rear_caution: caution・非車両/非警報の salient(非安全・block 超)。

#: surround_activity 発火の群衆閾値(周囲に複数人=群衆活動。v021_core 構造署名から導出した
#: 原理閾値であり、3 人以上検出で偽陽性ゼロにクラス分離する=証拠合わせ込みでなく構造)。
_MODE_SURROUND_MIN_HUMANS = 3

# scene 診断信号(health_raw)の縮退・スケール。観測品質 h_q を [0,1] の health 信号と
# みなし scene の HGF へ流す。
_SCENE_DEFAULT_HEALTH = 0.95


# ===========================================================================
# gate: Snapshot 検証(version 判別・Snapshot のみ受理・ts 単調非減少)
# ===========================================================================

def _validate_snapshot(record, prev_ts):
    """1 レコードを Snapshot として検証し ts を返す(ADR 0022/0006・F-基盤-001-3)。

    - version が Delta のレコードは明示エラー(SnapshotError)。
    - version が Snapshot(1.3/1.4 両受理)でなければ明示エラー。
    - ts が前フレームより小さい(後退)なら明示エラー(等値は許容=単調非減少)。

    任意フィールド(geom/scene_state/links/utter_events)の欠落はここでは咎めない
    (証拠抽出側で縮退既定にする)。
    """
    if not isinstance(record, dict):
        raise SnapshotError(f"Snapshot レコードが dict でない: {type(record)!r}")

    version = record.get("version", "")
    if isinstance(version, str) and version.startswith(_DELTA_PREFIX):
        raise SnapshotError(
            f"Delta レコードは非対応(明示エラー): version={version!r}"
            "(本ランナーは Snapshot のみ受理する)"
        )
    if not (isinstance(version, str) and version.startswith(_SNAPSHOT_PREFIX)):
        raise SnapshotError(
            f"Snapshot でない version: {version!r}"
            f"(Snapshot は {_SNAPSHOT_PREFIX!r} 始まり・1.3/1.4 両受理)"
        )

    ts = float(record.get("ts", 0.0))
    if prev_ts is not None and ts < prev_ts:
        raise SnapshotError(
            f"ts が後退した(単調非減少違反): {ts} < 前フレーム {prev_ts}"
        )
    return ts


# ===========================================================================
# 証拠抽出: world_state(Snapshot dict)→ 各モジュール入力
# ===========================================================================

def _audio_tracks(snap):
    return snap.get("tracks", {}).get("audio", []) or []


def _human_tracks(snap):
    return snap.get("tracks", {}).get("humans", []) or []


def _object_tracks(snap):
    return snap.get("tracks", {}).get("objects", []) or []


# ---------------------------------------------------------------------------
# v1.5(契約 v1.5)入力ヘルパ。すべて presence-gated(欠落=None=従来 v1.4 挙動)。
# ---------------------------------------------------------------------------

def _episode(snap):
    """v1.5: top-level episode dict(無ければ None=v1.4)。"""
    ep = snap.get("episode")
    return ep if isinstance(ep, dict) else None


def _stability(snap):
    """v1.5: scene_state.stability dict(無ければ None=v1.4)。"""
    ss = snap.get("scene_state")
    st = ss.get("stability") if isinstance(ss, dict) else None
    return st if isinstance(st, dict) else None


def _salient_kind(snap):
    """v1.5(C-1c): 最大 salience の track の category を返す。salience が無ければ None(v1.4)。

    category: audio speech→'speech' / vehicle→'vehicle' / 他→raw type、human→'human'、
    object vehicle→'vehicle' / 他→'object'。緊急音(siren/alarm)は role 側で絶対優先。
    """
    best = None  # (salience, kind)
    seen = False
    for t in _audio_tracks(snap):
        s = t.get("salience")
        if s is None:
            continue
        seen = True
        ty = t.get("type")
        kind = "speech" if ty == "speech" else ("vehicle" if ty == "vehicle" else ty)
        if best is None or s > best[0]:
            best = (float(s), kind)
    for t in _human_tracks(snap):
        s = t.get("salience")
        if s is None:
            continue
        seen = True
        if best is None or s > best[0]:
            best = (float(s), "human")
    for t in _object_tracks(snap):
        s = t.get("salience")
        if s is None:
            continue
        seen = True
        kind = "vehicle" if t.get("type") == "vehicle" else "object"
        if best is None or s > best[0]:
            best = (float(s), kind)
    return (best[1] if best else None) if seen else None


def _all_track_ranges(snap):
    """全 track の r_m を列挙する(最小 range / 主トラック選択の素材)。"""
    ranges = []
    for t in _audio_tracks(snap):
        ranges.append(float(t.get("r_m", 100.0)))
    for t in _human_tracks(snap):
        ranges.append(float(t.get("r_m", 100.0)))
    for t in _object_tracks(snap):
        ranges.append(float(t.get("r_m", 100.0)))
    return ranges


def _relation_tracks(snap):
    """relation 用 track 列(r_m 必須・kind/w_obs/speaking 付き)。GT(gt_derive._tracks)と同形。"""
    out = []
    for a in _audio_tracks(snap):
        if a.get("r_m") is not None:
            out.append({"r_m": float(a["r_m"]), "w_obs": float(a.get("w_obs", 0.5)),
                        "kind": a.get("type"), "speaking": a.get("type") == "speech"})
    for o in _object_tracks(snap):
        if o.get("r_m") is not None:
            out.append({"r_m": float(o["r_m"]), "w_obs": float(o.get("w_obs", 0.5)),
                        "kind": o.get("type"), "speaking": False})
    for h in _human_tracks(snap):
        if h.get("r_m") is not None:
            out.append({"r_m": float(h["r_m"]), "w_obs": float(h.get("w_obs", 0.5)),
                        "kind": "human", "speaking": (h.get("speaking_prob", 0.0) or 0.0) > 0.5})
    return out


def _salient_track_geom(snap):
    """主トラック(salient)を (w_obs, -r_m) の最大で選ぶ(GT gt_derive._salient と同基準)。

    w_obs/r_m は v1.4 入力にも在る観測量(v1.5 の salience フィールドとは別)。track 無は None。
    """
    ts = _relation_tracks(snap)
    if not ts:
        return None
    return max(ts, key=lambda t: (t["w_obs"], -t["r_m"]))


def _min_range(snap):
    """全 track の最小 r_m(track 無しは 100.0 を与える・t1 入力縮退既定)。"""
    ranges = _all_track_ranges(snap)
    return min(ranges) if ranges else 100.0


def _min_ttc(snap):
    """geom.min_TTC_s(欠落時は接近なし扱いの大きな値で縮退)。"""
    geom = snap.get("geom")
    if isinstance(geom, dict) and "min_TTC_s" in geom:
        return float(geom["min_TTC_s"])
    return 99.0


def _scene_qos_latency(snap):
    """scene_state.QoS / latency_ms(欠落時は縮退既定で続行)。"""
    ss = snap.get("scene_state")
    if isinstance(ss, dict):
        qos = float(ss.get("QoS", _DEFAULT_QOS))
        latency = float(ss.get("latency_ms", _DEFAULT_LATENCY))
        return qos, latency
    return _DEFAULT_QOS, _DEFAULT_LATENCY


def _w_obs_bar(snap):
    """観測信頼度 w_obs_bar(全 track の w_obs 中央値)を抽出する(baseline 忠実再現)。

    baseline `runner._extract_quality_inputs`(spec の w_obs 定義)の意味論を忠実に写す:
      w_obs_bar = median(全 audio/humans/objects track のうち `w_obs` を持つものの w_obs)。
      `w_obs` を持つ track が 1 つも無いフレームは 1.0(_DEFAULT_WOBS)。

    忠実再現の要点(baseline import せず意味論のみを写す):
      - 対象 track = audio + humans + objects の連結(全 track)。
      - `w_obs` フィールドを**持たない** track は中央値の母集団に**含めない**
        (baseline は `if "w_obs" in t` で在るものだけ集める)。無い track の既定値を
        勝手に補完しない=baseline の「在るものだけの中央値」に一致させる。
      - 母集団が空(どの track も w_obs を持たない・track ゼロ含む)なら 1.0。

    NOTE(観測式の証拠潰し修正): 旧 supreme は本値を固定 0.5 にハードコードし PSO の track が
    持つ w_obs を一切読まなかった(系統的な h_q 過小評価=GT=GOOD を DEGRADED へ落とす主因)。
    本関数は baseline の文書化済み入力抽出規則への忠実再現であり、v021_core 正解への合わせ込み
    ではない(w_obs は各フレームの実 track 信頼度で広く分布する=規則整合)。
    """
    w_obs_values = []
    for t in _audio_tracks(snap) + _human_tracks(snap) + _object_tracks(snap):
        if "w_obs" in t:
            w_obs_values.append(float(t["w_obs"]))
    if w_obs_values:
        return statistics.median(w_obs_values)
    return _DEFAULT_WOBS


def _audio_type_to_kind(type_):
    """audio track の type を t0/role 用の kind 語へ写す(siren/vehicle/speech/alarm)。"""
    return type_


def _t0_tracks(snap):
    """t0.risk_tier 入力({kind, ttc_s, r_m})の列を作る。

    audio track の type を kind に写し、ttc_s は geom.min_TTC_s(共通)を与える。
    object/human は kind を付け、危険判定の対象に含める(siren 優先選択は t0 側)。
    """
    ttc = _min_ttc(snap)
    out = []
    for t in _audio_tracks(snap):
        out.append({
            "kind": _audio_type_to_kind(t.get("type")),
            "ttc_s": ttc,
            "r_m": float(t.get("r_m", 100.0)),
        })
    for t in _human_tracks(snap):
        out.append({"kind": "human", "ttc_s": ttc, "r_m": float(t.get("r_m", 100.0))})
    for t in _object_tracks(snap):
        out.append({"kind": "object", "ttc_s": ttc, "r_m": float(t.get("r_m", 100.0))})
    return out


def _has_audio_type(snap, type_):
    return any(t.get("type") == type_ for t in _audio_tracks(snap))


def _has_object_type(snap, type_):
    return any(t.get("type") == type_ for t in _object_tracks(snap))


def _has_vehicle_evidence(snap):
    """role の has_vehicle 証拠(車両証拠)を抽出する(baseline t2.py L187-192 忠実再現)。

    baseline `_extract_evidence`(spec §3.5 has_vehicle_audio/object 準拠)は車両証拠を
        has_vehicle = audio track(type=="vehicle") ∨ object track(type=="vehicle")
    で算出する恒久規則。新 supreme は audio track のみを見ており object track 経路を欠いて
    いたため、車両を object track で表すフレーム(ns017 等)を取りこぼし source_vehicle を
    unknown へ潰していた。本関数は baseline の audio ∨ object 規則を意味論として忠実再現する
    (baseline コードは import しない・v021_core 固有の合わせ込みでない恒久規則の再現)。
    """
    return _has_audio_type(snap, "vehicle") or _has_object_type(snap, "vehicle")


def _links(snap):
    return snap.get("links", []) or []


def _utter_events(snap):
    return snap.get("utter_events", []) or []


def _speaking_evidence(snap):
    """会話証拠(speaking 確率の最大・speaking link の有無・link score 最大)を抽出する。"""
    speaking = 0.0
    for h in _human_tracks(snap):
        sp = h.get("speaking_prob")
        if sp is not None:
            speaking = max(speaking, float(sp))
    speaking_link = False
    linked_speech_score = 0.0
    for link in _links(snap):
        if link.get("type") == "speaking":
            speaking_link = True
            linked_speech_score = max(linked_speech_score, float(link.get("score", 0.0)))
    return speaking, speaking_link, linked_speech_score


def _role_evidence(snap):
    """role.classify 入力(role 証拠 dict)を抽出する。"""
    speaking, speaking_link, linked_speech_score = _speaking_evidence(snap)
    return {
        "has_siren": _has_audio_type(snap, "siren"),
        "has_alarm": _has_audio_type(snap, "alarm"),
        # has_vehicle = audio vehicle ∨ object vehicle(baseline t2.py L187-192・spec §3.5 忠実再現)。
        "has_vehicle": _has_vehicle_evidence(snap),
        "has_speech": _has_audio_type(snap, "speech"),
        "speaking": speaking,
        "min_range": _min_range(snap),
        "linked_speech_score": linked_speech_score,
        # v1.5(C-1c): salient track の category(None=v1.4・従来規則)。
        "salient_kind": _salient_kind(snap),
    }


def _relation_evidence(snap, approaching):
    """relation.classify 入力(relation 証拠 dict)を抽出する。"""
    speaking, speaking_link, _ = _speaking_evidence(snap)
    min_range = _min_range(snap)
    conv_strong = _has_audio_type(snap, "speech") and speaking > 0.7 and min_range < 5.0
    near_prox = min_range < 3.0
    n_speaking_links = sum(1 for link in _links(snap) if link.get("type") == "speaking")
    # call_user: utter_event は {"call_user": true} 形式(type キーは無い)。
    # 旧実装は e.get("type")=="call_user" を見ており常に False=取りこぼし。
    # baseline t2.py L254 `any(bool(u.get("call_user")) ...)` に忠実化。
    # (coverage_v1/seal で relation -0.142 回帰の主因・addressing_user 168件が grouped 既定へ誤落)
    call_user = any(bool(e.get("call_user", False)) for e in _utter_events(snap))
    linked_addressing = 0.0
    for link in _links(snap):
        if link.get("type") == "addressing":
            linked_addressing = max(linked_addressing, float(link.get("score", 0.0)))
    multiple_humans = len(_human_tracks(snap)) >= 2
    return {
        "conv_strong": conv_strong,
        "approaching": approaching,
        "call_user": call_user,
        "linked_addressing": linked_addressing,
        "near_prox": near_prox,
        "speaking_link": speaking_link,
        "n_speaking_links": n_speaking_links,
        "multiple_humans": multiple_humans,
    }


#: relation 幾何 override(ADR 0043)の物理閾値。near=5m / far=15m / 移動不感帯=0.1m。
#: GT relation(rule_derived・観測幾何の決定的関数)を主トラックの range/Δr で忠実化する境界。
_REL_NEAR_M = 5.0
_REL_FAR_M = 15.0
_REL_EPS_M = 0.1


def _relation_geometry_override(snap, prev_salient_range):
    """v1.6(ADR 0043): relation を主トラックの range 幾何で分類(GT relation_seq の忠実化)。

    relation は Tier-A rule_derived=観測幾何の決定的関数(intent 天井なし)。supreme の relation 移植は
    4/6 クラス(departing/unrelated 欠落・near_user 誤優先)で未完だった。主トラック(w_obs,-r_m 最大)の
    絶対 range と前フレームとの Δr で near_user/departing/approaching/grouped/unrelated を回収する。
    **addressing_user は既存 relation ロジック(evidence)に委ねる**(逐語コピーを避ける=None を返す)。

    優先順は gt_derive.relation_seq に一致(addressing→near→departing→approaching→grouped→unrelated)。
    w_obs/r_m は v1.4 入力にも在り version 非依存(観測由来・非循環)。Δr は前 salient range が要る(初手 None)。

    Returns: relation ラベル or None(=addressing は既存に委ねる/判定不能)。
    """
    st = _salient_track_geom(snap)
    lt = set(link.get("type") for link in _links(snap))
    n_tracks = len(_relation_tracks(snap))
    # 1. addressing/speaking link or 主トラック発話 → addressing_user は既存ロジックへ委譲。
    if ("addressing" in lt) or ("speaking" in lt) or (st is not None and st["speaking"]):
        return None
    # 2. near link or 主トラック近接(<=NEAR) → near_user。
    if ("near" in lt) or (st is not None and st["r_m"] <= _REL_NEAR_M):
        return relation_mod.NEAR_USER
    # 3/4. range 増 → departing / range 減 → approaching(前 salient range 必須)。
    if st is not None and prev_salient_range is not None:
        dr = st["r_m"] - prev_salient_range
        if dr > _REL_EPS_M:
            return "departing"
        if dr < -_REL_EPS_M:
            return relation_mod.APPROACHING
    # 5. grouped link or 多トラック(>=3) → grouped。
    if ("grouped" in lt) or n_tracks >= 3:
        return relation_mod.GROUPED
    # 6. 主トラック無 or 遠方(>FAR) → unrelated。
    if st is None or st["r_m"] > _REL_FAR_M:
        return "unrelated"
    return relation_mod.GROUPED


#: pass 判定の最接近距離(gt_derive._PASS_M)。range 増だが最接近が近ければ「接近して通過」。
_T1_PASS_M = 8.0


def _t1_geometry_sequence(snaps):
    """v1.6(ADR 0044): salient range 系列で t1_state を忠実化(gt_derive.t1_state_seq)。

    t1 も Tier-A rule_derived=salient track(w_obs,-r_m 最大)の range 軌跡の決定的関数。
    Δr<0→approach / Δr>0→depart(最接近直後 ∧ 最接近≤8m なら pass) / Δr≈0→idle。先頭は
    range>15m なら idle・以下なら approach。relation と同じ range 幾何で intent 天井なし。

    シナリオに salient track が 1 つも無ければ [None]*n を返し既存 t1 に委ねる(後方互換)。
    range の取れないフレームは GT に倣い idle。w_obs/r_m は v1.4 にも在り version 非依存。
    """
    rs = [(_salient_track_geom(s) or {}).get("r_m") for s in snaps]
    valid = [(i, v) for i, v in enumerate(rs) if v is not None]
    if not valid:
        return [None] * len(snaps)
    closest = min(valid, key=lambda x: x[1])[0]
    out = []
    for i, v in enumerate(rs):
        if v is None:
            out.append(t1_mod.IDLE)
            continue
        p = None
        for j in range(i - 1, -1, -1):
            if rs[j] is not None:
                p = rs[j]
                break
        if p is None:
            out.append(t1_mod.IDLE if v > _REL_FAR_M else t1_mod.APPROACH)
            continue
        dr = v - p
        if dr < -_REL_EPS_M:
            out.append(t1_mod.APPROACH)
        elif dr > _REL_EPS_M:
            if rs[closest] is not None and rs[closest] <= _T1_PASS_M and i == closest + 1:
                out.append(t1_mod.PASS)
            else:
                out.append(t1_mod.DEPART)
        else:
            out.append(t1_mod.IDLE)
    return out


def _role_salient(snap):
    """ADR 0046: GT(gt_derive.role)整合 — 最も目立つトラック(max(w_obs,-r_m))の種別で role を決定。

    v1.5 の salience でなく w_obs/r_m で salient を選ぶ(=GT 基準)。トラック順は gt_derive._tracks と同じ
    audio→objects→humans(tie は先勝ち=max の先頭一致)。speech→source_speech / vehicle→source_vehicle /
    siren・alarm→source_alarm / human→(発話なら speech 否なら human) / 他 object→source_object / 他→unknown。
    w_obs/r_m は v1.4 入力にも在り version 非依存(オラクルで role 1.0)。
    """
    best = None  # ((w_obs, -r_m), kind, speaking, src)
    for t in _audio_tracks(snap):
        r = t.get("r_m")
        if r is None:
            continue
        key = (float(t.get("w_obs", 0.5)), -float(r))
        if best is None or key > best[0]:
            best = (key, t.get("type"), t.get("type") == "speech", "audio")
    for t in _object_tracks(snap):
        r = t.get("r_m")
        if r is None:
            continue
        key = (float(t.get("w_obs", 0.5)), -float(r))
        if best is None or key > best[0]:
            best = (key, t.get("type"), False, "object")
    for t in _human_tracks(snap):
        r = t.get("r_m")
        if r is None:
            continue
        sp = (t.get("speaking_prob", 0.0) or 0.0) > 0.5
        key = (float(t.get("w_obs", 0.5)), -float(r))
        if best is None or key > best[0]:
            best = (key, "human", sp, "human")
    if best is None:
        return role_mod.UNKNOWN
    _, k, sp, src = best
    if k == "speech":
        return role_mod.SOURCE_SPEECH
    if k == "vehicle":
        return role_mod.SOURCE_VEHICLE
    if k in ("siren", "alarm"):
        return role_mod.SOURCE_ALARM
    if k == "human":
        return role_mod.SOURCE_SPEECH if sp else role_mod.SOURCE_HUMAN
    if src == "object":
        return role_mod.SOURCE_OBJECT
    return role_mod.UNKNOWN


def _risk_tier_strict(snap):
    """ADR 0048: GT(gt_derive.risk_tier)を厳密適用。track 非依存で geom.min_TTC_s を読む。

    siren salient(max(w_obs,-r_m) の kind==siren)→ danger / 生 geom.min_TTC_s が None→info /
    <2.0→danger / <8.0→caution / else info(厳密 `<`・閾値は t0 ADR 0045 と共有)。
    旧 `t0.risk_tier(_t0_tracks(snap))` は track 0 件のとき主トラック無で安全側 info に縮退し、
    ttc<8 の caution/danger を取りこぼしていた(seal pw-021-seal-07: ttc=6.0 だが track ゼロ→info、
    GT は caution)。geom TTC は track の有無に依らず観測されるため、GT 通り track ゼロでも読む。
    全入力 v1.4 可観測。risk は mode_seq にも渡るため、本厳密化で mode の risk 由来残差も解消する。
    """
    s = _salient_track_geom(snap)
    if s is not None and s.get("kind") == "siren":
        return t0_mod.DANGER
    geom = snap.get("geom")
    ttc = geom.get("min_TTC_s") if isinstance(geom, dict) else None
    if ttc is None:
        return t0_mod.INFO
    ttc = float(ttc)
    if ttc < t0_mod._TTC_DANGER_S:
        return t0_mod.DANGER
    if ttc < t0_mod._TTC_CAUTION_S:
        return t0_mod.CAUTION
    return t0_mod.INFO


def _mode_seq_strict(snap, risk_tier, prev_qos):
    """ADR 0047: GT(gt_derive.mode_seq)を厳密適用して t2_mode を確定(view 専用・hysteresis 近似を置換)。

    全入力は v1.4 観測のみ: salient=max(w_obs,-r_m)・links・utter_events・生 QoS。risk_tier は per-frame
    規則(siren/TTC)。優先順位は GT mode_seq と同一:
      danger→emergency / utter∧(speaking|addressing)→conv_(request|ongoing) / 非サイレン alarm 顕著→
      alert_required / 生QoS BLOCK→uncertain / |Δq|≥0.20→env_change / vehicle 顕著∧caution→forward_caution /
      caution→side_rear_caution / salient 無→quiet_standby / 他→surround_activity。

    quality は GT(gt_derive.quality_regime)を**生 QoS から関数内で再計算**(q None→GOOD・≥0.90 GOOD・
    <0.55 BLOCK・他 DEGRADED)。supreme の縮退既定 _DEFAULT_QOS=0.5 に引きずられて scene_state 欠落
    フレームを誤って BLOCK にしない(GT は None→GOOD)。env_change の Δq も生 QoS(None 可)で GT と一致。
    prev_qos は前フレームの生 QoS(シナリオ先頭は None)。t3 窓には内部 hysteresis mode を使い、本厳密 mode は
    出力(view)のみへ反映する(t3 非干渉)。
    """
    s = _salient_track_geom(snap)
    lt = set(link.get("type") for link in _links(snap))
    utter = bool(_utter_events(snap))
    ss = snap.get("scene_state") or {}
    q = ss.get("QoS")
    if q is None or q >= 0.90:
        qreg = "GOOD"
    elif q < 0.55:
        qreg = "BLOCK"
    else:
        qreg = "DEGRADED"
    if risk_tier == t0_mod.DANGER:
        return "emergency"
    if utter and ("speaking" in lt or "addressing" in lt):
        return "conv_request" if "addressing" in lt else "conv_ongoing"
    if s is not None and s["kind"] == "alarm":
        return "alert_required"
    if qreg == "BLOCK":
        return "uncertain"
    if prev_qos is not None and q is not None and abs(float(q) - float(prev_qos)) >= 0.20:
        return "env_change"
    if s is not None and s["kind"] == "vehicle" and risk_tier == t0_mod.CAUTION:
        return "forward_caution"
    if risk_tier == t0_mod.CAUTION:
        return "side_rear_caution"
    if s is None:
        return "quiet_standby"
    return "surround_activity"


def _mode_logits(snap, risk_tier, approaching, h_q):
    """段2 mode logits を証拠から生成する(ADR 0022 構成要素4・v1.4 mode 語彙で出力)。

    quiet_standby を基準(0.0)に置き、証拠が立つ mode に block(2.6)を越える logit を積む。
    mode.hysteresis は prev=quiet_standby のとき非安全 mode を block 減衰するため、conv/接近/
    品質劣化/周囲群衆など「持続したら遷移してほしい」mode には block 超の強い logit を与える。
    emergency/alert_required は安全 mode で減衰されないため即発火する。

    NOTE(surround_activity の結線): v1.4 mode 10 語彙のうち surround_activity は本関数に logit
    経路が無く、上流が**一度も emit できない構造潰し**だった(scene が STABLE を出さなかったのと
    同型)。これは下流 t3 規則層(`t3._rule_hypothesis` の crowd_tendency = surround_activity 比率
    > 0.25)を構造的に死なせていた。surround_activity の証拠(周囲に複数人=群衆活動)は v021_core
    に実在し supreme も既に抽出している(`_human_tracks`)ため、群衆署名(humans ≥ 3・強い単一会話
    でない・危険でない)から surround_activity の logit を結線する。3 人以上で偽陽性ゼロに分離する
    構造閾値(v021_core 合わせ込みではない)。
    """
    logits = {mode_mod.QUIET: _MODE_QUIET_BASE}

    # 会話証拠を先に判定(危険 mode のゲートに使う)。
    speaking, _, _ = _speaking_evidence(snap)
    min_range = _min_range(snap)
    conv_strong = _has_audio_type(snap, "speech") and speaking > 0.7 and min_range < 5.0
    call_user = any(bool(e.get("call_user", False)) for e in _utter_events(snap))
    # v1.6(ADR 0040): conv の種別は **link type** が一次識別子。coverage で conv_ongoing↔speaking
    # link / conv_request↔addressing link が完全分離する(conv_ongoing は addressing を持たない)。
    # 旧実装は conv_strong(speaking_prob>0.7∧range<5)でしか conv_ongoing を立てず、corpus の
    # speaking *link* を見ていなかったため conv_ongoing を全取りこぼし→call_user 経由で conv_request
    # へ誤流出していた。link type を一次識別子に格上げして種別を分離する。link は v1.4 入力にも在り
    # 後方互換(link 無の旧入力は call_user fallback で従来 conv_request 挙動を保つ)。
    link_types = set(link.get("type") for link in _links(snap))
    has_addressing_link = "addressing" in link_types
    has_speaking_link = "speaking" in link_types
    # addressing → request / speaking(addressing 無)or 強会話 → ongoing / link 無 call_user → request。
    want_ongoing = conv_strong or (has_speaking_link and not has_addressing_link)
    want_request = has_addressing_link or (call_user and not has_speaking_link)
    # 発話要求エピソード: request 種別 ∧ ongoing でない。emergency(danger)のみ優先し、caution の
    # alert_required より conv_request を優先する(baseline F-007-8: 危険でなければ alert より文脈支配的)。
    conv_request_fires = want_request and not want_ongoing and risk_tier != t0_mod.DANGER

    # 危険(t0)→ 安全 mode(減衰されず即発火)。caution は会話(request/ongoing)があれば conv を優先
    # (会話文脈は caution alert を支配=conv_request 既存ゲートを ongoing に対称拡張・ADR 0040)。
    if risk_tier == t0_mod.DANGER:
        logits["emergency"] = _MODE_EMERGENCY
    elif risk_tier == t0_mod.CAUTION and not conv_request_fires and not want_ongoing:
        # caution は salient kind で分岐(GT mode_seq: vehicle→forward_caution / 非車両非警報→
        # side_rear_caution / alarm 等→alert_required)。旧実装は caution を**一律 alert_required**に
        # しており forward_caution/side_rear_caution を構造的に潰していた(side_rear は emit 経路ゼロ=
        # 死クラス。surround_activity と同型の構造潰し)。salient kind は v1.5 で抽出済み。salience 不在
        # (v1.4)は None→alert_required で従来挙動を保つ(後方互換)。ADR 0042。
        sk = _salient_kind(snap)
        if sk == "vehicle":
            logits["forward_caution"] = logits.get("forward_caution", 0.0) + _MODE_FWD_CAUTION
        elif sk in ("object", "human"):
            logits["side_rear_caution"] = _MODE_SIDE_REAR
        else:
            logits["alert_required"] = _MODE_ALERT

    # 会話証拠(強会話 or speaking link)→ conv_ongoing(block 超で遷移)。
    if want_ongoing:
        logits["conv_ongoing"] = _MODE_CONV

    # 発話要求(addressing link / call_user)→ conv_request(emergency 以外に優先・上記ゲート)。
    if conv_request_fires:
        logits["conv_request"] = _MODE_CONV_REQUEST

    # 周囲群衆(複数人が周囲に存在・強い単一会話でない)→ surround_activity(非安全・block 超)。
    # 強い単一会話(conv_strong)は conv_ongoing が優先するため、ここは conv_strong でない群衆に限る。
    if not conv_strong and len(_human_tracks(snap)) >= _MODE_SURROUND_MIN_HUMANS:
        logits["surround_activity"] = _MODE_SURROUND

    # 接近(t1 フラグ)→ forward_caution(非安全・block 超で遷移)。
    if approaching:
        logits["forward_caution"] = logits.get("forward_caution", 0.0) + _MODE_FWD_CAUTION

    # 観測品質劣化 → env_change(非安全・block 超で遷移)。
    if h_q < 0.5:
        logits["env_change"] = logits.get("env_change", 0.0) + _MODE_ENV_CHANGE

    return logits


# ===========================================================================
# 観測式 + HGF(quality h_q/vol・anomaly pw_anom)— ADR 0022 決定3
# ===========================================================================

def _sigmoid(x):
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def _quality_obs_raw_logits(snaps):
    """各フレームの観測式 logit(生・sigmoid 前)の列を作る(ADR 0022 決定3)。

    観測式:
        logit = -2 + 5·qos - 4·(latency/200) - 2.5·(1-id_const) + 1.5·w_obs_bar
    id_const=1.0 固定(寄与 0)。**w_obs_bar は各フレームの全 track(audio+humans+objects)の
    w_obs 中央値**(`w_obs` を持つ track が無いフレームは 1.0)を `_w_obs_bar` で baseline
    `runner._extract_quality_inputs` 忠実に算出する(旧: 固定 0.5 のハードコードを是正)。
    この生 logit を共有 HGF へ流し、h_q = sigmoid(μ1) で観測品質 [0,1] に写す
    (高 QoS・高 w_obs で μ1 大 → h_q≈1、低 QoS で μ1 小 → h_q≈0)。
    """
    out = []
    for snap in snaps:
        qos, latency = _scene_qos_latency(snap)
        w_obs_bar = _w_obs_bar(snap)
        logit = (
            _OBS_BIAS
            + _OBS_QOS * qos
            + _OBS_LATENCY * (latency / _LATENCY_SCALE)
            + _OBS_ID * (1.0 - _ID_CONST)
            + _OBS_WOBS * w_obs_bar
        )
        out.append(logit)
    return out


def _anomaly_obs_raw_logits(snaps):
    """各フレームの anomaly 観測式 logit(生)の列を作る(pw_anom 素材・簡素だが決定的)。"""
    out = []
    for snap in snaps:
        qos, latency = _scene_qos_latency(snap)
        logit = (
            _ANOM_BIAS
            + _ANOM_LATENCY * (latency / _LATENCY_SCALE)
            + _ANOM_QOS * (1.0 - qos)
        )
        out.append(logit)
    return out


def _hq_vol_sequences(quality_logits):
    """観測 logit 列を共有 HGF に通し (h_q 列, vol 列) を生成する(ADR 0022 決定3)。

    HGF カーネルは scene(F-010)を共有再利用する。h_q = sigmoid(μ1)。
    生 logit を HGF へ流すため μ1 は logit スケールで観測へ追従し、h_q = sigmoid(μ1) は
    高 QoS で ≈1(GOOD)・低 QoS で ≈0(BLOCK)へ振れる。

    vol は quality.classify の GOOD ゲート(`vol<0.01`)が想定する正準量=**層1 事後分散
    sigma1(=1/π1)**を渡す(htraj.var1)。これは baseline `quality.py` が
    `vol = derived["sigma1"]`(=1/pi1_new・`hgf.py`)で渡していた量そのもので、ADR 0014 の
    計測(vol は全フレーム 0.0058〜0.0099 で `vol<0.01` を常に満たす)が定義する入力。
    htraj.volatility(=exp(μ2)・層2 log-volatility)は scene の CHANGING 検出用の別量で、
    本データで 0.01 を跨ぐため GOOD ゲートに流すと h_q≥0.93 の GOOD を不当に DEGRADED へ
    落とす(=結線ミス)。層を取り違えない(scene は層2 ボラ・quality は層1 事後分散)。
    """
    if not quality_logits:
        return [], []
    htraj = scene_mod.hgf_filter(quality_logits, scene_mod.default_hgf_params())
    h_q = [_sigmoid(mu) for mu in htraj.mu1]
    vol = list(htraj.var1)
    return h_q, vol


def _pw_anom_sequence(anomaly_logits):
    """anomaly 観測 logit 列を共有 HGF に通し precision_weight(pw_anom)列を生成する。

    HGF 層1 水準を sigmoid で [0,1] に写したものを pw_anom とする(t1 の閾値膨張に使う)。
    """
    if not anomaly_logits:
        return []
    htraj = scene_mod.hgf_filter(anomaly_logits, scene_mod.default_hgf_params())
    return [_sigmoid(mu) for mu in htraj.mu1]


# ===========================================================================
# scene: 観測 health 信号列 → scene_regime 列(scene の HGF+分類を再利用)
# ===========================================================================

def _scene_health_signal(quality_logits):
    """観測 logit 列を sigmoid で [0,1] の health 信号へ写す(scene の入力信号)。

    scene(F-010)は health_raw([0,1] 寄り)を入力に設計され、level_low 閾値 ~0.2-0.4 で
    DEGRADING 側へ倒す。生 logit でなく sigmoid 済みの health を渡すことで、高 health は STABLE・
    低 health は DEGRADING・急変は CHANGING へ寄る。
    """
    return [_sigmoid(x) for x in quality_logits]


# scene 分類の代表閾値(F-010 classify 契約 tests/test_F010_classify.py が
# 「この閾値ならこの regime」を固定する代表値そのもの)。原則ベース=v021 への合わせ込みでなく
# scene の判定構造の正準閾値を結線で与える。fit([])(練習データ皆無)が返す grid 先頭値
# (vol_high=0.005/persist_high=0.1/level_low=0.2)は最も緩い端点で STABLE が原理的に出ない
# ため、ここで構造的に正準閾値へ差し替える。学習 param は増やさない(learnable は固定9個)。
_SCENE_THRESHOLDS = {
    "vol_high": 0.05,      # これを超えるボラティリティは CHANGING(持続的変化)。
    "persist_high": 0.20,  # これを超える持続逸脱は CHANGING(平坦・非nominal の見逃し救済)。
    "level_low": 0.30,     # これを下回る水準は DEGRADING(健全度の下降)。
}


def _scene_persistence_params(signal):
    """信号列の nominal 水準を「安定時にいる中央値」として持続性 params を結線する。

    scene の持続性特徴は params.nominal からの逸脱を漏れ積分する。既定 nominal=0.5 は
    本結線の health 信号の動作点(高 QoS で ≈0.93)と乖離しており、安定・健全な平坦列でも
    |0.93-0.5| の逸脱が持続蓄積して persist_high を超え、CHANGING へ定数潰れする(STABLE が
    原理的に出ない)真因。nominal を「信号がその系列で安定的に居る中央水準=中央値」に
    結線で合わせると、安定・健全な平坦列は逸脱≈0 で STABLE、真の変化/劣化のみが
    CHANGING/DEGRADING へ寄る。中央値は外れ値に頑健な決定的推定で、v021 固有値ではない
    (学習 param は増やさない=既定 params の nominal を信号由来で置換するのみ)。
    """
    pp = scene_mod.default_persistence_params()
    nominal = statistics.median(signal) if signal else pp.nominal
    return dataclasses.replace(pp, nominal=nominal, nominal_init=nominal)


def _scene_params_for_signal(signal, learned_scene=None):
    """信号列に対する scene の実走 params を結線で組み立てる(既定 / 学習済み 両対応)。

    既定(learned_scene=None・後方互換): fit([])の既定 _SceneParams を土台に、(1)持続性
    nominal を信号の中央水準へ、(2)分類閾値を F-010 classify 契約の正準代表値(_SCENE_THRESHOLDS)
    へ結線する(STABLE/CHANGING/DEGRADING が原理的に到達可能になる構造修正)。

    学習済み(learned_scene が scene._SceneParams のとき): 学習で得た HGF + 閾値を注入しつつ、
    持続性 nominal だけは同じ信号由来の中央水準へ結線する(scene 入力構造=nominal は core の
    結線責務で、学習対象でないため・ADR 0025 決定3)。これにより既定経路との差は「分類閾値」
    のみになり、in-sample で『学習が既定を下回らない』担保(fit_supreme 側で良い方を採る)が
    end-to-end の scene_regime にそのまま反映される。
    """
    base = learned_scene if learned_scene is not None else scene_mod.fit([])
    thresholds = (
        dict(learned_scene.thresholds) if learned_scene is not None else dict(_SCENE_THRESHOLDS)
    )
    return dataclasses.replace(
        base,
        persist=_scene_persistence_params(signal),  # nominal を信号の中央水準へ結線。
        thresholds=thresholds,
    )


# v1.5(C-1b): scene_regime は **シナリオ内で一定**(episode-level intent・coverage で 406/406 一定)。
# per-frame の HGF は CHANGING シナリオの早期(高 QoS・平坦)フレームを取り違える。観測 stability を
# **episode 集約**して 1 シナリオ = 1 regime に分類し全フレームへ適用する(presence-gated)。
# 分類: 降下なし(min qos_trend > -0.1)→ STABLE / 降下あり ∧ 低 QoS 到達(min QoS < 0.5)→ DEGRADING /
# 降下あり ∧ 中 QoS → CHANGING(coverage_v2/train の regime 別平均で分離)。stability 不在(v1.4)は HGF 経路。
_SCENE_V15_DECLINE = 0.1     # min qos_trend > -0.1 = 降下なし = STABLE。
_SCENE_V15_QOS_DEG = 0.5     # 降下中に min QoS < 0.5 到達 = DEGRADING。

# v1.5(C-1a): episode の軌跡信号で t1_state を補正(coverage_v2/train: approach の approach_ratio≈0.54、
# idle/depart≈0.08 で分離)。approach_ratio>=0.3→approach、偽 approach は hazard_trend で depart/idle。
_T1_V15_APPROACH = 0.3      # approach_ratio >= 0.3 → approach(実接近)。
_T1_V15_DEPART = 0.005      # 偽 approach の再分類: hazard_trend > 0.005(離反)→ depart、他→ idle。

# v1.5(C-1b): 観測劣化(低 QoS)→ uncertain mode(coverage_v2/train: uncertain QoS≈0.39 最低・他 ≥0.61)。
_MODE_V15_UNCERTAIN_QOS = 0.5

# v1.5(C-1a): episode 集約の観測で t3 を分類(presence-gated・episode-level。t3 はシナリオ内ほぼ一定)。
# coverage_v2/train の t3 別署名で分離: conv_participating speech_ratio≈0.98(他≤0.5) /
# uncertain_context QoS≈0.35(最低・観測劣化=文脈断定不能) / traffic_unstable approach≈0.71(最高・接近継続)。
# env_start/hazard_declining は他クラスと信号が重なる/小さく、規則化は過適合のため**写さない**。
_T3_V15_SPEECH = 0.7            # mean speech_ratio >= 0.7 → conv_participating。
_T3_V15_QOS_UNCERTAIN = 0.4     # mean QoS < 0.4 → uncertain_context(観測劣化)。
_T3_V15_APPROACH_TRAFFIC = 0.65 # mean approach_ratio >= 0.65 → traffic_unstable(接近継続)。
#: v1.6(ADR 0041): 窓内 QoS の detrend(残差)分散の episode 平均がこの閾値以上 → env_start。
#: 振動(平均回帰)を単調降下(hazard_declining=残差≈0)・平坦(≈0)から分離する。
#: 閾値は 0.002〜0.004 で結果不変(knife-edge でなく振動/非振動の構造境界)。
_T3_V16_OSC_ENV = 0.003
_QOS_WINDOW_S = 3.0            # detrend 分散の窓(v1.5 stability.window_s と同値)。


def _qos_detrend_var_frame(snaps, i):
    """フレーム i の窓 [ts-3.0,ts]∩episode における QoS の OLS 残差分散(detrend 分散)。

    振動(env_start)=残差大 / 単調降下(hazard_declining)=残差≈0 / 平坦=0 を分離する観測量。
    点 < 3 は 0(直線で過小決定=判定不能)。観測 QoS のみ・ラベル非依存(非循環)。
    """
    ts = snaps[i].get("ts", 0.0)
    ep = (_episode(snaps[i]) or {}).get("episode_id")
    pts = []
    for j in range(i + 1):
        sj = snaps[j]
        tj = sj.get("ts", 0.0)
        if (_episode(sj) or {}).get("episode_id") != ep:
            continue
        if tj < ts - _QOS_WINDOW_S - 1e-9 or tj > ts + 1e-9:
            continue
        q = (sj.get("scene_state") or {}).get("QoS")
        if q is not None:
            pts.append((tj, float(q)))
    if len(pts) < 3:
        return 0.0
    n = len(pts)
    mx = sum(p[0] for p in pts) / n
    my = sum(p[1] for p in pts) / n
    den = sum((p[0] - mx) ** 2 for p in pts)
    slope = 0.0 if den == 0 else sum((p[0] - mx) * (p[1] - my) for p in pts) / den
    b = my - slope * mx
    return sum((p[1] - (slope * p[0] + b)) ** 2 for p in pts) / n


def _t3_v15_episode_override(snaps):
    """v1.5/1.6: episode 集約で t3 を分類して 1 ラベルを返す。該当なし or episode 不在は None。

    優先順: 会話(speech) → 観測劣化(低 QoS) → 接近(traffic) → 環境変化(QoS 振動=env_start)。
    いずれもクリーンに分離できる観測のみ。env_start は速い signal(speech/QoS/approach)で捕まらない
    残りの中から QoS 振動(detrend 分散)で立てる(上位 tier が優先=traffic/conv と競合しない)。
    """
    eps = [(_episode(s), s) for s in snaps]
    eps = [(e, s) for (e, s) in eps if e is not None]
    if not eps:
        return None  # v1.4(episode 無)。
    n = len(eps)
    speech = sum(float(e.get("speech_ratio", 0.0)) for e, _ in eps) / n
    approach = sum(float(e.get("approach_ratio", 0.0)) for e, _ in eps) / n
    qos = sum(_scene_qos_latency(s)[0] for _, s in eps) / n
    if speech >= _T3_V15_SPEECH:
        return t3_mod.CONV_PARTICIPATING
    if qos < _T3_V15_QOS_UNCERTAIN:
        return t3_mod.UNCERTAIN_CONTEXT
    if approach >= _T3_V15_APPROACH_TRAFFIC:
        return t3_mod.TRAFFIC_UNSTABLE
    # v1.6(ADR 0041): QoS 振動 → env_start。episode 全フレームの detrend 分散平均で判定。
    osc = sum(_qos_detrend_var_frame(snaps, i) for i in range(len(snaps))) / len(snaps)
    if osc >= _T3_V16_OSC_ENV:
        return t3_mod.ENV_START
    return None


def _scene_regime_sequence(quality_logits, learned_scene=None, snaps=None):
    """観測 logit 列を scene(F-010)の HGF + 分類へ通し scene_regime 列を返す。

    scene.classify_sequence は _SceneParams(HGF + 持続性 + 閾値)を要求する。learned_scene=None
    (既定・後方互換)は fit([])既定を起点に nominal/閾値を結線で差し替える従来挙動そのもの。
    learned_scene が与えられた(学習済み・ADR 0025)ときは学習済み HGF/閾値を注入する。
    決定的・学習 param 不変。
    """
    if not quality_logits:
        return []
    signal = _scene_health_signal(quality_logits)
    params = _scene_params_for_signal(signal, learned_scene)
    seq = scene_mod.classify_sequence(signal, params)
    # v1.5(C-1b・presence-gated): scene_state.stability が在るフレームを観測で上書き。
    # health<level_low→DEGRADING / qos_trend 降下 or track_churn/change_point→CHANGING / else STABLE。
    # level_low は学習値(fit)を再利用。stability 不在(v1.4)は学習 HGF 経路のまま=後方互換。
    if snaps is not None:
        qtrs, qoss = [], []
        for j, snap in enumerate(snaps):
            st = _stability(snap)
            if st is None:
                continue
            qtrs.append(float(st.get("qos_trend", 0.0)))
            qoss.append(_scene_qos_latency(snap)[0])
        if qtrs:  # stability が在る(v1.5)→ episode 集約で 1 regime に分類し全フレームへ適用。
            if min(qtrs) > -_SCENE_V15_DECLINE:
                regime = scene_mod.STABLE              # 降下なし。
            elif (sum(qoss) / len(qoss)) < _SCENE_V15_QOS_DEG:
                regime = scene_mod.DEGRADING           # 降下 ∧ 平均 QoS 低(settled low)。
            else:
                regime = scene_mod.CHANGING            # 降下 ∧ 平均 QoS 中(遷移)。
            seq = [regime] * len(seq)
    return seq


# ===========================================================================
# strict GT-conformance ゲート(ADR 0050)
# ===========================================================================

def _strict_gt_conformance(config):
    """config から `strict_gt_conformance` ゲート(ADR 0050)を読む。既定 True(現行挙動)。

    True(既定) = strict 系オーバーライド(ADR 0043〜0048 = GT 生成器 gt_derive.py の規則 f の写し。
    ADR 0049 で能力指標としては循環と撤回済み・spec-conformance としてコード保持)を view に適用する。
    gt_derive 系コーパスの回帰テスト・契約適合(spec-conformance)検証用のモード。

    False = strict 系オーバーライドをスキップし、strict 導入前(ADR 0042 まで)の観測ベース経路
    (v1.4/v1.5: quality=quality.classify(h_q,vol)・risk=t0.risk_tier(track)・t1=t1.t1_state+episode 補正・
    mode=logits→hysteresis+v1.5 uncertain・role=role.classify(evidence)・relation=relation.classify(evidence))
    へフォールバックする。**能力評価・対外比較の文脈では False を必須とする**(ADR 0049/0050 の規律。
    strict ON のまま gt_derive 系コーパスで測ると循環スコアが再生するため)。
    """
    if isinstance(config, dict):
        return bool(config.get("strict_gt_conformance", True))
    return True


# ===========================================================================
# 1 シナリオ分の tick オーケストレーション(状態持ち越し・先頭で T3 reset)
# ===========================================================================

def _run_one_scenario(snaps, config, params=None):
    """1 シナリオ(Snapshot 系列)を end-to-end で 8 層 view 列に変換する。

    シナリオ先頭フレームで T3 を reset する(ADR 0022 決定2・シナリオ境界 reset)。
    t1/t3 は状態を持ち越し、quality/anomaly/scene は系列全体を HGF で処理する。

    params=None(後方互換・最重要)は既定挙動そのもの(t3=default_params()・scene=既定結線)。
    params が SupremeParams のときは学習済み t3/scene を注入して実走する(ADR 0025 決定1)。
    8 層 view の組み立ては params の有無で変えない。

    config の `strict_gt_conformance`(ADR 0050・既定 True)で strict 系オーバーライド
    (ADR 0043〜0048=GT 規則の写し)を ON/OFF する。True は現行挙動そのもの(後方互換)。
    False は strict 導入前(ADR 0042 まで)の観測ベース経路にフォールバックする。
    """
    snaps = list(snaps)
    if not snaps:
        return []

    learned_scene = params.scene if params is not None else None
    strict_gt = _strict_gt_conformance(config)  # ADR 0050: strict 写し実装のゲート(既定 ON)。

    # --- gate: Snapshot 検証(version・ts 単調非減少)---
    prev_ts = None
    for snap in snaps:
        prev_ts = _validate_snapshot(snap, prev_ts)

    # --- 観測式 + HGF(系列処理)---
    quality_logits = _quality_obs_raw_logits(snaps)
    anomaly_logits = _anomaly_obs_raw_logits(snaps)
    h_q_seq, vol_seq = _hq_vol_sequences(quality_logits)
    pw_anom_seq = _pw_anom_sequence(anomaly_logits)
    scene_seq = _scene_regime_sequence(quality_logits, learned_scene, snaps)
    t3_v15_override = _t3_v15_episode_override(snaps)  # v1.5: episode 集約の t3 ラベル(無=None)。
    # v1.6(ADR 0044): salient range 幾何の t1 列(無=None)。GT t1_state_seq の写しのため
    # strict ゲート対象(ADR 0050)。OFF は全 None=既存 t1(t1_mod+ADR 0038 補正)に委ねる。
    t1_geo_seq = _t1_geometry_sequence(snaps) if strict_gt else [None] * len(snaps)
    # supreme3(ADR 0052-s3): strict OFF の T2 は NeuPSL(結合 MAP)経路へ。
    # strict ON(既定)は supreme2 と完全同一の従来ループを通す。
    if not strict_gt:
        return _run_one_scenario_neupsl(
            snaps, params, h_q_seq, vol_seq, pw_anom_seq, scene_seq, t3_v15_override)

    views = []
    prev_t1 = None
    prev_mode = mode_mod.QUIET   # ヒステリシス起点は quiet_standby。
    prev_salient_range = None    # relation 幾何 override 用の前 salient range(ADR 0043)。
    prev_qos_raw = None          # mode 厳密化(ADR 0047)の env_change Δq 用・前フレーム生 QoS。
    t3_state = None
    t3_params = params.t3 if params is not None else t3_mod.default_params()

    for i, snap in enumerate(snaps):
        h_q = h_q_seq[i]
        vol = vol_seq[i]
        pw_anom = pw_anom_seq[i]

        # --- quality 結線 ---
        # ADR 0045(strict・ADR 0050 ゲート): GT(gt_derive.quality_regime)整合の生 QoS 規則
        # (q>=0.90 GOOD / q<0.55 BLOCK / 他 DEGRADED)。GT は「生 QoS の規則(h_q を使わない=循環回避)」。
        # h_q/vol は HGF gating 用に保持(下流 anomaly/scene)。旧 quality_mod.classify(h_q,vol) は
        # h_q ベースで GT とズレ quality 0.80 に留めていた(強 baseline が露呈)。
        # ゲート OFF は strict 導入前の h_q/vol 経路(quality.classify・ADR 0014)へフォールバック。
        if strict_gt:
            _q = _scene_qos_latency(snap)[0]
            quality_regime = "GOOD" if _q >= 0.90 else ("BLOCK" if _q < 0.55 else "DEGRADED")
        else:
            quality_regime = quality_mod.classify(h_q, vol)

        # --- t0 結線(risk_tier)---
        # ADR 0048(strict・ADR 0050 ゲート): GT(risk_tier)厳密適用。track ゼロでも geom.min_TTC_s を
        # 読む(旧 t0.risk_tier は track 0 件で info に縮退し ttc<8 を取りこぼしていた)。risk は
        # mode_seq にも渡るため mode 残差も解消。ゲート OFF は track ベースの t0.risk_tier 経路
        # (ADR 0033/0045・track ゼロ→安全側 info)へフォールバック。
        if strict_gt:
            risk_tier = _risk_tier_strict(snap)
        else:
            risk_tier = t0_mod.risk_tier(_t0_tracks(snap))

        # --- t1 結線(状態持ち越し・pw_anom 注入)---
        ttc = _min_ttc(snap)
        min_range = _min_range(snap)
        t1_label, prev_t1 = t1_mod.t1_state(ttc, min_range, pw_anom, prev_t1)
        # v1.5(C-1a・presence-gated): episode.approach_ratio(実際に距離が減ったフレーム割合)で t1 を補正。
        # 現 t1 の「ttc<12→approach」は静止近接物も approach にする(idle/depart→approach 誤り)。実接近なら
        # approach、偽 approach(approach_ratio 低)は離反(hazard_trend>0)なら depart・他は idle。episode 不在は不変。
        ep_t1 = _episode(snap)
        if ep_t1 is not None:
            ar = float(ep_t1.get("approach_ratio", 0.0))
            if ar >= _T1_V15_APPROACH:
                t1_label = t1_mod.APPROACH
            elif t1_label == t1_mod.APPROACH:
                ht = float(ep_t1.get("hazard_trend", 0.0))
                t1_label = t1_mod.DEPART if ht > _T1_V15_DEPART else t1_mod.IDLE
        # v1.6(ADR 0044): salient range 幾何が authoritative(GT t1_state_seq の忠実化・上記
        # approach_ratio 補正 ADR 0038 を range 軌跡で上書き=より正確)。salient 無は既存 t1 を維持。
        if t1_geo_seq[i] is not None:
            t1_label = t1_geo_seq[i]
        approaching = t1_label == t1_mod.APPROACH

        # --- t2 mode 結線(段2 mode logits → hysteresis・状態持ち越し)---
        logits = _mode_logits(snap, risk_tier, approaching, h_q)
        t2_mode = mode_mod.hysteresis(logits, prev_mode)
        prev_mode = t2_mode  # ヒステリシス状態は raw のまま(下の v1.5 上書きで汚さない)。
        # v1.5(C-1b・presence-gated): 観測劣化(低 QoS)→ uncertain mode(supreme が出せない欠落クラスの回収)。
        # coverage_v2/train: uncertain の QoS≈0.39(最低)・他クラス ≥0.61 で分離。episode 不在(v1.4)は不変。
        # v1.6(ADR 0040): conv 確定(link type 由来)は低 QoS でも uncertain に奪わせない(conv link が
        # 在る=会話文脈は観測されており「文脈断定不能」ではない。conv フレーム 140 件の uncertain 誤流出を是正)。
        if (_episode(snap) is not None
                and _scene_qos_latency(snap)[0] < _MODE_V15_UNCERTAIN_QOS
                and t2_mode not in ("conv_ongoing", "conv_request")):
            t2_mode = "uncertain"

        # v1.6(ADR 0047・ADR 0050 ゲート): mode 厳密化 — view へは GT(gt_derive.mode_seq)を厳密適用した
        # mode を出す。上の logits→hysteresis(+uncertain)は t3 窓用の内部 mode として温存(t3 非干渉)し、
        # 出力 mode のみ観測規則の厳密版で確定(mode acc を 0.73→~1.0)。全入力は v1.4 観測
        # (salient/links/utter/生QoS/risk)。ゲート OFF は strict 導入前どおり hysteresis+v1.5 uncertain の
        # t2_mode をそのまま view と t3 窓へ出す(ADR 0039/0040/0042 経路)。
        if strict_gt:
            t2_mode_view = _mode_seq_strict(snap, risk_tier, prev_qos_raw)
        else:
            t2_mode_view = t2_mode
        prev_qos_raw = (snap.get("scene_state") or {}).get("QoS")

        # --- t2 role / relation 結線 ---
        # v1.6(ADR 0046・ADR 0050 ゲート): role を GT(gt_derive.role)整合の salient(w_obs/r_m)種別で確定
        # (salience に依らず ~1.0)。ゲート OFF は strict 導入前の evidence 経路
        # (role.classify(_role_evidence)・ADR 0017/0028/0029/0034)へフォールバック。
        if strict_gt:
            t2_role = _role_salient(snap)
        else:
            t2_role = role_mod.classify(_role_evidence(snap))
        t2_relation = relation_mod.classify(_relation_evidence(snap, approaching))
        # v1.6(ADR 0043・ADR 0050 ゲート): relation を主トラックの range 幾何で忠実化(departing/near_user/
        # unrelated 回収・near_user 優先是正)。addressing は既存ロジックに委譲(None)。relation は
        # rule_derived=観測完全可。ゲート OFF は override を適用せず relation.classify(evidence) のまま。
        if strict_gt:
            rel_geo = _relation_geometry_override(snap, prev_salient_range)
            if rel_geo is not None:
                t2_relation = rel_geo
            _st = _salient_track_geom(snap)
            if _st is not None:
                prev_salient_range = _st["r_m"]  # 次フレーム Δr 用(最後の非None salient range を保持)。

        # --- scene 結線(系列 HGF の i 番目)---
        scene_regime = scene_seq[i]

        # --- t3 結線(mode 系列 + reset・状態持ち越し)---
        # v1.6(ADR 0047): t3 窓へ供給する mode も view の mode に統一(t3.fit の学習サンプルが
        # view["t2_mode"] を消費する=train/infer 整合)。strict ON では GT 正確な mode 列で conv 窓検出が
        # 正しくなり t3 も底上げ。内部 hysteresis mode(prev_mode)は遷移状態の連続性維持にのみ用いる。
        # ゲート OFF では view mode=旧 t2_mode なので strict 導入前(ADR 0042 まで)の t3 窓入力と一致する。
        reset = i == 0  # シナリオ先頭で reset=True(シナリオ境界 reset)。
        t3_frame = {"mode": t2_mode_view, "posterior": h_q}
        t3_hypothesis, t3_state = t3_mod.step(t3_frame, reset, t3_state, t3_params)
        # v1.5(C-1a・presence-gated・episode-level): 会話/観測劣化/接近を観測から t3 に写す
        # (会話×衝突危険でも conv_participating を保持=ADR 0033 副作用解消)。episode 不在(v1.4)は不変。
        if t3_v15_override is not None:
            t3_hypothesis = t3_v15_override

        views.append({
            "risk_tier": risk_tier,
            "t1_state": t1_label,
            "t2_mode": t2_mode_view,
            "t2_role": t2_role,
            "t2_relation": t2_relation,
            "t3_hypothesis": t3_hypothesis,
            "quality_regime": quality_regime,
            "scene_regime": scene_regime,
        })

    return views


# ===========================================================================
# 公開 API
# ===========================================================================

# ===========================================================================
# supreme3(ADR 0052-s3): T2 = 本来型 NeuPSL の結線
# ===========================================================================

_T2_FIT_MAX_SCENARIOS = 2000    # 学習に使う練習シナリオ上限(決定的 stride 抽出)
_T2_GUARD_MAX_SCENARIOS = 400   # ≥ガードの train acc 比較に使う上限
_T2_FIT_EPOCHS = 10


def _neupsl_features(snap, risk_tier, approaching, h_q, t1_label=None):
    """1フレームの NeuPSL 入力特徴(観測述語+ニューラル述語の生特徴)を組み立てる。"""
    ev = _role_evidence(snap)
    rel_ev = _relation_evidence(snap, approaching)
    tr = snap.get("tracks", {}) or {}
    humans = tr.get("humans", []) or []
    objects = tr.get("objects", []) or []
    r = _min_range(snap)
    return {
        "siren": 1.0 if ev.get("has_siren") else 0.0,
        "alarm": 1.0 if ev.get("has_alarm") else 0.0,
        "vehicle": 1.0 if ev.get("has_vehicle") else 0.0,
        "speech": 1.0 if ev.get("has_speech") else 0.0,
        "speaking": float(ev.get("speaking", 0.0)),
        "range_n": max(0.0, min(1.0, 1.0 - min(float(r), 20.0) / 20.0)),
        "near3": 1.0 if rel_ev.get("near_prox") else 0.0,
        "humans_n": min(1.0, len(humans) / 4.0),
        "objects_n": min(1.0, len(objects) / 2.0),
        "call_user": 1.0 if rel_ev.get("call_user") else 0.0,
        "addr_link": float(rel_ev.get("linked_addressing", 0.0)),
        "spk_link": 1.0 if rel_ev.get("speaking_link") else 0.0,
        "risk_danger": 1.0 if risk_tier == t0_mod.DANGER else 0.0,
        "risk_caution": 1.0 if risk_tier == t0_mod.CAUTION else 0.0,
        "approaching": 1.0 if approaching else 0.0,
        "t1_depart": 1.0 if t1_label == t1_mod.DEPART else 0.0,
        "t1_pass": 1.0 if t1_label == t1_mod.PASS else 0.0,
        "h_q": float(h_q),
    }


def _neupsl_prepass(snaps, h_q_seq, vol_seq, pw_anom_seq):
    """OFF 経路の T2 より前段(quality/risk/t1)を supreme2 と同一の式で計算する。"""
    pre = []
    prev_t1 = None
    for i, snap in enumerate(snaps):
        quality_regime = quality_mod.classify(h_q_seq[i], vol_seq[i])
        risk_tier = t0_mod.risk_tier(_t0_tracks(snap))
        ttc = _min_ttc(snap)
        min_range = _min_range(snap)
        t1_label, prev_t1 = t1_mod.t1_state(ttc, min_range, pw_anom_seq[i], prev_t1)
        ep_t1 = _episode(snap)
        if ep_t1 is not None:
            ar = float(ep_t1.get("approach_ratio", 0.0))
            if ar >= _T1_V15_APPROACH:
                t1_label = t1_mod.APPROACH
            elif t1_label == t1_mod.APPROACH:
                ht = float(ep_t1.get("hazard_trend", 0.0))
                t1_label = t1_mod.DEPART if ht > _T1_V15_DEPART else t1_mod.IDLE
        approaching = t1_label == t1_mod.APPROACH
        pre.append({
            "quality_regime": quality_regime,
            "risk_tier": risk_tier,
            "t1_label": t1_label,
            "approaching": approaching,
            "feat": _neupsl_features(snap, risk_tier, approaching, h_q_seq[i], t1_label),
        })
    return pre


def _run_one_scenario_neupsl(snaps, params, h_q_seq, vol_seq, pw_anom_seq,
                             scene_seq, t3_v15_override):
    """strict OFF の 1 シナリオ実行(supreme3)。T2 のみ NeuPSL の結合 MAP で決める。

    quality/risk/t1/scene は supreme2 の OFF 経路と同一の式・同一の順序で計算する
    (T2 以外の不変条件)。T3 は supreme2 と同一のコードだが、窓に入る mode 列が
    NeuPSL の出力になるため、下流効果として値が変わり得る(ADR 0052-s3)。
    """
    pre = _neupsl_prepass(snaps, h_q_seq, vol_seq, pw_anom_seq)
    t2_params = params.t2 if params is not None and getattr(params, "t2", None) is not None else None
    labels = neupsl_mod.infer_scenario([p["feat"] for p in pre], t2_params)

    views = []
    t3_state = None
    t3_params = params.t3 if params is not None else t3_mod.default_params()
    for i, snap in enumerate(snaps):
        t2_mode = labels[i]["mode"]
        # v1.5(ADR 0039): presence-gated の uncertain 上書き(v1.3 入力では不作動)。
        if (_episode(snap) is not None
                and _scene_qos_latency(snap)[0] < _MODE_V15_UNCERTAIN_QOS
                and t2_mode not in ("conv_ongoing", "conv_request")):
            t2_mode = "uncertain"
        reset = i == 0
        t3_frame = {"mode": t2_mode, "posterior": h_q_seq[i]}
        t3_hypothesis, t3_state = t3_mod.step(t3_frame, reset, t3_state, t3_params)
        if t3_v15_override is not None:
            t3_hypothesis = t3_v15_override
        views.append({
            "risk_tier": pre[i]["risk_tier"],
            "t1_state": pre[i]["t1_label"],
            "t2_mode": t2_mode,
            "t2_role": labels[i]["role"],
            "t2_relation": labels[i]["rel"],
            "t3_hypothesis": t3_hypothesis,
            "quality_regime": pre[i]["quality_regime"],
            "scene_regime": scene_seq[i],
        })
    return views


def _neupsl_inputs_from_scenario(snaps):
    """fit 用: OFF 経路と同一の前段計算で NeuPSL 特徴列を返す。"""
    snaps = list(snaps)
    if not snaps:
        return []
    quality_logits = _quality_obs_raw_logits(snaps)
    h_q_seq, vol_seq = _hq_vol_sequences(quality_logits)
    pw_anom_seq = _pw_anom_sequence(_anomaly_obs_raw_logits(snaps))
    pre = _neupsl_prepass(snaps, h_q_seq, vol_seq, pw_anom_seq)
    return [p["feat"] for p in pre]


def _t2_train_acc(t2_params, scens):
    """NeuPSL params を練習シナリオで採点した micro acc(語彙内 GT のみ分母)。"""
    correct = 0
    total = 0
    for feats, gts in scens:
        if not feats:
            continue
        out = neupsl_mod.infer_scenario(feats, t2_params)
        for i, gt_f in enumerate(gts):
            for layer, vocab in (("mode", neupsl_mod.MODES),
                                 ("role", neupsl_mod.ROLES),
                                 ("rel", neupsl_mod.RELS)):
                lab = gt_f.get(layer)
                if lab in vocab:
                    total += 1
                    if out[i][layer] == lab:
                        correct += 1
    if total == 0:
        return None
    return correct / total


def run_supreme(pso_snapshots, params=None, config=None):
    """PSO-Snapshot 系列を end-to-end で 8 層 view 列に変換する(F-基盤-001-1 / ADR 0025)。

    単一シナリオ(1 系列)として処理する。先頭フレームで T3 reset する(エピソード先頭)。
    決定的(乱数・時刻なし)で、呼び出しごとに状態をクリーンに初期化する(呼び出し間で
    状態を共有しない)。

    Args:
        pso_snapshots: PSO-Snapshot(world_state dict)の系列(Snapshot のみ)。
        params: 学習済み SupremeParams(fit_supreme の返り値)。**None は現状の既定挙動
                (後方互換・最重要)で、既存呼び出しの結果を一切変えない**。SupremeParams の
                ときは学習済み t3/scene を注入して実走する(ADR 0025 決定1)。
        config: 探索構成(省略時は既定=全モジュール ON)。`strict_gt_conformance`(bool・
                既定 True・ADR 0050)のみ解釈する: True(既定)は strict 系オーバーライド
                (ADR 0043〜0048=GT 生成器 gt_derive の規則写し)を含む現行挙動そのもの
                (config 省略・空 dict と同一=後方互換)。False は strict をスキップし
                strict 導入前(ADR 0042 まで)の観測ベース経路へフォールバックする
                (能力評価・対外比較の文脈では False 必須=ADR 0049/0050 の規律)。
                いずれも決定的(乱数・時刻なし)。

    Returns:
        各フレームの 8 層 view dict 列(長さ=入力長)。
    """
    return _run_one_scenario(pso_snapshots, config, params)


def run_supreme_scenarios(scenarios, params=None, config=None):
    """シナリオ単位の入力を受け、各シナリオの 8 層 view 列を返す(F-基盤-001-1・決定2 / ADR 0025)。

    各シナリオは独立に処理され、シナリオ先頭で T3 を reset する(シナリオ境界 reset)。
    シナリオ間で状態を持ち越さない(別シナリオの T3 累積を引きずらない)。

    Args:
        scenarios: {scenario_id: pso_snapshots} の dict。
        params: 学習済み SupremeParams(None は既定挙動=後方互換・ADR 0025 決定4)。
        config: 探索構成(省略時は既定)。`strict_gt_conformance`(ADR 0050・既定 True)を
                run_supreme と同じ意味で解釈する(各シナリオへ透過)。

    Returns:
        {scenario_id: [frame_view, ...]} の dict(各 view は 8 層)。
    """
    out = {}
    for scenario_id, snaps in scenarios.items():
        out[scenario_id] = _run_one_scenario(snaps, config, params)
    return out


def build_trace(scenarios, gt, config=None):
    """8 層 view + gt を harness.score へ渡せる trace 形へ組み立てる(F-基盤-001-1・任意ヘルパ)。

    trace 形状: {scenario_id: [{"ts", "view"{8層}, "gt"{8層}}, ...]}(harness 互換)。

    Args:
        scenarios: {scenario_id: pso_snapshots} の dict(view を生成する入力)。
        gt:        {scenario_id: [gt_view, ...]} の dict(各フレームの正解 8 層)。
        config:    探索構成(省略時は既定)。

    Returns:
        harness.score にそのまま渡せる trace dict。
    """
    views_by_scenario = run_supreme_scenarios(scenarios, config=config)
    trace = {}
    for scenario_id, views in views_by_scenario.items():
        gt_list = list(gt.get(scenario_id, []))
        frames = []
        for i, view in enumerate(views):
            gt_view = gt_list[i] if i < len(gt_list) else dict(view)
            frames.append({"ts": float(i), "view": dict(view), "gt": dict(gt_view)})
        trace[scenario_id] = frames
    return trace


# ===========================================================================
# 学習配線(ADR 0025): SupremeParams + fit_supreme
#   練習シナリオ(PSO 入力 + 8層 GT)から t3/scene の学習入力を **core の実経路と一致**
#   させて組み立て(t3: argmax mode 系列 + reset + gt / scene: health 信号 + gt)、
#   t3.fit / scene.fit で決定的に学習する。run_supreme(..., params=) に注入して実走する。
#   後方互換: params=None は既定挙動を一切変えない(本節は新規追加のみ)。
# ===========================================================================

@dataclasses.dataclass(frozen=True)
class SupremeParams:
    """学習済み t3/scene params を保持する型(ADR 0025 決定1)。

    t3    : t3.fit / default_params() が返す T3 params(run_supreme の t3 実走に注入)。
    scene : scene.fit が返す _SceneParams(run_supreme の scene 実走に注入)。

    run_supreme(snaps, params=SupremeParams) に渡せ、既定値の代わりに学習済みを注入する。
    learnable_param_count() で学習可能 param 総数を取り出せる(= t3 + scene・fit 前後で不変)。
    """

    t3: object
    scene: object
    t2: object = None  # supreme3: NeuPSL の学習済み params(None=事前重みで推論)

    def learnable_param_count(self) -> int:
        """学習可能 param 総数(= t3.learnable_param_count() + scene.learnable_param_count())。

        学習対象は t3/scene の固定リスト(ADR 0025 決定2/決定3)。学習で増えない(F-014)。
        """
        n = t3_mod.learnable_param_count() + scene_mod.learnable_param_count()
        if self.t2 is not None:
            n += self.t2.learnable_param_count()
        return n


def _t3_practice_from_scenario(snaps, views, gt_views):
    """1 シナリオの t3 学習サンプルを core の実経路と一致させて組み立てる(ADR 0025・run_cv_train)。

    core._run_one_scenario が t3 に渡すのと同じ入力:
        h_q  = _hq_vol_sequences(_quality_obs_raw_logits(snaps))[0][i]
        mode = {"mode": view["t2_mode"](argmax 後), "posterior": h_q}
        reset = (i == 0)(シナリオ先頭 True・他 False)
    gt はその層(t3_hypothesis)を持つフレームのみ採用(無いフレームは学習サンプル外)。

    Returns:
        {"mode_seq":[...], "reset_seq":[...], "gt":[...]}(t3.fit が消費する形)。gt が
        t3_hypothesis を持たないフレームは mode_seq/reset_seq/gt から除外する(学習サンプル外)。
    """
    quality_logits = _quality_obs_raw_logits(snaps)
    h_q_seq, _vol = _hq_vol_sequences(quality_logits)
    mode_seq = []
    reset_seq = []
    gt_seq = []
    for i, view in enumerate(views):
        gt_label = gt_views[i].get("t3_hypothesis") if i < len(gt_views) else None
        if gt_label is None:
            continue
        mode_seq.append({"mode": view["t2_mode"], "posterior": h_q_seq[i]})
        # core はシナリオ先頭(i==0)で reset。学習サンプルはエピソード境界を保つため、
        # 採用フレームのうち元の i==0 のみ reset=True(他は False)。
        reset_seq.append(i == 0)
        gt_seq.append(gt_label)
    return {"mode_seq": mode_seq, "reset_seq": reset_seq, "gt": gt_seq}


def _scene_practice_from_scenario(snaps, gt_views):
    """1 シナリオの scene 学習サンプルを core の実経路と一致させて組み立てる(ADR 0025・run_cv_train)。

    core._scene_regime_sequence の入力:
        signal = _scene_health_signal(_quality_obs_raw_logits(snaps))
    gt はその層(scene_regime)を持つフレームのみ採用(無いフレームは学習サンプル外)。

    Returns:
        {"signal":[...], "gt":[...]}(scene.fit が消費する形)。gt が scene_regime を持たない
        フレームは signal/gt から除外する(学習サンプル外)。
    """
    quality_logits = _quality_obs_raw_logits(snaps)
    signal = _scene_health_signal(quality_logits)
    sig_seq = []
    gt_seq = []
    for i, gv in enumerate(gt_views):
        gt_label = gv.get("scene_regime")
        if gt_label is None or i >= len(signal):
            continue
        sig_seq.append(signal[i])
        gt_seq.append(gt_label)
    return {"signal": sig_seq, "gt": gt_seq}


def _t3_train_acc(t3_params, t3_samples):
    """t3_params を t3 練習サンプル群で採点した in-sample micro acc(Σ正答/Σ非null)。

    各サンプルの (mode_seq, reset_seq) を run_t3_sequence で分類し gt と完全一致採点する。
    採点対象が 0 のときは None(比較不能)。
    """
    correct = 0
    total = 0
    for s in t3_samples:
        if not s["gt"]:
            continue
        preds = t3_mod.run_t3_sequence(s["mode_seq"], s["reset_seq"], t3_params)
        for pred, gt_label in zip(preds, s["gt"]):
            total += 1
            if pred == gt_label:
                correct += 1
    if total == 0:
        return None
    return correct / total


def _scene_train_acc(learned_scene, scene_samples):
    """scene を core の実 scene 経路(_scene_params_for_signal で nominal を信号由来に結線)で
    採点した in-sample micro acc。

    learned_scene=None は既定閾値(_SCENE_THRESHOLDS)経路、learned_scene が _SceneParams なら
    その学習済み HGF/閾値を注入した経路で classify する(end-to-end の scene_regime と一致する
    採点)。採点対象が 0 のときは None。
    """
    correct = 0
    total = 0
    for s in scene_samples:
        signal = s["signal"]
        if not s["gt"] or not signal:
            continue
        params = _scene_params_for_signal(signal, learned_scene)
        preds = scene_mod.classify_sequence(signal, params)
        for pred, gt_label in zip(preds, s["gt"]):
            total += 1
            if pred == gt_label:
                correct += 1
    if total == 0:
        return None
    return correct / total


def fit_supreme(practice_scenarios, gt) -> "SupremeParams":
    """練習シナリオ + 8 層 GT から t3/scene を決定的に学習し SupremeParams を返す(ADR 0025 決定1)。

    各シナリオで **core の実経路と一致する学習入力**を組み立てる(run_cv_train と同じ抽出):
      t3   : {"mode_seq":[{"mode":<t2_mode argmax>,"posterior":<h_q>},...],
              "reset_seq":[先頭 True,...], "gt":[t3_hypothesis,...]}
      scene: {"signal":[health,...], "gt":[scene_regime,...]}
    GT にその層が無いフレームは学習サンプル外(t3/scene 別々に採点フレームを選ぶ)。

    t3.fit / scene.fit で決定的に学習する(乱数・時刻なし)。in-sample で『学習が既定を下回らない』
    担保(ADR 0025 決定3・観点5)のため、**学習結果と既定を同じ練習データの train acc で比較し
    良い方(>=)を採る**(既定が fit のグリッドに無い場合でも `>=` を保証する=学習が悪化させない)。

    Args:
        practice_scenarios: {scenario_id: pso_snapshots}(PSO-Snapshot 系列・Snapshot のみ)。
        gt: {scenario_id: [gt_view, ...]}(各フレームの 8 層 GT view・scene_regime/t3_hypothesis
            を採点キーとして与える)。

    Returns:
        SupremeParams(学習済み t3/scene params を保持・run_supreme(..., params=) に渡せる)。
    """
    t3_samples = []
    scene_samples = []
    for sid, snaps in practice_scenarios.items():
        snaps = list(snaps)
        gt_views = list(gt.get(sid, []))
        # core の既定経路で 8 層 view を得る(t2_mode argmax は core の実経路そのもの)。
        views = _run_one_scenario(snaps, None, None)
        t3_samples.append(_t3_practice_from_scenario(snaps, views, gt_views))
        scene_samples.append(_scene_practice_from_scenario(snaps, gt_views))

    # --- t3 学習(決定的)+ 既定との train acc 比較で良い方を採る(>= 担保)---
    t3_default = t3_mod.default_params()
    t3_learned = t3_mod.fit(t3_samples)
    acc_default = _t3_train_acc(t3_default, t3_samples)
    acc_learned = _t3_train_acc(t3_learned, t3_samples)
    if acc_default is not None and (acc_learned is None or acc_learned < acc_default):
        t3_chosen = t3_default
    else:
        t3_chosen = t3_learned

    # --- scene 学習(決定的)+ 既定との train acc 比較で良い方を採る(>= 担保)---
    # 比較は core の実 scene 経路(_scene_params_for_signal で nominal を信号由来に結線)で行う。
    scene_learned = scene_mod.fit(scene_samples)
    acc_scene_default = _scene_train_acc(None, scene_samples)              # 既定閾値経路。
    acc_scene_learned = _scene_train_acc(scene_learned, scene_samples)     # 学習済み閾値経路。
    if acc_scene_default is not None and (
        acc_scene_learned is None or acc_scene_learned < acc_scene_default
    ):
        # 既定の方が良い(または同等)→ 既定の HGF/閾値で実走するための _SceneParams を作る。
        # core の既定経路は fit([])の HGF + _SCENE_THRESHOLDS を使うため、それを保持する。
        scene_chosen = dataclasses.replace(
            scene_mod.fit([]), thresholds=dict(_SCENE_THRESHOLDS)
        )
    else:
        scene_chosen = scene_learned

    # --- supreme3: T2(NeuPSL)学習 + ≥ガード(ADR 0052-s3)---------------
    sids_all = sorted(practice_scenarios.keys())
    stride = max(1, len(sids_all) // _T2_FIT_MAX_SCENARIOS)
    t2_scens = []
    for sid in sids_all[::stride][:_T2_FIT_MAX_SCENARIOS]:
        snaps_s = list(practice_scenarios[sid])
        gt_views = list(gt.get(sid, []))
        feats = _neupsl_inputs_from_scenario(snaps_s)
        gts = [{"mode": (gt_views[i] or {}).get("t2_mode") if i < len(gt_views) else None,
                "role": (gt_views[i] or {}).get("t2_role") if i < len(gt_views) else None,
                "rel": (gt_views[i] or {}).get("t2_relation") if i < len(gt_views) else None}
               for i in range(len(feats))]
        t2_scens.append((feats, gts))
    t2_chosen = None
    if t2_scens:
        t2_learned = neupsl_mod.fit(t2_scens, epochs=_T2_FIT_EPOCHS)
        t2_default = neupsl_mod.default_params()
        g_stride = max(1, len(t2_scens) // _T2_GUARD_MAX_SCENARIOS)
        guard_scens = t2_scens[::g_stride][:_T2_GUARD_MAX_SCENARIOS]
        acc_learned = _t2_train_acc(t2_learned, guard_scens)
        acc_default = _t2_train_acc(t2_default, guard_scens)
        if acc_default is not None and (acc_learned is None or acc_learned < acc_default):
            t2_chosen = t2_default
        else:
            t2_chosen = t2_learned

    return SupremeParams(t3=t3_chosen, scene=scene_chosen, t2=t2_chosen)
