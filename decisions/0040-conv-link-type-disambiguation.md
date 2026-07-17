# ADR 0040: conv_ongoing / conv_request を link type で分離(mode 最大の取りこぼし是正)

- 日付: 2026-06-25
- ステータス: 採用
- 関連: F-007(mode)・F-009(t3)・`ROADMAP-v1.6.md`(A 項)・ADR 0031(call_user→conv_request)・ADR 0040 前段の v1.5 mode(uncertain)。
- エビデンス: coverage_v2(v1.5) train/eval・coverage_v1(v1.4) train/eval・全831テスト緑。

## 背景

mode 残最大の取りこぼしは **conv_ongoing の全滅**だった。coverage_v2/train 診断:

| GT | n | 旧 pred(混同先) | link type 署名 |
|---|---:|---|---|
| conv_ongoing | 325 | conv_request 245 / uncertain 80(**正解 0**) | 全件 `speaking`(addressing 無) |
| conv_request | 224 | conv_request 164 / uncertain 60 | 全件 `addressing` |

旧 `_mode_logits` は conv_ongoing を **conv_strong**(`has_speech ∧ speaking_prob>0.7 ∧ min_range<5`)でしか
立てず、corpus の speaking **link** を見ていなかった。conv_ongoing は call_user を持つため、
`call_user→conv_request`(ADR 0031)ゲートで **conv_request へ全流出**。加えて v1.5 の低 QoS→uncertain
上書きが conv フレーム 140 件を奪っていた。link type は両クラスを**完全分離**する(conv_ongoing は
addressing link を持たない)。

## 決定

link type を conv 種別の**一次識別子**に格上げ(`core._mode_logits`):
- `addressing` link → **conv_request**(優先)。
- `speaking` link(addressing 無)or 強会話(conv_strong) → **conv_ongoing**。
- link 無の旧入力で `call_user` → **conv_request**(v1.4 fallback・従来挙動保持)。

```python
want_ongoing = conv_strong or (has_speaking_link and not has_addressing_link)
want_request = has_addressing_link or (call_user and not has_speaking_link)
conv_request_fires = want_request and not want_ongoing and risk_tier != DANGER
```

- caution の `alert_required` 抑止を conv_request だけでなく **conv_ongoing にも対称拡張**
  (`elif CAUTION and not conv_request_fires and not want_ongoing`)。会話文脈は caution alert を支配。
- 低 QoS→uncertain 上書きは **conv 確定(conv_ongoing/conv_request)には掛けない**(conv link が在る=
  会話文脈は観測済み＝「文脈断定不能」でない)。

**後方互換に関する明示的判断**: link は v1.4 入力にも在るため、本修正は **v1.4 経路の mode も変える**
(v1.5 presence-gate しない)。これは観測可能な link type を使う**真の改善**であり、`ROADMAP-v1.6.md` A 項で
意図的に採った方針。v1.4「不変」前提は本 ADR で**改善方向に意図的に更新**する(回帰でなく前進)。

## 結果(train / eval・held-out)

| | v1.5 TRAIN | v1.5 EVAL | v1.4 TRAIN | v1.4 EVAL |
|---|---:|---:|---:|---:|
| t2_mode | 0.508→**0.678** | 0.504→**0.662** | ~0.57→**0.648** | ~0.57→**0.621** |
| t3_hypothesis | 0.637→**0.689** | 0.618→**0.681** | — | — |
| **8層平均** | 0.753→**0.781** | 0.749→**0.776** | 0.631→**0.656** | 0.631→**0.650** |

- conv_ongoing **325/325・130/130**、conv_request **224/224・93/93**(train/eval とも完全)。
- eval(held-out)が train と同等に伸び＝**過適合でない真の信号**。t3 conv_participating も連動改善。
- 全831テスト緑(既存826＋conv link-type 5)。seal 合わせ込みなし(seal 最終確認は別途1回)。

## 限界(正直に)

- conv は coverage 上ほぼ天井(link type が一意分離)。残 mode 伸びしろは side_rear_caution(生成器・ROADMAP B)と
  env_start(契約 v1.6 qos_variance・ROADMAP C)。
- link type に依存するため、link を出さない実データ入力では conv_strong/call_user fallback に縮退する(設計通り)。
