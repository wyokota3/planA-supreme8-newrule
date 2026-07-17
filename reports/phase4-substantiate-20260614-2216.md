# Phase 4 裏付け実測 — ADR 0026 の偽陽性ゼロ・tau plateau を計測で確定

- 生成時刻: 2026-06-14 22:16
- 対象: v021_core 20 シナリオ / 210 フレーム(CV held-out が正準)
- 目的: 監査 audit-20260614-2205-Phase4.md の R2(tau plateau 未裏付け)・R3(偽陽性ゼロ未裏付け)を実測で確定する。
- src/supreme/*.py 無改変・分析専用。supreme 公開 API + core 内部関数の import 再利用のみ。
- baseline 非 import・決定的・stdlib+pyyaml。src の実ゲート閾値 = 0.4。
- ゲート再現の自己検査: tau=0.40 で pre-gate+ゲート再現列が src の run_t3_sequence と**全シナリオ完全一致**(再現の正しさを確認済み)。

## 計測1: 偽陽性候補(GT=env_start/env_shift ∧ posterior < tau)

ゲートは `posterior < tau ∧ base ∈ {env_start, env_shift} → uncertain_context`。GT 自体が env のフレームでこれが発火すると、**正答の env を uncertain へ巻き込む(偽陽性)**。
全 210 フレーム中 GT=env のフレーム = **22** 件(env_start + env_shift)。

src の実閾値 tau=0.4 における偽陽性候補(GT=env ∧ posterior<0.4)の件数:

### → **0 件**(偽陽性ゼロ=GT=env のフレームは 1 件も gate を踏まない)

**env クラス別 posterior(h_q)分布**(min が tau を超えれば gate を踏まない):

| GT クラス | n | posterior min | median | max | min > src tau(0.40)? |
|---|---:|---:|---:|---:|---|
| env_start | 7 | 0.6582 | 0.9267 | 0.9417 | yes |
| env_shift | 15 | 0.7384 | 0.9205 | 0.9415 | yes |

→ env_start/env_shift いずれも posterior(h_q)min が src 閾値 0.40 を上回る(最小 = 0.6582)。**GT=env のフレームは構造的に gate を踏まないため、ゲートが正答 env を uncertain へ巻き込む regression は 0(偽陽性ゼロ)が実測で確定**。

## 計測2: tau スイープ(held-out 5-fold CV t3_hypothesis acc)

ゲート閾値 tau を振り、lineage-disjoint 5-fold CV held-out(分母 210)の t3 acc を算出する。
学習 params(t3.fit の重み3+バイアス3)は tau に依らず同一(ゲートは fit に無関係なstep 後段の固定後処理)。tau で変わるのは採点時のゲート適用閾値のみ。**held-out 学習 params** で採点。

| tau | held-out 学習 acc | correct/total | fold 別 acc |
|---:|---:|---:|---|
| no-gate(結線前) | **0.4095** | 86/210 | 0.2105, 0.3182, 0.3571, 0.5439, 0.4048 |
| 0.30 | **0.4381** | 92/210 | 0.3158, 0.3182, 0.4643, 0.5614, 0.4048 |
| 0.35 | **0.4429** | 93/210 | 0.3684, 0.3182, 0.4643, 0.5614, 0.4048 |
| 0.40 ← src 実値 | **0.4429** | 93/210 | 0.3684, 0.3182, 0.4643, 0.5614, 0.4048 |
| 0.45 | **0.4429** | 93/210 | 0.3684, 0.3182, 0.4643, 0.5614, 0.4048 |
| 0.50 | **0.4429** | 93/210 | 0.3684, 0.3182, 0.4643, 0.5614, 0.4048 |
| 0.55 | **0.4429** | 93/210 | 0.3684, 0.3182, 0.4643, 0.5614, 0.4048 |

→ **ゲート利得**(no-gate 結線前 → src 閾値 0.40): 0.4095 → 0.4429 = **+0.0333**(ADR 0026 の held-out 学習 0.4095→0.4429・+0.0333 はこの 1 レポートで完結して辿れる)。

→ **plateau 実在**: tau ∈ [0.35, 0.55] の 5 点で held-out acc が **0.4429 で同値**。閾値をこの域で振っても held-out 採点は変わらない(過適合でなく平坦域)。

---

_分析専用(src 無改変・baseline 非 import・決定的)。ゲート再現は tau=0.40 で src 完全一致を自己検査済み。2 回走行で全数値完全一致(決定的)。_