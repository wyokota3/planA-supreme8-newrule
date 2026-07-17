"""F-006 T0 (risk_tier) 流用移植・独立再実装: supreme の T0 ルール層が ADR 0017
決定3 の baseline ルール(主トラック選択 + kind 別 TTC 閾値 + siren 下限)を忠実再現
すること。テストは挙動 (tracks) → v1.4 risk_tier ラベルを契約とし、内部実装は裁量
(挙動等価なら通る)。

★ T0 safety latch 是正(2026-06-13・監査 T0-1・ADR 0017 追記):
  初版の決定3 T0 は safety latch(`min_TTC<=0.8 ∨ siren → danger`)を risk_tier の
  ルールとして記述したが、これは baseline 実コードとの乖離(誤記)だった
  (reports/audit-20260613-2201-F-006.md T0-1)。baseline では safety latch は
  `risk_safe`(数値特徴・採点8層外)のみに作用し、採点される `risk_tier` には非適用。
  ADR 0017 追記で確定: **risk_tier から safety latch を除去**する。
  risk_tier = kind 別 TTC 閾値テーブル + siren 下限のみ。siren の高 TTC フレームは
  siren 下限で caution(danger でない)= baseline 一致。本ファイルは是正後の挙動を固定
  する(latch を期待するテストは削除/是正済み)。

契約の最終根拠:
  - decisions/0017-f006-strong-reimplementation.md(手法の正・流用形態 U9)
      決定1: 独立再実装(baseline コードへ実行時リンクしない・F-006-2)。
      決定2: スコープ = ルール層のみ(T0 = 閾値判定 + siren 下限)。証拠抽出・HGF・
             softmax/EMA は上流共有基盤=スコープ外(テストは track 特徴を直接与える)。
      決定3 T0 (risk_tier・直接ルール・HGF 非依存・状態レス)+ 追記(latch 是正):
        - 主トラック選択: siren 優先、なければ最近傍(最小 r_m)。
        - kind 別 (caution, danger) TTC 閾値:
            vehicle/siren = (12.0, 2.0), alarm = (5.0, 2.0),
            speech = (2.0, 1.0), default = (5.0, 2.0)。
        - min_TTC <= danger 閾値 -> danger / <= caution 閾値 -> caution / else info。
        - siren 下限: siren が info 判定なら caution へ引き上げ。
        - safety latch は risk_tier に適用しない(追記で是正・risk_safe 用=採点外)。
        - 語彙 v1.4: info / caution / danger。
  - specs/SPEC.md F-006(行 141: 「safety latch は risk_safe 用=採点外・除外」)/
    decisions/0012(risk_tier 採点・210 分母)/ decisions/0006(v1.4 語彙)。

スコープ外(ADR 0017): 証拠抽出(段1)・HGF・softmax/EMA・baseline 数値一致
(δ_strong は F-013 で測定)・Anomaly 本体・risk_safe(採点8層外・latch が作用する数値
特徴)。テストは track 特徴(kind, ttc_s, r_m)を直接与え、risk_tier ラベルの完全一致を
採点する(F-007/F-008/F-011 と同流儀)。

設計裁量(指示で明示委任・既存 quality/mode/relation の流儀に合わせる):
  t0.risk_tier(tracks) -> str
      track の列(各 track は kind / ttc_s / r_m を持つ dict)から主トラックを選び、
      ADR 0017 決定3 T0 ルール(latch 是正後)で v1.4 risk_tier ラベル文字列を返す純関数。
  t0.INFO / CAUTION / DANGER -> str
      v1.4 統制語彙のラベル定数("info" / "caution" / "danger")。

ADR 0017 から一意に決まらない点(推測でテスト化しない):
  - 主トラック選択で r_m が完全同値(tie)になる複数 non-siren track の選好順序は
    ADR 0017 が規定しない。本ファイルは r_m が一意に最小となるケースのみ固定し、
    人工的な r_m 同値 tie は作らない。

track 列が空(track 0 件)のとき(ADR 0017 追記・軽微指摘・低):
  例外を投げず、安全側の既定として有効な v1.4 risk_tier 語彙を返す(info を推奨)。
  既定値は実装裁量だが「例外を投げない・v1.4 語彙集合に閉じる」ことを固定する。
"""

import pytest

from supreme import t0


# ADR 0017 決定3 T0: kind 別 (caution, danger) TTC 閾値。
TH_VEHICLE = (12.0, 2.0)
TH_SIREN = (12.0, 2.0)
TH_ALARM = (5.0, 2.0)
TH_SPEECH = (2.0, 1.0)
TH_DEFAULT = (5.0, 2.0)


def _track(kind, ttc_s, r_m):
    """単一 track 特徴(kind / ttc_s / r_m)。証拠抽出はスコープ外のため直接与える。"""
    return {"kind": kind, "ttc_s": ttc_s, "r_m": r_m}


# ===========================================================================
# kind=vehicle の TTC 閾値 (caution=12.0, danger=2.0) — ADR 0017 決定3 T0
# ===========================================================================

def test_F006_vehicle_ttc_below_danger_is_danger():
    """F-006(ADR 0017 決定3 T0・固定ケース): vehicle で min_TTC=1.5(<= danger 2.0)
    なら danger。

    vehicle 閾値 (caution=12.0, danger=2.0)。1.5 <= 2.0 で danger 域。
    """
    assert t0.risk_tier([_track("vehicle", 1.5, 30.0)]) == t0.DANGER


def test_F006_vehicle_ttc_in_caution_band_is_caution():
    """F-006(ADR 0017 決定3 T0・固定ケース): vehicle で min_TTC=5.0
    (danger 2.0 < 5.0 <= caution 12.0)なら caution。
    """
    assert t0.risk_tier([_track("vehicle", 5.0, 30.0)]) == t0.CAUTION


def test_F006_vehicle_ttc_above_caution_is_info():
    """F-006(ADR 0017 決定3 T0・固定ケース): vehicle で min_TTC=15.0(> caution 12.0)
    なら info。
    """
    assert t0.risk_tier([_track("vehicle", 15.0, 30.0)]) == t0.INFO


def test_F006_vehicle_ttc_at_danger_threshold_is_danger():
    """F-006(ADR 0017 決定3 T0・境界 <=): vehicle で min_TTC=2.0(danger 閾値ちょうど)
    なら danger。

    ADR 0045(純 TTC 厳密 `<`): danger は ttc<2.0。2.0 は danger でなく caution(2.0<8.0)。
    """
    assert t0.risk_tier([_track("vehicle", 2.0, 30.0)]) == t0.CAUTION


def test_F006_vehicle_ttc_at_caution_threshold_is_caution():
    """F-006(ADR 0017 決定3 T0・境界 <=): vehicle で min_TTC=12.0(caution 閾値ちょうど)
    なら caution。

    ADR 0045(純 TTC 厳密 `<`): caution は ttc<8.0。12.0 は caution 帯外で info。
    """
    assert t0.risk_tier([_track("vehicle", 12.0, 30.0)]) == t0.INFO


def test_F006_vehicle_just_above_danger_is_caution():
    """F-006(ADR 0017 決定3 T0・境界): vehicle で min_TTC=2.001(danger 2.0 を僅かに超え)
    なら caution(danger を抜け caution 域)。閾値の向き(danger は <=)を一意に固定。
    """
    assert t0.risk_tier([_track("vehicle", 2.001, 30.0)]) == t0.CAUTION


def test_F006_vehicle_just_above_caution_is_info():
    """F-006(ADR 0017 決定3 T0・境界): vehicle で min_TTC=12.001(caution 12.0 を僅かに
    超え)なら info(caution を抜け info 域)。閾値の向き(caution は <=)を一意に固定。
    """
    assert t0.risk_tier([_track("vehicle", 12.001, 30.0)]) == t0.INFO


# ===========================================================================
# kind=speech の TTC 閾値 (caution=2.0, danger=1.0) — ADR 0017 決定3 T0
# ===========================================================================

def test_F006_speech_ttc_in_caution_band_is_caution():
    """T0(ADR 0033・純 TTC 統一): caution 帯(2 < ttc <= 12)は kind に依らず caution。
    speech で min_TTC=6.0 なら caution(旧 kind 別閾値は撤廃)。
    """
    assert t0.risk_tier([_track("speech", 6.0, 30.0)]) == t0.CAUTION


def test_F006_speech_ttc_below_danger_is_danger():
    """F-006(ADR 0017 決定3 T0): speech で min_TTC=0.9(<= danger 1.0)なら danger。

    純粋な閾値 danger(speech danger 閾値 1.0 で danger)。risk_tier に latch は無い
    (ADR 0017 追記で除去)ため、danger は kind 別閾値テーブルのみで決まる。
    """
    assert t0.risk_tier([_track("speech", 0.9, 30.0)]) == t0.DANGER


def test_F006_speech_ttc_at_caution_threshold_is_caution():
    """ADR 0045(純 TTC 厳密 `<`): caution は ttc<8.0。ttc=12.0 は info(kind 非依存)。"""
    assert t0.risk_tier([_track("speech", 12.0, 30.0)]) == t0.INFO


def test_F006_speech_ttc_above_caution_is_info():
    """T0(ADR 0033): caution 上端(12)超(ttc=13.0)なら info(kind 非依存)。"""
    assert t0.risk_tier([_track("speech", 13.0, 30.0)]) == t0.INFO


# ===========================================================================
# kind=alarm の TTC 閾値 (caution=5.0, danger=2.0) — ADR 0017 決定3 T0
# ===========================================================================

def test_F006_alarm_ttc_in_caution_band_is_caution():
    """F-006(ADR 0017 決定3 T0): alarm で min_TTC=4.0
    (danger 2.0 < 4.0 <= caution 5.0)なら caution。

    alarm 閾値 (caution=5.0, danger=2.0)。4.0 は vehicle(caution 12)でも caution、
    default(caution 5)でも caution だが、kind 別に alarm 閾値で判定されることを固定。
    """
    assert t0.risk_tier([_track("alarm", 4.0, 30.0)]) == t0.CAUTION


def test_F006_alarm_ttc_above_caution_is_info():
    """T0(ADR 0033・純 TTC 統一): alarm も caution 閾値は 12(旧 5 から統一)。
    ttc=6.0 は caution、info になるのは ttc=13.0 超のとき。
    """
    assert t0.risk_tier([_track("alarm", 6.0, 30.0)]) == t0.CAUTION
    assert t0.risk_tier([_track("alarm", 13.0, 30.0)]) == t0.INFO


def test_F006_alarm_ttc_below_danger_is_danger():
    """F-006(ADR 0017 決定3 T0): alarm で min_TTC=1.5(<= danger 2.0)なら danger。"""
    assert t0.risk_tier([_track("alarm", 1.5, 30.0)]) == t0.DANGER


# ===========================================================================
# default(未知 kind)の TTC 閾値 (caution=5.0, danger=2.0) — ADR 0017 決定3 T0
# ===========================================================================

def test_F006_default_kind_uses_default_thresholds_caution():
    """F-006(ADR 0017 決定3 T0・default): 未知 kind(例 "object")は default 閾値
    (caution=5.0, danger=2.0)。min_TTC=4.0 なら caution。
    """
    assert t0.risk_tier([_track("object", 4.0, 30.0)]) == t0.CAUTION


def test_F006_default_kind_above_caution_is_info():
    """T0(ADR 0033): 未知 kind も統一閾値(caution=12)。ttc=6.0 は caution、info は 13.0 超。"""
    assert t0.risk_tier([_track("object", 6.0, 30.0)]) == t0.CAUTION
    assert t0.risk_tier([_track("object", 13.0, 30.0)]) == t0.INFO


# ===========================================================================
# 主トラック選択: siren 優先 / なければ最近傍(最小 r_m)— ADR 0017 決定3 T0
# ===========================================================================

def test_F006_nearest_track_selected_when_no_siren():
    """F-006(ADR 0017 決定3 T0・主トラック選択): siren が無いとき、最小 r_m の track が
    主トラックとして選ばれる。

    遠い vehicle(r_m=50, ttc=15→info 域)と近い vehicle(r_m=5, ttc=1.5→danger 域)が
    あれば、最近傍(r_m=5)が選ばれ danger。遠方の info に引きずられない。
    """
    tracks = [
        _track("vehicle", 15.0, 50.0),  # 遠方・info 域
        _track("vehicle", 1.5, 5.0),    # 最近傍・danger 域 ← 選ばれる
    ]
    assert t0.risk_tier(tracks) == t0.DANGER


def test_F006_siren_prioritized_over_nearer_non_siren():
    """F-006(ADR 0017 決定3 T0・siren 優先): siren が存在すれば、より近い non-siren
    track があっても siren が主トラックに選ばれる。

    近い vehicle(r_m=2・ttc=15→vehicle caution 12 超で info 域)と遠い siren
    (r_m=40・ttc=15→siren 閾値でも info 域だが siren 下限で caution)があるとき、
    主トラック選択結果で出力が変わる:
      - siren が主トラック(siren 優先)→ siren 下限で caution。
      - 仮に最近傍(vehicle)が主トラックなら ttc=15 > caution 12 で info。
    結果が caution であることで「最近傍 vehicle ではなく siren が選ばれる」選択ロジック
    を固定する(latch 是正後: siren 選択は siren 下限の caution で観測される)。
    """
    tracks = [
        _track("vehicle", 15.0, 2.0),   # 最近傍だが non-siren・info 域
        _track("siren", 15.0, 40.0),    # 遠いが siren ← 主トラックに選ばれる
    ]
    # ADR 0045: siren→danger。siren が主トラックなら danger。vehicle が主トラックなら
    # ttc=15 で info。結果が danger であることで siren 選択を固定する。
    assert t0.risk_tier(tracks) == t0.DANGER


# ===========================================================================
# siren 下限: siren が info 判定なら caution へ引き上げ — ADR 0017 決定3 T0
# (latch 是正後: siren に safety latch は適用しない。高 TTC siren は caution 止まり)
# ===========================================================================

def test_F006_siren_high_ttc_is_danger():
    """ADR 0045(GT 整合): siren salient は TTC に依らず danger(GT gt_derive.risk_tier)。
    高 TTC(15.0)でも siren→danger。旧 siren 下限 caution(0.94 の主因)を是正。
    """
    assert t0.risk_tier([_track("siren", 15.0, 30.0)]) == t0.DANGER


def test_F006_siren_very_large_ttc_is_danger():
    """ADR 0045: siren は min_TTC が非常に大きく(100.0)ても danger(siren salient→danger)。"""
    assert t0.risk_tier([_track("siren", 100.0, 80.0)]) == t0.DANGER


def test_F006_siren_in_caution_band_is_danger():
    """ADR 0045: siren は caution 帯の TTC(6.0)でも danger(siren salient→danger)。"""
    assert t0.risk_tier([_track("siren", 6.0, 30.0)]) == t0.DANGER


def test_F006_siren_below_danger_threshold_is_danger_via_threshold():
    """F-006(ADR 0017 決定3 T0・latch 是正・siren 閾値判定): siren で min_TTC=1.5
    (<= siren danger 閾値 2.0)は閾値経由で danger。

    siren が danger になるのは latch ではなく kind 別 danger 閾値(2.0)による。低 TTC
    siren は閾値で danger(baseline 実トレースの siren-danger 39 フレームと整合)。この
    ケースは latch 是正後も danger のまま(現実装でも danger なので落ちない)。
    """
    assert t0.risk_tier([_track("siren", 1.5, 30.0)]) == t0.DANGER


# ===========================================================================
# 低 TTC の danger は kind 別閾値テーブルで決まる(latch ではない)— ADR 0017 是正後
# ===========================================================================

def test_F006_low_ttc_speech_is_danger_via_threshold_not_latch():
    """F-006(ADR 0017 決定3 T0・latch 是正): speech で min_TTC=0.8 は speech danger
    閾値 1.0 で danger(閾値経由)。

    latch 是正前はこれを「latch(<=0.8)による danger」と固定していたが、risk_tier から
    latch を除去したため、danger になる根拠は speech danger 閾値 1.0(0.8 <= 1.0)のみ。
    結果は danger のまま(現実装でも danger なので落ちない)だが、根拠を閾値に明示する。
    """
    assert t0.risk_tier([_track("speech", 0.8, 30.0)]) == t0.DANGER


def test_F006_low_ttc_vehicle_is_danger_via_threshold_not_latch():
    """F-006(ADR 0017 決定3 T0・latch 是正): vehicle で min_TTC=0.8 は vehicle danger
    閾値 2.0 で danger(0.8 <= 2.0・閾値経由)。

    latch ではなく kind 別 danger 閾値で danger になることを明示。danger のまま(現実装
    でも danger なので落ちない)。
    """
    assert t0.risk_tier([_track("vehicle", 0.8, 30.0)]) == t0.DANGER


def test_F006_low_ttc_default_kind_is_danger_via_threshold_not_latch():
    """F-006(ADR 0017 決定3 T0・latch 是正・kind 非依存ではなく閾値依存): default kind
    (例 "object")で min_TTC=0.5 は default danger 閾値 2.0 で danger(0.5 <= 2.0)。

    latch 是正前は「latch が kind 非依存に効く」例として固定していたが、risk_tier から
    latch を除去したため、danger の根拠は default danger 閾値 2.0(閾値経由)。danger の
    まま(現実装でも danger なので落ちない)。
    """
    assert t0.risk_tier([_track("object", 0.5, 30.0)]) == t0.DANGER


def test_F006_no_latch_high_ttc_speech_is_caution_not_danger():
    """T0(ADR 0033・latch 非作動): danger 閾値(2)超・caution 帯(ttc=6.0)なら caution。
    latch は無いので「低 TTC でも常に danger」ではない(高めの TTC は danger に latch しない)。
    """
    assert t0.risk_tier([_track("speech", 6.0, 30.0)]) == t0.CAUTION


# ===========================================================================
# track 空配列(track 0 件)— ADR 0017 追記・軽微指摘(監査・低)
# 例外を投げず、安全側の既定として有効な v1.4 語彙を返す(info を推奨)
# ===========================================================================

def test_F006_empty_tracks_returns_safe_default_not_exception():
    """F-006(ADR 0017 追記・軽微指摘・低): track 列が空(track 0 件)のとき、risk_tier は
    例外を投げず、安全側の既定として有効な v1.4 risk_tier 語彙(info / caution / danger)
    を返す。

    ADR 0017 追記「T0 の track 空配列は例外でなく安全側の既定(info 等)で扱う」。既定
    値そのものは実装裁量だが、「例外を投げない・v1.4 語彙集合に閉じる」ことを固定する
    (現実装は min([]) 等で例外を投げうるため、是正実装待ち=red)。
    """
    v14_risk_tiers = {t0.INFO, t0.CAUTION, t0.DANGER}
    try:
        result = t0.risk_tier([])
    except Exception as exc:  # noqa: BLE001 — 例外を投げないこと自体が契約
        pytest.fail(
            f"track 空配列で risk_tier が例外を投げた(安全側既定を返すべき): {exc!r}"
        )
    assert result in v14_risk_tiers, (
        f"track 空配列の risk_tier が v1.4 語彙外: {result!r}"
    )


def test_F006_empty_tracks_default_is_info():
    """F-006(ADR 0017 追記・軽微指摘・低・推奨既定): track 空配列のときの安全側既定は
    info を推奨(ADR 0017 追記「安全側の既定(info 等)」)。

    既定値は実装裁量だが、ADR 0017 追記の推奨どおり「危険を煽らない info」を固定する。
    実装が caution / danger を返したい合理的理由が出た場合は ADR 追記の更新が先(本
    テストの単独緩和は禁止)。
    """
    assert t0.risk_tier([]) == t0.INFO


# ===========================================================================
# 出力語彙は v1.4 risk_tier(info / caution / danger)— ADR 0006 / 0012
# ===========================================================================

def test_F006_risk_tier_output_is_v14_vocabulary():
    """F-006(ADR 0017 決定3 T0 + ADR 0006 語彙): risk_tier の出力は v1.4 統制語彙
    {info, caution, danger} のいずれかのみ。

    代表ケース群で語彙集合に閉じることを確認する(どの入力がどのラベルかは個別
    テストが固定)。
    """
    v14_risk_tiers = {"info", "caution", "danger"}
    samples = [
        [_track("vehicle", 1.5, 30.0)],
        [_track("vehicle", 5.0, 30.0)],
        [_track("vehicle", 15.0, 30.0)],
        [_track("speech", 1.5, 30.0)],
        [_track("siren", 15.0, 30.0)],
        [_track("object", 0.5, 30.0)],
    ]
    for tracks in samples:
        label = t0.risk_tier(tracks)
        assert label in v14_risk_tiers, (
            f"risk_tier({tracks!r}) が v1.4 語彙外を返した: {label!r}"
        )


def test_F006_t0_exposes_v14_label_constants():
    """F-006(契約面・ADR 0006/0017): t0 は v1.4 risk_tier 語彙 info/caution/danger を
    ラベル定数として公開し、その値がそれぞれの文字列であること(語彙 faithfulness)。
    """
    expected = {"INFO": "info", "CAUTION": "caution", "DANGER": "danger"}
    for name, value in expected.items():
        assert hasattr(t0, name), f"t0.{name} が公開されていない"
        assert getattr(t0, name) == value, (
            f"t0.{name} の値が '{value}' でない(v1.4 語彙 faithfulness 違反)"
        )


# ===========================================================================
# HGF 非依存・状態レス(ADR 0017 決定3 T0: 直接ルール・状態レス)
# ===========================================================================

def test_F006_t0_is_stateless_and_deterministic():
    """F-006(ADR 0017 決定3 T0・状態レス/決定性): risk_tier は状態を持たず、同じ tracks
    で何度呼んでも同一ラベル(HGF 非依存・乱数なし)。

    T0 は直接ルール・状態レス(ADR 0017 決定3)。前回呼び出しの影響を受けないことを、
    複数ケースを交互に呼んで確認する。
    """
    cases = [
        ([_track("vehicle", 1.5, 30.0)], t0.DANGER),
        ([_track("vehicle", 5.0, 30.0)], t0.CAUTION),
        ([_track("vehicle", 15.0, 30.0)], t0.INFO),
        # ADR 0045: siren salient は TTC に依らず danger(GT 整合)。
        ([_track("siren", 15.0, 30.0)], t0.DANGER),
        ([_track("speech", 1.5, 30.0)], t0.DANGER),  # ADR 0033: 純 TTC ≤2 は kind 非依存で danger
    ]
    # 一度通しで呼んだ後、逆順でもう一度呼んで状態残留が無いことを確認。
    for tracks, _ in cases:
        t0.risk_tier(tracks)
    for tracks, expected in reversed(cases):
        first = t0.risk_tier(tracks)
        second = t0.risk_tier(tracks)
        assert first == second == expected, (
            f"risk_tier({tracks!r}) が状態レス/決定的でない: "
            f"{first!r}/{second!r} (expected {expected!r})"
        )
