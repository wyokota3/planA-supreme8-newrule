"""回帰テスト: t2_role の object-vehicle 経路を end-to-end で pin する。

観点(本ファイル固有・既存テストとの非重複):
  既存の F-006 role テスト(tests/test_F006_role_logits.py)は `has_vehicle` を抽出済み
  ブール値で `role.classify` に**直接注入**するため、core の証拠抽出(_role_evidence)を
  一切経由しない。既存の結線テスト(tests/test_Fbase001_wiring.py)も role 結線を
  **会話経路**(speech track → source_speech)でのみ固定する。よって 790 緑は
  「object track の type==vehicle を has_vehicle 証拠に変換する経路」を 1 件も実行して
  いない(監査 reports/audit-20260615-0242-role-B.md「テストカバレッジ」穴 1〜4)。

  本ファイルは唯一、`core.run_supreme` の end-to-end で **object track に type=="vehicle"**
  を持つ合成 PSO snapshot を流し、その view の `t2_role` を固定する。これにより
  修正(core._role_evidence の has_vehicle を `audio ∨ object` の忠実再現へ)が回帰しない
  ことを pin する。修正前は同じ object-vehicle snapshot で t2_role が unknown に潰れていた
  (診断 reports/role-diagnose-20260615-0233.md の 18 件取りこぼし)。

固定する現挙動(実装済み・green が前提の回帰テスト):
  1. object-vehicle(audio に vehicle 無し)→ source_vehicle(unknown に潰れない)= 核心の回復。
  2. audio-vehicle → source_vehicle(既存経路の非回帰)。
  3. object-vehicle ∧ 緊急音(siren/alarm)→ source_alarm(alarm 優先・vehicle に誤って倒さない)。
  4. vehicle 証拠が一切無い良性 → source_vehicle にしない(過剰予測しない)。
  5. 決定性(同一入力 2 回で t2_role 一致)。

根拠:
  - 忠実規則: reports/role-diagnose-20260615-0233.md(has_vehicle = audio ∨ object・§5)。
  - 修正の正当性/偽陽性ゼロ: reports/audit-20260615-0242-role-B.md。
  - role 語彙・ラベル定数: src/supreme/role.py(SOURCE_VEHICLE / SOURCE_ALARM 等の名前のみ参照)。
  - object track の type フィールドは PSO 入力契約 v1.4(objects[].type)。fixtures_pso の
    object_track は **extra kwargs を track dict に載せるため object_track(..., type="vehicle")
    で付与できる(fixtures_pso.py:87-90)。
  - r1 の elif 構造(緊急音優先 → source_alarm elif has_vehicle → source_vehicle)で alarm 共在
    時は vehicle に倒れない(role.py:98-102・監査 検証 2)。

規律:
  - stdlib のみ・決定的(乱数・時刻なし)。合成 PSO snapshot で完結(fixtures_pso 再利用)。
  - 実装ロジックは読まない・書かない。公開 API(core.run_supreme)と role の公開ラベル定数のみ。
  - 既存テストは不変。object/audio/緊急音の弁別を実際に固定し骨抜きにしない。
"""

import fixtures_pso as fxp

from supreme import role


def _import_core():
    """supreme.core を import して返す(統合ランナー run_supreme の入口)。"""
    from supreme import core

    return core


# v1.4 role 統制語彙のラベルは role モジュールの公開定数から引く(リテラル直書きを避ける)。
SOURCE_VEHICLE = role.SOURCE_VEHICLE  # "source_vehicle"
SOURCE_ALARM = role.SOURCE_ALARM      # "source_alarm"


# ---------------------------------------------------------------------------
# 合成 snapshot ビルダ(本ファイル固有・object track に type を付与する経路を作る)
# ---------------------------------------------------------------------------

def _object_vehicle_snapshot(ts, *, r_m=30.0):
    """object track に type=="vehicle" を持つ snapshot(audio/会話/緊急音は無し)。

    diagnose の取りこぼしフレーム(audio=['noise'] or 無音 + object=['vehicle']・n_humans=0)
    と同型。audio に vehicle を入れず、object 経路だけで has_vehicle 証拠が立つことを狙う。
    会話証拠(speech/speaking link)も緊急音(siren/alarm)も一切入れない。
    """
    return fxp.snapshot(
        ts,
        objects=[fxp.object_track("O_veh", r_m=r_m, type="vehicle")],
        geom=fxp.geom(min_TTC_s=99.0),
        scene_state=fxp.scene_state(qos=0.95, latency_ms=20.0),
    )


def _audio_vehicle_snapshot(ts, *, r_m=30.0):
    """audio track に type=="vehicle" を持つ snapshot(既存経路・object vehicle 無し)。

    緊急音(siren/alarm)・会話証拠は入れない。audio 経路のみで has_vehicle を立てる。
    """
    return fxp.snapshot(
        ts,
        audio=[fxp.audio_track("A_veh", "vehicle", r_m=r_m)],
        geom=fxp.geom(min_TTC_s=99.0),
        scene_state=fxp.scene_state(qos=0.95, latency_ms=20.0),
    )


def _object_vehicle_with_alarm_snapshot(ts, *, r_m=20.0):
    """object-vehicle と緊急音(siren)を同時に持つ snapshot(偽陽性ガード用)。

    diagnose の `source_vehicle→source_alarm` フレーム(audio=['siren'] + object=['vehicle'])
    と同型。r1 elif 構造で alarm が優先され source_alarm になる(vehicle に倒さない)はず。
    """
    return fxp.snapshot(
        ts,
        audio=[fxp.audio_track("A_siren", "siren", r_m=r_m)],
        objects=[fxp.object_track("O_veh", r_m=r_m, type="vehicle")],
        geom=fxp.geom(min_TTC_s=99.0),
        scene_state=fxp.scene_state(qos=0.95, latency_ms=20.0),
    )


# ===========================================================================
# 1. object-vehicle → source_vehicle(核心: unknown 取りこぼしの回復)
# ===========================================================================

def test_object_vehicle_yields_source_vehicle():
    """観点 1(核心): audio に vehicle 無し・object track に type=="vehicle" を持ち、会話・
    緊急音の無い snapshot を run_supreme に流すと t2_role == source_vehicle。

    修正前は has_vehicle 証拠が audio track のみを見ていたため object-vehicle が拾われず
    unknown に潰れていた(診断 18 件)。本テストは object 経路で has_vehicle が立ち
    source_vehicle が一意 argmax になる現挙動を pin する。unknown に潰れないことを固定。
    """
    core = _import_core()
    view = core.run_supreme([_object_vehicle_snapshot(ts=0.0)])[0]
    assert view["t2_role"] == SOURCE_VEHICLE, (
        f"object-vehicle snapshot の t2_role が source_vehicle でない: {view['t2_role']!r}"
        "(object track type==vehicle が has_vehicle 証拠まで結線されず unknown に潰れた疑い"
        "=修正の回帰)"
    )


# ===========================================================================
# 2. audio-vehicle → source_vehicle(既存経路の非回帰)
# ===========================================================================

def test_audio_vehicle_still_yields_source_vehicle():
    """観点 2(非回帰): audio track に type=="vehicle" を持つ snapshot は従来どおり
    t2_role == source_vehicle。

    object 経路を足した修正で audio 経路(`audio ∨ object` の audio 側)を壊していない
    ことを固定する。緊急音・会話は無し。
    """
    core = _import_core()
    view = core.run_supreme([_audio_vehicle_snapshot(ts=0.0)])[0]
    assert view["t2_role"] == SOURCE_VEHICLE, (
        f"audio-vehicle snapshot の t2_role が source_vehicle でない: {view['t2_role']!r}"
        "(修正で audio 経路を壊した疑い)"
    )


# ===========================================================================
# 3. 偽陽性ガード: object-vehicle ∧ 緊急音 → source_alarm(vehicle に倒さない)
# ===========================================================================

def test_object_vehicle_with_siren_yields_source_alarm_not_vehicle():
    """観点 3(偽陽性ガード): object-vehicle と siren(緊急音)を同時に持つ snapshot は
    t2_role == source_alarm(source_vehicle ではない)。

    r1 は緊急音優先の elif(has_siren∨has_alarm → source_alarm / elif has_vehicle →
    source_vehicle)。object-vehicle を has_vehicle 証拠に足しても、緊急音が共在する
    フレームでは alarm が優先され vehicle に誤って倒さないことを固定する(監査 検証 2 の
    偽陽性ゼロを回帰固定)。
    """
    core = _import_core()
    view = core.run_supreme([_object_vehicle_with_alarm_snapshot(ts=0.0)])[0]
    assert view["t2_role"] == SOURCE_ALARM, (
        f"object-vehicle ∧ siren の t2_role が source_alarm でない: {view['t2_role']!r}"
        "(緊急音優先の elif が崩れ vehicle に誤って倒れた疑い=偽陽性)"
    )
    assert view["t2_role"] != SOURCE_VEHICLE, (
        "object-vehicle ∧ 緊急音で source_vehicle に倒れている(alarm 優先が効いていない)"
    )


# ===========================================================================
# 4. vehicle 証拠が無い良性 → source_vehicle にしない(過剰予測しない)
# ===========================================================================

def test_benign_no_vehicle_evidence_is_not_source_vehicle():
    """観点 4(過剰予測しない): vehicle 証拠(audio/object とも type!=vehicle)が無い良性
    snapshot は t2_role != source_vehicle。

    良性フレーム(frame_benign)は object track が type を持たない(O1・r_m=40)。
    has_vehicle が立たず source_vehicle が発火しないこと=object 経路が type を見て判定し、
    全 object track を無条件に vehicle 扱いしていないことを固定する(過剰予測ガード)。
    """
    core = _import_core()
    view = core.run_supreme([fxp.frame_benign(ts=0.0)])[0]
    assert view["t2_role"] != SOURCE_VEHICLE, (
        f"vehicle 証拠の無い良性 snapshot の t2_role が source_vehicle: {view['t2_role']!r}"
        "(object track を type 無視で vehicle 扱いしている過剰予測の疑い)"
    )


# ===========================================================================
# 5. 決定性: 同一入力 2 回で t2_role 一致
# ===========================================================================

def test_object_vehicle_role_is_deterministic():
    """観点 5(決定性): 同一の object-vehicle snapshot を 2 回 run_supreme に流すと
    t2_role が一致する(乱数・時刻に依存しない決定的経路)。

    object-vehicle 経路が決定的純関数経路であること(証拠抽出 → role argmax)を固定する。
    """
    core = _import_core()
    snap = _object_vehicle_snapshot(ts=0.0)
    role_a = core.run_supreme([snap])[0]["t2_role"]
    role_b = core.run_supreme([snap])[0]["t2_role"]
    assert role_a == role_b, (
        f"同一 object-vehicle 入力で t2_role が 2 回一致しない: {role_a!r} != {role_b!r}"
        "(object-vehicle 経路に非決定性が混入している疑い)"
    )
    # 念のため核心ラベルでもあること(回帰の二重固定)。
    assert role_a == SOURCE_VEHICLE, (
        f"決定性テストの t2_role が source_vehicle でない: {role_a!r}"
    )
