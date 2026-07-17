"""F-010: scene regime 改良(scene)— HGF 階層ボラティリティ + 持続性特徴 + 3クラス分類。

supreme の scene regime 判定を「少量学習」で解く改良モジュール。入力 = scene 診断信号
(health_raw / H_post の系列・float 列)、出力 = 各ステップの v1.4 scene regime
(STABLE / CHANGING / DEGRADING)。診断抽出(6診断 → health_raw)は上流の共有基盤であり
スコープ外(信号を直接受ける)。

契約の最終根拠は specs/SPEC.md「F-010」節、
decisions/0019-f010-scene-hgf-learning.md(手法の正・決定1〜4)、
decisions/0018(U24: 学習可能パラメータのみ計数・k=0.5)、decisions/0006(v1.4 scene 語彙)、
decisions/0002(ε=U5a・再現性 F-004-2)、および tests/test_F010_*.py。

構成(ADR 0019 決定1):
  A) HGF 3層カーネル(階層 Gaussian filter)— 潜在水準 μ1(層1)と log-volatility(層2)を
     階層推定する。層2のボラティリティが「持続的変化」(1ステップ drift が見逃す sustained
     non-stationarity)を捉える=見逃しの根本対処。本モジュールが独立再実装する(共有基盤を
     一切参照しない・決定4の独立性)。
  B) 持続性特徴 — nominal 水準からの逸脱を漏れ積分(slow nominal EMA + 逸脱の持続度)。
     平坦・非nominal に張り付くと正に蓄積し(見逃しを CHANGING 側へ寄せる)、平坦・nominal は
     ≈0、単発スパイクは小さい。
  C) 3クラス分類 — (HGF 水準 μ1, HGF 層2ボラティリティ, 持続逸脱量)を入力に閾値で
     STABLE / CHANGING / DEGRADING を判定。DEGRADING を3クラス目標に含める。
  D) 学習可能パラメータ予算 — 学習対象(HGF param + regime 閾値)のみ計数。固定の集約・EMA
     係数は計上しない(U24)。予算検査は guard.check_param_budget を再利用する。
  E) 学習(fit)— 決定的手順(乱数なし・grid/座標降下)。同じ練習データで2回 fit すると
     同一 learned_params。再現性(F-004-2)のため学習も決定的。
  F) end-to-end — 信号列 → (HGF + 持続性 + 分類)→ regime 列。同入力+同 params で完全一致。

決定的(乱数・時刻なし)。本モジュールは stdlib(math)のみに依存し、他 supreme モジュール
(guard 以外)を改修しない。guard は予算検査の再利用のみ(改修しない)。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# v1.4 scene 統制語彙(ADR 0006 / 0019 決定1)のラベル定数。値は自身の文字列。
# DEGRADING を3クラス目標に含める(deg 検出も同時最適化・ADR 0019)。
# ---------------------------------------------------------------------------

STABLE = "STABLE"
CHANGING = "CHANGING"
DEGRADING = "DEGRADING"

#: 出力語彙(end-to-end / classify_scene が閉じる集合)。
_V14_SCENE = (STABLE, CHANGING, DEGRADING)

#: log(e^2) のゼロ割回避用の床(決定的・微小)。
_LOG_FLOOR = 1e-12


# ===========================================================================
# A) HGF 3層カーネル(階層 Gaussian filter)
# ===========================================================================

@dataclass(frozen=True)
class HgfTrajectory:
    """HGF カーネルの belief 軌跡(各ステップの潜在水準とボラティリティ推定)。

    mu1        : 各ステップの潜在水準推定(層1)。len == 入力長。
    volatility : 各ステップのボラティリティ推定(層2 log-volatility=exp(μ2)・非負)。
                 「持続的変化」(scene の CHANGING)を捉える層2 量。len == 入力長。
    var1       : 各ステップの層1 事後分散(=1/π1・非負)。層1 推定の不確かさで、
                 観測精度が高いほど小さい。これが baseline quality.py の `sigma1`
                 (=1/pi1_new)に対応する正準量で、quality の GOOD ゲート `vol<0.01` が
                 想定する入力(ADR 0014 計測: 0.0058〜0.0099)。scene は volatility を、
                 quality は var1 を使う(層が違う・混同しない)。len == 入力長。
                 既定 () は後方互換(旧構築箇所が var1 を渡さなくても壊れない)。
    """

    mu1: tuple
    volatility: tuple
    var1: tuple = ()


def default_hgf_params() -> dict:
    """既定 HGF パラメータ(決定的・fit 前の初期値)。

    層1 = 潜在水準 x1(precision 加重で観測へ追従)。層2 = log-volatility x2(slow random walk
    で log(innovation^2) へ寄せる=持続的に逸脱し続ける入力でのみ蓄積し、単発スパイク後の平坦列
    では減衰する)。層3 = メタ log-rate x3(層2 の有効学習率を緩やかに調整)。

    これらの既定値は、ボラティリティ応答の性質テスト
    (持続変化列 > 定常列 / 持続変化列 > 1ステップ跳ね平坦列 / 定常列 < drift 列)を満たすよう
    決定済み(ADR 0019 決定1・性質充足が要件・実際の学習値は F-013)。
    """
    return {
        # 層間結合 κ(層2→層1 のボラ寄与、層3→層2 の rate 寄与)。
        "kappa1": 1.0,
        "kappa2": 0.1,        # 層2 log-volatility の学習率(slow walk)。
        # 各層の tonic(定常)log-volatility 切片 ω。
        "omega1": -3.0,       # 層1 process log-variance 切片。
        "omega2": -2.0,       # 層2 log-volatility のスケール切片。
        "omega3": 0.0,        # 層3(meta-rate)切片。
        "obs_noise": 0.01,    # 観測ノイズ分散(層1 観測 precision = 1/obs_noise)。
        # 初期 belief(決定的)。学習対象ではない(初期化定数)。
        "mu1_0": 0.0,
        "mu2_0": -4.0,
        "mu3_0": 0.0,
        "pi1_0": 1.0,
    }


def hgf_filter(signal_sequence, params) -> HgfTrajectory:
    """信号列を HGF 3層カーネルで逐次フィルタし、belief 軌跡を返す(ADR 0019 決定1)。

    決定的(乱数・時刻なし)。各ステップで層1(潜在水準 μ1)を precision 加重で観測へ更新し、
    層2(log-volatility)を「層1 の prediction error の2乗」へ slow random walk で寄せる。
    層3 は層2 の有効学習率を緩やかに調整する meta-volatility。

    ボラティリティ = exp(μ2)(常に正)。持続的に逸脱し続ける列では prediction error が
    一貫して非ゼロなので μ2(=log-volatility)が蓄積し、単発スパイク後の平坦列では
    後続の prediction error ≈0 が log-volatility を引き下げる(=持続性のみを蓄積)。

    Args:
        signal_sequence: scene 診断信号の float 列。
        params: HGF パラメータ dict(default_hgf_params() 形式)。

    Returns:
        HgfTrajectory(.mu1, .volatility)。長さは入力列長に一致。
    """
    p = params
    ka1 = float(p["kappa1"])
    ka2 = float(p["kappa2"])
    om1 = float(p["omega1"])
    om2 = float(p["omega2"])
    om3 = float(p["omega3"])
    obs = float(p["obs_noise"])

    mu1 = float(p["mu1_0"])
    mu2 = float(p["mu2_0"])
    mu3 = float(p["mu3_0"])
    pi1 = float(p["pi1_0"])

    obs_pi = 1.0 / obs

    mu1_out = []
    vol_out = []
    var1_out = []
    for raw in signal_sequence:
        u = float(raw)

        # ---- 層1: 潜在水準 x1 を precision 加重で観測へ更新 ----
        # process 分散は層2 のボラティリティで膨らむ(exp(ka1*mu2 + om1))。
        v1 = math.exp(ka1 * mu2 + om1)
        pi1_pred = 1.0 / (1.0 / pi1 + v1)        # 拡散後の予測 precision。
        muhat1 = mu1                              # 予測平均(ドリフト無し)。
        e = u - muhat1                            # 層1 prediction error(innovation)。
        pi1 = pi1_pred + obs_pi                   # 観測取り込み後の posterior precision。
        mu1 = muhat1 + (obs_pi / pi1) * e         # posterior 平均(観測へ寄る)。

        # ---- 層3: 層2 の有効学習率(meta-volatility)を緩やかに調整 ----
        rate2 = 1.0 / (1.0 + math.exp(-(mu3 + om3)))   # sigmoid -> (0,1)。

        # ---- 層2: log-volatility x2 を log(e^2) へ slow random walk ----
        target = math.log(e * e + _LOG_FLOOR) + om2
        mu2 = mu2 + ka2 * rate2 * (target - mu2)

        # ---- 層3: surprise に応じ rate を微調整(有界・決定的) ----
        surprise2 = target - mu2
        mu3 = mu3 + 0.01 * (abs(surprise2) - 1.0)
        if mu3 > 4.0:
            mu3 = 4.0
        elif mu3 < -4.0:
            mu3 = -4.0

        mu1_out.append(mu1)
        vol_out.append(math.exp(mu2))             # 層2 ボラティリティ(常に正・scene 用)。
        var1_out.append(1.0 / pi1)                # 層1 事後分散=1/π1(常に正・quality 用)。

    return HgfTrajectory(
        mu1=tuple(mu1_out),
        volatility=tuple(vol_out),
        var1=tuple(var1_out),
    )


# ===========================================================================
# B) 持続性特徴(slow nominal EMA + 逸脱の漏れ積分)
# ===========================================================================

@dataclass(frozen=True)
class PersistenceTrajectory:
    """持続性特徴の軌跡。

    value   : 各ステップの持続逸脱量(非負・nominal からの逸脱の漏れ積分)。len == 入力長。
    nominal : 各ステップの nominal 水準推定(遅い EMA)。len == 入力長。
    """

    value: tuple
    nominal: tuple


def default_persistence_params() -> "_PersistenceParams":
    """既定の持続性パラメータ(決定的・nominal 水準を含む)。

    .nominal 属性で nominal 水準を取り出せる(平坦テスト用)。
    gain/leak は漏れ積分の蓄積・減衰率。持続的逸脱でのみ正に蓄積し、平坦・nominal では ≈0、
    単発スパイクは小さい(ADR 0019 決定1・機構)。
    """
    return _PersistenceParams(
        nominal=0.5,
        gain=0.2,
        leak=0.1,
        deadband=0.0,
        cap=10.0,
        nominal_ema_alpha=0.05,
        nominal_init=0.5,
    )


@dataclass(frozen=True)
class _PersistenceParams:
    """持続性パラメータ(.nominal で nominal 水準を公開する dict 風レコード)。"""

    nominal: float
    gain: float
    leak: float
    deadband: float
    cap: float
    nominal_ema_alpha: float
    nominal_init: float


def persistence(signal_sequence, params) -> PersistenceTrajectory:
    """信号列の持続逸脱量を漏れ積分で計算する(ADR 0019 決定1・持続性特徴)。

    決定的。逸脱 dev = max(0, |u - nominal| - deadband) を漏れ積分:
        acc <- clip(acc + gain*dev - leak*acc, 0, cap)
    逸脱が続く限り acc は漸近値 gain*dev/leak へ近づくため、長く続く逸脱ほど・持続するほど
    大きくなる。単発スパイクは1ステップ蓄積後に leak で減衰し小さい。平坦・nominal は
    dev=0 で acc → 0。nominal は params が固定で与える(slow EMA は nominal 推定の報告用)。

    Args:
        signal_sequence: scene 診断信号の float 列。
        params: _PersistenceParams(default_persistence_params() 形式)。

    Returns:
        PersistenceTrajectory(.value, .nominal)。長さは入力列長に一致。
    """
    p = params
    nominal = float(p.nominal)
    gain = float(p.gain)
    leak = float(p.leak)
    deadband = float(p.deadband)
    cap = float(p.cap)
    ema_alpha = float(p.nominal_ema_alpha)
    ema = float(p.nominal_init)

    acc = 0.0
    value_out = []
    nominal_out = []
    for raw in signal_sequence:
        u = float(raw)

        # nominal 推定(遅い EMA・報告用)。
        ema = ema + ema_alpha * (u - ema)

        # nominal からの逸脱(deadband 内は無視)。
        dev = abs(u - nominal) - deadband
        if dev < 0.0:
            dev = 0.0

        # 漏れ積分(持続するほど蓄積・平坦 nominal では減衰)。
        acc = acc + gain * dev - leak * acc
        if acc < 0.0:
            acc = 0.0
        elif acc > cap:
            acc = cap

        value_out.append(acc)
        nominal_out.append(ema)

    return PersistenceTrajectory(value=tuple(value_out), nominal=tuple(nominal_out))


# ===========================================================================
# C) 3クラス分類(STABLE / CHANGING / DEGRADING)
# ===========================================================================

def classify_scene(features, params) -> str:
    """feature(水準/ボラティリティ/持続逸脱)を閾値で v1.4 scene regime に分類する。

    判定構造(ADR 0019 決定1・テストが閾値を与える):
      1) 低水準(level < level_low)→ DEGRADING(安定的に劣化していても STABLE にしない)。
      2) 高ボラ(volatility > vol_high)or 持続逸脱大(persistence > persist_high)→ CHANGING
         (HGF 層2 が持続的変化を捉えた / 平坦・非nominal の見逃しを CHANGING 側へ救う)。
      3) いずれも無し → STABLE(変化兆候も下降兆候も無い)。
    閾値の向きは厳密 `>`(vol_high / persist_high)・厳密 `<`(level_low)。境界ちょうどは
    CHANGING/DEGRADING 側に倒さない(テストの境界契約)。決定的。

    Args:
        features: {"level": float, "volatility": float, "persistence": float}。
        params:   閾値 dict({"vol_high","persist_high","level_low"})。

    Returns:
        v1.4 scene ラベル(STABLE / CHANGING / DEGRADING)。
    """
    level = float(features["level"])
    volatility = float(features["volatility"])
    persist = float(features["persistence"])

    vol_high = float(params["vol_high"])
    persist_high = float(params["persist_high"])
    level_low = float(params["level_low"])

    # 1) 低水準 → DEGRADING(安定的に低くても STABLE と取り違えない)。
    if level < level_low:
        return DEGRADING

    # 2) 高ボラ or 持続逸脱大 → CHANGING(持続的非定常の検出・見逃し救済)。
    if volatility > vol_high or persist > persist_high:
        return CHANGING

    # 3) 変化兆候・下降兆候なし → STABLE。
    return STABLE


# ===========================================================================
# D) 学習可能パラメータ予算(U24・F-014 連携)
# ===========================================================================

#: 学習可能(fit で更新される連続値)パラメータの名前リスト(ADR 0019 決定2 / 0025 決定3)。
#: 本実装の fit が実際に更新するのは regime 閾値3個(vol_high,persist_high,level_low)のみで、
#: HGF param(κ1,κ2,ω1,ω2,ω3,obs_noise)は性質テストを満たす既定値で固定する(fit は探索しない)。
#: U24「学習可能=fit で更新される連続値のみ計数」に厳密に従い、固定の HGF param・初期 belief
#: (mu*_0,pi1_0)・固定の集約/EMA 係数は学習可能 param に**含めない**。よって 3 個
#: (ADR 0025 決定3「scene=3」と一致)。3 ≪ 予算 100(200×0.5)で予算は binding でない。
#: 個数の厳密値は F-010 契約(test_F010_budget)で実装裁量(1 件以上・予算内)に委ねられている。
_LEARNABLE_PARAM_NAMES = (
    "vol_high",
    "persist_high",
    "level_low",
)


def learnable_param_names() -> list:
    """学習可能パラメータの名前リスト(U24: 学習可能のみ計数・固定定数は含めない)。

    過学習ガード(F-014-1)に渡す param_count を得る手段。fit で更新される連続値
    (HGF param + 学習する regime 閾値)だけを数える。
    """
    return list(_LEARNABLE_PARAM_NAMES)


def learnable_param_count() -> int:
    """学習可能パラメータの個数(== len(learnable_param_names()))。"""
    return len(_LEARNABLE_PARAM_NAMES)


# ===========================================================================
# E) 学習(fit)+ 学習済みパラメータ
# ===========================================================================

@dataclass(frozen=True)
class _SceneParams:
    """fit が返す学習済みパラメータ(end-to-end に渡せる形)。

    hgf       : HGF パラメータ dict。
    persist   : 持続性パラメータ(_PersistenceParams)。
    thresholds: regime 判定閾値 dict({"vol_high","persist_high","level_low"})。

    learnable_param_count() で学習可能 param 数を取り出せる(== scene.learnable_param_count()
    と同数=学習対象は固定・fit が param を増やさない)。
    """

    hgf: dict
    persist: "_PersistenceParams"
    thresholds: dict

    def learnable_param_count(self) -> int:
        """学習可能パラメータ数(学習対象は固定リストと同数)。"""
        return learnable_param_count()


#: fit の閾値探索グリッド(決定的・座標降下の候補値)。ボラティリティは HGF 層2 の
#: exp(μ2) スケール、持続逸脱は漏れ積分スケール、水準は信号スケールに合わせた候補。
_VOL_HIGH_GRID = (0.005, 0.01, 0.02, 0.04, 0.08)
_PERSIST_HIGH_GRID = (0.1, 0.2, 0.4, 0.8, 1.2)
_LEVEL_LOW_GRID = (0.2, 0.25, 0.3, 0.35, 0.4)


def _features_for_sequence(signal_sequence, hgf_params, persist_params):
    """信号列から各ステップの (level, volatility, persistence) 特徴列を作る(決定的)。"""
    htraj = hgf_filter(signal_sequence, hgf_params)
    ptraj = persistence(signal_sequence, persist_params)
    feats = []
    for level, vol, pers in zip(htraj.mu1, htraj.volatility, ptraj.value):
        feats.append({"level": level, "volatility": vol, "persistence": pers})
    return feats


def fit(practice_data) -> "_SceneParams":
    """練習データ上で regime 閾値を決定的に学習する(ADR 0019 決定3・乱数なし)。

    HGF / 持続性パラメータは既定値(fit 前初期値)から開始し、regime 閾値
    (vol_high / persist_high / level_low)を**決定的な座標降下**で練習データの分類正解率が
    最大になる組へ選ぶ。同点は固定グリッド順で最小候補を選ぶ(決定的 tie-break)。乱数・時刻
    無しのため、同じ練習データで2回 fit すると同一 learned_params(再現性 F-004-2)。

    学習可能 param 数は固定(learnable_param_count())。fit は param を増やさない(予算を
    後から食い破らない)。HGF param 自体の探索は本実装では既定値固定(性質テストを満たす値)
    とし、閾値のみ学習する(学習対象=固定リスト・count は不変)。

    Args:
        practice_data: [{"signal": [float,...], "gt": ["STABLE",...]}, ...] の列。

    Returns:
        _SceneParams(学習済み・end-to-end / classify_sequence に渡せる)。
    """
    hgf_params = default_hgf_params()
    persist_params = default_persistence_params()

    # 各サンプルの特徴列と gt を一度だけ計算(決定的)。
    samples = []
    for sample in practice_data:
        feats = _features_for_sequence(sample["signal"], hgf_params, persist_params)
        gt = list(sample["gt"])
        samples.append((feats, gt))

    def accuracy(thresholds):
        correct = 0
        total = 0
        for feats, gt in samples:
            for f, label in zip(feats, gt):
                total += 1
                if classify_scene(f, thresholds) == label:
                    correct += 1
        if total == 0:
            return 0.0
        return correct / total

    # 決定的座標降下: 各閾値を順に固定グリッド上で走査し正解率最大の候補へ移す。
    # 同点は「現在値維持」優先、未設定時はグリッド先頭(最小)。固定回数で収束(乱数なし)。
    best = {
        "vol_high": _VOL_HIGH_GRID[0],
        "persist_high": _PERSIST_HIGH_GRID[0],
        "level_low": _LEVEL_LOW_GRID[0],
    }
    grids = {
        "vol_high": _VOL_HIGH_GRID,
        "persist_high": _PERSIST_HIGH_GRID,
        "level_low": _LEVEL_LOW_GRID,
    }
    # 2 パスの座標降下(決定的・有界)。
    for _ in range(2):
        for key in ("level_low", "vol_high", "persist_high"):
            best_acc = accuracy(best)
            best_val = best[key]
            for cand in grids[key]:
                trial = dict(best)
                trial[key] = cand
                acc = accuracy(trial)
                # 厳密 `>` のみ採用 → 同点は既存値維持(決定的 tie-break)。
                if acc > best_acc:
                    best_acc = acc
                    best_val = cand
            best[key] = best_val

    return _SceneParams(
        hgf=dict(hgf_params),
        persist=persist_params,
        thresholds=dict(best),
    )


# ===========================================================================
# F) end-to-end(信号列 → regime 列)
# ===========================================================================

def classify_sequence(signal_sequence, params) -> list:
    """信号列を HGF → 持続性 → 分類で各ステップの v1.4 scene regime 列に変換する。

    決定的(乱数・時刻なし)。同じ入力列 + 同じ params で2回とも同一の regime 列を返す
    (再現性 F-004-2 を end-to-end に適用)。params は fit の返り値(_SceneParams)を渡せる。

    Args:
        signal_sequence: scene 診断信号の float 列。
        params: _SceneParams(fit の返り値)。

    Returns:
        各ステップの v1.4 scene ラベル列(STABLE / CHANGING / DEGRADING)。長さは入力長に一致。
    """
    feats = _features_for_sequence(signal_sequence, params.hgf, params.persist)
    return [classify_scene(f, params.thresholds) for f in feats]
