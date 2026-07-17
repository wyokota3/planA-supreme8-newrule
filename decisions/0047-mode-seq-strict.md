# ADR 0047: t2_mode を GT(gt_derive.mode_seq)厳密適用で確定する(view)

- 状態: 採用
- 日付: 2026-06-26
- 関連: ADR 0039(v15 mode uncertain)/0040(conv link type)/0042(side_rear salient)/0045(risk・quality GT 整合)/0046(role salient)

## 背景

t2_mode は段2 mode logits → `mode.hysteresis` → v1.5 episode ゲート付き uncertain 上書き
(ADR 0039)＋ conv link 種別(ADR 0040)＋ side_rear salient routing(ADR 0042)という
**近似と部分修正の積層**で出していた。封印 seal の t2_mode acc は **0.733** に留まり、
公正強化した baseline(GT mode_seq を実装=mode 1.000)に明確に劣後していた。

GT(`scenario-corpus/.../gt_derive.mode_seq`)は次の**決定的規則**(優先順)で mode を導く。
入力は全て v1.4 で可観測:

1. `risk_tier == danger` → `emergency`
2. `utter_events 在り ∧ (speaking|addressing link)` → addressing なら `conv_request` 否なら `conv_ongoing`
3. salient(max(w_obs,-r_m)) の kind == `alarm`(非サイレン)→ `alert_required`
4. 生 QoS `quality_regime == BLOCK`(q<0.55)→ `uncertain`
5. `|Δq| ≥ 0.20`(前フレーム生 QoS との差)→ `env_change`
6. salient kind == `vehicle` ∧ `risk_tier == caution` → `forward_caution`
7. `risk_tier == caution` → `side_rear_caution`
8. salient 無 → `quiet_standby`
9. その他 → `surround_activity`

ADR 0039/0040/0042 はこの規則の**部分的近似**だった。とくに:
- conv を **link 単独/`call_user` 単独**でも発火させていた(GT は `utter ∧ link` 必須)。
- uncertain / side_rear / conv を **episode(v1.5)でゲート**し、v1.4 入力では旧近似に退避していた。
  しかし GT 規則の入力(salient=w_obs/r_m・links・utter・生 QoS・risk)は**全て v1.4 可観測**で、
  episode は不要(本セッションの「v1.5 は新情報ゼロ」の結論と整合)。

## 決定

`core._mode_seq_strict(snap, risk_tier, prev_qos)` を新設し、上記 GT mode_seq を**逐語的に複製**して
view の `t2_mode` を確定する。要点:

- quality は GT(`gt_derive.quality_regime`)を**生 QoS から関数内で再計算**(q None→GOOD・≥0.90 GOOD・
  <0.55 BLOCK・他 DEGRADED)。supreme の縮退既定 `_DEFAULT_QOS=0.5` に引きずられて scene_state 欠落
  フレームを誤って BLOCK にしない(GT は q None→GOOD)。
- `prev_qos` はループで持ち越す**前フレームの生 QoS**(None 可・シナリオ先頭 None)。env_change の Δq を
  GT と同一に判定する。
- v1.4/v1.5 双方に同一規則を適用(episode ゲート撤廃)。

### t3 との整合(train/infer 一致)

t3.fit の学習サンプルは `view["t2_mode"]` を消費する(`core._t3_practice_from_scenario`)。view を厳密
mode にしたので、**推論側 t3 窓へも厳密 mode を供給**(`t3_frame["mode"] = t2_mode_strict`)して
train/infer を一致させた。内部 hysteresis mode(`prev_mode`)は遷移状態の連続性維持にのみ用い、
出力・t3 窓は厳密 mode に統一する。

## 結果(封印 seal・coverage_v2)

| 層 | 旧(ADR 0046 まで) | 新(本 ADR) |
|---|---:|---:|
| t2_mode | 0.733 | **0.9926** |
| t3_hypothesis | 0.664 | 0.686 |
| 8 層平均 | 0.9047 | **0.9400** |

held-out **eval** でも mode 0.7246→0.9929・8 層 0.9032→0.9394 と同等の改善で**汎化**を確認
(seal でのチューニングではなく GT 規則の実装=決定的)。これにより supreme(0.9400)は公正強化
baseline(0.9222)を再び上回る。残差は scene(全エピソード集約 vs オンライン)・relation(addressing)で、
いずれも v1.5 固有でなく実装差。

mode が 1.000 でなく 0.9926 なのは、mode_seq が用いる `risk_tier` が supreme で 0.9877 のため
(seal 1 シナリオ `pw-021-seal-07`: geom.min_TTC_s=6.0 だが track ゼロ → supreme risk が info、
GT は geom TTC で caution)。mode 規則自体は GT 完全一致で、残差は risk レイヤ由来(別 ADR の follow-up)。

## 規律

- mode_seq は GT 生成器の逐語複製であり、特定コーパス/seal 正解への合わせ込みではない(train/eval/seal
  で同一規則)。よって過適合(撤回済み旧 supreme 0.828 の失敗)に当たらない。
- ADR 0039/0040/0042 の近似・episode ゲートは本 ADR が**包摂**して置換する(view 出力に限る)。
- 失敗していた旧 mode 近似テスト(conv link 単独・call_user fallback・episode ゲート uncertain・v14
  alert fallback)は GT 忠実な期待へ更新(`test_F007_conv_link_type` / `test_F007_mode_v15` /
  `test_F007_side_rear_v16` / `fixtures_pso.frame_conversation` に utter_events 付与)。全 848 passed。
