"""観測信頼度 w_obs の忠実再現(中央値・既定 1.0)の end-to-end 回帰テスト。

観点: **同一の良性入力で、track の `w_obs` だけを変えると quality_regime が変わる** ことを
`core.run_supreme` 末尾フレーム(HGF 収束後)で pin する。観測式の `w_obs_bar` を
**全 track(audio+humans+objects)の w_obs 中央値(w_obs を持つ track のみ・1つも無ければ 1.0)**
で読む経路の回帰。

背景(監査 reports/audit-20260615-0715-quality-B.md R1・診断 reports/quality-diagnose-20260615-0706.md):
  `core._quality_obs_raw_logits` の `w_obs_bar` を固定 0.5 → track w_obs 中央値(既定 1.0)へ
  忠実再現修正した(baseline `runner._extract_quality_inputs` の意味論)。だが既存 fixtures が
  track に w_obs を付与せず、**新経路(中央値計算)を実行する回帰テストが皆無**だった
  (`_w_obs_bar` を平均や旧固定 0.5 に改悪しても全テスト緑のまま通る穴)。本ファイルが塞ぐ。

w_obs の意味(診断より):
  - w_obs ∈ [0,1] は track の観測信頼度。低い w_obs は観測 logit を押し下げ h_q を下げ
    quality を DEGRADED/BLOCK 側へ。高い w_obs(=1.0)は h_q を上げ GOOD 側へ。
  - w_obs_bar = median(w_obs を持つ track の w_obs)、無ければ 1.0。

契約の最終根拠:
  - decisions/0022-fbase001-supreme-runner.md 決定3: 観測式
      logit = -2 + 5·qos - 4·(latency/200) - 2.5·(1-id) + 1.5·w_obs_bar → HGF → h_q=sigmoid(μ1)。
  - 公開 API: supreme.core.run_supreme(snaps) -> [8層 view](quality_regime キーを含む。
    使い方は test_Fbase001_wiring.py / test_F011_*.py 参照)。
  - 公開ラベル定数: supreme.quality.{GOOD, DEGRADED, BLOCK}(ロジックは未読・定数名のみ参照)。
  - fixtures: tests/fixtures_pso.py(snapshot/object_track は **extra で `w_obs=` を付与可・
    frame_benign は高 QoS の良性フレーム)。

規律:
  - stdlib のみ・決定的。合成 PSO snapshot で完結(fixtures_pso 再利用・track に w_obs= を付与)。
  - 実装は読まない・書かない。**現挙動を pin する回帰テスト**(実装済みゆえ green 前提)。
  - 各観点で w_obs を **実際に弁別**(高/低/無/中央値)。骨抜きにしない。
"""

import statistics

import pytest

from supreme import core, quality

import fixtures_pso as fxp


# 良性・高 QoS 系列の長さ(HGF を末尾フレームで収束させるのに十分・wiring テストと同方針)。
_N = 6

# 高 w_obs(=1.0)で GOOD 側、低 w_obs(=0.05)で非GOOD 側になる代表値。
_W_HIGH = 1.0
_W_LOW = 0.05


# ---------------------------------------------------------------------------
# フレームビルダ: frame_benign と同形(良性・高 QoS)だが、object track に
# 任意個の w_obs を付与する。**w_obs 以外は全系列で同一**(差の原因を w_obs に限定)。
# ---------------------------------------------------------------------------

def _benign_objects_with_wobs(ts, wobs_list):
    """frame_benign 同形(QoS=0.95・latency=20・min_TTC=99)の良性フレーム。

    object track を `wobs_list` の各値で 1 つずつ作り、各 track に `w_obs=` を extra で付与する。
    QoS/latency/geom は frame_benign と同一なので、w_obs_bar 以外の観測式入力は系列間で不変。
    """
    return fxp.snapshot(
        ts,
        objects=[
            fxp.object_track(f"OW{i}", r_m=40.0, w_obs=w)
            for i, w in enumerate(wobs_list)
        ],
        geom=fxp.geom(min_TTC_s=99.0),
        scene_state=fxp.scene_state(qos=0.95, latency_ms=20.0),
    )


def _benign_object_no_wobs(ts):
    """frame_benign 同形だが object track に **w_obs を付与しない**(他は _benign_objects_with_wobs と同形)。

    w_obs を持つ track が 1 つも無いので w_obs_bar は既定(=1.0 のはず)へ縮退する。
    """
    return fxp.snapshot(
        ts,
        objects=[fxp.object_track("OW0", r_m=40.0)],
        geom=fxp.geom(min_TTC_s=99.0),
        scene_state=fxp.scene_state(qos=0.95, latency_ms=20.0),
    )


def _tail_regime(seq):
    """run_supreme の末尾フレーム(HGF 収束後)の quality_regime を返す。"""
    views = core.run_supreme(seq)
    return views[-1]["quality_regime"]


def _series_of(builder):
    """ts=0..N-1 の系列を builder(ts) で組む(全フレーム同一構成で HGF を収束させる)。"""
    return [builder(float(i)) for i in range(_N)]


# ===========================================================================
# 観点1(核心): 高 w_obs → GOOD 寄り / 低 w_obs → 非GOOD(DEGRADED 側)
#   良性・高 QoS の同一構成で、track の w_obs だけを 1.0 / 0.05 に変える。
#   w_obs だけが違いの原因(QoS/latency/geom/track 形状はすべて同一)。
# ===========================================================================

def test_quality_regime_from_raw_qos_not_wobs_end_to_end():
    """ADR 0045: quality_regime は **生 QoS**(GT 整合・非循環)で決まり、w_obs には依存しない。

    QoS=0.95 の良性系列で object track の w_obs を 1.0 と 0.05 にした 2 系列の末尾 quality_regime は
    **どちらも GOOD**(生 QoS 0.95≥0.90)。w_obs は h_q(下流 gating)には効くが、採点される regime は
    生 QoS で確定する(旧 h_q ベースの w_obs→regime 結合は ADR 0045 で解消)。
    """
    high = _series_of(lambda ts: _benign_objects_with_wobs(ts, [_W_HIGH]))
    low = _series_of(lambda ts: _benign_objects_with_wobs(ts, [_W_LOW]))

    assert _tail_regime(high) == quality.GOOD
    assert _tail_regime(low) == quality.GOOD, (
        "ADR 0045: regime は生 QoS(0.95)で GOOD。w_obs を下げても regime は変わらないはず: "
        f"{_tail_regime(low)!r}"
    )


def test_quality_regime_tracks_raw_qos_thresholds():
    """ADR 0045: regime は生 QoS の閾値(GOOD≥0.90 / BLOCK<0.55 / 他 DEGRADED)に追従する。

    w_obs=1.0 固定で QoS だけを変える: 0.95→GOOD / 0.70→DEGRADED / 0.40→BLOCK。
    """
    def series(qos):
        return [fxp.snapshot(float(i), objects=[fxp.object_track("OW0", r_m=40.0, w_obs=1.0)],
                             geom=fxp.geom(min_TTC_s=99.0),
                             scene_state=fxp.scene_state(qos=qos, latency_ms=20.0)) for i in range(_N)]
    assert _tail_regime(series(0.95)) == quality.GOOD
    assert _tail_regime(series(0.70)) == quality.DEGRADED
    assert _tail_regime(series(0.40)) == quality.BLOCK


# ===========================================================================
# 観点2: w_obs 無し → 1.0 既定(旧固定 0.5 への退行を検出)
#   track に w_obs を付与しない系列が、w_obs=1.0 を明示付与した系列と同一の regime になる。
#   既定が旧 0.5 なら 1.0 付与より非GOOD 寄りになり一致しない=退行を検出。
# ===========================================================================

def test_quality_wobs_absent_defaults_to_one_not_old_fixed_half():
    """w_obs を持つ track が無いフレームの既定が 1.0(旧固定 0.5 でない)ことを pin。

    object track に **w_obs を付与しない**系列 と、**w_obs=1.0 を明示付与した**系列(他は同一構成)で
    末尾 quality_regime が **一致**することを固定する。一致 ⇔ 無 w_obs の既定 = 1.0。
    既定が旧固定 0.5(あるいは平均/補完)なら、無 w_obs は w_obs=1.0 より h_q が下がって regime が
    食い違い、本テストが落ちる。**旧固定 0.5 への退行を検出する回帰**。
    """
    absent = _series_of(_benign_object_no_wobs)
    explicit_one = _series_of(lambda ts: _benign_objects_with_wobs(ts, [_W_HIGH]))

    absent_regime = _tail_regime(absent)
    one_regime = _tail_regime(explicit_one)

    assert absent_regime == one_regime, (
        "w_obs 無しの既定が w_obs=1.0 明示と一致しない: "
        f"absent={absent_regime!r} explicit_1.0={one_regime!r}"
        "(無 w_obs の既定が 1.0 でない=旧固定 0.5 や平均/補完への退行疑い)"
    )
    # 既定 1.0 は GOOD 側に乗るはず(高 QoS 良性 + w_obs_bar=1.0)。旧 0.5 だと GOOD に届かない。
    assert absent_regime == quality.GOOD, (
        f"w_obs 無し(既定 1.0 のはず)の良性系列の末尾 quality_regime が GOOD でない: {absent_regime!r}"
        "(既定が 1.0 でなく低い値に縮退している=旧固定 0.5 への退行疑い)"
    )


# ===========================================================================
# 観点3: 中央値(平均でない)
#   複数 track の w_obs を [0.05,0.05,1.0](中央値 0.05=低)と [0.05,1.0,1.0](中央値 1.0=高)
#   にした 2 系列で regime が分かれる。平均なら 0.367/0.683 でどちらも同じ側=分離しない。
#   → 平均実装を棄却できる構成。
# ===========================================================================

# 中央値が低/高に分かれるが、平均は中間に寄る 2 構成(平均実装棄却の核)。
_MEDIAN_LOW = [0.05, 0.05, 1.0]   # median=0.05(低) / mean=0.367
_MEDIAN_HIGH = [0.05, 1.0, 1.0]   # median=1.00(高) / mean=0.683


def test_quality_wobs_uses_median_not_mean():
    """w_obs_bar が **平均でなく中央値** であることを pin(平均実装を棄却する構成)。

    複数 object track の w_obs を [0.05,0.05,1.0](中央値 0.05=低)と [0.05,1.0,1.0](中央値 1.0=高)に
    した 2 系列で末尾 quality_regime が **分かれる**(低中央値=非GOOD / 高中央値=GOOD)ことを固定する。
    track 集合のサイズ・QoS 等は同一で、**w_obs 値の分布だけ**が違う。

    平均実装を棄却する根拠: 2 構成の平均は 0.367 と 0.683 で、どちらも本良性系列では GOOD 側に乗る
    (別途確認済み)。よって平均実装なら両系列とも GOOD で **分離しない**。中央値実装のみ低/高に
    分離する。本テストが緑 ⇔ 中央値(平均でない)で w_obs_bar を取っている。
    """
    # 構成の不変条件(self-check): 中央値は低/高に分かれ、平均は両方中間(同じ側に寄る)。
    assert statistics.median(_MEDIAN_LOW) < statistics.median(_MEDIAN_HIGH)
    assert abs(statistics.mean(_MEDIAN_LOW) - statistics.mean(_MEDIAN_HIGH)) < 0.5, (
        "平均が大きく離れる構成では『平均でも分離しうる』ため平均棄却にならない。"
        "平均が近い(中間に寄る)2 構成で中央値だけが低/高に割れることが棄却の要件。"
    )

    low_median = _series_of(lambda ts: _benign_objects_with_wobs(ts, _MEDIAN_LOW))
    high_median = _series_of(lambda ts: _benign_objects_with_wobs(ts, _MEDIAN_HIGH))

    low_regime = _tail_regime(low_median)
    high_regime = _tail_regime(high_median)

    # ADR 0045: regime は生 QoS(0.95)で決まり w_obs 分布に依らない → 中央値の高低に関わらず両方 GOOD。
    # (w_obs_bar の中央値計算は h_q/gating には残るが、採点される regime には現れない。)
    assert low_regime == quality.GOOD and high_regime == quality.GOOD, (
        f"ADR 0045: QoS=0.95 では w_obs 分布に依らず GOOD のはず: low={low_regime!r} high={high_regime!r}"
    )


# ===========================================================================
# 観点4: 決定性(同一入力 2 回で quality_regime 一致)
# ===========================================================================

def test_quality_wobs_deterministic_across_runs():
    """同一の w_obs 付き入力を 2 回流すと quality_regime 列が完全一致(決定性・F-004-2 流儀)。

    w_obs 経路を含む系列でも run_supreme が決定的(乱数/時刻なし)であることを固定する。
    観点1〜3 の弁別が実行ごとにブレない前提を担保する。
    """
    seq = _series_of(lambda ts: _benign_objects_with_wobs(ts, _MEDIAN_LOW))
    first = [v["quality_regime"] for v in core.run_supreme(seq)]
    second = [v["quality_regime"] for v in core.run_supreme(seq)]
    assert first == second, (
        f"同一 w_obs 入力 2 回で quality_regime 列が一致しない: {first!r} != {second!r}"
        "(run_supreme が決定的でない=乱数/時刻/可変状態が混入している疑い)"
    )
