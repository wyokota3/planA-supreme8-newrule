"""F-006: role logit ルール層(role)。

supreme の role 判定。入力 = role 証拠(evidence dict)、出力 = 各 role の logit 群 と
その argmax ラベル。証拠抽出・softmax/EMA は上流の共有基盤でありスコープ外
(ADR 0017 決定2)。argmax は F-008 relation と同流儀。

契約の最終根拠は specs/SPEC.md「F-006」節、decisions/0017-f006-strong-reimplementation.md
(手法の正・独立再実装)、decisions/0006(v1.4 語彙)、および
tests/test_F006_role_logits.py。

logit ルール(ADR 0017 決定3 role):
  - has_siren OR has_alarm -> source_alarm += 1.5
    elif has_vehicle       -> source_vehicle += 1.5(緊急音優先)。
  - conv_strong(has_speech ∧ speaking>0.7 ∧ min_range<5) -> source_speech += 2.0。
  - conv_weak(has_speech ∧ speaking>0.3 ∧ min_range<4 ∧ ¬conv_strong)
                                                         -> source_speech += 1.0。
  - linked_speech_score>0.4 -> source_speech += 1.5。
  - 無証拠既定(role logit 全 0) -> unknown += 1.5。
  - 語彙 v1.4(6): source_speech / source_vehicle / source_alarm /
    source_human / source_object / unknown。source_human/source_object は発火ルールが
    無く出力されない(忠実再現・relation の departing/unrelated と同型)。
  - argmax は role logit の最大。

決定的(乱数・時刻なし)な純関数。発火した role のみを logit dict のキーとして持ち
(未発火は欠落・値 0.0 と同義)、出力語彙は v1.4 6 クラスに閉じる。本モジュールは
stdlib のみに依存し、datagov/sealset/augment/guard/harness/quality/mode/relation を
改修しない。
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# v1.4 role 統制語彙(ADR 0006 / 0017 決定3)のラベル定数。値は自身の文字列。
# source_human/source_object は発火ルールが無いが、語彙の一部として定数を公開する。
# ---------------------------------------------------------------------------

SOURCE_SPEECH = "source_speech"
SOURCE_VEHICLE = "source_vehicle"
SOURCE_ALARM = "source_alarm"
SOURCE_HUMAN = "source_human"
SOURCE_OBJECT = "source_object"
UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# logit 重み(ADR 0017 決定3 role・baseline/planA 計測値)。
# ---------------------------------------------------------------------------

_W_ALARM = 1.5          # source_alarm: has_siren OR has_alarm。
_W_VEHICLE = 1.5        # source_vehicle: elif has_vehicle。
_W_CONV_STRONG = 2.0    # source_speech: conv_strong。
_W_CONV_WEAK = 1.0      # source_speech: conv_weak。
_W_LINKED_SPEECH = 1.5  # source_speech: linked_speech_score>0.4。
_W_UNKNOWN = 1.5        # unknown: 無証拠既定。

# v1.5(C-1c): salient_kind(max-salience track の category)→ role。緊急音は別途絶対優先。
_W_SALIENT = 1.5
_SALIENT_TO_ROLE = {
    "speech": SOURCE_SPEECH,
    "vehicle": SOURCE_VEHICLE,
    "human": SOURCE_HUMAN,
    "object": SOURCE_OBJECT,
}

#: conv_strong / conv_weak / linked_speech の発火閾値(厳密 `>` / `<`)。
_SPEAKING_STRONG = 0.7   # conv_strong: speaking > 0.7。
_SPEAKING_WEAK = 0.3     # conv_weak: speaking > 0.3。
_RANGE_STRONG = 5.0      # conv_strong: min_range < 5。
_RANGE_WEAK = 4.0        # conv_weak: min_range < 4。
_LINKED_THRESHOLD = 0.4  # linked_speech_score > 0.4。

#: argmax tie-break の決定的順序。緊急音優先(source_alarm を source_speech より先)。
#: v021_core の固定ケースは全て一意 argmax(tie 無し)だったが、coverage_v1 held-out で
#: has_alarm ∧ linked_speech_score>0.4(speech track 無し)のとき source_alarm(1.5)と
#: source_speech(1.5)が同点になる。baseline は posterior 順序で source_alarm を選ぶ(緊急音
#: 優先・実測)。旧順序(speech 先頭)は baseline と不一致で role を一方的に悪化させていた
#: (coverage_v1/seal で role -0.076 回帰・disagree 62件全て supreme のみ誤り)。緊急音優先で忠実化。
_LABEL_ORDER = (
    SOURCE_ALARM,
    SOURCE_VEHICLE,
    SOURCE_SPEECH,
    SOURCE_HUMAN,
    SOURCE_OBJECT,
    UNKNOWN,
)


def role_logits(evidence) -> dict:
    """evidence(role 証拠 dict)から各 role の logit 値を返す(ADR 0017 決定3 role)。

    発火した role のみをキーとして持つ dict を返す純関数(未発火 role は欠落＝値 0.0
    と同義)。証拠キーは欠落しうるため evidence.get(key, default) で安全に読む。

    Args:
        evidence: {証拠キー: 値} の role 証拠 dict。

    Returns:
        {role_label: float} の logit 群。発火した role のみ正の値を持つ。
        role logit が全て 0 のときは無証拠既定により unknown に 1.5 が乗る。
    """
    has_siren = bool(evidence.get("has_siren", False))
    has_alarm = bool(evidence.get("has_alarm", False))
    has_vehicle = bool(evidence.get("has_vehicle", False))
    has_speech = bool(evidence.get("has_speech", False))
    speaking = float(evidence.get("speaking", 0.0))
    min_range = float(evidence.get("min_range", 0.0))
    linked_speech_score = float(evidence.get("linked_speech_score", 0.0))

    logits: dict = {}

    # v1.5(C-1c・presence-gated): salient_kind が在れば「緊急音絶対優先 → それ以外 argmax salience の
    # category」で role を決める(contract v1.5 §6 / Rc3)。salient_kind 不在(v1.4)は従来の4クラス規則。
    salient_kind = evidence.get("salient_kind")
    if salient_kind is not None:
        if has_siren or has_alarm:
            return {SOURCE_ALARM: _W_ALARM}
        label = _SALIENT_TO_ROLE.get(salient_kind)
        return {label: _W_SALIENT} if label else {UNKNOWN: _W_UNKNOWN}

    # 緊急音優先: has_siren OR has_alarm -> source_alarm / elif has_vehicle -> source_vehicle。
    if has_siren or has_alarm:
        logits[SOURCE_ALARM] = logits.get(SOURCE_ALARM, 0.0) + _W_ALARM
    elif has_vehicle:
        logits[SOURCE_VEHICLE] = logits.get(SOURCE_VEHICLE, 0.0) + _W_VEHICLE

    # conv_strong: has_speech ∧ speaking>0.7 ∧ min_range<5 -> source_speech += 2.0。
    conv_strong = (
        has_speech and speaking > _SPEAKING_STRONG and min_range < _RANGE_STRONG
    )
    if conv_strong:
        logits[SOURCE_SPEECH] = logits.get(SOURCE_SPEECH, 0.0) + _W_CONV_STRONG

    # conv_weak: has_speech ∧ speaking>0.3 ∧ min_range<4 ∧ ¬conv_strong -> += 1.0。
    conv_weak = (
        has_speech
        and speaking > _SPEAKING_WEAK
        and min_range < _RANGE_WEAK
        and not conv_strong
    )
    if conv_weak:
        logits[SOURCE_SPEECH] = logits.get(SOURCE_SPEECH, 0.0) + _W_CONV_WEAK

    # linked_speech_score>0.4 -> source_speech += 1.5。
    if linked_speech_score > _LINKED_THRESHOLD:
        logits[SOURCE_SPEECH] = logits.get(SOURCE_SPEECH, 0.0) + _W_LINKED_SPEECH

    # 無証拠既定: role logit が全て 0(発火ゼロ)のとき unknown += 1.5。
    if not logits:
        logits[UNKNOWN] = _W_UNKNOWN

    return logits


def classify(evidence) -> str:
    """evidence を role logit の argmax で v1.4 role ラベルに分類する(ADR 0017 決定3 role)。

    role_logits の最大 logit を持つ role ラベルを返す純関数。ADR 0017 の固定ケースは
    全て一意 argmax(tie は起きない)だが、念のため同値時は _LABEL_ORDER の固定順で
    決定的に選ぶ。

    Args:
        evidence: {証拠キー: 値} の role 証拠 dict。

    Returns:
        v1.4 role ラベル(source_speech / source_vehicle / source_alarm /
        source_human / source_object / unknown)。
    """
    logits = role_logits(evidence)

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
