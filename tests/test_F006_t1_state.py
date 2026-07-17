"""F-006 T1 (t1_state) 流用移植・独立再実装: supreme の T1 状態機械が ADR 0017
決定3 の baseline ルール(ttc_threshold クランプ + tick0 + approach 状態での
pass/depart 判定 + 状態持ち越し)を忠実再現すること。テストは挙動
(ttc_s, min_range_m, pw_anom, prev_t1) → (v1.4 t1_state ラベル, 次状態) を契約とし、
内部実装は裁量(挙動等価なら通る)。

契約の最終根拠:
  - decisions/0017-f006-strong-reimplementation.md(手法の正・流用形態 U9)
      決定2: T1 の precision_weight_anom(pw_anom)は入力パラメータ(上流供給・既定 0)。
             証拠抽出・HGF・softmax/EMA は上流共有基盤=スコープ外。
      決定3 T1 (t1_state・状態機械・状態保持):
        - 入力: ttc_s(min_TTC)、min_range_m(全 track の最小 r_m・track 無しは 100.0)、
                pw_anom(既定 0)、prev_t1(前 tick の状態)。
        - ttc_threshold = clamp(12 + pw_anom*3, [12, 15])、appr = ttc_s < ttc_threshold。
        - tick0(prev 無し): appr -> approach / else idle(pass/depart は出さない)。
        - prev=approach: min_seen = min(prev_min_seen, cur_range)、
                         diverged = (cur_range - min_seen) > 1.0、
                         incremented = (cur_range - prev_range) > 0.3。
                         diverged AND incremented AND cur < 5.0  -> pass /
                         diverged AND incremented AND cur > 10.0 -> depart /
                         それ以外は閾値で approach / idle。
        - prev=idle: 閾値のみで approach / idle。
        - 状態 (min_seen, prev_range, in_approach) を次 tick へ持ち越す。
        - 語彙 v1.4: idle / approach / pass / depart。
  - specs/SPEC.md F-006 / decisions/0012(t1_state 4クラス・risk_tier)/
    decisions/0006(v1.4 語彙)。

スコープ外(ADR 0017): 証拠抽出・HGF・softmax/EMA・baseline 数値一致(δ_strong は
F-013 で測定)・上流 pw_anom 生成(pw_anom は入力パラメータとして与える)。

設計裁量(指示で明示委任・ADR 0017「状態を外から注入・取得できる形」F-009 と同様):
  t1.t1_state(ttc_s, min_range_m, pw_anom=0.0, prev_t1=None) -> (label, next_state)
      v1.4 t1_state ラベル文字列と、次 tick へ渡す状態オブジェクトのタプルを返す。
      prev_t1=None は tick0(前状態無し)。次 tick はこの返り値の状態を prev_t1 に
      渡して連鎖する(状態を外から注入・取得できる形)。
  t1.IDLE / APPROACH / PASS / DEPART -> str
      v1.4 統制語彙のラベル定数。

ADR 0017 から一意に決まらない点(推測でテスト化しない):
  - 次状態オブジェクトの具体的な型(namedtuple / dict / dataclass)は ADR 0017 が
    規定しない。本ファイルは t1_state の返り値を「ラベル, 次状態」の2要素として扱い、
    次状態を次呼び出しの prev_t1 にそのまま渡せること(往復可能性)のみを契約とし、
    内部表現の中身(フィールド名)には踏み込まない。
  - prev=pass / prev=depart を次 tick の prev_t1 として与えたときの遷移は ADR 0017 が
    明示的に規定しない(規定は prev=approach / prev=idle の2系統)。実装が pass/depart
    後にどの内部状態へ落ちるかは裁量。本ファイルは pass/depart を「終端的な単発出力」
    として固定し、pass/depart を prev に再注入する人工ケースは作らない。
"""

import pytest

from supreme import t1


# ADR 0017 決定3 T1: ttc_threshold クランプ範囲と pw_anom 係数。
TTC_BASE = 12.0
TTC_CLAMP_MAX = 15.0
PW_COEF = 3.0


def _label(result):
    """t1_state の返り値 (label, next_state) から label を取り出す。"""
    label, _next = result
    return label


def _next_state(result):
    """t1_state の返り値 (label, next_state) から次状態を取り出す。"""
    _label_, next_state = result
    return next_state


# ===========================================================================
# tick0(prev 無し): appr -> approach / else idle(pass/depart は出さない)
# ADR 0017 決定3 T1
# ===========================================================================

def test_F006_tick0_approaching_is_approach():
    """F-006(ADR 0017 決定3 T1・tick0): prev 無しで ttc_s=8.0 < ttc_threshold(12)なら
    appr=True で approach。

    tick0 は appr のみで idle/approach を出す(pass/depart は出さない)。
    """
    assert _label(t1.t1_state(8.0, 30.0, prev_t1=None)) == t1.APPROACH


def test_F006_tick0_not_approaching_is_idle():
    """F-006(ADR 0017 決定3 T1・tick0): prev 無しで ttc_s=20.0 >= ttc_threshold(12)なら
    appr=False で idle。
    """
    assert _label(t1.t1_state(20.0, 30.0, prev_t1=None)) == t1.IDLE


def test_F006_tick0_never_emits_pass_or_depart():
    """F-006(ADR 0017 決定3 T1・tick0): tick0(prev 無し)は pass/depart を出さない。

    接近中(ttc 小)でも遠ざかる兆候(min_range 大)でも、tick0 は approach か idle の
    どちらかのみ。pass/depart は prev=approach の発散判定があって初めて出る。
    """
    for ttc_s, min_range in [(1.0, 3.0), (50.0, 90.0), (8.0, 30.0)]:
        label = _label(t1.t1_state(ttc_s, min_range, prev_t1=None))
        assert label in (t1.IDLE, t1.APPROACH), (
            f"tick0 t1_state({ttc_s}, {min_range}) が pass/depart を出した: {label!r}"
        )


# ===========================================================================
# ttc_threshold = clamp(12 + pw_anom*3, [12, 15]) — ADR 0017 決定3 T1
# pw_anom=0 で 12 / pw_anom>0 で上がる(クランプ 15)
# ===========================================================================

def test_F006_ttc_threshold_default_is_12_boundary():
    """F-006(ADR 0017 決定3 T1・閾値 pw_anom=0): pw_anom=0 で ttc_threshold=12。
    appr = ttc_s < 12(厳密小なり)。

    ttc_s=11.999(< 12)は approach、ttc_s=12.0(== 12、< でない)は idle。
    閾値の向き(<)と pw_anom=0 の threshold=12 を境界で固定する。
    """
    assert _label(t1.t1_state(11.999, 30.0, pw_anom=0.0, prev_t1=None)) == t1.APPROACH
    assert _label(t1.t1_state(12.0, 30.0, pw_anom=0.0, prev_t1=None)) == t1.IDLE


def test_F006_ttc_threshold_raised_by_pw_anom():
    """F-006(ADR 0017 決定3 T1・閾値 pw_anom>0): pw_anom=0.5 で
    ttc_threshold = clamp(12 + 0.5*3, [12,15]) = clamp(13.5, ...) = 13.5。

    ttc_s=13.0 は pw_anom=0(threshold 12)なら idle(13.0 >= 12)だが、pw_anom=0.5
    (threshold 13.5)なら approach(13.0 < 13.5)。pw_anom が閾値を上げることを固定。
    """
    # pw_anom=0: threshold 12, ttc 13.0 >= 12 -> idle
    assert _label(t1.t1_state(13.0, 30.0, pw_anom=0.0, prev_t1=None)) == t1.IDLE
    # pw_anom=0.5: threshold 13.5, ttc 13.0 < 13.5 -> approach
    assert _label(t1.t1_state(13.0, 30.0, pw_anom=0.5, prev_t1=None)) == t1.APPROACH


def test_F006_ttc_threshold_clamped_at_15():
    """F-006(ADR 0017 決定3 T1・閾値クランプ上限): pw_anom が大きく
    12 + pw_anom*3 > 15 でも ttc_threshold は 15 にクランプされる。

    pw_anom=5.0 なら 12 + 15 = 27 だが clamp で 15。ttc_s=14.9(< 15)は approach、
    ttc_s=15.0(== 15、< でない)は idle。クランプ上限 15 を境界で固定する。
    """
    assert _label(t1.t1_state(14.9, 30.0, pw_anom=5.0, prev_t1=None)) == t1.APPROACH
    assert _label(t1.t1_state(15.0, 30.0, pw_anom=5.0, prev_t1=None)) == t1.IDLE


def test_F006_ttc_threshold_default_pw_anom_is_zero():
    """F-006(ADR 0017 決定2/決定3 T1・pw_anom 既定 0): pw_anom を省略すると既定 0 として
    扱われ、threshold=12 になる。

    pw_anom 引数を省いた呼び出しと pw_anom=0.0 を明示した呼び出しが同一挙動であること
    (既定 0・ADR 0017 決定2「pw_anom は入力パラメータ・既定 0」)。
    """
    omitted = _label(t1.t1_state(13.0, 30.0, prev_t1=None))
    explicit = _label(t1.t1_state(13.0, 30.0, pw_anom=0.0, prev_t1=None))
    assert omitted == explicit == t1.IDLE


# ===========================================================================
# prev=idle: 閾値のみで approach / idle(pass/depart は出さない)
# ADR 0017 決定3 T1
# ===========================================================================

def test_F006_prev_idle_threshold_only_to_approach():
    """F-006(ADR 0017 決定3 T1・prev=idle): prev=idle 状態から ttc_s=8.0(< 12)なら
    閾値判定で approach。

    prev=idle は発散判定(pass/depart)を行わず閾値のみ。次状態を idle 状態から作って
    注入する。
    """
    _l0, idle_state = t1.t1_state(20.0, 30.0, prev_t1=None)  # tick0 -> idle
    assert _l0 == t1.IDLE
    result = t1.t1_state(8.0, 30.0, prev_t1=idle_state)
    assert _label(result) == t1.APPROACH


def test_F006_prev_idle_threshold_only_stays_idle():
    """F-006(ADR 0017 決定3 T1・prev=idle): prev=idle で ttc_s=20.0(>= 12)なら idle のまま。

    prev=idle は閾値のみ。発散兆候(min_range が大きい等)があっても depart は出さない。
    """
    _l0, idle_state = t1.t1_state(20.0, 30.0, prev_t1=None)
    assert _l0 == t1.IDLE
    result = t1.t1_state(20.0, 90.0, prev_t1=idle_state)
    assert _label(result) == t1.IDLE


def test_F006_prev_idle_never_emits_pass_or_depart():
    """F-006(ADR 0017 決定3 T1・prev=idle): prev=idle からは pass/depart を出さない
    (発散判定は prev=approach のみ)。
    """
    _l0, idle_state = t1.t1_state(20.0, 30.0, prev_t1=None)
    for ttc_s, min_range in [(1.0, 3.0), (50.0, 95.0), (8.0, 30.0)]:
        label = _label(t1.t1_state(ttc_s, min_range, prev_t1=idle_state))
        assert label in (t1.IDLE, t1.APPROACH), (
            f"prev=idle で t1_state({ttc_s}, {min_range}) が pass/depart を出した: "
            f"{label!r}"
        )


# ===========================================================================
# prev=approach: pass / depart 判定 — ADR 0017 決定3 T1
# diverged = (cur - min_seen) > 1.0、incremented = (cur - prev_range) > 0.3
# diverged AND incremented AND cur < 5.0  -> pass
# diverged AND incremented AND cur > 10.0 -> depart
# ===========================================================================

def test_F006_prev_approach_diverged_close_is_pass():
    """F-006(ADR 0017 決定3 T1・pass): prev=approach で発散 ∧ 増加 ∧ cur<5.0 なら pass。

    シーケンス: tick0 ttc=8.0,range=3.0 -> approach(min_seen=3.0, prev_range=3.0)。
    次 tick cur_range=4.5: diverged=(4.5-3.0)=1.5>1.0 ∧ incremented=(4.5-3.0)=1.5>0.3
    ∧ cur 4.5<5.0 -> pass(近距離で発散=すれ違い)。
    """
    _l0, approach_state = t1.t1_state(8.0, 3.0, prev_t1=None)  # tick0 -> approach
    assert _l0 == t1.APPROACH
    result = t1.t1_state(8.0, 4.5, prev_t1=approach_state)
    assert _label(result) == t1.PASS


def test_F006_prev_approach_diverged_far_is_depart():
    """F-006(ADR 0017 決定3 T1・depart): prev=approach で発散 ∧ 増加 ∧ cur>10.0 なら depart。

    シーケンス: tick0 ttc=8.0,range=9.0 -> approach(min_seen=9.0, prev_range=9.0)。
    次 tick cur_range=10.5: diverged=(10.5-9.0)=1.5>1.0 ∧ incremented=(10.5-9.0)=1.5>0.3
    ∧ cur 10.5>10.0 -> depart(遠距離で発散=離脱)。
    """
    _l0, approach_state = t1.t1_state(8.0, 9.0, prev_t1=None)  # tick0 -> approach
    assert _l0 == t1.APPROACH
    result = t1.t1_state(8.0, 10.5, prev_t1=approach_state)
    assert _label(result) == t1.DEPART


def test_F006_prev_approach_not_diverged_stays_by_threshold():
    """F-006(ADR 0017 決定3 T1・発散せず): prev=approach で発散しない(cur が min_seen
    から 1.0 以内)なら、pass/depart を出さず閾値で approach/idle。

    シーケンス: tick0 ttc=8.0,range=3.0 -> approach。次 tick cur_range=3.5:
    diverged=(3.5-3.0)=0.5、>1.0 でない -> 発散せず。ttc=8.0<12 -> approach のまま。
    """
    _l0, approach_state = t1.t1_state(8.0, 3.0, prev_t1=None)
    result = t1.t1_state(8.0, 3.5, prev_t1=approach_state)
    assert _label(result) == t1.APPROACH


def test_F006_prev_approach_diverged_but_not_incremented_no_pass():
    """F-006(ADR 0017 決定3 T1・増加せず): prev=approach で発散していても増加していない
    (cur - prev_range <= 0.3)なら pass/depart は出さない(両条件の AND)。

    シーケンス: tick0 ttc=8.0,range=3.0 -> approach(min_seen=3.0, prev_range=3.0)。
    tick1 cur_range=4.5 -> pass を経ず…ではなく、ここでは min_seen を作るために
    2 tick 構成する: tick1 で range=4.5 にすると pass になってしまうので、
    increment を抑えるシーケンスを別に組む。

    別シーケンス: tick0 ttc=8.0,range=5.0 -> approach(min_seen=5.0, prev_range=5.0)。
    tick1 cur_range=6.2(diverged=(6.2-5.0)=1.2>1.0、incremented=(6.2-5.0)=1.2>0.3)
    だと pass(cur<5.0 でないので…6.2 は 5<cur<10 なので pass でも depart でもなく
    閾値域)。これは「cur が 5..10 の中間帯」ケースで pass/depart にならないことを固定。
    """
    # cur が 5.0..10.0 の中間帯: diverged ∧ incremented でも pass(<5)でも depart(>10)
    # でもないので閾値判定に落ちる。
    _l0, approach_state = t1.t1_state(8.0, 5.0, prev_t1=None)  # approach, min_seen=5.0
    result = t1.t1_state(8.0, 6.2, prev_t1=approach_state)
    # diverged ∧ incremented だが cur=6.2 は (<5 でも >10 でもない)中間帯。
    # よって pass/depart は出ず、閾値(ttc 8.0<12)で approach。
    assert _label(result) == t1.APPROACH


def test_F006_prev_approach_diverged_mid_range_no_pass_no_depart():
    """F-006(ADR 0017 決定3 T1・中間帯 5..10): prev=approach で発散 ∧ 増加でも
    5.0 <= cur <= 10.0 の中間帯では pass(cur<5.0)にも depart(cur>10.0)にもならず、
    閾値判定に落ちる。

    cur=7.0(diverged ∧ incremented だが 5<7<10)。ttc=8.0<12 なので approach のまま。
    pass/depart の cur 条件(< 5.0 / > 10.0)が厳密不等で中間帯を除外することを固定。
    """
    _l0, approach_state = t1.t1_state(8.0, 5.5, prev_t1=None)  # approach, min_seen=5.5
    result = t1.t1_state(8.0, 7.0, prev_t1=approach_state)
    assert _label(result) in (t1.APPROACH, t1.IDLE), (
        "中間帯(5<cur<10)で pass/depart が出た"
    )
    # ttc 8.0 < 12 なので approach 側。
    assert _label(result) == t1.APPROACH


# ===========================================================================
# 状態持ち越し: min_seen は過去の最小を保持 — ADR 0017 決定3 T1
# ===========================================================================

def test_F006_min_seen_persists_across_ticks():
    """F-006(ADR 0017 決定3 T1・状態保持 min_seen): min_seen は過去 tick の最小 range を
    保持し、後の発散判定 (cur - min_seen) > 1.0 に使われる。

    シーケンス: tick0 range=3.0 -> approach(min_seen=3.0)。tick1 range=2.0 ->
    approach(min_seen=min(3.0,2.0)=2.0、(2.0-2.0)=0 で発散せず)。tick2 range=3.5:
    diverged=(3.5-min_seen 2.0)=1.5>1.0 ∧ incremented=(3.5-prev 2.0)=1.5>0.3 ∧
    cur 3.5<5.0 -> pass。min_seen が tick1 の 2.0 に更新されていなければこの pass は
    起きない(tick0 の 3.0 基準なら diverged=(3.5-3.0)=0.5 で発散せず)。
    """
    _l0, s0 = t1.t1_state(8.0, 3.0, prev_t1=None)        # approach, min_seen=3.0
    l1, s1 = t1.t1_state(8.0, 2.0, prev_t1=s0)           # approach, min_seen updated to 2.0
    assert l1 == t1.APPROACH
    result = t1.t1_state(8.0, 3.5, prev_t1=s1)
    assert _label(result) == t1.PASS, (
        "min_seen が tick1 の 2.0 に更新されていれば (3.5-2.0)=1.5>1.0 で発散し pass。"
        "min_seen 持ち越しが効いていない疑い"
    )


def test_F006_next_state_is_consumable_as_prev_t1():
    """F-006(ADR 0017 決定3 T1・状態の往復可能性): t1_state の返り値の次状態は、その後の
    呼び出しの prev_t1 にそのまま渡せる(状態を外から注入・取得できる形)。

    返り値が2要素(label, next_state)で、next_state を prev_t1 に渡してエラーなく次の
    label が得られることを固定する(状態の受け渡し API 契約)。内部表現の中身には
    踏み込まない(ADR 0017 が型を規定しないため)。
    """
    result0 = t1.t1_state(8.0, 30.0, prev_t1=None)
    assert isinstance(result0, tuple) and len(result0) == 2, (
        "t1_state は (label, next_state) の2要素タプルを返すべき"
    )
    label0, state0 = result0
    assert isinstance(label0, str)
    # 次状態を prev_t1 に注入して連鎖できること。
    label1, state1 = t1.t1_state(8.0, 30.0, prev_t1=state0)
    assert isinstance(label1, str)
    # さらに連鎖できること(状態が壊れない)。
    label2, _state2 = t1.t1_state(8.0, 30.0, prev_t1=state1)
    assert isinstance(label2, str)


# ===========================================================================
# track 無し: min_range_m=100.0(ADR 0017 決定3 T1 入力定義)
# ===========================================================================

def test_F006_no_track_min_range_100_is_idle_when_ttc_high():
    """F-006(ADR 0017 決定3 T1・track 無し): track 無しは min_range_m=100.0 を与える
    (入力定義)。ttc_s が高ければ idle。

    track 無し(min_range 100.0)・ttc 大(99.0 >= 12)なら tick0 で idle。min_range は
    発散判定に使われるが prev=idle/tick0 では閾値のみなので idle。
    """
    assert _label(t1.t1_state(99.0, 100.0, prev_t1=None)) == t1.IDLE


# ===========================================================================
# 出力語彙は v1.4 t1_state(idle / approach / pass / depart)— ADR 0006 / 0012
# ===========================================================================

def test_F006_t1_output_is_v14_vocabulary():
    """F-006(ADR 0017 決定3 T1 + ADR 0006/0012 語彙): t1_state の出力ラベルは v1.4 4クラス
    {idle, approach, pass, depart} のいずれかのみ。

    tick0 と approach 系列の代表点で語彙集合に閉じることを確認する(enum の stop/repeat は
    採点語彙外・ADR 0017 決定3 注記)。
    """
    v14_t1 = {"idle", "approach", "pass", "depart"}
    # tick0 群
    for ttc_s, min_range in [(8.0, 30.0), (20.0, 30.0), (1.0, 3.0)]:
        label = _label(t1.t1_state(ttc_s, min_range, prev_t1=None))
        assert label in v14_t1, (
            f"tick0 t1_state({ttc_s}, {min_range}) が v1.4 語彙外: {label!r}"
        )
    # approach -> pass / depart
    _l0, s_close = t1.t1_state(8.0, 3.0, prev_t1=None)
    assert _label(t1.t1_state(8.0, 4.5, prev_t1=s_close)) in v14_t1
    _l1, s_far = t1.t1_state(8.0, 9.0, prev_t1=None)
    assert _label(t1.t1_state(8.0, 10.5, prev_t1=s_far)) in v14_t1


def test_F006_t1_exposes_v14_label_constants():
    """F-006(契約面・ADR 0006/0012/0017): t1 は v1.4 t1_state 語彙
    idle/approach/pass/depart をラベル定数として公開し、その値がそれぞれの文字列であること。
    """
    expected = {
        "IDLE": "idle",
        "APPROACH": "approach",
        "PASS": "pass",
        "DEPART": "depart",
    }
    for name, value in expected.items():
        assert hasattr(t1, name), f"t1.{name} が公開されていない"
        assert getattr(t1, name) == value, (
            f"t1.{name} の値が '{value}' でない(v1.4 語彙 faithfulness 違反)"
        )


# ===========================================================================
# 決定性(同入力・同 prev 状態で2回呼んで同一ラベル・乱数で揺れない)
# ===========================================================================

def test_F006_t1_is_deterministic_same_label_twice():
    """F-006(決定性): 同じ (ttc_s, min_range_m, pw_anom, prev_t1) で2回呼ぶと同一ラベル
    (乱数で揺れない)。

    T1 状態機械はルール判定であり学習・乱数を含まない。tick0・prev=idle・prev=approach
    の代表点で完全一致を確認する。prev 状態は同じ前状態オブジェクトを使い回す。
    """
    _l0, idle_state = t1.t1_state(20.0, 30.0, prev_t1=None)
    _la, approach_state = t1.t1_state(8.0, 3.0, prev_t1=None)
    cases = [
        (8.0, 30.0, 0.0, None),
        (20.0, 30.0, 0.0, None),
        (13.0, 30.0, 0.5, None),
        (8.0, 30.0, 0.0, idle_state),
        (8.0, 4.5, 0.0, approach_state),
    ]
    for ttc_s, min_range, pw_anom, prev in cases:
        first = _label(t1.t1_state(ttc_s, min_range, pw_anom=pw_anom, prev_t1=prev))
        second = _label(t1.t1_state(ttc_s, min_range, pw_anom=pw_anom, prev_t1=prev))
        assert first == second, (
            f"t1_state({ttc_s}, {min_range}, pw_anom={pw_anom}) が2回で不一致: "
            f"{first!r} != {second!r}"
        )
