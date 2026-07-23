# -*- coding: utf-8 -*-
"""F-015 補助: situations_v1 eval(N3)の per-frame GT-vs-pred フレームビューア生成器。

`frames-N3.json`(dump_frames.py 出力)と `results.json`(公式測定値)を読み、
- suite/pooled の 8 層集計、
- 235 非違反シナリオの per-frame 正誤グリッドと機械生成考察、
- 契約違反 5 件の rejection カード、
を **Python 側で全て計算** し、自己完結・単一ファイルの HTML を書き出す。

規律(reports/VIEWERS.md):
- **機械生成数値**: ページに出る数値・件数・グリッドは全て本スクリプトが frames-N3.json /
  results.json から計算し埋め込む(手書き数値は禁止)。
- **INTEGRITY ASSERTION**: frames から再計算した pooled 8 層 acc(層別・overall)が
  results.json の N3 pooled と 1e-9 以内で一致することを assert(不一致なら停止・数値を丸めない)。
- **strict OFF が正規**: situations_v1 は能力評価土俵で strict OFF が正規実行(ADR 0049/0050)。
  よって `-nostrict` サフィックス規約は適用外(バナーに明示)。
- **別土俵**: coverage 系スコアと同一土俵で比較しない(バナーに明示)。

使い方:
  python build_frame_viewer.py [--frames PATH] [--results PATH] [--out PATH]

依存: 標準ライブラリのみ(supreme エンジンは import しない=frames-N3.json の突合値で自足)。
"""

from __future__ import annotations

import argparse
import html
import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_FRAMES = os.path.join(_HERE, "frames-N3.json")
_DEFAULT_RESULTS = os.path.join(_HERE, "results.json")
_DEFAULT_OUT = os.path.abspath(
    os.path.join(_HERE, "..", "frame-viewer-supreme8-situations.html")
)

# 8 層(採点キー・core.VIEW_LAYERS と同順)。
LAYERS = [
    "risk_tier", "t1_state", "t2_mode", "t2_role", "t2_relation",
    "t3_hypothesis", "quality_regime", "scene_regime",
]
LAYER_JA = {
    "risk_tier": "risk_tier(危険度)",
    "t1_state": "t1_state(接近状態)",
    "t2_mode": "t2_mode(場の様相)",
    "t2_role": "t2_role(音の主)",
    "t2_relation": "t2_relation(関係)",
    "t3_hypothesis": "t3_hypothesis(文脈仮説)",
    "quality_regime": "quality_regime(観測品質)",
    "scene_regime": "scene_regime(場面レジーム)",
}
SUITE_JA = {
    "std": "std 標準",
    "emg": "emg 緊急",
    "crw": "crw 群衆",
    "bst": "bst バースト",
    "dcp": "dcp 欺瞞(観測が嘘)",
    "crp": "crp 破損/Safety Latch",
}
SUITE_ORDER = ["std", "emg", "crw", "bst", "dcp", "crp"]

_TOL = 1e-9


# ---------------------------------------------------------------------------
# 集計(全て frames から機械計算)
# ---------------------------------------------------------------------------
def _abbrev(label):
    """語彙ラベルを決定的にコード化(グリッドの狭いセルに載せる短縮形)。

    '_' を含む → 各トークン頭字を大文字連結(conv_ongoing→CO・source_object→SO)。
    含まない → 先頭3文字を大文字化(info→INF・GOOD→GOO・STABLE→STA)。
    """
    if label is None:
        return "·"
    s = str(label)
    if "_" in s:
        return "".join(t[0] for t in s.split("_") if t).upper()
    return s[:3].upper()


def _scenario_stats(frames):
    """1 シナリオの per-layer 正誤・acc・最弱層・最長連続誤り区間を計算する。

    frames: [[ts, gt8, pred8], ...]。
    返り値: {n_frames, cells, correct, acc, per_layer:{L:{cor,tot,acc,streak,streak_span}},
             weakest_layer, worst_streak_layer}
    """
    n = len(frames)
    per_layer = {}
    total_cor = 0
    for L in LAYERS:
        cor = 0
        # 連続誤りストリーク(このレイヤの mismatch=1 の最長連続長と区間)。
        best_len, best_a, best_b = 0, None, None
        cur_len, cur_a = 0, None
        for i, (ts, gt, pred) in enumerate(frames):
            ok = gt.get(L) == pred.get(L)
            if ok:
                cor += 1
                cur_len, cur_a = 0, None
            else:
                if cur_len == 0:
                    cur_a = i
                cur_len += 1
                if cur_len > best_len:
                    best_len, best_a, best_b = cur_len, cur_a, i
        total_cor += cor
        per_layer[L] = {
            "cor": cor, "tot": n, "acc": (cor / n if n else 0.0),
            "streak": best_len, "streak_a": best_a, "streak_b": best_b,
        }
    # 最弱層(acc 最小・同率は LAYERS 順で先勝ち)。
    weakest = min(LAYERS, key=lambda L: (per_layer[L]["acc"], LAYERS.index(L)))
    # 最長連続誤り区間を持つ層(長さ最大・同率は LAYERS 順)。
    worst_streak = max(LAYERS, key=lambda L: (per_layer[L]["streak"], -LAYERS.index(L)))
    cells = n * len(LAYERS)
    return {
        "n_frames": n, "cells": cells, "correct": total_cor,
        "acc": (total_cor / cells if cells else 0.0),
        "per_layer": per_layer, "weakest_layer": weakest,
        "worst_streak_layer": worst_streak,
    }


def _agg_layers(frame_iter):
    """フレーム列 [[ts,gt,pred],...] から per-layer micro acc(cor,tot,acc)を返す。"""
    cor = {L: 0 for L in LAYERS}
    tot = 0
    for ts, gt, pred in frame_iter:
        tot += 1
        for L in LAYERS:
            if gt.get(L) == pred.get(L):
                cor[L] += 1
    layers = {L: {"cor": cor[L], "tot": tot, "acc": (cor[L] / tot if tot else 0.0)}
              for L in LAYERS}
    overall = sum(layers[L]["acc"] for L in LAYERS) / len(LAYERS)
    weakest = min(LAYERS, key=lambda L: (layers[L]["acc"], LAYERS.index(L)))
    return {"layers": layers, "overall": overall, "n_frames": tot, "weakest": weakest}


# ---------------------------------------------------------------------------
# HTML 断片
# ---------------------------------------------------------------------------
def _e(s):
    return html.escape("" if s is None else str(s), quote=True)


def _pct(x):
    return f"{x * 100:.1f}%"


def _bar(acc, label_value=True):
    """細い単一色(accent)アキュラシーバー(直接ラベル付き)。"""
    w = max(0.0, min(1.0, acc)) * 100
    lab = f"<span class='barlab'>{_pct(acc)}</span>" if label_value else ""
    return (f"<span class='bar'><span class='barfill' style='width:{w:.2f}%'></span></span>"
            f"{lab}")


def _grid_html(frames):
    """1 シナリオのグリッド(rows=8層・cols=frames)。match=dim green+✓ / mismatch=red+✗+pred。"""
    rows = []
    # 時刻ヘッダ行(フレーム index)。
    head = "".join(f"<i class='hc'>{i}</i>" for i in range(len(frames)))
    rows.append(f"<div class='grow head'><i class='rl'>frame</i>{head}</div>")
    for L in LAYERS:
        cells = []
        for i, (ts, gt, pred) in enumerate(frames):
            g = gt.get(L)
            p = pred.get(L)
            if g == p:
                cells.append(f"<i class='c ok' title='{_e(g)} ✓'></i>")
            else:
                # mismatch: pred 値表示(短縮)+ data-gt/data-pred + ツールチップ 'pred → GT'。
                cells.append(
                    f"<i class='c x' data-gt='{_e(g)}' data-pred='{_e(p)}' "
                    f"title='{_e(p)} → {_e(g)}'>{_e(_abbrev(p))}</i>"
                )
        rows.append(
            f"<div class='grow' data-layer='{L}'>"
            f"<i class='rl' title='{_e(LAYER_JA[L])}'>{_e(L)}</i>"
            f"{''.join(cells)}</div>"
        )
    return "".join(rows)


def _scenario_block(sid, suite, motif, frames, st):
    """1 シナリオ block(header + grid + 機械生成考察行)。data-* にフィルタ用メタ。"""
    weak = st["weakest_layer"]
    wl = st["per_layer"][weak]
    ws = st["worst_streak_layer"]
    wss = st["per_layer"][ws]
    if wss["streak"] > 0:
        streak_txt = (f"最長連続誤り: <b>{_e(ws)}</b> フレーム "
                      f"{wss['streak_a']}–{wss['streak_b']}(連続 {wss['streak']})")
    else:
        streak_txt = "最長連続誤り: なし(全フレーム一致)"
    has_mismatch = "1" if st["correct"] < st["cells"] else "0"
    header = (
        f"<div class='sh'>"
        f"<span class='sid'>{_e(sid)}</span>"
        f"<span class='motif'>{_e(motif)}</span>"
        f"<span class='sacc'>正答率 {_pct(st['acc'])} "
        f"<span class='mut'>({st['correct']}/{st['cells']} セル・{st['n_frames']}フレーム)</span></span>"
        f"<span class='sweak'>最弱層 <b>{_e(weak)}</b> {_pct(wl['acc'])}</span>"
        f"</div>"
    )
    anal = (
        f"<div class='anal'>考察(機械生成): 最弱層 <b>{_e(weak)}</b>"
        f"({wl['cor']}/{wl['tot']}={_pct(wl['acc'])})、{streak_txt}。</div>"
    )
    return (
        f"<div class='scen' data-sid='{_e(sid)}' data-suite='{suite}' "
        f"data-mismatch='{has_mismatch}' data-acc='{st['acc']:.6f}'>"
        f"{header}"
        f"<div class='grid'>{_grid_html(frames)}</div>"
        f"{anal}"
        f"</div>"
    )


def _kpi_tile(name, agg, is_pooled=False):
    cls = "tile pooled" if is_pooled else "tile"
    weak = agg["weakest"]
    return (
        f"<div class='{cls}'>"
        f"<div class='tname'>{_e(name)}</div>"
        f"<div class='tov'>{_pct(agg['overall'])}</div>"
        f"<div class='tsub'>8層平均 overall・{agg['n_frames']}フレーム</div>"
        f"<div class='tweak'>最弱層 <b>{_e(weak)}</b> {_pct(agg['layers'][weak]['acc'])}</div>"
        f"</div>"
    )


def _violation_card(v):
    """契約違反 rejection カード(sid・注入op・検出理由・明示拒否=正解・PASS バッジ)。"""
    ops = ", ".join(v.get("injected_ops") or []) or "—"
    return (
        f"<div class='vcard'>"
        f"<div class='vhead'><span class='vsid'>{_e(v['sid'])}</span>"
        f"<span class='vbadge'>✓ PASS</span></div>"
        f"<div class='vrow'><span class='vk'>suite</span><span class='vv'>{_e(v.get('suite'))}</span></div>"
        f"<div class='vrow'><span class='vk'>注入 op</span><span class='vv'>{_e(ops)}</span></div>"
        f"<div class='vrow'><span class='vk'>検出理由</span><span class='vv'>{_e(v.get('detected_reason'))}</span></div>"
        f"<div class='vrow'><span class='vk'>detail</span><span class='vv'>{_e(v.get('detail'))}</span></div>"
        f"<div class='vok'>明示拒否 = 正解(preflight が engine 実行前に停止)</div>"
        f"</div>"
    )


# ---------------------------------------------------------------------------
# ページ組み立て
# ---------------------------------------------------------------------------
def build_html(frames_doc, results_doc, recomputed_pooled, per_suite_agg, blocks_by_suite,
               n_blocks, n_cells):
    meta = frames_doc.get("meta", {})
    n3 = results_doc["configs"]["N3"]
    prov = n3["provenance"]
    rej = results_doc["meta"]["rejection_eval"]
    fit = n3["fit"]

    # --- KPI タイル(6 suite + pooled)---
    tiles = [_kpi_tile("pooled(全 235)", recomputed_pooled, is_pooled=True)]
    for su in SUITE_ORDER:
        tiles.append(_kpi_tile(SUITE_JA[su], per_suite_agg[su]))
    tiles_html = "".join(tiles)

    # --- suite ごとの <details>(std open・他 closed)---
    details = []
    for su in SUITE_ORDER:
        blocks = blocks_by_suite.get(su, [])
        openattr = " open" if su == "std" else ""
        agg = per_suite_agg[su]
        details.append(
            f"<details class='suite' data-suite='{su}'{openattr}>"
            f"<summary><span class='smname'>{_e(SUITE_JA[su])}</span>"
            f"<span class='smmeta'>{len(blocks)} シナリオ・overall {_pct(agg['overall'])}・"
            f"最弱層 {_e(agg['weakest'])} {_pct(agg['layers'][agg['weakest']]['acc'])}</span></summary>"
            f"<div class='blocks'>{''.join(b for _sid, b in blocks)}</div>"
            f"</details>"
        )
    details_html = "".join(details)

    # --- violation カード ---
    vcards = "".join(_violation_card(v) for v in frames_doc.get("violations", []))
    n_cards = len(frames_doc.get("violations", []))

    # --- layer toggle chips ---
    layer_chips = "".join(
        f"<label class='chip'><input type='checkbox' class='lyr' value='{L}' checked>"
        f"{_e(L)}</label>" for L in LAYERS
    )
    suite_chips = "".join(
        f"<label class='chip'><input type='checkbox' class='ste' value='{su}' checked>"
        f"{_e(su)}</label>" for su in SUITE_ORDER
    )

    # --- pooled 層別 acc バー(集計から機械描画)---
    layer_bars = "".join(
        f"<div class='lrow'><span class='lname'>{_e(L)}</span>"
        f"{_bar(recomputed_pooled['layers'][L]['acc'])}</div>"
        for L in LAYERS
    )

    regen = (
        "python reports/situations_v1-eval-20260722/dump_frames.py  # frames-N3.json 再生成\n"
        "python reports/situations_v1-eval-20260722/build_frame_viewer.py  # 本ビューア再生成"
    )

    css = _CSS
    js = _JS

    title = "supreme8 situations_v1 フレームビューア(N3・strict OFF)"
    return f"""<!doctype html>
<html lang="ja"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_e(title)}</title>
<style>{css}</style>
</head><body>

<header class="top">
  <h1>{_e(title)}</h1>
  <div class="banner">
    <div class="bline"><b>⚠️ world-first 生成の能力評価土俵(situations_v1)</b> —
      GT を潜在世界 W から直接導出。<b>coverage 系スコアと同一土俵で比較しない(別土俵)</b>。</div>
    <div class="bline"><b>strict OFF が正規</b>: 能力評価は <code>strict_gt_conformance=False</code> 必須
      (ADR 0049/0050)。situations_v1 は strict OFF が正規実行のため
      <code>-nostrict</code> サフィックス規約は適用外。</div>
    <div class="bline">測定日 <b>{_e(prov and results_doc['meta'].get('measurement_date'))}</b>・
      eval split・非違反 <b>{recomputed_pooled['n_frames']}</b> フレーム/<b>{n_blocks}</b> シナリオ採点。
      engine HEAD <code>{_e(prov['engine_repo_head'])}</code>・
      data HEAD <code>{_e(prov['data_repo_head'])}</code>(results.json N3)。</div>
    <div class="bline mut">フレームデータ源: <code>frames-N3.json</code>
      (dump engine <code>{_e(meta.get('engine_repo_head'))}</code>・code_state {_e(meta.get('code_state'))};
      dump_frames.py が pooled==results.json N3 を assert 済み)。</div>
  </div>
</header>

<section class="kpis">
  <h2>suite 別 / pooled 正答率(全数値は frames から機械計算)</h2>
  <div class="tiles">{tiles_html}</div>
  <div class="poolbars">
    <div class="pbtitle">pooled 8 層別 acc(N3・235 シナリオ・{recomputed_pooled['n_frames']}フレーム)</div>
    {layer_bars}
  </div>
</section>

<div class="filterbar" id="filterbar">
  <div class="fgrp"><span class="flab">suite</span>{suite_chips}</div>
  <div class="fgrp"><span class="flab">8層表示</span>{layer_chips}</div>
  <div class="fgrp">
    <label class="chip"><input type="checkbox" id="mmonly"> 不一致のみ</label>
    <input type="search" id="sidsearch" placeholder="sid 検索…">
    <span class="fcount" id="fcount"></span>
  </div>
</div>

<main class="scenarios">
  {details_html}
</main>

<section class="violations">
  <h2>契約違反 rejection({n_cards} 件・eval 公式・rejection_acc {rej['rejected']}/{rej['total']}=
    {rej['rejection_acc']:.4f})</h2>
  <p class="mut">違反は 8 層採点の全分母から除外し、preflight の <b>明示拒否</b>を正解として別採点する
    (engine 実行前に停止)。全 {n_cards} 件が正しく拒否された。</p>
  <div class="vcards">{vcards}</div>
</section>

<footer class="foot">
  <div><b>provenance</b> — system {_e(meta.get('system'))} / config {_e(meta.get('config'))} /
    strict {str(meta.get('strict')).lower()} /
    engine(results.json N3) <code>{_e(prov['engine_repo_head'])}</code> /
    data <code>{_e(prov['data_repo_head'])}</code> / 測定日 {_e(results_doc['meta'].get('measurement_date'))}。</div>
  <div>T2 学習レシピ(N3): {_e(fit.get('t2_choice'))} ・
    ≥ガード acc_tuned {fit.get('t2_guard', {}).get('acc_tuned', float('nan')):.4f} vs
    acc_default {fit.get('t2_guard', {}).get('acc_default', float('nan')):.4f}。</div>
  <div><b>再生成</b><pre class="regen">{_e(regen)}</pre></div>
  <div class="mut">本ファイルは build_frame_viewer.py が生成。数値・件数・グリッドは
    frames-N3.json / results.json から機械計算し、pooled==results.json N3 を assert 済み。手編集しないこと。</div>
</footer>

<script>{js}</script>
</body></html>
"""


_CSS = """
:root{--bg:#0f1419;--panel:#161b22;--panel2:#1c232c;--ink:#e6edf3;--mut:#8b949e;
--good:#3fb950;--bad:#f85149;--accent:#58a6ff;--line:#30363d;}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Hiragino Kaku Gothic ProN",Meiryo,sans-serif;
font-size:13px;line-height:1.5}
code{font-family:"SFMono-Regular",Consolas,Menlo,monospace;font-size:.92em;color:var(--accent)}
h1{font-size:19px;margin:0 0 8px}
h2{font-size:15px;margin:0 0 10px;color:var(--ink)}
.mut{color:var(--mut)}
.top{padding:16px 20px;border-bottom:1px solid var(--line);background:var(--panel)}
.banner{background:var(--panel2);border:1px solid var(--line);border-left:3px solid var(--accent);
border-radius:6px;padding:10px 12px;margin-top:6px}
.bline{margin:3px 0}
.kpis{padding:16px 20px;border-bottom:1px solid var(--line)}
.tiles{display:flex;flex-wrap:wrap;gap:10px;margin-bottom:14px}
.tile{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:10px 12px;
min-width:150px;flex:1 1 150px}
.tile.pooled{border-color:var(--accent)}
.tname{color:var(--mut);font-size:12px}
.tov{font-size:24px;font-weight:700;color:var(--ink);margin:2px 0}
.tsub{color:var(--mut);font-size:11px}
.tweak{font-size:11.5px;margin-top:4px}
.poolbars{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:12px}
.pbtitle{color:var(--mut);margin-bottom:8px}
.lrow{display:flex;align-items:center;gap:8px;margin:3px 0}
.lname{width:120px;color:var(--ink);font-size:12px}
.bar{display:inline-block;width:min(360px,45vw);height:8px;background:var(--panel2);
border-radius:4px;overflow:hidden}
.barfill{display:block;height:100%;background:var(--accent)}
.barlab{color:var(--mut);font-variant-numeric:tabular-nums;min-width:44px}
.filterbar{position:sticky;top:0;z-index:20;background:var(--panel);border-bottom:1px solid var(--line);
padding:8px 20px;display:flex;flex-wrap:wrap;gap:14px;align-items:center}
.fgrp{display:flex;flex-wrap:wrap;gap:6px;align-items:center}
.flab{color:var(--mut);font-size:11px;margin-right:2px}
.chip{background:var(--panel2);border:1px solid var(--line);border-radius:14px;padding:2px 9px;
font-size:11.5px;cursor:pointer;user-select:none;display:inline-flex;gap:4px;align-items:center}
.chip input{margin:0;cursor:pointer}
#sidsearch{background:var(--panel2);border:1px solid var(--line);color:var(--ink);border-radius:6px;
padding:3px 8px;font-size:12px;min-width:150px}
.fcount{color:var(--mut);font-size:11.5px}
.scenarios{padding:14px 20px}
.suite{margin-bottom:10px;border:1px solid var(--line);border-radius:8px;overflow:hidden;background:var(--panel)}
.suite>summary{cursor:pointer;padding:9px 12px;background:var(--panel2);font-weight:600;
display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap}
.smmeta{color:var(--mut);font-weight:400;font-size:12px}
.blocks{padding:8px 10px}
.scen{border:1px solid var(--line);border-radius:6px;padding:8px 10px;margin:8px 0;background:var(--bg)}
.sh{display:flex;flex-wrap:wrap;gap:10px;align-items:baseline;margin-bottom:6px}
.sid{font-weight:700;color:var(--accent);font-family:"SFMono-Regular",Consolas,monospace;font-size:12px}
.motif{color:var(--mut);font-size:12px}
.sacc{font-variant-numeric:tabular-nums}
.sweak{font-size:12px;color:var(--ink)}
.grid{overflow-x:auto;padding:2px 0}
.grow{display:flex;gap:2px;margin:2px 0;align-items:center;white-space:nowrap}
.grow.head{color:var(--mut)}
.rl{width:96px;min-width:96px;font-size:10.5px;color:var(--mut);text-align:right;padding-right:6px;
font-family:"SFMono-Regular",Consolas,monospace;font-style:normal}
.hc{width:20px;min-width:20px;text-align:center;font-size:9.5px;font-style:normal;color:var(--mut)}
.c{width:20px;min-width:20px;height:18px;border-radius:3px;display:inline-flex;align-items:center;
justify-content:center;font-size:8.5px;font-style:normal;font-weight:700;letter-spacing:-.3px}
.c.ok{background:rgba(63,185,80,.16)}
.c.ok::before{content:"✓";color:var(--good);font-size:10px}
.c.x{background:rgba(248,81,73,.20);color:#ffd7d5;cursor:help;border:1px solid rgba(248,81,73,.5)}
.anal{margin-top:6px;font-size:11.5px;color:var(--mut);border-top:1px dashed var(--line);padding-top:5px}
.anal b{color:var(--ink)}
.violations{padding:14px 20px;border-top:1px solid var(--line)}
.vcards{display:flex;flex-wrap:wrap;gap:10px}
.vcard{background:var(--panel);border:1px solid var(--line);border-left:3px solid var(--good);
border-radius:8px;padding:10px 12px;min-width:240px;flex:1 1 240px}
.vhead{display:flex;justify-content:space-between;align-items:center;margin-bottom:6px}
.vsid{font-weight:700;color:var(--accent);font-family:"SFMono-Regular",Consolas,monospace;font-size:12px}
.vbadge{background:rgba(63,185,80,.16);color:var(--good);border:1px solid var(--good);
border-radius:12px;padding:1px 8px;font-size:11px;font-weight:700}
.vrow{display:flex;gap:8px;margin:2px 0;font-size:12px}
.vk{color:var(--mut);width:64px;min-width:64px}
.vv{color:var(--ink)}
.vok{margin-top:6px;font-size:11.5px;color:var(--good)}
.foot{padding:16px 20px;border-top:1px solid var(--line);color:var(--mut);font-size:12px}
.foot>div{margin:4px 0}
.regen{background:var(--panel2);border:1px solid var(--line);border-radius:6px;padding:8px;
color:var(--ink);overflow-x:auto;white-space:pre;font-size:11.5px}
"""

_JS = """
(function(){
  var scen = Array.prototype.slice.call(document.querySelectorAll('.scen'));
  var suites = Array.prototype.slice.call(document.querySelectorAll('.suite'));
  var steBoxes = Array.prototype.slice.call(document.querySelectorAll('input.ste'));
  var lyrBoxes = Array.prototype.slice.call(document.querySelectorAll('input.lyr'));
  var mmonly = document.getElementById('mmonly');
  var search = document.getElementById('sidsearch');
  var fcount = document.getElementById('fcount');

  function activeSuites(){
    var s={}; steBoxes.forEach(function(b){ s[b.value]=b.checked; }); return s;
  }
  function applyLayers(){
    var on={}; lyrBoxes.forEach(function(b){ on[b.value]=b.checked; });
    document.querySelectorAll('.grow[data-layer]').forEach(function(r){
      r.style.display = on[r.getAttribute('data-layer')] ? '' : 'none';
    });
  }
  function apply(){
    var s=activeSuites();
    var q=(search.value||'').trim().toLowerCase();
    var mm=mmonly.checked;
    var shown=0;
    scen.forEach(function(el){
      var ok = s[el.getAttribute('data-suite')];
      if(ok && mm && el.getAttribute('data-mismatch')!=='1') ok=false;
      if(ok && q && el.getAttribute('data-sid').toLowerCase().indexOf(q)<0) ok=false;
      el.style.display = ok ? '' : 'none';
      if(ok) shown++;
    });
    // suite <details>: 表示シナリオ 0 の suite は畳む/隠す
    suites.forEach(function(d){
      var vis = d.querySelectorAll('.scen').length &&
        Array.prototype.some.call(d.querySelectorAll('.scen'), function(e){return e.style.display!=='none';});
      var suiteOn = s[d.getAttribute('data-suite')];
      d.style.display = suiteOn ? '' : 'none';
      if(suiteOn && (q||mm) && vis && !d.open) d.open=true;
    });
    fcount.textContent = shown + ' / ' + scen.length + ' シナリオ表示';
  }
  steBoxes.forEach(function(b){ b.addEventListener('change',apply); });
  lyrBoxes.forEach(function(b){ b.addEventListener('change',applyLayers); });
  mmonly.addEventListener('change',apply);
  search.addEventListener('input',apply);
  applyLayers(); apply();
})();
"""


# ---------------------------------------------------------------------------
# INTEGRITY ASSERTION
# ---------------------------------------------------------------------------
def integrity_assert(recomputed_pooled, results_doc):
    rec = results_doc["configs"]["N3"]["eval"]["pooled"]
    mismatches = []
    print("=== INTEGRITY ASSERTION (N3 pooled: frames 再計算 vs results.json) ===")
    print(f"{'layer':<16}{'recomputed':>16}{'recorded':>16}{'diff':>12}")
    for L in LAYERS:
        a = recomputed_pooled["layers"][L]["acc"]
        b = rec["layers"][L]
        diff = abs(a - b)
        print(f"{L:<16}{a:>16.12f}{b:>16.12f}{diff:>12.2e}")
        if diff > _TOL:
            mismatches.append((L, a, b, diff))
    a, b = recomputed_pooled["overall"], rec["overall"]
    diff = abs(a - b)
    print(f"{'overall':<16}{a:>16.12f}{b:>16.12f}{diff:>12.2e}")
    if diff > _TOL:
        mismatches.append(("overall", a, b, diff))
    if mismatches:
        raise AssertionError(
            "INTEGRITY ASSERTION 不一致(frames 再計算 != results.json N3 pooled): "
            + "; ".join(f"{m[0]}: {m[1]!r} != {m[2]!r} (diff={m[3]!r})" for m in mismatches)
        )
    print(f"=== INTEGRITY ASSERTION: PASS (tol={_TOL:.0e}) ===")


def main(argv=None):
    ap = argparse.ArgumentParser(description="supreme8 situations_v1 フレームビューア生成")
    ap.add_argument("--frames", default=_DEFAULT_FRAMES)
    ap.add_argument("--results", default=_DEFAULT_RESULTS)
    ap.add_argument("--out", default=_DEFAULT_OUT)
    args = ap.parse_args(argv)

    with open(args.frames, encoding="utf-8") as f:
        frames_doc = json.load(f)
    with open(args.results, encoding="utf-8") as f:
        results_doc = json.load(f)

    scenarios = frames_doc["scenarios"]

    # --- pooled 再計算(全 frames)---
    def _all_frames():
        for sid, v in scenarios.items():
            for fr in v["frames"]:
                yield fr
    recomputed_pooled = _agg_layers(_all_frames())

    # --- INTEGRITY ASSERTION(丸めない・不一致で停止)---
    integrity_assert(recomputed_pooled, results_doc)

    # --- per-suite 集計 + 照合(results.json per_suite overall と一致検証)---
    per_suite_agg = {}
    ps_rec = results_doc["configs"]["N3"]["eval"]["per_suite"]
    for su in SUITE_ORDER:
        frs = [fr for sid, v in scenarios.items() if v["suite"] == su for fr in v["frames"]]
        agg = _agg_layers(frs)
        per_suite_agg[su] = agg
        rec_ov = ps_rec[su]["overall"]
        if abs(agg["overall"] - rec_ov) > _TOL:
            raise AssertionError(
                f"per-suite {su} overall 不一致: {agg['overall']!r} != {rec_ov!r}")
    print("per-suite overall: 全 6 suite が results.json N3 と一致(tol=%.0e)" % _TOL)

    # --- シナリオ block(suite ごと・sid 昇順で決定的)---
    blocks_by_suite = {su: [] for su in SUITE_ORDER}
    n_cells = 0
    for sid in sorted(scenarios.keys()):
        v = scenarios[sid]
        su = v["suite"]
        st = _scenario_stats(v["frames"])
        n_cells += st["cells"]
        blocks_by_suite.setdefault(su, []).append(
            (sid, _scenario_block(sid, su, v["motif"], v["frames"], st)))
    n_blocks = sum(len(b) for b in blocks_by_suite.values())

    html_out = build_html(frames_doc, results_doc, recomputed_pooled, per_suite_agg,
                          blocks_by_suite, n_blocks, n_cells)

    with open(args.out, "w", encoding="utf-8") as f:
        f.write(html_out)

    size = os.path.getsize(args.out)
    n_cards = len(frames_doc.get("violations", []))
    expected_cells = recomputed_pooled["n_frames"] * len(LAYERS)

    # --- 検証プリント + assert ---
    print("--- BUILD VERIFICATION ---")
    print(f"scenario blocks : {n_blocks}  (期待 235)")
    print(f"violation cards : {n_cards}  (期待 5)")
    print(f"grid cells      : {n_cells}  == frames*8 = {expected_cells}  "
          f"({recomputed_pooled['n_frames']} frames * {len(LAYERS)} layers)")
    print(f"output          : {args.out}")
    print(f"output size     : {size} bytes ({size/1e6:.2f} MB)")
    assert n_blocks == 235, f"scenario blocks 期待 235, 実 {n_blocks}"
    assert n_cards == 5, f"violation cards 期待 5, 実 {n_cards}"
    assert n_cells == expected_cells == 4057 * 8, (
        f"cell count 期待 {4057 * 8}, 実 {n_cells}")
    assert size < 7 * 1024 * 1024, f"出力 {size} bytes が 7MB を超過"
    print("--- ALL BUILD ASSERTIONS PASS ---")


if __name__ == "__main__":
    main()
