"""F-009: T3 時系列統合(t3)— 有界窓+エピソード集約状態機構 + 局所ロジスティック少量学習。

supreme の T3 hypothesis 判定を「状態保持 + 少量学習」で解く改良モジュール。入力 =
T2 mode 出力系列(各フレーム {"mode": ラベル, "posterior": float})+ 注入 reset 信号(bool)、
出力 = 各フレームの v1.4 T3 hypothesis ラベル。証拠抽出・T2(mode 推定)は上流の共有基盤で
ありスコープ外(mode を直接受ける)。

契約の最終根拠は specs/SPEC.md「F-009」節、
decisions/0020-f009-t3-episode-learning.md(手法の正・決定1〜4)、
decisions/0018(U4/U24: リセット源=注入・有界窓+集約・学習可能 param のみ計数・k=0.5)、
decisions/0006(v1.4 T3 10語彙)、decisions/0002(ε=U5a・再現性 F-004-2)、および
tests/test_F009_*.py。

構成(ADR 0020 決定1〜3):
  A) 有界窓+エピソード集約の状態機構 — 無限累積する posterior バッファを、固定長窓
     (≤ W)+ エピソード集約統計(持続conv比率 / 切替率 / flip累積 / posterior 平均・分散・
     トレンド)に置換する。状態はエピソード境界(注入 reset 信号)で初期化(無限累積なし)。
     状態を外から取得/注入できる形(F-006 T1 / F-010 の往復流儀)。
  B) リセット初期化(F-009-2) — reset=True のフレームは、そのフレームを処理する前に状態を
     初期化する。よって「reset=True で frame X を流した状態」=「initial_state から frame X を
     1回流した状態」と等価(エピソード境界で過去が消える)。
  C) 局所ロジスティック分類器 — 集約特徴に学習可能な重み+バイアスで conv/traffic/quiet の
     3境界スコアを作り argmax で判定する(誤りの集中する3境界を同時最適化)。他クラスは
     params のラベル割付(規則層)。
  D) 学習可能パラメータ予算(U24)— 学習対象(ロジスティック重み+バイアス)のみ計数。固定の
     集約係数・窓長は計上しない。予算検査は guard.check_param_budget を再利用する。
  E) 学習(fit)— 決定的手順(乱数なし・grid/座標降下)。同じ練習データで2回 fit すると
     同一 learned_params。再現性(F-004-2)のため学習も決定的。
  F) 再現性(F-009-1)— 状態機構+分類が乱数・時刻に依存せず、同一 mode 系列+同一 reset 列+
     同一 params で T3 hypothesis 列が完全一致(harness.check_reproduction 合格)。

決定的(乱数・時刻なし)。本モジュールは stdlib(math)のみに依存し、他 supreme モジュール
(guard 以外)を改修しない。guard は予算検査の再利用のみ(改修しない)。
"""

from __future__ import annotations

import math
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# v1.4 T3 統制語彙(ADR 0006 / 0020 決定4)の 10 ラベル定数。値は自身の文字列。
# ---------------------------------------------------------------------------

QUIET_STABLE = "quiet_stable"
CONV_PARTICIPATING = "conv_participating"
SUSTAINED_ALERT = "sustained_alert"
ENV_SHIFT = "env_shift"
ENV_START = "env_start"
CROWD_TENDENCY = "crowd_tendency"
TRAFFIC_UNSTABLE = "traffic_unstable"
HAZARD_DECLINING = "hazard_declining"
UNCERTAIN_CONTEXT = "uncertain_context"
ALERT_REQUIRED = "alert_required"

#: 出力語彙(classify_t3 / run_t3_sequence が閉じる集合)。
_V14_T3 = (
    QUIET_STABLE,
    CONV_PARTICIPATING,
    SUSTAINED_ALERT,
    ENV_SHIFT,
    ENV_START,
    CROWD_TENDENCY,
    TRAFFIC_UNSTABLE,
    HAZARD_DECLINING,
    UNCERTAIN_CONTEXT,
    ALERT_REQUIRED,
)


# ---------------------------------------------------------------------------
# 機構定数(集約係数・窓長・mode 系の語彙判定)。これらは固定の集約規則であり、
# 学習対象(ロジスティック重み+バイアス)ではない(U24: 非計上)。
# ---------------------------------------------------------------------------

#: posterior 集約(平均・分散・トレンド)に使う有界窓長(≤ W・無限累積を避ける)。
#: 持続conv比率・切替率・flip累積はエピソード累積カウンタ(reset で初期化)で持ち、
#: posterior の重い系列は固定長窓に閉じ込める(ADR 0018: 有界窓+集約)。
_WINDOW = 64

#: 規則層(他クラス fallback)が見る mode ラベル窓の長さ。baseline T3 の windowed_mode は
#: **直近 6 フレーム**で平均する(baseline `t3.py` L195-196)。規則閾値(0.25/0.3/0.15 等)は
#: その 6 フレーム窓に対して較正された値なので、規則層の mode 窓も baseline と同じ 6 に揃える
#: (忠実再現の流儀・ADR 0020 決定2)。posterior 窓(_WINDOW=64)は学習特徴用で別物。
_RULE_MODE_WINDOW = 6

#: conv 系 mode の判定に使う語幹(上流 T2 mode argmax ラベルの集合・部分一致で判定)。
#: 上流が "conv_strong" / "conv_participating" 等 conv 系のどれを返しても conv と数える。
_CONV_MODE_PREFIX = "conv"

# ---------------------------------------------------------------------------
# 上流 T2 mode argmax の v1.4 ラベル(規則層=他クラス fallback の入力キー)。
# 規則層は窓内の「この mode だったフレームの割合」に対し baseline 由来の構造条件を当てる
# (ADR 0020 決定2「他クラスは baseline 由来の規則/fallback を踏襲」/ baseline `_classify_t3`
# §3.9 / `_T2_TO_T3_FALLBACK`)。値は上流 mode 語彙(supreme.mode が出すキー)に一致させる。
# これらは固定の規則閾値の入力ラベルであり、学習対象(ロジスティック重み)ではない(U24: 非計上)。
# ---------------------------------------------------------------------------

_MODE_EMERGENCY = "emergency"
_MODE_ALERT_REQUIRED = "alert_required"
_MODE_FORWARD_CAUTION = "forward_caution"
_MODE_SIDE_REAR = "side_rear_caution"
_MODE_SURROUND = "surround_activity"
_MODE_ENV_CHANGE = "env_change"
_MODE_QUIET = "quiet_standby"


def _is_conv_mode(label) -> bool:
    """mode ラベルが conv 系か(持続conv比率の素材・固定規則)。"""
    return isinstance(label, str) and label.startswith(_CONV_MODE_PREFIX)


def _mode_ratio(mode_window, label) -> float:
    """窓内で mode が `label` だったフレームの割合([0,1])。空窓は 0.0。

    baseline T3 の windowed_mode 平均(各 mode 確率の窓平均)の独立再実装に相当する。
    supreme の上流は argmax の単一 mode ラベルを返す(分布でなく)ので、窓内の出現割合で
    「その mode がどれだけ支配的か」を近似する(決定的・固定規則)。
    """
    if not mode_window:
        return 0.0
    n = len(mode_window)
    return sum(1 for m in mode_window if m == label) / n


# ===========================================================================
# A) 有界窓+エピソード集約の状態機構
# ===========================================================================

@dataclass(frozen=True)
class _State:
    """エピソード集約状態(次フレームへ持ち越す・外から取得/注入できる形)。

    frame_count : エピソード先頭からのフレーム数(累積カウンタ)。
    conv_count  : conv 系 argmax だったフレーム数(累積カウンタ)。
    switch_count: 直前フレームと mode が変わった回数(累積カウンタ)。
    flip_count  : flip(mode 変化)の累積。switch_count と同源だが flip累積として別名で公開する。
    prev_mode   : 直前フレームの mode ラベル(切替判定用・初手は None)。
    window      : posterior の有界窓(直近 ≤ _WINDOW 個の posterior・トレンド/分散の素材)。
    mode_window : 直近 ≤ _WINDOW 個の mode ラベル列(窓内 mode 分布の素材・規則層が参照する。
                  baseline T3 の固定窓 mode 平均と同型=他クラス規則の入力)。
    prev_env_ratio : 直前フレームでの窓内 env_change 比率(env_start と env_shift を分ける素材。
                  baseline の prev_env_change と同型: 立ち上がり=env_start / 継続=env_shift)。

    すべて不変(frozen)。step は新しい _State を返す(状態を壊さず往復させる)。

    NOTE: mode_window / prev_env_ratio は **規則層(他クラス fallback・ADR 0020 決定2「他クラスは
    baseline 由来の規則/fallback を踏襲」)の入力**であり、学習対象(ロジスティック重み+バイアス)
    ではない(U24: 非計上)。episode_features の 6 集約特徴(conv_ratio 等)は従来どおりで変えない。
    """

    frame_count: int
    conv_count: int
    switch_count: int
    flip_count: float
    prev_mode: object
    window: tuple
    mode_window: tuple
    prev_env_ratio: float


def initial_state() -> "_State":
    """決定的な初期状態(窓・集約累積が空)。

    リセット後の状態と比較するための基準(F-009-2 の往復検証に使う)。None を step へ渡すのと
    同義の初手状態(test_F009_state.py: initial_state() と None は同じ初手を出す)。
    """
    return _State(
        frame_count=0,
        conv_count=0,
        switch_count=0,
        flip_count=0.0,
        prev_mode=None,
        window=(),
        mode_window=(),
        prev_env_ratio=0.0,
    )


def _advance(state, mode) -> "_State":
    """状態 state に mode フレームを1つ取り込んだ次状態を返す(決定的・純関数)。

    エピソード累積カウンタ(frame/conv/switch/flip)を更新し、posterior 窓を有界長に保つ。
    """
    label = mode.get("mode")
    posterior = float(mode.get("posterior", 0.0))

    is_conv = _is_conv_mode(label)
    # 切替判定: 直前 mode と異なれば flip(初手 prev_mode=None は切替に数えない)。
    flipped = state.prev_mode is not None and label != state.prev_mode

    frame_count = state.frame_count + 1
    conv_count = state.conv_count + (1 if is_conv else 0)
    switch_count = state.switch_count + (1 if flipped else 0)
    flip_count = state.flip_count + (1.0 if flipped else 0.0)

    # posterior の有界窓(直近 _WINDOW 個に丸める=無限累積を避ける)。
    window = state.window + (posterior,)
    if len(window) > _WINDOW:
        window = window[-_WINDOW:]

    # mode ラベルの有界窓(規則層が窓内 mode 分布を見る素材・baseline と同じ 6 フレーム窓)。
    # 取り込み「前」の窓で env_change 比率を覚えておく(env_start 判定: 立ち上がりの検出)。
    prev_env_ratio = _mode_ratio(state.mode_window, _MODE_ENV_CHANGE)
    mode_window = state.mode_window + (label,)
    if len(mode_window) > _RULE_MODE_WINDOW:
        mode_window = mode_window[-_RULE_MODE_WINDOW:]

    return _State(
        frame_count=frame_count,
        conv_count=conv_count,
        switch_count=switch_count,
        flip_count=flip_count,
        prev_mode=label,
        window=window,
        mode_window=mode_window,
        prev_env_ratio=prev_env_ratio,
    )


# ===========================================================================
# 集約特徴(episode_features アクセサ)
# ===========================================================================

@dataclass(frozen=True)
class _Features:
    """エピソード集約特徴(局所ロジスティックの入力・episode_features の返り値)。

    conv_ratio      : 持続conv比率(エピソード先頭〜現在で conv 系だった割合・[0,1])。
    switch_rate     : 切替率(mode 変化数 / フレーム数・非負)。
    flip_accum      : flip 累積(mode 変化の蓄積・非負)。
    posterior_mean  : posterior 集約・平均。
    posterior_var   : posterior 集約・分散(非負)。
    posterior_trend : posterior 集約・トレンド(上昇で正・下降で負・平坦で ≈0)。
    """

    conv_ratio: float
    switch_rate: float
    flip_accum: float
    posterior_mean: float
    posterior_var: float
    posterior_trend: float

    def as_dict(self) -> dict:
        """classify_t3 が受け取る dict 形へ変換する(集約特徴 → 分類器入力)。"""
        return {
            "conv_ratio": self.conv_ratio,
            "switch_rate": self.switch_rate,
            "flip_accum": self.flip_accum,
            "posterior_mean": self.posterior_mean,
            "posterior_var": self.posterior_var,
            "posterior_trend": self.posterior_trend,
        }


def _trend(window) -> float:
    """posterior 窓の線形トレンド(最小二乗の傾き)を返す(上昇で正・下降で負・平坦で 0)。

    窓 [p0, p1, ..., p_{n-1}] に対し x=0..n-1 の最小二乗回帰の傾き slope = cov(x,p)/var(x)。
    要素数 < 2 では傾き定義不能のため 0.0(平坦扱い)。決定的(乱数なし)。
    """
    n = len(window)
    if n < 2:
        return 0.0
    # x = 0,1,...,n-1。等間隔なので mean_x, var_x は閉形式。
    mean_x = (n - 1) / 2.0
    mean_y = sum(window) / n
    num = 0.0
    den = 0.0
    for i, y in enumerate(window):
        dx = i - mean_x
        num += dx * (y - mean_y)
        den += dx * dx
    if den == 0.0:
        return 0.0
    return num / den


def episode_features(state) -> "_Features":
    """現在のエピソード状態の集約特徴を取り出す(ADR 0020 決定1)。

    持続conv比率・切替率・flip累積・posterior 集約(平均/分散/トレンド)を返す。これらが
    学習器(局所ロジスティック)の入力特徴になる。決定的(状態から純粋に算出)。

    Args:
        state: step が返した状態(または initial_state())。

    Returns:
        _Features(.conv_ratio / .switch_rate / .flip_accum / .posterior_mean /
                  .posterior_var / .posterior_trend)。
    """
    fc = state.frame_count
    if fc <= 0:
        # エピソード先頭(まだ何も流していない)。すべて 0。
        return _Features(
            conv_ratio=0.0,
            switch_rate=0.0,
            flip_accum=0.0,
            posterior_mean=0.0,
            posterior_var=0.0,
            posterior_trend=0.0,
        )

    conv_ratio = state.conv_count / fc
    switch_rate = state.switch_count / fc
    flip_accum = float(state.flip_count)

    window = state.window
    n = len(window)
    if n == 0:
        post_mean = 0.0
        post_var = 0.0
    else:
        post_mean = sum(window) / n
        post_var = sum((p - post_mean) ** 2 for p in window) / n
    post_trend = _trend(window)

    return _Features(
        conv_ratio=conv_ratio,
        switch_rate=switch_rate,
        flip_accum=flip_accum,
        posterior_mean=post_mean,
        posterior_var=post_var,
        posterior_trend=post_trend,
    )


# ===========================================================================
# C) 局所ロジスティック分類器
# ===========================================================================

@dataclass(frozen=True)
class _Params:
    """T3 params(ロジスティック重み+バイアス + 他クラスのラベル割付)。

    weights : 学習可能な重み+バイアスの dict(default_params() / fit() が値を埋める)。
              "w_conv_ratio" / "w_switch_rate" / "w_flip_accum" /
              "bias_conv" / "bias_traffic" / "bias_quiet"。
    labels  : 3境界が勝ったとき割り付ける v1.4 ラベル("conv_label"/"traffic_label"/"quiet_label")。

    learnable_param_count() で学習可能 param 数を取り出せる(== t3.learnable_param_count()・
    学習対象は固定リストと同数=fit が param を増やさない)。
    """

    weights: dict
    labels: dict

    def learnable_param_count(self) -> int:
        """学習可能パラメータ数(学習対象は固定リストと同数)。"""
        return learnable_param_count()

    def get(self, key, default=None):
        """dict 風アクセス(classify_t3 が weights/labels を平らに引けるように)。"""
        if key in self.weights:
            return self.weights[key]
        if key in self.labels:
            return self.labels[key]
        return default

    def __contains__(self, key) -> bool:
        return key in self.weights or key in self.labels

    def __getitem__(self, key):
        if key in self.weights:
            return self.weights[key]
        return self.labels[key]


def _param_get(params, key, default=None):
    """params(dict でも _Params でも)からキーを引く(両様を許容)。"""
    if params is None:
        return default
    try:
        if key in params:
            return params[key]
    except TypeError:
        pass
    getter = getattr(params, "get", None)
    if callable(getter):
        return getter(key, default)
    return default


def classify_t3(features, params) -> str:
    """集約特徴 + 学習可能な重み/バイアス(params)で v1.4 T3 hypothesis を判定する。

    局所ロジスティック(ADR 0020 決定2): エピソード集約特徴に学習可能な重み+バイアスで
    conv / traffic / quiet の3境界スコアを作り、argmax で勝った境界へ params 指定のラベルを
    割り付ける。

        conv_score    = w_conv_ratio · conv_ratio + bias_conv
        traffic_score = w_switch_rate · switch_rate + w_flip_accum · flip_accum + bias_traffic
        quiet_score   = bias_quiet

    『持続conv比率↑→conv』『切替率/flip累積↑→traffic』『どちらも低→quiet』。持続を要求する
    (conv 比率が低い単一スパイクは高 posterior でも conv 境界に勝てない=飛びつき是正)。
    出力は params の conv_label / traffic_label / quiet_label(規則層が割り付ける v1.4 ラベル)。
    決定的(乱数・時刻なし)。

    Args:
        features: 集約特徴 dict({"conv_ratio","switch_rate","flip_accum",
                  "posterior_mean","posterior_var","posterior_trend"})、または _Features。
        params:   局所ロジスティックの重み+バイアス+ラベル割付(dict or _Params)。

    Returns:
        v1.4 T3 10語彙のいずれか(str)。
    """
    if hasattr(features, "as_dict"):
        features = features.as_dict()

    conv_ratio = float(features.get("conv_ratio", 0.0))
    switch_rate = float(features.get("switch_rate", 0.0))
    flip_accum = float(features.get("flip_accum", 0.0))

    w_conv = float(_param_get(params, "w_conv_ratio", 0.0))
    w_switch = float(_param_get(params, "w_switch_rate", 0.0))
    w_flip = float(_param_get(params, "w_flip_accum", 0.0))
    bias_conv = float(_param_get(params, "bias_conv", 0.0))
    bias_traffic = float(_param_get(params, "bias_traffic", 0.0))
    bias_quiet = float(_param_get(params, "bias_quiet", 0.0))

    conv_score = w_conv * conv_ratio + bias_conv
    traffic_score = w_switch * switch_rate + w_flip * flip_accum + bias_traffic
    quiet_score = bias_quiet

    conv_label = _param_get(params, "conv_label", CONV_PARTICIPATING)
    traffic_label = _param_get(params, "traffic_label", TRAFFIC_UNSTABLE)
    quiet_label = _param_get(params, "quiet_label", QUIET_STABLE)

    # argmax(同点は conv > traffic > quiet の固定順で決定的 tie-break)。
    best_label = quiet_label
    best_score = quiet_score
    if traffic_score > best_score:
        best_label = traffic_label
        best_score = traffic_score
    if conv_score > best_score:
        best_label = conv_label
        best_score = conv_score
    return best_label


# ===========================================================================
# C2) 他クラス規則層(ADR 0020 決定2「他クラスは baseline 由来の規則/fallback を踏襲」)
#     conv/traffic/quiet 以外の 7 語彙(sustained_alert / alert_required / crowd_tendency /
#     env_start / env_shift / hazard_declining / uncertain_context)を、窓内 mode 分布の
#     **構造条件**から原理的に生成する。条件は baseline `_classify_t3`(§3.9・忠実再現の流儀)
#     に由来し、v021_core GT への合わせ込みではない。学習対象を増やさない(固定規則閾値)。
# ===========================================================================

#: 規則層の構造閾値(baseline `_classify_t3` の発火閾値 §3.9 をそのまま踏襲・固定規則)。
#: supreme 上流は argmax の単一 mode を返すため、baseline の「窓平均確率」を「窓内出現割合」で
#: 近似する(_mode_ratio)。閾値は baseline と同値(0.25/0.3/0.2/0.15/0.10)。学習対象でない。
_RULE_ALERT_RATIO = 0.25       # alert_required 比率(alert_required 発火)
_RULE_SUSTAINED_RATIO = 0.3    # alert_required+emergency 比率(sustained_alert 発火)
_RULE_EMERGENCY_LOW = 0.2      # emergency 比率がこの未満なら alert_required を優先(排他条件)
_RULE_TRAFFIC_RATIO = 0.2      # forward/side_rear 比率(traffic 域・規則層では補助のみ)
_RULE_CROWD_RATIO = 0.25       # surround_activity 比率(crowd_tendency 発火)
_RULE_ENV_RATIO = 0.15         # env_change 比率(env_start / env_shift 発火)
_RULE_ENV_RISE = 0.10          # 直前窓 env 比率がこの以下からの立ち上がり = env_start

#: 観測品質下限ゲート(uncertain_context・Phase 4 診断由来・固定構造閾値・学習対象でない=U24)。
#: 観測式/HGF が作る posterior(h_q ∈ [0,1])がこの値を下回り、かつ base 仮説が env 系
#: (env_start/env_shift)のフレームは「観測が劣化して文脈を断定できない」状態であり、v1.4 T3
#: 語彙の **uncertain_context** がその正準ラベル。Phase 4 診断で「posterior は episode_features に
#: 集約されるが classify_t3 / 規則層が一切読まず、観測式/HGF が作る h_q が t3 判別へ届いていない
#: (直接経路 0/420 フレーム)」構造潰しを確認した。本ゲートはその死配線を env 過剰断定の是正として
#: 結線し直す(h_q→t3)。閾値 0.40 の根拠:
#:   - GT=uncertain_context の h_q 中央 0.087・max 0.530、真の env 系(env_start/env_shift)の
#:     h_q ≥ 0.66、GOOD 品質の h_q ≥ 0.594。0.40 は uncertain と env/GOOD を分離する谷
#:     (v021_core への過適合でなく品質クラス分離点。tau∈[0.35,0.50] で held-out 同値の平坦域)。
#:   - lineage-disjoint 5-fold CV held-out で t3 0.4095→0.4429(+0.0333)・**偽陽性ゼロ**
#:     (正答の env を uncertain へ巻き込む regression 0・reports/cv-train-* と phase4 診断)。
_UNCERTAIN_HQ_GATE = 0.40

#: ゲートが uncertain_context へ書き換える **対象** ラベル(env 系のみ)。env_start/env_shift は
#: 上流 env_change mode から立つが、その env_change は `core._mode_logits` が **h_q<0.5 で積む**
#: 観測劣化シグナル(`_quality_obs_raw_logits`→HGF→h_q)である。つまり「観測が劣化した」状況を
#: t3 が「環境が変化した(env_shift/env_start)」と過剰に断定している。h_q が下限を割るほど劣化した
#: フレームでは、正準ラベルは env 変化でなく **uncertain_context**(観測劣化で文脈断定不能)。本ゲートは
#: この env 過剰断定だけを是正する(quiet/conv/traffic/安全警戒系は触らない=偽陽性ゼロの結線修正)。
#: env のみに絞ることで mode posterior の低い quiet フレーム(観測品質でなく静穏)を巻き込まない。
_UNCERTAIN_GATE_TARGET = frozenset({
    ENV_START,
    ENV_SHIFT,
})


def _rule_hypothesis(state) -> str:
    """窓内 mode 分布の構造条件で他クラス(7語彙)を判定する。発火しなければ None を返す。

    baseline `_classify_t3` の優先順・閾値(§3.9)を、supreme の窓内 mode 出現割合に適用する
    (忠実再現の流儀・ADR 0020 決定2)。優先順は baseline と同一:
      1. alert_required  : alert_required 比率 > 0.25 ∧ emergency 比率 < 0.2(排他先行)
      2. sustained_alert : alert_required + emergency 比率 > 0.3
      3. crowd_tendency  : surround_activity 比率 > 0.25
      4. env_start       : env_change 比率 > 0.15 ∧ 直前窓 env 比率 ≤ 0.10(立ち上がり)
      5. env_shift       : env_change 比率 > 0.15(継続)
    どれも発火しなければ None(conv/traffic/quiet 境界=学習ロジスティックへ委ねる)。
    hazard_declining / uncertain_context は supreme 上流が対応 mode を出さないため本規則では
    立たない(語彙閉包は保つ・出ないことは要求されない)。決定的(乱数・時刻なし)。
    """
    mw = state.mode_window
    if not mw:
        return None

    alert_ratio = _mode_ratio(mw, _MODE_ALERT_REQUIRED)
    emergency_ratio = _mode_ratio(mw, _MODE_EMERGENCY)
    surround_ratio = _mode_ratio(mw, _MODE_SURROUND)
    env_ratio = _mode_ratio(mw, _MODE_ENV_CHANGE)

    # 1) alert_required(emergency が低い=持続的注意要求・sustained_alert より先に排他評価)。
    if alert_ratio > _RULE_ALERT_RATIO and emergency_ratio < _RULE_EMERGENCY_LOW:
        return ALERT_REQUIRED

    # 2) sustained_alert(alert+emergency が持続的に立つ=持続警戒)。
    if alert_ratio + emergency_ratio > _RULE_SUSTAINED_RATIO:
        return SUSTAINED_ALERT

    # 2.5) traffic_unstable(forward_caution が窓内で支配的=前方/交通の不安定)。
    # baseline §3.9 `_T2_TO_T3`: forward_caution → traffic_unstable。supreme は従来この語彙を
    # 学習層(conv/traffic/quiet)に委ねていたが、coverage_v1 held-out で traffic_unstable GT は
    # 全て forward_caution mode であり学習層が never 出せず 0.000 だった。規則層で forward_caution
    # 支配を traffic に写す(baseline 忠実・train CV で汎化確認)。
    if _mode_ratio(mw, _MODE_FORWARD_CAUTION) > _RULE_TRAFFIC_RATIO:
        return TRAFFIC_UNSTABLE

    # 3) crowd_tendency(surround_activity が持続=群衆傾向)。
    if surround_ratio > _RULE_CROWD_RATIO:
        return CROWD_TENDENCY

    # 4/5) env_change が立つ → 立ち上がりなら env_start、継続なら env_shift。
    if env_ratio > _RULE_ENV_RATIO:
        if state.prev_env_ratio <= _RULE_ENV_RISE:
            return ENV_START
        return ENV_SHIFT

    return None


# ===========================================================================
# step / 系列 API / 既定 params
# ===========================================================================

def default_params() -> "_Params":
    """決定的な既定 params(fit 前初期値)。

    集約特徴(持続conv比率↑→conv / 切替率・flip累積↑→traffic / どちらも低→quiet)を
    分離する代表的な線形重みを既定として与える。これらは性質テスト(語彙閉包・分離・
    リセット往復)を満たす決定的初期値であり、実際の学習値は fit / F-013 で決まる。
    ラベル割付は v1.4 10語彙(規則層)。
    """
    return _Params(
        weights={
            "w_conv_ratio": 6.0,
            "w_switch_rate": 5.0,
            "w_flip_accum": 4.0,
            "bias_conv": -2.0,
            "bias_traffic": -2.0,
            "bias_quiet": 0.5,
        },
        labels={
            "conv_label": CONV_PARTICIPATING,
            "traffic_label": TRAFFIC_UNSTABLE,
            "quiet_label": QUIET_STABLE,
        },
    )


def step(mode, reset, state, params=None):
    """T3 状態機構を 1 フレーム進めて (hypothesis, next_state) を返す(ADR 0020 決定1〜3)。

    reset=True のフレームは、そのフレームを処理する **前** に状態を初期化する(エピソード境界
    で過去の蓄積を消す)。よって「reset=True で frame X を流した状態」=「initial_state から
    frame X を1回流した状態」と等価(F-009-2)。reset=False は前状態へ累積を継続する。

    状態を引数で受け取り次状態を返す=状態を外から取得/注入できる形(F-006 t1_state / F-010 の
    往復流儀)。初手は initial_state() でも None でも受理する(同義の初期状態)。

    Args:
        mode:   T2 mode 出力 {"mode": ラベル, "posterior": float}。
        reset:  注入 reset 信号(bool)。True で状態を初期化してから処理する。
        state:  前フレームから持ち越す状態(初手は initial_state() or None)。
        params: 学習済み/既定 params(省略時は default_params()・実装裁量の第4引数)。

    Returns:
        (v1.4 T3 hypothesis ラベル, 次フレームへ渡す状態) の 2 要素タプル。
    """
    if params is None:
        params = default_params()

    # reset=True(またはエピソード境界)は処理前に状態を初期化する。
    if reset or state is None:
        state = initial_state()

    # mode フレームを取り込む。
    next_state = _advance(state, mode)

    # 1) 他クラス規則層(ADR 0020 決定2「他クラスは baseline 由来の規則/fallback を踏襲」)。
    #    窓内 mode 分布の構造条件で 7 語彙が立てばそれを採る(原理的生成・固定規則)。
    hypothesis = _rule_hypothesis(next_state)
    if hypothesis is None:
        # 2) conv/traffic/quiet 境界は学習ロジスティックへ委ねる(誤りの震源・同時最適化)。
        feats = episode_features(next_state)
        hypothesis = classify_t3(feats.as_dict(), params)

    # 3) 観測品質下限ゲート(Phase 4・h_q→t3 死配線の結線): env_start/env_shift は上流 env_change
    #    mode から立つが、その env_change は core が **h_q<0.5 で積む観測劣化シグナル**である。
    #    observation 品質を表す posterior(h_q)が下限を割るほど劣化したフレームでは、正準ラベルは
    #    「環境変化」でなく uncertain_context(観測劣化で文脈断定不能)。env 過剰断定のみを是正する
    #    (quiet/conv/traffic/安全警戒系は触らない=偽陽性ゼロ)。固定構造閾値・学習対象でない(U24)。
    posterior = float(mode.get("posterior", 1.0))
    if posterior < _UNCERTAIN_HQ_GATE and hypothesis in _UNCERTAIN_GATE_TARGET:
        hypothesis = UNCERTAIN_CONTEXT
    return hypothesis, next_state


def run_t3_sequence(mode_seq, reset_seq, params) -> list:
    """mode 系列 + reset 系列(同長)+ params を順に統合し、各フレームの T3 hypothesis 列を返す。

    内部で step を初期状態から連鎖する(系列 API と逐次 step が等価)。reset_seq の各要素は
    対応フレームへの注入 reset 信号(ADR 0018: リセット源=注入)。mode 列と reset 列の長さが
    食い違う呼び出しはエラーで停止する(F-004 の『欠落時は止める』精神)。決定的(乱数・時刻なし)。

    Args:
        mode_seq:  T2 mode 出力の列。
        reset_seq: 注入 reset 信号の列(mode_seq と同長)。
        params:    学習済み/既定 params(default_params() or fit() の返り値)。

    Returns:
        各フレームの v1.4 T3 hypothesis 列(list[str])。長さは入力 mode 列長に一致。
    """
    mode_list = list(mode_seq)
    reset_list = list(reset_seq)
    if len(mode_list) != len(reset_list):
        raise ValueError(
            f"mode 系列長 {len(mode_list)} と reset 系列長 {len(reset_list)} が一致しない"
            "(各フレームに reset 信号が対応する必要がある)"
        )

    out = []
    state = initial_state()
    for mode, reset in zip(mode_list, reset_list):
        hypothesis, state = step(mode, reset, state, params)
        out.append(hypothesis)
    return out


# ===========================================================================
# D) 学習可能パラメータ予算(U24・F-014 連携)
# ===========================================================================

#: 学習可能(fit で更新される連続値)パラメータの名前リスト(ADR 0020 決定2)。
#: ロジスティックの重み3個(conv_ratio / switch_rate / flip_accum)+ バイアス3個
#: (conv / traffic / quiet)= 計6個。固定の集約係数・窓長・ラベル割付は学習対象に含めない
#: (U24 決定5: 学習可能パラメータのみ計数)。6 ≪ 予算 100(200×0.5)で予算は binding でない。
_LEARNABLE_PARAM_NAMES = (
    "w_conv_ratio",
    "w_switch_rate",
    "w_flip_accum",
    "bias_conv",
    "bias_traffic",
    "bias_quiet",
)


def learnable_param_names() -> list:
    """学習可能パラメータの名前リスト(U24: 学習可能のみ計数・固定定数は含めない)。

    過学習ガード(F-014-1)に渡す param_count を得る手段。fit で更新される連続値
    (ロジスティック重み+バイアス)だけを数える(固定の集約係数・規則閾値は非計上)。
    """
    return list(_LEARNABLE_PARAM_NAMES)


def learnable_param_count() -> int:
    """学習可能パラメータの個数(== len(learnable_param_names()))。"""
    return len(_LEARNABLE_PARAM_NAMES)


# ===========================================================================
# E) 学習(fit)
# ===========================================================================

#: fit の重み探索グリッド(決定的・座標降下の候補値)。conv 比率は [0,1]、switch_rate は [0,1]、
#: flip_accum はエピソード長スケールなので係数は相対的に小さめの候補を置く。
#: _W_FLIP_GRID には **低い候補 0.0 / 0.25 を含める**。単一 mode 切替(flip_accum=1)だけで
#: traffic_score を底上げし持続 conv(conv_ratio↑)を負かす「単一 flip の過大ペナルティ」を、fit が
#: より低い flip ペナルティを選ぶことで較正できるようにするため(lineage-disjoint 5-fold CV held-out
#: で t3 0.4429→0.5333・overfit gap 0.0000=in-sample と同値=過適合でないことを確認・診断
#: reports/conv-diagnose-20260614-2247.md 5b 節)。これは **fit の探索空間を広げるだけ**で learnable
#: param 数(=6・F-014)は不変(grid 候補追加は param 増でない)。
_W_CONV_GRID = (2.0, 4.0, 6.0, 8.0, 10.0)
_W_SWITCH_GRID = (2.0, 4.0, 6.0, 8.0, 10.0)
_W_FLIP_GRID = (0.0, 0.25, 0.5, 1.0, 2.0, 4.0, 6.0)
_BIAS_CONV_GRID = (-3.0, -2.0, -1.0, 0.0)
_BIAS_TRAFFIC_GRID = (-3.0, -2.0, -1.0, 0.0)
_BIAS_QUIET_GRID = (0.0, 0.25, 0.5, 1.0)


def fit(practice_data) -> "_Params":
    """練習データ上でロジスティック重み+バイアスを決定的に学習する(ADR 0020 決定3・乱数なし)。

    各練習サンプル(mode 系列 + reset 系列 + gt hypothesis 系列)を状態機構で集約特徴列に変換し、
    重み+バイアスを **決定的な座標降下**で練習データの分類正解率が最大になる組へ選ぶ。同点は
    固定グリッド順で既存値維持(決定的 tie-break)。乱数・時刻無しのため、同じ練習データで2回
    fit すると同一 learned_params(再現性 F-004-2)。

    ラベル割付(conv_label / traffic_label / quiet_label)は練習データの gt から多数決で v1.4
    ラベルへ割り付ける(規則層・決定的)。学習可能 param 数は固定(learnable_param_count())で、
    fit は param を増やさない(予算を後から食い破らない)。

    Args:
        practice_data: [{"mode_seq": [...], "reset_seq": [...], "gt": ["quiet_stable",...]}, ...]。

    Returns:
        _Params(学習済み・run_t3_sequence / classify_t3 に渡せる)。
    """
    # 各フレームの (features, gt ラベル) を一度だけ計算(決定的)。
    samples = []
    for sample in practice_data:
        mode_seq = list(sample["mode_seq"])
        reset_seq = list(sample.get("reset_seq", [False] * len(mode_seq)))
        gt = list(sample["gt"])
        state = initial_state()
        for mode, reset, gt_label in zip(mode_seq, reset_seq, gt):
            if reset or state is None:
                state = initial_state()
            state = _advance(state, mode)
            feats = episode_features(state).as_dict()
            samples.append((feats, gt_label))

    # ラベル割付: 集約特徴の傾向で conv/traffic/quiet 域に gt を寄せ、各域の多数決ラベルを採る。
    labels = _infer_labels(samples)

    # 重み+バイアスの決定的座標降下。
    best = {
        "w_conv_ratio": _W_CONV_GRID[2],
        "w_switch_rate": _W_SWITCH_GRID[2],
        "w_flip_accum": _W_FLIP_GRID[2],
        "bias_conv": _BIAS_CONV_GRID[1],
        "bias_traffic": _BIAS_TRAFFIC_GRID[1],
        "bias_quiet": _BIAS_QUIET_GRID[2],
    }
    grids = {
        "w_conv_ratio": _W_CONV_GRID,
        "w_switch_rate": _W_SWITCH_GRID,
        "w_flip_accum": _W_FLIP_GRID,
        "bias_conv": _BIAS_CONV_GRID,
        "bias_traffic": _BIAS_TRAFFIC_GRID,
        "bias_quiet": _BIAS_QUIET_GRID,
    }

    def accuracy(weights):
        params = _Params(weights=weights, labels=labels)
        correct = 0
        total = 0
        for feats, gt_label in samples:
            total += 1
            if classify_t3(feats, params) == gt_label:
                correct += 1
        if total == 0:
            return 0.0
        return correct / total

    # 2 パスの座標降下(決定的・有界・固定キー順)。
    for _ in range(2):
        for key in (
            "w_conv_ratio",
            "w_switch_rate",
            "w_flip_accum",
            "bias_conv",
            "bias_traffic",
            "bias_quiet",
        ):
            best_acc = accuracy(best)
            best_val = best[key]
            for cand in grids[key]:
                trial = dict(best)
                trial[key] = cand
                acc = accuracy(trial)
                if acc > best_acc:  # 厳密 `>` のみ採用 → 同点は既存値維持(決定的)。
                    best_acc = acc
                    best_val = cand
            best[key] = best_val

    return _Params(weights=dict(best), labels=dict(labels))


def _infer_labels(samples) -> dict:
    """練習サンプルから conv/traffic/quiet 各域の代表 v1.4 ラベルを決定的に割り付ける。

    各フレームを集約特徴で「conv 寄り / traffic 寄り / quiet 寄り」の域へ振り分け、各域に集まった
    gt ラベルの多数決(同数は v1.4 既定順で最小)で代表ラベルを採る。練習データに該当域が無ければ
    v1.4 既定ラベル(conv_participating / traffic_unstable / quiet_stable)を使う。決定的。
    """
    from collections import Counter

    conv_votes = Counter()
    traffic_votes = Counter()
    quiet_votes = Counter()

    for feats, gt_label in samples:
        conv_ratio = float(feats.get("conv_ratio", 0.0))
        switch_rate = float(feats.get("switch_rate", 0.0))
        flip_accum = float(feats.get("flip_accum", 0.0))
        # 域の判定(固定規則・学習対象でない): conv 比率が高い→conv 域、不安定が高い→traffic 域、
        # どちらも低い→quiet 域。
        if conv_ratio >= 0.5 and conv_ratio >= switch_rate:
            conv_votes[gt_label] += 1
        elif switch_rate > 0.0 or flip_accum > 0.0:
            traffic_votes[gt_label] += 1
        else:
            quiet_votes[gt_label] += 1

    def majority(votes, default):
        if not votes:
            return default
        best_count = max(votes.values())
        # 同数は v1.4 既定順(_V14_T3)で最小を採る(決定的 tie-break)。
        winners = [lbl for lbl, c in votes.items() if c == best_count]
        for lbl in _V14_T3:
            if lbl in winners:
                return lbl
        return sorted(winners)[0]

    return {
        "conv_label": majority(conv_votes, CONV_PARTICIPATING),
        "traffic_label": majority(traffic_votes, TRAFFIC_UNSTABLE),
        "quiet_label": majority(quiet_votes, QUIET_STABLE),
    }
