"""F-008 relation logit ルール(計測根拠ケース): supreme.relation が ADR 0016 の
addressing 発火条件の再設計 + grouped 較正を満たすこと。テストは挙動
(relation 証拠 dict) → relation logit 群 / argmax ラベル を契約とし、内部実装は裁量
(挙動等価なら通る)。

契約の最終根拠:
  - decisions/0016-f008-relation-rules.md(手法の正・計測根拠)
      決定1: F-008 のスコープ = relation の logit ルール(relation 証拠 → relation
             logit → argmax)。PSO 入力からの証拠抽出(段1)は上流の共有基盤=スコープ外。
             relation 語彙は v1.4(addressing_user/near_user/approaching/grouped。
             departing/unrelated は勝ち GT が無く是正0のため追加しない)。
      決定2: addressing 発火条件の再設計(計測根拠・是正25/副作用10):
             新ルール `near_prox(min_range<3m) ∧ speaking_link≥1` → addressing_user += 2.5。
             これにより near_user(+1.5)より addressing(2.5)が優先される。
             既存の `call_user ∨ linked_addressing>0.3` → addressing += 2.5 も保持。
      決定3: grouped 較正(計測根拠・約6件是正):
             B1 `multiple_humans(humans≥2)` → grouped += 2.0。
             既定強化: 無証拠既定 grouped を 1.0 → 2.0(EMA 持ち越し型の振動を回収)。
  - specs/SPEC.md F-008 / decisions/0013(U1: relation=ルール改良)/
    decisions/0006(v1.4 relation 語彙)。

logit ルール(ADR 0016 決定2・3)— 入力 evidence(dict)から各 relation logit を加算:
  - near_user:       conv_strong なら += 1.5
  - approaching:     approaching(T1フラグ)なら += 2.0
  - addressing_user: (call_user ∨ linked_addressing>0.3) なら += 2.5(既存・保持)
                     【F-008 新規】(near_prox ∧ speaking_link≥1) なら += 2.5
  - grouped:         n_speaking_links≥2 なら += 1.0(既存)
                     【F-008 B1】multiple_humans なら += 2.0
                     【F-008 既定強化】上記の relation logit が全て 0 なら既定 += 2.0
  - 最終ラベル = relation logit の argmax

本ファイルの各ケースは ADR 0016 の**計測根拠ケース**(addressing 再設計の主たる勝ち筋・
near_user の生存・既存 addressing・B1・既定強化(logit 値)・approaching の保全・決定性)を
固定する。証拠抽出はスコープ外のため evidence を直接与える。既存 F-007(mode)/F-011
(quality)と同様の「ルール判定の完全一致採点」流儀を踏襲する。

argmax の tie-break について(ADR 0016 から一意に決まらない領域の明示):
  ADR 0016 の固定ケースは全て argmax が一意(同値の競合が起きない)に決まる。
  本ファイルは ADR 0016 の計測根拠ケースのみを固定し、人工的な同値 tie は作らない
  (tie-break 規約は ADR 0016 が定義しておらず、推測でテスト化しない)。
"""

import pytest

from supreme import relation


# ADR 0016 決定2・3: logit 重み(baseline/planA 計測値)。
W_NEAR_USER = 1.5        # near_user: conv_strong
W_APPROACHING = 2.0      # approaching: T1 フラグ
W_ADDRESSING = 2.5       # addressing_user: 既存 / 新規(near_prox ∧ speaking_link)
W_GROUPED_B1 = 2.0       # grouped: multiple_humans(B1)
W_GROUPED_DEFAULT = 2.0  # grouped: 無証拠既定(1.0→2.0 へ強化)


# ===========================================================================
# addressing 再設計(主たる勝ち筋)— ADR 0016 決定2
# near_prox ∧ speaking_link → addressing_user(near_user より優先)
# ===========================================================================

def test_F008_near_prox_and_speaking_link_fires_addressing():
    """F-008(ADR 0016 決定2・計測根拠 addressing 再設計): near_prox=True ∧
    speaking_link=True なら addressing_user が +2.5 で発火し argmax が addressing_user。

    call_user 証拠が入力に皆無(全210フレーム)なので、利用可能な証拠
    (近接 ∧ 発話リンク)で addressing を発火させる F-008 の主たる勝ち筋
    (是正25件相当の代表)。
    """
    ev = {"near_prox": True, "speaking_link": True}
    assert relation.classify(ev) == relation.ADDRESSING_USER


def test_F008_addressing_beats_near_user_when_both_fire():
    """F-008(ADR 0016 決定2・計測根拠 優先度): conv_strong=True で near_user(1.5)が
    立っても、同時に near_prox=True ∧ speaking_link=True なら addressing_user(2.5)が
    near_user に勝ち argmax が addressing_user。

    「優先度競合で near_user に劣後する」のではなく、addressing 証拠が発火すれば
    logit 値 2.5 > 1.5 で addressing が勝つ(発火条件の再設計の核心)。
    """
    ev = {"conv_strong": True, "near_prox": True, "speaking_link": True}
    logits = relation.relation_logits(ev)
    assert logits["addressing_user"] == pytest.approx(W_ADDRESSING)
    assert logits["near_user"] == pytest.approx(W_NEAR_USER)
    assert logits["addressing_user"] > logits["near_user"]
    assert relation.classify(ev) == relation.ADDRESSING_USER


def test_F008_near_prox_without_speaking_link_does_not_fire_addressing():
    """F-008(ADR 0016 決定2・境界): near_prox=True だが speaking_link=False(発話リンク
    無し)なら新 addressing ルールは発火しない(両証拠の AND が条件)。

    conv_strong も無いので addressing/near_user/approaching が全て 0 となり、
    既定強化により grouped(2.0)が argmax になる(addressing 単独証拠では立たない)。
    """
    ev = {"near_prox": True, "speaking_link": False}
    logits = relation.relation_logits(ev)
    assert logits.get("addressing_user", 0.0) == pytest.approx(0.0)
    assert relation.classify(ev) == relation.GROUPED


def test_F008_speaking_link_without_near_prox_does_not_fire_addressing():
    """F-008(ADR 0016 決定2・境界): speaking_link=True だが near_prox=False(近接でない)
    なら新 addressing ルールは発火しない(両証拠の AND が条件)。
    """
    ev = {"near_prox": False, "speaking_link": True}
    logits = relation.relation_logits(ev)
    assert logits.get("addressing_user", 0.0) == pytest.approx(0.0)


# ===========================================================================
# near_user の生存 — ADR 0016 決定2(addressing/near_user の境界)
# conv_strong だが near_prox=False(r 3-5m)→ near_user のまま
# ===========================================================================

def test_F008_conv_strong_without_near_prox_stays_near_user():
    """F-008(ADR 0016 決定2・計測根拠 near_user 生存): conv_strong=True だが
    near_prox=False(r 3-5m で min_range<3m を満たさない)なら addressing は発火せず、
    near_user(1.5)が argmax のまま。

    addressing 再設計が near_user を全て奪うわけではない境界(addressing 条件
    near_prox を満たさない近距離会話は near_user に残る)。
    """
    ev = {"conv_strong": True, "near_prox": False, "speaking_link": True}
    logits = relation.relation_logits(ev)
    assert logits["near_user"] == pytest.approx(W_NEAR_USER)
    assert logits.get("addressing_user", 0.0) == pytest.approx(0.0)
    assert relation.classify(ev) == relation.NEAR_USER


def test_F008_conv_strong_alone_is_near_user():
    """F-008(ADR 0016 決定2・near_user): conv_strong=True のみ(他証拠なし)なら
    near_user(1.5)が立ち、既定強化(grouped 2.0)より上か下かを logit 値で固定する。

    near_user 1.5 < grouped 既定 2.0 だが、near_user が立っている=「relation logit が
    全て 0」ではないので既定強化は発火しない(grouped は 0 のまま)→ argmax は near_user。
    """
    ev = {"conv_strong": True}
    logits = relation.relation_logits(ev)
    assert logits["near_user"] == pytest.approx(W_NEAR_USER)
    assert logits.get("grouped", 0.0) == pytest.approx(0.0), (
        "near_user が立っているのに grouped 既定強化が発火している"
        "(既定強化は relation logit が全て 0 のときのみ)"
    )
    assert relation.classify(ev) == relation.NEAR_USER


# ===========================================================================
# 既存 addressing(call_user / linked_addressing)— ADR 0016 決定2(保持)
# ===========================================================================

def test_F008_call_user_fires_addressing():
    """F-008(ADR 0016 決定2・既存 addressing 保持): call_user=True なら
    addressing_user が +2.5 で発火し argmax が addressing_user。

    現データセットでは call_user 証拠が皆無だが、将来 call_user 証拠が入る入力で
    有効な既存ルールを保持する(発火条件の再設計が既存ルールを壊さない)。
    """
    ev = {"call_user": True}
    logits = relation.relation_logits(ev)
    assert logits["addressing_user"] == pytest.approx(W_ADDRESSING)
    assert relation.classify(ev) == relation.ADDRESSING_USER


def test_F008_linked_addressing_above_threshold_fires_addressing():
    """F-008(ADR 0016 決定2・既存 addressing 保持): linked_addressing>0.3 なら
    addressing_user が +2.5 で発火し argmax が addressing_user。
    """
    ev = {"linked_addressing": 0.5}
    logits = relation.relation_logits(ev)
    assert logits["addressing_user"] == pytest.approx(W_ADDRESSING)
    assert relation.classify(ev) == relation.ADDRESSING_USER


def test_F008_linked_addressing_at_threshold_does_not_fire():
    """F-008(ADR 0016 決定2・境界): linked_addressing==0.3(閾値ちょうど)は
    `> 0.3`(厳密大なり)を満たさないため addressing は発火しない。

    閾値の向き(> 0.3)を一意に固定する。他証拠なしなので既定強化で grouped(2.0)。
    """
    ev = {"linked_addressing": 0.3}
    logits = relation.relation_logits(ev)
    assert logits.get("addressing_user", 0.0) == pytest.approx(0.0)
    assert relation.classify(ev) == relation.GROUPED


# ===========================================================================
# B1: multiple_humans → grouped += 2.0 — ADR 0016 決定3
# ===========================================================================

def test_F008_multiple_humans_adds_grouped_logit():
    """F-008(ADR 0016 決定3 B1・計測根拠): multiple_humans=True(他証拠なし)なら
    grouped logit に +2.0 が乗り、argmax が grouped。

    grouped に正証拠を与える B1 ルール(humans≥2)。multiple_humans で grouped=2.0 と
    なるため、これは「無証拠既定」ではなく B1 による発火である(値は 2.0 で一致)。
    """
    ev = {"multiple_humans": True}
    logits = relation.relation_logits(ev)
    assert logits["grouped"] == pytest.approx(W_GROUPED_B1)
    assert relation.classify(ev) == relation.GROUPED


def test_F008_multiple_humans_does_not_fire_other_relations():
    """F-008(ADR 0016 決定3 B1・対比): multiple_humans=True 単独では near_user/
    approaching/addressing_user は発火しない(grouped にのみ +2.0)。
    """
    ev = {"multiple_humans": True}
    logits = relation.relation_logits(ev)
    assert logits.get("near_user", 0.0) == pytest.approx(0.0)
    assert logits.get("approaching", 0.0) == pytest.approx(0.0)
    assert logits.get("addressing_user", 0.0) == pytest.approx(0.0)


# ===========================================================================
# 既定強化(logit 値で検証)— ADR 0016 決定3
# 全証拠なし → grouped 既定 logit == 2.0(baseline は 1.0)
# argmax 単独では 1.0/2.0 を区別不能なので "値" を直接アサートする
# ===========================================================================

def test_F008_no_evidence_grouped_default_logit_is_two():
    """F-008(ADR 0016 決定3 既定強化・計測根拠・重要): 全証拠なし(空 evidence)なら
    grouped 既定 logit が **2.0** であること(baseline は 1.0 だった)。

    重要: argmax 単独では既定が 1.0 でも 2.0 でも grouped になり区別不能。既定強化は
    EMA 持ち越し型の振動回収という "値" の効果なので、logit の値が 2.0 であることを
    直接アサートする(ADR 0016 が明示した検証要件)。
    """
    ev = {}
    logits = relation.relation_logits(ev)
    assert logits["grouped"] == pytest.approx(W_GROUPED_DEFAULT), (
        "無証拠既定 grouped logit が 2.0 でない(ADR 0016 決定3 既定強化: 1.0→2.0)"
    )


def test_F008_no_evidence_other_relations_are_zero():
    """F-008(ADR 0016 決定3 既定強化・前提): 全証拠なしなら grouped 以外の relation
    logit は全て 0(=「relation logit が全て 0」の状態で既定強化が発火する前提)。
    """
    ev = {}
    logits = relation.relation_logits(ev)
    assert logits.get("near_user", 0.0) == pytest.approx(0.0)
    assert logits.get("approaching", 0.0) == pytest.approx(0.0)
    assert logits.get("addressing_user", 0.0) == pytest.approx(0.0)


def test_F008_no_evidence_argmax_is_grouped():
    """F-008(ADR 0016 決定3 既定強化): 全証拠なしなら argmax は grouped。

    多数派 grouped(118/210)の大半が無証拠既定依存(計測)。既定を保全・強化する。
    """
    assert relation.classify({}) == relation.GROUPED


# ===========================================================================
# approaching の保全 — ADR 0016 決定4 / 決定2-3
# approaching=True → approaching(2.0)。発火時は既定強化が立たない(全logit 0でない)
# ===========================================================================

def test_F008_approaching_flag_fires_approaching():
    """F-008(ADR 0016 決定2・approaching 保全): approaching=True(T1フラグ)なら
    approaching logit が +2.0 で発火し argmax が approaching。
    """
    ev = {"approaching": True}
    logits = relation.relation_logits(ev)
    assert logits["approaching"] == pytest.approx(W_APPROACHING)
    assert relation.classify(ev) == relation.APPROACHING


def test_F008_approaching_suppresses_grouped_default():
    """F-008(ADR 0016 決定3・計測根拠 approaching を割らない): approaching=True 単独
    なら approaching(2.0)が発火し、relation logit が全て 0 ではないので既定強化
    grouped(2.0)は立たない(grouped は 0 のまま)→ argmax は approaching。

    既定強化 w=2.0 が approaching を巻き込まない最適点であること(w≥2.5/3.0 は
    approaching を割る、という ADR 0016 の計測根拠)を、approaching 発火時に既定が
    立たない=同値競合が起きない形で固定する。
    """
    ev = {"approaching": True}
    logits = relation.relation_logits(ev)
    assert logits["approaching"] == pytest.approx(W_APPROACHING)
    assert logits.get("grouped", 0.0) == pytest.approx(0.0), (
        "approaching が立っているのに grouped 既定強化が発火している"
        "(既定強化は relation logit が全て 0 のときのみ)"
    )
    assert relation.classify(ev) == relation.APPROACHING


# ===========================================================================
# 決定性(F-004-1 / F-007 / F-011 の流儀: 同入力で2回呼んで同一・乱数で揺れない)
# ===========================================================================

def test_F008_relation_rules_are_deterministic_same_label_twice():
    """F-008(決定性): 同じ evidence で2回呼ぶと argmax ラベルも logit dict も同一
    (乱数で揺れない)。

    relation logit ルールはルール判定であり学習・乱数を含まない(ADR 0016: 学習は
    しない。EMA/softmax 平滑化はスコープ外)。addressing 再設計・near_user 生存・
    既存 addressing・B1・既定強化・approaching 保全を含む代表点で完全一致を確認する。
    """
    cases = [
        {},
        {"conv_strong": True},
        {"approaching": True},
        {"near_prox": True, "speaking_link": True},
        {"conv_strong": True, "near_prox": True, "speaking_link": True},
        {"conv_strong": True, "near_prox": False, "speaking_link": True},
        {"call_user": True},
        {"linked_addressing": 0.5},
        {"multiple_humans": True},
    ]
    for ev in cases:
        first_label = relation.classify(ev)
        second_label = relation.classify(ev)
        assert first_label == second_label, (
            f"classify({ev!r}) が2回呼び出しで一致しない: "
            f"{first_label!r} != {second_label!r}"
        )
        first_logits = relation.relation_logits(ev)
        second_logits = relation.relation_logits(ev)
        assert first_logits == second_logits, (
            f"relation_logits({ev!r}) が2回呼び出しで一致しない: "
            f"{first_logits!r} != {second_logits!r}"
        )
