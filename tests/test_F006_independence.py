r"""F-006-2 独立性チェック(機械チェック): supreme の強い項目モジュール(t0/t1/role)が
baseline / external-data パッケージへ実行時リンクしていないこと(独立再実装)を機械的に
固定する。

契約の最終根拠:
  - specs/SPEC.md F-006 受け入れ条件:
      F-006-2: supreme が baseline コードへ実行時リンクしていない(独立性の機械チェック)。
  - decisions/0017-f006-strong-reimplementation.md:
      決定1: 独立再実装。「baseline と独立な新アーキ supreme」原則に整合し、F-006-2
             (実行時非リンク)を自然に満たす。物理コピー・submodule は採らない。
      決定4: F-006-2 独立性チェックを本機能(F-006)のテストで固定する
             (supreme.t0/t1/role 等が external-data / baseline パッケージを import しない・
              supreme パッケージ内で閉じる)。
  - specs/TEST_STRATEGY.md F-006:
      統合: supreme が baseline コードへ実行時リンクしていない(F-006-2、独立性の機械チェック)。

baseline パッケージ名(独立性の検証対象・external-data\planA-baseline\src\ns_epi):
  - トップレベルパッケージ名 `ns_epi`(baseline 実装。t0.py/t1.py/t2.py が強い項目原典)。
  - external-data はリポジトリ外のクローン置き場(`external-data\planA-baseline` 等)。
  supreme は EPI 入出力契約のみ共有し、baseline 実装コードへはリンクしない(判断1・ADR 0017)。

検証手段(ADR 0017 決定4・指示で裁量・importlib/inspect/sys.modules で確認):
  1. supreme.t0/t1/role を import した時点で sys.modules に baseline パッケージ
     (ns_epi 系)が現れない(実行時に baseline へリンクしない)。
  2. 各モジュールのソース(inspect.getsource 相当)に baseline / external-data の
     import 文が現れない(静的 import グラフが baseline へ伸びない)。
  3. 各モジュールの __file__ が supreme パッケージ配下にある(supreme 内で閉じる)。

スコープ外(ADR 0017): baseline 数値一致(δ_strong)は F-013 で測定。本ファイルは
「リンクしていない」ことのみを固定する(数値忠実度は別)。
"""

import ast
import importlib
import sys
from pathlib import Path

import pytest


# F-006 の強い項目モジュール(独立再実装の対象・ADR 0017 決定3)。
STRONG_MODULE_NAMES = ["supreme.t0", "supreme.t1", "supreme.role"]

# 実行時リンクを禁止する baseline / external-data パッケージのトップレベル名。
# baseline 実装は `ns_epi`(external-data\planA-baseline\src\ns_epi)。
FORBIDDEN_TOP_LEVEL = {
    "ns_epi",        # baseline 実装パッケージ(t0/t1/t2 原典)
    "external_data",  # 念のため(ハイフンは識別子にならないが防御的に)
}

# import 文のソース上で禁止する文字列断片(external-data クローンへの直接参照等)。
FORBIDDEN_SOURCE_FRAGMENTS = [
    "ns_epi",
    "external-data",
    "external_data",
    "planA-baseline",
    "planA_baseline",
]


def _import_strong_module(name):
    """強い項目モジュールを import して返す(実装不在なら ImportError で失敗)。"""
    return importlib.import_module(name)


# ===========================================================================
# 1. 実行時非リンク: import 後の sys.modules に baseline が現れない
# ===========================================================================

@pytest.mark.parametrize("mod_name", STRONG_MODULE_NAMES)
def test_F006_2_strong_module_does_not_link_baseline_at_runtime(mod_name):
    """F-006-2(ADR 0017 決定4・実行時非リンク): supreme.t0/t1/role を import しても、
    sys.modules に baseline パッケージ(ns_epi 系)が読み込まれない。

    強い項目モジュールの import が baseline 実装を芋づる式に import しない=実行時に
    baseline へリンクしないことを sys.modules で機械チェックする。
    """
    # baseline が他テストで先に読まれている可能性を排除して計測する。
    baseline_before = {
        m for m in sys.modules if m == "ns_epi" or m.startswith("ns_epi.")
    }
    _import_strong_module(mod_name)
    baseline_after = {
        m for m in sys.modules if m == "ns_epi" or m.startswith("ns_epi.")
    }
    newly_linked = baseline_after - baseline_before
    assert not newly_linked, (
        f"{mod_name} の import で baseline パッケージがリンクされた: "
        f"{sorted(newly_linked)!r}(F-006-2 違反: 実行時非リンクのはず)"
    )


# ===========================================================================
# 2. 静的 import グラフ: ソースに baseline import が現れない
# ===========================================================================

@pytest.mark.parametrize("mod_name", STRONG_MODULE_NAMES)
def test_F006_2_strong_module_source_has_no_baseline_import(mod_name):
    """F-006-2(ADR 0017 決定4・静的非依存): supreme.t0/t1/role のソースに baseline /
    external-data の import 文が現れない。

    AST を走査して import / import-from の対象に ns_epi 等(FORBIDDEN_TOP_LEVEL)が
    無いことを固定する。独立再実装(ADR 0017 決定1)=ソース上でも baseline へ依存しない。
    """
    mod = _import_strong_module(mod_name)
    source_path = Path(mod.__file__)
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    offending = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top in FORBIDDEN_TOP_LEVEL:
                    offending.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            # from X import ... の X(相対 import は module=None・対象外)
            if node.module:
                top = node.module.split(".")[0]
                if top in FORBIDDEN_TOP_LEVEL:
                    offending.append(node.module)
    assert not offending, (
        f"{mod_name} のソースに baseline/external-data の import がある: "
        f"{offending!r}(F-006-2 違反: 独立再実装のはず)"
    )


@pytest.mark.parametrize("mod_name", STRONG_MODULE_NAMES)
def test_F006_2_strong_module_source_has_no_baseline_path_reference(mod_name):
    """F-006-2(ADR 0017 決定4・静的非依存・文字列参照): supreme.t0/t1/role のソース
    本文に baseline / external-data を指す文字列断片(ns_epi / external-data /
    planA-baseline 等)が現れない。

    import 文以外(動的 import・sys.path 操作・パス直読み等)で baseline へリンクする
    抜け道も塞ぐため、ソース文字列レベルで禁止断片の不在を固定する(穴8: ログを介さない
    経路を静的に塞ぐ)。
    """
    mod = _import_strong_module(mod_name)
    source = Path(mod.__file__).read_text(encoding="utf-8")
    hits = [frag for frag in FORBIDDEN_SOURCE_FRAGMENTS if frag in source]
    assert not hits, (
        f"{mod_name} のソースに baseline/external-data を指す文字列がある: "
        f"{hits!r}(F-006-2 違反: 独立再実装のはず・動的 import やパス直読みの疑い)"
    )


# ===========================================================================
# 3. supreme 内で閉じる: __file__ が supreme パッケージ配下
# ===========================================================================

@pytest.mark.parametrize("mod_name", STRONG_MODULE_NAMES)
def test_F006_2_strong_module_lives_under_supreme_package(mod_name):
    """F-006-2(ADR 0017 決定4・supreme 内で閉じる): supreme.t0/t1/role の __file__ が
    supreme パッケージ配下にあり、external-data / baseline ツリー配下でない。

    強い項目の実体が supreme パッケージ内に独立実装されていること(submodule や
    external-data へのシンボリックリンクでないこと)を __file__ のパスで固定する。
    """
    import supreme

    mod = _import_strong_module(mod_name)
    supreme_dir = Path(supreme.__file__).resolve().parent
    mod_file = Path(mod.__file__).resolve()

    assert supreme_dir in mod_file.parents, (
        f"{mod_name} の __file__({mod_file}) が supreme パッケージ配下"
        f"({supreme_dir})にない(F-006-2 違反: supreme 内で閉じるはず)"
    )
    # external-data ツリー配下でないことも明示。
    assert "external-data" not in mod_file.as_posix(), (
        f"{mod_name} の __file__ が external-data 配下にある: {mod_file}"
        "(F-006-2 違反: baseline クローンへリンクしている疑い)"
    )


# ===========================================================================
# 4. baseline パッケージ自体が import されていない(セッション全体での確認)
# ===========================================================================

def test_F006_2_baseline_package_not_loaded_after_importing_strong_modules():
    """F-006-2(ADR 0017 決定4・総括): 3つの強い項目モジュールを全て import した後でも、
    sys.modules に baseline パッケージ(ns_epi 系)が一切存在しない。

    個別モジュール単位(上の parametrize)に加え、3モジュール一括 import 後の到達点でも
    baseline が読まれていないことを固定する(supreme 全体として baseline へ非リンク)。
    """
    for name in STRONG_MODULE_NAMES:
        _import_strong_module(name)
    baseline_modules = {
        m for m in sys.modules if m == "ns_epi" or m.startswith("ns_epi.")
    }
    assert not baseline_modules, (
        f"強い項目モジュール import 後に baseline パッケージが sys.modules にある: "
        f"{sorted(baseline_modules)!r}(F-006-2 違反)"
    )
