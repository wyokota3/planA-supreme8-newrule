"""F-009-2 リセット初期化: 注入 reset 後に状態が初期値へ戻る(エピソード境界で過去が消える)。

これは F-009 の最も具体的な受け入れ条件である。注入 reset(bool 信号)後に状態(窓・集約累積)が
初期状態へ戻ることを、状態を外から取得できる API(F-006 t1_state / F-010 流儀)で検証する。

契約の最終根拠:
  - specs/SPEC.md F-009-2:「RESET_T3 / EPISODE_SWITCH 後に状態が初期値へ戻ることを検証できる」。
  - decisions/0020-f009-t3-episode-learning.md:
      決定1: 有界窓+エピソード集約。状態は注入 reset 信号の受信時に初期化(無限累積なし)。
      決定3 F-009-2: 注入 reset 信号後に状態(窓・集約累積)が初期値へ戻る。状態を外から取得/注入
             できる API。
  - decisions/0018-u4-u24-learning-prerequisites.md(U4):
      リセット源=注入(入力)。状態形=有界窓+集約。境界(注入 reset)で初期化。無限累積なし。
      跨ぐ単位=エピソード。reset 信号は外部入力としてモック可能(TEST_STRATEGY F-009)。
  - specs/TEST_STRATEGY.md F-009:「リセットトリガを外部入力としてモック可能に設計し、トリガ後の
    初期化をテスト」。リセット分岐は分岐網羅必須。
  - specs/SPEC.md 異常系:「リセット命令の発生源が無いと状態が無限累積する」(C と連動)。

検証戦略(ADR 0020 決定3「初期状態から1フレーム流したのと同じ」):
  reset=True のフレーム後の状態が、「初期状態から、その reset フレームの mode を1回流した状態」と
  等価。これを end-to-end の hypothesis で観測する: ある系列を蓄積 → reset付きフレーム →
  直後のふるまいが「初期状態から流し始めたのと同じ」になる(過去が消える)。

スコープ外(ADR 0020・推測でテスト化しない):
  - 集約特徴の具体的な式・状態オブジェクトの内部表現は ADR 0020 が一意に規定しない。本ファイルは
    『reset 後の状態が初期状態と等価』を、状態オブジェクトの中身に踏み込まず、後続フレームの
    hypothesis 等価性および集約特徴アクセサ(test_F009_aggregate.py が定義)で観測する。
  - reset 信号の発火源(scene cut / ts ギャップ)は上流共有基盤(スコープ外)。reset は注入信号。

テストが前提とする supreme.t3 の公開 API(設計裁量・指示で委任・test_F009_state.py 参照):
  t3.step(mode, reset, state) -> (hypothesis, next_state)
  t3.initial_state() -> state
  t3.run_t3_sequence(mode_seq, reset_seq, params) -> list[hypothesis]
  t3.default_params() -> params
  t3.episode_features(state) -> dict 風(持続conv比率 等のアクセサ・test_F009_aggregate.py 参照)
      .conv_ratio / .switch_rate / .flip_accum を持つ(reset でこれらが初期化されることを観測)。
"""

import pytest

from supreme import t3


def _mode(label, posterior=0.5):
    return {"mode": label, "posterior": posterior}


def _conv(posterior=0.7):
    return _mode("conv_strong", posterior)


def _quiet(posterior=0.2):
    return _mode("quiet", posterior)


def _traffic(posterior=0.5):
    return _mode("traffic", posterior)


# ===========================================================================
# C) reset=True 後の状態が「初期状態から1フレーム流した」と等価
#    (エピソード境界で過去が消える)
# ===========================================================================

def test_F009_2_reset_returns_state_to_initial_episode():
    """F-009-2(ADR 0020 決定3・リセット初期化・核心): conv を長く蓄積した後に reset=True の
    フレームを流すと、その後のふるまいが「初期状態から流し始めた」のと同じになる。

    検証: (A) 蓄積系列を流して状態を作る → その状態に reset=True で frame X を流す → 続けて
    frame Y を流す。(B) 初期状態に reset=False で frame X を流す(= reset が初期化したのと同じ
    エピソード先頭)→ 続けて frame Y を流す。reset がエピソード境界で過去を消すなら、(A) の
    reset 以降の hypothesis 列 == (B) の hypothesis 列。
    """
    params = t3.default_params()

    # (A) conv を蓄積した状態 → reset 付き frame X(quiet)→ frame Y(quiet)。
    state = t3.initial_state()
    for _ in range(6):
        _h, state = t3.step(_conv(0.75), False, state)
    hA_x, state = t3.step(_quiet(0.2), True, state)   # reset=True で frame X
    hA_y, _ = t3.step(_quiet(0.21), False, state)      # frame Y(reset 後)

    # (B) 初期状態に frame X(quiet・reset 無しでエピソード先頭)→ frame Y(quiet)。
    state_b = t3.initial_state()
    hB_x, state_b = t3.step(_quiet(0.2), False, state_b)  # エピソード先頭の frame X
    hB_y, _ = t3.step(_quiet(0.21), False, state_b)        # frame Y

    assert hA_x == hB_x, (
        f"reset=True のフレーム出力 {hA_x!r} が、初期状態からのエピソード先頭 {hB_x!r} と"
        "一致しない(reset が状態を初期化していない=過去が残っている)"
    )
    assert hA_y == hB_y, (
        f"reset 直後のフレーム出力 {hA_y!r} が、初期状態から2フレーム目 {hB_y!r} と一致しない"
        "(エピソード境界で過去が消えていない)"
    )


def test_F009_2_reset_clears_prior_conv_accumulation():
    """F-009-2(ADR 0020 決定1/決定3・持続conv累積のリセット): reset 前に蓄積した持続conv の
    影響が reset 後に消える。

    conv を長く蓄積した状態と、何も蓄積していない初期状態とで、reset=True を同じ frame に
    与えれば、その後の hypothesis が一致する(reset が持続conv累積を消すため、蓄積の有無が
    結果に出ない)。
    """
    params = t3.default_params()
    frame_x = _traffic(0.5)
    frame_y = _quiet(0.2)

    # 蓄積あり → reset=True で frame_x → frame_y
    s_accum = t3.initial_state()
    for _ in range(8):
        _h, s_accum = t3.step(_conv(0.8), False, s_accum)
    _hx_a, s_accum = t3.step(frame_x, True, s_accum)
    hy_accum, _ = t3.step(frame_y, False, s_accum)

    # 蓄積なし(初期状態) → reset=True で frame_x → frame_y
    s_fresh = t3.initial_state()
    _hx_f, s_fresh = t3.step(frame_x, True, s_fresh)
    hy_fresh, _ = t3.step(frame_y, False, s_fresh)

    assert hy_accum == hy_fresh, (
        f"reset 後の hypothesis が蓄積の有無で異なる: 蓄積あり {hy_accum!r} != "
        f"蓄積なし {hy_fresh!r}(reset が持続conv累積を消していない)"
    )


# ===========================================================================
# C) エピソード集約特徴が reset で初期化される(無限累積しない=ADR 0018)
#    持続conv比率 / 切替率 / flip累積 が reset 後に消える
# ===========================================================================

def test_F009_2_reset_initializes_episode_aggregate_features():
    """F-009-2(ADR 0020 決定1/決定3・集約特徴のリセット): reset 前に蓄積した集約特徴
    (持続conv比率・切替率・flip累積)が reset 後に初期状態の値へ戻る。

    conv 持続+mode 切替で集約特徴を蓄積 → reset=True フレーム後の集約特徴が、初期状態から
    その reset フレームの mode を1回流した集約特徴と等価であること。状態の内部表現でなく
    episode_features アクセサ(.conv_ratio/.switch_rate/.flip_accum)で観測する。
    """
    params = t3.default_params()

    # 蓄積: conv 持続 → traffic 切替 を交互に入れて集約特徴を育てる。
    state = t3.initial_state()
    for m in [_conv(0.8), _conv(0.8), _traffic(0.5), _conv(0.8), _traffic(0.5), _conv(0.8)]:
        _h, state = t3.step(m, False, state)
    feats_before = t3.episode_features(state)
    # 蓄積されている(少なくとも conv 比率は正)ことを前提確認。
    assert feats_before.conv_ratio > 0.0, (
        "蓄積フェーズで持続conv比率が育っていない(集約機構が動いていない)"
    )

    # reset=True フレーム(quiet)を流す。
    reset_frame = _quiet(0.2)
    _h_reset, state_after_reset = t3.step(reset_frame, True, state)
    feats_after = t3.episode_features(state_after_reset)

    # 比較対象: 初期状態に reset_frame を1回流した集約特徴(=エピソード先頭)。
    s_fresh = t3.initial_state()
    _h_fresh, s_fresh = t3.step(reset_frame, False, s_fresh)
    feats_fresh = t3.episode_features(s_fresh)

    assert feats_after.conv_ratio == feats_fresh.conv_ratio, (
        f"reset 後の持続conv比率 {feats_after.conv_ratio} がエピソード先頭 "
        f"{feats_fresh.conv_ratio} と一致しない(累積が消えていない)"
    )
    assert feats_after.switch_rate == feats_fresh.switch_rate, (
        f"reset 後の切替率 {feats_after.switch_rate} がエピソード先頭 "
        f"{feats_fresh.switch_rate} と一致しない(累積が消えていない)"
    )
    assert feats_after.flip_accum == feats_fresh.flip_accum, (
        f"reset 後の flip累積 {feats_after.flip_accum} がエピソード先頭 "
        f"{feats_fresh.flip_accum} と一致しない(累積が消えていない)"
    )


def test_F009_2_aggregate_does_not_accumulate_unboundedly_across_reset():
    """F-009-2(ADR 0018・無限累積しない): エピソードを跨いで集約が無限に累積しない。
    reset を挟めば、同じ長さの conv 持続でも集約特徴(flip累積等)が初期化されて積み上がらない。

    (A) reset 無しで conv/traffic を 12 フレーム流す。(B) 6 フレーム流して reset、さらに 6
    フレーム流す。reset がエピソード境界で初期化するなら、(B) の末尾 flip累積 < (A) の末尾
    flip累積(reset 後は後半6フレーム分しか積まれない=無限累積でない)。
    """
    params = t3.default_params()
    pattern = [_conv(0.8), _traffic(0.5)] * 6  # 12 フレーム・交互(flip が立ちやすい)

    # (A) reset 無し 12 フレーム。
    s_a = t3.initial_state()
    for m in pattern:
        _h, s_a = t3.step(m, False, s_a)
    flip_no_reset = t3.episode_features(s_a).flip_accum

    # (B) 前半6 → reset → 後半6。
    s_b = t3.initial_state()
    for m in pattern[:6]:
        _h, s_b = t3.step(m, False, s_b)
    # 7フレーム目で reset=True を注入(エピソード境界)。
    _h, s_b = t3.step(pattern[6], True, s_b)
    for m in pattern[7:]:
        _h, s_b = t3.step(m, False, s_b)
    flip_with_reset = t3.episode_features(s_b).flip_accum

    assert flip_with_reset < flip_no_reset, (
        f"reset を挟んでも flip累積が減らない: reset有 {flip_with_reset} >= "
        f"reset無 {flip_no_reset}(エピソード境界で初期化されず無限累積している)"
    )


# ===========================================================================
# reset=False の連続フレームでは累積が消えない(リセット分岐の対・分岐網羅)
# ===========================================================================

def test_F009_2_no_reset_keeps_accumulating():
    """F-009-2(ADR 0020 決定1・リセット分岐の対): reset=False のフレームでは集約累積が消えず、
    持続的に conv が続くほど持続conv比率が単調に育つ(reset 分岐の False 側)。

    reset=True で初期化する側(上のテスト)と対になる、reset=False で累積が保たれる側を固定し、
    リセット分岐の両側(True=初期化 / False=継続)を網羅する。
    """
    state = t3.initial_state()
    _h, state = t3.step(_conv(0.8), False, state)
    ratio_1 = t3.episode_features(state).conv_ratio
    # さらに conv を続ける(reset せず)。
    for _ in range(5):
        _h, state = t3.step(_conv(0.8), False, state)
    ratio_6 = t3.episode_features(state).conv_ratio
    # conv のみのエピソードなので持続conv比率は維持/上昇(消えない)。
    assert ratio_6 >= ratio_1 and ratio_6 > 0.0, (
        f"reset=False で持続conv比率が保たれない/育たない: {ratio_1} → {ratio_6}"
        "(reset 分岐の False 側で累積が消えてしまっている)"
    )


def test_F009_2_reset_at_first_frame_equals_no_reset_first_frame():
    """F-009-2(ADR 0020 決定3・境界): 初期状態(履歴なし)に対する reset=True は、reset=False と
    同じ結果になる(消すべき過去が無いため)。

    エピソード先頭での reset は no-op 等価(初期状態 → reset → 等価に初期状態)。reset 分岐が
    『初期状態へ戻す』という定義に整合することを境界で固定する。
    """
    frame = _conv(0.7)
    h_reset, s_reset = t3.step(frame, True, t3.initial_state())
    h_noreset, s_noreset = t3.step(frame, False, t3.initial_state())
    assert h_reset == h_noreset, (
        f"初期状態への reset=True {h_reset!r} が reset=False {h_noreset!r} と異なる"
        "(消す過去が無いのに結果が変わる=reset の定義が初期化でない)"
    )
    # 集約特徴も一致(初期状態へ1フレームと等価)。
    f_reset = t3.episode_features(s_reset)
    f_noreset = t3.episode_features(s_noreset)
    assert f_reset.conv_ratio == f_noreset.conv_ratio, (
        "初期状態への reset で集約特徴がエピソード先頭(reset無し1フレーム)と異なる"
    )


# ===========================================================================
# run_t3_sequence の reset 列でも初期化が効く(系列 API のリセット分岐)
# ===========================================================================

def test_F009_2_run_sequence_reset_clears_episode_in_sequence():
    """F-009-2(ADR 0020 決定3・系列 API のリセット): run_t3_sequence の reset 列で True を
    与えたフレーム以降は、過去エピソードの蓄積に依存しない。

    系列 [conv×6, (reset)quiet, quiet×3] と [(初期状態から)quiet, quiet×3] の reset 後部分の
    hypothesis 列が一致する(系列 API でもエピソード境界で過去が消える)。
    """
    params = t3.default_params()

    # 系列 A: conv 蓄積 → frame#6 で reset → quiet 列。
    mode_a = [_conv(0.8)] * 6 + [_quiet(0.2)] + [_quiet(0.21)] * 3
    reset_a = [False] * 6 + [True] + [False] * 3
    out_a = list(t3.run_t3_sequence(mode_a, reset_a, params))

    # 系列 B: 初期状態から同じ quiet 列(エピソード先頭)。
    mode_b = [_quiet(0.2)] + [_quiet(0.21)] * 3
    reset_b = [False] * len(mode_b)
    out_b = list(t3.run_t3_sequence(mode_b, reset_b, params))

    # A の reset フレーム(index 6)以降 == B の全体。
    assert out_a[6:] == out_b, (
        f"系列 API で reset 後の hypothesis 列 {out_a[6:]} がエピソード先頭からの列 "
        f"{out_b} と一致しない(系列のリセット境界で過去が消えていない)"
    )
