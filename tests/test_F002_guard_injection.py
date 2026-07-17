"""F-002-2: 外部注入 guard（seal_guard）の優先順位規約と fail-closed。

specs/SPEC.md F-002-2:
  「封印へのアクセスは開封セッション単位で生涯1回のみ。」（本番封印の生涯1回担保）
specs/GUARD_IF.md:
  - SealGuard(*, production)。本番封印は production=True で生涯1回を強制。
  - 運用規約2: プロセス跨ぎの「生涯1回」最終保証は F-002 のアクセス制御＋永続セッション
    状態の突合で担保する。
decisions/0009-f002-sealset-policies.md:
  SealStore(*, root_dir, production, seal_guard=None)。seal_guard 省略時は production に
  応じて内部生成する。

decisions/0010-f002-audit-fixes.md（本ファイルが固定する契約の正）:
  追記「外部注入 guard の優先順位規約」:
    公開復元API化（決定3）により注入 guard へ状態ファイル計数を適用できない
    （構築時注入のため）。よって
    - production=True での seal_guard 注入は GuardInputError で拒否（fail-closed）。
      本番は自前生成＋状態ファイル復元のみ。
    - dummy（production=False）は注入可だが、状態ファイル復元は自前生成時のみ
      （注入時は session_state.json を読まない）。

----------------------------------------------------------------------------
本ファイルが固定する supreme.sealset.SealStore の契約（ADR 0010 追記）:

  SealStore(root_dir=..., production=True, seal_guard=<任意の SealGuard>)
    → guard.GuardInputError（本番での注入は fail-closed で禁止）。

  SealStore(root_dir=..., production=False, seal_guard=<SealGuard>)
    → 構築成功（dummy での注入は従来どおり可）。
    かつ root_dir に session_state.json があっても注入 guard には適用されない
    （注入 guard の lifetime_session_count() は 0 のまま）。

  注: 既存のプロセス跨ぎ復元（test_F002_lifetime_session.py の自前生成経路）は
      契約不変（本ファイルでは触れない）。本ファイルは注入経路の規約のみを固定する。
"""

import json

import pytest

from supreme import guard
from supreme import sealset


# ---------------------------------------------------------------------------
# production=True での seal_guard 注入は fail-closed で拒否
# ---------------------------------------------------------------------------

def test_F002_2_production_guard_injection_rejected(tmp_path):
    """F-002-2（ADR 0010 追記・核心）: 本番での seal_guard 注入は GuardInputError。

    公開復元API化により注入 guard へ状態ファイル計数を適用できないため、本番封印の
    生涯1回を取りこぼさないよう、production=True での注入は構築時に fail-closed で拒否する
    （本番は自前生成＋状態ファイル復元のみ）。
    """
    injected = guard.SealGuard(production=True)
    with pytest.raises(guard.GuardInputError):
        sealset.SealStore(root_dir=tmp_path, production=True, seal_guard=injected)


def test_F002_2_production_rejects_injection_regardless_of_guard_mode(tmp_path):
    """F-002-2（ADR 0010 追記・陰性）: 本番では注入 guard の production 値に関わらず拒否。

    production=False の guard を本番 SealStore に注入しても拒否（fail-closed）。
    「注入された guard のモードに合わせて緩める」抜け道を作らない。
    """
    injected_dummy = guard.SealGuard(production=False)
    with pytest.raises(guard.GuardInputError):
        sealset.SealStore(root_dir=tmp_path, production=True,
                          seal_guard=injected_dummy)


# ---------------------------------------------------------------------------
# dummy（production=False）での注入は従来どおり可（構築成功）
# ---------------------------------------------------------------------------

def test_F002_2_dummy_guard_injection_allowed(tmp_path):
    """F-002-2（ADR 0010 追記・対照）: dummy での seal_guard 注入は構築成功。

    非本番（構成検証・常用テスト）では注入を許す（従来どおり）。
    """
    injected = guard.SealGuard(production=False)
    store = sealset.SealStore(root_dir=tmp_path, production=False,
                              seal_guard=injected)
    # 構築でき、注入 guard 経由で発行できる（dummy は複数可・少なくとも1回は発行成功）。
    tok = store.issue_open_token("S1", issued_ts=100.0, precheck_passed=True)
    assert tok.active is True


# ---------------------------------------------------------------------------
# dummy 注入時、root_dir の session_state.json は注入 guard に適用されない
# ---------------------------------------------------------------------------

def test_F002_2_dummy_injection_ignores_session_state_file(tmp_path):
    """F-002-2（ADR 0010 追記・核心）: dummy 注入時、状態ファイルは注入 guard に適用されない。

    root_dir に session_state.json（lifetime_session_count: 1）を置いても、注入 guard の
    lifetime_session_count() は 0 のまま（状態ファイル復元は自前生成時のみ）。
    """
    # 状態ファイルを先に置く（自前生成なら 1 を復元する想定の値）。
    state_path = tmp_path / "session_state.json"
    state_path.write_text(json.dumps({"lifetime_session_count": 1}),
                          encoding="utf-8")

    injected = guard.SealGuard(production=False)
    assert injected.lifetime_session_count() == 0  # 注入前は素の 0

    sealset.SealStore(root_dir=tmp_path, production=False, seal_guard=injected)

    # 注入 guard は状態ファイルの 1 を読み込まない（自前生成経路ではないため）。
    assert injected.lifetime_session_count() == 0, (
        "注入 guard に session_state.json が適用されてしまっている"
    )
