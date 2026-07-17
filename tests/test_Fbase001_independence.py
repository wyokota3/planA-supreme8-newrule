r"""F-基盤-001-2(ADR 0022)— 独立性: supreme.core(統合ランナー)が baseline / ns_epi /
external-data を実行時・静的にリンクしない(F-006-2 流儀の機械チェック)。

F-基盤-001 は最大の統合機能(8モジュールを結線)であり、ここで baseline 実装を import すると
プロジェクトの独立性原則(判断1・ADR 0017)が破れる。core は EPI 契約のみ共有し、
baseline コードへはリンクしない(baseline 忠実な独立再実装・ADR 0022 確定事項)。

契約の最終根拠:
  - decisions/0022-fbase001-supreme-runner.md:
      確定事項「baseline 忠実な独立再実装(baseline/ns_epi/external を import・参照しない・
      F-006-2 流儀)」。F-基盤-001-2「独立性(baseline/ns_epi/external を実行時・静的に
      非リンク・F-006-2 流儀)」。
  - specs/SPEC.md F-基盤-001-2(行 221)/ F-006-2(独立性の機械チェック)/ 判断1(supreme は
    baseline へ実行時依存しない)。
  - tests/test_F006_independence.py(検証手段の流儀: sys.modules / AST / ソース文字列 /
    __file__)。本ファイルは検証対象を core(+ core が結線する supreme モジュール群)に拡張する。

検証手段(F-006-2 流儀・ADR 0022 で裁量):
  1. supreme.core を import した時点で sys.modules に baseline パッケージ(ns_epi 系)が
     現れない(実行時に baseline へリンクしない)。
  2. core のソース(__file__)に baseline / external-data の import 文・文字列断片が現れない
     (静的 import グラフ・動的 import/パス直読みの抜け道を塞ぐ)。
  3. core の __file__ が supreme パッケージ配下にある(external-data ツリー配下でない)。

スコープ外(ADR 0022): baseline 数値一致(δ_strong)は F-013 で測定。本ファイルは
「リンクしていない」ことのみ(数値忠実度は別)。
"""

import ast
import importlib
import sys
from pathlib import Path

import pytest


# F-基盤-001 の統合ランナー(独立性チェック対象)。core が結線する supreme モジュール群も
# baseline 非リンクであるべきだが、t0/t1/role は test_F006_independence.py、scene/t3 は
# test_F010/F009_independence.py で固定済み。本ファイルは新規ノード core を対象に追加する。
CORE_MODULE_NAME = "supreme.core"

# 実行時リンクを禁止する baseline / external-data パッケージのトップレベル名。
FORBIDDEN_TOP_LEVEL = {
    "ns_epi",        # baseline 実装パッケージ(runner/gate/t2/quality/anomaly/hgf 原典)
    "external_data",
}

# import 文以外の抜け道(動的 import・sys.path 操作・パス直読み)を塞ぐ禁止文字列断片。
FORBIDDEN_SOURCE_FRAGMENTS = [
    "ns_epi",
    "external-data",
    "external_data",
    "planA-baseline",
    "planA_baseline",
]


def _import_core_module():
    """supreme.core を import して返す(実装不在なら ImportError で失敗=TDD 期待)。"""
    return importlib.import_module(CORE_MODULE_NAME)


def _baseline_modules_in_sys():
    return {m for m in sys.modules if m == "ns_epi" or m.startswith("ns_epi.")}


# ===========================================================================
# 1. 実行時非リンク: core を import しても sys.modules に baseline が現れない
# ===========================================================================

def test_Fbase001_2_core_does_not_link_baseline_at_runtime():
    """F-基盤-001-2(ADR 0022・実行時非リンク): supreme.core を import しても sys.modules に
    baseline パッケージ(ns_epi 系)が読み込まれない。

    統合ランナー core の import が baseline 実装を芋づる式に import しない=実行時に baseline へ
    リンクしないことを sys.modules で機械チェックする(F-006-2 流儀)。
    """
    before = _baseline_modules_in_sys()
    _import_core_module()
    after = _baseline_modules_in_sys()
    newly_linked = after - before
    assert not newly_linked, (
        f"supreme.core の import で baseline パッケージがリンクされた: "
        f"{sorted(newly_linked)!r}(F-基盤-001-2 違反: 実行時非リンクのはず)"
    )


# ===========================================================================
# 2. 静的 import グラフ: core のソースに baseline import が現れない
# ===========================================================================

def test_Fbase001_2_core_source_has_no_baseline_import():
    """F-基盤-001-2(ADR 0022・静的非依存): supreme.core のソースに baseline / external-data の
    import 文が現れない。

    AST を走査して import / import-from の対象に ns_epi 等(FORBIDDEN_TOP_LEVEL)が無いことを
    固定する。独立再実装(ADR 0022 確定事項)=ソース上でも baseline へ依存しない。
    """
    mod = _import_core_module()
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
        f"supreme.core のソースに baseline/external-data の import がある: "
        f"{offending!r}(F-基盤-001-2 違反: 独立再実装のはず)"
    )


def test_Fbase001_2_core_source_has_no_baseline_path_reference():
    """F-基盤-001-2(ADR 0022・静的非依存・文字列参照): supreme.core のソース本文に baseline /
    external-data を指す文字列断片(ns_epi / external-data / planA-baseline 等)が現れない。

    import 文以外(動的 import・sys.path 操作・パス直読み)で baseline へリンクする抜け道も
    塞ぐため、ソース文字列レベルで禁止断片の不在を固定する(test_F006_independence.py 穴8 と同型)。
    """
    mod = _import_core_module()
    source = Path(mod.__file__).read_text(encoding="utf-8")
    hits = [frag for frag in FORBIDDEN_SOURCE_FRAGMENTS if frag in source]
    assert not hits, (
        f"supreme.core のソースに baseline/external-data を指す文字列がある: "
        f"{hits!r}(F-基盤-001-2 違反: 動的 import やパス直読みの疑い)"
    )


# ===========================================================================
# 3. supreme 内で閉じる: core の __file__ が supreme パッケージ配下
# ===========================================================================

def test_Fbase001_2_core_lives_under_supreme_package():
    """F-基盤-001-2(ADR 0022・supreme 内で閉じる): supreme.core の __file__ が supreme
    パッケージ配下にあり、external-data / baseline ツリー配下でない。

    統合ランナーの実体が supreme パッケージ内に独立実装されていること(submodule や
    external-data へのシンボリックリンクでないこと)を __file__ のパスで固定する。
    """
    import supreme

    mod = _import_core_module()
    supreme_dir = Path(supreme.__file__).resolve().parent
    mod_file = Path(mod.__file__).resolve()

    assert supreme_dir in mod_file.parents, (
        f"supreme.core の __file__({mod_file}) が supreme パッケージ配下({supreme_dir})に"
        "ない(F-基盤-001-2 違反: supreme 内で閉じるはず)"
    )
    assert "external-data" not in mod_file.as_posix(), (
        f"supreme.core の __file__ が external-data 配下にある: {mod_file}"
        "(F-基盤-001-2 違反: baseline クローンへリンクしている疑い)"
    )


# ===========================================================================
# 4. 総括: core を import して end-to-end を 1 回回しても baseline が読まれない
# ===========================================================================

def test_Fbase001_2_running_core_does_not_load_baseline():
    """F-基盤-001-2(ADR 0022・総括): supreme.core を import し run_supreme を 1 回実行しても、
    sys.modules に baseline パッケージ(ns_epi 系)が一切現れない。

    import 時点(上のテスト)だけでなく、実際に end-to-end を回した到達点でも baseline が
    読まれていないことを固定する(遅延 import で実行時に baseline へ伸びる抜け道を塞ぐ)。
    """
    import fixtures_pso as fxp

    core = _import_core_module()
    before = _baseline_modules_in_sys()
    core.run_supreme([fxp.frame_benign(ts=0.0), fxp.frame_conversation(ts=1.0)])
    after = _baseline_modules_in_sys()
    newly_linked = after - before
    assert not newly_linked, (
        f"run_supreme 実行で baseline パッケージがリンクされた: {sorted(newly_linked)!r}"
        "(F-基盤-001-2 違反: 遅延 import で実行時に baseline へ伸びている疑い)"
    )
