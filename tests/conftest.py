"""pytest 共有設定（テスト基盤・実装コードではない）。

`src/` レイアウトのため、パッケージ未インストール環境でも `supreme.datagov` を
import 解決できるよう `src/` を sys.path に載せる。

注意:
- これはテスト基盤であり実装コードではない。
- `supreme.datagov` は実装不在のため import は失敗する（TDD の期待挙動）。
  この conftest は「import の探索パス」を整えるだけで、実装を肩代わりしない。
"""

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
