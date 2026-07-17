"""F-006: T1 t1_state 状態機械層(t1)。

supreme の T1 t1_state 判定。入力 = (ttc_s, min_range_m, pw_anom, prev_t1)、出力 =
(v1.4 t1_state ラベル, 次 tick へ渡す状態)。証拠抽出・HGF・softmax/EMA は上流の共有
基盤でありスコープ外(ADR 0017 決定2)。pw_anom は入力パラメータ(上流供給・既定 0)。

契約の最終根拠は specs/SPEC.md「F-006」節、decisions/0017-f006-strong-reimplementation.md
(手法の正・独立再実装)、decisions/0012(t1_state 4クラス)/0006(v1.4 語彙)、および
tests/test_F006_t1_state.py。

状態機械(ADR 0017 決定3 T1):
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
  語彙 v1.4: idle / approach / pass / depart。

決定的(乱数・時刻なし)な純関数。状態は引数(prev_t1)で外から注入し、返り値で取得
する(エピソード状態を内部に隠し持たない)。本モジュールは stdlib のみに依存し、
datagov/sealset/augment/guard/harness/quality/mode/relation を改修しない。
"""

from __future__ import annotations

from collections import namedtuple


# ---------------------------------------------------------------------------
# v1.4 t1_state 統制語彙(ADR 0006 / 0012)のラベル定数。値は自身の文字列。
# ---------------------------------------------------------------------------

IDLE = "idle"
APPROACH = "approach"
PASS = "pass"
DEPART = "depart"


# ---------------------------------------------------------------------------
# 機構定数(ADR 0017 決定3 T1・baseline/planA 計測値)。
# ---------------------------------------------------------------------------

_TTC_BASE = 12.0          # ttc_threshold の基準。
_TTC_CLAMP_MAX = 15.0     # ttc_threshold のクランプ上限。
_PW_COEF = 3.0            # pw_anom の閾値寄与係数。

_DIVERGE_MARGIN = 1.0     # diverged: (cur - min_seen) > 1.0。
_INCREMENT_MARGIN = 0.3   # incremented: (cur - prev_range) > 0.3。
_PASS_CLOSE = 5.0         # pass: cur < 5.0(近距離発散)。
_DEPART_FAR = 10.0        # depart: cur > 10.0(遠距離発散)。


# 次 tick へ持ち越す状態。min_seen=過去 tick の最小 range、prev_range=直前 tick の
# range、in_approach=直前 tick の出力が approach 系か(prev=approach 分岐の判定)。
_State = namedtuple("_State", ["min_seen", "prev_range", "in_approach"])


def t1_state(ttc_s, min_range_m, pw_anom=0.0, prev_t1=None):
    """T1 状態機械を 1 tick 進めて (label, next_state) を返す(ADR 0017 決定3 T1)。

    prev_t1=None は tick0(前状態無し)。返り値の次状態をそのまま次呼び出しの prev_t1 に
    渡して連鎖する(状態を外から注入・取得できる形)。

    Args:
        ttc_s: min_TTC(秒)。
        min_range_m: 全 track の最小 r_m(track 無しは 100.0 を与える)。
        pw_anom: precision_weight_anom(上流供給・既定 0)。
        prev_t1: 前 tick の状態(本関数が返した次状態)。None は tick0。

    Returns:
        (v1.4 t1_state ラベル, 次 tick へ渡す状態) の 2 要素タプル。
    """
    cur = float(min_range_m)
    ttc_threshold = _clamp(_TTC_BASE + float(pw_anom) * _PW_COEF, _TTC_BASE, _TTC_CLAMP_MAX)
    appr = float(ttc_s) < ttc_threshold

    if prev_t1 is None:
        # tick0: 閾値のみ(pass/depart は出さない)。
        label = APPROACH if appr else IDLE
        return label, _State(min_seen=cur, prev_range=cur, in_approach=appr)

    prev_min_seen = prev_t1.min_seen
    prev_range = prev_t1.prev_range
    in_approach = prev_t1.in_approach

    if in_approach:
        # prev=approach: 発散判定(pass/depart)→ 不発なら閾値判定。
        min_seen = min(prev_min_seen, cur)
        diverged = (cur - min_seen) > _DIVERGE_MARGIN
        incremented = (cur - prev_range) > _INCREMENT_MARGIN
        if diverged and incremented and cur < _PASS_CLOSE:
            return PASS, _State(min_seen=min_seen, prev_range=cur, in_approach=False)
        if diverged and incremented and cur > _DEPART_FAR:
            return DEPART, _State(min_seen=min_seen, prev_range=cur, in_approach=False)
        # 発散せず: 閾値で approach / idle。
        label = APPROACH if appr else IDLE
        return label, _State(min_seen=min_seen, prev_range=cur, in_approach=appr)

    # prev=idle: 閾値のみで approach / idle(発散判定は行わない)。
    label = APPROACH if appr else IDLE
    return label, _State(min_seen=min(prev_min_seen, cur), prev_range=cur, in_approach=appr)


def _clamp(value, lo, hi):
    """value を [lo, hi] にクランプする。"""
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value
