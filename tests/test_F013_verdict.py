"""F-013-2: 項目別 verdict（compare_items）— 弱い項目 win/lose/draw の境界、
強い項目 maintained/degraded の境界、no_data 層の勝敗除外、成功目標フラグは合否を強制しない。

specs/SPEC.md F-013-2:
  「項目別対比（弱い5項目の勝敗・引き分け、強い項目の δ_strong 内維持判定）が…報告される。
   差が δ_strong（U5b）以内は引き分けとして報告する。『弱い5項目↑ ∧ 強い項目維持』自体は
   合否ゲートでなく成功目標。」
specs/SPEC.md 非機能要件:
  「勝敗判定は項目別。強い項目を下げて弱い項目を上げる平均的ごまかしを禁止（平均判定却下）。」
decisions/0023-f013-sealed-evaluation-design.md 決定5:
  弱い項目: supreme-baseline > δ → win ／ baseline-supreme > δ → lose ／ |Δ| ≤ δ → draw。
  強い項目: baseline-supreme > δ → degraded ／ それ以外 → maintained。
  「弱い5↑ ∧ 強い維持」は成功目標フラグとして report に載せるのみ。合否ゲートにしない。
decisions/0023 決定4:
  封印に当該層データが無い項目は no_data として勝敗から除外（draw 扱いにしない）。
具体値: δ_strong = U5b 暫定 0.02（fixtures_sealeval.DELTA_STRONG）。

----------------------------------------------------------------------------
このファイルが定義する supreme.sealeval.compare_items の前提 API（テスト駆動・report 明記）:

  sealeval.compare_items(supreme, baseline, *, delta_strong, weak_items, strong_items)
      -> ItemComparisonReport
    supreme / baseline は ScoreResult 互換（.layer_score(layer) -> float|None・.layers）。
    層 acc の差で項目別 verdict を決める。返り値 ItemComparisonReport の面:
      .verdict(item) -> str       "win"|"lose"|"draw"（弱）／"maintained"|"degraded"（強）
                                  ／"no_data"（封印に当該層データ無し＝勝敗除外）
      .verdicts -> dict[str,str]  item -> verdict（報告用）
      .weak_items / .strong_items -> tuple[str]   入力をそのまま保持
      .success_goal -> bool       「弱い全 win ∧ 強い全 maintained ∧ no_data 無し」の成功目標フラグ
      .no_data_items -> tuple[str]  no_data として勝敗から除外された項目

  verdict 規約:
    Δ = supreme.layer_score(item) - baseline.layer_score(item)
    弱い: Δ > δ → win ／ Δ < -δ → lose ／ |Δ| ≤ δ → draw（境界 |Δ|==δ は draw）
    強い: Δ < -δ → degraded ／ それ以外（Δ ≥ -δ）→ maintained
    どちらかの層スコアが None（封印に当該層データ無し）→ no_data（draw にしない）

  成功目標フラグは report に**載せるだけ**。compare_items は pass/fail を assert で
  強制しない（合否ゲートでない・SPEC 非機能要件）。本ファイルも verdict と success_goal の
  **値**のみを検証し、compare_items 自体が例外/失敗で合否を強制しないことを固定する。

注意（規律）: stdlib のみ・決定的。supreme/baseline は層 acc を直接持つ軽量
スタブ（封印を開けない＝ダミー verdict 検証・TEST_STRATEGY 穴2）。
"""

import pytest

import fixtures_sealeval as fxs


def _import_sealeval():
    from supreme import sealeval

    return sealeval


# ---------------------------------------------------------------------------
# 層 acc を直接持つ軽量スコアスタブ（ScoreResult 互換の最小面）
#   verdict ロジックは層 acc の差だけで決まる。封印を開けず compare_items を検証するため、
#   supreme/baseline 双方をこのスタブで与える（TEST_STRATEGY「勝敗ロジックはダミーで検証」）。
#   layer_score(layer) は値が無い層に対し None を返す（封印に当該層データ無し＝no_data 素材）。
# ---------------------------------------------------------------------------

class _ScoreStub:
    def __init__(self, layer_accs):
        self._accs = dict(layer_accs)

    @property
    def layers(self):
        return tuple(self._accs.keys())

    def layer_score(self, layer):
        return self._accs.get(layer, None)

    def overall(self):
        vals = [v for v in self._accs.values() if v is not None]
        return sum(vals) / len(vals) if vals else None


def _compare(supreme_accs, baseline_accs):
    """compare_items を δ_strong=0.02・canonical 弱/強項目で呼ぶ薄いラッパ。"""
    sealeval = _import_sealeval()
    return sealeval.compare_items(
        _ScoreStub(supreme_accs),
        _ScoreStub(baseline_accs),
        delta_strong=fxs.DELTA_STRONG,
        weak_items=fxs.WEAK_ITEMS,
        strong_items=fxs.STRONG_ITEMS,
    )


# ===========================================================================
# 弱い項目: win / lose / draw（draw の境界 = δ ちょうど）
# ===========================================================================

def test_F013_2_weak_win_when_supreme_exceeds_by_more_than_delta():
    """F-013-2（弱・win）: 弱い項目で supreme-baseline > δ なら win。

    Δ=0.10 > 0.02 → win。
    """
    item = "t2_mode"
    rep = _compare({item: 0.70}, {item: 0.60})
    assert rep.verdict(item) == "win", f"{item} が win でない: {rep.verdict(item)}"


def test_F013_2_weak_lose_when_baseline_exceeds_by_more_than_delta():
    """F-013-2（弱・lose）: 弱い項目で baseline-supreme > δ なら lose。

    Δ=-0.10 < -0.02 → lose。
    """
    item = "t2_relation"
    rep = _compare({item: 0.50}, {item: 0.60})
    assert rep.verdict(item) == "lose", f"{item} が lose でない: {rep.verdict(item)}"


def test_F013_2_weak_draw_when_abs_delta_within_delta_strong():
    """F-013-2（弱・draw）: |Δ| < δ なら draw（引き分け）。

    Δ=0.01（< 0.02）→ draw。「差が δ_strong 以内は引き分け」（SPEC）。
    """
    item = "t3_hypothesis"
    rep = _compare({item: 0.61}, {item: 0.60})
    assert rep.verdict(item) == "draw", f"{item} が draw でない: {rep.verdict(item)}"


def test_F013_2_weak_draw_boundary_exact_delta_positive():
    """F-013-2（弱・draw 境界・上端）: Δ == +δ ちょうどは draw（win でない）。

    決定5: |Δ| ≤ δ_strong → draw。境界（ちょうど）を draw 側に固定する（厳密 > のみ win）。
    Δ = 0.62-0.60 = 0.02 == δ → draw。
    """
    item = "scene_regime"
    rep = _compare({item: 0.62}, {item: 0.60})
    assert rep.verdict(item) == "draw", (
        f"Δ==δ ちょうどが draw でない（win に倒れている疑い）: {rep.verdict(item)}"
    )


def test_F013_2_weak_draw_boundary_exact_delta_negative():
    """F-013-2（弱・draw 境界・下端）: Δ == -δ ちょうどは draw（lose でない）。

    Δ = 0.58-0.60 = -0.02 == -δ → draw（|Δ| ≤ δ）。境界を draw 側に固定。
    """
    item = "quality_regime"
    rep = _compare({item: 0.58}, {item: 0.60})
    assert rep.verdict(item) == "draw", (
        f"Δ==-δ ちょうどが draw でない（lose に倒れている疑い）: {rep.verdict(item)}"
    )


def test_F013_2_weak_win_just_above_delta_boundary():
    """F-013-2（弱・win 境界の外側）: Δ が δ を僅かに超える（厳密 >）と win。

    Δ = 0.621-0.60 = 0.021 > 0.02 → win。draw と win の境界が厳密 > であることを固定。
    """
    item = "t2_mode"
    rep = _compare({item: 0.621}, {item: 0.60})
    assert rep.verdict(item) == "win", (
        f"δ を超える Δ が win でない（境界が閉じている疑い）: {rep.verdict(item)}"
    )


# ===========================================================================
# 強い項目: maintained / degraded（degraded の境界 = δ ちょうどは維持）
# ===========================================================================

def test_F013_2_strong_maintained_when_within_delta():
    """F-013-2（強・maintained）: 強い項目で低下が δ 以内なら維持（maintained）。

    Δ = -0.01（baseline-supreme=0.01 < δ）→ maintained。
    """
    item = "risk_tier"
    rep = _compare({item: 0.84}, {item: 0.85})
    assert rep.verdict(item) == "maintained", \
        f"{item} が maintained でない: {rep.verdict(item)}"


def test_F013_2_strong_maintained_when_supreme_higher():
    """F-013-2（強・maintained・改善側）: supreme が baseline を上回る強い項目も維持扱い。

    Δ = +0.05 → 低下なし → maintained（degraded は低下のみ）。
    """
    item = "t1_state"
    rep = _compare({item: 0.90}, {item: 0.85})
    assert rep.verdict(item) == "maintained", \
        f"{item} が maintained でない: {rep.verdict(item)}"


def test_F013_2_strong_degraded_when_drop_exceeds_delta():
    """F-013-2（強・degraded）: 強い項目で baseline-supreme > δ なら degraded（低下）。

    Δ = -0.10 < -δ → degraded。
    """
    item = "t2_role"
    rep = _compare({item: 0.75}, {item: 0.85})
    assert rep.verdict(item) == "degraded", \
        f"{item} が degraded でない: {rep.verdict(item)}"


def test_F013_2_strong_maintained_boundary_exact_delta_drop():
    """F-013-2（強・degraded 境界）: 低下が δ ちょうど（== δ）は maintained（degraded でない）。

    決定5: baseline-supreme > δ で degraded（厳密 >）。Δ = 0.83-0.85 = -0.02 == -δ →
    低下が δ ちょうど → maintained 側に固定（強い項目は δ_strong 内維持・SPEC F-013-2）。
    """
    item = "risk_tier"
    rep = _compare({item: 0.83}, {item: 0.85})
    assert rep.verdict(item) == "maintained", (
        f"低下 δ ちょうどが degraded に倒れている（境界が閉じている疑い）: {rep.verdict(item)}"
    )


def test_F013_2_strong_degraded_just_beyond_delta():
    """F-013-2（強・degraded 境界の外側）: 低下が δ を僅かに超えると degraded。

    Δ = 0.829-0.85 = -0.021 < -0.02 → degraded。境界が厳密 > であることを固定。
    """
    item = "t2_role"
    rep = _compare({item: 0.829}, {item: 0.85})
    assert rep.verdict(item) == "degraded", (
        f"δ を超える低下が degraded でない（境界が開いている疑い）: {rep.verdict(item)}"
    )


# ===========================================================================
# no_data: 封印に当該層データが無い項目は勝敗から除外（draw にしない）
# ===========================================================================

def test_F013_2_no_data_when_supreme_layer_absent():
    """F-013-2（ADR 0023 決定4・no_data）: supreme 側に当該層データが無い項目は no_data。

    layer_score が None（封印に当該層データ無し）→ no_data。draw（引き分け）にしない。
    """
    item = "scene_regime"
    rep = _compare({item: None}, {item: 0.60})
    assert rep.verdict(item) == "no_data", \
        f"{item} が no_data でない（draw に倒れている疑い）: {rep.verdict(item)}"


def test_F013_2_no_data_when_baseline_layer_absent():
    """F-013-2（no_data・baseline 側欠落）: baseline 側に当該層データが無くても no_data。"""
    item = "scene_regime"
    rep = _compare({item: 0.60}, {item: None})
    assert rep.verdict(item) == "no_data", \
        f"{item} が no_data でない: {rep.verdict(item)}"


def test_F013_2_no_data_excluded_from_win_lose_draw():
    """F-013-2（no_data 除外）: no_data 項目は勝敗（win/lose/draw）に数えない。

    no_data_items に列挙され、verdicts では "no_data" として区別される。
    draw（=測れたが互角）と no_data（=そもそも測れない）を混同しないことを固定する。
    """
    accs_s = {"t2_mode": 0.70, "scene_regime": None}
    accs_b = {"t2_mode": 0.60, "scene_regime": 0.60}
    rep = _compare(accs_s, accs_b)
    assert "scene_regime" in rep.no_data_items
    assert rep.verdict("scene_regime") == "no_data"
    assert rep.verdict("scene_regime") != "draw", "no_data を draw に混同している"
    # 測れた項目は通常どおり勝敗が付く。
    assert rep.verdict("t2_mode") == "win"


# ===========================================================================
# 成功目標フラグ: report に載せるだけ・合否を強制しない
# ===========================================================================

def _all_items_accs(supreme_map, baseline_map):
    """弱5+強3 の全項目に値を与えた acc dict を作る（成功目標フラグ検証用）。"""
    s = {it: supreme_map.get(it, 0.60) for it in fxs.WEAK_ITEMS + fxs.STRONG_ITEMS}
    b = {it: baseline_map.get(it, 0.60) for it in fxs.WEAK_ITEMS + fxs.STRONG_ITEMS}
    return s, b


def test_F013_2_success_goal_flag_true_when_all_weak_win_and_strong_maintained():
    """F-013-2（成功目標フラグ・真）: 弱い全 win ∧ 強い全 maintained ∧ no_data 無し →
    success_goal=True。

    成功目標（SPEC 非機能要件）が満たされた構成でフラグが立つことを固定する。
    """
    # 弱は全て +0.10（win）、強は全て同値（maintained）。
    s, b = _all_items_accs(
        {it: 0.70 for it in fxs.WEAK_ITEMS},
        {it: 0.60 for it in fxs.WEAK_ITEMS},
    )
    rep = _import_sealeval().compare_items(
        _ScoreStub(s), _ScoreStub(b),
        delta_strong=fxs.DELTA_STRONG,
        weak_items=fxs.WEAK_ITEMS, strong_items=fxs.STRONG_ITEMS,
    )
    assert rep.success_goal is True


def test_F013_2_success_goal_flag_false_when_a_weak_item_loses():
    """F-013-2（成功目標フラグ・偽）: 弱い項目に1つでも lose があれば success_goal=False。

    ただし compare_items は**例外/失敗で合否を強制しない**（フラグを下げるだけ）。
    """
    s, b = _all_items_accs(
        {**{it: 0.70 for it in fxs.WEAK_ITEMS}, "t2_relation": 0.40},  # relation は lose
        {it: 0.60 for it in fxs.WEAK_ITEMS},
    )
    rep = _import_sealeval().compare_items(
        _ScoreStub(s), _ScoreStub(b),
        delta_strong=fxs.DELTA_STRONG,
        weak_items=fxs.WEAK_ITEMS, strong_items=fxs.STRONG_ITEMS,
    )
    assert rep.verdict("t2_relation") == "lose"
    assert rep.success_goal is False


def test_F013_2_success_goal_false_when_strong_degraded():
    """F-013-2（成功目標フラグ・偽・強劣化）: 強い項目が degraded なら success_goal=False。

    平均的ごまかし（弱を上げ強を下げる）を成功目標として認めない（SPEC 非機能・平均判定却下）。
    """
    s, b = _all_items_accs(
        {it: 0.70 for it in fxs.WEAK_ITEMS},          # 弱は全 win
        {it: 0.60 for it in fxs.WEAK_ITEMS},
    )
    s["risk_tier"] = 0.70   # 強 risk_tier を baseline より大きく下げる
    b["risk_tier"] = 0.85   # Δ=-0.15 → degraded
    rep = _import_sealeval().compare_items(
        _ScoreStub(s), _ScoreStub(b),
        delta_strong=fxs.DELTA_STRONG,
        weak_items=fxs.WEAK_ITEMS, strong_items=fxs.STRONG_ITEMS,
    )
    assert rep.verdict("risk_tier") == "degraded"
    assert rep.success_goal is False


def test_F013_2_compare_items_does_not_raise_on_unmet_goal():
    """F-013-2（合否ゲートでない・核心）: 成功目標を満たさなくても compare_items は
    例外を出さず（pass/fail を assert で強制せず）、verdict と success_goal=False を返す。

    SPEC: 「弱い5項目↑ ∧ 強い項目維持」は合否ゲートでなく成功目標。compare_items が
    未達構成で raise すると合否ゲート化してしまう。raise しないことを固定する。
    """
    sealeval = _import_sealeval()
    s, b = _all_items_accs(
        {it: 0.40 for it in fxs.WEAK_ITEMS},   # 弱は全 lose（最悪構成）
        {it: 0.80 for it in fxs.WEAK_ITEMS},
    )
    # 例外なく report が返る（合否を強制しない）。
    rep = sealeval.compare_items(
        _ScoreStub(s), _ScoreStub(b),
        delta_strong=fxs.DELTA_STRONG,
        weak_items=fxs.WEAK_ITEMS, strong_items=fxs.STRONG_ITEMS,
    )
    assert rep.success_goal is False
    # 報告面（verdicts）が全項目を含む（測定・報告がされている）。
    for it in fxs.WEAK_ITEMS + fxs.STRONG_ITEMS:
        assert it in rep.verdicts


def test_F013_2_verdicts_cover_all_weak_and_strong_items():
    """F-013-2（報告の網羅）: verdicts は弱い5項目＋強い3項目すべてを項目別に報告する。

    平均でなく項目別（SPEC 非機能要件）。全 8 項目が verdicts に現れることを固定する。
    """
    s, b = _all_items_accs({}, {})
    rep = _import_sealeval().compare_items(
        _ScoreStub(s), _ScoreStub(b),
        delta_strong=fxs.DELTA_STRONG,
        weak_items=fxs.WEAK_ITEMS, strong_items=fxs.STRONG_ITEMS,
    )
    assert set(rep.verdicts.keys()) == set(fxs.WEAK_ITEMS + fxs.STRONG_ITEMS), (
        "verdicts が弱5+強3 の全項目を項目別に報告していない"
    )
