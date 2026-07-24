"""docs/architecture-explainer.html の T3 拡充を実装ソースと実測値へ照合します。"""

from __future__ import annotations

import ast
from collections import Counter
import copy
from html.parser import HTMLParser
from html import unescape
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
HTML_PATH = ROOT / "docs" / "architecture-explainer.html"
T3_PATH = ROOT / "src" / "supreme" / "t3.py"
CORE_PATH = ROOT / "src" / "supreme" / "core.py"
FRAMES_PATH = ROOT / "reports" / "situations_v1-eval-20260722" / "frames-N3.json"
SCENARIO_ID = "std-doorbell_visit-eval-02"
TARGET_TS = 3.0
READING_CHARS_PER_MINUTE = 400
BROWSER_HELPER = ROOT / "scripts" / "verify_architecture_browser.mjs"
NUMERIC_TOKEN_RE = re.compile(
    r"(?<![A-Za-z_])[-+]?(?:\d+\.\d+|\d+)(?:[eE][-+]?\d+)?(?![A-Za-z_])"
)
ALL_NUMERIC_TOKEN_RE = re.compile(
    r"[-+]?(?:\d+\.\d+|\d+)(?:[eE][-+]?\d+)?"
)

VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}


def fail(message: str) -> None:
    raise AssertionError(f"[architecture-t3] {message}")


def resolve_expr(expr: ast.AST, values: dict[str, object]) -> object:
    if isinstance(expr, ast.Constant):
        return expr.value
    if isinstance(expr, (ast.Tuple, ast.List, ast.Set)):
        resolved = [resolve_expr(item, values) for item in expr.elts]
        if isinstance(expr, ast.Tuple):
            return tuple(resolved)
        if isinstance(expr, ast.Set):
            return set(resolved)
        return resolved
    if isinstance(expr, ast.Name) and expr.id in values:
        return values[expr.id]
    if isinstance(expr, ast.UnaryOp) and isinstance(expr.op, ast.USub):
        return -resolve_expr(expr.operand, values)
    raise ValueError(f"解決できない式です: {ast.dump(expr)}")


def module_constants(path: Path) -> dict[str, object]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    pending: dict[str, ast.AST] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                pending[target.id] = node.value

    values: dict[str, object] = {}
    changed = True
    while pending and changed:
        changed = False
        for name, expr in list(pending.items()):
            try:
                values[name] = resolve_expr(expr, values)
            except (KeyError, TypeError, ValueError):
                continue
            del pending[name]
            changed = True
    return values


class AuditParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.errors: list[str] = []
        self.ids: list[str] = []
        self.hrefs: list[str] = []
        self.figure_keys: list[str] = []
        self.figure_refs: list[str] = []
        self.idrefs: list[tuple[str, str]] = []
        self.t3_vocab: list[str] = []
        self.mode_cells: list[tuple[float, str]] = []
        self.ratio_rows: list[tuple[str, int, float]] = []
        self.actual_t3: list[str] = []
        self.script_id: str | None = None
        self.script_chunks: dict[str, list[str]] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        amap = dict(attrs)
        if tag not in VOID_TAGS:
            self.stack.append(tag)
        if value := amap.get("id"):
            self.ids.append(value)
        if href := amap.get("href"):
            self.hrefs.append(href)
        if tag == "figure" and (key := amap.get("data-figure")):
            self.figure_keys.append(key)
        if ref := amap.get("data-figure-ref"):
            self.figure_refs.append(ref)
        for attribute in ("aria-labelledby", "aria-describedby", "for", "headers"):
            if value := amap.get(attribute):
                for target in value.split():
                    self.idrefs.append((attribute, target))
        if hypothesis := amap.get("data-t3-hypothesis"):
            self.t3_vocab.append(hypothesis)
        if tag == "span" and amap.get("class", "").find("t3-time-cell") >= 0:
            self.mode_cells.append((float(amap["data-ts"]), str(amap["data-mode"])))
        if mode := amap.get("data-ratio-mode"):
            self.ratio_rows.append(
                (mode, int(str(amap["data-count"])), float(str(amap["data-ratio"])))
            )
        if actual := amap.get("data-actual-t3"):
            self.actual_t3.append(actual)
        if tag == "script" and (script_id := amap.get("id")):
            self.script_id = script_id
            self.script_chunks.setdefault(script_id, [])

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in VOID_TAGS:
            self.stack.pop()

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self.script_id = None
        if tag in VOID_TAGS:
            return
        if not self.stack:
            self.errors.append(f"余分な終了タグ </{tag}> があります")
            return
        opened = self.stack.pop()
        if opened != tag:
            self.errors.append(f"<{opened}> を </{tag}> で閉じています")

    def handle_data(self, data: str) -> None:
        if self.script_id is not None:
            self.script_chunks[self.script_id].append(data)


def parse_html(html: str) -> AuditParser:
    parser = AuditParser()
    parser.feed(html)
    parser.close()
    if parser.stack:
        parser.errors.append(f"未終了タグがあります: {parser.stack[-10:]}")
    return parser


def extract_json_scripts(html: str) -> dict[str, object]:
    pattern = re.compile(
        r'<script\b[^>]*\btype=["\']application/json["\'][^>]*\bid=["\']([^"\']+)["\'][^>]*>'
        r"([\s\S]*?)</script>"
        r"|<script\b[^>]*\bid=[\"\']([^\"\']+)[\"\'][^>]*\btype=[\"\']application/json[\"\'][^>]*>"
        r"([\s\S]*?)</script>",
        re.IGNORECASE,
    )
    out: dict[str, object] = {}
    for match in pattern.finditer(html):
        script_id = match.group(1) or match.group(3)
        payload = match.group(2) if match.group(1) else match.group(4)
        out[script_id] = json.loads(payload)
    return out


def baseline_html() -> str:
    command = [
        "git",
        "-c",
        f"safe.directory={ROOT.as_posix()}",
        "show",
        "HEAD:docs/architecture-explainer.html",
    ]
    return subprocess.check_output(command, cwd=ROOT, text=True, encoding="utf-8")


def stable_numeric_text(html: str) -> str:
    """数値照合の対象本文を、節移動と静的アンカー化に耐える形へ整えます。"""

    text = re.sub(r"<style>[\s\S]*?</style>", "", html, flags=re.IGNORECASE)
    text = re.sub(r"<script\b[\s\S]*?</script>", "", text, flags=re.IGNORECASE)
    text = re.sub(
        r'<section class="reading-guide"[\s\S]*?</section>',
        "<!-- READING GUIDE NORMALIZED -->",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r'<nav class="toc-box"[\s\S]*?</nav>',
        "<!-- TOC NORMALIZED -->",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r'<aside class="chapter-rail"[\s\S]*?</aside>',
        "<!-- RAIL NORMALIZED -->",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r'<section class="textbook-box" id="chapter-4-map"[\s\S]*?</section>',
        "<!-- CHAPTER MAP NORMALIZED -->",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r'(<h2 id="chapter-6"[\s\S]*?<p class="chapter-goal">[\s\S]*?</p>)\s*<ul>[\s\S]*?</ul>',
        r"\1<!-- CHAPTER 6 INTERPRETATION NORMALIZED -->",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r'<div><dt>(?:evalの)?契約違反</dt><dd>[\s\S]*?</dd></div>',
        "<!-- CONTRACT REJECTION SUMMARY NORMALIZED -->",
        text,
        count=1,
    )
    text = re.sub(
        r'<div class="readnote"><b>操作方法(?:を説明します)?。</b>[\s\S]*?</div>',
        "<!-- WIRING INTERACTION GUIDE NORMALIZED -->",
        text,
        count=1,
    )
    text = re.sub(
        r'<aside class="why-box">\s*<div class="box-title">結合をどのように'
        r'イメージすればよいでしょうか。</div>[\s\S]*?</aside>',
        "<!-- DELETED CROSSWORD ANALOGY NORMALIZED -->",
        text,
        count=1,
    )
    text = text.replace(
        "8 層のなかで pooled accuracy が最も高く、",
        "",
    )
    text = re.sub(
        r'<h3 id="common-frame-comparison">[\s\S]*?'
        r'<!-- COMMON_FRAME_TABLE_START -->',
        "<!-- COMMON FRAME INTRO NORMALIZED -->"
        "<!-- COMMON_FRAME_TABLE_START -->",
        text,
        count=1,
    )
    text = re.sub(
        r"<!-- COMMON_FRAME_TABLE_START -->[\s\S]*?<!-- COMMON_FRAME_TABLE_END -->",
        "<!-- COMMON FRAME NORMALIZED -->",
        text,
    )
    text = re.sub(
        r"<!-- SCORE_WALK_ROWS_START -->[\s\S]*?<!-- SCORE_WALK_ROWS_END -->",
        "<!-- SCORE WALK NORMALIZED -->",
        text,
    )
    # The baseline has no score markers, so normalize its old hard-coded tbody.
    text = re.sub(
        r'(<table class="score-match-table"[\s\S]*?<tbody>)[\s\S]*?(</tbody>\s*</table>)',
        r"\1<!-- SCORE WALK NORMALIZED -->\2",
        text,
        count=1,
        flags=re.IGNORECASE,
    )
    text = re.sub(r'<span class="figure-number"[\s\S]*?</span>', "", text)
    text = re.sub(
        r'(<a\b[^>]*\bdata-figure-ref="[^"]+"[^>]*>)[\s\S]*?(</a>)',
        r"\1図\2",
        text,
    )
    # 第7章から削除した項目は、直前のGT由来説明および第6章の比較規約と同義でした。
    text = re.sub(
        r"<li><b>GT は規則で生成されています。</b>[\s\S]*?</li>",
        "<!-- DUPLICATE GT NOTE NORMALIZED -->",
        text,
        count=1,
    )
    text = re.sub(
        r"<h3>3段学習図の内部を4段のレシピとして確認します</h3>\s*"
        r"<p>次の4段は独立した別フレームではなく、上の3段学習図を"
        r"詳しく読み替えた内部レシピです。[\s\S]*?</p>",
        "<!-- INTERNAL LEARNING RECIPE INTRO NORMALIZED -->",
        text,
        count=1,
    )
    text = re.sub(
        r"<p>T2 の各層は、次の 4 段のパイプラインで学習されます。"
        r"[\s\S]*?</p>",
        "<!-- INTERNAL LEARNING RECIPE INTRO NORMALIZED -->",
        text,
        count=1,
    )
    text = text.replace(
        "<h3>学習レシピ（4 段のパイプライン）</h3>",
        "<!-- INTERNAL LEARNING RECIPE HEADING NORMALIZED -->",
    )
    text = re.sub(
        r"<p>3段学習図のbilevel段に記したMoreau包絡は値関数を"
        r"平滑化する仕組みであり、[\s\S]*?</p>",
        "<!-- MOREAU DISTINCTION NORMALIZED -->",
        text,
        count=1,
    )
    text = re.sub(r"第[1-7]章", "章", text)
    text = re.sub(
        r"([A-Za-z][A-Za-z0-9_-]*-(?:eval|train)-)\d+",
        r"\1SCENARIO",
        text,
    )
    # 属性中の章・図ID、SVG座標、アンカー先は測定値ではありません。表示本文だけを
    # 比べることで、JS採番から静的ID参照への変更を数値差分として誤検出しません。
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    return text


def stable_numeric_tokens(html: str) -> Counter[str]:
    """本文に残る検証済み数値の順序非依存な多重集合を返します。"""

    return Counter(
        NUMERIC_TOKEN_RE.findall(stable_numeric_text(html))
    )


def check_inline_javascript(html: str) -> int:
    blocks = re.findall(
        r"<script(?![^>]*\bsrc=)(?![^>]*application/json)[^>]*>([\s\S]*?)</script>",
        html,
        flags=re.IGNORECASE,
    )
    for index, block in enumerate(blocks, start=1):
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".js", encoding="utf-8", delete=False
            ) as handle:
                handle.write(block)
                temp_path = Path(handle.name)
            subprocess.run(
                ["node", "--check", str(temp_path)],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            )
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
    return len(blocks)


def hex_rgb(value: str) -> tuple[float, float, float]:
    value = value.lstrip("#")
    if len(value) == 3:
        value = "".join(char * 2 for char in value)
    return tuple(int(value[i : i + 2], 16) / 255 for i in (0, 2, 4))


def luminance(value: str) -> float:
    def channel(component: float) -> float:
        return component / 12.92 if component <= 0.04045 else ((component + 0.055) / 1.055) ** 2.4

    red, green, blue = hex_rgb(value)
    return 0.2126 * channel(red) + 0.7152 * channel(green) + 0.0722 * channel(blue)


def contrast(foreground: str, background: str) -> float:
    lighter, darker = sorted((luminance(foreground), luminance(background)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def theme_variables(html: str) -> dict[str, dict[str, str]]:
    light_blocks = re.findall(r":root\{([\s\S]*?)\}", html)
    dark_blocks = re.findall(r':root\[data-theme="dark"\]\{([\s\S]*?)\}', html)
    if not light_blocks or not dark_blocks:
        fail("テーマ変数を抽出できません")

    def variables(blocks: list[str]) -> dict[str, str]:
        out: dict[str, str] = {}
        for block in blocks:
            out.update(
                dict(re.findall(r"(--[\w-]+)\s*:\s*(#[0-9a-fA-F]{3,8})", block))
            )
        return out

    light = variables(light_blocks)
    dark = dict(light)
    dark.update(variables(dark_blocks))
    return {"light": light, "dark": dark}


def check_contrast(html: str) -> dict[str, float]:
    themes = theme_variables(html)
    pairs = [
        ("--ink", "--bg"),
        ("--ink", "--card"),
        ("--ink", "--card2"),
        ("--mut", "--bg"),
        ("--mut", "--card"),
        ("--accent", "--bg"),
        ("--accent", "--card"),
        ("--accent-on", "--accent"),
        ("--accent-on", "--good"),
    ]
    minima: dict[str, float] = {}
    for theme_name, variables in themes.items():
        ratios = []
        for foreground, background in pairs:
            if foreground not in variables or background not in variables:
                fail(f"{theme_name} の配色変数 {foreground}/{background} がありません")
            ratio = contrast(variables[foreground], variables[background])
            ratios.append(ratio)
            if ratio < 4.5:
                fail(
                    f"{theme_name} の {foreground}/{background} がコントラスト不足です: {ratio:.3f}"
                )
        minima[theme_name] = min(ratios)
    return minima


def extract_baseline_common_frame(html: str) -> dict[str, object]:
    section_match = re.search(
        r"<!-- COMMON_FRAME_TABLE_START -->([\s\S]*?)<!-- COMMON_FRAME_TABLE_END -->",
        html,
    )
    if not section_match:
        fail("ベースラインの共通フレーム表を抽出できません")
    section = section_match.group(1)

    def labels(fragment: str) -> dict[str, str]:
        return dict(
            re.findall(
                r"<li><code>([^<]+)</code><span>([^<]+)</span>",
                fragment,
            )
        )

    systems: list[dict[str, object]] = []
    names = ["baseline", "supreme2", "supreme8"]
    for index, name in enumerate(names):
        start = section.index(f'<th scope="row">{name}</th>')
        end = (
            section.index(f'<th scope="row">{names[index + 1]}</th>', start)
            if index + 1 < len(names)
            else section.index("</tbody>", start)
        )
        row = section[start:end]
        labels_match = re.search(
            r'<td><ul class="frame-labels">([\s\S]*?)</ul></td>',
            row,
        )
        if not labels_match:
            fail(f"ベースラインの{name}ラベルを抽出できません")
        mechanism_match = re.findall(r"<td>(差は、[\s\S]*?)</td>", row)
        if not mechanism_match:
            fail(f"ベースラインの{name}機構説明を抽出できません")
        systems.append(
            {
                "id": name,
                "labels": labels(labels_match.group(1)),
                "mechanism": unescape(re.sub(r"<[^>]+>", "", mechanism_match[-1])),
            }
        )

    gt_match = re.search(
        r'<td rowspan="3"><ul class="frame-labels">([\s\S]*?)</ul></td>',
        section,
    )
    observation_match = re.search(
        r'<td rowspan="3" class="frame-observation">([\s\S]*?)</td>',
        section,
    )
    source_match = re.search(
        r"<code>(std-doorbell_visit-eval-02)</code> の <code>ts=([0-9.]+)</code>",
        section,
    )
    if not gt_match or not observation_match or not source_match:
        fail("ベースラインのGT、観測、フレームIDを抽出できません")
    return {
        "scenario_id": source_match.group(1),
        "ts": float(source_match.group(2)),
        "observation": unescape(re.sub(r"<[^>]+>", "", observation_match.group(1))),
        "layers": [
            "risk_tier",
            "t1_state",
            "t2_mode",
            "t2_role",
            "t2_relation",
            "t3_hypothesis",
            "quality_regime",
            "scene_regime",
        ],
        "gt": labels(gt_match.group(1)),
        "systems": systems,
    }


def check_static_book_model(html: str, parser: AuditParser) -> dict[str, int]:
    required_order = [
        "learning-objectives-title",
        "measurement-contract-title",
        "reading-guide-title",
        "toc-title",
        "quick-summary",
        "chapter-1",
        "chapter-2",
        "chapter-3",
        "chapter-4",
        "chapter-5",
        "chapter-6",
        "chapter-7",
        "glossary",
        "separate-arena-record",
    ]
    positions = {}
    for target in required_order:
        if target not in parser.ids:
            fail(f"必須の静的セクション #{target} がありません")
        positions[target] = parser.ids.index(target)
    if [positions[target] for target in required_order] != sorted(positions.values()):
        fail("前付、第1〜7章、用語集、付録のソース順が指定と違います")

    chapter_numbers = [
        int(value)
        for value in re.findall(
            r'<h2\b[^>]*\bdata-chapter[^>]*>第([1-7])章',
            html,
        )
    ]
    if chapter_numbers != list(range(1, 8)):
        fail(f"静的章番号が単調ではありません: {chapter_numbers}")

    expected_toc = [
        "#chapter-1",
        "#chapter-2",
        "#chapter-3",
        "#chapter-4",
        "#chapter-5",
        "#chapter-6",
        "#chapter-7",
        "#glossary",
        "#separate-arena-record",
    ]
    toc_match = re.search(r'<ol id="toc">([\s\S]*?)</ol>', html)
    if not toc_match:
        fail("静的目次がありません")
    toc_hrefs = re.findall(r'href="(#[^"]+)"', toc_match.group(1))
    if toc_hrefs != expected_toc:
        fail(f"目次の収録対象または順序が違います: {toc_hrefs}")

    local_orders = [
        ["fig-output-catalog", "predicate-label-relation", "t2-evaluation-targets"],
        ["one-screen-summary", "overview-flow", "fig-evidence-to-label-map", "fig-system-detail"],
        [
            "chapter-4-map",
            "intro-psl",
            "intro-neural-predicate",
            "intro-grounding",
            "intro-map",
            "joint-map-explained",
            "real-wiring-title",
            "why-convex-optimization",
            "learning-flow-title",
            "why-nn-convex-learning",
        ],
        ["common-frame-comparison", "system-specific-trace"],
    ]
    for ordered_ids in local_orders:
        local_positions = [parser.ids.index(target) for target in ordered_ids]
        if local_positions != sorted(local_positions):
            fail(f"節の物理順が違います: {ordered_ids}")

    expected_figure_keys = [
        "output-catalog",
        "predicate-label-anatomy",
        "t2-evaluation-flow",
        "overview-flow",
        "evidence-to-label-map",
        "system-detail",
        "layer-overview",
        "t3-window",
        "toy-psl",
        "toy-predicate",
        "toy-grounding",
        "toy-map",
        "joint-map-missing-siren",
        "joint-map-ropes",
        "real-wiring",
        "convex-energy-landscape",
        "toy-convex-steps",
        "learning-flow",
        "envelope-two-ways",
        "real-trace",
        "suite-overall",
    ]
    if parser.figure_keys != expected_figure_keys:
        fail(f"図キーの全ソース順が違います: {parser.figure_keys}")
    semantic_count_captions = {
        "fig-system-detail": r"21\s*ノードと\s*31\s*エッジ",
        "fig-real-wiring": r"41\s*ノードと\s*74\s*配線",
    }
    for figure_id, count_pattern in semantic_count_captions.items():
        figure_match = re.search(
            rf'<figure\b[^>]*\bid="{re.escape(figure_id)}"[^>]*>([\s\S]*?)</figure>',
            html,
        )
        figure_text = (
            unescape(re.sub(r"<[^>]+>", " ", figure_match.group(1)))
            if figure_match
            else ""
        )
        if not re.search(count_pattern, figure_text):
            fail(f"{figure_id}のノード・配線数の説明が正しい図にありません")

    chapter_section_ids = {
        1: ["fig-output-catalog", "predicate-label-relation", "t2-evaluation-targets"],
        2: ["one-screen-summary", "overview-flow", "fig-evidence-to-label-map", "fig-system-detail"],
        3: ["fig-layer-overview", "layer-t2_relation", "fig-t3-window"],
        4: [
            "chapter-4-map",
            "intro-psl",
            "intro-neural-predicate",
            "intro-grounding",
            "intro-map",
            "joint-map-explained",
            "real-wiring-title",
            "why-convex-optimization",
            "learning-flow-title",
            "t3-detailed-rules",
            "why-nn-convex-learning",
        ],
        5: ["common-frame-comparison", "system-specific-trace", "fig-real-trace"],
        6: ["fig-suite-overall"],
    }
    for chapter, section_ids in chapter_section_ids.items():
        lower = parser.ids.index(f"chapter-{chapter}")
        upper_target = f"chapter-{chapter + 1}" if chapter < 7 else "glossary"
        upper = parser.ids.index(upper_target)
        misplaced = [
            section_id
            for section_id in section_ids
            if not lower < parser.ids.index(section_id) < upper
        ]
        if misplaced:
            fail(f"第{chapter}章の境界外に節があります: {misplaced}")

    for chapter in range(1, 8):
        next_id = f"chapter-{chapter + 1}" if chapter < 7 else "glossary"
        chapter_match = re.search(
            rf'<h2 id="chapter-{chapter}"[\s\S]*?(?=<h2 id="{next_id}")',
            html,
        )
        if not chapter_match:
            fail(f"第{chapter}章の静的範囲を抽出できません")
        segment = chapter_match.group(0)
        summary = segment.rfind('class="chapter-summary"')
        checkpoint = segment.rfind('class="check-block"')
        if summary < 0 or checkpoint < summary:
            fail(f"第{chapter}章の章末まとめ・確認問題の順が違います")

    hero_match = re.search(
        r'<figure\b[^>]*\bid="one-screen-summary"[^>]*>([\s\S]*?)</figure>',
        html,
    )
    if not hero_match:
        fail("第2章のヒーロー図がありません")
    hero_opening = hero_match.group(0).split(">", 1)[0]
    if "data-figure" in hero_opening or "figure-number" in hero_match.group(1):
        fail("ヒーロー図は無番号でなければなりません")

    figures = list(
        re.finditer(
            r'<figure\b(?=[^>]*\bdata-figure="([^"]+)")[^>]*>[\s\S]*?</figure>',
            html,
        )
    )
    number_by_key: dict[str, int] = {}
    for expected, figure in enumerate(figures, start=1):
        opening = figure.group(0).split(">", 1)[0]
        key_match = re.search(r'data-figure="([^"]+)"', opening)
        id_match = re.search(r'id="([^"]+)"', opening)
        number_match = re.search(
            r'<figcaption[^>]*><span class="figure-number" data-figure-number="(\d+)">'
            r"図(\d+)。</span>",
            figure.group(0),
        )
        if not key_match or not id_match or not number_match:
            fail(f"図{expected}の静的キー、ID、figcaption番号が不足しています")
        key = key_match.group(1)
        if id_match.group(1) != f"fig-{key}" or re.fullmatch(r"fig-\d+", id_match.group(1)):
            fail(f"図IDが意味ベースではありません: {id_match.group(1)}")
        values = [int(number_match.group(1)), int(number_match.group(2))]
        if values != [expected, expected]:
            fail(f"図番号がDOM順に単調ではありません: {key} -> {values}")
        number_by_key[key] = expected

    ref_pattern = re.compile(
        r'<a\b(?=[^>]*\bdata-figure-ref="([^"]+)")[^>]*\bhref="([^"]+)"[^>]*>'
        r"図(\d+)</a>"
    )
    refs = list(ref_pattern.finditer(html))
    if len(refs) != len(parser.figure_refs):
        fail("図参照に静的な表示番号、href、キーが揃っていません")
    for ref in refs:
        key, href, number_text = ref.groups()
        expected = number_by_key.get(key)
        if expected is None or href != f"#fig-{key}" or int(number_text) != expected:
            fail(f"図参照が不整合です: key={key}, href={href}, number={number_text}")

    forbidden_js = [
        'fig.id="fig-"',
        "caption.insertBefore",
        'document.createElement("ol")',
        'document.createElement("figure")',
        "chapterOrder.forEach",
        "frontmatterOrder.forEach",
        "appendOrdered",
    ]
    for token in forbidden_js:
        if token in html:
            fail(f"実行時の配置・採番処理が残っています: {token}")

    if "クロスワード" in html or "data-extreme=" in html:
        fail("削除対象の比喩または最高/最低suite定型文が残っています")
    if html.count('class="misconception-box"') < 1:
        fail("誤解boxが失われています")
    if (
        html.count('id="predicate-label-misconception"') != 1
        or "述語出力をそのままラベルにする後処理ではありません" in html
        or "MAP は述語の出力を後処理で微修正するのでしょうか" in html
    ):
        fail("述語出力と最終ラベルを混同する同義の誤解boxが統合されていません")
    required_markers = [
        "OUTPUT_CATALOG_START",
        "OUTPUT_CATALOG_END",
        "SCORE_WALK_ROWS_START",
        "SCORE_WALK_ROWS_END",
        "COMMON_FRAME_TABLE_START",
        "COMMON_FRAME_TABLE_END",
    ]
    if any(html.count(marker) != 1 for marker in required_markers):
        fail("JSON生成領域のマーカーコメントが不足または重複しています")

    return {"chapters": len(chapter_numbers), "figures": len(figures), "toc": len(toc_hrefs)}


def check_directional_references(html: str) -> int:
    """再配置後の前方・後方参照が、実際のソース方向と一致するか検査します。"""

    forbidden = [
        "結合MAPの節で見た",
        "前に説明した凸最適化",
        "下で説明する 1 フレーム",
        "後述の共通フレーム",
        "前に説明した",
        "前述の",
        "下で説明する",
        "結合MAPの節で見た",
    ]
    stale = [phrase for phrase in forbidden if phrase in html]
    if stale:
        fail(f"再配置前の方向参照が残っています: {stale}")

    checks = [
        ('href="#joint-map-explained">第4章で説明する結合MAP</a>', "joint-map-explained", "later"),
        ('次節の<a href="#why-convex-optimization">凸最適化</a>', "why-convex-optimization", "later"),
        ('href="#system-specific-trace">第5章の別フレーム固有トレース</a>', "system-specific-trace", "later"),
        ('href="#chapter-6">第6章</a>に集約しています', "chapter-6", "later"),
        ('<b>凸最適化の節からつなげます。</b>', "why-convex-optimization", "earlier"),
        ("上の3段学習図を詳しく読み替えた内部レシピです", "fig-learning-flow", "earlier"),
        ('href="#predicate-label-misconception">述語出力と最終ラベル', "predicate-label-misconception", "earlier"),
        ('href="#layer-t2_relation">第3章のrelationカード</a>', "layer-t2_relation", "earlier"),
    ]
    for marker, target, direction in checks:
        source = html.find(marker)
        target_match = re.search(rf'\bid="{re.escape(target)}"', html)
        if source < 0 or not target_match:
            fail(f"方向参照の検査対象がありません: {marker} -> #{target}")
        is_later = target_match.start() > source
        if (direction == "later" and not is_later) or (
            direction == "earlier" and is_later
        ):
            fail(f"方向参照が逆向きです: {marker} -> #{target}")

    chapter_four = html.index('id="chapter-4"')
    chapter_links = [
        match.start()
        for match in re.finditer(
            r'href="#chapter-4">さらに詳しく、NeuPSLの入門・配線・学習を'
            r"第4章で確認します。</a>",
            html,
        )
    ]
    if len(chapter_links) != 3 or any(source >= chapter_four for source in chapter_links):
        fail("第3章T2カードから第4章への参照方向が違います")
    return len(checks) + len(chapter_links)


def check_complete_prose(html: str, page_data: dict[str, object]) -> tuple[int, int]:
    """本文を完全文にし、用語集の定義を一文へ限定します。"""

    without_scripts = re.sub(
        r"<script\b[\s\S]*?</script>",
        "",
        html,
        flags=re.IGNORECASE,
    )
    toc_free = re.sub(
        r'<nav class="toc-box"[\s\S]*?</nav>',
        "",
        without_scripts,
        flags=re.IGNORECASE,
    )

    def visible(fragment: str) -> str:
        return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", "", fragment))).strip()

    paragraphs = [
        visible(fragment)
        for fragment in re.findall(r"<p\b[^>]*>([\s\S]*?)</p>", without_scripts)
    ]
    list_items = [
        visible(fragment)
        for fragment in re.findall(r"<li\b[^>]*>([\s\S]*?)</li>", toc_free)
    ]
    incomplete = [
        text
        for text in paragraphs + list_items
        if text and not re.search(r"[。？！!?](?:[」』])?$", text)
    ]
    if incomplete:
        fail(f"です・ます完全文になっていない本文があります: {incomplete[:5]}")
    impolite = [
        text
        for text in paragraphs + list_items
        if text
        and not (text.startswith("「") and text.endswith("」"))
        and not re.search(r"(?:です|ます|ません|ました|でした)", text[-100:])
    ]
    if impolite:
        fail(f"本文の終止がです・ます調ではありません: {impolite[:5]}")

    glossary_match = re.search(
        r'<dl class="glossary">([\s\S]*?)</dl>',
        html,
    )
    if not glossary_match:
        fail("用語集を抽出できません")
    definitions = [
        visible(fragment)
        for fragment in re.findall(
            r"<dd>([\s\S]*?)</dd>",
            glossary_match.group(1),
        )
    ]
    invalid_definitions = [
        definition
        for definition in definitions
        if definition.count("。") != 1 or not definition.endswith("。")
    ]
    if invalid_definitions:
        fail(f"用語集に一文ではない定義があります: {invalid_definitions[:5]}")

    responses = [str(node["resp"]) for node in page_data["nodes"]]
    invalid_responses = [
        response
        for response in responses
        if response.count("。") != 1 or not response.endswith("。")
    ]
    if invalid_responses:
        fail(f"全体図の責務説明に完全文でない項目があります: {invalid_responses[:5]}")
    return len(paragraphs) + len(list_items) + len(responses), len(definitions)


def check_all_idrefs(parser: AuditParser) -> int:
    ids = set(parser.ids)
    unresolved = [
        f"{attribute}={target}"
        for attribute, target in parser.idrefs
        if target not in ids
    ]
    if unresolved:
        fail(f"未解決のID参照があります: {unresolved[:10]}")
    return len(parser.idrefs)


def check_reading_guide_source(html: str) -> list[dict[str, object]]:
    cards = re.findall(
        r'<a class="guide-card" href="(#[^"]+)" '
        r'data-guide-targets="([^"]+)" data-reading-minutes="(\d*)">'
        r"<b>[^<]*理解時間・約(\d+)分</b><span>([\s\S]*?)</span></a>",
        html,
    )
    if len(cards) != 3:
        fail("読み方ガイドは3パスでなければなりません")
    parsed = []
    expected_chapter_mentions = {
        "#quick-summary": [1, 6, 7],
        "#chapter-1": [1, 3],
        "#chapter-4": [4, 5],
    }
    expected_targets = {
        "#quick-summary": ["quick-summary", "chapter-1", "chapter-6", "chapter-7"],
        "#chapter-1": ["chapter-1", "chapter-2", "chapter-3"],
        "#chapter-4": ["chapter-4", "chapter-5"],
    }
    for href, targets_text, minutes_text, shown_text, description in cards:
        targets = targets_text.split(",")
        if href != f"#{targets[0]}":
            fail(f"読み方ガイドのリンクがパス先頭と違います: {href} != #{targets[0]}")
        if expected_targets.get(href) != targets:
            fail(f"読み方ガイド {href} の固定パスが違います: {targets}")
        for target in targets:
            if f'id="{target}"' not in html:
                fail(f"読み方ガイドの対象 #{target} がありません")
        if not minutes_text:
            fail(f"読み方ガイド {href} の理解時間が未確定です")
        if int(minutes_text) != int(shown_text):
            fail(
                f"読み方ガイド {href} の属性と表示時間が違います: "
                f"{minutes_text} != {shown_text}"
            )
        chapter_mentions = [int(value) for value in re.findall(r"第(\d+)章", description)]
        if chapter_mentions != expected_chapter_mentions[href]:
            fail(
                f"読み方ガイド {href} の章表記がパスと違います: "
                f"{chapter_mentions}"
            )
        parsed.append(
            {"href": href, "targets": targets, "minutes": int(minutes_text)}
        )
    return parsed


def find_chrome() -> Path:
    candidates = [
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    discovered = shutil.which("chrome") or shutil.which("msedge")
    if discovered:
        return Path(discovered)
    fail("実ブラウザ検証に使うChromeまたはEdgeがありません")
    raise AssertionError


def check_browser_runtime(
    expected_wiring_nodes: int,
    expected_wiring_edges: int,
    expected_mermaid_nodes: int,
    expected_mermaid_edges: int,
    expected_common: dict[str, object],
    reading_source: list[dict[str, object]] | None,
) -> list[dict[str, object]]:
    chrome = find_chrome()
    if not BROWSER_HELPER.exists():
        fail(f"ブラウザ検証ヘルパーがありません: {BROWSER_HELPER}")
    with tempfile.TemporaryDirectory(
        prefix="architecture-browser-",
        ignore_cleanup_errors=True,
    ) as temp_name:
        profile = Path(temp_name)
        process = subprocess.Popen(
            [
                str(chrome),
                "--headless=new",
                "--remote-debugging-port=0",
                "--remote-allow-origins=*",
                f"--user-data-dir={profile}",
                "--allow-file-access-from-files",
                "--disable-extensions",
                "--disable-gpu",
                "--disable-software-rasterizer",
                "--no-sandbox",
                "--no-first-run",
                "--no-default-browser-check",
                "about:blank",
            ],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            active_port = profile / "DevToolsActivePort"
            deadline = time.monotonic() + 15
            while not active_port.exists() and time.monotonic() < deadline:
                if process.poll() is not None:
                    fail("ChromeがDevTools待受前に終了しました")
                time.sleep(0.1)
            if not active_port.exists():
                fail("ChromeのDevToolsポートが起動しませんでした")
            port = active_port.read_text(encoding="utf-8").splitlines()[0]
            page_url = HTML_PATH.resolve().as_uri()
            request = Request(
                f"http://127.0.0.1:{port}/json/new?about:blank",
                method="PUT",
            )
            with urlopen(request, timeout=10) as response:
                target = json.loads(response.read().decode("utf-8"))
            try:
                run = subprocess.run(
                    [
                        "node",
                        str(BROWSER_HELPER),
                        target["webSocketDebuggerUrl"],
                        page_url,
                        str(READING_CHARS_PER_MINUTE),
                    ],
                    cwd=ROOT,
                    check=True,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=60,
                )
            except subprocess.CalledProcessError as error:
                fail(
                    "ブラウザ検証ヘルパーが失敗しました: "
                    + (error.stderr or error.stdout or str(error)).strip()
                )
            result = json.loads(run.stdout)
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)

    if result["runtimeErrors"]:
        fail(f"実ブラウザのJSエラーがあります: {result['runtimeErrors'][:8]}")
    cases = result["cases"]
    if len(cases) != 4:
        fail(f"ブラウザ検証ケースが4件ではありません: {len(cases)}")
    for case in cases:
        label = f"{case['width']}px/{case['theme']}"
        if case["activeTheme"] != case["theme"]:
            fail(f"{label}で実際のテーマ属性が一致しません: {case['activeTheme']}")
        if case["scrollWidth"] > case["clientWidth"] or case["overflow"]:
            fail(
                f"{label}で横はみ出しがあります: "
                f"scroll={case['scrollWidth']}/{case['clientWidth']} "
                f"elements={case['overflow'][:4]}"
            )
        if case["contrastMin"] + 1e-9 < 4.5:
            fail(
                f"{label}の実表示コントラストが不足しています: "
                f"{case['contrastMin']:.3f} ({case['contrastOffender']})"
            )
        if case["mermaidSvg"] != 1 or case["mermaidError"]:
            fail(f"{label}でMermaidを描画できません")
        if case["mermaidNodes"] != expected_mermaid_nodes:
            fail(f"{label}のMermaidノード数が違います: {case['mermaidNodes']}")
        if case["mermaidEdges"] != expected_mermaid_edges:
            fail(f"{label}のMermaidエッジ数が違います: {case['mermaidEdges']}")
        if case["wiringNodes"] != expected_wiring_nodes:
            fail(f"{label}の配線ノード数が違います: {case['wiringNodes']}")
        if case["wiringEdges"] != expected_wiring_edges:
            fail(f"{label}の配線エッジ数が違います: {case['wiringEdges']}")
        if case["commonRows"] != 3 or case["scoreRows"] != 8 or case["catalogCards"] != 8:
            fail(
                f"{label}のJSON生成領域が不完全です: "
                f"common={case['commonRows']}, score={case['scoreRows']}, "
                f"catalog={case['catalogCards']}"
            )
        if case["dynamicUnresolved"]:
            fail(f"{label}でJS生成後の未解決アンカーがあります: {case['dynamicUnresolved']}")
        expected_systems = [
            {
                "id": system["id"],
                "labels": system["labels"],
                "mechanism": system["mechanism"],
            }
            for system in expected_common["systems"]
        ]
        if case["commonData"] != {
            "gt": expected_common["gt"],
            "systems": expected_systems,
        }:
            fail(
                f"{label}の共通フレーム比較表示が正本JSONと違います: "
                f"rendered={case['commonData']}, "
                f"expected={{'gt': {expected_common['gt']}, 'systems': {expected_systems}}}"
            )
        n3 = next(
            system for system in expected_common["systems"] if system["id"] == "supreme8"
        )
        expected_score = [
            {
                "layer": layer,
                "pred": n3["labels"][layer],
                "gt": expected_common["gt"][layer],
            }
            for layer in expected_common["layers"]
        ]
        if case["scoreData"] != expected_score:
            fail(f"{label}の採点ウォーク表示が正本JSONと違います")

    if reading_source is None:
        return cases

    rendered_reading = cases[0]["reading"]
    if len(rendered_reading) != len(reading_source):
        fail("実ブラウザの読み方ガイド件数が違います")
    for rendered, source in zip(rendered_reading, reading_source):
        if rendered["href"] != source["href"] or rendered["targets"] != source["targets"]:
            fail(f"実ブラウザの読み方パスがソース宣言と違います: {rendered}")
        if (
            rendered["minutes"] != source["minutes"]
            or rendered["declared"] != source["minutes"]
            or rendered["shown"] != source["minutes"]
        ):
            fail(
                f"{source['href']}の理解時間が実測と違います: "
                f"chars={rendered['chars']}, expected={rendered['minutes']}, "
                f"declared={source['minutes']}, shown={rendered['shown']}"
            )
    return cases


def main() -> None:
    html = HTML_PATH.read_text(encoding="utf-8")
    baseline = baseline_html()
    t3_values = module_constants(T3_PATH)
    core_values = module_constants(CORE_PATH)

    expected_vocab = list(t3_values["_V14_T3"])
    expected_mode_window = int(t3_values["_RULE_MODE_WINDOW"])
    expected_posterior_window = int(t3_values["_WINDOW"])
    expected_traffic_threshold = float(t3_values["_RULE_TRAFFIC_RATIO"])

    parser = parse_html(html)
    if parser.errors:
        fail("HTMLタグ均衡に失敗しました: " + " / ".join(parser.errors[:5]))
    duplicate_ids = [key for key, count in Counter(parser.ids).items() if count > 1]
    if duplicate_ids:
        fail(f"重複idがあります: {duplicate_ids}")
    id_set = set(parser.ids)
    unresolved_hrefs = sorted(
        href for href in parser.hrefs if href.startswith("#") and href[1:] not in id_set
    )
    if unresolved_hrefs:
        fail(f"未解決アンカーがあります: {unresolved_hrefs}")
    if len(parser.figure_keys) != len(set(parser.figure_keys)):
        fail("data-figureキーが重複しています")
    unresolved_figures = sorted(set(parser.figure_refs) - set(parser.figure_keys))
    if unresolved_figures:
        fail(f"未解決の図参照があります: {unresolved_figures}")
    structure = check_static_book_model(html, parser)
    directional_ref_count = check_directional_references(html)
    idref_count = check_all_idrefs(parser)
    if parser.t3_vocab != expected_vocab:
        fail(f"T3語彙表が実装順と違います: {parser.t3_vocab} != {expected_vocab}")

    scripts = extract_json_scripts(html)
    if "t3-window-data" not in scripts:
        fail("t3-window-data がありません")
    figure_data = scripts["t3-window-data"]

    frames_doc = json.loads(FRAMES_PATH.read_text(encoding="utf-8"))
    frames = frames_doc["scenarios"][SCENARIO_ID]["frames"]
    source_series = [
        {"ts": float(frame[0]), "mode": frame[2]["t2_mode"]} for frame in frames
    ]
    if figure_data["series"] != source_series:
        fail("新図の全mode系列が frames-N3.json のpredと一致しません")
    if parser.mode_cells != [(row["ts"], row["mode"]) for row in source_series]:
        fail("新図の表示セルが埋め込みmode系列と一致しません")

    target_index = next(
        index for index, frame in enumerate(frames) if float(frame[0]) == TARGET_TS
    )
    source_window = source_series[
        max(0, target_index - expected_mode_window + 1) : target_index + 1
    ]
    if figure_data["window_size"] != expected_mode_window:
        fail("新図の窓長が t3.py の _RULE_MODE_WINDOW と一致しません")
    if figure_data["window"] != source_window:
        fail("新図の切り出し窓が実データと一致しません")

    composition_counts = Counter(row["mode"] for row in source_window)
    expected_composition = {
        mode: {"count": count, "ratio": count / len(source_window)}
        for mode, count in composition_counts.items()
    }
    if figure_data["composition"] != expected_composition:
        fail("新図の構成比が切り出し窓と一致しません")
    parsed_ratios = {
        mode: {"count": count, "ratio": ratio}
        for mode, count, ratio in parser.ratio_rows
    }
    if parsed_ratios != expected_composition:
        fail("新図に表示した構成比が埋め込み値と一致しません")

    target_frame = frames[target_index]
    actual_gt = target_frame[1]["t3_hypothesis"]
    actual_pred = target_frame[2]["t3_hypothesis"]
    if figure_data["actual_pred"] != actual_pred or parser.actual_t3 != [actual_pred]:
        fail("新図の実predが frames-N3.json と一致しません")
    if figure_data["actual_gt"] != actual_gt:
        fail("新図のGTが frames-N3.json と一致しません")
    trigger = figure_data["trigger"]
    if trigger["threshold"] != expected_traffic_threshold:
        fail("新図のtrafficしきい値が t3.py と一致しません")
    if not trigger["ratio"] > trigger["threshold"]:
        fail("新図のtraffic規則が実際には発火しません")
    if actual_pred != "traffic_unstable":
        fail(f"対象フレームの実predが想定外です: {actual_pred}")

    required_constants = {
        "_RULE_ALERT_RATIO": 0.25,
        "_RULE_SUSTAINED_RATIO": 0.3,
        "_RULE_EMERGENCY_LOW": 0.2,
        "_RULE_TRAFFIC_RATIO": 0.2,
        "_RULE_CROWD_RATIO": 0.25,
        "_RULE_ENV_RATIO": 0.15,
        "_RULE_ENV_RISE": 0.10,
        "_UNCERTAIN_HQ_GATE": 0.40,
    }
    for name, expected in required_constants.items():
        if not math.isclose(float(t3_values[name]), expected, rel_tol=0, abs_tol=1e-12):
            fail(f"{name} が引用値と一致しません: {t3_values[name]} != {expected}")
    required_core_constants = {
        "_T3_V15_SPEECH": 0.7,
        "_T3_V15_QOS_UNCERTAIN": 0.4,
        "_T3_V15_APPROACH_TRAFFIC": 0.65,
        "_T3_V16_OSC_ENV": 0.003,
        "_QOS_WINDOW_S": 3.0,
    }
    for name, expected in required_core_constants.items():
        if not math.isclose(float(core_values[name]), expected, rel_tol=0, abs_tol=1e-12):
            fail(f"{name} が引用値と一致しません: {core_values[name]} != {expected}")
    if expected_posterior_window != 64:
        fail(f"posterior窓長が引用値と一致しません: {expected_posterior_window}")

    current_json = extract_json_scripts(html)
    baseline_json = extract_json_scripts(baseline)
    prose_count, glossary_count = check_complete_prose(
        html,
        current_json["page-data"],
    )
    unchanged_json_ids = {
        "ex-data",
        "wiring-data",
        "trace-data",
        "joint-map-toy-data",
    }
    for script_id in unchanged_json_ids:
        if current_json.get(script_id) != baseline_json.get(script_id):
            fail(f"既存埋め込みJSON {script_id} が変化しています")
    current_page_data = copy.deepcopy(current_json["page-data"])
    baseline_page_data = copy.deepcopy(baseline_json["page-data"])
    current_response_numbers = Counter(
        token
        for node in current_page_data["nodes"]
        for token in ALL_NUMERIC_TOKEN_RE.findall(str(node["resp"]))
    )
    baseline_response_numbers = Counter(
        token
        for node in baseline_page_data["nodes"]
        for token in ALL_NUMERIC_TOKEN_RE.findall(str(node["resp"]))
    )
    if current_response_numbers != baseline_response_numbers:
        fail("Mermaidの責務説明に含まれる数値が移動前後で違います")
    for document in (current_page_data, baseline_page_data):
        for node in document["nodes"]:
            node.pop("resp", None)
    if current_page_data != baseline_page_data:
        fail("Mermaidの責務説明以外のpage-dataが変化しています")
    if len(current_json["page-data"]["nodes"]) != len(baseline_json["page-data"]["nodes"]):
        fail("Mermaidノード数が変化しています")
    if current_json["page-data"]["edges"] != baseline_json["page-data"]["edges"]:
        fail("Mermaidエッジが変化しています")
    if current_json["wiring-data"] != baseline_json["wiring-data"]:
        fail("配線図のノードまたはエッジが変化しています")

    if "common-frame-data" not in current_json:
        fail("共通フレームJSONの正本がありません")
    baseline_common = extract_baseline_common_frame(baseline)
    if current_json["common-frame-data"] != baseline_common:
        fail("共通フレームJSONが移動前の比較表と一致しません")
    if 'querySelector(".common-frame-table")' in html:
        fail("採点ウォークが第5章の比較表DOMをデータ源にしています")
    if html.count('id="common-frame-data"') != 1:
        fail("共通フレームJSONが単一の正本になっていません")
    walk_start = html.find("(function buildEvaluationWalk(){")
    walk_end = html.find("// ---- 結合MAPのおもちゃ罰金表", walk_start)
    if walk_start < 0 or walk_end < 0:
        fail("採点ウォーク生成関数を抽出できません")
    walk_source = html[walk_start:walk_end]
    if "COMMON_FRAME" not in walk_source or any(
        token in walk_source
        for token in ("commonFrameComparison", "common-frame-table", "frameLabelList")
    ):
        fail("採点ウォークが共通JSONではなく比較表DOMへ依存しています")

    chapter_six = html[
        html.index('id="chapter-6"') : html.index('id="chapter-7"')
    ]
    canonical_chapter_six = [
        "strict_gt_conformance=False",
        "pooledとper-suiteは分母が違います",
        "違反入力は8層accuracyへ混ぜず",
        "situations_v1と付録のcoverage_v3はGT、目的、分母が異なる",
        "suite=situations_v1",
        "split=eval",
        "構成N3（PRIMARY）",
        "strict OFF、測定日",
    ]
    missing_canonical = [
        phrase for phrase in canonical_chapter_six if phrase not in chapter_six
    ]
    if missing_canonical:
        fail(f"第6章の解釈・引用規約の正本が不足しています: {missing_canonical}")
    if "語彙の上限近くで学習しきれない" in html[
        html.index('id="chapter-4"') : html.index('id="chapter-5"')
    ]:
        fail("relation語彙ギャップの原因説明が第4章に重複しています")

    current_numbers = stable_numeric_tokens(html)
    baseline_numbers = stable_numeric_tokens(baseline)
    if current_numbers != baseline_numbers:
        removed = baseline_numbers - current_numbers
        added = current_numbers - baseline_numbers
        fail(
            "検証済み数値の多重集合が移動前後で違います: "
            f"removed={dict(removed.most_common(20))}, "
            f"added={dict(added.most_common(20))}"
        )

    js_blocks = check_inline_javascript(html)
    contrast_minima = check_contrast(html)
    reading_source = check_reading_guide_source(html)
    browser_cases = check_browser_runtime(
        expected_wiring_nodes=len(current_json["wiring-data"]["nodes"]),
        expected_wiring_edges=len(current_json["wiring-data"]["wires"]),
        expected_mermaid_nodes=len(current_json["page-data"]["nodes"]),
        expected_mermaid_edges=len(current_json["page-data"]["edges"]),
        expected_common=current_json["common-frame-data"],
        reading_source=reading_source,
    )

    print(
        "[architecture-t3] OK: "
        f"HTML tags balanced / chapters={structure['chapters']} / "
        f"figures={structure['figures']} / toc={structure['toc']} / "
        f"anchors+idrefs={len(parser.hrefs)}+{idref_count} resolved / "
        f"directional_refs={directional_ref_count} / prose={prose_count} / "
        f"glossary_defs={glossary_count} / "
        f"mode_window={expected_mode_window} / posterior_window={expected_posterior_window} / "
        f"vocab={len(expected_vocab)} / scenario_frames={len(source_series)} / "
        f"target_pred={actual_pred} / inline_js={js_blocks}"
    )
    print(
        "[architecture-t3] OK: "
        f"composition={expected_composition} / traffic>{expected_traffic_threshold} / "
        f"contrast_min(light)={contrast_minima['light']:.3f} / "
        f"contrast_min(dark)={contrast_minima['dark']:.3f}"
    )
    print(
        "[architecture-t3] OK: "
        f"existing JSON/numeric multiset unchanged / common-frame single source / Mermaid="
        f"{len(current_json['page-data']['nodes'])} nodes,"
        f"{len(current_json['page-data']['edges'])} edges / "
        f"wiring={len(current_json['wiring-data']['nodes'])} nodes,"
        f"{len(current_json['wiring-data']['wires'])} edges"
    )
    reading = browser_cases[0]["reading"]
    print(
        "[architecture-t3] OK: browser runtime errors=0 / "
        "overflow=0 at 1600px+390px / "
        f"rendered contrast min={min(case['contrastMin'] for case in browser_cases):.3f} / "
        "reading="
        + ", ".join(
            f"{item['chars']} chars->{item['minutes']} min" for item in reading
        )
    )


if __name__ == "__main__":
    main()
