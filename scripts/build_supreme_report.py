# -*- coding: utf-8 -*-
"""新 supreme 研究レポート HTML 組み立て — baseline 完成形レポートの CSS/JS/付録を再利用。

設計(忠実ポート・正直さ優先):
  - CSS(<style>)・JS エンジン(データ駆動の図/ヒートマップ/カルテ/レーダー再生)・付録 A の
    インタラクティブ・ウィジェット(HGF/T0/T1/T2/EMA/scene/t3 の体験版)は **baseline から再利用**
    (機構は Plan A 系で共有・同一入力 PSO なのでレーダー/イベント帯も視覚一致して当然)。
  - 本文(ヘッダ KPI・要旨・アーキ図・採点・結果・診断・考察・信頼度・課題・再現)は **supreme 用に
    新規執筆**。図のアンカー(#layerbars/#heatmap/#cards/#rolebars/#modebars/#t3bars/#slbars)は維持。
  - JS の DATA は gen_supreme_report.py が出した **supreme 実走 DATA** に差し替え。
    STORY(シナリオ別講評)と診断 errBars(top 混同)は **supreme DATA から honest に自動生成**。
  - 数値は old-supreme-v14-rescore §3(検証済み・apples-to-apples)に一致。**in-sample/CV であって
    封印 verdict ではない**ことを冒頭・各所で明示。

出力: reports/research-20260615-planA-supreme.html(自己完結 HTML)
使い方: python scripts/gen_supreme_report.py && python scripts/build_supreme_report.py
"""

from __future__ import annotations

import json
import os
import re
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_SCRIPT_DIR)
BASELINE_REPORT = (
    r"C:\work\L04-planA\baseline\planA-baseline\reports"
    r"\research-20260610-planA-baseline.html"
)
DATA_JSON = os.path.join(_ROOT, "reports", "_supreme_report_data.json")
OUT_HTML = os.path.join(_ROOT, "reports", "research-20260615-planA-supreme.html")

LAYERS = ["risk_tier", "t1_state", "t2_mode", "t2_role", "t2_relation",
          "t3_hypothesis", "quality_regime", "scene_regime"]
LAYER_JP = {
    "risk_tier": "risk_tier (T0)", "t1_state": "t1_state (T1)",
    "t2_mode": "t2_mode (T2)", "t2_role": "t2_role (T2)",
    "t2_relation": "t2_relation (T2)", "t3_hypothesis": "t3_hypothesis (T3)",
    "quality_regime": "quality_regime", "scene_regime": "scene_regime",
}

# --- 検証済み数値(old-supreme-v14-rescore-20260615-0737.md §3・apples-to-apples)---
OLD_V14 = {"risk_tier": 0.9333, "t1_state": 0.9095, "t2_mode": 0.6238,
           "t2_role": 0.9333, "t2_relation": 0.7476, "t3_hypothesis": 0.5857,
           "quality_regime": 0.8238, "scene_regime": 0.5286}
NEW_DEFAULT = {"risk_tier": 0.9333, "t1_state": 0.9095, "t2_mode": 0.6286,
               "t2_role": 0.9571, "t2_relation": 0.8381, "t3_hypothesis": 0.3952,
               "quality_regime": 0.8238, "scene_regime": 0.4524}
NEW_TRAINED_INSAMPLE = {"t3_hypothesis": 0.5381, "scene_regime": 0.5571}
NEW_CV_HELDOUT = {"t3_hypothesis": 0.4095, "scene_regime": 0.5571}
CV_DEFAULT = {"t3_hypothesis": 0.3571, "scene_regime": 0.3238}


# ===========================================================================
# baseline パーツ抽出
# ===========================================================================

def _extract_parts():
    html = open(BASELINE_REPORT, encoding="utf-8").read()
    style = html[html.index("<style>"):html.index("</style>") + len("</style>")]
    appendix = html[html.index('<h2 id="apA">'):html.index("</main>")]
    js_full = html[html.rindex("<script>") + len("<script>"):html.rindex("</script>")]
    return style, appendix, js_full


# ===========================================================================
# supreme DATA から STORY / 診断バーを honest 自動生成
# ===========================================================================

def _acc(cells):
    cs = [c for c in cells if c[1] is not None]
    if not cs:
        return None
    return sum(1 for c in cs if c[1] == c[2]) / len(cs)


def _top_confusions(scenarios, layer, k=5):
    bad = {}
    for s in scenarios:
        for c in s["cells"][layer]:
            if c[1] is not None and c[1] != c[2]:
                key = (c[1], c[2])
                bad[key] = bad.get(key, 0) + 1
    return sorted(bad.items(), key=lambda kv: -kv[1])[:k]


# 要所シナリオのハンド補強(supreme 固有の物語・honest)。auto 文に前置きする。
HIGHLIGHTS = {
    "ns001_boot_sanity": ("✅起動健全", "空シーンで全層が正しく「何もない」と答える(決定的起動)。"),
    "ns003_siren_danger": ("✅role満点", "サイレン+緊急車両接近。主役当て(警報)は流用移植で満点。残差は scene の急変鈍感。"),
    "ns005_anomaly_surprise": ("✅role満点", "静けさからの突発音。警報の正体当ては満点。"),
    "ns007_crowd_ambient": ("mode改善", "3人の雑踏。人数≥3→雑踏ルールで mode を底上げ。"),
    "ns013_scene_degrading": ("✅role満点", "警報累積で環境悪化。旧の最大バグ(alarm未認識)は流用移植で解消。"),
    "ns016_deep_conversation": ("relation改善", "接近→会話→離脱。relation の addressing/grouped 較正で旧より底上げ。会話の取り下げは残課題。"),
    "ns020_sustained_emergency": ("緊急が降りない", "サイレン接近→離脱。主役当ては満点。最大失点は『危機が去った』を認められない残留(▶再生で確認)。"),
}


def _build_story(scenarios):
    """各シナリオの trained 実績から honest な講評を生成。"""
    story = {}
    for s in scenarios:
        sid = s["id"]
        accs = {ly: _acc(s["cells"][ly]) for ly in LAYERS}
        scored = [a for a in accs.values() if a is not None]
        overall = sum(scored) / len(scored) if scored else 0.0
        # 弱い層を拾う(acc<0.6)
        weak = sorted(((ly, a) for ly, a in accs.items() if a is not None and a < 0.6),
                      key=lambda x: x[1])
        tags = []
        hl = HIGHLIGHTS.get(sid)
        if hl:
            tags.append(hl[0])
        if overall >= 0.95:
            tags.append("✅高得点")
        for ly, a in weak[:2]:
            tags.append(f"{ly.replace('t2_', '').replace('t3_hypothesis', 't3').replace('_regime', '').replace('_state', '').replace('_tier', '')}弱")
        if not tags:
            tags.append("概ね良好")
        # 本文 = ハンド補強 + 実績要約
        parts = []
        if hl:
            parts.append(hl[1])
        if weak:
            wtxt = "・".join(f"{ly}={a:.2f}" for ly, a in weak[:3])
            parts.append(f"主因: {wtxt}(学習配備版 in-sample)。")
        else:
            parts.append(f"全層 0.6 以上(総合 {overall:.2f}・学習配備版 in-sample)。")
        story[sid] = {"ok": overall >= 0.95, "tags": tags, "txt": "".join(parts)}
    return story


def _errbars_js(scenarios):
    """rolebars/modebars/t3bars を supreme の top 混同で生成(honest・data 由来)。"""
    out = []
    specs = [
        ("rolebars", "t2_role"),
        ("modebars", "t2_mode"),
        ("t3bars", "t3_hypothesis"),
    ]
    for elid, layer in specs:
        conf = _top_confusions(scenarios, layer, k=5)
        maxn = max((n for _, n in conf), default=1)
        rows = []
        for (g, p), n in conf:
            rows.append([f"{g} → {p}", n, ""])
        out.append(f'errBars("{elid}",{json.dumps(rows, ensure_ascii=False)},{maxn});')
    return "\n".join(out)


# ===========================================================================
# 本文(supreme 新規執筆)
# ===========================================================================

def _narrative(scenarios):
    la = {ly: _acc_all(scenarios, ly) for ly in LAYERS}  # 学習配備版 in-sample 層別

    def f(x):
        return f"{x:.4f}"

    ov_default = sum(NEW_DEFAULT[ly] for ly in LAYERS) / 8
    ov_trained = sum((NEW_TRAINED_INSAMPLE.get(ly, NEW_DEFAULT[ly])) for ly in LAYERS) / 8
    ov_old = sum(OLD_V14[ly] for ly in LAYERS) / 8

    H = []
    a = H.append

    # ---------- header ----------
    a('<header class="page"><div class="wrap">')
    a('<h1>研究レポート: planA supreme<br>— NS-EPI L04 新アーキ(学習配備版)</h1>')
    a('<div class="sub">生成 2026-06-15 ・ 評価: v021_core catalog 1.4.0(20シナリオ・210フレーム)・'
      '図とカルテはすべて <b>supreme 学習配備版(fit_supreme→run_supreme)</b>の実走で描画 ・ '
      '<b>in-sample / CV held-out ＝封印 verdict ではない</b></div>')
    a('<div class="kpis">')
    a('<div class="kpi"><div class="v">新3 / 分4 / 旧1</div><div class="k">'
      '旧リファレンスと同一 v1.4 で層別勝敗(学習層は CV held-out)</div></div>')
    a('<div class="kpi"><div class="v">0.957 / 0.838</div><div class="k">'
      'role / relation を底上げ(新 &gt; 旧)</div></div>')
    a('<div class="kpi"><div class="v">t3 = 0.5381</div><div class="k">'
      'CV 天井=過適合せず詰める余地なし(研究者領分)</div></div>')
    a('<div class="kpi"><div class="v">800 / 0</div><div class="k">'
      'テスト passed / failed・決定的(バイト一致)</div></div>')
    a('</div></div></header>')

    a('<main>')

    # ---------- opening callout ----------
    a('<div class="callout" style="margin-top:24px">'
      '本レポートは NS-EPI L04(Plan A 系)を baseline リファレンス実装と<b>独立に</b>作り直した'
      '<b>新アーキ supreme</b> の解説と評価です。ルール+HGF に加え、苦手だった層に'
      '<b>学習(<code>fit_supreme</code>)</b>を配備しました。狙いは<b>弱い項目の底上げ</b>。'
      '<b class="warn">重要</b>: 本ページの数値は <b>in-sample(開発セット v021_core)と CV held-out</b> であり、'
      '<b>汚染ゼロの封印 verdict ではありません</b>(封印の本番実走は研究者手動 = '
      '<code>docs/SEALED_EVAL_RUNBOOK.md</code>)。旧リファレンス実装(= planA-baseline)とは'
      '<b>同一 v1.4 採点規約で apples-to-apples</b> に比較しています。</div>')

    # ---------- TOC ----------
    a('<nav class="toc"><ol start="0">'
      '<li><a href="#s0">要旨 — 3行でいうと</a></li>'
      '<li><a href="#s1">これは何をするシステムか</a></li>'
      '<li><a href="#s2">全体アーキテクチャ(図1)</a></li>'
      '<li><a href="#s3">作り方(開発プロセス)</a></li>'
      '<li><a href="#s4">採点方法 — 8つの「答え」と20本のテスト</a></li>'
      '<li><a href="#s5">結果 — 新旧比較・層別・ヒートマップ・<b>カルテ(▶再生)</b></a></li>'
      '<li><a href="#s6">診断 — どこで・なぜ間違えるのか / 学習は効いたか</a></li>'
      '<li><a href="#s7">考察 — 限界の正体と、次の一手</a></li>'
      '<li><a href="#s8">この数字をどこまで信じてよいか</a></li>'
      '<li><a href="#s9">今後の課題</a></li>'
      '<li><a href="#s10">再現手順</a></li>'
      '</ol><div style="margin-top:8px"><b><a href="#apA">付録A: ノード図鑑(触って試せる)</a></b>'
      ' / <a href="#apB">付録B: 参照資料</a></div></nav>')

    # ---------- s0 要旨 ----------
    a('<h2 id="s0">0. 要旨 — 3行でいうと</h2><ol style="font-size:16px">')
    a('<li>音の観測から「いま何が起きているか」を8観点で答えるシステムを、'
      '<b>ルール+ベイズフィルタに学習を足して</b>独立実装した。旧リファレンス(同一 v1.4 で '
      f'overall {f(ov_old)})と比べ、<b>role/relation を明確に底上げし、scene を学習で改善'
      '(CV held-out で汎化を確認)、強い項目(危険・接近・主役)を維持</b>した。</li>')
    a('<li><b>honest な層別勝敗</b>(学習層は CV held-out で判定): '
      '<span class="good">新が優</span> = role(+0.024)・relation(+0.091)・scene(CV 0.557&gt;0.529)、'
      '<span class="warn">互角</span> = risk/t1/mode/quality、'
      '<span class="bad">旧が優</span> = <b>t3 の1層のみ</b>。</li>')
    a('<li><b>t3 は CV で天井(0.5381)を実証</b>= in-sample/CV でこれ以上の作り込みは'
      '<b>過適合で逆効果</b>。t3 の残りは「ルールの書き方」ではなく構造(上流 T2 従属・文脈ラベル)で、'
      '<b>研究者領分</b>(多様な実人手シナリオ + 封印実走)に委ねる(§6.3・§7)。</li></ol>')

    # ---------- s1 ----------
    a('<h2 id="s1">1. これは何をするシステムか</h2>'
      '<p>入力は PSO — マイクアレイ等で「分離・定位済み」の音環境データ。各時刻(0.5秒ごと)に'
      '「どこに・どんな音源があるか」(声・車・サイレン、方向と距離)が入る。L04 の仕事は、この'
      'バラバラの観測に<b>束ねる</b>(声と話者を同じ thread に)・<b>ちらつかせない</b>'
      '(時間方向に平滑化)を足して、8つの観点で解釈すること。</p>'
      '<div class="intuition"><span class="t">supreme の立場:</span> baseline が'
      '<b>ルール+HGF だけ</b>で到達した地点を出発点に、<b>苦手な層(scene/t3)へ学習を配備</b>し、'
      '<b>強い層は流用移植</b>、<b>mode/relation は計測で発見したルールの誤りを修正</b>して底上げした。'
      '「静的な仮説の誤りを計測で見つけて直す」のが本プロジェクトの一貫した進め方。</div>')

    # ---------- s2 architecture ----------
    a('<h2 id="s2">2. 全体アーキテクチャ(図1)</h2>'
      '<p>左から右へ流れる。<b>読み方</b>: ①太い灰の本流(入力→各層→統合→出力)を追う。'
      '②緑の破線は品質レール(信頼度)。③<span style="color:#7c5cab">紫の層は学習配備'
      '(<code>fit_supreme</code>)</span>、<span style="color:#0b5fa5">青の層はルール</span>。'
      '④下の点線枠は<b>オフライン経路</b>(増強→探索→ガード→封印評価=研究者手動)。</p>')
    a(_ARCH_SVG)

    # ---------- s3 ----------
    a('<h2 id="s3">3. 作り方(開発プロセス)</h2>'
      '<p>役割を分けた4つの AI エージェント(仕様レビュー / テスト作成 / 実装 / 監査)を'
      'オーケストレーター(Claude)が指揮する方式で、<b>実働4日・テスト800本</b>(実装コードの約3倍)で'
      '構築。設計判断は <b>ADR 29本</b>、検証は<b>監査レポート 26本</b>として記録。テストを先に書いて'
      '(赤)→実装で通す(緑)→監査で仕様一致を確認、を全15機能で反復した。'
      '<b>本プロジェクトの特徴は「静的仮説の誤りを計測で発見・修正」</b>したこと — '
      '開発中に<b>構造バグ5件</b>(scene 定数潰れ / quality vol 層取り違え / t3 規則層7語彙未配線 / '
      'mode 語彙潰し / h_q→t3 死配線)を計測で発見して直し、学習配線(<code>fit_supreme</code>)も'
      '当初 <code>fit([])</code> で未学習だったのを CV で検出して接続した(ADR 0024〜0029)。</p>')

    # ---------- s4 ----------
    a('<h2 id="s4">4. 採点方法 — 8つの「答え」と20本のテスト</h2>'
      '<p>システムは 0.5 秒ごとに次の<b>8つの質問</b>に答える。20本のテスト(計210フレーム)には'
      '人手の正解(GT)が付き、層ごとの正答率を出す。総合 = 8層の正答率の単純平均。'
      '<b>採点は新旧で完全に同一</b>(<code>harness.canonical_metric_spec</code>・micro acc・完全一致)。</p>')
    a('<table><thead><tr><th>層(担当)</th><th>質問</th><th>答えの例</th><th>supreme の作り</th></tr></thead><tbody>'
      '<tr><td><b>risk_tier</b>(T0)</td><td>今すぐ危ない?</td><td>info/caution/danger</td><td>流用移植(ルール+Latch)</td></tr>'
      '<tr><td><b>t1_state</b>(T1)</td><td>近づいてる?</td><td>idle/approach/pass/depart</td><td>流用移植</td></tr>'
      '<tr><td><b>t2_mode</b>(T2)</td><td>いま何の場面?</td><td>会話/緊急/雑踏 等10種</td><td>ルール改良(ヒステリシス)</td></tr>'
      '<tr><td><b>t2_role</b>(T2)</td><td>主役の正体は?</td><td>声/車/警報/不明 等6種</td><td>ルール改良(忠実再現)</td></tr>'
      '<tr><td><b>t2_relation</b>(T2)</td><td>主役との関係は?</td><td>話しかけ/接近 等6種</td><td>ルール改良(較正)</td></tr>'
      '<tr><td><b>t3_hypothesis</b>(T3)</td><td>この数分の物語は?</td><td>安定/会話参加 等10種</td><td><b>学習</b>(エピソード集約)</td></tr>'
      '<tr><td><b>quality_regime</b></td><td>入力(耳)は健全?</td><td>GOOD/DEGRADED/BLOCK</td><td>ルール改良(忠実再現)</td></tr>'
      '<tr><td><b>scene_regime</b></td><td>場面は安定?変化?悪化?</td><td>STABLE/CHANGING/DEGRADING</td><td><b>学習</b>(HGF階層)</td></tr>'
      '</tbody></table>'
      '<div class="qa"><div class="t">用語ミニ辞典</div><ul style="margin:6px 0 0;font-size:14px">'
      '<li><b>GT</b>: 人手の正解ラベル。<b>argmax</b>: 確率分布の最大クラスを答えとして採点。</li>'
      '<li><b>in-sample</b>: 開発に使ったデータ自身での採点(楽観)。<b>CV held-out</b>: 学習に使っていない'
      'fold での採点(<b>正直な汎化推定</b>・lineage-disjoint 5-fold)。<b>封印 verdict</b>: 汚染ゼロの'
      '封印での最終勝敗(<b>本レポートでは未実施</b>=研究者手動)。</li>'
      '<li><b>学習配備版</b>: <code>fit_supreme(練習,GT)→params</code> を <code>run_supreme(params=)</code> に'
      '渡した状態(t3/scene が学習済み)。カルテ・図はこの配備版で描画。</li></ul></div>')

    # ---------- s5 results ----------
    a('<h2 id="s5">5. 結果</h2>')
    a('<h3>5.1 総合 — 旧リファレンスとの apples-to-apples</h3>')
    a('<div class="callout">'
      '<b class="warn">単一の総合値は「顔」にしない</b>(正直さ優先)。学習を含む系では in-sample 総合は'
      f'楽観方向に歪むため(学習 in-sample overall {f(ov_trained)})、'
      f'<b>非学習の確定列(既定 {f(ov_default)})</b>と<b>旧リファレンス(同一 v1.4 {f(ov_old)})</b>、'
      'そして学習層の<b>CV held-out(正直)</b>を併記する。下表が確定値。</div>')
    a('<table><thead><tr><th>層</th><th class="num">旧(v1.4)</th><th class="num">新・既定</th>'
      '<th class="num">新・学習(in-sample)</th><th class="num">新・CV held-out(正直)</th>'
      '<th>honest 判定</th></tr></thead><tbody>')
    verdict = {
        "risk_tier": ("互角", "warn"), "t1_state": ("互角", "warn"),
        "t2_mode": ("互角", "warn"), "t2_role": ("新が優", "good"),
        "t2_relation": ("新が優", "good"), "t3_hypothesis": ("旧が優", "bad"),
        "quality_regime": ("互角", "warn"), "scene_regime": ("新が優", "good"),
    }
    for ly in LAYERS:
        ins = NEW_TRAINED_INSAMPLE.get(ly)
        cv = NEW_CV_HELDOUT.get(ly)
        ins_c = f(ins) if ins is not None else "—"
        cv_c = f(cv) if cv is not None else "—(学習対象外)"
        vt, cls = verdict[ly]
        a(f'<tr><td><b>{ly}</b></td><td class="num">{f(OLD_V14[ly])}</td>'
          f'<td class="num">{f(NEW_DEFAULT[ly])}</td><td class="num">{ins_c}</td>'
          f'<td class="num">{cv_c}</td><td class="{cls}">{vt}</td></tr>')
    a(f'<tr style="font-weight:700;background:#eef4fa"><td>overall(8層平均)</td>'
      f'<td class="num">{f(ov_old)}</td><td class="num">{f(ov_default)}</td>'
      f'<td class="num">{f(ov_trained)}</td><td class="num">—</td>'
      f'<td>互角域(±0.02)</td></tr>')
    a('</tbody></table>')
    a('<div class="lesson"><span class="t">読み方:</span> '
      '<b>強い項目は維持・role/relation は明確に底上げ</b>(新 &gt; 旧)。'
      '<b>scene は学習で win 反転</b>(CV held-out 0.557 &gt; 旧 0.529 ・既定 0.452 から学習で改善)。'
      '<b>t3 だけは旧が優</b>(CV held-out 0.410 &lt; 旧 0.586)。'
      'overall の既定 0.742 が旧 0.761 をわずかに下回るのは、未学習の t3/scene 既定値が低いため — '
      '学習配備で scene は逆転し、t3 は §6.3 のとおり <b>CV 天井</b>に達している。'
      '<b>学習 in-sample 列は楽観値で、勝敗 verdict には使わない。</b></div>')

    a('<h3>5.2 層別プロファイル(図2)</h3>'
      '<div class="fig"><div class="bars" id="layerbars"></div>'
      '<div class="legend"><span><span class="sw" style="background:#1a7f37"></span>強い(0.75以上)</span>'
      '<span><span class="sw" style="background:#e09f3e"></span>中位</span>'
      '<span><span class="sw" style="background:#c0392b"></span>弱い(0.60未満)</span></div>'
      '<div class="cap"><b>図2: 8層の正答率(supreme 学習配備版・in-sample)。</b>'
      '「いまの物理量で決まる質問」(危険・動き・主役)は強く、「文脈・履歴で決まる質問」'
      '(場面・物語)は依然弱い。<b>t3/scene は学習対象</b>で、図は in-sample 値 — '
      f'正直な汎化は CV held-out(scene {f(NEW_CV_HELDOUT["scene_regime"])} / '
      f't3 {f(NEW_CV_HELDOUT["t3_hypothesis"])})。</div></div>')

    a('<h3>5.3 シナリオ×層 ヒートマップ(図3)</h3>'
      '<div class="fig"><div id="heatmap"></div>'
      '<div class="legend"><span>セル=そのシナリオ・層の正答率(%)。</span>'
      '<span><span class="sw" style="background:#1a7f37"></span>100</span>'
      '<span><span class="sw" style="background:#7cb342"></span>75</span>'
      '<span><span class="sw" style="background:#f0ad4e"></span>50</span>'
      '<span><span class="sw" style="background:#e06a4f"></span>25</span>'
      '<span><span class="sw" style="background:#c0392b"></span>0</span></div>'
      '<div class="cap"><b>図3: 20シナリオ × 8層。</b>mode/role/relation は T2 の出力。'
      '<b>縦に赤が並ぶ列(t3・mode の一部)は層ぐるみの構造問題</b>、ポツンと赤いセルは局所事情'
      '(各カルテ参照)。シナリオ名クリックで該当カルテへ。</div></div>')

    a('<h3 id="s55">5.4 シナリオ別カルテ(全20本)— ▶ボタンで時間を再生</h3>')
    a('<p><b>カルテの読み方</b>(全カード共通):</p><ul style="font-size:14px">'
      '<li><b>レーダー(左)</b>: 自分が中心。周囲の音/人/車の方向(上=前)・距離(輪=2/5/10/20/40m)と動き。'
      '<b>色=種別、濃さ=時間</b>。</li>'
      '<li><b>▶再生</b>: レーダー上で動き、右の時系列に<b>赤いタイムバー</b>が連動。</li>'
      '<li><b>入力イベント帯/GT場面帯</b>: 鳴っていた音 / 正解の場面の推移。</li>'
      '<li><b>正誤ストリップ</b>: 8つの答えの正誤(緑=正・赤=誤)。マウスオーバーで「正解→supremeの答え」。</li></ul>')
    a(_CARD_LEGENDS)
    a('<div id="cards"></div>')

    # ---------- s6 diagnosis ----------
    a('<h2 id="s6">6. 診断 — どこで・なぜ間違えるのか / 学習は効いたか</h2>')
    a('<p>弱い層について「ルールが下手か、学習が足りないか、原理的に無理か」を切り分けた。'
      '<b>結論</b>: ①計測で見つけた<b>構造バグは直る</b>(role/relation/mode)、'
      '②<b>学習は scene で汎化した</b>(CV win 反転)、'
      '③<b>t3 は CV 天井</b>で in-sample/CV では詰め切り、残りは構造(上流従属・文脈ラベル)。</p>')

    a('<h3>6.1 まず土台: 再現性とテスト</h3><ul style="font-size:14.5px">'
      '<li><code>run_supreme_scenarios</code> を既定・学習の両 params で各2回走行 → view が'
      '<b>バイト一致</b>(決定的・乱数/時刻なし)。本レポートの数値は分散ゼロ。</li>'
      '<li>テストスイート <b>800 passed / 0 failed</b>。supreme は <b>stdlib のみ</b>(numpy 不使用)。</li></ul>')

    a('<h3>6.2 各層の誤りの中身(混同)</h3>')
    a(f'<h4>(a) t2_role(主役の正体)= {f(la["t2_role"])} — 旧の弱点を底上げ</h4>'
      '<div class="fig"><div class="bars" id="rolebars"></div>'
      '<div class="cap"><b>図4: t2_role の残存誤り(top 混同)。</b>'
      'baseline が object-vehicle 経路で取りこぼしていた正体当てを<b>忠実再現で修正</b>し '
      f'旧 {f(OLD_V14["t2_role"])} → 新 {f(NEW_DEFAULT["t2_role"])}(ADR 0028)。残差は遠方サイレンを'
      '「車」とした正解側のブレが主。</div></div>')

    rel_conf = _top_confusions(scenarios, "t2_relation", 4)
    rel_rows = "".join(
        f'<tr><td>{g} → {p}</td><td class="num">{n}</td></tr>' for (g, p), n in rel_conf)
    a(f'<h4>(b) t2_relation(主役との関係)= {f(la["t2_relation"])} — 較正で大幅改善</h4>'
      '<div class="fig"><table style="max-width:520px"><thead><tr><th>正解 → 答え</th>'
      f'<th class="num">件数</th></tr></thead><tbody>{rel_rows}</tbody></table>'
      f'<div class="cap"><b>図5: t2_relation の top 混同。</b>旧 {f(OLD_V14["t2_relation"])} → '
      f'新 {f(NEW_DEFAULT["t2_relation"])}(+{f(NEW_DEFAULT["t2_relation"]-OLD_V14["t2_relation"])})。'
      'addressing_user/grouped の較正が効いた。残差の approaching↔grouped は上流 T1 依存・'
      'addressing↔near_user は入力分離不能(入力契約拡張は別課題)。</div></div>')

    a(f'<h4>(c) t2_mode(いま何の場面?)= {f(la["t2_mode"])} — 「解釈が降りない」</h4>'
      '<div class="fig"><div class="bars" id="modebars"></div>'
      '<div class="cap"><b>図6: t2_mode の top 混同。</b>柱は<b>残留</b>'
      '(静かになったのに alert_required/emergency と言い続ける)と<b>段階の取り違え</b>。'
      '原因はルールに「取り下げ」が無いこと(サイレンが遠ざかっても加点が続く)。'
      'baseline と同根の構造問題で、無理に合わせると過適合(§6.3 棄却実験)。</div></div>')

    a(f'<h4>(d) t3_hypothesis(この数分の物語?)= {f(la["t3_hypothesis"])}(in-sample)/ '
      f'CV {f(NEW_CV_HELDOUT["t3_hypothesis"])} — 上流従属 + CV 天井</h4>'
      '<div class="fig"><div class="bars" id="t3bars"></div>'
      '<div class="cap"><b>図7: t3 の top 混同。</b>T3 は T2 の答えの集約から物語を選ぶため'
      '<b>T2 が誤れば連鎖</b>。学習で in-sample は底上げできるが、'
      f'<b>CV held-out は {f(NEW_CV_HELDOUT["t3_hypothesis"])} で天井</b>(§6.3 実験3)。</div></div>')

    sc_conf = _top_confusions(scenarios, "scene_regime", 4)
    sc_rows = "".join(
        f'<tr><td>{g} → {p}</td><td class="num">{n}</td></tr>' for (g, p), n in sc_conf)
    a(f'<h4>(e) scene_regime(場面は安定?)= {f(la["scene_regime"])}(in-sample)/ '
      f'CV {f(NEW_CV_HELDOUT["scene_regime"])} — <span class="good">学習で win 反転</span></h4>'
      '<div class="fig"><table style="max-width:520px"><thead><tr><th>正解 → 答え</th>'
      f'<th class="num">件数</th></tr></thead><tbody>{sc_rows}</tbody></table>'
      '<div class="cap"><b>図8: scene の top 混同。</b>悪化/変化を「安定」と見る鈍感は残るが、'
      f'<b>学習配線(<code>fit_supreme</code>)で CV held-out が {f(CV_DEFAULT["scene_regime"])}→'
      f'{f(NEW_CV_HELDOUT["scene_regime"])}</b>(全 fold 正・過適合ゼロ)へ改善し、'
      f'旧 {f(OLD_V14["scene_regime"])} を<b>上回った</b>(ADR 0025)。</div></div>')

    a(f'<h4>(f) quality_regime(入力は健全?)= {f(la["quality_regime"])} — 忠実再現 + BLOCK 構造</h4>'
      '<div class="fig"><div class="cap">'
      f'<b>図9: quality。</b>旧 {f(OLD_V14["quality_regime"])} と互角。誤りは GOOD↔DEGRADED の'
      '惜しい取り違えと、3段階の正解に対し実装が持つ第4段階 BLOCK の構造差(安全側)。'
      '観測式 w_obs を baseline spec 通り(固定0.5→track中央値)に<b>忠実再現</b>した(ADR 0029)。</div></div>')

    a('<h4>(g) 短いシナリオ vs 長いシナリオ(過学習チェック)</h4>'
      '<div class="fig"><div class="bars pair" id="slbars"></div>'
      '<div class="legend"><span><span class="sw" style="background:#7fa8c9"></span>短尺 ns001–015</span>'
      '<span><span class="sw" style="background:#0b5fa5"></span>長尺 ns016–020</span></div>'
      '<div class="cap"><b>図10: 短尺 vs 長尺。</b>長尺で大きく崩れなければ「特定シナリオの暗記」では'
      'ない傍証。学習層の正直な汎化は CV held-out(下記 6.3)で別途確認している。</div></div>')

    a('<h3 id="s63">6.3 学習は効いたか — CV held-out で正直に測る</h3>')
    a('<p>学習(t3/scene)の利得は <b>in-sample(楽観)と CV held-out(正直)を厳密に分けて</b>測った'
      '(lineage-disjoint 5-fold・系統リークなし)。</p>')
    a('<table><thead><tr><th>層</th><th class="num">既定(CV)</th><th class="num">学習(CV held-out)</th>'
      '<th class="num">Δ(正直)</th><th class="num">旧(v1.4)</th><th>結論</th></tr></thead><tbody>'
      f'<tr><td><b>scene_regime</b></td><td class="num">{f(CV_DEFAULT["scene_regime"])}</td>'
      f'<td class="num">{f(NEW_CV_HELDOUT["scene_regime"])}</td>'
      f'<td class="num good">+{f(NEW_CV_HELDOUT["scene_regime"]-CV_DEFAULT["scene_regime"])}</td>'
      f'<td class="num">{f(OLD_V14["scene_regime"])}</td>'
      '<td class="good">win 反転・全 fold 正・過適合0(ADR 0025/0027)</td></tr>'
      f'<tr><td><b>t3_hypothesis</b></td><td class="num">{f(CV_DEFAULT["t3_hypothesis"])}</td>'
      f'<td class="num">{f(NEW_CV_HELDOUT["t3_hypothesis"])}</td>'
      f'<td class="num">+{f(NEW_CV_HELDOUT["t3_hypothesis"]-CV_DEFAULT["t3_hypothesis"])}</td>'
      f'<td class="num">{f(OLD_V14["t3_hypothesis"])}</td>'
      '<td class="warn">改善も旧に届かず・<b>CV 天井 0.5381</b></td></tr></tbody></table>')
    a('<div class="lesson"><span class="t">実験(ADR 0024〜0029・各 cv-*.md):</span><ol style="margin:6px 0 0">'
      '<li><b>学習配線 Phase1</b>: 学習モジュールは当初 <code>fit([])</code> で<b>未学習</b>だった。'
      '<code>core.fit_supreme</code> を <code>run_supreme(params=)</code> に接続し、'
      '<b>scene CV 0.324→0.557(win 反転)</b>。</li>'
      '<li><b>conv 較正</b>(ADR 0027): <code>_W_FLIP_GRID</code> 拡張で <b>t3 CV 0.443→0.538</b>'
      '(overfit gap 0=汎化)。</li>'
      '<li><b>t3 CV 天井</b>(<code>reports/t3-grid-boundary-check.md</code>): grid 境界探索で'
      '<b>CV 天井 0.5381</b>を実証。これ以上は w_conv 拡張で CV が<b>悪化</b>(過適合)。'
      '→ t3 改善は研究者領分。</li>'
      '<li><b>正しく棄却した過適合</b>: 練習増強(cv-augment=label保存で新情報ゼロ)・'
      '合成多様化(cv-author=規則層外)・mode弱会話結線(conv-A-overfit=held-out悪化)・'
      't3 grid拡張 — いずれも <b>CV/論理で棄却</b>。<b>実シナリオは v021_core 20件のみ</b>で、'
      'in-sample の作り込みは過適合に直結する。</li></ol></div>')

    # ---------- s7 ----------
    a('<h2 id="s7">7. 考察 — 限界の正体と、次の一手</h2>'
      '<p><b>底上げできた層</b>(role/relation/scene)は、誤りの原因が「直せる構造」だった — '
      'role/relation は計測で見つけた<b>ルールの忠実再現漏れ</b>、scene は<b>学習配線の欠落</b>。'
      'いずれも計測(混同・CV)で原因を特定して直った。</p>'
      '<p><b>底上げできなかった層</b>(t3)は、誤りの原因が「直せない構造」だった — '
      'T3 は上流 T2 の答えに<b>従属</b>し、かつ正解ラベルが「そのシナリオがどういう<b>物語</b>か」'
      'という<b>文脈</b>で決まる(baseline §6 と同じ発見)。瞬間の物理量からは原理的に届かず、'
      'in-sample で無理に合わせると過適合になる。<b>CV 天井 0.5381 がその限界線</b>。</p>'
      '<p><b>次の一手</b>は計算ではなく<b>データと封印</b>: ①多様な実人手シナリオ(現状 v021_core 20件のみ)、'
      '②<b>汚染ゼロの封印実走</b>(研究者手動・<code>SEALED_EVAL_RUNBOOK.md</code>)で点推定を勝敗に確定。</p>')

    # ---------- s8 ----------
    a('<h2 id="s8">8. この数字をどこまで信じてよいか</h2>'
      '<div class="callout"><b>信頼度の階層</b>(下にいくほど厳しい・正直):<br>'
      '① <b>in-sample</b>(開発セット自身の採点)= <span class="warn">楽観</span>。学習列は二重に楽観。<br>'
      '② <b>CV held-out</b>(lineage-disjoint 5-fold)= <span class="good">正直な汎化推定</span>。'
      '学習層の勝敗はこの列で判定。<br>'
      '③ <b>封印 verdict</b>(汚染ゼロの封印・生涯1回開封)= <b>最終確定</b>・'
      '<span class="bad">本レポートでは未実施</span>(研究者手動)。</div>'
      '<ul style="font-size:14.5px">'
      '<li><b>apples-to-apples の担保</b>: 新旧とも <code>harness.canonical_metric_spec</code> で'
      '同一採点。GT は ADR 0006 の文書化マッピングで v1.4 正準化(正準化不能層はゼロ)。</li>'
      '<li><b>risk_tier の分母規約</b>: 本採点は 210 全件分母(ADR 0012)。baseline カタログは短尺 T0 を'
      'NA 除外(non-null=125)で測る規約のため、<b>baseline カタログ値とは厳密 apples-to-apples ではない</b>'
      '(新旧 supreme 間は同一 210 分母で厳密に揃う)。</li>'
      '<li><b>統計的有意性</b>(U11): 20シナリオ・210フレームの<b>点推定</b>。少数封印の勝敗は誤差棒なしの'
      '点推定であり、有意性検定は今後の課題。</li></ul>')

    # ---------- s9 ----------
    a('<h2 id="s9">9. 今後の課題</h2><ul style="font-size:14.5px">'
      '<li><b>封印本番実走</b>(最優先・研究者手動): supreme は <code>core.run_supreme(封印PSO)</code> で'
      '実走可能。baseline 再計測(risk_tier 210規約・quality v1.4)を取り込み、'
      '<code>guard</code> 発行の開封トークン下で<b>生涯1回</b>開封して項目別 verdict を確定。</li>'
      '<li><b>t3 の研究者領分</b>: 多様な実人手シナリオ + episode_features の分離配線(ns016 群)。</li>'
      '<li><b>relation の入力契約拡張</b>: addressing↔near_user は現状の入力では分離不能。</li>'
      '<li><b>契約フル emit</b>(EPI-T0..T3/CTRL/NOVEL)・Delta 対応・multi-thread(ADR 0022 スコープ外)。</li>'
      '<li><b>統計的有意性</b>(U11)の検定枠組み。</li></ul>')

    # ---------- s10 ----------
    a('<h2 id="s10">10. 再現手順</h2>'
      '<pre><code># テスト(800件 全緑・要 cwd = リポジトリルート)\n'
      'python -m pytest tests/ -q\n\n'
      '# in-sample 評価(supreme vs baseline v1.4・8層)\n'
      'python scripts/run_dev_eval.py\n\n'
      '# CV held-out(正直な汎化・lineage-disjoint 5-fold)\n'
      'python scripts/run_cv_train.py\n\n'
      '# 旧リファレンスを同一 v1.4 で再採点(apples-to-apples)\n'
      'python scripts/run_old_supreme_v14_rescore.py\n\n'
      '# 本レポートの DATA 生成 → HTML 組み立て\n'
      'python scripts/gen_supreme_report.py\n'
      'python scripts/build_supreme_report.py</code></pre>'
      '<p style="font-size:13.5px;color:#5f6b76">supreme は <b>stdlib のみ</b>・決定的(乱数/時刻なし)。'
      'baseline コードは import しない(独立性)。GT 正準化は ADR 0006 の文書化マッピングのみ。</p>')

    return "\n".join(H)


def _acc_all(scenarios, layer):
    pairs = []
    for s in scenarios:
        for c in s["cells"][layer]:
            if c[1] is not None:
                pairs.append((c[1], c[2]))
    if not pairs:
        return 0.0
    return sum(1 for g, p in pairs if g == p) / len(pairs)


# --- supreme アーキ図(SVG・忠実だが baseline より簡潔)---
_ARCH_SVG = r'''<div class="fig">
<svg viewBox="0 0 1180 560" font-family="Segoe UI, sans-serif" font-size="12.5">
 <defs>
  <marker id="ar" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6.5" markerHeight="6.5" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#5f6b76"/></marker>
  <marker id="arg" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#1a7f37"/></marker>
 </defs>
 <!-- 入力 -->
 <rect x="20" y="250" width="92" height="48" rx="8" fill="#eef2f6" stroke="#5f6b76"/><text x="66" y="270" text-anchor="middle" font-weight="600">PSO入力</text><text x="66" y="287" text-anchor="middle" font-size="10" fill="#5f6b76">reader / gate</text>
 <!-- quality gate -->
 <rect x="150" y="160" width="120" height="46" rx="8" fill="#e7f5ea" stroke="#1a7f37"/><text x="210" y="179" text-anchor="middle" font-weight="600" fill="#14572a">quality_regime</text><text x="210" y="196" text-anchor="middle" font-size="10" fill="#14572a">入力は健全か(ルール改良)</text>
 <!-- strong rule layers -->
 <rect x="330" y="40" width="150" height="44" rx="8" fill="#e8f0fa" stroke="#0b5fa5"/><text x="405" y="58" text-anchor="middle" font-weight="600" fill="#0b3a63">T0+Latch → risk_tier</text><text x="405" y="74" text-anchor="middle" font-size="10" fill="#0b3a63">流用移植(強)</text>
 <rect x="330" y="96" width="150" height="44" rx="8" fill="#e8f0fa" stroke="#0b5fa5"/><text x="405" y="114" text-anchor="middle" font-weight="600" fill="#0b3a63">T1 → t1_state</text><text x="405" y="130" text-anchor="middle" font-size="10" fill="#0b3a63">流用移植(強)</text>
 <rect x="330" y="152" width="150" height="44" rx="8" fill="#e8f0fa" stroke="#0b5fa5"/><text x="405" y="170" text-anchor="middle" font-weight="600" fill="#0b3a63">role → t2_role</text><text x="405" y="186" text-anchor="middle" font-size="10" fill="#0b3a63">ルール改良(忠実再現)</text>
 <!-- improved rule layers -->
 <rect x="330" y="208" width="150" height="44" rx="8" fill="#e8f0fa" stroke="#0b5fa5"/><text x="405" y="226" text-anchor="middle" font-weight="600" fill="#0b3a63">mode → t2_mode</text><text x="405" y="242" text-anchor="middle" font-size="10" fill="#0b3a63">ルール改良(ヒステリシス)</text>
 <rect x="330" y="264" width="150" height="44" rx="8" fill="#e8f0fa" stroke="#0b5fa5"/><text x="405" y="282" text-anchor="middle" font-weight="600" fill="#0b3a63">relation → t2_relation</text><text x="405" y="298" text-anchor="middle" font-size="10" fill="#0b3a63">ルール改良(較正)</text>
 <!-- learning layers -->
 <rect x="330" y="330" width="150" height="46" rx="8" fill="#f3eefa" stroke="#7c5cab"/><text x="405" y="349" text-anchor="middle" font-weight="600" fill="#54398a">scene-HGF → scene</text><text x="405" y="366" text-anchor="middle" font-size="10" fill="#54398a">学習(fit_supreme)</text>
 <rect x="330" y="388" width="150" height="46" rx="8" fill="#f3eefa" stroke="#7c5cab"/><text x="405" y="407" text-anchor="middle" font-weight="600" fill="#54398a">t3(episode) → t3</text><text x="405" y="424" text-anchor="middle" font-size="10" fill="#54398a">学習(fit_supreme)</text>
 <!-- integrate / output -->
 <rect x="560" y="180" width="120" height="60" rx="8" fill="#fff8e6" stroke="#b08a00"/><text x="620" y="205" text-anchor="middle" font-weight="600" fill="#6e5600">core 統合</text><text x="620" y="223" text-anchor="middle" font-size="10" fill="#6e5600">8層 view</text>
 <rect x="730" y="186" width="110" height="48" rx="8" fill="#eef2f6" stroke="#5f6b76"/><text x="785" y="206" text-anchor="middle" font-weight="600">harness</text><text x="785" y="223" text-anchor="middle" font-size="10" fill="#5f6b76">8層 micro acc</text>
 <rect x="890" y="186" width="120" height="48" rx="8" fill="#eaf3fb" stroke="#0b5fa5"/><text x="950" y="206" text-anchor="middle" font-weight="600" fill="#0b3a63">8層スコア</text><text x="950" y="223" text-anchor="middle" font-size="10" fill="#0b3a63">in-sample / CV</text>
 <!-- 本流 -->
 <line x1="112" y1="274" x2="148" y2="186" stroke="#5f6b76" stroke-width="1.4" marker-end="url(#ar)"/>
 <path d="M112,266 L300,266 L300,62 L328,62" fill="none" stroke="#5f6b76" stroke-width="1.3" marker-end="url(#ar)"/>
 <line x1="300" y1="118" x2="328" y2="118" stroke="#5f6b76" stroke-width="1.3" marker-end="url(#ar)"/>
 <line x1="300" y1="174" x2="328" y2="174" stroke="#5f6b76" stroke-width="1.3" marker-end="url(#ar)"/>
 <path d="M112,282 L300,282 L300,230 L328,230" fill="none" stroke="#5f6b76" stroke-width="1.3" marker-end="url(#ar)"/>
 <line x1="300" y1="286" x2="328" y2="286" stroke="#5f6b76" stroke-width="1.3" marker-end="url(#ar)"/>
 <path d="M112,290 L300,290 L300,353 L328,353" fill="none" stroke="#5f6b76" stroke-width="1.3" marker-end="url(#ar)"/>
 <path d="M112,290 L300,290 L300,411 L328,411" fill="none" stroke="#5f6b76" stroke-width="1.3" marker-end="url(#ar)"/>
 <!-- 品質レール(緑) -->
 <path d="M270,183 L300,183 L300,150" fill="none" stroke="#1a7f37" stroke-width="1.2" stroke-dasharray="5 3"/>
 <text x="236" y="148" font-size="10" fill="#14572a">品質レール(信頼度)g_global → 各層</text>
 <!-- 層 → core -->
 <path d="M480,62 L520,62 L520,196 L558,196" fill="none" stroke="#0b5fa5" stroke-width="1.2" marker-end="url(#ar)"/>
 <path d="M480,411 L520,411 L520,228 L558,228" fill="none" stroke="#7c5cab" stroke-width="1.2" marker-end="url(#ar)"/>
 <line x1="480" y1="210" x2="558" y2="210" stroke="#5f6b76" stroke-width="1.2" marker-end="url(#ar)"/>
 <line x1="680" y1="210" x2="728" y2="210" stroke="#5f6b76" stroke-width="1.6" marker-end="url(#ar)"/>
 <line x1="840" y1="210" x2="888" y2="210" stroke="#5f6b76" stroke-width="1.6" marker-end="url(#ar)"/>
 <!-- オフライン経路 -->
 <rect x="560" y="330" width="450" height="150" rx="10" fill="#fbfcfd" stroke="#c3ccd5" stroke-dasharray="6 4"/>
 <text x="576" y="350" font-size="11" fill="#5f6b76" font-weight="600">オフライン経路(開発・最終評価)</text>
 <rect x="576" y="362" width="92" height="40" rx="6" fill="#fff" stroke="#5f6b76"/><text x="622" y="386" text-anchor="middle" font-size="11">augment 増強</text>
 <rect x="690" y="362" width="92" height="40" rx="6" fill="#fff" stroke="#5f6b76"/><text x="736" y="386" text-anchor="middle" font-size="11">search 探索</text>
 <rect x="804" y="362" width="92" height="40" rx="6" fill="#fff" stroke="#c0392b"/><text x="850" y="380" text-anchor="middle" font-size="11" fill="#8c2b21">guard</text><text x="850" y="394" text-anchor="middle" font-size="9" fill="#8c2b21">開封トークン</text>
 <rect x="918" y="362" width="84" height="40" rx="6" fill="#fff" stroke="#0b5fa5"/><text x="960" y="380" text-anchor="middle" font-size="11" fill="#0b3a63">sealeval</text><text x="960" y="394" text-anchor="middle" font-size="9" fill="#0b3a63">封印verdict</text>
 <line x1="668" y1="382" x2="688" y2="382" stroke="#5f6b76" stroke-width="1.2" marker-end="url(#ar)"/>
 <line x1="782" y1="382" x2="802" y2="382" stroke="#5f6b76" stroke-width="1.2" marker-end="url(#ar)"/>
 <line x1="896" y1="382" x2="916" y2="382" stroke="#5f6b76" stroke-width="1.2" marker-end="url(#ar)"/>
 <text x="576" y="430" font-size="10.5" fill="#b35900">封印は生涯1回だけ開封(F-014 ガード)。本レポートの数値は in-sample/CV で、この封印 verdict は研究者手動・未実施。</text>
</svg>
<div class="cap"><b>図1: supreme のアーキテクチャ(実装 18 ノードの要約)。</b>
<span style="color:#0b5fa5">青=ルール層</span>(強い項目は baseline から流用移植、mode/relation は計測で発見した誤りを修正)、
<span style="color:#7c5cab">紫=学習層</span>(scene/t3 を <code>fit_supreme</code> で配備)。
品質レール(緑)が各層へ信頼度を配る。下の点線枠はオフライン経路 — 増強→探索→ガード→封印評価。
<b>封印評価は生涯1回開封で、研究者手動・本レポートでは未実施</b>(数値は in-sample/CV)。</div></div>'''

# --- カルテ凡例(baseline と同一の色定義)---
_CARD_LEGENDS = '''<div class="legend" style="margin-bottom:2px"><span><b>レーダーの色:</b></span>
 <span><span class="sw" style="background:#c62828"></span>siren</span>
 <span><span class="sw" style="background:#e67e22"></span>alarm</span>
 <span><span class="sw" style="background:#455a64"></span>vehicle</span>
 <span><span class="sw" style="background:#8d6e63"></span>noise</span>
 <span><span class="sw" style="background:#1e88e5"></span>speech</span>
 <span><span class="sw" style="background:#5e35b1"></span>human</span>
 <span><span class="sw" style="background:#90a4ae"></span>ambient</span></div>
<div class="legend" style="margin-bottom:2px"><span><b>GT場面帯:</b></span>
 <span><span class="sw" style="background:#cfd8dc"></span>静穏</span>
 <span><span class="sw" style="background:#64b5f6"></span>会話きざし</span>
 <span><span class="sw" style="background:#1e88e5"></span>会話中</span>
 <span><span class="sw" style="background:#26a69a"></span>雑踏</span>
 <span><span class="sw" style="background:#ffb74d"></span>前方注意</span>
 <span><span class="sw" style="background:#fb8c00"></span>観察警戒</span>
 <span><span class="sw" style="background:#f4511e"></span>要警戒</span>
 <span><span class="sw" style="background:#c62828"></span>緊急</span>
 <span><span class="sw" style="background:#9575cd"></span>環境変化</span></div>'''


# ===========================================================================
# 組み立て
# ===========================================================================

def main():
    style, appendix, js_full = _extract_parts()
    data = json.load(open(DATA_JSON, encoding="utf-8"))
    scenarios = data["scenarios"]

    # JS の DATA を supreme 実走 DATA に差し替え(lambda 置換でエスケープ問題回避)
    data_json = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    js = re.sub(r"const DATA = \{.*?\};",
                lambda m: "const DATA = " + data_json + ";", js_full, count=1, flags=re.DOTALL)

    # STORY を supreme 自動生成に差し替え
    story = _build_story(scenarios)
    story_js = "const STORY = " + json.dumps(story, ensure_ascii=False) + ";"
    js, n_story = re.subn(r"const STORY = \{.*?\n\};",
                          lambda m: story_js, js, count=1, flags=re.DOTALL)
    if n_story != 1:
        raise SystemExit(f"STORY 置換失敗(n={n_story})")

    # 診断 errBars(role/mode/t3)を supreme top 混同に差し替え
    errbars = _errbars_js(scenarios)
    js, n_eb = re.subn(
        r'errBars\("rolebars",\[.*?\]\s*,\s*\d+\);\s*errBars\("modebars",\[.*?\]\s*,\s*\d+\);\s*errBars\("t3bars",\[.*?\]\s*,\s*\d+\);',
        lambda m: errbars, js, count=1, flags=re.DOTALL)
    if n_eb != 1:
        raise SystemExit(f"errBars 置換失敗(n={n_eb})")

    # 付録の冒頭に supreme 注記を差し込む
    appendix_note = (
        '<div class="callout" style="margin-top:4px">付録Aの各ウィジェットは Plan A 系が共有する機構'
        '(HGF / T0 / T1 / T2 / EMA / scene / t3)の<b>体験版</b>。supreme はこれらに'
        '<b>学習(<code>fit_supreme</code>)</b>を加えた配備版で、機構の直感は新旧で共通です。</div>')
    appendix = appendix.replace("</h2>", "</h2>\n" + appendix_note, 1)

    narrative = _narrative(scenarios)
    footer = ('<footer>研究レポート: planA supreme(新アーキ・学習配備版)・生成 2026-06-15 ・ '
              '数値は in-sample / CV held-out(封印 verdict ではない)・ 真実の源は specs/status.json</footer>')

    html = (
        '<!DOCTYPE html>\n<html lang="ja">\n<head>\n<meta charset="UTF-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        '<title>研究レポート: planA supreme — NS-EPI L04 新アーキ(学習配備版)</title>\n'
        + style + "\n</head>\n<body>\n"
        + narrative + "\n"
        + appendix + "\n</main>\n"
        + footer + "\n"
        + "<script>\n" + js + "\n</script>\n</body>\n</html>\n"
    )

    with open(OUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[done] {OUT_HTML}  ({len(html.encode('utf-8'))} bytes)")
    print(f"  scenarios={len(scenarios)} story={len(story)} STORY置換={n_story} errBars置換={n_eb}")


if __name__ == "__main__":
    main()
