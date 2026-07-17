"""t2_role(強項目)忠実度ギャップ診断ランナー(src/supreme 無改変・診断のみ)。

目的: 新 supreme の t2_role(in-sample v021_core acc=0.8714)が旧 supreme(l04-ours
0.9333)に -0.06 劣る原因を、

  (A) 構造バグ(証拠の死配線/潰し) /
  (B) baseline 規則の再現漏れ(忠実度ギャップ) /
  (C) genuine

のどれかへ切り分ける。run_dev_eval / run_dev_eval_diagnose と同一経路
(PSO→core.run_supreme→v1.4 view、GT→ADR0006 正準化→v1.4 gt view、210 フレーム)で
t2_role について「混同行列 / 誤りフレーム列挙 / シナリオ別精度 / 証拠の利用状況」を測定する。

最重要規律(指示):
  - **src/supreme・テストは一切変更しない**(純粋な測定・分析)。
  - baseline は import しない(意味論は読むが実行時リンクしない)。決定的。stdlib + pyyaml。
  - 正準化・データ対応ロジックは run_dev_eval から **再利用**(二重実装しない)。
  - 数字・所見は観測値のみ。捏造禁止。不整合・不明は報告。

切り分け素材:
  - 混同行列(GT role → supreme role argmax): 系統的取り違えか分散か。
  - 誤りフレーム列挙(GT≠pred): シナリオ・ts・GT・pred・**その場の role 証拠**。
  - 証拠在不在検査: 誤るフレームで role 判定に必要な証拠(has_*・speaking・min_range・
    linked_speech_score・object vehicle 等)が入力に在るのに新 supreme が使っていないか
    (=死配線/証拠潰し=A)、それとも baseline 規則と違うだけ(=B)かを区別する。

使い方:
    python scripts/run_role_diagnose.py [--pso-dir <path>] [--gt-dir <path>] [--out <path>]
"""

from __future__ import annotations

import argparse
import datetime
import os
import sys
from collections import Counter, defaultdict

# プロジェクト src を Python パスに追加(run_dev_eval と同じ)。
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_SRC_DIR = os.path.join(os.path.dirname(_SCRIPT_DIR), "src")
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

# supreme 公開 API のみ(baseline は import しない)。
from supreme import core

# 既存の評価ランナーから「正準化・データ対応・既定パス・語彙集合」を再利用(二重実装しない)。
import run_dev_eval as dev

LAYER = "t2_role"


# ===========================================================================
# データ読み込み(run_dev_eval_diagnose.load_views_and_gt と同型・role に流用)
# ===========================================================================

def load_views_and_gt(pso_dir, gt_dir):
    """run_dev_eval と同一経路で (views_by_sid, gt_by_sid, snaps_by_sid, dir_to_sid, dirs) を返す。

    role 診断では「その場の入力 snap」も後段の証拠在不在検査に要るため、
    snaps_by_sid(scenario_id -> [snap,...])も併せて返す(run_dev_eval_diagnose との差分)。
    """
    dirs = dev._scenario_dirs(pso_dir, gt_dir)

    scenario_inputs = {}
    scenario_gt = {}
    dir_to_sid = {}

    for dir_name in dirs:
        pso_path = os.path.join(pso_dir, dir_name, "pso_input.jsonl")
        gt_path = os.path.join(gt_dir, dir_name, "ground_truth.yaml")
        if not os.path.isfile(pso_path):
            raise dev.DataMismatch(f"PSO 入力が存在しない: {pso_path}")
        if not os.path.isfile(gt_path):
            raise dev.DataMismatch(f"GT が存在しない: {gt_path}")

        snaps = dev._load_pso(pso_path)
        gt_data = dev._load_gt(gt_path)
        timeline = gt_data.get("timeline", []) or []
        scenario_id = str(gt_data.get("scenario_id", dir_name))

        if len(snaps) != len(timeline):
            raise dev.DataMismatch(
                f"[{dir_name}] pso 入力と GT のフレーム数が不一致: "
                f"pso={len(snaps)} gt={len(timeline)}(scenario_id={scenario_id})。停止する。"
            )
        for i, (snap, gt_fr) in enumerate(zip(snaps, timeline)):
            pso_ts = float(snap.get("ts"))
            gt_ts = float(gt_fr.get("ts"))
            if pso_ts != gt_ts:
                raise dev.DataMismatch(
                    f"[{dir_name}] frame {i} の ts が pso と GT で不一致: "
                    f"pso_ts={pso_ts} gt_ts={gt_ts}(scenario_id={scenario_id})。停止する。"
                )

        gt_views = [
            dev.gt_frame_to_v14_view(gt_fr, scenario_id=scenario_id, ts=gt_fr.get("ts"))
            for gt_fr in timeline
        ]

        scenario_inputs[scenario_id] = snaps
        scenario_gt[scenario_id] = gt_views
        dir_to_sid[dir_name] = scenario_id

    # supreme view を生成(決定性検査つき)。
    views_by_sid = core.run_supreme_scenarios(scenario_inputs)
    views_by_sid_2 = core.run_supreme_scenarios(scenario_inputs)
    if views_by_sid != views_by_sid_2:
        raise dev.DataMismatch(
            "決定性検査に失敗: 2 回の run_supreme_scenarios の出力が一致しない。停止する。"
        )

    for sid, views in views_by_sid.items():
        if len(views) != len(scenario_gt[sid]):
            raise dev.DataMismatch(
                f"[{sid}] supreme view 数({len(views)})が gt view 数"
                f"({len(scenario_gt[sid])})と不一致。停止する。"
            )

    return views_by_sid, scenario_gt, scenario_inputs, dir_to_sid, dirs


# ===========================================================================
# 証拠の再抽出(core._role_evidence と同じ意味論をローカルで再現=src 無改変で観測する)
#
# 注: src/supreme を変更しない規律のため、core._role_evidence(非公開)を直接呼ぶ。
#     これは「観測のために既存純関数を読むだけ」であり src の挙動を一切変えない。
#     さらに baseline 規則との乖離点(object vehicle・EMA 等)を可視化するため、
#     入力 snap から「baseline が見る証拠」も独立に観測する(baseline コードは import しない)。
# ===========================================================================

def supreme_role_evidence(snap):
    """新 supreme が実際に role.classify へ渡す証拠 dict(core._role_evidence を観測)。"""
    return core._role_evidence(snap)


def observe_input_signals(snap):
    """入力 snap に「在る」role 関連シグナルを独立観測する(baseline 意味論の照合用)。

    baseline は import しない。snap 構造(tracks.audio/humans/objects・links・utter_events)を
    読み、role 判定に関わりうる素のシグナルを列挙する。これにより「証拠が入力に在るのに
    新 supreme が使っていない」=死配線/証拠潰し(A)を、規則差(B)と区別できる。
    """
    audio = snap.get("tracks", {}).get("audio", []) or []
    humans = snap.get("tracks", {}).get("humans", []) or []
    objects = snap.get("tracks", {}).get("objects", []) or []
    links = snap.get("links", []) or []

    audio_types = sorted({t.get("type") for t in audio if t.get("type")})
    object_types = sorted({t.get("type") for t in objects if t.get("type")})
    has_audio_vehicle = any(t.get("type") == "vehicle" for t in audio)
    has_object_vehicle = any(t.get("type") == "vehicle" for t in objects)
    speaking = 0.0
    for h in humans:
        sp = h.get("speaking_prob")
        if sp is not None:
            speaking = max(speaking, float(sp))
    linked_speech = 0.0
    n_speaking_links = 0
    for lnk in links:
        if lnk.get("type") == "speaking":
            n_speaking_links += 1
            linked_speech = max(linked_speech, float(lnk.get("score", 0.0)))
    return {
        "audio_types": audio_types,
        "object_types": object_types,
        "has_audio_vehicle": has_audio_vehicle,
        "has_object_vehicle": has_object_vehicle,
        "n_humans": len(humans),
        "n_objects": len(objects),
        "speaking": speaking,
        "n_speaking_links": n_speaking_links,
        "linked_speech_score": linked_speech,
    }


# ===========================================================================
# 集計
# ===========================================================================

class RoleStats:
    def __init__(self):
        self.gt_counts = Counter()
        self.pred_counts = Counter()
        self.confusion = defaultdict(Counter)   # gt -> Counter(pred -> n)
        self.scenario_correct = Counter()
        self.scenario_total = Counter()
        self.n_scored = 0
        self.n_correct = 0
        self.errors = []   # 誤りフレーム(GT 非 None ∧ pred≠gt)

    def add(self, sid, ts, gt_label, pred_label, sup_ev, in_sig):
        if gt_label is None:
            return
        self.gt_counts[gt_label] += 1
        self.pred_counts[pred_label] += 1
        self.confusion[gt_label][pred_label] += 1
        self.scenario_total[sid] += 1
        self.n_scored += 1
        if pred_label == gt_label:
            self.scenario_correct[sid] += 1
            self.n_correct += 1
        else:
            self.errors.append({
                "sid": sid, "ts": ts, "gt": gt_label, "pred": pred_label,
                "sup_ev": sup_ev, "in_sig": in_sig,
            })

    def acc(self):
        return self.n_correct / self.n_scored if self.n_scored else float("nan")


def collect(views_by_sid, gt_by_sid, snaps_by_sid):
    st = RoleStats()
    for sid in sorted(views_by_sid):
        views = views_by_sid[sid]
        gts = gt_by_sid[sid]
        snaps = snaps_by_sid[sid]
        for i, view in enumerate(views):
            gt = gts[i].get(LAYER)
            pred = view.get(LAYER)
            snap = snaps[i]
            sup_ev = supreme_role_evidence(snap)
            in_sig = observe_input_signals(snap)
            ts = snap.get("ts")
            st.add(sid, ts, gt, pred, sup_ev, in_sig)
    return st


# ===========================================================================
# 誤りフレームの A/B 分類(証拠在不在 × baseline 規則照合)
#
# baseline 規則(意味論・src/ns_epi/t2.py を読んで把握。import しない):
#   r1) has_siren ∨ has_alarm -> source_alarm += 1.5  elif has_vehicle -> source_vehicle += 1.5
#       (※ baseline の has_vehicle = audio vehicle ∨ **object vehicle**)
#   r2) conv_strong(speech ∧ speaking>0.7 ∧ min_range<5) -> source_speech += 2.0
#   r3) conv_weak (speech ∧ speaking>0.3 ∧ min_range<4 ∧ ¬conv_strong) -> source_speech += 1.0
#   r4) linked_speech_score>0.4 -> source_speech += 1.5
#   r5) 全 role 0 -> unknown += 1.5
#   そして baseline は logits を **品質温度 softmax → 時間 EMA → argmax**(t2.py 段3-4)。
#   新 supreme(role.py)は **生 logit を per-frame argmax**(softmax/EMA なし)。
# ===========================================================================

def classify_error(err):
    """1 誤りフレームを (A 候補 / B 候補 / 要精査) に仕分ける素材を作る。

    返す reason は観測事実のみ(捏造しない)。最終 A/B/C 判定はレポート横断節で総括する。
    """
    sup_ev = err["sup_ev"]
    in_sig = err["in_sig"]
    gt = err["gt"]
    pred = err["pred"]

    notes = []
    flag_dead_wiring = False     # 入力に在るのに新 supreme が使っていない証拠(A 候補)
    flag_rule_diff = False       # baseline と規則が違うだけ(B 候補)

    # --- object vehicle 死配線検査(新 supreme の _role_evidence は audio vehicle のみ)---
    if in_sig["has_object_vehicle"] and not sup_ev.get("has_vehicle", False):
        notes.append(
            "object track に vehicle が在るが新 supreme の has_vehicle 証拠は False "
            "(_role_evidence が audio vehicle のみ参照=baseline の object vehicle 規則を欠く)"
        )
        # この欠落が当該誤りに効くのは pred/gt のどちらかが source_vehicle のときのみ。
        if gt == "source_vehicle" or pred == "source_vehicle":
            flag_dead_wiring = True

    # --- EMA 不在の徴候: 現フレーム証拠が薄い(unknown 既定)のに GT は実 role ---
    sup_logit_keys = set()
    # role.role_logits の発火状況を観測(値は使わずキーの有無のみ。src は無改変)。
    try:
        from supreme import role as role_mod
        logits = role_mod.role_logits(sup_ev)
        sup_logit_keys = set(logits)
    except Exception:  # 観測失敗時は素材を空にするだけ(捏造しない)
        logits = {}
        sup_logit_keys = set()

    if pred == "unknown" and gt != "unknown":
        notes.append(
            f"新 supreme は現フレーム証拠で role logit が unknown 既定に潰れた一方 "
            f"GT={gt!r}(baseline は softmax+時間 EMA で前フレーム role を持ち越すため、"
            f"瞬間的に証拠が切れても直前 role を保持しうる=EMA 不在の忠実度ギャップ候補)"
        )
        flag_rule_diff = True

    # --- 会話系取り違え: speech 証拠が在るが閾値/EMA でズレ ---
    if (gt == "source_speech" and pred != "source_speech"
            and (in_sig["speaking"] > 0.0 or in_sig["linked_speech_score"] > 0.0
                 or "speech" in in_sig["audio_types"])):
        notes.append(
            f"GT=source_speech・新 supreme pred={pred!r}。入力に発話シグナル "
            f"(speaking={in_sig['speaking']:.2f} / linked_speech={in_sig['linked_speech_score']:.2f} "
            f"/ audio={in_sig['audio_types']})は在るが閾値(speaking>0.7/0.3・range<5/4・link>0.4)"
            f"を満たさず source_speech logit 未発火。閾値/EMA の規則差候補"
        )
        flag_rule_diff = True

    # --- 緊急音/車両系 ---
    if gt in ("source_alarm", "source_vehicle") and pred not in ("source_alarm", "source_vehicle"):
        notes.append(
            f"GT={gt!r}・pred={pred!r}。audio_types={in_sig['audio_types']}・"
            f"object_types={in_sig['object_types']}"
        )

    if not notes:
        notes.append(
            f"GT={gt!r}・pred={pred!r}・新 supreme 発火 logit={sorted(sup_logit_keys)!r}・"
            f"入力 audio={in_sig['audio_types']} object={in_sig['object_types']} "
            f"speaking={in_sig['speaking']:.2f} link={in_sig['linked_speech_score']:.2f}"
        )

    return {
        "flag_dead_wiring": flag_dead_wiring,
        "flag_rule_diff": flag_rule_diff,
        "notes": notes,
    }


# ===========================================================================
# レポート生成
# ===========================================================================

def render_report(*, dirs, dir_to_sid, st, supreme_vocab, gt_vocab_schema):
    now = datetime.datetime.now()
    stamp = now.strftime("%Y-%m-%d %H:%M")
    L = []
    a = L.append

    a("# t2_role 忠実度ギャップ診断レポート(新 supreme vs baseline 規則)")
    a("")
    a(f"- 生成時刻: {stamp}")
    a(f"- 対象シナリオ: {len(dirs)} 件 / 総採点フレーム(GT 非 null): {st.n_scored}")
    a("- 経路: run_dev_eval と同一(PSO→core.run_supreme→v1.4 view、GT→ADR0006 正準化→v1.4 gt view)")
    a("- 正準化・データ対応は `run_dev_eval.py` を再利用(二重実装なし)。")
    a("- **src/supreme・テストは未変更(診断のみ)**。baseline は import していない(意味論のみ読了)。決定的。")
    a("")
    a("> 注: これは in-sample(v021_core)診断。最終 verdict ではなく忠実度ギャップ(A/B/C)の切り分けが目的。")
    a(f"> 比較対象スコア: 新 supreme t2_role **{st.acc():.4f}**(本走) / 旧 supreme l04-ours 0.9333 / baseline 0.8429。")
    a("")

    # ----- サマリ -----
    a("## 結論サマリ")
    a("")
    a(f"- t2_role acc(新 supreme・in-sample) = **{st.acc():.4f}**(正答 {st.n_correct} / 採点 {st.n_scored})")
    a(f"- 誤りフレーム数 = **{len(st.errors)}**")
    # 最頻取り違え。
    pair_counter = Counter((e["gt"], e["pred"]) for e in st.errors)
    a("- 最頻の取り違え(GT→pred):")
    for (g, p), n in pair_counter.most_common(8):
        a(f"  - `{g}` → `{p}`: {n} 件")
    a("")

    # ----- 1. 語彙対照 -----
    a("## 1. 語彙集合の対照(死配線/語彙ミス検出)")
    a("")
    a("**GT 側 t2_role ラベルと頻度(採点対象):**")
    a("")
    a("| GT ラベル | 頻度 |")
    a("|---|---:|")
    for lbl, n in st.gt_counts.most_common():
        a(f"| `{lbl}` | {n} |")
    a("")
    a("**新 supreme 側 t2_role ラベルと頻度(GT 採点対象フレーム上):**")
    a("")
    a("| supreme ラベル | 頻度 |")
    a("|---|---:|")
    for lbl, n in st.pred_counts.most_common():
        a(f"| `{lbl}` | {n} |")
    a("")
    gt_only = set(st.gt_counts) - set(st.pred_counts)
    pred_only = set(st.pred_counts) - set(st.gt_counts)
    a(f"- GT に出るが新 supreme が**一度も出さない**ラベル: "
      f"{sorted(gt_only) if gt_only else 'なし'}")
    a(f"- 新 supreme が出すが GT に**無い**ラベル: "
      f"{sorted(pred_only) if pred_only else 'なし'}")
    pred_outside = sorted(set(st.pred_counts) - set(supreme_vocab))
    a(f"- v1.4 role 語彙集合 {sorted(supreme_vocab)!r} 外の出力: "
      f"{pred_outside if pred_outside else 'なし(配線健全)'}")
    a("")

    # ----- 2. 混同行列 -----
    a("## 2. 混同行列(GT 行 → 新 supreme 予測 列)")
    a("")
    a(_render_confusion(st))
    a("")
    # 系統的か分散か。
    sys_pairs = [(g, p, n) for (g, p), n in pair_counter.most_common() if g != p]
    if sys_pairs:
        top_g, top_p, top_n = sys_pairs[0]
        share = top_n / len(st.errors) if st.errors else 0.0
        a(f"- 最頻誤りペア `{top_g}`→`{top_p}` が全誤りの {share:.0%} を占める"
          f"({'系統的' if share >= 0.4 else '分散寄り'})。")
    a("")

    # ----- 3. シナリオ別精度 -----
    a("## 3. シナリオ別精度")
    a("")
    a("| dir | scenario_id | 採点数 | 正答 | acc |")
    a("|---|---|---:|---:|---:|")
    for d in dirs:
        sid = dir_to_sid[d]
        tot = st.scenario_total.get(sid, 0)
        cor = st.scenario_correct.get(sid, 0)
        acc = (cor / tot) if tot else float("nan")
        acc_s = f"{acc:.3f}" if tot else "n/a"
        flag = " ⚠️" if (tot and cor == 0) else ""
        a(f"| {d} | {sid} | {tot} | {cor} | {acc_s}{flag} |")
    a("")

    # ----- 4. 誤りフレーム列挙 + A/B 素材 -----
    a("## 4. 誤りフレーム列挙(GT≠pred)と証拠在不在")
    a("")
    a("各誤りフレームについて、GT・pred・新 supreme が実際に渡した証拠(core._role_evidence)・"
      "入力 snap に在る素のシグナル(独立観測)・所見を示す。")
    a("")
    n_dead = 0
    n_rulediff = 0
    for e in st.errors:
        cl = classify_error(e)
        if cl["flag_dead_wiring"]:
            n_dead += 1
        if cl["flag_rule_diff"]:
            n_rulediff += 1
        sup_ev = e["sup_ev"]
        in_sig = e["in_sig"]
        a(f"### {e['sid']} @ ts={e['ts']} — GT=`{e['gt']}` / pred=`{e['pred']}`")
        a("")
        a(f"- 新 supreme 証拠(_role_evidence): has_siren={sup_ev.get('has_siren')} "
          f"has_alarm={sup_ev.get('has_alarm')} has_vehicle={sup_ev.get('has_vehicle')} "
          f"has_speech={sup_ev.get('has_speech')} speaking={sup_ev.get('speaking'):.2f} "
          f"min_range={sup_ev.get('min_range'):.2f} "
          f"linked_speech={sup_ev.get('linked_speech_score'):.2f}")
        a(f"- 入力素シグナル: audio={in_sig['audio_types']} object={in_sig['object_types']} "
          f"n_humans={in_sig['n_humans']} n_objects={in_sig['n_objects']} "
          f"has_object_vehicle={in_sig['has_object_vehicle']} "
          f"n_speaking_links={in_sig['n_speaking_links']}")
        for note in cl["notes"]:
            a(f"- {note}")
        a("")

    # ----- 5. 横断的判定 -----
    a("## 5. 横断的判定(A 構造バグ / B 忠実度ギャップ / C genuine)")
    a("")
    a(f"- object vehicle 死配線が当該誤りに効くフレーム数(A 候補): **{n_dead}**")
    a(f"- baseline 規則差(閾値/EMA/softmax)候補フレーム数(B 候補): **{n_rulediff}**")
    a("")
    a("**新 supreme role と baseline role の乖離点(意味論照合・baseline 非 import):**")
    a("")
    a("| 観点 | 新 supreme(role.py + core._role_evidence) | baseline(ns_epi/t2.py 意味論) | 乖離 |")
    a("|---|---|---|---|")
    a("| has_vehicle 証拠 | audio track type==vehicle のみ | audio **∨ object** track type==vehicle | object vehicle を欠く |")
    a("| logit 規則 r1–r5 | r1 緊急音優先/r2 conv_strong/r3 conv_weak/r4 linked_speech/r5 unknown 既定 | 同一(重み・閾値も一致) | **一致** |")
    a("| 後段処理 | 生 logit を **per-frame argmax**(softmax/EMA なし) | 品質温度 softmax → **時間 EMA** → argmax | EMA/温度を欠く |")
    a("| 既定潰れ | 無証拠フレームは即 unknown | EMA で前フレーム role を持ち越し可 | 瞬間の証拠切れに脆い |")
    a("")

    a("> 上記は src/ns_epi/t2.py の意味論を読み取った対照であり、baseline コードは実行時に "
      "リンクしていない(F-006-2 独立性)。新 supreme role.py の **logit 規則(r1–r5・重み・閾値)は "
      "baseline と一致**。乖離は (i) has_vehicle の object 経路欠落、(ii) 後段の softmax+EMA 平滑の不在。")
    a("")

    a("---")
    a("")
    a("_本レポートは supreme.* API(core / role)と run_dev_eval の正準化ロジックのみで生成"
      "(baseline 非 import・src/supreme 本体未変更・決定的)。数字は観測値のみ。_")
    a("")

    return "\n".join(L), n_dead, n_rulediff


def _render_confusion(st):
    gt_labels = sorted(st.gt_counts)
    pred_labels = sorted(st.pred_counts)
    if not gt_labels:
        return "(採点対象なし)"
    header = "| GT＼予測 | " + " | ".join(f"`{p}`" for p in pred_labels) + " | 行計 |"
    sep = "|---|" + "|".join(["---:"] * len(pred_labels)) + "|---:|"
    rows = [header, sep]
    for g in gt_labels:
        cells = []
        row_total = 0
        for p in pred_labels:
            c = st.confusion[g].get(p, 0)
            row_total += c
            cells.append(f"**{c}**" if (g == p and c) else (str(c) if c else "·"))
        rows.append(f"| `{g}` | " + " | ".join(cells) + f" | {row_total} |")
    return "\n".join(rows)


# ===========================================================================
# 標準出力サマリ
# ===========================================================================

def print_stdout_summary(st, n_dead, n_rulediff):
    print()
    print("=" * 72)
    print("t2_role 忠実度ギャップ診断サマリ(標準出力)")
    print("=" * 72)
    print(f"  acc(新 supreme・in-sample) = {st.acc():.4f}  採点={st.n_scored}  正答={st.n_correct}")
    print(f"  誤りフレーム数 = {len(st.errors)}")
    print(f"  GT 語彙: {dict(st.gt_counts.most_common())}")
    print(f"  supreme 語彙: {dict(st.pred_counts.most_common())}")
    pair_counter = Counter((e["gt"], e["pred"]) for e in st.errors)
    print("  最頻取り違え(GT→pred):")
    for (g, p), n in pair_counter.most_common(8):
        print(f"    {g} -> {p}: {n}")
    print(f"  object vehicle 死配線が効く誤り(A 候補) = {n_dead}")
    print(f"  baseline 規則差(閾値/EMA)候補(B 候補)   = {n_rulediff}")
    print("=" * 72)


# ===========================================================================
# メイン
# ===========================================================================

def run(pso_dir, gt_dir, out_path):
    print(f"[1/4] データ読み込み(run_dev_eval 経路を再利用)")
    print(f"      PSO={pso_dir}")
    print(f"      GT ={gt_dir}")
    views_by_sid, gt_by_sid, snaps_by_sid, dir_to_sid, dirs = load_views_and_gt(pso_dir, gt_dir)
    total_frames = sum(len(v) for v in views_by_sid.values())
    print(f"      共通シナリオ {len(dirs)} 件・総フレーム {total_frames}・決定性 OK・GT 正準化 OK")

    print(f"[2/4] t2_role の混同行列・誤りフレーム・証拠在不在を集計します")
    st = collect(views_by_sid, gt_by_sid, snaps_by_sid)

    print(f"[3/4] レポートを生成します")
    supreme_vocab = dev._V14_VOCAB[LAYER]
    report_md, n_dead, n_rulediff = render_report(
        dirs=dirs, dir_to_sid=dir_to_sid, st=st,
        supreme_vocab=supreme_vocab, gt_vocab_schema=supreme_vocab,
    )

    print(f"[4/4] レポートを書き出します: {out_path}")
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report_md)
    print(f"      出力完了: {out_path}")

    print_stdout_summary(st, n_dead, n_rulediff)
    return st, n_dead, n_rulediff


def main():
    parser = argparse.ArgumentParser(
        description="t2_role 忠実度ギャップ診断ランナー(src/supreme 無改変・診断のみ)"
    )
    parser.add_argument("--pso-dir", default=dev.DEFAULT_PSO_DIR)
    parser.add_argument("--gt-dir", default=dev.DEFAULT_GT_DIR)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    out_path = args.out
    if out_path is None:
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M")
        out_path = os.path.join(dev.DEFAULT_OUT_DIR, f"role-diagnose-{stamp}.md")

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
