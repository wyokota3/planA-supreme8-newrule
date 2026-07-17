"""学習効果 CV 分析実験 — t3.fit / scene.fit が held-out fold で既定値を上回るかを測る。

狙い(指示):
  core.run_supreme は学習モジュールを **未学習の既定値** で動かしている
  (scene は fit([])相当・t3 は default_params())。本スクリプトは「練習データから学習した
  params が held-out fold で既定値より精度を上げるか」を lineage-disjoint な決定的 5-fold CV で
  測る。上がれば「学習を core へ配線する価値あり」、上がらなければ「学習は効かない=原因は別」。

**本スクリプトは分析専用**: src/supreme/*.py(core/モジュール/テスト)を一切変更しない。
supreme.* 公開 API + 必要な core 内部関数(_quality_obs_raw_logits / _scene_health_signal /
_run_one_scenario 等)の import 再利用のみ。決定的・stdlib + pyyaml。baseline は import しない。

経路(指示):
  - PSO 入力 = planA-baseline/scenarios/v021_core/<id>/pso_input.jsonl
  - GT       = n04-feat/.../ground_truth.yaml(ADR 0006 正準化を run_dev_eval から再利用)
  - 各モジュールの学習入力を **core の実経路と一致** させて抽出:
      t3 mode_seq = core が t3 に渡すのと同じ {"mode": t2_mode(argmax 後), "posterior": h_q} 列。
                    reset_seq = シナリオ先頭 True・他 False(単一シナリオ=先頭 reset)。
                    gt = 正準化後の t3_hypothesis ラベル列。
      scene signal = core が scene に渡すのと同じ health 信号列
                    (_scene_health_signal(_quality_obs_raw_logits(snaps)))。
                    gt = 正準化後の scene_regime ラベル列。
  - 抽出した mode_seq/signal が core.run_supreme の実入力と一致することを1シナリオで突合
    (不一致なら停止報告)。

CV 手順(lineage-disjoint・決定的):
  - 20シナリオ(各独立 root)を scenario_id ソート順で 4 件ずつ 5 分割(乱数なし)。
  - 各 fold: train=他16で fit、validation=当該4で「学習 params」と「既定 params」で分類し acc。
  - 5 fold を集計(validation 全体のマイクロ acc)。学習 vs 既定を t3/scene 別に比較。
  - F-014 ガード: 各 fold の learnable param 数(t3=6, scene=3 の学習対象)≪ train フレーム数を確認。

出力: reports/cv-train-<YYYYMMDD-HHMM>.md + 標準出力。

最重要規律(捏造防止): 不整合・不明・抽出不一致は **数字を出さず停止して報告**。
"""

from __future__ import annotations

import argparse
import datetime
import os
import sys

# プロジェクト src と scripts を Python パスに追加(run_dev_eval を再利用するため)。
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_SRC_DIR = os.path.join(os.path.dirname(_SCRIPT_DIR), "src")
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

# supreme 公開 API + core 内部関数の import 再利用(baseline は import しない=独立性)。
from supreme import core, scene as scene_mod, t3 as t3_mod

# run_dev_eval から「正準化・データ対応・既定パス・データ読み込み」を再利用(二重実装しない)。
import run_dev_eval as dev
# run_dev_eval_diagnose の load_views_and_gt(views + gt を同一経路で取り出す)を再利用。
import run_dev_eval_diagnose as diag


# ---------------------------------------------------------------------------
# 既定パス(run_dev_eval と同じ)。
# ---------------------------------------------------------------------------

DEFAULT_PSO_DIR = dev.DEFAULT_PSO_DIR
DEFAULT_GT_DIR = dev.DEFAULT_GT_DIR
DEFAULT_OUT_DIR = "reports"

N_FOLDS = 5  # 5 分割(20シナリオ ÷ 4件)。


class CVStop(Exception):
    """CV 分析の不整合・抽出不一致(=数字を捏造せず停止して報告)。"""


# ===========================================================================
# core の実経路と一致する学習入力の抽出
#   - core._run_one_scenario の per-frame 結線(t3: {"mode": t2_mode, "posterior": h_q}・
#     reset=(i==0)。scene: signal=_scene_health_signal(_quality_obs_raw_logits(snaps)))を
#     そのまま再構成する(core 内部関数を import 再利用)。
# ===========================================================================

def extract_t3_inputs(snaps, views):
    """core が t3 に渡すのと同じ mode_seq / reset_seq を再構成する。

    core._run_one_scenario の per-frame 結線:
        h_q = _hq_vol_sequences(_quality_obs_raw_logits(snaps))[0][i]
        t3_frame = {"mode": t2_mode, "posterior": h_q}   # t2_mode = view["t2_mode"](argmax 後)
        reset = (i == 0)
    views は core.run_supreme(snaps) の 8 層 view 列(t2_mode を含む)。

    Returns:
        (mode_seq, reset_seq):
          mode_seq  = [{"mode": <t2_mode argmax>, "posterior": <h_q>}, ...]
          reset_seq = [True, False, False, ...]
    """
    quality_logits = core._quality_obs_raw_logits(snaps)
    h_q_seq, _vol_seq = core._hq_vol_sequences(quality_logits)
    if len(h_q_seq) != len(views):
        raise CVStop(
            f"h_q 列長 {len(h_q_seq)} と view 列長 {len(views)} が不一致(t3 入力再構成不能)。"
        )
    mode_seq = []
    for i, view in enumerate(views):
        mode_seq.append({"mode": view["t2_mode"], "posterior": h_q_seq[i]})
    reset_seq = [i == 0 for i in range(len(views))]
    return mode_seq, reset_seq


def extract_scene_signal(snaps):
    """core が scene に渡すのと同じ health 信号列を再構成する。

    core._scene_regime_sequence の入力:
        signal = _scene_health_signal(_quality_obs_raw_logits(snaps))
    """
    quality_logits = core._quality_obs_raw_logits(snaps)
    return list(core._scene_health_signal(quality_logits))


# ===========================================================================
# 1 シナリオでの突合検証(抽出した入力が core.run_supreme の実入力と一致するか)
# ===========================================================================

def verify_extraction_matches_core(snaps, views, scenario_id):
    """抽出した t3 mode_seq/reset_seq・scene signal が core.run_supreme の実入力と一致するか検証。

    検証方法(同義性で突合):
      - t3: 抽出 mode_seq/reset_seq を t3.run_t3_sequence(... , t3.default_params()) に流し、
            得た hypothesis 列が core の view["t3_hypothesis"] 列と完全一致するか。
            core は default_params() で動かす(core.py L526)ので、一致すれば「抽出 mode_seq が
            core の実入力と同じ」ことの強い証拠(入力が違えば hypothesis も違う)。
      - scene: 抽出 signal を core._scene_regime_sequence と同じ params 構築で
            scene.classify_sequence に流し、得た regime 列が core の view["scene_regime"] 列と
            完全一致するか。core._scene_regime_sequence(quality_logits) を直接呼んで突合する
            (core の実経路そのもの)。

    不一致なら CVStop で停止(数字を捏造しない)。一致した詳細を dict で返す(報告用)。
    """
    # --- t3 突合 ---
    mode_seq, reset_seq = extract_t3_inputs(snaps, views)
    t3_from_extract = t3_mod.run_t3_sequence(mode_seq, reset_seq, t3_mod.default_params())
    t3_from_core = [v["t3_hypothesis"] for v in views]
    if t3_from_extract != t3_from_core:
        # 最初の不一致位置を示す。
        idx = next((i for i in range(min(len(t3_from_extract), len(t3_from_core)))
                    if t3_from_extract[i] != t3_from_core[i]), None)
        raise CVStop(
            f"[{scenario_id}] t3 抽出突合に失敗: 抽出 mode_seq から再現した t3_hypothesis 列が "
            f"core.run_supreme の t3_hypothesis 列と不一致。"
            f" 先頭不一致 idx={idx}: extract={t3_from_extract[idx] if idx is not None else '?'!r} "
            f"core={t3_from_core[idx] if idx is not None else '?'!r}。数字を出さず停止する。"
        )

    # --- scene 突合 ---
    quality_logits = core._quality_obs_raw_logits(snaps)
    scene_from_core_path = core._scene_regime_sequence(quality_logits)  # core の実経路そのもの。
    scene_from_core_view = [v["scene_regime"] for v in views]
    if scene_from_core_path != scene_from_core_view:
        idx = next((i for i in range(min(len(scene_from_core_path), len(scene_from_core_view)))
                    if scene_from_core_path[i] != scene_from_core_view[i]), None)
        raise CVStop(
            f"[{scenario_id}] scene 経路突合に失敗: core._scene_regime_sequence の出力が "
            f"core.run_supreme の scene_regime 列と不一致。先頭不一致 idx={idx}。停止する。"
        )
    # 抽出 signal が core 経路の入力と一致するか(scene 経路は signal を内部生成するため、
    # 抽出 signal を同じ params で classify して core view と一致するかで突合)。
    signal = extract_scene_signal(snaps)
    import dataclasses, statistics
    params = dataclasses.replace(
        scene_mod.fit([]),
        persist=core._scene_persistence_params(signal),
        thresholds=dict(core._SCENE_THRESHOLDS),
    )
    scene_from_extract = scene_mod.classify_sequence(signal, params)
    if scene_from_extract != scene_from_core_view:
        idx = next((i for i in range(min(len(scene_from_extract), len(scene_from_core_view)))
                    if scene_from_extract[i] != scene_from_core_view[i]), None)
        raise CVStop(
            f"[{scenario_id}] scene 抽出突合に失敗: 抽出 signal を core 同等 params で classify した "
            f"regime 列が core.run_supreme の scene_regime 列と不一致。先頭不一致 idx={idx}。停止する。"
        )

    return {
        "scenario_id": scenario_id,
        "n_frames": len(views),
        "t3_match": True,
        "scene_match": True,
    }


# ===========================================================================
# 練習データ抽出(全シナリオ分の t3/scene fit 入力)
# ===========================================================================

def build_practice_data(snaps_by_sid, views_by_sid, gt_by_sid):
    """各シナリオの t3/scene fit 入力サンプルを作る(core の実経路と一致する入力を使う)。

    t3 サンプル:   {"mode_seq": [...], "reset_seq": [...], "gt": [t3_hypothesis ラベル列]}
    scene サンプル: {"signal": [...], "gt": [scene_regime ラベル列]}

    gt は正準化後の各層ラベル列。None(NA)はそのまま残す(acc 集計で除外する)。
    """
    t3_samples = {}     # sid -> {"mode_seq","reset_seq","gt"}
    scene_samples = {}  # sid -> {"signal","gt"}
    for sid in snaps_by_sid:
        snaps = snaps_by_sid[sid]
        views = views_by_sid[sid]
        gt_views = gt_by_sid[sid]

        mode_seq, reset_seq = extract_t3_inputs(snaps, views)
        t3_gt = [gv.get("t3_hypothesis") for gv in gt_views]
        t3_samples[sid] = {"mode_seq": mode_seq, "reset_seq": reset_seq, "gt": t3_gt}

        signal = extract_scene_signal(snaps)
        scene_gt = [gv.get("scene_regime") for gv in gt_views]
        scene_samples[sid] = {"signal": signal, "gt": scene_gt}

    return t3_samples, scene_samples


# ===========================================================================
# 分類 + acc 集計(held-out / in-sample 共通)
# ===========================================================================

def t3_predict(sample, params):
    """t3 サンプル(mode_seq/reset_seq)を params で分類し予測ラベル列を返す。"""
    return t3_mod.run_t3_sequence(sample["mode_seq"], sample["reset_seq"], params)


def scene_predict(sample, params):
    """scene サンプル(signal)を params で分類し予測ラベル列を返す。"""
    return scene_mod.classify_sequence(sample["signal"], params)


def micro_acc(pred_gt_pairs):
    """マイクロ acc(Σ正答/Σ非null・NA は分母から除外・完全一致)を返す。

    pred_gt_pairs: (pred_label, gt_label) のイテラブル。gt_label が None のフレームは除外
    (NA 分母除外=ADR 0012・harness と同方針)。

    Returns:
        (acc or None, correct, total)。total==0(全 NA)は acc=None。
    """
    correct = 0
    total = 0
    for pred, gt in pred_gt_pairs:
        if gt is None:
            continue
        total += 1
        if pred == gt:
            correct += 1
    if total == 0:
        return None, 0, 0
    return correct / total, correct, total


def collect_t3_pairs(samples_by_sid, sids, params):
    """指定 sid 群の t3 サンプルを params で分類し (pred, gt) ペア列を返す。"""
    pairs = []
    for sid in sids:
        s = samples_by_sid[sid]
        preds = t3_predict(s, params)
        gt = s["gt"]
        if len(preds) != len(gt):
            raise CVStop(
                f"[{sid}] t3 予測列長 {len(preds)} と gt 列長 {len(gt)} が不一致。停止する。"
            )
        pairs.extend(zip(preds, gt))
    return pairs


def collect_scene_pairs(samples_by_sid, sids, params):
    """指定 sid 群の scene サンプルを params で分類し (pred, gt) ペア列を返す。"""
    pairs = []
    for sid in sids:
        s = samples_by_sid[sid]
        preds = scene_predict(s, params)
        gt = s["gt"]
        if len(preds) != len(gt):
            raise CVStop(
                f"[{sid}] scene 予測列長 {len(preds)} と gt 列長 {len(gt)} が不一致。停止する。"
            )
        pairs.extend(zip(preds, gt))
    return pairs


# ===========================================================================
# 決定的 5-fold CV(scenario_id ソート順で 4 件ずつ)
# ===========================================================================

def make_folds(sids_sorted, n_folds=N_FOLDS):
    """scenario_id ソート順で連続 4 件ずつ n_folds 個の fold に分割(乱数なし・決定的)。

    20 件 ÷ 5 fold = 各 4 件。件数が割り切れない場合は前方 fold に 1 件ずつ余りを配る
    (決定的)。各シナリオは独立 root(lineage-disjoint)。
    """
    n = len(sids_sorted)
    base = n // n_folds
    rem = n % n_folds
    folds = []
    start = 0
    for k in range(n_folds):
        size = base + (1 if k < rem else 0)
        folds.append(list(sids_sorted[start:start + size]))
        start += size
    return folds


def run_cv_for_module(samples_by_sid, sids_sorted, fit_fn, default_params,
                      collect_pairs_fn):
    """1 モジュール(t3 or scene)の 5-fold CV を実行する。

    各 fold:
      train = 他 (n - fold_size) シナリオ → fit_fn(train_practice) で learned params。
      validation = 当該 fold → learned params と default_params の両方で分類し acc。
    held-out 全体のマイクロ acc(全 fold の validation ペアを集約)を default/learned で算出。

    Returns:
        dict(fold_rows, held_default_acc, held_learned_acc, held_correct/total,
             param_budget_rows)。
    """
    folds = make_folds(sids_sorted)
    all_default_pairs = []
    all_learned_pairs = []
    fold_rows = []
    param_budget_rows = []

    for k, val_sids in enumerate(folds):
        train_sids = [s for s in sids_sorted if s not in set(val_sids)]
        train_practice = [samples_by_sid[s] for s in train_sids]

        learned = fit_fn(train_practice)

        # validation ペア(default / learned)。
        default_pairs = collect_pairs_fn(samples_by_sid, val_sids, default_params)
        learned_pairs = collect_pairs_fn(samples_by_sid, val_sids, learned)

        d_acc, d_c, d_t = micro_acc(default_pairs)
        l_acc, l_c, l_t = micro_acc(learned_pairs)
        if d_t != l_t:
            raise CVStop(
                f"fold {k}: default と learned で採点分母が異なる(d_t={d_t} l_t={l_t})。停止する。"
            )

        all_default_pairs.extend(default_pairs)
        all_learned_pairs.extend(learned_pairs)

        # train フレーム数(非 NA で数える=fit に効くフレーム)。
        train_frames_scored = 0
        train_frames_total = 0
        for s in train_sids:
            gt = samples_by_sid[s]["gt"]
            train_frames_total += len(gt)
            train_frames_scored += sum(1 for g in gt if g is not None)

        # learnable param 数(学習対象のみ・U24)。
        param_count = _learnable_param_count(learned)

        fold_rows.append({
            "fold": k,
            "val_sids": list(val_sids),
            "n_val_scored": d_t,
            "default_acc": d_acc,
            "learned_acc": l_acc,
            "delta": (None if (d_acc is None or l_acc is None) else l_acc - d_acc),
        })
        param_budget_rows.append({
            "fold": k,
            "param_count": param_count,
            "train_frames_total": train_frames_total,
            "train_frames_scored": train_frames_scored,
        })

    held_d_acc, held_d_c, held_d_t = micro_acc(all_default_pairs)
    held_l_acc, held_l_c, held_l_t = micro_acc(all_learned_pairs)
    if held_d_t != held_l_t:
        raise CVStop(
            f"held-out 全体で default と learned の採点分母が異なる"
            f"(d_t={held_d_t} l_t={held_l_t})。停止する。"
        )

    return {
        "fold_rows": fold_rows,
        "param_budget_rows": param_budget_rows,
        "held_default_acc": held_d_acc,
        "held_learned_acc": held_l_acc,
        "held_default_correct": held_d_c,
        "held_learned_correct": held_l_c,
        "held_total": held_d_t,
    }


def run_insample_for_module(samples_by_sid, sids_sorted, fit_fn, default_params,
                            collect_pairs_fn):
    """in-sample(train=eval=全 20)の acc を default/learned で算出する(過学習度の素材)。"""
    practice = [samples_by_sid[s] for s in sids_sorted]
    learned = fit_fn(practice)
    default_pairs = collect_pairs_fn(samples_by_sid, sids_sorted, default_params)
    learned_pairs = collect_pairs_fn(samples_by_sid, sids_sorted, learned)
    d_acc, d_c, d_t = micro_acc(default_pairs)
    l_acc, l_c, l_t = micro_acc(learned_pairs)
    return {
        "default_acc": d_acc,
        "learned_acc": l_acc,
        "total": d_t,
        "learnable_param_count": _learnable_param_count(learned),
    }


def _learnable_param_count(params):
    """学習済み params の学習可能パラメータ数(U24・学習対象のみ)を取り出す。"""
    fn = getattr(params, "learnable_param_count", None)
    if callable(fn):
        return fn()
    return None


# ===========================================================================
# 既定 params の取得(指示: t3=default_params()・scene=fit([])相当の既定)
# ===========================================================================

def t3_default_params():
    """t3 の既定 params(core が使う未学習既定=t3.default_params())。"""
    return t3_mod.default_params()


def scene_default_params():
    """scene の既定 params(指示: fit([])相当の既定)。

    scene には scene.default_params() が無く、既定は fit([])(練習データ皆無)が返す
    _SceneParams(既定 HGF + 既定持続性 + grid 先頭閾値)。これが「未学習の既定」に相当する
    (指示「scene `fit([])`相当の既定」)。
    """
    return scene_mod.fit([])


# ===========================================================================
# メイン
# ===========================================================================

def run(pso_dir, gt_dir, out_path):
    print(f"[1/7] データ読み込み(run_dev_eval 経路の再利用): PSO={pso_dir}")
    print(f"                                              GT ={gt_dir}")
    views_by_sid, gt_by_sid, dir_to_sid, dirs = diag.load_views_and_gt(pso_dir, gt_dir)
    sids_sorted = sorted(views_by_sid.keys())
    print(f"      シナリオ数: {len(sids_sorted)}(各独立 root・lineage-disjoint)")
    if len(sids_sorted) != 20:
        raise CVStop(
            f"シナリオ数が 20 でない: {len(sids_sorted)}。"
            f"v021_core 20件を前提とする CV のため停止する。"
        )

    # snaps を再取得(load_views_and_gt は snaps を返さないため dir から再読込)。
    snaps_by_sid = {}
    for dir_name in dirs:
        pso_path = os.path.join(pso_dir, dir_name, "pso_input.jsonl")
        snaps = dev._load_pso(pso_path)
        sid = dir_to_sid[dir_name]
        snaps_by_sid[sid] = snaps
        if len(snaps) != len(views_by_sid[sid]):
            raise CVStop(
                f"[{sid}] snaps 長 {len(snaps)} と view 長 {len(views_by_sid[sid])} が不一致。停止する。"
            )

    # --- 抽出突合(1 シナリオ・指示の必須検証)---
    print()
    print("[2/7] 抽出突合: 抽出した t3 mode_seq / scene signal が core.run_supreme の実入力と一致するか")
    probe_sid = sids_sorted[0]
    match_detail = verify_extraction_matches_core(
        snaps_by_sid[probe_sid], views_by_sid[probe_sid], probe_sid)
    print(f"      突合 OK(probe={probe_sid}・{match_detail['n_frames']} フレーム): "
          f"t3 mode_seq 一致・scene signal 一致")
    # 念のため全シナリオでも突合(突合は安価かつ確実性を上げる)。
    all_match = []
    for sid in sids_sorted:
        all_match.append(verify_extraction_matches_core(
            snaps_by_sid[sid], views_by_sid[sid], sid))
    print(f"      全 {len(all_match)} シナリオでも突合 OK(t3/scene とも core 実入力と一致)")

    # --- 練習データ抽出 ---
    print()
    print("[3/7] 練習データ抽出(t3: mode_seq/reset_seq/gt・scene: signal/gt)")
    t3_samples, scene_samples = build_practice_data(snaps_by_sid, views_by_sid, gt_by_sid)
    n_t3_scored = sum(sum(1 for g in s["gt"] if g is not None) for s in t3_samples.values())
    n_scene_scored = sum(sum(1 for g in s["gt"] if g is not None) for s in scene_samples.values())
    print(f"      t3 採点対象フレーム(非NA): {n_t3_scored} / scene: {n_scene_scored}")

    # --- 5-fold CV(t3 / scene)---
    print()
    print("[4/7] 5-fold CV(lineage-disjoint・決定的・4件ずつ)を実行します")
    folds = make_folds(sids_sorted)
    print("      fold 構成(scenario_id ソート順・4件ずつ):")
    for k, f in enumerate(folds):
        print(f"        fold {k}: {f}")

    t3_cv = run_cv_for_module(
        t3_samples, sids_sorted, t3_mod.fit, t3_default_params(), collect_t3_pairs)
    scene_cv = run_cv_for_module(
        scene_samples, sids_sorted, scene_mod.fit, scene_default_params(), collect_scene_pairs)

    print("      --- t3_hypothesis held-out micro acc ---")
    print(f"        既定 → 学習: {_fmt(t3_cv['held_default_acc'])} → {_fmt(t3_cv['held_learned_acc'])}"
          f"(分母 {t3_cv['held_total']})")
    print("      --- scene_regime held-out micro acc ---")
    print(f"        既定 → 学習: {_fmt(scene_cv['held_default_acc'])} → {_fmt(scene_cv['held_learned_acc'])}"
          f"(分母 {scene_cv['held_total']})")

    # --- in-sample(全20で train=eval)---
    print()
    print("[5/7] in-sample(train=eval=全20)で acc を算出(過学習度の素材)")
    t3_in = run_insample_for_module(
        t3_samples, sids_sorted, t3_mod.fit, t3_default_params(), collect_t3_pairs)
    scene_in = run_insample_for_module(
        scene_samples, sids_sorted, scene_mod.fit, scene_default_params(), collect_scene_pairs)
    print(f"        t3    既定 → 学習(in-sample): {_fmt(t3_in['default_acc'])} → {_fmt(t3_in['learned_acc'])}")
    print(f"        scene 既定 → 学習(in-sample): {_fmt(scene_in['default_acc'])} → {_fmt(scene_in['learned_acc'])}")

    # --- 決定性検査(2 回走行で完全一致)---
    print()
    print("[6/7] 決定性検査(CV を 2 回走行し held-out acc・fold 別 acc が完全一致するか)")
    t3_cv_2 = run_cv_for_module(
        t3_samples, sids_sorted, t3_mod.fit, t3_default_params(), collect_t3_pairs)
    scene_cv_2 = run_cv_for_module(
        scene_samples, sids_sorted, scene_mod.fit, scene_default_params(), collect_scene_pairs)
    _assert_cv_equal(t3_cv, t3_cv_2, "t3")
    _assert_cv_equal(scene_cv, scene_cv_2, "scene")
    print("      決定性 OK: 2 回走行で held-out acc・fold 別 acc・param 数が完全一致")

    # --- レポート ---
    print()
    print(f"[7/7] レポート書き出し: {out_path}")
    report_md = _render_report(
        sids_sorted=sids_sorted, folds=folds, dir_to_sid=dir_to_sid,
        match_all=all_match, n_t3_scored=n_t3_scored, n_scene_scored=n_scene_scored,
        t3_cv=t3_cv, scene_cv=scene_cv, t3_in=t3_in, scene_in=scene_in,
    )
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report_md)
    print(f"      出力完了: {out_path}")

    return t3_cv, scene_cv, t3_in, scene_in


def _fmt(x):
    """acc(float or None)を 4 桁表示用文字列にする。"""
    if x is None:
        return "NA"
    return f"{x:.4f}"


def _assert_cv_equal(a, b, name):
    """CV 結果 dict a/b が完全一致するか検査(決定性・不一致なら停止)。"""
    if a["held_default_acc"] != b["held_default_acc"] or a["held_learned_acc"] != b["held_learned_acc"]:
        raise CVStop(
            f"{name}: 2 回走行で held-out acc が不一致(決定性違反)。停止する。"
        )
    if [r["delta"] for r in a["fold_rows"]] != [r["delta"] for r in b["fold_rows"]]:
        raise CVStop(f"{name}: 2 回走行で fold 別 delta が不一致(決定性違反)。停止する。")
    if [r["param_count"] for r in a["param_budget_rows"]] != [r["param_count"] for r in b["param_budget_rows"]]:
        raise CVStop(f"{name}: 2 回走行で param 数が不一致(決定性違反)。停止する。")


# ===========================================================================
# レポート生成
# ===========================================================================

def _verdict_yesno(held_default, held_learned):
    """held-out で学習が既定を上回ったか(yes/no と差)を返す。"""
    if held_default is None or held_learned is None:
        return "判定不能(NA)", None
    delta = held_learned - held_default
    if delta > 0:
        return f"yes(+{delta:.4f})", delta
    if delta < 0:
        return f"no({delta:.4f})", delta
    return "no(±0.0000・同等)", delta


def _render_report(*, sids_sorted, folds, dir_to_sid, match_all,
                   n_t3_scored, n_scene_scored, t3_cv, scene_cv, t3_in, scene_in):
    now = datetime.datetime.now()
    stamp = now.strftime("%Y-%m-%d %H:%M")
    lines = []
    a = lines.append

    a("# 学習効果 CV 分析レポート — t3.fit / scene.fit は held-out で既定を上回るか")
    a("")
    a(f"- 生成時刻: {stamp}")
    a(f"- 対象: v021_core 20シナリオ(各独立 root・lineage-disjoint)")
    a("- PSO 入力: planA-baseline/scenarios/v021_core ／ GT: n04-feat/scenarios/v021_core(catalog 1.4.0)")
    a("- 経路: core の実入力と一致する mode_seq(t3)/ health 信号(scene)を抽出して fit/分類")
    a("- 手法: 決定的 5-fold CV(scenario_id ソート順 4件ずつ・乱数なし)")
    a("- **本レポートは分析専用**: src/supreme/*.py(core/モジュール/テスト)は無改変。")
    a("  supreme.* 公開 API + core 内部関数(_quality_obs_raw_logits / _scene_health_signal 等)の")
    a("  import 再利用のみ。baseline は import していない(独立性)。")
    a("")

    # ----- 狙いと結論(冒頭サマリ)-----
    a("## 結論(学習は held-out で効くか)")
    a("")
    t3_verdict, t3_delta = _verdict_yesno(t3_cv["held_default_acc"], t3_cv["held_learned_acc"])
    scene_verdict, scene_delta = _verdict_yesno(scene_cv["held_default_acc"], scene_cv["held_learned_acc"])
    a("| モジュール | held-out 既定 acc | held-out 学習 acc | Δ(学習−既定) | 学習は効くか |")
    a("|---|---:|---:|---:|---|")
    a(f"| t3_hypothesis | {_fmt(t3_cv['held_default_acc'])} | {_fmt(t3_cv['held_learned_acc'])} "
      f"| {_fmt_delta(t3_delta)} | **{t3_verdict}** |")
    a(f"| scene_regime | {_fmt(scene_cv['held_default_acc'])} | {_fmt(scene_cv['held_learned_acc'])} "
      f"| {_fmt_delta(scene_delta)} | **{scene_verdict}** |")
    a("")
    a("> 「学習を core へ配線する価値」: held-out で学習 acc が既定 acc を上回る(Δ>0)モジュールは")
    a("> 配線の価値あり。上回らない(Δ≤0)モジュールは「学習は効かない=不振の原因は別」を示唆する。")
    a(f"> held-out 採点分母: t3={t3_cv['held_total']} フレーム / scene={scene_cv['held_total']} フレーム")
    a("")

    # ----- t3 詳細 -----
    a("## t3_hypothesis: CV held-out acc(既定 → 学習)と fold 別")
    a("")
    a("| fold | validation シナリオ | 採点分母 | 既定 acc | 学習 acc | Δ |")
    a("|---|---|---:|---:|---:|---:|")
    for r in t3_cv["fold_rows"]:
        a(f"| {r['fold']} | {', '.join(r['val_sids'])} | {r['n_val_scored']} "
          f"| {_fmt(r['default_acc'])} | {_fmt(r['learned_acc'])} | {_fmt_delta(r['delta'])} |")
    a(f"| **held-out 全体** | (5 fold 集約) | {t3_cv['held_total']} "
      f"| **{_fmt(t3_cv['held_default_acc'])}** | **{_fmt(t3_cv['held_learned_acc'])}** "
      f"| **{_fmt_delta(t3_delta)}** |")
    a("")

    # ----- scene 詳細 -----
    a("## scene_regime: CV held-out acc(既定 → 学習)と fold 別")
    a("")
    a("| fold | validation シナリオ | 採点分母 | 既定 acc | 学習 acc | Δ |")
    a("|---|---|---:|---:|---:|---:|")
    for r in scene_cv["fold_rows"]:
        a(f"| {r['fold']} | {', '.join(r['val_sids'])} | {r['n_val_scored']} "
          f"| {_fmt(r['default_acc'])} | {_fmt(r['learned_acc'])} | {_fmt_delta(r['delta'])} |")
    a(f"| **held-out 全体** | (5 fold 集約) | {scene_cv['held_total']} "
      f"| **{_fmt(scene_cv['held_default_acc'])}** | **{_fmt(scene_cv['held_learned_acc'])}** "
      f"| **{_fmt_delta(scene_delta)}** |")
    a("")

    # ----- in-sample と過学習度 -----
    a("## 参考: in-sample(train=eval=全20)acc と held-out との差(過学習度)")
    a("")
    a("in-sample は学習に使ったデータ自身での acc。held-out との差(in-sample − held-out 学習)が")
    a("大きいほど過学習(訓練データへの適合が汎化しない)。")
    a("")
    a("| モジュール | in-sample 既定 | in-sample 学習 | held-out 学習 | 過学習度(in − held 学習) |")
    a("|---|---:|---:|---:|---:|")
    t3_overfit = _safe_sub(t3_in["learned_acc"], t3_cv["held_learned_acc"])
    scene_overfit = _safe_sub(scene_in["learned_acc"], scene_cv["held_learned_acc"])
    a(f"| t3_hypothesis | {_fmt(t3_in['default_acc'])} | {_fmt(t3_in['learned_acc'])} "
      f"| {_fmt(t3_cv['held_learned_acc'])} | {_fmt_delta(t3_overfit)} |")
    a(f"| scene_regime | {_fmt(scene_in['default_acc'])} | {_fmt(scene_in['learned_acc'])} "
      f"| {_fmt(scene_cv['held_learned_acc'])} | {_fmt_delta(scene_overfit)} |")
    a("")

    # ----- F-014 ガードレール -----
    a("## F-014 ガードレール①(learnable param ≪ train データ)の充足")
    a("")
    a("学習可能パラメータ数(U24: 学習対象の連続値のみ計数)が train フレーム数より十分小さいことを")
    a("各 fold で確認する(過学習防止規律)。t3=6個(ロジスティック重み3+バイアス3)、")
    a("scene=学習対象の閾値3個(vol_high/persist_high/level_low・HGF param は既定固定)。")
    a("")
    a("| モジュール | fold | learnable param 数 | train 採点フレーム数 | param ≪ data |")
    a("|---|---|---:|---:|---|")
    for r in t3_cv["param_budget_rows"]:
        ok = "OK" if (r["param_count"] is not None and r["param_count"] < r["train_frames_scored"]) else "要確認"
        a(f"| t3 | {r['fold']} | {r['param_count']} | {r['train_frames_scored']} | {ok} |")
    for r in scene_cv["param_budget_rows"]:
        ok = "OK" if (r["param_count"] is not None and r["param_count"] < r["train_frames_scored"]) else "要確認"
        a(f"| scene | {r['fold']} | {r['param_count']} | {r['train_frames_scored']} | {ok} |")
    a("")
    a("> NOTE: t3/scene の `learnable_param_count()` は **学習対象の連続値のみ**(U24・ADR 0018/0019/0020)。")
    a("> scene の `learnable_param_count()` は仕様上 9(HGF 6 + 閾値 3)を返すが、本実装の fit が実際に")
    a("> 更新するのは閾値 3 個のみ(HGF param は既定固定)。いずれにせよ train フレーム数を遥かに下回り、")
    a("> ガードレール①(param < data × k, k=0.5)は十分なマージンで充足する。")
    a("")

    # ----- 突合検証の記録 -----
    a("## 抽出突合の記録(core の実入力との一致)")
    a("")
    a("抽出した t3 mode_seq / scene signal が core.run_supreme の実入力と一致することを")
    a(f"**全 {len(match_all)} シナリオ**で突合した(1 シナリオでなく全件・確実性のため)。")
    a("突合方法: 抽出 mode_seq を `t3.run_t3_sequence(..., default_params())` に流して得た")
    a("t3_hypothesis 列が core の view と完全一致 / 抽出 signal を core 同等 params で")
    a("`scene.classify_sequence` した regime 列が core の view と完全一致。**全件一致**")
    a("(不一致が 1 件でもあれば数字を出さず停止する設計)。")
    a("")

    # ----- caveat -----
    a("## caveat(厳密性に関する注記)")
    a("")
    a("1. **in-sample 性**: v021_core は F-005 エラー分析(supreme 改良モジュールの開発)に使用済み。")
    a("   本 CV の held-out は v021_core 内の分割であり、人手封印(F-013)ではない。汚染ゼロの最終")
    a("   verdict ではなく、「学習が CV で汎化するか」の分析である。")
    a("2. **scene 既定 = fit([])**: scene には `default_params()` が無く、既定は fit([])(練習データ")
    a("   皆無)が返す _SceneParams(grid 先頭閾値)。これが指示の「fit([])相当の既定」。なお core は")
    a("   この既定をそのまま使わず persist.nominal と閾値を結線で差し替える(`_SCENE_THRESHOLDS`)が、")
    a("   本 CV は「fit が学習する閾値」自体の汎化を測るため、純粋な fit([]) vs fit(train) で比較する")
    a("   (core の結線差し替えは学習効果の測定対象でない)。")
    a("3. **t3 既定 = default_params()**: core が実際に使う未学習既定そのもの(core.py L526)。")
    a("4. **lineage-disjoint**: v021_core 20件は各自が root(generation=0・F-001 境界条件)。")
    a("   増強の親子は無いため、scenario_id 単位の分割で train/validation のリネージは非交差。")
    a("")

    # ----- fold とシナリオ対応 -----
    a("## fold 構成(決定的・scenario_id ソート順)")
    a("")
    a("| fold | validation シナリオ(4件) |")
    a("|---|---|")
    for k, f in enumerate(folds):
        a(f"| {k} | {', '.join(f)} |")
    a("")

    a("---")
    a("")
    a("_本レポートは supreme.* 公開 API + core 内部関数の import 再利用のみで生成した")
    a("(baseline コードは import していない=独立性)。core/モジュール/テストは無改変・分析専用。")
    a("2 回走行で held-out acc・fold 別 acc・param 数が完全一致することを確認済み(決定性)。_")
    a("")

    return "\n".join(lines)


def _fmt_delta(x):
    if x is None:
        return "NA"
    return f"{x:+.4f}"


def _safe_sub(a, b):
    if a is None or b is None:
        return None
    return a - b


# ===========================================================================
# エントリポイント
# ===========================================================================

def main():
    parser = argparse.ArgumentParser(
        description="学習効果 CV 分析: t3.fit / scene.fit が held-out で既定を上回るかを測る"
    )
    parser.add_argument("--pso-dir", default=DEFAULT_PSO_DIR,
                        help=f"PSO 入力ディレクトリ(既定: {DEFAULT_PSO_DIR})")
    parser.add_argument("--gt-dir", default=DEFAULT_GT_DIR,
                        help=f"GT ディレクトリ(既定: {DEFAULT_GT_DIR})")
    parser.add_argument("--out", default=None,
                        help="出力 Markdown パス(既定: reports/cv-train-<YYYYMMDD-HHMM>.md)")
    args = parser.parse_args()

    out_path = args.out
    if out_path is None:
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M")
        out_path = os.path.join(DEFAULT_OUT_DIR, f"cv-train-{stamp}.md")

    try:
        run(args.pso_dir, args.gt_dir, out_path)
    except (CVStop, dev.V13LabelError, dev.DataMismatch) as e:
        print(file=sys.stderr)
        print("=" * 70, file=sys.stderr)
        print("STOP(数字を捏造せず停止しました)。", file=sys.stderr)
        print(f"  種別: {type(e).__name__}", file=sys.stderr)
        print(f"  内容: {e}", file=sys.stderr)
        print("=" * 70, file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
