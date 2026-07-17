"""F-基盤-001-3(ADR 0022)— Snapshot 規律: Snapshot のみ受理・Delta は明示エラー・
ts 単調非減少違反は拒否・任意フィールド欠落は縮退。

契約の最終根拠:
  - decisions/0022-fbase001-supreme-runner.md:
      確定事項「Snapshot のみ受理・Delta/fields_ref は明示エラー(ADR 0006 決定3)。
      任意フィールド欠落は縮退。ts 単調非減少検証。」
      異常系: Delta/fields_ref は明示エラー・任意フィールド欠落は縮退・ts 単調非減少違反は拒否。
      F-基盤-001-3: Snapshot のみ受理・Delta は明示エラー・任意フィールド欠落は縮退・
                    ts 単調非減少検証。
  - decisions/0006-v14-vocabulary-migration-u7.md(決定3): Snapshot のみ・Delta/fields_ref は
    当面非対応(明示エラー)。実装が前提にしてよい不変条件: ts 単調非減少。任意フィールド
    (geom/scene_state 等)は欠落時縮退。
  - PSO 入力契約 v1.4 §4 運用ルール「ts は単調非減少」/ §1.2 PSO-Delta/1.4(version 識別子)。
  - specs/SPEC.md F-基盤-001-3(行 222)。

スコープ外(ADR 0022・推測でテスト化しない):
  - ts 単調非減少違反の処理が「エラー」か「スキップ」かは ADR 0022 が『拒否(エラー or
    スキップを明示固定)』と委任。本ファイルは **エラー(例外)で拒否** を既定として固定する
    (F-004 の『欠落・不整合は止める』精神・黙って通さない)。実装が『スキップ』を選ぶ合理的
    理由があれば ADR 追記が先(本テストの単独緩和は禁止)。
  - 縮退時の具体的な既定値(欠落 geom のときの risk_tier 等)は上流の証拠抽出裁量。本ファイルは
    「欠落しても例外を投げず 8層 view が揃う」ことのみを固定し、具体ラベル値には踏み込まない。

本ファイルが前提とする supreme.core の公開 API:
  core.run_supreme(pso_snapshots, config=None) -> list[frame_view]
"""

import pytest

import fixtures_pso as fxp


EIGHT_LAYERS = {
    "risk_tier", "t1_state", "t2_mode", "t2_role", "t2_relation",
    "t3_hypothesis", "quality_regime", "scene_regime",
}


def _import_core():
    from supreme import core

    return core


# ===========================================================================
# Delta レコードを渡すと明示エラー(ADR 0006・非対応)
# ===========================================================================

def test_Fbase001_3_delta_record_raises_explicit_error():
    """F-基盤-001-3(ADR 0022/0006・Delta 非対応): version が PSO-Delta のレコードを渡すと
    明示的に例外で拒否する(黙って Snapshot 扱いしない)。

    ADR 0006 決定3「Delta/fields_ref は当面非対応(明示エラー)」。Delta を黙殺・誤適用すると
    状態が壊れるため、明示エラーで止める(F-004 異常系の精神)。
    """
    core = _import_core()
    delta = {
        "version": fxp.DELTA_VERSION_14,
        "ts": 0.1,
        "tracks_update": {"upsert": {"audio": [], "humans": [], "objects": []},
                          "delete": {"audio": [], "humans": [], "objects": []}},
    }
    with pytest.raises(Exception):
        core.run_supreme([delta])


def test_Fbase001_3_delta_mixed_in_snapshot_sequence_raises():
    """F-基盤-001-3(ADR 0022/0006・Delta 非対応・混在): Snapshot 系列の途中に Delta が
    混ざっても明示エラーで拒否する(系列の一部 Delta を黙って通さない)。
    """
    core = _import_core()
    seq = [
        fxp.frame_benign(ts=0.0),
        {"version": fxp.DELTA_VERSION_14, "ts": 1.0,
         "scene_state_update": {"QoS": 0.5}},
        fxp.frame_benign(ts=2.0),
    ]
    with pytest.raises(Exception):
        core.run_supreme(seq)


def test_Fbase001_3_snapshot_versions_13_and_14_both_accepted():
    """F-基盤-001-3(ADR 0006・version 両受理): PSO-Snapshot/1.3 と /1.4 は両方受理される
    (構造同一・version 文字列のみの差)。

    ADR 0006「supreme は version 1.3/1.4 を両受理(構造同一)」。Snapshot であれば 1.3/1.4 とも
    8層 view を生成できることを固定する(Delta だけが非対応・version で Snapshot/Delta を判別)。
    """
    core = _import_core()
    v13 = core.run_supreme([fxp.frame_benign(ts=0.0)])  # 既定は /1.4
    v13_snap = fxp.snapshot(0.0, version=fxp.SNAPSHOT_VERSION_13,
                            objects=[fxp.object_track("O1", r_m=40.0)],
                            geom=fxp.geom(99.0), scene_state=fxp.scene_state(0.95, 20.0))
    v13_out = core.run_supreme([v13_snap])
    for out in (v13, v13_out):
        assert len(out) == 1
        assert EIGHT_LAYERS.issubset(set(out[0].keys())), (
            "Snapshot/1.3 または /1.4 で 8層 view が揃わない(version 両受理のはず)"
        )


# ===========================================================================
# ts 単調非減少違反(ts が前フレームより小)は拒否(本ファイルは例外で固定)
# ===========================================================================

def test_Fbase001_3_ts_decreasing_raises():
    """F-基盤-001-3(ADR 0022/0006・ts 単調非減少): ts が前フレームより小さい系列は明示エラーで
    拒否する。

    契約 §4「ts は単調非減少」。ts=0.0 → 1.0 → 0.5 のように後退する系列は時系列整合違反。
    本ファイルは『拒否=例外』を既定として固定する(ADR 0022 は『エラー or スキップを明示固定』
    と委任しており、ここでは止める方=エラーを採る)。
    """
    core = _import_core()
    seq = [
        fxp.frame_benign(ts=0.0),
        fxp.frame_benign(ts=1.0),
        fxp.frame_benign(ts=0.5),  # 後退(< 前フレーム)
    ]
    with pytest.raises(Exception):
        core.run_supreme(seq)


def test_Fbase001_3_ts_equal_is_allowed_non_decreasing():
    """F-基盤-001-3(ADR 0022/0006・ts 単調非減少の境界): ts が等しい連続フレーム(非減少=
    減少でない)は受理される(単調『非減少』であり狭義増加ではない)。

    契約 §4 は『単調非減少』(ts[i+1] >= ts[i])。等値(ts 同じ)は違反でない。等値系列で
    例外を投げず 8層 view が揃うことを固定する(減少のみ拒否)。
    """
    core = _import_core()
    seq = [
        fxp.frame_benign(ts=0.0),
        fxp.frame_benign(ts=0.0),  # 等値(非減少)
        fxp.frame_benign(ts=1.0),
    ]
    views = core.run_supreme(seq)
    assert len(views) == 3
    for v in views:
        assert EIGHT_LAYERS.issubset(set(v.keys())), (
            "ts 等値(非減少)系列で 8層 view が揃わない(等値を誤って拒否している疑い)"
        )


def test_Fbase001_3_ts_strictly_increasing_is_accepted():
    """F-基盤-001-3(ADR 0022/0006・ts 単調増加): 通常の単調増加 ts 系列は受理される。

    正常系の確認(後退拒否の対)。ts=0,1,2 の素直な系列で例外なく 8層 view が揃う。
    """
    core = _import_core()
    views = core.run_supreme([fxp.frame_benign(ts=float(i)) for i in range(3)])
    assert len(views) == 3


# ===========================================================================
# 任意フィールド(geom/scene_state 等)欠落時は縮退(エラーにせず既定で続行)
# ===========================================================================

def test_Fbase001_3_missing_geom_degrades_not_error():
    """F-基盤-001-3(ADR 0022/0006・欠落縮退): geom(min_TTC_s 等)が欠落しても例外を投げず、
    8層 view を生成して続行する(縮退)。

    契約 §0-5 / ADR 0006「任意フィールド(geom/scene_state 等)は欠落時縮退」。geom 欠落で
    落ちず、既定で 8層が揃うことを固定する(具体ラベル値は上流裁量・踏み込まない)。
    """
    core = _import_core()
    snap = fxp.snapshot(0.0, objects=[fxp.object_track("O1", r_m=40.0)],
                        scene_state=fxp.scene_state(0.95, 20.0))  # geom 無し
    views = core.run_supreme([snap])
    assert len(views) == 1
    assert EIGHT_LAYERS.issubset(set(views[0].keys())), (
        "geom 欠落で 8層 view が揃わない(欠落縮退でなくエラー/欠層になっている疑い)"
    )


def test_Fbase001_3_missing_scene_state_degrades_not_error():
    """F-基盤-001-3(ADR 0022/0006・欠落縮退): scene_state(QoS/latency_ms)が欠落しても
    例外を投げず 8層 view を生成して続行する(縮退)。

    QoS 欠落時は quality 観測式が既定値で縮退する(ADR 0022 構成要素3 は QoS から h_q/vol を
    作るが、欠落時は縮退既定)。落ちず 8層が揃うことを固定する。
    """
    core = _import_core()
    snap = fxp.snapshot(0.0, objects=[fxp.object_track("O1", r_m=40.0)],
                        geom=fxp.geom(99.0))  # scene_state 無し
    views = core.run_supreme([snap])
    assert len(views) == 1
    assert EIGHT_LAYERS.issubset(set(views[0].keys())), (
        "scene_state 欠落で 8層 view が揃わない(欠落縮退でなくエラー/欠層になっている疑い)"
    )


def test_Fbase001_3_missing_links_and_utter_events_degrades_not_error():
    """F-基盤-001-3(ADR 0022/0006・欠落縮退): links / utter_events が欠落しても例外を投げず
    8層 view を生成する(縮退)。

    links(speaking 等)・utter_events(call_user 等)は relation/role/mode の証拠源だが
    任意フィールド。欠落しても落ちず、無証拠既定で 8層が揃うことを固定する。
    """
    core = _import_core()
    snap = fxp.snapshot(0.0, audio=[fxp.audio_track("A1", "ambient", r_m=10.0)],
                        geom=fxp.geom(99.0), scene_state=fxp.scene_state(0.95, 20.0))
    views = core.run_supreme([snap])
    assert len(views) == 1
    assert EIGHT_LAYERS.issubset(set(views[0].keys()))


def test_Fbase001_3_minimal_snapshot_only_required_fields_degrades():
    """F-基盤-001-3(ADR 0022/0006・欠落縮退・極小): 契約 required(version/ts/frame/origin/
    tracks)のみで任意フィールドが全欠落の極小 Snapshot でも、例外を投げず 8層 view が揃う。

    tracks の audio/humans/objects は空配列。geom/scene_state/links/utter_events 全欠落。
    縮退の最も厳しいケース(証拠ほぼゼロ)で end-to-end が成立することを固定する。
    """
    core = _import_core()
    minimal = fxp.snapshot(0.0)  # tracks 空・任意フィールド全欠落
    views = core.run_supreme([minimal])
    assert len(views) == 1
    assert EIGHT_LAYERS.issubset(set(views[0].keys())), (
        "極小 Snapshot(required のみ)で 8層 view が揃わない(縮退が成立していない)"
    )
    for layer in EIGHT_LAYERS:
        assert isinstance(views[0][layer], str) and views[0][layer] != "", (
            f"極小 Snapshot の層 {layer} が非空ラベルでない(縮退既定が欠けている): "
            f"{views[0][layer]!r}"
        )
