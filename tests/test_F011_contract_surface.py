"""F-011 公開契約面: supreme.quality モジュールの公開 API が存在し、
ADR 0014 の quality_regime 判定規則(入力 (h_q, vol) → v1.4 ラベル)を供給すること。

契約の最終根拠:
  - specs/SPEC.md「F-011: Quality regime 改良モジュール」
      手段(ADR 0013/0014): ルール改良(境界再較正)。スコープ = 判定規則のみ
      (h_q,vol → v1.4 3クラス)。学習はしない。対応コンポーネント `quality`。
  - decisions/0014-f011-quality-recalibration.md(手法の正)
      決定1: F-011 = supreme 独自の quality_regime 判定規則。入力 (h_q, vol)、
             出力 v1.4 3クラス {GOOD, DEGRADED, BLOCK}。h_q/vol の生成
             (観測式+HGF)は F-011 スコープ外(上流の共有基盤)。
      決定3: v1.4 3クラス規則(優先順位チェーン・GOOD ゲート h_q≥0.93 へ再較正)。
  - decisions/0006-v14-vocabulary-migration-u7.md(v1.4 語彙の正)
      quality: GOOD/DEGRADED/BLOCK(順位シフト後の v1.4 統制語彙)。

このファイルは個々の判定値ではなく「契約面(公開シンボルの存在・最小不変条件)」を
固定する。判定規則の振る舞い(計測根拠ケース)は test_F011_classify_rule.py が担当。
quality は datagov/sealset/augment/harness と疎結合でよい(h_q/vol は外から与える入力)。
実装不在のうちは import 段階で失敗する(supreme.quality 未実装)。

設計裁量(指示で明示的に委任・既存 harness/augment の流儀に合わせる):
  quality.classify(h_q, vol) -> str
      ADR 0014 決定3 の判定規則で v1.4 ラベル文字列を返す。
  quality.GOOD / quality.DEGRADED / quality.BLOCK -> str
      v1.4 統制語彙のラベル定数("GOOD"/"DEGRADED"/"BLOCK")。
"""

import inspect

from supreme import quality


# ---------------------------------------------------------------------------
# 公開シンボルの存在
# ---------------------------------------------------------------------------

def test_F011_quality_module_exposes_classify():
    """F-011(契約面): quality は判定規則の入口 classify() を公開する。

    入力 (h_q, vol) → v1.4 ラベルへ写す純関数の入口が公開されていること。
    """
    assert hasattr(quality, "classify"), "quality.classify が公開されていない"
    assert callable(quality.classify)


def test_F011_quality_module_exposes_v14_label_constants():
    """F-011(契約面・ADR 0006): quality は v1.4 語彙 GOOD/DEGRADED/BLOCK を公開する。

    順位シフト後の v1.4 統制語彙(GOOD/DEGRADED/BLOCK)をラベル定数として公開し、
    その値がそれぞれの文字列であること(語彙 faithfulness)。
    """
    for name in ("GOOD", "DEGRADED", "BLOCK"):
        assert hasattr(quality, name), f"quality.{name} が公開されていない"
        assert getattr(quality, name) == name, (
            f"quality.{name} の値が '{name}' でない(v1.4 語彙 faithfulness 違反)"
        )


def test_F011_classify_accepts_h_q_and_vol_arguments():
    """F-011(契約面・ADR 0014 決定1): classify() は (h_q, vol) を引数で受け取る。

    h_q/vol を内部生成せず外から与える契約(観測式+HGF はスコープ外)。
    位置で2つ以上、または vol キーワードを受け取れること。
    """
    sig = inspect.signature(quality.classify)
    params = list(sig.parameters)
    assert "vol" in params or len(params) >= 2, (
        "classify() が (h_q, vol) を引数で受け取らない"
        "(h_q/vol を内部生成している疑い)"
    )


# ---------------------------------------------------------------------------
# 最小不変条件: classify は v1.4 3クラスのいずれかの文字列のみを返す
# ---------------------------------------------------------------------------

def test_F011_classify_returns_only_v14_labels():
    """F-011(契約面・ADR 0014 決定3): classify は v1.4 3クラスのみを返す。

    代表的な (h_q, vol) 群に対し、戻り値が常に {GOOD, DEGRADED, BLOCK} の
    いずれかの文字列であること(旧 PASS 等の旧語彙や None を返さない)。
    具体的な対応(どの入力がどのラベルか)は test_F011_classify_rule.py が固定する。
    """
    allowed = {quality.GOOD, quality.DEGRADED, quality.BLOCK}
    samples = [
        (0.001, 0.009),
        (0.30, 0.009),
        (0.549, 0.009),
        (0.55, 0.009),
        (0.70, 0.009),
        (0.929, 0.009),
        (0.93, 0.009),
        (0.94, 0.009),
        (0.95, 0.005),
        (0.95, 0.02),
    ]
    for h_q, vol in samples:
        label = quality.classify(h_q, vol)
        assert label in allowed, (
            f"classify({h_q}, {vol}) が v1.4 3クラス外の値を返した: {label!r}"
        )
