"""docs/architecture-explainer.html の T3 拡充を実装ソースと実測値へ照合します。"""

from __future__ import annotations

import ast
from collections import Counter
from html.parser import HTMLParser
import json
import math
from pathlib import Path
import re
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
HTML_PATH = ROOT / "docs" / "architecture-explainer.html"
T3_PATH = ROOT / "src" / "supreme" / "t3.py"
CORE_PATH = ROOT / "src" / "supreme" / "core.py"
FRAMES_PATH = ROOT / "reports" / "situations_v1-eval-20260722" / "frames-N3.json"
SCENARIO_ID = "std-doorbell_visit-eval-02"
TARGET_TS = 3.0

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


def stable_numeric_tokens(html: str) -> list[str]:
    text = re.sub(r"<style>[\s\S]*?</style>", "", html, flags=re.IGNORECASE)
    text = re.sub(
        r"<!-- t3_hypothesis -->[\s\S]*?<!-- quality_regime -->",
        "<!-- T3 NORMALIZED -->",
        text,
    )
    text = re.sub(
        r'\s*<div id="term-window-classification">[\s\S]*?</div>',
        "",
        text,
    )
    text = re.sub(
        r'\s*<div id="term-phase-declaration">[\s\S]*?</div>',
        "",
        text,
    )
    return re.findall(r"(?<![A-Za-z_])[-+]?(?:\d+\.\d+|\d+)(?![A-Za-z_])", text)


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
    unchanged_json_ids = {
        "ex-data",
        "page-data",
        "wiring-data",
        "trace-data",
        "joint-map-toy-data",
    }
    for script_id in unchanged_json_ids:
        if current_json.get(script_id) != baseline_json.get(script_id):
            fail(f"既存埋め込みJSON {script_id} が変化しています")
    if stable_numeric_tokens(html) != stable_numeric_tokens(baseline):
        fail("T3/CSS/用語集の追加領域外で既存数値が変化しています")

    if current_json["page-data"]["nodes"] != baseline_json["page-data"]["nodes"]:
        fail("Mermaidノードが変化しています")
    if current_json["page-data"]["edges"] != baseline_json["page-data"]["edges"]:
        fail("Mermaidエッジが変化しています")
    if current_json["wiring-data"] != baseline_json["wiring-data"]:
        fail("配線図のノードまたはエッジが変化しています")

    js_blocks = check_inline_javascript(html)
    contrast_minima = check_contrast(html)

    print(
        "[architecture-t3] OK: "
        f"HTML tags balanced / figures={len(parser.figure_keys)} / anchors resolved / "
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
        f"existing JSON/numerics unchanged / Mermaid="
        f"{len(current_json['page-data']['nodes'])} nodes,"
        f"{len(current_json['page-data']['edges'])} edges / "
        f"wiring={len(current_json['wiring-data']['nodes'])} nodes,"
        f"{len(current_json['wiring-data']['wires'])} edges"
    )


if __name__ == "__main__":
    main()
