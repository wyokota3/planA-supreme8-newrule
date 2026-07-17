"""F-006 role (t2_role) 流用移植・独立再実装: supreme の role logit ルールが ADR 0017
決定3 の baseline ルール(緊急音優先 + conv_strong/weak + linked_speech + 無証拠既定)を
忠実再現すること。テストは挙動 (evidence dict) → role logit 群 / argmax ラベル を契約とし、
内部実装は裁量(挙動等価なら通る)。F-008 relation と同型(logit ルール)。

契約の最終根拠:
  - decisions/0017-f006-strong-reimplementation.md(手法の正・流用形態 U9)
      決定1: 独立再実装(baseline コードへ実行時リンクしない・F-006-2)。
      決定2: role は logit ルール(argmax は F-008 relation と同流儀)。証拠抽出・
             softmax/EMA は上流共有基盤=スコープ外(テストは evidence を直接与える)。
      決定3 role (t2_role・logit ルール):
        - has_siren OR has_alarm -> source_alarm += 1.5
          elif has_vehicle      -> source_vehicle += 1.5(緊急音優先)。
        - conv_strong(has_speech ∧ speaking>0.7 ∧ min_range<5) -> source_speech += 2.0。
        - conv_weak(has_speech ∧ speaking>0.3 ∧ min_range<4 ∧ ¬conv_strong)
                                                            -> source_speech += 1.0。
        - linked_speech_score>0.4 -> source_speech += 1.5。
        - 無証拠既定(role logit 全 0) -> unknown += 1.5。
        - 語彙 v1.4(6): source_speech / source_vehicle / source_alarm /
          source_human / source_object / unknown。source_human/source_object は
          発火ルールが無く出力されない(忠実再現・relation の departing/unrelated と同型)。
        - argmax は role logit の最大(softmax/EMA は上流・スコープ外)。
  - specs/SPEC.md F-006 / decisions/0006(v1.4 語彙)/ tests/test_F008_relation_rules.py
    (logit ルール・role と同型の流儀)。

スコープ外(ADR 0017): 証拠抽出・softmax/EMA・baseline 数値一致(δ_strong は F-013 で
測定)。テストは evidence(dict)を直接与え、role logit 値 / argmax ラベルを採点する。

設計裁量(指示で明示委任・既存 F-008 relation の流儀に合わせる):
  role.role_logits(evidence: dict) -> dict[str, float]
      ADR 0017 決定3 role の logit ルールで各 role の logit 値を返す。
  role.classify(evidence: dict) -> str
      role logit の argmax で v1.4 role ラベル文字列を返す。
  role.SOURCE_SPEECH / SOURCE_VEHICLE / SOURCE_ALARM / SOURCE_HUMAN /
  role.SOURCE_OBJECT / UNKNOWN -> str
      v1.4 統制語彙のラベル定数(6クラス)。

ADR 0017 から一意に決まらない点(推測でテスト化しない):
  - argmax の tie-break(同値の role logit が複数最大)は ADR 0017 が規定しない
    (F-008 relation と同方針)。本ファイルは ADR 0017 の発火ルールから argmax が一意に
    決まるケースのみ固定し、人工的な同値 tie は作らない。
  - source_human / source_object は発火ルールが無い(忠実再現)。これらが argmax に
    なる入力は ADR 0017 のルール上存在しないため、それらの選好は固定しない。
"""

import pytest

from supreme import role


# ADR 0017 決定3 role: logit 重み(baseline/planA 計測値)。
W_ALARM = 1.5          # source_alarm: has_siren OR has_alarm
W_VEHICLE = 1.5        # source_vehicle: elif has_vehicle
W_CONV_STRONG = 2.0    # source_speech: conv_strong
W_CONV_WEAK = 1.0      # source_speech: conv_weak
W_LINKED_SPEECH = 1.5  # source_speech: linked_speech_score>0.4
W_UNKNOWN = 1.5        # unknown: 無証拠既定


# ===========================================================================
# 緊急音優先: has_siren OR has_alarm -> source_alarm / elif has_vehicle -> source_vehicle
# ADR 0017 決定3 role
# ===========================================================================

def test_F006_has_siren_fires_source_alarm():
    """F-006(ADR 0017 決定3 role): has_siren=True なら source_alarm に +1.5 が乗り
    argmax が source_alarm。
    """
    ev = {"has_siren": True}
    logits = role.role_logits(ev)
    assert logits["source_alarm"] == pytest.approx(W_ALARM)
    assert role.classify(ev) == role.SOURCE_ALARM


def test_F006_has_alarm_fires_source_alarm():
    """F-006(ADR 0017 決定3 role): has_alarm=True なら source_alarm に +1.5 が乗り
    argmax が source_alarm(siren OR alarm の OR の片側)。
    """
    ev = {"has_alarm": True}
    logits = role.role_logits(ev)
    assert logits["source_alarm"] == pytest.approx(W_ALARM)
    assert role.classify(ev) == role.SOURCE_ALARM


def test_F006_has_vehicle_fires_source_vehicle():
    """F-006(ADR 0017 決定3 role): has_vehicle=True(siren/alarm 無し)なら source_vehicle に
    +1.5 が乗り argmax が source_vehicle。
    """
    ev = {"has_vehicle": True}
    logits = role.role_logits(ev)
    assert logits["source_vehicle"] == pytest.approx(W_VEHICLE)
    assert role.classify(ev) == role.SOURCE_VEHICLE


def test_F006_emergency_audio_takes_priority_over_vehicle():
    """F-006(ADR 0017 決定3 role・緊急音優先 elif): has_siren=True ∧ has_vehicle=True なら、
    elif 構造により source_alarm のみ +1.5、source_vehicle は発火しない(0)。

    `has_siren OR has_alarm` が真なら elif の vehicle 枝に入らない。緊急音優先を
    source_vehicle が 0 であることで固定する。
    """
    ev = {"has_siren": True, "has_vehicle": True}
    logits = role.role_logits(ev)
    assert logits["source_alarm"] == pytest.approx(W_ALARM)
    assert logits.get("source_vehicle", 0.0) == pytest.approx(0.0), (
        "緊急音(siren/alarm)優先の elif なのに source_vehicle が発火している"
    )
    assert role.classify(ev) == role.SOURCE_ALARM


# ===========================================================================
# conv_strong: has_speech ∧ speaking>0.7 ∧ min_range<5 -> source_speech += 2.0
# ADR 0017 決定3 role
# ===========================================================================

def test_F006_conv_strong_fires_source_speech_two():
    """F-006(ADR 0017 決定3 role・conv_strong): has_speech ∧ speaking=0.8(>0.7) ∧
    min_range=3.0(<5)なら source_speech に +2.0 が乗り argmax が source_speech。
    """
    ev = {"has_speech": True, "speaking": 0.8, "min_range": 3.0}
    logits = role.role_logits(ev)
    assert logits["source_speech"] == pytest.approx(W_CONV_STRONG)
    assert role.classify(ev) == role.SOURCE_SPEECH


def test_F006_conv_strong_speaking_at_0_7_does_not_fire_strong():
    """F-006(ADR 0017 決定3 role・境界 conv_strong speaking>0.7): speaking=0.7(閾値ちょうど・
    >0.7 を満たさない)では conv_strong は発火しない。

    has_speech ∧ speaking=0.7 ∧ min_range=3.0(<5)。conv_strong は不発だが、
    conv_weak(speaking>0.3 ∧ min_range<4 ∧ ¬conv_strong)は満たすので source_speech に
    +1.0(2.0 ではない)。閾値の向き(>0.7)を strong=2.0 でない=1.0 で固定する。
    """
    ev = {"has_speech": True, "speaking": 0.7, "min_range": 3.0}
    logits = role.role_logits(ev)
    assert logits["source_speech"] == pytest.approx(W_CONV_WEAK), (
        "speaking=0.7 は conv_strong(>0.7)不発・conv_weak(>0.3)発火で +1.0 のはず"
    )


def test_F006_conv_strong_min_range_at_5_does_not_fire_strong():
    """F-006(ADR 0017 決定3 role・境界 conv_strong min_range<5): min_range=5.0(閾値ちょうど・
    <5 を満たさない)では conv_strong は発火しない。

    has_speech ∧ speaking=0.8 ∧ min_range=5.0。conv_strong 不発。conv_weak も
    min_range<4 を満たさない(5.0 は <4 でない)ため不発。linked も無し。よって
    role logit 全 0 となり無証拠既定 unknown(1.5)。閾値の向き(<5)を固定する。
    """
    ev = {"has_speech": True, "speaking": 0.8, "min_range": 5.0}
    logits = role.role_logits(ev)
    assert logits.get("source_speech", 0.0) == pytest.approx(0.0), (
        "min_range=5.0 は conv_strong(<5)・conv_weak(<4)とも不発のはず"
    )
    assert role.classify(ev) == role.UNKNOWN


# ===========================================================================
# conv_weak: has_speech ∧ speaking>0.3 ∧ min_range<4 ∧ ¬conv_strong -> += 1.0
# ADR 0017 決定3 role
# ===========================================================================

def test_F006_conv_weak_fires_source_speech_one():
    """F-006(ADR 0017 決定3 role・conv_weak): has_speech ∧ speaking=0.5(>0.3, ≤0.7) ∧
    min_range=3.0(<4)で conv_strong を満たさないなら source_speech に +1.0。

    speaking=0.5 は conv_strong の speaking>0.7 を満たさない(¬conv_strong)が、
    conv_weak(speaking>0.3 ∧ min_range<4)を満たす。weak の +1.0(strong の 2.0 でない)を固定。
    """
    ev = {"has_speech": True, "speaking": 0.5, "min_range": 3.0}
    logits = role.role_logits(ev)
    assert logits["source_speech"] == pytest.approx(W_CONV_WEAK)
    assert role.classify(ev) == role.SOURCE_SPEECH


def test_F006_conv_weak_speaking_at_0_3_does_not_fire():
    """F-006(ADR 0017 決定3 role・境界 conv_weak speaking>0.3): speaking=0.3(閾値ちょうど・
    >0.3 を満たさない)では conv_weak は発火しない。

    has_speech ∧ speaking=0.3 ∧ min_range=3.0(<4)。conv_strong も conv_weak も不発、
    linked 無し -> role logit 全 0 -> 無証拠既定 unknown。閾値の向き(>0.3)を固定する。
    """
    ev = {"has_speech": True, "speaking": 0.3, "min_range": 3.0}
    logits = role.role_logits(ev)
    assert logits.get("source_speech", 0.0) == pytest.approx(0.0)
    assert role.classify(ev) == role.UNKNOWN


def test_F006_conv_weak_min_range_at_4_does_not_fire():
    """F-006(ADR 0017 決定3 role・境界 conv_weak min_range<4): min_range=4.0(閾値ちょうど・
    <4 を満たさない)では conv_weak は発火しない。

    has_speech ∧ speaking=0.5 ∧ min_range=4.0。conv_strong 不発(speaking≤0.7)・
    conv_weak 不発(min_range は <4 でない)・linked 無し -> 無証拠既定 unknown。
    閾値の向き(<4)を固定する。
    """
    ev = {"has_speech": True, "speaking": 0.5, "min_range": 4.0}
    logits = role.role_logits(ev)
    assert logits.get("source_speech", 0.0) == pytest.approx(0.0)
    assert role.classify(ev) == role.UNKNOWN


def test_F006_conv_strong_excludes_conv_weak_no_double_count():
    """F-006(ADR 0017 決定3 role・conv_weak の ¬conv_strong 条件): conv_strong が発火する
    入力では conv_weak は ¬conv_strong により発火せず、source_speech は 2.0(2.0+1.0=3.0
    にならない)。

    has_speech ∧ speaking=0.8(>0.7) ∧ min_range=3.0(<5 かつ <4)。conv_strong 発火。
    conv_weak は ¬conv_strong 条件で抑止。二重加算しないことを source_speech==2.0 で固定。
    """
    ev = {"has_speech": True, "speaking": 0.8, "min_range": 3.0}
    logits = role.role_logits(ev)
    assert logits["source_speech"] == pytest.approx(W_CONV_STRONG), (
        "conv_strong と conv_weak が二重加算されている(¬conv_strong 条件の漏れ)"
    )


# ===========================================================================
# linked_speech_score>0.4 -> source_speech += 1.5 — ADR 0017 決定3 role
# ===========================================================================

def test_F006_linked_speech_above_threshold_fires():
    """F-006(ADR 0017 決定3 role・linked_speech): linked_speech_score=0.5(>0.4)なら
    source_speech に +1.5。

    他に speech 証拠(conv_strong/weak)が無いなら source_speech=1.5 で argmax は
    source_speech。
    """
    ev = {"linked_speech_score": 0.5}
    logits = role.role_logits(ev)
    assert logits["source_speech"] == pytest.approx(W_LINKED_SPEECH)
    assert role.classify(ev) == role.SOURCE_SPEECH


def test_F006_linked_speech_at_threshold_does_not_fire():
    """F-006(ADR 0017 決定3 role・境界 linked_speech>0.4): linked_speech_score=0.4
    (閾値ちょうど・>0.4 を満たさない)では発火しない。

    他証拠も無いので role logit 全 0 -> 無証拠既定 unknown。閾値の向き(>0.4)を固定する。
    """
    ev = {"linked_speech_score": 0.4}
    logits = role.role_logits(ev)
    assert logits.get("source_speech", 0.0) == pytest.approx(0.0)
    assert role.classify(ev) == role.UNKNOWN


def test_F006_speech_evidence_accumulates_conv_strong_plus_linked():
    """F-006(ADR 0017 決定3 role・source_speech 累積): conv_strong(+2.0)と
    linked_speech(+1.5)はともに source_speech に乗り、合算 3.5 になる。

    has_speech ∧ speaking=0.8 ∧ min_range=3.0(conv_strong)∧ linked_speech_score=0.5
    (>0.4)。source_speech = 2.0 + 1.5 = 3.5(同じ role への複数ルールは加算)。
    """
    ev = {
        "has_speech": True,
        "speaking": 0.8,
        "min_range": 3.0,
        "linked_speech_score": 0.5,
    }
    logits = role.role_logits(ev)
    assert logits["source_speech"] == pytest.approx(W_CONV_STRONG + W_LINKED_SPEECH)
    assert role.classify(ev) == role.SOURCE_SPEECH


# ===========================================================================
# 無証拠既定: role logit 全 0 -> unknown += 1.5 — ADR 0017 決定3 role
# ===========================================================================

def test_F006_no_evidence_default_is_unknown_logit_1_5():
    """F-006(ADR 0017 決定3 role・無証拠既定・重要): 空 evidence(全証拠なし)なら
    unknown 既定 logit が **1.5** で、argmax は unknown。

    role logit が全て 0 のときのみ unknown=1.5 が発火する既定。argmax 単独では区別
    できない部分があるため logit "値" を直接アサートする(F-008 既定強化と同型の検証要件)。
    """
    ev = {}
    logits = role.role_logits(ev)
    assert logits["unknown"] == pytest.approx(W_UNKNOWN), (
        "無証拠既定 unknown logit が 1.5 でない(ADR 0017 決定3 role 無証拠既定)"
    )
    assert role.classify(ev) == role.UNKNOWN


def test_F006_default_unknown_only_when_all_role_logits_zero():
    """F-006(ADR 0017 決定3 role・無証拠既定の前提): いずれかの role logit が立っていれば
    unknown 既定は発火しない(unknown は 0 のまま)。

    has_speech ∧ speaking=0.8 ∧ min_range=3.0 で source_speech=2.0 が立つので、
    role logit は全 0 ではない -> 無証拠既定 unknown は発火しない(unknown==0)。
    """
    ev = {"has_speech": True, "speaking": 0.8, "min_range": 3.0}
    logits = role.role_logits(ev)
    assert logits.get("unknown", 0.0) == pytest.approx(0.0), (
        "source_speech が立っているのに無証拠既定 unknown が発火している"
        "(既定は role logit 全 0 のときのみ)"
    )


# ===========================================================================
# source_human / source_object は発火ルールが無く出力されない(忠実再現)
# ADR 0017 決定3 role(relation の departing/unrelated と同型)
# ===========================================================================

def test_F006_source_human_object_have_no_firing_rule():
    """F-006(ADR 0017 決定3 role・忠実再現): source_human / source_object には発火ルールが
    無く、どの証拠を与えても logit が立たない(0 のまま、または出力されない)。

    baseline は source_human/source_object に発火ルールが無く出力されない(忠実再現・
    relation の departing/unrelated と同型)。代表的な証拠群で常に 0 であることを固定する。
    """
    samples = [
        {},
        {"has_siren": True},
        {"has_vehicle": True},
        {"has_speech": True, "speaking": 0.8, "min_range": 3.0},
        {"linked_speech_score": 0.5},
    ]
    for ev in samples:
        logits = role.role_logits(ev)
        assert logits.get("source_human", 0.0) == pytest.approx(0.0), (
            f"role_logits({ev!r}) で source_human が立っている(発火ルール無しのはず)"
        )
        assert logits.get("source_object", 0.0) == pytest.approx(0.0), (
            f"role_logits({ev!r}) で source_object が立っている(発火ルール無しのはず)"
        )


# ===========================================================================
# 出力語彙は v1.4 role(6クラス)— ADR 0006 / 0017
# ===========================================================================

V14_ROLE_LABELS = {
    "source_speech",
    "source_vehicle",
    "source_alarm",
    "source_human",
    "source_object",
    "unknown",
}


def test_F006_role_logits_keys_are_v14_vocabulary():
    """F-006(ADR 0006/0017 role 語彙): role_logits の戻り値キーは v1.4 role 6クラスに
    閉じる(開いた辞書にしない)。
    """
    samples = [
        {},
        {"has_siren": True},
        {"has_vehicle": True},
        {"has_speech": True, "speaking": 0.8, "min_range": 3.0},
        {"has_speech": True, "speaking": 0.5, "min_range": 3.0},
        {"linked_speech_score": 0.5},
    ]
    for ev in samples:
        logits = role.role_logits(ev)
        assert isinstance(logits, dict), (
            f"role_logits({ev!r}) が dict を返さない: {logits!r}"
        )
        assert set(logits).issubset(V14_ROLE_LABELS), (
            f"role_logits({ev!r}) が v1.4 語彙外のキーを含む: {set(logits)!r}"
        )


def test_F006_classify_returns_only_v14_role_labels():
    """F-006(ADR 0017 role argmax): classify は v1.4 role 6クラスのいずれかのみを返す
    (None や語彙外を返さない)。
    """
    samples = [
        {},
        {"has_siren": True},
        {"has_alarm": True},
        {"has_vehicle": True},
        {"has_siren": True, "has_vehicle": True},
        {"has_speech": True, "speaking": 0.8, "min_range": 3.0},
        {"has_speech": True, "speaking": 0.5, "min_range": 3.0},
        {"linked_speech_score": 0.5},
    ]
    for ev in samples:
        label = role.classify(ev)
        assert label in V14_ROLE_LABELS, (
            f"classify({ev!r}) が v1.4 role 6クラス外を返した: {label!r}"
        )


def test_F006_role_exposes_v14_label_constants():
    """F-006(契約面・ADR 0006/0017): role は v1.4 role 6クラスをラベル定数として公開し、
    その値がそれぞれの文字列であること(語彙 faithfulness)。

    source_human/source_object は発火しないが、v1.4 語彙の一部として定数は公開する
    (語彙は 6 クラス・ADR 0017 決定3 role)。
    """
    expected = {
        "SOURCE_SPEECH": "source_speech",
        "SOURCE_VEHICLE": "source_vehicle",
        "SOURCE_ALARM": "source_alarm",
        "SOURCE_HUMAN": "source_human",
        "SOURCE_OBJECT": "source_object",
        "UNKNOWN": "unknown",
    }
    for name, value in expected.items():
        assert hasattr(role, name), f"role.{name} が公開されていない"
        assert getattr(role, name) == value, (
            f"role.{name} の値が '{value}' でない(v1.4 語彙 faithfulness 違反)"
        )


# ===========================================================================
# 決定性(F-008 relation と同流儀: 同入力で2回呼んで同一・乱数で揺れない)
# ===========================================================================

def test_F006_role_rules_are_deterministic_same_label_twice():
    """F-006(決定性): 同じ evidence で2回呼ぶと argmax ラベルも logit dict も同一
    (乱数で揺れない)。

    role logit ルールはルール判定であり学習・乱数を含まない(softmax/EMA はスコープ外)。
    緊急音優先・conv_strong/weak・linked・無証拠既定を含む代表点で完全一致を確認する。
    """
    cases = [
        {},
        {"has_siren": True},
        {"has_vehicle": True},
        {"has_siren": True, "has_vehicle": True},
        {"has_speech": True, "speaking": 0.8, "min_range": 3.0},
        {"has_speech": True, "speaking": 0.5, "min_range": 3.0},
        {"linked_speech_score": 0.5},
        {
            "has_speech": True,
            "speaking": 0.8,
            "min_range": 3.0,
            "linked_speech_score": 0.5,
        },
    ]
    for ev in cases:
        first_label = role.classify(ev)
        second_label = role.classify(ev)
        assert first_label == second_label, (
            f"classify({ev!r}) が2回で不一致: {first_label!r} != {second_label!r}"
        )
        first_logits = role.role_logits(ev)
        second_logits = role.role_logits(ev)
        assert first_logits == second_logits, (
            f"role_logits({ev!r}) が2回で不一致: {first_logits!r} != {second_logits!r}"
        )
