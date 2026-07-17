# ADR 0042(v1.6): caution mode を salient kind で分岐(side_rear_caution の死クラス解消)

- 日付: 2026-06-25
- ステータス: 採用
- 関連: F-007(mode)・`ROADMAP-v1.6.md`(B 項)・ADR 0040(conv link type)・ADR 0033(salient_kind 抽出)。
- エビデンス: coverage_v2 train/eval(held-out)・coverage_v1(v1.4) 不変・全840テスト緑。

## 背景

roadmap B は「生成器が rear 幾何(theta>90)を emit せず、supreme が theta で検出できない」と仮説したが、
**GT 導出を確認すると誤り**だった。`gt_derive.mode_seq` の side_rear_caution は **theta 非依存**:

```
danger→emergency / conv / alarm→alert_required / BLOCK→uncertain / Δq→env_change /
vehicle+caution→forward_caution / caution(else)→side_rear_caution / none→quiet / surround
```

side_rear_caution は **caution risk で salient が非車両・非警報**のときの GT。真因は生成器でなく **supreme**:
supreme は caution を**一律 alert_required**にしており(`_mode_logits`)、forward_caution/side_rear_caution を
構造的に潰していた。特に **side_rear_caution は emit 経路がゼロ=死クラス**(surround_activity と同型の構造潰し)。

coverage_v2 診断(GT vs supreme pred・salient kind):

| GT | n(tr/ev) | salient | 旧 pred | あるべき |
|---|---|---|---|---|
| side_rear_caution | 52/25 | object(37/19) / None(15/6) | **alert_required / quiet** | object→side_rear |
| forward_caution | 26/12 | vehicle | **alert_required**(全) | vehicle→forward |
| alert_required | 150/70 | alarm | alert / uncertain | alarm→alert(維持) |

## 決定

`core._mode_logits` の caution 分岐を **salient kind ルーティング**に置換(salient_kind は ADR 0033 で抽出済み):
- `vehicle` → **forward_caution**
- `object` / `human` → **side_rear_caution**(`_MODE_SIDE_REAR`)
- それ以外(`alarm` 等)→ **alert_required**(従来)
- **salience 不在(v1.4)は None → alert_required** で従来挙動を保つ(後方互換)。

side_rear_caution は非安全 mode(hysteresis で block 減衰されるが多フレームで持続=遷移する)。GT 規則の
salient 分岐を観測 salient kind で忠実化しただけ(過適合でない)。残 None(salient 無)の側後方は回収不能。

## 結果(train / eval・held-out)

| | TRAIN | EVAL(held-out) | SEAL(A+B+C 累積) |
|---|---:|---:|---:|
| t2_mode | 0.678→**0.710** | 0.662→**0.699** | **0.706** |
| t3_hypothesis | 0.738→**0.748** | 0.731→**0.744** | **0.738** |
| **8層平均** | 0.787→**0.792** | 0.783→**0.789** | 0.781→**0.7865** |

- side_rear_caution **37/37・19/19 完全回収**(object+caution)・forward_caution も同時回収(vehicle+caution)。
- alarm→alert_required 維持(回帰なし)。**v1.4 完全不変**(coverage_v1 mode 0.648/0.621・B 前後同値)。
- roadmap B 推定(~0.0004)を大きく超過=forward_caution も死んでいたため。全840テスト緑(+side_rear v16 5件)。

## 限界(正直に)

- side_rear_caution の残 15/6f は salient 無(空フレーム・risk=info)で回収不能(観測に対象が無い)。
- これで v1.6 ROADMAP の A/B/C 完了。残る低層は t1_state(0.60)/relation(0.66)で、軌跡の細かい弁別=
  合わせ込みは過適合のため不追求。hazard_declining は原理天井(ADR 0041)。
