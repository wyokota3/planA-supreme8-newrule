r"""F-010 scene 改良(ADR 0019)— HGF カーネル独立再実装の独立性チェック(機械チェック)。

ADR 0019 決定4: supreme が **HGF カーネルを独立再実装**(baseline/external を import しない・
F-006 と同じ独立性の流儀)。HGF は quality/anomaly/scene が使う共有基盤だが、F-010 が最初に
実装する。本ファイルは supreme.scene が baseline(ns_epi)/ external-data へ実行時・静的に
リンクしないことを F-006-2 流儀(test_F006_independence.py)で固定する。

契約の最終根拠:
  - decisions/0019-f010-scene-hgf-learning.md 決定4 / 残件「HGF カーネルの独立再実装は既知
    アルゴリズム。supreme 内に閉じる(F-006-2 と同じ独立性)」。
  - decisions/0017-f006-strong-reimplementation.md 決定1/決定4(独立性の機械チェック)。
  - specs/SPEC.md F-006-2(実行時非リンクの機械チェック)。

baseline パッケージ名(独立性の検証対象):
  - トップレベル `ns_epi`(external-data\planA-baseline\src\ns_epi。scene.py/hgf.py 等が原典)。
  supreme は EPI 入出力契約のみ共有し、baseline 実装(HGF/EMA カーネル含む)へはリンクしない。

スコープ外: baseline 数値一致(δ_strong)は F-013 で測定。本ファイルは「リンクしていない」のみ固定。
"""

import ast
import importlib
import sys
from pathlib import Path

import pytest


SCENE_MODULE = "supreme.scene"

# 実行時/静的リンクを禁止する baseline / external-data パッケージのトップレベル名。
FORBIDDEN_TOP_LEVEL = {
    "ns_epi",        # baseline 実装パッケージ(scene.py / hgf.py 原典)
    "external_data",
}

# import 文以外の抜け道(動的 import・パス直読み)も塞ぐための禁止文字列断片。
FORBIDDEN_SOURCE_FRAGMENTS = [
    "ns_epi",
    "external-data",
    "external_data",
    "planA-baseline",
    "planA_baseline",
]


def _baseline_loaded():
    return {m for m in sys.modules if m == "ns_epi" or m.startswith("ns_epi.")}


# ===========================================================================
# 1. 実行時非リンク: scene を import しても baseline が sys.modules に現れない
# ===========================================================================

def test_F010_scene_does_not_link_baseline_at_runtime():
    """F-010(ADR 0019 決定4 / F-006-2・実行時非リンク): supreme.scene を import しても
    sys.modules に baseline パッケージ(ns_epi 系)が読み込まれない。

    HGF カーネルが supreme 独立実装で、baseline の hgf.py/scene.py を芋づる式に import
    しないことを sys.modules で機械チェックする。
    """
    before = _baseline_loaded()
    importlib.import_module(SCENE_MODULE)
    newly_linked = _baseline_loaded() - before
    assert not newly_linked, (
        f"{SCENE_MODULE} の import で baseline がリンクされた: "
        f"{sorted(newly_linked)!r}(ADR 0019 決定4 違反: HGF は独立実装のはず)"
    )


# ===========================================================================
# 2. 静的 import グラフ: ソースに baseline import が現れない
# ===========================================================================

def test_F010_scene_source_has_no_baseline_import():
    """F-010(ADR 0019 決定4 / F-006-2・静的非依存): supreme.scene のソースに baseline /
    external-data の import 文が現れない。

    AST を走査し import / import-from の対象に ns_epi 等が無いことを固定する。
    """
    mod = importlib.import_module(SCENE_MODULE)
    source = Path(mod.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    offending = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in FORBIDDEN_TOP_LEVEL:
                    offending.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.split(".")[0] in FORBIDDEN_TOP_LEVEL:
                offending.append(node.module)
    assert not offending, (
        f"{SCENE_MODULE} のソースに baseline/external-data の import がある: "
        f"{offending!r}(ADR 0019 決定4 違反: HGF 独立再実装のはず)"
    )


def test_F010_scene_source_has_no_baseline_path_reference():
    """F-010(ADR 0019 決定4 / F-006-2・静的非依存・文字列参照): supreme.scene のソース本文に
    baseline / external-data を指す文字列断片が現れない(動的 import・パス直読みの抜け道も塞ぐ)。
    """
    mod = importlib.import_module(SCENE_MODULE)
    source = Path(mod.__file__).read_text(encoding="utf-8")
    hits = [frag for frag in FORBIDDEN_SOURCE_FRAGMENTS if frag in source]
    assert not hits, (
        f"{SCENE_MODULE} のソースに baseline/external-data を指す文字列がある: "
        f"{hits!r}(ADR 0019 決定4 違反: 動的 import やパス直読みの疑い)"
    )


# ===========================================================================
# 3. supreme 内で閉じる: __file__ が supreme パッケージ配下
# ===========================================================================

def test_F010_scene_lives_under_supreme_package():
    """F-010(ADR 0019 決定4 / F-006-2・supreme 内で閉じる): supreme.scene の __file__ が
    supreme パッケージ配下にあり、external-data / baseline ツリー配下でない。
    """
    import supreme

    mod = importlib.import_module(SCENE_MODULE)
    supreme_dir = Path(supreme.__file__).resolve().parent
    mod_file = Path(mod.__file__).resolve()
    assert supreme_dir in mod_file.parents, (
        f"{SCENE_MODULE} の __file__({mod_file}) が supreme パッケージ配下"
        f"({supreme_dir})にない(ADR 0019 決定4 違反)"
    )
    assert "external-data" not in mod_file.as_posix(), (
        f"{SCENE_MODULE} の __file__ が external-data 配下: {mod_file}"
    )
