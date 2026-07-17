"""F-基盤-001-1(ADR 0022)— end-to-end 組み立て(結線): 合成 PSO-Snapshot 系列を
run_supreme に流すと、各フレームに 8層すべての view が揃う(長さ=入力長・各層 v1.4 語彙)。

本ファイルは「結線の骨格」(8層が揃う・長さ整合・harness.score に渡せる形)を契約化する。
各層の代表ケース値(siren→caution 等)の固定は test_Fbase001_wiring.py、語彙閉包は
test_Fbase001_vocab.py、決定性は test_Fbase001_determinism.py で扱う。

契約の最終根拠:
  - decisions/0022-fbase001-supreme-runner.md(手法の正・scope・受け入れ条件):
      目的 = run_supreme(PSO入力系列) → trace(各フレーム 8層 view)。
      決定1: 出力は 8層 view に絞る(契約フル emit は別課題)。
      決定2: T3 reset 発火源 = シナリオ境界(シナリオ先頭で reset=True を T3 へ注入)。
      決定3: quality h_q/vol・anomaly pw_anom は baseline 観測式 + 共有 HGF で再実装。
      F-基盤-001-1: PSO Snapshot 系列から end-to-end で 8層 view trace を生成し、
                    全モジュール結線・状態持ち越し・T3 シナリオ境界 reset・harness.score 互換。
  - specs/SPEC.md F-基盤-001(行 210-224)/ decisions/0006(Snapshot のみ・v1.4 語彙)/
    PSO 入力契約 v1.4(tracks/links/geom/scene_state の形状)。

スコープ外(ADR 0022・推測でテスト化しない):
  - 各モジュールの内部ロジック網羅(F-006〜012 で済み)。本ファイルは結線・組み立て。
  - 契約フル emit・Delta 対応・multi-thread・実際の精度/改善(F-013 の成功目標)。

本ファイルが前提とする supreme.core の公開 API(設計裁量・ADR 0022 で API 名は委任):
  core.run_supreme(pso_snapshots, config=None) -> list[frame_view]
      pso_snapshots = PSO-Snapshot(world_state dict)の系列。Snapshot のみ。
      config        = 探索構成(改良モジュール ON/OFF + ハイパラ・省略時は既定=全 ON)。
      返り値        = 各フレームの 8層 view dict の列(長さ=入力長)。
  core.run_supreme_scenarios(scenarios, config=None) -> dict[scenario_id, list[frame_view]]
      シナリオ単位の入力({scenario_id: pso_snapshots})を受け、各シナリオ先頭フレームで
      T3 を reset(ADR 0022 決定2: シナリオ境界 reset)した上で各シナリオの 8層 view 列を返す。
  core.VIEW_LAYERS -> 8層キーの集合/列(risk_tier/t1_state/t2_mode/t2_role/t2_relation/
      t3_hypothesis/quality_regime/scene_regime)。

ADR 0022 / PSO 契約から一意に決まらない点(性質契約に留めた・推測でテスト化しない):
  - run_supreme の正確な signature(scenario 単位 か frame 列単位 か)は ADR 0022 が
    「(または scenario 単位)」と委任。本ファイルは frame 列の run_supreme と scenario 単位の
    run_supreme_scenarios の両方を「8層が揃う・長さ整合」の性質で固定し、内部呼び出し形態には
    踏み込まない。scenario 境界 reset の固定は test_Fbase001_wiring.py。
  - config の正確な構造(キー名・ハイパラ)は ADR 0022/0021 が探索軸(mode/relation/quality/
    scene/t3 の ON/OFF + 離散ハイパラ)を示すが具体キーを一意に与えない。本ファイルは
    「config 省略時 = 既定で 8層 view が揃う」ことのみを固定し、config の中身は触れない。
  - 各層の具体ラベル値(どの入力でどのラベルか)は ADR 0022 が代表ケースのみ示し閾値は上流裁量。
    本ファイルは「8層が揃う・v1.4 語彙集合に閉じる・長さ整合」の性質に留める(値固定は wiring)。
"""

import pytest

import fixtures_pso as fxp


# F-基盤-001 が組み立てる 8層 view のキー(SPEC.md 行 220 / ADR 0022 目的)。
EIGHT_LAYERS = {
    "risk_tier",
    "t1_state",
    "t2_mode",
    "t2_role",
    "t2_relation",
    "t3_hypothesis",
    "quality_regime",
    "scene_regime",
}


def _import_core():
    """supreme.core を import して返す(実装不在なら ImportError で失敗=TDD 期待)。"""
    from supreme import core

    return core


def _benign_sequence(n):
    """良性フレーム n 個の Snapshot 系列(ts は 0,1,2,... で単調増加)。"""
    return [fxp.frame_benign(ts=float(i)) for i in range(n)]


# ===========================================================================
# 公開シンボルの存在(統合ランナーの入口)
# ===========================================================================

def test_Fbase001_1_core_exposes_run_supreme():
    """F-基盤-001-1(契約面・ADR 0022 目的): supreme.core は統合ランナー run_supreme() を
    公開する。

    run_supreme(pso_snapshots, config=None) -> list[frame_view]。PSO Snapshot 系列を
    8層 view trace に組み立てる入口(epiin/epiout stage の実装)。
    """
    core = _import_core()
    assert hasattr(core, "run_supreme"), "core.run_supreme が公開されていない"
    assert callable(core.run_supreme)


# ===========================================================================
# 8層が揃う(各フレームに 8層すべての view が存在する)
# ===========================================================================

def test_Fbase001_1_each_frame_has_all_eight_layers():
    """F-基盤-001-1(ADR 0022・結線): run_supreme の各フレーム view に 8層すべてのキーが
    揃う(過不足なく risk_tier/t1_state/t2_mode/t2_role/t2_relation/t3_hypothesis/
    quality_regime/scene_regime)。

    8層が揃うこと=epiout(8層 view)stage が組み上がっていること。1層でも欠けると F-013 の
    8層採点が成立しない。
    """
    core = _import_core()
    views = core.run_supreme(_benign_sequence(3))
    for i, view in enumerate(views):
        keys = set(view.keys())
        assert EIGHT_LAYERS.issubset(keys), (
            f"frame {i} の view に欠けている層がある: 欠落={EIGHT_LAYERS - keys!r}"
        )


def test_Fbase001_1_view_has_no_extra_unspecified_layers():
    """F-基盤-001-1(ADR 0022 決定1・8層に絞る): view のキーは 8層に閉じる(契約フル emit の
    EPI-T0..T3/CTRL/NOVEL 等の余分なキーを混ぜない)。

    ADR 0022 決定1「出力は 8層 view に絞る」。view が 8層ちょうどであることで、契約フル emit を
    本機能に混ぜていない(別課題に申し送り)ことを固定する。
    """
    core = _import_core()
    views = core.run_supreme(_benign_sequence(2))
    for i, view in enumerate(views):
        keys = set(view.keys())
        assert keys == EIGHT_LAYERS, (
            f"frame {i} の view が 8層ちょうどでない: 余分={keys - EIGHT_LAYERS!r} "
            f"欠落={EIGHT_LAYERS - keys!r}"
        )


def test_Fbase001_1_each_layer_value_is_string_label():
    """F-基盤-001-1(ADR 0022・結線): 8層 view の各値は分類ラベル文字列(argmax 済み)。

    ADR 0022 構成要素6「8層 view 組み立て(argmax 含む)」。各層が確率分布や None でなく
    1つの v1.4 語彙ラベル文字列に確定していること(harness の完全一致採点に渡せる形)。
    """
    core = _import_core()
    views = core.run_supreme(_benign_sequence(2))
    for i, view in enumerate(views):
        for layer in EIGHT_LAYERS:
            assert isinstance(view[layer], str) and view[layer] != "", (
                f"frame {i} の層 {layer} が非空文字列ラベルでない: {view[layer]!r}"
            )


# ===========================================================================
# 長さ = 入力長(各フレームに 1 view)
# ===========================================================================

def test_Fbase001_1_output_length_matches_input_length():
    """F-基盤-001-1(ADR 0022・結線): run_supreme の出力 view 列の長さが入力 Snapshot 列長と
    一致する(各フレームに 1 つの 8層 view)。
    """
    core = _import_core()
    for n in [1, 3, 5]:
        views = core.run_supreme(_benign_sequence(n))
        assert len(list(views)) == n, (
            f"入力 {n} フレームに対し出力 view 数が {len(list(views))}(長さ不整合)"
        )


def test_Fbase001_1_empty_sequence_returns_empty():
    """F-基盤-001-1(ADR 0022・境界): 空の Snapshot 系列は空の view 列を返す(例外でない)。

    長さ整合の境界(入力 0 → 出力 0)。空入力で落ちないことを固定する。
    """
    core = _import_core()
    views = core.run_supreme([])
    assert list(views) == [], "空入力に対し空の view 列を返さない"


# ===========================================================================
# config 省略時 = 既定(全 ON)で 8層が揃う(ADR 0022: config 省略時は既定=全 ON)
# ===========================================================================

def test_Fbase001_1_config_none_defaults_to_all_modules_on():
    """F-基盤-001-1(ADR 0022・config 既定): config を省略(None)しても、既定構成(全モジュール
    ON)で 8層 view が揃う。

    ADR 0022「config 省略時は既定=全 ON」。探索構成を与えなくても end-to-end が成立する
    (F-013 の既定実走・F-012 の基準構成の土台)。
    """
    core = _import_core()
    views_default = core.run_supreme(_benign_sequence(2))
    views_explicit_none = core.run_supreme(_benign_sequence(2), config=None)
    for views in (views_default, views_explicit_none):
        for view in views:
            assert EIGHT_LAYERS.issubset(set(view.keys()))


# ===========================================================================
# scenario 単位 API(シナリオ境界 reset の土台): 各シナリオの 8層 view が揃う
# ===========================================================================

def test_Fbase001_1_scenario_runner_returns_views_per_scenario():
    """F-基盤-001-1(ADR 0022 決定2・scenario 単位): run_supreme_scenarios はシナリオごとに
    8層 view 列を返し、各シナリオの長さが入力シナリオ長と一致する。

    ADR 0022 決定2「T3 reset 発火源 = シナリオ境界」のため、シナリオ単位の入口が要る。
    reset 注入そのものの効果は test_Fbase001_wiring.py で固定し、ここでは「シナリオ単位で
    8層が揃う・長さ整合」の組み立てのみを固定する。
    """
    core = _import_core()
    if not hasattr(core, "run_supreme_scenarios"):
        pytest.skip("scenario 単位 API は run_supreme(...) 一本に集約された実装(裁量・ADR 0022)")
    scenarios = {
        "sc1": _benign_sequence(3),
        "sc2": _benign_sequence(2),
    }
    out = core.run_supreme_scenarios(scenarios)
    assert set(out.keys()) == {"sc1", "sc2"}, "シナリオキーが入出力で一致しない"
    assert len(list(out["sc1"])) == 3
    assert len(list(out["sc2"])) == 2
    for views in out.values():
        for view in views:
            assert EIGHT_LAYERS.issubset(set(view.keys())), (
                "scenario 単位 view にも 8層が揃うべき"
            )
