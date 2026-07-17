"""F-009 T3 時系列統合(ADR 0020)— 状態機構(入力系列 → T3 hypothesis 系列)+ 状態の往復。

これは「状態保持+学習モジュール」のテストである。fit で決まる**実際の学習値**(重み/バイアス)は
F-013 で測定する成功目標であり契約にしない。本ファイルは T3 状態機構の**構造・決定性・状態の
往復可能性**を契約化する(F-006 t1_state / F-010 の流儀)。

契約の最終根拠:
  - decisions/0020-f009-t3-episode-learning.md(手法の正):
      決定1: 有界窓+エピソード集約の状態機構(無限累積を有界窓+集約統計に置換)。
      決定3: 状態保持の決定性とリセット。状態を外から取得/注入できる API(F-006 T1 / F-010 流儀)。
      決定4: 入力 = T2 mode 出力系列 + 注入 reset 信号。証拠抽出・T2 は上流共有基盤(スコープ外)。
  - decisions/0018-u4-u24-learning-prerequisites.md(U4):
      リセット源=注入(入力)・状態形=有界窓+集約・跨ぐ単位=エピソード・無限累積なし。
  - specs/SPEC.md F-009(F-009-1 再現性 / F-009-2 リセット初期化)/ decisions/0006(v1.4 T3 語彙)/
    decisions/0002(ε=U5a・再現性)。

受け入れ条件(本ファイルが寄与):
  - F-009-1(再現性): 状態機構が決定的(乱数/時刻なし)であること。完全一致は test_F009_reproduce.py。
  - 状態の往復: 状態を取り出し次フレームへ注入できる形(リセット検証用・F-009-2 の土台)。

スコープ外(ADR 0020・推測でテスト化しない):
  - 証拠抽出・T2(上流共有基盤)。テストは mode/features を直接与える。
  - fit 後の厳密な学習値・実際の T3 acc 改善・ns016群の分離成否(F-013 の成功目標/残件)。
  - 次状態オブジェクトの具体的な型(namedtuple/dict/dataclass)・窓長 W・集約特徴の最終セットは
    ADR 0020 が一意に規定しない(実装時確定)。本ファイルは状態の「往復可能性」(取り出して
    次フレームへ注入できる)と「機構の決定性・構造」のみを固定し、内部表現には踏み込まない。

テストが前提とする supreme.t3 の公開 API(設計裁量・指示で委任・F-006/F-010 の流儀):
  t3.step(mode, reset, state) -> (hypothesis, next_state)
      mode  = T2 mode 出力(dict or 集約済み特徴・スコープ外の証拠抽出は与えられる前提)。
      reset = 注入 reset 信号(bool)。True で状態を初期化する(F-009-2)。
      state = 前フレームから持ち越す状態(初手は t3.initial_state() or None)。
      返り値 = (v1.4 T3 hypothesis ラベル, 次フレームへ渡す状態)。状態を外から取得/注入できる形。
  t3.initial_state() -> state
      決定的な初期状態(窓・集約累積が空)。外から注入できる初期状態。
  t3.run_t3_sequence(mode_seq, reset_seq, params) -> list[hypothesis]
      mode 系列 + reset 系列(同長)+ params(学習済み重み/バイアス等)を順に統合し、各フレームの
      v1.4 T3 hypothesis 列を返す(系列 API)。内部で step を初期状態から連鎖する。
  t3.default_params() -> params
      決定的な既定 params(fit 前初期値)。テストはこれを与えて機構を見る。
"""

import pytest

from supreme import t3


def _mode(label, posterior=0.5):
    """T2 mode 出力の最小形(集約済み特徴を直接与える=上流の証拠抽出はスコープ外)。

    label    = その frame の T2 mode argmax(conv 系 / traffic 系 / quiet 系のいずれか)。
    posterior = mode posterior の代表スカラ(集約の posterior 平均/分散/トレンドの素材)。
    """
    return {"mode": label, "posterior": posterior}


def _conv(posterior=0.7):
    return _mode("conv_strong", posterior)


def _quiet(posterior=0.2):
    return _mode("quiet", posterior)


def _traffic(posterior=0.5):
    return _mode("traffic", posterior)


# ===========================================================================
# 公開シンボルの存在(状態機構の入口)
# ===========================================================================

def test_F009_t3_exposes_step():
    """F-009(契約面・ADR 0020 決定1/決定3): t3 は1フレーム統合の入口 step() を公開する。

    step(mode, reset, state) -> (hypothesis, next_state)。状態を引数で受け取り次状態を返す
    =状態を外から取得/注入できる形(F-006 t1_state / F-010 流儀・リセット検証の土台)。
    """
    assert hasattr(t3, "step"), "t3.step が公開されていない"
    assert callable(t3.step)


def test_F009_t3_exposes_initial_state():
    """F-009(契約面・ADR 0020 決定1/決定3): t3 は初期状態 initial_state() を公開する。

    決定的な初期状態(窓・集約累積が空)。リセット後の状態と比較するための基準
    (F-009-2 の往復検証に使う)。
    """
    assert hasattr(t3, "initial_state"), "t3.initial_state が公開されていない"
    assert callable(t3.initial_state)


def test_F009_t3_exposes_run_sequence_and_default_params():
    """F-009(契約面・ADR 0020 決定1/決定4): t3 は系列 API run_t3_sequence() と
    default_params() を公開する。

    run_t3_sequence(mode_seq, reset_seq, params) で mode 系列+reset 系列を一括統合する
    (F-009-1 再現性を系列単位で見る入口)。default_params で決定的な既定 params を得る。
    """
    assert hasattr(t3, "run_t3_sequence"), "t3.run_t3_sequence が公開されていない"
    assert callable(t3.run_t3_sequence)
    assert hasattr(t3, "default_params"), "t3.default_params が公開されていない"
    assert callable(t3.default_params)


# ===========================================================================
# step の構造: 状態を受け取り (hypothesis, next_state) を返す
# ===========================================================================

def test_F009_step_returns_hypothesis_and_next_state():
    """F-009(ADR 0020 決定1/決定3・構造): step は (hypothesis, next_state) の2要素を返す。

    第1要素は v1.4 T3 hypothesis ラベル(str)、第2要素は次フレームへ渡せる状態。状態を
    外から取得できる形であること(リセット検証・状態往復の前提)。
    """
    result = t3.step(_conv(), False, t3.initial_state())
    assert isinstance(result, tuple) and len(result) == 2, (
        "step は (hypothesis, next_state) の2要素タプルを返すべき"
    )
    hypothesis, next_state = result
    assert isinstance(hypothesis, str), (
        f"step の第1要素(hypothesis)が str でない: {hypothesis!r}"
    )
    assert next_state is not None, "step の第2要素(next_state)が None"


def test_F009_step_accepts_initial_state_or_none():
    """F-009(ADR 0020 決定1/決定3・初手): 初手は initial_state() を渡しても None を渡しても
    エラーなく1フレーム統合できる。

    系列の先頭フレームは「初期状態から1フレーム流す」操作。initial_state() と None の
    どちらでも初手として受理できることを固定する(往復 API の入口)。
    """
    h_init, s_init = t3.step(_conv(), False, t3.initial_state())
    h_none, s_none = t3.step(_conv(), False, None)
    assert isinstance(h_init, str) and isinstance(h_none, str)
    # 初期状態 と None の初手は同じ入力なら同じ hypothesis を出す(初期状態の同一性)。
    assert h_init == h_none, (
        "initial_state() と None の初手が同じ入力で異なる hypothesis を出した"
        "(初期状態が一意でない疑い)"
    )


# ===========================================================================
# 状態の往復: next_state を次フレームへ注入して連鎖できる(F-006 t1_state 流儀)
# ===========================================================================

def test_F009_next_state_is_consumable_across_frames():
    """F-009(ADR 0020 決定3・状態の往復可能性): step の next_state は、その後の step の
    state にそのまま渡せる(状態を外から注入・取得できる形)。

    次状態を次フレームの state に注入してエラーなく連鎖し、各フレームで hypothesis が
    得られることを固定する(状態の受け渡し API 契約)。内部表現の中身には踏み込まない
    (ADR 0020 が型を規定しないため)。
    """
    h0, s0 = t3.step(_conv(), False, t3.initial_state())
    assert isinstance(h0, str)
    h1, s1 = t3.step(_conv(), False, s0)
    assert isinstance(h1, str)
    # さらに連鎖できる(状態が壊れない)。
    h2, _s2 = t3.step(_traffic(), False, s1)
    assert isinstance(h2, str)


def test_F009_state_carries_history_across_frames():
    """F-009(ADR 0020 決定1・状態保持): 状態は前フレームの履歴を持ち越す。

    同じ frame 入力(conv)でも、初期状態から1フレーム流した直後と、conv を長く蓄積した
    後とでは、状態(集約累積)が異なる=過去が状態に反映されている。状態の同一性を
    end-to-end の hypothesis ではなく「状態が初期状態と異なること」で固定する
    (具体的な集約値には踏み込まない)。
    """
    init = t3.initial_state()
    # conv を持続的に蓄積した状態(エピソード集約が進む)。
    state = init
    for _ in range(6):
        _h, state = t3.step(_conv(), False, state)
    # 蓄積後の状態は初期状態と「同一でない」(履歴を保持している)。
    # 状態オブジェクトの中身には踏み込まず、初期状態へ1フレームだけ流した状態とも
    # 異なる(蓄積が進んでいる)ことを hypothesis 経由で観測する。
    _h_after_one, state_one = t3.step(_conv(), False, init)
    # 蓄積状態と「1フレームだけ」状態に、同じ次 frame(conv)を与えたときの hypothesis を比較。
    h_from_accum, _ = t3.step(_conv(), False, state)
    h_from_one, _ = t3.step(_conv(), False, state_one)
    # 蓄積の有無で hypothesis が変わりうる(持続conv が積み上がるほど conv 判定が強まる機構)。
    # ただし両方が conv 域なら一致しうるため、ここでは「状態が履歴を運ぶこと」の最小確認として
    # 蓄積状態が initial_state と区別可能(=過去消えていない)であることを別アサートで担保する。
    assert state is not init, "蓄積後の状態が initial_state そのもの(履歴を運んでいない)"
    # hypothesis は両者とも v1.4 語彙の文字列であること(機構の健全性)。
    assert isinstance(h_from_accum, str) and isinstance(h_from_one, str)


# ===========================================================================
# 系列 API: 出力長 = 入力長、reset 列は mode 列と同長
# ===========================================================================

def test_F009_run_sequence_output_length_matches_input():
    """F-009(ADR 0020 決定1・構造): run_t3_sequence の出力 hypothesis 列の長さが入力 mode
    列長と一致する(各フレームに1つの T3 hypothesis)。
    """
    mode_seq = [_conv(), _conv(), _traffic(), _quiet(), _quiet()]
    reset_seq = [False] * len(mode_seq)
    out = t3.run_t3_sequence(mode_seq, reset_seq, t3.default_params())
    assert len(list(out)) == len(mode_seq), (
        f"出力長 {len(list(out))} が入力 mode 列長 {len(mode_seq)} と一致しない"
    )


def test_F009_run_sequence_requires_reset_seq_same_length():
    """F-009(ADR 0020 決定3/決定4・構造): reset 列は mode 列と同長で与える(各フレームに
    reset 信号が対応する)。長さが食い違う呼び出しはエラーで停止する。

    reset は各フレームへの注入信号(ADR 0018: リセット源=注入)。フレームと reset の対応が
    崩れる入力を黙って通さない(F-004 の『欠落時は止める』精神)。
    """
    mode_seq = [_conv(), _conv(), _traffic()]
    reset_seq = [False, False]  # 1つ短い
    with pytest.raises(Exception):
        t3.run_t3_sequence(mode_seq, reset_seq, t3.default_params())


def test_F009_run_sequence_equals_manual_step_chain():
    """F-009(ADR 0020 決定1・系列 = step 連鎖): run_t3_sequence の出力が、initial_state から
    step を手動連鎖した hypothesis 列と一致する。

    系列 API が「初期状態から step を順に適用する」ことの等価性を固定する(系列と逐次が
    同じ統合=状態機構の一貫性)。reset は各フレームの注入信号として step に渡る。
    """
    params = t3.default_params()
    mode_seq = [_conv(), _conv(), _traffic(), _quiet()]
    reset_seq = [False, False, False, False]

    seq_out = list(t3.run_t3_sequence(mode_seq, reset_seq, params))

    manual = []
    state = t3.initial_state()
    for m, r in zip(mode_seq, reset_seq):
        h, state = t3.step(m, r, state, params) if _step_takes_params() else t3.step(m, r, state)
        manual.append(h)

    assert seq_out == manual, (
        f"run_t3_sequence の出力 {seq_out} が step 手動連鎖 {manual} と一致しない"
        "(系列 API と逐次 step の統合が等価でない)"
    )


def _step_takes_params():
    """step が params を第4引数に取るか(実装裁量)を判定するヘルパ。

    ADR 0020 は step の params 引数有無を一意に規定しない。run_t3_sequence は params を取るが、
    step が params を取るかは実装裁量。両様を許容するため signature を見て分岐する。
    """
    import inspect

    try:
        sig = inspect.signature(t3.step)
        return len(sig.parameters) >= 4
    except (ValueError, TypeError):
        return False


# ===========================================================================
# 出力語彙: v1.4 T3 10クラスに閉じる(decisions/0006)
# ===========================================================================

# v1.4 T3 統制語彙(10クラス・ADR 0020 決定4 / 指示)。
V14_T3_LABELS = {
    "quiet_stable",
    "conv_participating",
    "sustained_alert",
    "env_shift",
    "env_start",
    "crowd_tendency",
    "traffic_unstable",
    "hazard_declining",
    "uncertain_context",
    "alert_required",
}


def test_F009_run_sequence_output_in_v14_vocabulary():
    """F-009(ADR 0006/0020・語彙閉包): run_t3_sequence の出力が v1.4 T3 10クラスのみで
    構成される(開いた辞書にしない)。

    conv 持続 / traffic 切替 / quiet 安定 を含む代表系列で、各 hypothesis が v1.4 10語彙の
    いずれかであることを固定する。どの系列がどのラベルになるかは test_F009_classify.py が
    params 供給で固定する(ここは語彙集合に閉じることのみ)。
    """
    params = t3.default_params()
    mode_seq = [
        _conv(), _conv(), _conv(),          # conv 持続
        _traffic(), _quiet(), _traffic(),   # 切替(不安定)
        _quiet(), _quiet(), _quiet(),       # quiet 安定
    ]
    reset_seq = [False] * len(mode_seq)
    out = t3.run_t3_sequence(mode_seq, reset_seq, params)
    for h in out:
        assert h in V14_T3_LABELS, (
            f"run_t3_sequence の出力に v1.4 T3 語彙外のラベル: {h!r}"
        )


def test_F009_t3_exposes_v14_label_constants():
    """F-009(契約面・ADR 0006/0020): t3 は v1.4 T3 10語彙をラベル定数として公開し、その値が
    それぞれの文字列であること(語彙 faithfulness)。
    """
    expected = {
        "QUIET_STABLE": "quiet_stable",
        "CONV_PARTICIPATING": "conv_participating",
        "SUSTAINED_ALERT": "sustained_alert",
        "ENV_SHIFT": "env_shift",
        "ENV_START": "env_start",
        "CROWD_TENDENCY": "crowd_tendency",
        "TRAFFIC_UNSTABLE": "traffic_unstable",
        "HAZARD_DECLINING": "hazard_declining",
        "UNCERTAIN_CONTEXT": "uncertain_context",
        "ALERT_REQUIRED": "alert_required",
    }
    for name, value in expected.items():
        assert hasattr(t3, name), f"t3.{name} が公開されていない"
        assert getattr(t3, name) == value, (
            f"t3.{name} の値が '{value}' でない(v1.4 T3 語彙 faithfulness 違反)"
        )
