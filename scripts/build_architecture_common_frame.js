"use strict";

const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");
const TARGET_HTML = path.join(ROOT, "docs", "architecture-explainer.html");
const SCENARIO_ID = "std-doorbell_visit-eval-02";
const FRAME_TS = 3.0;
const LAYERS = [
  "risk_tier",
  "t1_state",
  "t2_mode",
  "t2_role",
  "t2_relation",
  "t3_hypothesis",
  "quality_regime",
  "scene_regime",
];
const SOURCES = [
  {
    key: "baseline",
    label: "baseline",
    file: path.resolve(
      ROOT,
      "..",
      "..",
      "baseline",
      "planA-baseline",
      "reports",
      "situations_v1-eval-20260723",
      "frames-baseline.json",
    ),
  },
  {
    key: "supreme2",
    label: "supreme2",
    file: path.resolve(
      ROOT,
      "..",
      "planA-supreme2",
      "reports",
      "situations_v1-eval-20260722",
      "frames-S2.json",
    ),
  },
  {
    key: "supreme8",
    label: "supreme8",
    file: path.resolve(
      ROOT,
      "reports",
      "situations_v1-eval-20260722",
      "frames-N3.json",
    ),
  },
];

const START = "<!-- COMMON_FRAME_TABLE_START -->";
const END = "<!-- COMMON_FRAME_TABLE_END -->";

function fail(message) {
  throw new Error(`[common-frame] ${message}`);
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function readFrame(source) {
  if (!fs.existsSync(source.file)) fail(`入力が見つかりません: ${source.file}`);
  const payload = JSON.parse(fs.readFileSync(source.file, "utf8"));
  const scenario = payload.scenarios && payload.scenarios[SCENARIO_ID];
  if (!scenario) fail(`${source.label} にシナリオ ${SCENARIO_ID} がありません`);
  const frame = scenario.frames.find((entry) => Number(entry[0]) === FRAME_TS);
  if (!frame) fail(`${source.label} に ts=${FRAME_TS} のフレームがありません`);
  if (!Array.isArray(frame) || frame.length !== 3) {
    fail(`${source.label} のフレーム形式が [ts, GT, pred] ではありません`);
  }
  const gt = frame[1];
  const pred = frame[2];
  for (const layer of LAYERS) {
    if (!(layer in gt) || !(layer in pred)) {
      fail(`${source.label} の ${layer} が欠けています`);
    }
  }
  return { ...source, suite: scenario.suite, motif: scenario.motif, gt, pred };
}

function assertSharedGroundTruth(rows) {
  const expected = JSON.stringify(rows[0].gt);
  for (const row of rows.slice(1)) {
    if (JSON.stringify(row.gt) !== expected) {
      fail(`GT が ${rows[0].label} と ${row.label} で一致しません`);
    }
  }
}

function observationSentence(gt) {
  const role = {
    source_speech: "発話音源",
    source_vehicle: "車両音源",
    source_alarm: "警報音源",
    source_human: "人物音源",
    source_object: "物体音源",
    unknown: "正体不明の音源",
  }[gt.t2_role] || "主要音源";
  const relation = {
    addressing_user: "ユーザーへ話しかけ",
    near_user: "ユーザーの近くにあり",
    approaching: "ユーザーへ接近し",
    grouped: "周囲とまとまり",
    departing: "ユーザーから離れ",
    unrelated: "ユーザーとは無関係であり",
  }[gt.t2_relation] || "ユーザーとの関係が定まり";
  const mode = {
    conv_request: "会話要求が生じる",
    conv_ongoing: "会話が継続する",
    surround_activity: "周囲活動が続く",
    forward_caution: "前方への注意が必要になる",
    side_rear_caution: "側方・後方への注意が必要になる",
    alert_required: "警戒が必要になる",
    emergency: "緊急状態になる",
    quiet_standby: "静かな待機状態になる",
    env_change: "環境が変化する",
    uncertain: "状況が不確かになる",
  }[gt.t2_mode] || "場の様相が定まる";
  return `${role}が${relation}、${mode}フレームです。`;
}

function mechanismName(system, layer) {
  const shared = {
    risk_tier: "T0のTTC閾値",
    t1_state: "T1の状態機械",
    t3_hypothesis: "T3の時系列統合",
    quality_regime: "品質の優先順位判定",
    scene_regime: "シーンのHGF判定",
  };
  if (shared[layer]) return shared[layer];
  if (layer.startsWith("t2_")) {
    if (system === "baseline") return "T2の決定規則";
    if (system === "supreme2") return "T2の手調整ルール";
    return "T2のNeuPSL結合MAP";
  }
  return layer;
}

function joinJapanese(items) {
  if (items.length === 1) return items[0];
  if (items.length === 2) return `${items[0]}と${items[1]}`;
  return `${items.slice(0, -1).join("、")}、${items[items.length - 1]}`;
}

function differenceSentence(row) {
  const mismatches = LAYERS.filter((layer) => row.pred[layer] !== row.gt[layer]);
  if (!mismatches.length) return "8層すべてがGTと一致しました。";
  const mechanisms = [
    ...new Set(mismatches.map((layer) => mechanismName(row.key, layer))),
  ];
  return `差は、${joinJapanese(mechanisms)}で生じました。`;
}

function labelStack(values, gt) {
  return `<ul class="frame-labels">${LAYERS.map((layer) => {
    const isPrediction = Boolean(gt);
    const ok = isPrediction ? values[layer] === gt[layer] : true;
    const mark = isPrediction
      ? `<span class="${ok ? "frame-ok" : "frame-ng"}" aria-label="${ok ? "正解" : "不正解"}">${ok ? "✓" : "✕"}</span>`
      : "";
    return `<li><code>${layer}</code><span>${escapeHtml(values[layer])}</span>${mark}</li>`;
  }).join("")}</ul>`;
}

function render(rows) {
  const gt = rows[0].gt;
  const observation = observationSentence(gt);
  const bodyRows = rows
    .map((row, index) => {
      const correct = LAYERS.filter((layer) => row.pred[layer] === gt[layer]).length;
      const leadingCells =
        index === 0
          ? `<td rowspan="${rows.length}" class="frame-observation">${escapeHtml(observation)}</td>`
          : "";
      const gtCell =
        index === 0
          ? `<td rowspan="${rows.length}">${labelStack(gt)}</td>`
          : "";
      return `<tr>
${leadingCells}<th scope="row">${escapeHtml(row.label)}</th>
<td>${labelStack(row.pred, gt)}</td>
${gtCell}<td class="frame-score">${correct}/8一致</td>
<td>${escapeHtml(differenceSentence(row))}</td>
</tr>`;
    })
    .join("\n");

  return `${START}
<div class="tblwrap common-frame-wrap">
<table class="common-frame-table" aria-describedby="common-frame-source">
<thead><tr>
<th scope="col">主要観測</th>
<th scope="col">システム</th>
<th scope="col">8層の最終ラベルと正誤</th>
<th scope="col">GT</th>
<th scope="col">判定</th>
<th scope="col">差が生じた決定機構</th>
</tr></thead>
<tbody>
${bodyRows}
</tbody>
</table>
</div>
<p id="common-frame-source" class="mut">出典は <code>frames-baseline.json</code>、<code>frames-S2.json</code>、<code>frames-N3.json</code> です。<code>${SCENARIO_ID}</code> の <code>ts=${FRAME_TS.toFixed(1)}</code> をビルド時に抽出しました。</p>
${END}`;
}

function replaceRegion(html, generated) {
  const start = html.indexOf(START);
  const end = html.indexOf(END);
  if (start < 0 || end < 0 || end < start) {
    fail(`HTMLに生成領域 ${START} ... ${END} がありません`);
  }
  return html.slice(0, start) + generated + html.slice(end + END.length);
}

function main() {
  const rows = SOURCES.map(readFrame);
  assertSharedGroundTruth(rows);
  const generated = render(rows);
  const html = fs.readFileSync(TARGET_HTML, "utf8");
  const next = replaceRegion(html, generated);
  const checkOnly = process.argv.includes("--check");
  if (checkOnly) {
    if (next !== html) fail("HTMLの共通フレーム表が3つの入力JSONと一致しません");
    console.log(
      `[common-frame] OK: ${SCENARIO_ID} ts=${FRAME_TS.toFixed(1)} / ${rows.length} systems / ${LAYERS.length} layers`,
    );
    return;
  }
  fs.writeFileSync(TARGET_HTML, next, "utf8");
  console.log(
    `[common-frame] updated: ${path.relative(ROOT, TARGET_HTML)} (${rows.length} systems × ${LAYERS.length} layers)`,
  );
}

main();
