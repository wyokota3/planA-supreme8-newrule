"""F-008: relation logit ルール層(relation)。

supreme relation の logit ルール。入力 = relation 証拠(evidence dict)、出力 =
各 relation の logit 群 と その argmax ラベル。PSO 入力からの証拠抽出(段1)・温度
softmax・EMA 平滑化は上流の共有基盤でありスコープ外(ADR 0016 決定1)。

契約の最終根拠は specs/SPEC.md「F-008」節、decisions/0016-f008-relation-rules.md
(手法の正・計測根拠)、decisions/0013(U1: relation=ルール改良)/0006(v1.4 relation
語彙)、および tests/test_F008_relation_rules.py / tests/test_F008_contract_surface.py。

logit ルール(ADR 0016 決定2・3 — evidence から各 relation logit に加算):
  - near_user:       conv_strong なら += 1.5
  - approaching:     approaching(T1 フラグ)なら += 2.0
  - addressing_user: (call_user ∨ linked_addressing > 0.3) なら += 2.5(既存・保持)
                     【F-008 新規】(near_prox ∧ speaking_link) なら += 2.5
  - grouped:         n_speaking_links >= 2 なら += 1.0(既存)
                     【F-008 B1】multiple_humans なら += 2.0
                     【F-008 既定強化】上記 4 relation logit(near_user/approaching/
                       addressing_user/grouped)が全て 0 なら grouped 既定 += 2.0
  - 最終ラベル = relation logit の argmax

v1.4 relation 語彙は 4 クラス(addressing_user / near_user / approaching / grouped)。
departing / unrelated は勝ち GT が無く是正0のため不採用(ADR 0016 決定4)。

決定的(乱数・時刻なし)な純関数。発火した relation のみを logit dict のキーとして
持ち(未発火は欠落・値 0.0 と同義)、出力語彙は v1.4 4 クラスに閉じる。本モジュールは
stdlib のみに依存し、datagov/sealset/augment/guard/harness/quality/mode を改修しない。
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# v1.4 relation 統制語彙(ADR 0006 / 0016 決定1)のラベル定数。値は自身の文字列。
# departing / unrelated は ADR 0016 決定4 で不採用のため公開しない。
# ---------------------------------------------------------------------------

ADDRESSING_USER = "addressing_user"
NEAR_USER = "near_user"
APPROACHING = "approaching"
GROUPED = "grouped"


# ---------------------------------------------------------------------------
# logit 重み(ADR 0016 決定2・3・baseline/planA 計測値)。
# ---------------------------------------------------------------------------

_W_NEAR_USER = 1.5        # near_user: conv_strong
_W_APPROACHING = 2.0      # approaching: T1 フラグ
_W_ADDRESSING = 2.5       # addressing_user: 既存 / 新規(near_prox ∧ speaking_link)
_W_GROUPED_LINKS = 1.0    # grouped: n_speaking_links >= 2(既存)
_W_GROUPED_B1 = 2.0       # grouped: multiple_humans(B1)
_W_GROUPED_DEFAULT = 2.0  # grouped: 無証拠既定(1.0→2.0 へ強化)

#: linked_addressing の addressing 発火閾値(厳密 `> 0.3`)。
_LINKED_ADDRESSING_THRESHOLD = 0.3

#: argmax tie-break の決定的順序(ADR 0016 の固定ケースは全て一意 argmax)。
_LABEL_ORDER = (ADDRESSING_USER, NEAR_USER, APPROACHING, GROUPED)


def relation_logits(evidence) -> dict:
    """evidence(relation 証拠 dict)から各 relation の logit 値を返す(ADR 0016 決定2・3)。

    発火した relation のみをキーとして持つ dict を返す純関数(未発火 relation は
    欠落＝値 0.0 と同義)。証拠キーは欠落しうるため evidence.get(key, default) で
    安全に読む(bool 既定 False・float 既定 0.0・int 既定 0)。

    Args:
        evidence: {証拠キー: 値} の relation 証拠 dict。

    Returns:
        {relation_label: float} の logit 群。発火した relation のみ正の値を持つ。
        全証拠なし等で 4 logit が全て 0 のときは既定強化により grouped に 2.0 が乗る。
    """
    conv_strong = bool(evidence.get("conv_strong", False))
    approaching = bool(evidence.get("approaching", False))
    call_user = bool(evidence.get("call_user", False))
    linked_addressing = float(evidence.get("linked_addressing", 0.0))
    near_prox = bool(evidence.get("near_prox", False))
    speaking_link = bool(evidence.get("speaking_link", False))
    n_speaking_links = int(evidence.get("n_speaking_links", 0))
    multiple_humans = bool(evidence.get("multiple_humans", False))

    logits: dict = {}

    # near_user: conv_strong。
    if conv_strong:
        logits[NEAR_USER] = logits.get(NEAR_USER, 0.0) + _W_NEAR_USER

    # approaching: T1 フラグ。
    if approaching:
        logits[APPROACHING] = logits.get(APPROACHING, 0.0) + _W_APPROACHING

    # addressing_user: 既存(call_user ∨ linked_addressing > 0.3)。
    if call_user or linked_addressing > _LINKED_ADDRESSING_THRESHOLD:
        logits[ADDRESSING_USER] = logits.get(ADDRESSING_USER, 0.0) + _W_ADDRESSING
    # addressing_user: 【F-008 新規】near_prox ∧ speaking_link。
    elif near_prox and speaking_link:
        logits[ADDRESSING_USER] = logits.get(ADDRESSING_USER, 0.0) + _W_ADDRESSING

    # grouped: 既存(n_speaking_links >= 2)。
    if n_speaking_links >= 2:
        logits[GROUPED] = logits.get(GROUPED, 0.0) + _W_GROUPED_LINKS
    # grouped: 【F-008 B1】multiple_humans。
    if multiple_humans:
        logits[GROUPED] = logits.get(GROUPED, 0.0) + _W_GROUPED_B1

    # grouped: 【F-008 既定強化】4 relation logit が全て 0 なら grouped 既定 += 2.0。
    # B1 等で grouped が既に立っている場合は「全て 0」でないため既定は加えない。
    if not logits:
        logits[GROUPED] = _W_GROUPED_DEFAULT

    return logits


def classify(evidence) -> str:
    """evidence を relation logit の argmax で v1.4 relation ラベルに分類する(ADR 0016)。

    relation_logits の最大 logit を持つ relation ラベルを返す純関数。ADR 0016 の固定
    ケースは全て一意 argmax(tie は起きない)だが、念のため同値時は _LABEL_ORDER の
    固定順で決定的に選ぶ。

    Args:
        evidence: {証拠キー: 値} の relation 証拠 dict。

    Returns:
        v1.4 relation ラベル(addressing_user / near_user / approaching / grouped)。
    """
    logits = relation_logits(evidence)

    best_label = None
    best_value = None
    for label in _LABEL_ORDER:
        if label not in logits:
            continue
        value = logits[label]
        if best_value is None or value > best_value:
            best_label = label
            best_value = value

    return best_label
