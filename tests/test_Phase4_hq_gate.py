"""Phase 4 観測品質下限ゲート(ADR 0026)の回帰テスト — env 過剰断定の uncertain 是正を pin。

ADR 0026(採用済み・実装済み)の `t3.step` 観測品質下限ゲートの**現挙動を固定**する回帰テスト。
監査 needs_fix の R1「このゲート挙動を pin する回帰テストが無い」への応答。

ゲート契約(ADR 0026 決定):
  `step` で base 仮説確定後、**フレームの posterior(h_q ∈ [0,1])< 0.40 ∧ base ∈ {env_start,
  env_shift}** のとき、hypothesis を uncertain_context に書き換える。観測劣化を「環境変化」と
  誤断する env 過剰断定の是正。
    - 対象は **env 系のみ**(env_start / env_shift)。quiet / conv / traffic / 安全警戒系は不変
      =**偽陽性ゼロ**(観測品質でなく静穏な低 posterior フレームを巻き込まない)。
    - 閾値 0.40 は固定構造定数で**学習対象でない**(`learnable_param_count()` は 6 のまま)。
    - 厳密 `< 0.40` のみ是正(`== 0.40` は env のまま)。

検証戦略(ADR 0020 / 既存 test_F009_*.py の流儀を踏襲):
  - 入力は**合成 mode 系列** `{"mode": ラベル, "posterior": float}` の列で完結・実データ非依存。
  - base 仮説を env 系へ乗せる mode 系列 = `env_change` mode の列(core が h_q<0.5 で積む観測劣化
    シグナルから env_start/env_shift が立つ・ADR 0026 診断3)。非 env 系は各クラスを出す mode で
    固定。
  - env フレームの posterior を低/高/境界で振り分け、ゲートの弁別(低→uncertain・高→env・
    境界 0.40→env / 0.399→uncertain)を実際に確認する(「緑にするための骨抜き」にしない)。

スコープ・規律:
  - stdlib + pytest のみ・決定的(乱数/時刻なし)。実装ロジックは読まず、公開 API のみ使用。
  - 既存テスト不変。本ファイルは現挙動を pin する回帰テスト(実装済みゆえ green が前提)。

テストが前提とする supreme.t3 の公開 API(既存 test_F009_*.py 参照):
  t3.step(mode, reset, state) -> (hypothesis, next_state)
  t3.initial_state() -> state
  t3.run_t3_sequence(mode_seq, reset_seq, params) -> list[hypothesis]
  t3.default_params() -> params
  t3.ENV_START / t3.ENV_SHIFT / t3.UNCERTAIN_CONTEXT(v1.4 T3 語彙定数・str)
  mode dict = {"mode": ラベル, "posterior": float}
"""

import pytest

from supreme import t3


# ---------------------------------------------------------------------------
# 合成 mode 系列のヘルパ(既存 test_F009_*.py の {"mode","posterior"} 流儀)
# ---------------------------------------------------------------------------

def _mode(label, posterior):
    """T2 mode 出力の最小形(上流の証拠抽出はスコープ外・mode/posterior を直接与える)。"""
    return {"mode": label, "posterior": posterior}


# base 仮説を env 系(env_start / env_shift)へ乗せる mode ラベル。
# ADR 0026 診断3: core は h_q<0.5 で env_change mode を積み、t3 はそこから env_start/env_shift を
# 立てる。よって env_change mode の列が env 系 base 仮説を生む合成系列。
_ENV_MODE = "env_change"

# uncertain ゲート対象外(非 env)の代表クラスを出す mode ラベル。
# 各々が異なる v1.4 T3 クラス(quiet/conv/安全警戒/crowd)へ落ち、env ゲートの対象でない。
_NON_ENV_MODES = {
    "quiet_standby": "quiet",          # → quiet 系
    "conv_ongoing": "conv",            # → conv 系
    "alert_required": "safety_alert",  # → 安全警戒系(alert)
    "emergency": "safety_alert",       # → 安全警戒系(sustained_alert)
    "surround_activity": "crowd",      # → crowd 系
}


def _env_sequence(posterior, n=8):
    """env 系 base 仮説を生む合成 mode 系列(env_change×n)を所定 posterior で作る。"""
    return [_mode(_ENV_MODE, posterior)] * n


def _run_seq(mode_seq):
    """mode 系列を default_params で run_t3_sequence に流し hypothesis 列(list)を返す。"""
    reset_seq = [False] * len(mode_seq)
    return list(t3.run_t3_sequence(mode_seq, reset_seq, t3.default_params()))


def _step_once(mode):
    """初期状態から1フレームだけ step して hypothesis を返す(単一フレーム path)。"""
    h, _state = t3.step(mode, False, t3.initial_state())
    return h


# v1.4 T3 語彙定数(公開シンボル)— ゲートの是正先と対象。
UNCERTAIN = t3.UNCERTAIN_CONTEXT
ENV_TARGETS = frozenset({t3.ENV_START, t3.ENV_SHIFT})


# ===========================================================================
# 観点1: 低 posterior の env → uncertain(ゲートの核心)
# ===========================================================================

def test_Phase4_low_posterior_env_is_gated_to_uncertain():
    """ADR 0026(観点1・核心): base が env 系になる mode 系列を低 posterior(0.1 < 0.40)で
    流すと、出力が全フレーム uncertain_context へ是正される(env 過剰断定の是正)。

    env_change mode の列は base 仮説 env_start/env_shift を立てるが、フレームの posterior が
    0.40 未満なので観測品質下限ゲートが uncertain_context に書き換える。
    """
    out = _run_seq(_env_sequence(posterior=0.1, n=8))
    assert all(h == UNCERTAIN for h in out), (
        f"低 posterior(0.1)の env 系列が全 uncertain_context にならない: {out}"
        "(env 過剰断定の是正ゲートが効いていない)"
    )
    # 是正後は env 系ラベルが1つも残らない(全是正)。
    assert not (set(out) & ENV_TARGETS), (
        f"低 posterior の env 系列に env ラベルが残存: {set(out) & ENV_TARGETS}"
    )


def test_Phase4_low_posterior_env_gated_at_single_step():
    """ADR 0026(観点1・単一フレーム path): 単一 env フレーム(env_change, posterior=0.1)を
    初期状態から step すると uncertain_context になる(step 単体でもゲートが効く)。

    系列 API だけでなく step 単体でもゲートが base env を uncertain へ是正することを固定する。
    """
    h = _step_once(_mode(_ENV_MODE, 0.1))
    assert h == UNCERTAIN, (
        f"単一 env フレーム(posterior=0.1)の step 出力が uncertain_context でない: {h!r}"
    )


# ===========================================================================
# 観点2: 高 posterior の env は不変(ゲートは閾値以上では作動しない)
# ===========================================================================

def test_Phase4_high_posterior_env_is_unchanged():
    """ADR 0026(観点2): 同じ env 系列でも posterior >= 0.40(0.9)なら出力は env のまま
    (uncertain にしない)。観測品質が十分なら env 断定を是正しない。

    posterior=0.9 の env_change 系列は env_start/env_shift を保ち、uncertain_context を
    1つも含まない(ゲートは閾値以上では不作動)。
    """
    out = _run_seq(_env_sequence(posterior=0.9, n=8))
    assert all(h in ENV_TARGETS for h in out), (
        f"高 posterior(0.9)の env 系列に env 以外が混入: {out}"
        "(閾値以上なのにゲートが作動した=偽是正)"
    )
    assert UNCERTAIN not in out, (
        f"高 posterior の env 系列が uncertain_context を含む: {out}"
        "(観測品質十分なのに env を uncertain へ巻き込んだ)"
    )


def test_Phase4_low_vs_high_env_outputs_differ():
    """ADR 0026(観点1+2・弁別): 同一の env mode 系列でも、低 posterior(0.1)と高 posterior
    (0.9)で出力が変わる(=ゲートが posterior を実際に読んで弁別している)。

    posterior のみを振った 2 系列で出力が一致するなら「骨抜き」(ゲートが posterior を見ていない)。
    低=uncertain・高=env と確かに分かれることを固定する。
    """
    low = _run_seq(_env_sequence(posterior=0.1, n=8))
    high = _run_seq(_env_sequence(posterior=0.9, n=8))
    assert low != high, (
        f"低/高 posterior の env 出力が同一(ゲートが posterior を弁別していない): {low}"
    )
    assert all(h == UNCERTAIN for h in low)
    assert all(h in ENV_TARGETS for h in high)


# ===========================================================================
# 観点3: 境界(厳密 < 0.40 のみ uncertain・== 0.40 は env)
# ===========================================================================

def test_Phase4_boundary_exactly_040_stays_env():
    """ADR 0026(観点3・境界・閾値ちょうど): posterior == 0.40 の env 系列は env のまま
    (厳密 < 0.40 のみ uncertain なので、ちょうどは是正しない)。

    閾値 0.40 が固定構造定数で、境界の包含側(>=)が env であることを pin する。
    """
    out = _run_seq(_env_sequence(posterior=0.40, n=8))
    assert all(h in ENV_TARGETS for h in out), (
        f"posterior==0.40 の env 系列が env のままでない: {out}"
        "(境界 0.40 を < 側に取り込んでいる=厳密 < 0.40 でない)"
    )
    assert UNCERTAIN not in out


def test_Phase4_boundary_just_below_040_is_uncertain():
    """ADR 0026(観点3・境界・閾値直下): posterior == 0.399(< 0.40)の env 系列は
    uncertain_context へ是正される(閾値直下は is gated)。

    0.40 と 0.399 を弁別することで、境界が厳密 `< 0.40` であることを両側から固定する。
    """
    out = _run_seq(_env_sequence(posterior=0.399, n=8))
    assert all(h == UNCERTAIN for h in out), (
        f"posterior==0.399(<0.40)の env 系列が全 uncertain にならない: {out}"
        "(境界直下でゲートが作動していない)"
    )


def test_Phase4_boundary_040_and_0399_disagree():
    """ADR 0026(観点3・境界の弁別): posterior=0.40 と 0.399 で env 系列の出力が異なる
    (0.40→env / 0.399→uncertain)。閾値が両者の間にあることを直接固定する。
    """
    at = _run_seq(_env_sequence(posterior=0.40, n=8))
    below = _run_seq(_env_sequence(posterior=0.399, n=8))
    assert at != below, (
        f"posterior=0.40 と 0.399 で env 出力が同一(閾値が両者を分離していない): "
        f"0.40={at} / 0.399={below}"
    )
    assert all(h in ENV_TARGETS for h in at)
    assert all(h == UNCERTAIN for h in below)


# ===========================================================================
# 観点4: env 以外は不変(偽陽性ゼロ)
# ===========================================================================

@pytest.mark.parametrize("mode_label", sorted(_NON_ENV_MODES))
def test_Phase4_non_env_classes_not_gated_at_low_posterior(mode_label):
    """ADR 0026(観点4・偽陽性ゼロ): env ゲート対象外(quiet/conv/traffic/安全警戒/crowd)の
    mode 系列は、低 posterior(0.1)でも uncertain_context にならない。

    ゲートは env 系のみを是正対象とするため、非 env クラスは観測品質が低くても元の仮説のまま
    (静穏など観測品質でなく低 posterior なフレームを巻き込まない=偽陽性ゼロ)。
    各非 env mode クラスについて個別に固定する。
    """
    out = _run_seq([_mode(mode_label, 0.1)] * 8)
    assert UNCERTAIN not in out, (
        f"非 env mode {mode_label!r} の低 posterior 系列が uncertain_context を含む: {out}"
        "(env 以外を巻き込んだ=偽陽性)"
    )


@pytest.mark.parametrize("mode_label", sorted(_NON_ENV_MODES))
def test_Phase4_non_env_classes_invariant_to_posterior(mode_label):
    """ADR 0026(観点4・偽陽性ゼロ・不変性): 非 env mode 系列の出力は、低 posterior(0.1)でも
    高 posterior(0.9)でも同じ(ゲートが env 以外には一切作用しない)。

    観点2(env は posterior で変わる)の対。非 env クラスは posterior に依存して uncertain へ
    動かない=ゲートが env 限定であることを、複数の非 env クラスで弁別固定する。
    """
    low = _run_seq([_mode(mode_label, 0.1)] * 8)
    high = _run_seq([_mode(mode_label, 0.9)] * 8)
    assert low == high, (
        f"非 env mode {mode_label!r} の出力が posterior で変わった: 低={low} / 高={high}"
        "(env ゲートが非 env クラスに波及している=偽陽性の温床)"
    )
    assert UNCERTAIN not in low


# ===========================================================================
# 観点5: 決定性(同一入力で2回 step して一致)
# ===========================================================================

def test_Phase4_gate_is_deterministic_low_env():
    """ADR 0026(観点5・決定性): 低 posterior の env 系列を2回流すと出力が完全一致
    (乱数・時刻なし)。is gated 経路も決定的。
    """
    seq = _env_sequence(posterior=0.1, n=8)
    assert _run_seq(seq) == _run_seq(seq), "低 posterior env のゲート出力が2回で不一致(非決定)"


def test_Phase4_gate_is_deterministic_high_env():
    """ADR 0026(観点5・決定性): 高 posterior の env 系列(非 gated 経路)も2回で完全一致。"""
    seq = _env_sequence(posterior=0.9, n=8)
    assert _run_seq(seq) == _run_seq(seq), "高 posterior env の出力が2回で不一致(非決定)"


def test_Phase4_single_step_gate_is_deterministic():
    """ADR 0026(観点5・決定性・単一 step): 同一の env フレームを初期状態から2回 step すると
    (hypothesis, は)同一(ゲート是正を含む単一フレーム経路の決定性)。
    """
    m = _mode(_ENV_MODE, 0.1)
    first = _step_once(m)
    second = _step_once(m)
    assert first == second == UNCERTAIN, (
        f"単一 env フレームの step 出力が2回で不一致または uncertain でない: "
        f"{first!r} / {second!r}"
    )
