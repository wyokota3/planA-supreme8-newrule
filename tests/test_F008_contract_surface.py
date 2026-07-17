"""F-008 公開契約面: supreme.relation モジュールの公開 API が存在し、
ADR 0016 の relation logit ルール(入力 = relation 証拠 dict → relation logit 群
+ argmax ラベル)を供給すること。

契約の最終根拠:
  - specs/SPEC.md「F-008: relation 改良モジュール」
      手段(ADR 0013/0016): ルール改良(addressing 発火条件の再設計 + grouped 較正)。
      スコープ = relation の logit ルールのみ(relation 証拠 → relation logit → argmax)。
      学習はしない。対応コンポーネント `relation`。
  - decisions/0016-f008-relation-rules.md(手法の正・計測根拠)
      決定1: F-008 = supreme relation の logit ルール。入力 = relation 証拠、
             出力 = relation logit 群 と argmax ラベル。証拠抽出(段1・PSO→特徴)は
             上流の共有基盤=スコープ外(テストは evidence を直接与える)。
      決定2: addressing 発火条件の再設計(near_prox ∧ speaking_link → addressing += 2.5)。
      決定3: grouped 較正(B1: multiple_humans → += 2.0 / 無証拠既定を 1.0 → 2.0 に強化)。
  - decisions/0006-v14-vocabulary-migration-u7.md(v1.4 語彙の正)
      relations キー集合は統制語彙に閉じる(開いた辞書にしない)。
      relation v1.4 語彙(ADR 0016 決定1): addressing_user / near_user / approaching / grouped。
      departing / unrelated は本 benchmark で勝ち GT が無く是正0のため追加しない。

このファイルは個々の logit 値ではなく「契約面(公開シンボルの存在・最小不変条件)」を
固定する。logit ルールの振る舞い(計測根拠ケース)は test_F008_relation_rules.py が担当。
relation は datagov/sealset/augment/harness と疎結合でよい(証拠 dict は外から与える入力)。
実装不在のうちは import 段階で失敗する(supreme.relation 未実装の ImportError)。

設計裁量(指示で明示的に委任・既存 mode/quality の流儀に合わせる):
  relation.relation_logits(evidence: dict) -> dict[str, float]
      ADR 0016 決定2・3 の logit ルールで各 relation の logit 値を返す。
  relation.classify(evidence: dict) -> str
      relation logit の argmax で v1.4 relation ラベル文字列を返す。
  relation.ADDRESSING_USER / NEAR_USER / APPROACHING / GROUPED -> str
      v1.4 統制語彙のラベル定数("addressing_user" 等)。
"""

import inspect

from supreme import relation


# ADR 0016 決定1: relation v1.4 統制語彙(4クラス・departing/unrelated は不採用)。
V14_RELATION_LABELS = {
    "addressing_user",
    "near_user",
    "approaching",
    "grouped",
}


# ---------------------------------------------------------------------------
# 公開シンボルの存在
# ---------------------------------------------------------------------------

def test_F008_relation_module_exposes_relation_logits():
    """F-008(契約面・ADR 0016 決定1): relation は logit ルールの入口
    relation_logits() を公開する。

    入力 = relation 証拠 dict → 各 relation の logit 値(dict)へ写す純関数の入口が
    公開されていること。既定強化(無証拠→grouped logit==2.0)を直接アサートできるよう、
    argmax だけでなく logit "値" を返す API が必要(ADR 0016 既定強化の検証要件)。
    """
    assert hasattr(relation, "relation_logits"), (
        "relation.relation_logits が公開されていない"
    )
    assert callable(relation.relation_logits)


def test_F008_relation_module_exposes_classify():
    """F-008(契約面・ADR 0016 決定1): relation は argmax ラベルの入口 classify() を公開する。

    入力 = relation 証拠 dict → relation logit の argmax(v1.4 ラベル)へ写す純関数の
    入口が公開されていること。
    """
    assert hasattr(relation, "classify"), "relation.classify が公開されていない"
    assert callable(relation.classify)


def test_F008_relation_module_exposes_v14_label_constants():
    """F-008(契約面・ADR 0006/0016 決定1): relation は v1.4 語彙
    addressing_user/near_user/approaching/grouped を公開する。

    relation v1.4 統制語彙をラベル定数として公開し、その値がそれぞれの文字列であること
    (語彙 faithfulness)。departing/unrelated は ADR 0016 決定4 で不採用のため
    定数として公開しない。
    """
    expected = {
        "ADDRESSING_USER": "addressing_user",
        "NEAR_USER": "near_user",
        "APPROACHING": "approaching",
        "GROUPED": "grouped",
    }
    for name, value in expected.items():
        assert hasattr(relation, name), f"relation.{name} が公開されていない"
        assert getattr(relation, name) == value, (
            f"relation.{name} の値が '{value}' でない(v1.4 語彙 faithfulness 違反)"
        )


def test_F008_relation_module_does_not_expose_out_of_vocab_labels():
    """F-008(契約面・ADR 0016 決定4): departing/unrelated は v1.4 relation 語彙に
    追加しない(勝ち GT が無く是正0)。

    定数として departing/unrelated を公開しないことを固定する(語彙を開かない)。
    """
    for name in ("DEPARTING", "UNRELATED"):
        assert not hasattr(relation, name), (
            f"relation.{name} を公開している(ADR 0016 決定4: 語彙追加しない)"
        )


# ---------------------------------------------------------------------------
# 引数契約: 証拠 dict を外から受け取る(証拠抽出はスコープ外)
# ---------------------------------------------------------------------------

def test_F008_relation_logits_accepts_evidence_argument():
    """F-008(契約面・ADR 0016 決定1): relation_logits() は evidence(dict)を引数で受け取る。

    relation 証拠を内部生成せず外から与える契約(PSO→特徴の証拠抽出はスコープ外)。
    少なくとも1つの位置引数を受け取れること。
    """
    sig = inspect.signature(relation.relation_logits)
    params = list(sig.parameters)
    assert len(params) >= 1, (
        "relation_logits() が evidence 引数を受け取らない"
        "(証拠を内部生成している疑い)"
    )


def test_F008_classify_accepts_evidence_argument():
    """F-008(契約面・ADR 0016 決定1): classify() は evidence(dict)を引数で受け取る。"""
    sig = inspect.signature(relation.classify)
    params = list(sig.parameters)
    assert len(params) >= 1, "classify() が evidence 引数を受け取らない"


# ---------------------------------------------------------------------------
# 最小不変条件: 出力語彙が v1.4 4クラスに閉じる
# ---------------------------------------------------------------------------

def test_F008_relation_logits_keys_are_v14_vocabulary():
    """F-008(契約面・ADR 0006/0016 決定1): relation_logits の戻り値キーは
    v1.4 relation 語彙に閉じる(開いた辞書にしない)。

    代表的な証拠群に対し、logit dict のキーが {addressing_user, near_user,
    approaching, grouped} の部分集合であり、departing/unrelated を含まないこと。
    具体的な logit 値は test_F008_relation_rules.py が固定する。
    """
    samples = [
        {},
        {"conv_strong": True},
        {"approaching": True},
        {"near_prox": True, "speaking_link": True},
        {"call_user": True},
        {"multiple_humans": True},
    ]
    for ev in samples:
        logits = relation.relation_logits(ev)
        assert isinstance(logits, dict), (
            f"relation_logits({ev!r}) が dict を返さない: {logits!r}"
        )
        assert set(logits).issubset(V14_RELATION_LABELS), (
            f"relation_logits({ev!r}) が v1.4 語彙外のキーを含む: {set(logits)!r}"
        )
        assert "departing" not in logits and "unrelated" not in logits, (
            f"relation_logits({ev!r}) が departing/unrelated を含む"
            "(ADR 0016 決定4 違反)"
        )


def test_F008_classify_returns_only_v14_labels():
    """F-008(契約面・ADR 0016 決定1): classify は v1.4 4クラスのいずれかのみを返す。

    代表的な証拠群に対し、戻り値が常に {addressing_user, near_user, approaching,
    grouped} のいずれかの文字列であること(departing/unrelated や None を返さない)。
    どの証拠がどのラベルになるかは test_F008_relation_rules.py が固定する。
    """
    samples = [
        {},
        {"conv_strong": True},
        {"approaching": True},
        {"near_prox": True, "speaking_link": True},
        {"call_user": True},
        {"multiple_humans": True},
        {"conv_strong": True, "near_prox": True, "speaking_link": True},
    ]
    for ev in samples:
        label = relation.classify(ev)
        assert label in V14_RELATION_LABELS, (
            f"classify({ev!r}) が v1.4 4クラス外の値を返した: {label!r}"
        )
