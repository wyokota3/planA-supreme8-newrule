"""弱3層(t3_hypothesis / scene_regime / quality_regime)の誤り診断ランナー。

run_dev_eval.py と同一経路(PSO→core.run_supreme→v1.4 view、GT→ADR0006 正準化→v1.4 gt view、
210 フレーム)で評価し、弱3層について「語彙集合の対照 / 混同行列 / シナリオ別精度 / 最頻ラベル」を
測定して診断レポートを出す。**supreme 本体(src/supreme/*.py)は一切変更しない**。純粋な測定・分析のみ。

切り分けの主眼(指示):
  各層の不振が
    (A) 語彙/配線の構造ミス(supreme が GT と別の語彙空間を出す・特定クラスを一切出さない 等)か、
    (B) 係数の未チューニング(正しい語彙だが閾値/感度がズレている)か、
  を**証拠付きで判定**する。

規律:
  - supreme.* 公開 API のみ(baseline は import しない)。決定的。
  - 既存の正準化・データ対応ロジックは run_dev_eval から **再利用**(二重実装しない)。
  - pyyaml 使用可。GT 正準化で v1.3 固有ラベルに当たれば run_dev_eval と同じく停止する。

使い方:
    python scripts/run_dev_eval_diagnose.py [--pso-dir <path>] [--gt-dir <path>] [--out <path>]
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

# 既存の評価ランナーから「正準化・データ対応・既定パス・語彙集合」を再利用する
# (二重実装しない=指示の規律)。run_dev_eval は import 時副作用なし(main ガードあり)。
import run_dev_eval as dev


# 診断対象の弱3層(指示)。
TARGET_LAYERS = ("t3_hypothesis", "scene_regime", "quality_regime")


# ===========================================================================
# データ読み込み(run_dev_eval のロジックを再利用して view/gt を取り出す)
# ===========================================================================

def load_views_and_gt(pso_dir, gt_dir):
    """run_dev_eval と同一経路で (views_by_sid, gt_by_sid, dir_to_sid, dirs) を返す。

    - シナリオ対応検証(dev._scenario_dirs)
    - フレーム数 / ts 対応検証(run_dev_eval.run と同じ規律)
    - GT を ADR0006 正準化(dev.gt_frame_to_v14_view)。v1.3 固有ラベルがあれば停止。
    - core.run_supreme_scenarios で supreme view を生成し、決定性も検査。
    """
    dirs = dev._scenario_dirs(pso_dir, gt_dir)

    scenario_inputs = {}   # scenario_id -> snaps
    scenario_gt = {}       # scenario_id -> [gt_view_v14, ...]
    dir_to_sid = {}        # dir_name -> scenario_id

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

    # supreme view を生成(決定性検査つき=run_dev_eval と整合)。
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

    return views_by_sid, scenario_gt, dir_to_sid, dirs


# ===========================================================================
# 集計(語彙集合 / 混同行列 / シナリオ別精度 / 最頻ラベル)
# ===========================================================================

class LayerStats:
    """1 層分の診断統計を保持する。"""

    def __init__(self, layer):
        self.layer = layer
        self.gt_counts = Counter()        # GT ラベル -> 出現数(採点対象=非 None のみ)
        self.pred_counts = Counter()      # supreme 予測ラベル -> 出現数(GT 非 None のフレームのみ)
        self.confusion = defaultdict(Counter)  # gt_label -> Counter(pred_label -> count)
        self.scenario_correct = Counter()     # sid -> 正答数
        self.scenario_total = Counter()       # sid -> 採点対象フレーム数
        self.n_scored = 0
        self.n_correct = 0

    def add(self, sid, gt_label, pred_label):
        # GT が None のフレームは採点対象外(harness と同規約)。
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

    def acc(self):
        return self.n_correct / self.n_scored if self.n_scored else float("nan")

    def gt_vocab(self):
        return set(self.gt_counts)

    def pred_vocab(self):
        return set(self.pred_counts)

    def gt_only(self):
        """GT に出るが supreme が一度も出さないラベル。"""
        return self.gt_vocab() - self.pred_vocab()

    def pred_only(self):
        """supreme が出すが GT に無いラベル。"""
        return self.pred_vocab() - self.gt_vocab()

    def shared(self):
        return self.gt_vocab() & self.pred_vocab()

    def most_common_gt(self):
        return self.gt_counts.most_common(1)[0] if self.gt_counts else (None, 0)

    def most_common_pred(self):
        return self.pred_counts.most_common(1)[0] if self.pred_counts else (None, 0)


def collect_stats(views_by_sid, gt_by_sid, layers):
    """各層の LayerStats を集計する。"""
    stats = {layer: LayerStats(layer) for layer in layers}
    for sid in sorted(views_by_sid):
        views = views_by_sid[sid]
        gts = gt_by_sid[sid]
        for i, view in enumerate(views):
            gt = gts[i]
            for layer in layers:
                stats[layer].add(sid, gt.get(layer), view.get(layer))
    return stats


def diagnose_layer(st, supreme_vocab):
    """1 層の不振原因を (A) 構造ミス / (B) 未チューニング のどちらかに判定する。

    判定ロジック(証拠ベース・指示の最重要結論):
      - GT 語彙の大半(>=50%・かつ最頻含む)を supreme が一度も出さない、または
        supreme 予測が単一クラスに極端集中(>=90%)し GT は多様 → (A) 構造ミス寄り。
      - GT 語彙と supreme 出力語彙が概ね共有され、誤りが特定クラス偏りでなく分散、
        定数潰れも無い → (B) 未チューニング寄り。
      - その中間(語彙は共有するが系統的に特定クラスへ吸い込まれる)は両者の度合いを併記。

    返り値: dict(判定・根拠列)。捏造せず、観測した数字のみから所見を述べる。
    """
    gt_labels = st.gt_vocab()
    pred_labels = st.pred_vocab()
    gt_only = st.gt_only()
    pred_only = st.pred_only()
    n_scored = st.n_scored

    # supreme が GT 語彙のうち一度も出さないクラスの GT 出現比率(=取りこぼし規模)。
    gt_total = sum(st.gt_counts.values())
    missed_mass = sum(st.gt_counts[c] for c in gt_only) / gt_total if gt_total else 0.0

    # supreme 予測の最頻クラス集中度(定数潰れ検出)。
    mc_pred_label, mc_pred_n = st.most_common_pred()
    pred_concentration = (mc_pred_n / n_scored) if n_scored else 0.0
    mc_gt_label, mc_gt_n = st.most_common_gt()
    gt_concentration = (mc_gt_n / gt_total) if gt_total else 0.0

    # supreme 出力が supreme 自身の v1.4 語彙集合に収まっているか(配線健全性の素材)。
    pred_outside_vocab = sorted(pred_labels - set(supreme_vocab))

    flags = []
    structural_signals = 0
    tuning_signals = 0

    # シグナル1: GT に出るが supreme が一切出さないラベルが GT 質量の半分超 → 構造ミス。
    if missed_mass >= 0.50:
        structural_signals += 1
        flags.append(
            f"GT 語彙のうち supreme が一度も出さないクラスが GT 出現の {missed_mass:.0%} を占める"
            f"(取りこぼし語彙={sorted(gt_only)!r})"
        )
    elif gt_only:
        flags.append(
            f"GT にあり supreme が出さないクラス={sorted(gt_only)!r}"
            f"(GT 出現の {missed_mass:.0%}・部分的)"
        )

    # シグナル2: supreme 予測が単一クラスへ極端集中(>=90%)し GT は多様 → 定数潰れ=構造寄り。
    if pred_concentration >= 0.90 and len(gt_labels) >= 2:
        structural_signals += 1
        flags.append(
            f"supreme 予測が単一クラス '{mc_pred_label}' に {pred_concentration:.0%} 集中"
            f"(定数出力に近い)一方 GT は {len(gt_labels)} クラスに分布"
        )

    # シグナル3: supreme 出力語彙 ⊄ supreme v1.4 語彙集合(配線ミスの決定的証拠)。
    if pred_outside_vocab:
        structural_signals += 1
        flags.append(
            f"supreme 出力に v1.4 語彙集合外のラベル {pred_outside_vocab!r}(配線/語彙の構造ミス)"
        )

    # シグナル3b: supreme の出力語彙被覆率が低い(GT 語彙の半分未満しか出力しない)
    #   → 多数クラスを構造的に出せていない(閾値ズレでは説明困難)=構造寄り。
    coverage_ratio = (len(pred_labels & gt_labels) / len(gt_labels)) if gt_labels else 0.0
    if len(gt_labels) >= 4 and coverage_ratio < 0.50:
        structural_signals += 1
        flags.append(
            f"supreme は GT {len(gt_labels)} クラス中 {len(pred_labels & gt_labels)} クラスしか"
            f"出力せず、語彙被覆率 {coverage_ratio:.0%}(過半クラスを構造的に出せていない"
            f"= 閾値ズレでは説明困難)"
        )

    # シグナル4: 語彙が概ね共有・予測が分散している → 未チューニング寄り。
    shared_ratio = (len(st.shared()) / len(gt_labels)) if gt_labels else 0.0
    if shared_ratio >= 0.66 and pred_concentration < 0.90 and missed_mass < 0.50:
        tuning_signals += 1
        flags.append(
            f"GT 語彙の {shared_ratio:.0%} を supreme も出力し、予測も特定クラスへ"
            f"潰れていない(最頻集中 {pred_concentration:.0%})→ 語彙空間は一致"
        )

    # 総合判定。
    if structural_signals >= 1 and structural_signals > tuning_signals:
        verdict = "(A) 語彙/配線の構造ミス寄り"
    elif tuning_signals >= 1 and structural_signals == 0:
        verdict = "(B) 係数の未チューニング寄り"
    else:
        verdict = "(混在/要精査) 構造シグナルとチューニングシグナルが拮抗"

    return {
        "verdict": verdict,
        "flags": flags,
        "missed_mass": missed_mass,
        "pred_concentration": pred_concentration,
        "gt_concentration": gt_concentration,
        "mc_pred": (mc_pred_label, mc_pred_n),
        "mc_gt": (mc_gt_label, mc_gt_n),
        "gt_only": sorted(gt_only),
        "pred_only": sorted(pred_only),
        "pred_outside_vocab": pred_outside_vocab,
        "structural_signals": structural_signals,
        "tuning_signals": tuning_signals,
    }


# ===========================================================================
# レポート生成
# ===========================================================================

def render_report(*, dirs, dir_to_sid, stats, diagnoses, supreme_vocab):
    now = datetime.datetime.now()
    stamp = now.strftime("%Y-%m-%d %H:%M")
    lines = []
    a = lines.append

    a("# 弱3層 誤り診断レポート — t3_hypothesis / scene_regime / quality_regime")
    a("")
    a(f"- 生成時刻: {stamp}")
    a(f"- 対象シナリオ: {len(dirs)} 件")
    a("- 経路: run_dev_eval と同一(PSO→core.run_supreme→v1.4 view、GT→ADR0006 正準化→v1.4 gt view)")
    a("- 正準化・データ対応ロジックは `run_dev_eval.py` を再利用(二重実装なし)")
    a("- supreme 本体・テストは未変更(診断のみ)。baseline は import していない。決定的。")
    a("")
    a("> 注: これは in-sample(v021_core)診断。最終 verdict ではなく構造原因の切り分けが目的。")
    a("")

    # ----- エグゼクティブサマリ -----
    a("## 結論サマリ(各層の切り分け)")
    a("")
    a("| 層 | acc | GT語彙数 | supreme出力語彙数 | 混同の型 | 判定 |")
    a("|---|---:|---:|---:|---|---|")
    for layer in TARGET_LAYERS:
        st = stats[layer]
        dg = diagnoses[layer]
        conf_type = _confusion_type_short(st)
        a(f"| {layer} | {st.acc():.4f} | {len(st.gt_vocab())} | {len(st.pred_vocab())} "
          f"| {conf_type} | {dg['verdict']} |")
    a("")

    # ----- 各層詳細 -----
    for layer in TARGET_LAYERS:
        st = stats[layer]
        dg = diagnoses[layer]
        a(f"## {layer}")
        a("")
        a(f"- 採点フレーム数(GT 非 null): {st.n_scored} / 正答 {st.n_correct} "
          f"→ acc = **{st.acc():.4f}**")
        a("")

        # --- 1. 語彙集合の対照 ---
        a("### 1. 語彙集合の対照(構造ミス検出)")
        a("")
        a("**GT 側に出現する v1.4 ラベル集合と頻度:**")
        a("")
        a("| GT ラベル | 頻度 |")
        a("|---|---:|")
        for lbl, n in st.gt_counts.most_common():
            a(f"| `{lbl}` | {n} |")
        a("")
        a("**supreme 側が出力する v1.4 ラベル集合と頻度(GT 採点対象フレーム上):**")
        a("")
        a("| supreme ラベル | 頻度 |")
        a("|---|---:|")
        for lbl, n in st.pred_counts.most_common():
            a(f"| `{lbl}` | {n} |")
        a("")
        a("**集合の食い違い:**")
        a("")
        gt_only = st.gt_only()
        pred_only = st.pred_only()
        if gt_only:
            a(f"- ⚠️ GT に出るが supreme が **一度も出さない**ラベル: "
              f"{_fmt_labels_with_freq(gt_only, st.gt_counts)}")
        else:
            a("- GT に出るが supreme が出さないラベル: なし")
        if pred_only:
            a(f"- ⚠️ supreme が出すが GT に **無い**ラベル: "
              f"{_fmt_labels_with_freq(pred_only, st.pred_counts)}")
        else:
            a("- supreme が出すが GT に無いラベル: なし")
        a(f"- 共有ラベル: {sorted(st.shared())!r}")
        if dg["pred_outside_vocab"]:
            a(f"- ⚠️ supreme 出力に v1.4 語彙集合外のラベル: {dg['pred_outside_vocab']!r}")
        else:
            a(f"- supreme 出力は supreme v1.4 語彙集合 {sorted(supreme_vocab[layer])!r} に収束(配線健全)")
        a("")

        # --- 2. 混同行列 ---
        a("### 2. 混同行列(GT 行 → supreme 予測 列)")
        a("")
        a(_render_confusion(st))
        a("")

        # --- 3. シナリオ別精度 ---
        a("### 3. シナリオ別精度(20 シナリオ)")
        a("")
        a("| dir | scenario_id | 採点数 | 正答 | acc |")
        a("|---|---|---:|---:|---:|")
        for d in dirs:
            sid = dir_to_sid[d]
            tot = st.scenario_total.get(sid, 0)
            cor = st.scenario_correct.get(sid, 0)
            acc = (cor / tot) if tot else float("nan")
            acc_s = f"{acc:.3f}" if tot else "n/a"
            flag = " ⚠️" if (tot and acc == 0.0) else ""
            a(f"| {d} | {sid} | {tot} | {cor} | {acc_s}{flag} |")
        # 最悪シナリオ(acc=0 群)を強調。
        zero_scen = [dir_to_sid[d] for d in dirs
                     if st.scenario_total.get(dir_to_sid[d], 0)
                     and st.scenario_correct.get(dir_to_sid[d], 0) == 0]
        a("")
        if zero_scen:
            a(f"- **acc=0 の致命的シナリオ**: {zero_scen!r}")
        else:
            a("- acc=0 の致命的シナリオ: なし")
        a("")

        # --- 4. 最頻ラベル(定数出力チェック) ---
        a("### 4. 最頻ラベル(定数出力に潰れていないか)")
        a("")
        mc_gt = dg["mc_gt"]
        mc_pred = dg["mc_pred"]
        a(f"- GT 最頻ラベル: `{mc_gt[0]}`（{mc_gt[1]} / {st.n_scored} = "
          f"{dg['gt_concentration']:.0%}）")
        a(f"- supreme 予測最頻ラベル: `{mc_pred[0]}`（{mc_pred[1]} / {st.n_scored} = "
          f"{dg['pred_concentration']:.0%}）")
        if dg["pred_concentration"] >= 0.90:
            a(f"- ⚠️ supreme 予測が単一クラスに {dg['pred_concentration']:.0%} 集中 = ほぼ定数出力")
        a("")

        # --- 5. 層の判定 ---
        a("### 5. 判定(構造ミス A か 未チューニング B か)")
        a("")
        a(f"**判定: {dg['verdict']}**")
        a("")
        a("根拠:")
        for f in dg["flags"]:
            a(f"- {f}")
        a("")

    # ----- 横断的な最重要結論 -----
    a("## 横断的な最重要結論")
    a("")
    for layer in TARGET_LAYERS:
        dg = diagnoses[layer]
        a(f"- **{layer}**: {dg['verdict']}")
    a("")
    a("> 判定は観測した語彙集合・混同・集中度のみから導いた(数字の捏造なし)。"
      "in-sample のため絶対値は楽観方向に歪み得るが、語彙不一致・定数潰れの有無は"
      "in-sample でも構造の問題を示す。")
    a("")

    a("---")
    a("")
    a("_本レポートは supreme.* 公開 API(core)と run_dev_eval の正準化ロジックのみで生成"
      "(baseline 非 import・supreme 本体未変更・決定的)。_")
    a("")

    return "\n".join(lines)


def _fmt_labels_with_freq(labels, counter):
    return ", ".join(f"`{lbl}`(×{counter[lbl]})" for lbl in sorted(labels))


def _confusion_type_short(st):
    """混同の型(特定クラス偏り or 分散)を短文で返す。"""
    n_scored = st.n_scored
    if not n_scored:
        return "n/a"
    mc_label, mc_n = st.most_common_pred()
    conc = mc_n / n_scored
    if conc >= 0.90:
        return f"定数潰れ('{mc_label}'へ {conc:.0%})"
    if conc >= 0.60:
        return f"特定クラス偏り('{mc_label}'へ {conc:.0%})"
    return f"分散(最頻 '{mc_label}' {conc:.0%})"


def _render_confusion(st):
    """混同行列を Markdown 表で描く(GT 行 → 予測 列)。"""
    gt_labels = sorted(st.gt_vocab())
    pred_labels = sorted(st.pred_vocab())
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
            # 対角(正答)は強調。
            cells.append(f"**{c}**" if (g == p and c) else (str(c) if c else "·"))
        rows.append(f"| `{g}` | " + " | ".join(cells) + f" | {row_total} |")
    return "\n".join(rows)


# ===========================================================================
# 標準出力サマリ
# ===========================================================================

def print_stdout_summary(stats, diagnoses, supreme_vocab):
    print()
    print("=" * 72)
    print("弱3層 誤り診断サマリ(標準出力)")
    print("=" * 72)
    for layer in TARGET_LAYERS:
        st = stats[layer]
        dg = diagnoses[layer]
        print()
        print(f"[{layer}]  acc={st.acc():.4f}  採点={st.n_scored}")
        print(f"  GT 語彙({len(st.gt_vocab())}):     {dict(st.gt_counts.most_common())}")
        print(f"  supreme 語彙({len(st.pred_vocab())}): {dict(st.pred_counts.most_common())}")
        if st.gt_only():
            print(f"  [!] GT のみ(supreme 非出力): {sorted(st.gt_only())}")
        if st.pred_only():
            print(f"  [!] supreme のみ(GT に無い): {sorted(st.pred_only())}")
        if dg["pred_outside_vocab"]:
            print(f"  [!] v1.4 語彙集合外の出力: {dg['pred_outside_vocab']}")
        print(f"  GT 最頻={dg['mc_gt'][0]} ({dg['gt_concentration']:.0%}) / "
              f"supreme 最頻={dg['mc_pred'][0]} ({dg['pred_concentration']:.0%})")
        # acc=0 シナリオ。
        zero = [sid for sid in st.scenario_total
                if st.scenario_total[sid] and st.scenario_correct.get(sid, 0) == 0]
        if zero:
            print(f"  acc=0 シナリオ: {sorted(zero)}")
        print(f"  → 判定: {dg['verdict']}")
    print()
    print("=" * 72)


# ===========================================================================
# メイン
# ===========================================================================

def run(pso_dir, gt_dir, out_path):
    print(f"[1/4] データ読み込み(run_dev_eval 経路を再利用)")
    print(f"      PSO={pso_dir}")
    print(f"      GT ={gt_dir}")
    views_by_sid, gt_by_sid, dir_to_sid, dirs = load_views_and_gt(pso_dir, gt_dir)
    total_frames = sum(len(v) for v in views_by_sid.values())
    print(f"      共通シナリオ {len(dirs)} 件・総フレーム {total_frames}・決定性 OK・GT 正準化 OK")

    print(f"[2/4] 弱3層 {TARGET_LAYERS} の統計を集計します")
    stats = collect_stats(views_by_sid, gt_by_sid, TARGET_LAYERS)

    print(f"[3/4] 各層の構造ミス/未チューニング切り分けを判定します")
    supreme_vocab = dev._V14_VOCAB
    diagnoses = {layer: diagnose_layer(stats[layer], supreme_vocab[layer])
                 for layer in TARGET_LAYERS}

    print(f"[4/4] レポートを書き出します: {out_path}")
    report_md = render_report(
        dirs=dirs, dir_to_sid=dir_to_sid, stats=stats,
        diagnoses=diagnoses, supreme_vocab=supreme_vocab,
    )
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report_md)
    print(f"      出力完了: {out_path}")

    print_stdout_summary(stats, diagnoses, supreme_vocab)
    return stats, diagnoses


def main():
    parser = argparse.ArgumentParser(
        description="弱3層(t3_hypothesis/scene_regime/quality_regime)の誤り診断ランナー"
    )
    parser.add_argument("--pso-dir", default=dev.DEFAULT_PSO_DIR,
                        help=f"PSO 入力ディレクトリ(既定: {dev.DEFAULT_PSO_DIR})")
    parser.add_argument("--gt-dir", default=dev.DEFAULT_GT_DIR,
                        help=f"GT ディレクトリ(既定: {dev.DEFAULT_GT_DIR})")
    parser.add_argument("--out", default=None,
                        help="出力 Markdown パス(既定: reports/dev-eval-diagnose-<YYYYMMDD-HHMM>.md)")
    args = parser.parse_args()

    out_path = args.out
    if out_path is None:
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M")
        out_path = os.path.join(dev.DEFAULT_OUT_DIR, f"dev-eval-diagnose-{stamp}.md")

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
