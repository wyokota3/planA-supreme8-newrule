# Phase 4 診断 — 観測式/HGF は t3_hypothesis に効くか

- 生成時刻: 2026-06-14 22:03
- 対象: v021_core 20 シナリオ(in-sample 診断)
- src/supreme/*.py 無改変・分析専用。supreme 公開 API + core 内部関数の import 再利用のみ。
- baseline 非 import・決定的・stdlib。

## 計測1: h_q 分布(GT quality クラス別)— ADR 0014 積み残し(h_q 過敏)の確認

| GT quality | n | h_q min | median | max | mean |
|---|---:|---:|---:|---:|---:|
| GOOD | 154 | 0.5944 | 0.9407 | 0.9491 | 0.9286 |
| DEGRADED | 32 | 0.1849 | 0.8267 | 0.9418 | 0.7837 |
| BLOCK | 24 | 0.0023 | 0.2576 | 0.8241 | 0.3217 |

**quality 混同(GT 行 → h_q,vol→classify 予測 列):**

| GT＼予測 | BLOCK | DEGRADED | GOOD |
|---|---:|---:|---:|
| GOOD | 0 | 43 | 111 |
| DEGRADED | 4 | 25 | 3 |
| BLOCK | 16 | 8 | 0 |

## 計測2: t3 への h_q 寄与(感度実験)

**実験A(直接経路)**: t3 に渡す mode 列の posterior(h_q)だけを 0.0 / 1.0 に置換し
(mode ラベルは固定)、t3 hypothesis 列が変わるフレーム数を数える。

- posterior を 0/1 に振っても t3 が変わったフレーム: **19 / 420**

**実験B(間接経路 h_q→mode→t3)**: h_q<0.5 で env_change logit を積む `_mode_logits` 経路。
h_q を全フレーム 1.0 固定で mode を再計算し、mode 差と t3 差を数える。

- h_q=1 固定で変わった mode フレーム: **11 / 210**
- その mode 差が t3 を変えたフレーム: **22 / 210**

## 計測3: t3 入力の証拠品質(GT t3 クラス別 h_q 分布)

| GT t3_hypothesis | n | h_q min | median | max |
|---|---:|---:|---:|---:|
| quiet_stable | 84 | 0.4314 | 0.9428 | 0.9491 |
| conv_participating | 29 | 0.3502 | 0.9460 | 0.9466 |
| traffic_unstable | 23 | 0.8576 | 0.9387 | 0.9450 |
| sustained_alert | 23 | 0.0023 | 0.8022 | 0.9456 |
| env_shift | 15 | 0.7384 | 0.9205 | 0.9415 |
| crowd_tendency | 14 | 0.7891 | 0.9076 | 0.9380 |
| uncertain_context | 9 | 0.0023 | 0.0871 | 0.5297 |
| env_start | 7 | 0.6582 | 0.9267 | 0.9417 |
| alert_required | 4 | 0.6192 | 0.9371 | 0.9405 |
| hazard_declining | 2 | 0.8225 | 0.8391 | 0.8557 |

---

_分析専用(src 無改変・baseline 非 import・決定的)。_