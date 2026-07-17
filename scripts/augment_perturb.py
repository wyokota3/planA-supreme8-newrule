"""保守的 label-preserving 摂動 generator(F-003 増強の実 generator・分析専用)。

F-003 `src/supreme/augment.py` の `Augmentor` は規律フレームワークで、内容生成は注入
generator に委譲する(実 generator は無い)。本モジュールは **決定的・乱数なし** の
label-preserving 摂動 generator を提供する。core/モジュール/テストは一切変更しない
(supreme.* の公開 API + core 内部関数の import 再利用のみ・baseline は import しない)。

=== 摂動設計(per-layer ラベル保存の根拠)===

supreme の全 8 層ラベルは、PSO-Snapshot の **少数フィールド** から決定的に導かれる
(core.py の証拠抽出を精読して同定):

  (Q) 観測品質チャネル — `scene_state.QoS` と `scene_state.latency_ms` のみ:
        quality_logit = -2 + 5·QoS - 4·(latency/200) - 2.5·(1-id_const) + 1.5·w_obs
        (id_const=1.0・w_obs=0.5 は定数 ⇒ QoS/latency 以外は寄与しない)
      この logit が HGF を通り
        - h_q = sigmoid(μ1)        → quality_regime の閾値(0.25/0.40/0.55/0.93)
                                    → t3 の posterior(集約特徴)
                                    → mode の env_change ゲート(h_q<0.5)
        - var1(vol)                → quality の vol ゲート(<0.01 / >0.05)
        - health=sigmoid(logit)    → scene_regime(HGF level/vol + 持続逸脱の閾値)
      を駆動する。**QoS/latency を「同じ logit 帯の内側」で微小に揺らせば、これら全層の
      argmax/regime は変わらない**(後述の検証で実測担保)。

  (R) range/ttc/speaking/humans チャネル — mode argmax(env_change 以外)・t0/t1/role/relation:
        conv_strong = has_speech ∧ speaking>0.7 ∧ min_range<5.0
        surround    = humans≥3
        approaching = t1(ttc, min_range, pw_anom, prev)
        risk_tier   = t0(kind, ttc, r_m)
      これらは **非線形な閾値・カテゴリ判定** で、微小スケールでも境界を跨ぐと argmax が変わる。
      ⇒ **保守側に倒し、本 generator は R チャネル(r_m / TTC / speaking_prob / humans 構成)を
      一切触らない**。触らなければ mode argmax・t0・t1・role・relation の入力は親と完全同一で、
      その層のラベルは原理的に保たれる(摂動していないため)。

  結論(摂動範囲):**QoS と latency_ms のみ**を、各フレームで同一 logit 帯の内側に留まる
  微小スケールで揺らす。logit が動いても各層の閾値帯を跨がない子のみを採用する。

=== ラベル保存の「設計上の根拠」と「実測検証」の二段 ===

  設計上の根拠(per-layer):
    - quality_regime: h_q/vol は logit の単調関数。子の logit を親 logit と同じ
      「最近接閾値までのマージン」の内側に収める(後述 _safe_logit_scale)。
    - scene_regime  : health 信号(=sigmoid(logit))が動くが、HGF/持続性は系列依存で
      非自明 ⇒ **設計だけでは保証しない**。下記「実測検証」で担保する。
    - t3_hypothesis : mode argmax 列(R チャネル=不変)+ posterior(h_q・logit 由来)。
      posterior の微小変化が集約特徴の符号を変えうる ⇒ 同じく実測検証で担保。
    - mode argmax   : env_change ゲート(h_q<0.5)以外は R チャネル(不変)。
      env_change ゲートは h_q が 0.5 を跨がない子のみ採用(実測検証で担保)。
    - risk_tier/t1/role/relation: R チャネル不変 ⇒ 原理的に不変(摂動していない)。

  実測検証(最重要・捏造防止):
    生成した各子を **core.run_supreme(child_snaps) に流し、得た 8 層 view 列が
    親の 8 層 view 列と完全一致するか** を確認する。一致しない子は「ラベルが壊れた」
    として **採用しない**(verify_child_preserves_labels)。一致した子のみ、親の正準化済み
    GT を継承して train に入れる(摂動でラベルが変わらない設計だから継承可)。
    ⇒ 「ラベル保存が担保できない子は使わない」=無効データで水増ししない。

決定的・乱数なし: 摂動は子インデックス i に対する固定の決定的スケール係数で与える
(`_deterministic_scales`)。同じ親・同じ i・同じ m で 2 回生成すると bit 一致する。
"""

from __future__ import annotations

import copy
import math
import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_SRC_DIR = os.path.join(os.path.dirname(_SCRIPT_DIR), "src")
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

# supreme 公開 API + core 内部関数のみ(baseline は import しない=独立性)。
from supreme import core


# ---------------------------------------------------------------------------
# 摂動の決定的スケール係数(乱数なし)
#
# 子インデックス i に対し、QoS と latency を別々の微小スケールで揺らす。係数は固定の
# 決定的テーブル。m(親あたり子数)が増えるほど 0 から外側へ少しずつ広げる(多様性の
# 名目を出すためでなく、「同じ logit 帯の内側でどこまで動かせるか」を効果曲線で見るため)。
# すべて ±数% 以内に収め、_safe_logit_scale でさらに帯内へクリップする。
# ---------------------------------------------------------------------------

# i 番目の子に与える (QoS 相対変化, latency 相対変化)。決定的・対称(正負交互)。
# 値は小さく取る(±1%, ±2%, ±3% を交互に QoS/latency へ)。
_PERTURB_TABLE = (
    (+0.010, -0.010),   # i=0: QoS を +1%, latency を -1%(品質をわずかに上げる方向)
    (-0.010, +0.010),   # i=1: QoS を -1%, latency を +1%(わずかに下げる方向)
    (+0.020, +0.000),   # i=2: QoS のみ +2%
    (+0.000, -0.020),   # i=3: latency のみ -2%
    (-0.020, +0.000),   # i=4: QoS のみ -2%
    (+0.000, +0.020),   # i=5: latency のみ +2%
    (+0.030, -0.010),   # i=6
    (-0.030, +0.010),   # i=7
)


def _deterministic_scales(index):
    """子インデックス index に対する (qos_rel, latency_rel) を決定的に返す(乱数なし)。

    テーブルを超える index はテーブルを周回し、周回数に応じて微増させる(決定的)。
    """
    base = _PERTURB_TABLE[index % len(_PERTURB_TABLE)]
    lap = index // len(_PERTURB_TABLE)
    # 周回ごとに 0.5% だけ外側へ(符号を保って絶対値を増やす)。決定的。
    grow = 1.0 + 0.5 * lap
    return base[0] * grow, base[1] * grow


# ---------------------------------------------------------------------------
# 観測 logit を「同じ閾値帯の内側」に保つための安全クリップ
#
# quality の h_q/vol 閾値は logit の単調関数(h_q=sigmoid(μ1)・μ1 は logit に追従)。
# 子フレームの logit を、親 logit から「最近接の quality 閾値 logit までのマージンの
# 半分」を超えないようにクリップする(帯の内側に確実に留める保守化)。
# scene/t3/mode の閾値は系列依存で logit との単調対応が自明でないため、ここでは
# quality 帯を保つクリップに留め、最終判断は実測検証(全層 view 一致)に委ねる。
# ---------------------------------------------------------------------------

# h_q の閾値(quality.classify の境界)。h_q = sigmoid(μ1) で μ1 ≈ logit 追従。
# 観測 logit から h_q への写像は HGF を通るので厳密な逆写像はしないが、保守化のため
# 「観測 logit を親から大きく動かさない」だけで十分(微小スケール前提)。
def _quality_logit(qos, latency):
    """core._quality_obs_raw_logits と同一式で 1 フレームの観測 logit を計算する。"""
    return (
        core._OBS_BIAS
        + core._OBS_QOS * qos
        + core._OBS_LATENCY * (latency / core._LATENCY_SCALE)
        + core._OBS_ID * (1.0 - core._ID_CONST)
        + core._OBS_WOBS * core._DEFAULT_WOBS
    )


# 観測 logit の許容移動幅(親 logit からの絶対差をこの幅以内にクリップ)。
# 微小スケール(±数%)前提の保守的上限。これを超えると h_q が閾値帯を跨ぐ恐れがある。
_MAX_LOGIT_DELTA = 0.15


def _apply_perturbation_to_frame(snap, qos_rel, latency_rel):
    """1 フレーム snap の QoS / latency_ms のみを微小スケールで揺らす(R チャネルは不触)。

    - QoS は [0,1] にクリップ。latency は [0, ∞) にクリップ(負にしない)。
    - 揺らした結果の観測 logit が親 logit から _MAX_LOGIT_DELTA を超えて動く場合は、
      QoS/latency をその境界へ後退させて帯の内側に留める(保守クリップ)。
    - scene_state が無いフレームは縮退既定で動くため摂動しない(安全側=親のまま)。

    Returns:
        摂動後の snap(deep copy)。scene_state を持たないフレームは copy のみ。
    """
    child = copy.deepcopy(snap)
    ss = child.get("scene_state")
    if not isinstance(ss, dict) or "QoS" not in ss or "latency_ms" not in ss:
        # scene_state 欠落 → 観測式は縮退既定で動く(QoS/latency に依存しない)ため摂動しない。
        return child

    qos0 = float(ss["QoS"])
    lat0 = float(ss["latency_ms"])
    logit0 = _quality_logit(qos0, lat0)

    qos1 = qos0 * (1.0 + qos_rel)
    lat1 = lat0 * (1.0 + latency_rel)
    # 物理レンジへクリップ。
    qos1 = min(1.0, max(0.0, qos1))
    lat1 = max(0.0, lat1)

    # 観測 logit が帯を跨がないよう保守クリップ(親 logit ± _MAX_LOGIT_DELTA)。
    logit1 = _quality_logit(qos1, lat1)
    delta = logit1 - logit0
    if abs(delta) > _MAX_LOGIT_DELTA:
        # delta を境界へ後退させる(QoS のみで補正=決定的)。
        # logit の QoS 係数は _OBS_QOS なので、許す delta に対応する QoS を逆算。
        allowed = math.copysign(_MAX_LOGIT_DELTA, delta)
        # logit0 + allowed を満たす QoS を求める(latency1 は維持)。
        # logit = BIAS + QOS_COEF·qos + LAT_COEF·(lat/scale) + 定数
        lat_term = core._OBS_LATENCY * (lat1 / core._LATENCY_SCALE)
        const = (
            core._OBS_BIAS
            + core._OBS_ID * (1.0 - core._ID_CONST)
            + core._OBS_WOBS * core._DEFAULT_WOBS
        )
        target_logit = logit0 + allowed
        qos1 = (target_logit - const - lat_term) / core._OBS_QOS
        qos1 = min(1.0, max(0.0, qos1))

    ss["QoS"] = qos1
    ss["latency_ms"] = lat1
    return child


# ---------------------------------------------------------------------------
# 子シナリオ(snap 系列)の生成
# ---------------------------------------------------------------------------

def make_child_snaps(parent_snaps, index):
    """親 snap 系列から index 番目の子 snap 系列を決定的に生成する(乱数なし)。

    全フレームに同一の (qos_rel, latency_rel)(index 由来)を適用する。R チャネル
    (tracks / links / geom / utter_events)は一切触らないため、mode/t0/t1/role/relation
    の入力は親と完全同一(その層は原理的にラベル不変)。
    """
    qos_rel, latency_rel = _deterministic_scales(index)
    return [_apply_perturbation_to_frame(s, qos_rel, latency_rel) for s in parent_snaps]


# ---------------------------------------------------------------------------
# ラベル保存の実測検証(最重要・捏造防止)
# ---------------------------------------------------------------------------

def verify_child_preserves_labels(parent_views, child_snaps):
    """子 snap を core.run_supreme に流し、8 層 view が親と完全一致するか検証する。

    一致すれば「摂動で per-frame ラベルが保たれた」ことの直接の実測証拠(8 層すべて)。
    一致しなければ False を返し(壊れた子=採用しない)、最初の不一致層・フレームを示す。

    Returns:
        (ok: bool, detail: dict)。detail は不一致時に {"layer","frame","parent","child"} を持つ。
    """
    child_views = core.run_supreme(child_snaps)
    if len(child_views) != len(parent_views):
        return False, {
            "reason": "frame_count_mismatch",
            "parent_frames": len(parent_views),
            "child_frames": len(child_views),
        }
    for i, (pv, cv) in enumerate(zip(parent_views, child_views)):
        for layer in core.VIEW_LAYERS:
            if pv.get(layer) != cv.get(layer):
                return False, {
                    "reason": "label_mismatch",
                    "layer": layer,
                    "frame": i,
                    "parent": pv.get(layer),
                    "child": cv.get(layer),
                }
    return True, {"reason": "ok", "frames": len(parent_views)}


def generate_preserving_children(parent_snaps, parent_views, m):
    """親から最大 m 件の label-preserving 子を生成する(壊れた子は除外・報告)。

    各子について make_child_snaps → verify_child_preserves_labels を行い、8 層 view が
    親と完全一致した子のみ採用する。

    Returns:
        {
          "kept":    [child_snaps, ...],          # ラベル保存が実測担保された子のみ
          "kept_index": [i, ...],                 # 採用した子のインデックス
          "rejected": [{"index","detail"}, ...],  # 壊れた子(採用しない)の記録
          "n_requested": m,
        }
    """
    kept = []
    kept_index = []
    rejected = []
    for i in range(m):
        child = make_child_snaps(parent_snaps, i)
        ok, detail = verify_child_preserves_labels(parent_views, child)
        if ok:
            kept.append(child)
            kept_index.append(i)
        else:
            rejected.append({"index": i, "detail": detail})
    return {
        "kept": kept,
        "kept_index": kept_index,
        "rejected": rejected,
        "n_requested": m,
    }
