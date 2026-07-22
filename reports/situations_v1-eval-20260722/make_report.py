"""results.json → README.md（報告）と ADR 用テーブル片を生成する(F-015)。

数値は results.json をそのまま写して齟齬を防ぐ。決定的（乱数・時刻なし）。
使い方: python make_report.py   （同ディレクトリの results.json を読む）
"""
import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
LAYERS = ["risk_tier", "t1_state", "t2_mode", "t2_role",
          "t2_relation", "t3_hypothesis", "quality_regime", "scene_regime"]
SUITES = ["std", "emg", "crw", "bst", "dcp", "crp"]
CONFIG_ORDER = ["N1", "N2", "N3", "N3-std"]


def fmt(x):
    if x is None:
        return "—"
    if isinstance(x, float):
        return f"{x:.4f}"
    return str(x)


def load():
    with open(os.path.join(_HERE, "results.json"), encoding="utf-8") as f:
        return json.load(f)


def rejection_block(meta):
    lines = []
    re = meta["rejection_eval"]
    rt = meta["rejection_train_informational"]
    lines.append("## rejection_acc（EVALUATION.md §7・明示拒否＝preflight が契約違反を検出）\n")
    lines.append(f"- **eval 側（公式）**: {re['rejected']}/{re['total']} = "
                 f"**{fmt(re['rejection_acc'])}**  内訳 {re['by_reason']}")
    lines.append(f"- train 側（情報）: {rt['rejected']}/{rt['total']} = "
                 f"{fmt(rt['rejection_acc'])}  内訳 {rt['by_reason']}\n")
    lines.append("| split | sid | rejected | reason |")
    lines.append("|---|---|:--:|---|")
    for d in re["detail"]:
        lines.append(f"| eval | {d['sid']} | {'✓' if d['rejected'] else '✗'} | {d['reason']} |")
    for d in rt["detail"]:
        lines.append(f"| train | {d['sid']} | {'✓' if d['rejected'] else '✗'} | {d['reason']} |")
    return "\n".join(lines)


def pooled_table(cfgs):
    lines = ["## pooled 8 層 global acc（eval・非違反 235 本・strict OFF・2026-07-22）\n"]
    header = "| layer | " + " | ".join(CONFIG_ORDER) + " |"
    sep = "|---|" + "|".join([":--:"] * len(CONFIG_ORDER)) + "|"
    lines.append(header)
    lines.append(sep)
    for ly in LAYERS:
        row = [ly]
        for c in CONFIG_ORDER:
            v = cfgs.get(c, {}).get("eval", {}).get("pooled", {}).get("layers", {}).get(ly)
            row.append(fmt(v))
        lines.append("| " + " | ".join(row) + " |")
    row = ["**8層平均**"]
    for c in CONFIG_ORDER:
        v = cfgs.get(c, {}).get("eval", {}).get("pooled", {}).get("overall")
        row.append("**" + fmt(v) + "**")
    lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def per_suite_overall_table(cfgs):
    lines = ["## per-suite overall（eval・非違反）\n"]
    header = "| suite | " + " | ".join(CONFIG_ORDER) + " |"
    sep = "|---|" + "|".join([":--:"] * len(CONFIG_ORDER)) + "|"
    lines.append(header)
    lines.append(sep)
    for s in SUITES:
        row = [s]
        for c in CONFIG_ORDER:
            v = cfgs.get(c, {}).get("eval", {}).get("per_suite", {}).get(s, {}).get("overall")
            row.append(fmt(v))
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def config_layer_table(cfg, name):
    lines = [f"### {name} — per-suite × per-layer acc\n"]
    header = "| suite | " + " | ".join(LAYERS) + " | overall |"
    sep = "|---|" + "|".join([":--:"] * (len(LAYERS) + 1)) + "|"
    lines.append(header)
    lines.append(sep)
    ps = cfg.get("eval", {}).get("per_suite", {})
    for s in SUITES:
        if s not in ps:
            continue
        row = [s]
        for ly in LAYERS:
            row.append(fmt(ps[s]["layers"].get(ly)))
        row.append(fmt(ps[s]["overall"]))
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def timings_table(cfgs):
    lines = ["## timings（秒・metadata・決定性採点には非関与）\n"]
    lines.append("| config | train scen | fit s | eval s | crashes | det.identical |")
    lines.append("|---|:--:|:--:|:--:|:--:|:--:|")
    for c in CONFIG_ORDER:
        cfg = cfgs.get(c)
        if not cfg:
            continue
        fit = cfg.get("fit", {})
        ev = cfg.get("eval", {})
        det = cfg.get("determinism", {})
        lines.append(f"| {c} | {fit.get('train_scenarios')} | "
                     f"{fmt(fit.get('seconds'))} | {fmt(ev.get('seconds'))} | "
                     f"{cfg.get('n_crash_incidents')} | {det.get('identical')} |")
    return "\n".join(lines)


def guard_note(cfgs):
    lines = ["## T2 手配線の ≥ガード（学習 vs 事前重み・最大400練習シナリオ）\n"]
    for c in ("N3", "N3-std"):
        cfg = cfgs.get(c)
        if not cfg:
            continue
        g = cfg.get("fit", {}).get("t2_guard")
        choice = cfg.get("fit", {}).get("t2_choice")
        if g:
            lines.append(f"- {c}: 学習 acc={fmt(g.get('acc_tuned'))} / 事前 acc="
                         f"{fmt(g.get('acc_default'))} → 採用={choice}")
    return "\n".join(lines)


def main():
    d = load()
    meta = d["meta"]
    cfgs = d["configs"]
    out = []
    out.append("# situations_v1 能力評価（supreme8 / F-015）— 2026-07-22\n")
    out.append(
        "world-first 生成の situations_v1（std/emg/crw/bst/dcp/crp・各 train80/eval40）で "
        "supreme8（NeuPSL エンジン）を評価した報告。**strict OFF 必須**（ADR 0049/0050）で実走し、"
        "契約違反入力は engine 実行前に明示拒否（rejection_acc）した。`src/supreme/*.py` は無変更"
        "（アダプタ規約=ADR 0058）。\n")
    out.append("> ⚠️ **coverage 系スコアと直接比較しない（別土俵）**。引用は必ず "
               "「suite＋split＋測定日（2026-07-22）」を併記すること（README §6）。\n")
    out.append("## メタ\n")
    out.append(f"- 測定日: **{meta['measurement_date']}** / strict_gt_conformance: "
               f"**{meta['strict_gt_conformance']}**")
    out.append(f"- データ root: `{meta['data_root']}`")
    out.append(f"- データ repo HEAD: `{meta['data_repo_head']}`")
    out.append(f"- エンジン repo HEAD: `{meta['engine_repo_head']}`")
    c = meta["counts"]
    out.append(f"- 列挙: train {c['train_total']}（違反 {c['train_violation']}）/ "
               f"eval {c['eval_total']}（違反 {c['eval_violation']}）。"
               f"非違反 eval {c['eval_nonviolation']} 本を採点。\n")
    out.append("## 構成\n")
    for name in CONFIG_ORDER:
        if name in cfgs:
            out.append(f"- **{name}**: {cfgs[name]['description']}")
    out.append("")
    out.append(rejection_block(meta))
    out.append("")
    out.append(pooled_table(cfgs))
    out.append("")
    out.append(per_suite_overall_table(cfgs))
    out.append("")
    for name in CONFIG_ORDER:
        if name in cfgs:
            out.append(config_layer_table(cfgs[name], name))
            out.append("")
    out.append(guard_note(cfgs))
    out.append("")
    out.append(timings_table(cfgs))
    out.append("")
    # crashes
    total_crash = sum(cfgs[c].get("n_crash_incidents", 0) for c in cfgs)
    out.append("## crash incidents（堅牢性の所見・採点分母には非算入）\n")
    if total_crash == 0:
        out.append("- **0 件**（全 config で非違反 235 本が例外なく実走）。\n")
    else:
        out.append(f"- 合計 **{total_crash} 件**。詳細は results.json の各 config "
                   "`crash_incidents` を参照。\n")
    out.append("## 正直な注記\n")
    out.append("- **relation の語彙ギャップ**: departing/unrelated が relation ラベルの約 48% を占め、"
               "現特徴（t1_depart・距離）では分離が不十分（ADR 0057 の既知挙動でありバグではない）。")
    out.append("- **dcp/crp の設計意図**: dcp は「観測が嘘をつく」罠（media 音の role は source_object・"
               "risk 不上昇）、crp は破損下の Safety Latch。低めの値は設計意図で天井は構造的に 1.0 未満"
               "（README §0/§6）。")
    out.append("- **coverage 比較禁止**: 本スイートは world-first 土俵。coverage_v3 の 0.6879 等と"
               "同一スケールで比較しない。")
    out.append("- **モチーフ有限性**: train/eval は同一 50 モチーフの別パラメタ。最終確定（seal）には"
               "完全新作モチーフが必要（README §10）。能力主張には独立ラベラ照合の併記が要る。\n")
    out.append("---\n")
    out.append("生成元: `run_supreme_situations.py` → `results.json` → `make_report.py`。"
               "数値は results.json を機械転記。\n")

    text = "\n".join(out)
    with open(os.path.join(_HERE, "README.md"), "w", encoding="utf-8") as f:
        f.write(text)
    print("wrote README.md")


if __name__ == "__main__":
    main()
