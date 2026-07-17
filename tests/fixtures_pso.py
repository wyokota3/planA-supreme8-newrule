"""F-基盤-001(ADR 0022)用 合成 PSO-Snapshot フィクスチャ(決定的・最小限)。

方針(指示・TEST_STRATEGY「テストデータ管理」):
- 依存は stdlib のみ。PSO-Snapshot を dict リテラルで決定的に合成する。
- 形状は **PSO 入力契約 v1.4**(external-data/.../ns_epi_input_contract_v_1.4_pso_snapshot_delta.md)
  の PSO-Snapshot/1.4 に接地: version / ts / frame="W2D" / origin / tracks{audio,humans,objects}
  / links / geom{min_TTC_s,overlap_path,lane_alignment} / utter_events / scene_state{QoS,latency_ms}。
- **Snapshot のみ**(Delta は ADR 0006 で非対応)。fields_ref/grid 等の重い任意フィールドは
  v021_core 同様に省略する(契約 §5.3「v021_core は全フレーム fields_ref を省略」)。
- 「証拠抽出」の具体閾値は上流共有基盤の裁量(ADR 0022)なので、フィクスチャは各モジュールが
  代表ケースで明確に発火する強い値を与える(境界値の網羅は各モジュールの F-006〜011 で済み)。

注意:
- これはテスト基盤であり実装コードではない。run_supreme は未実装のため、これを使うテストは
  ImportError 等で失敗する(TDD の期待挙動)。
"""

# 契約 v1.4 のレコード型バージョン(supreme は 1.3/1.4 両受理・ADR 0006)。
SNAPSHOT_VERSION_14 = "PSO-Snapshot/1.4"
SNAPSHOT_VERSION_13 = "PSO-Snapshot/1.3"
DELTA_VERSION_14 = "PSO-Delta/1.4"


def _origin():
    return {"x_m": 0.0, "y_m": 0.0, "yaw_deg": 0.0}


def snapshot(
    ts,
    *,
    version=SNAPSHOT_VERSION_14,
    audio=None,
    humans=None,
    objects=None,
    links=None,
    geom=None,
    utter_events=None,
    scene_state=None,
):
    """1フレームの PSO-Snapshot(world_state dict)を作る。

    任意フィールド(geom/scene_state/links/utter_events)は省略可能(欠落時縮退の検証用)。
    tracks{audio,humans,objects} は契約上 required なので空配列で必ず付与する。
    """
    snap = {
        "version": version,
        "ts": float(ts),
        "frame": "W2D",
        "origin": _origin(),
        "tracks": {
            "audio": list(audio or []),
            "humans": list(humans or []),
            "objects": list(objects or []),
        },
    }
    if links is not None:
        snap["links"] = list(links)
    if geom is not None:
        snap["geom"] = dict(geom)
    if utter_events is not None:
        snap["utter_events"] = list(utter_events)
    if scene_state is not None:
        snap["scene_state"] = dict(scene_state)
    return snap


# ---------------------------------------------------------------------------
# track ヘルパ(契約 §1.1 tracks.audio/humans/objects のプロパティに沿う最小形)
# ---------------------------------------------------------------------------

def audio_track(aid, type_, r_m, theta_deg=0.0, **extra):
    t = {"aid": aid, "type": type_, "r_m": float(r_m), "theta_deg": float(theta_deg)}
    t.update(extra)
    return t


def human_track(hid, r_m, theta_deg=0.0, *, speaking_prob=None, face_towards_user=None, **extra):
    t = {"hid": hid, "r_m": float(r_m), "theta_deg": float(theta_deg)}
    if speaking_prob is not None:
        t["speaking_prob"] = float(speaking_prob)
    if face_towards_user is not None:
        t["face_towards_user"] = float(face_towards_user)
    t.update(extra)
    return t


def object_track(oid, r_m, theta_deg=0.0, **extra):
    t = {"oid": oid, "r_m": float(r_m), "theta_deg": float(theta_deg)}
    t.update(extra)
    return t


def geom(min_TTC_s, *, overlap_path=False, lane_alignment=False):
    return {
        "overlap_path": bool(overlap_path),
        "lane_alignment": bool(lane_alignment),
        "min_TTC_s": float(min_TTC_s),
    }


def scene_state(qos, latency_ms, *, noise_db=None):
    s = {"latency_ms": float(latency_ms), "QoS": float(qos)}
    if noise_db is not None:
        s["noise_db"] = float(noise_db)
    return s


# ---------------------------------------------------------------------------
# 代表 frame ビルダ(結線確認用・各モジュールが明確に発火する強い値)
# ---------------------------------------------------------------------------

def frame_benign(ts):
    """良性・静穏フレーム: 危険トラック無し・会話無し・QoS 高・接近無し。

    risk_tier=info 寄り / t1=idle 寄り / mode=quiet 寄り / quality=GOOD 寄り /
    scene=STABLE 寄り を引き出す既定フレーム。各モジュールの中立基準として使う。
    """
    return snapshot(
        ts,
        objects=[object_track("O1", r_m=40.0)],
        geom=geom(min_TTC_s=99.0),
        scene_state=scene_state(qos=0.95, latency_ms=20.0),
    )


def frame_siren(ts, *, r_m=30.0, min_TTC_s=15.0, qos=0.95):
    """siren track を含むフレーム(t0 結線確認)。

    siren は ADR 0017 決定3 T0 の siren 下限で info にならず caution/danger 側になる。
    """
    return snapshot(
        ts,
        audio=[audio_track("A_siren", "siren", r_m=r_m)],
        geom=geom(min_TTC_s=min_TTC_s),
        scene_state=scene_state(qos=qos, latency_ms=20.0),
    )


def frame_approach(ts, *, r_m, min_TTC_s):
    """接近中フレーム(t1 結線確認・min_TTC 小 + range が系列で減少)。"""
    return snapshot(
        ts,
        audio=[audio_track("A_veh", "vehicle", r_m=r_m)],
        geom=geom(min_TTC_s=min_TTC_s),
        scene_state=scene_state(qos=0.95, latency_ms=20.0),
    )


def frame_conversation(ts, *, r_m=2.0, speaking_prob=0.9):
    """会話証拠フレーム(mode/role/relation 結線確認)。

    speech track + 近接 human(speaking_prob 高)+ speaking link + utter_events。role=source_speech /
    relation=addressing_user / mode=conv 系を引き出す強い会話証拠。

    NOTE(ADR 0047): GT(gt_derive.mode_seq)の conv 判定は `utter_events 在り ∧ (speaking|addressing link)`。
    旧フィクスチャは utter_events を欠き strict mode_seq では conv にならなかった(=不完全な会話証拠)。
    実コーパスの会話フレームは utter_events を持つため、GT 整合の会話証拠として付与する。
    """
    return snapshot(
        ts,
        audio=[audio_track("A_sp", "speech", r_m=r_m)],
        humans=[human_track("H1", r_m=r_m, speaking_prob=speaking_prob, face_towards_user=0.9)],
        links=[{"from": "A_sp", "to": "H1", "type": "speaking", "score": 0.9}],
        geom=geom(min_TTC_s=99.0),
        scene_state=scene_state(qos=0.95, latency_ms=20.0),
        utter_events=[{"id": "u", "speaker": "H1"}],
    )


def frame_low_qos(ts, *, qos=0.05, latency_ms=190.0):
    """低 QoS フレーム(quality 結線確認・観測式 + HGF → quality)。

    QoS 低・latency 高 → 観測式 logit が下がり h_q 低 → quality_regime が DEGRADED/BLOCK 側。
    """
    return snapshot(
        ts,
        objects=[object_track("O1", r_m=40.0)],
        geom=geom(min_TTC_s=99.0),
        scene_state=scene_state(qos=qos, latency_ms=latency_ms),
    )
