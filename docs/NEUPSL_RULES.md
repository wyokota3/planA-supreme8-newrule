# supreme3 NeuPSL の論理ルール一覧(全28本)

supreme3 の T2(role / relation / mode)が使用する重み付き論理ルールの完全なリストです。
定義の実体は `src/supreme/neupsl.py` の `RULES` にあり、いずれも Łukasiewicz 緩和の
重み付き含意「体部 → 頭部」の形をとります。重みは学習対象で、下表の値は学習前の初期値です。
内訳は、mode 向け11本・role 向け7本・relation 向け5本・層間整合4本・時間持続1本です。

## mode(場の様相)への11本

| # | 論理式 | 意味 | 初期重み |
|---|---|---|---:|
| 1 | risk_danger → Mode(emergency) | T0 が危険なら様相も緊急 | 5.0 |
| 2 | risk_caution ∧ vehicle ∧ ¬ConvEv → Mode(forward_caution) | 注意状態で車両が主で会話でないなら前方注意 | 4.0 |
| 3 | risk_caution ∧ HumanSrc ∧ ¬ConvEv → Mode(side_rear_caution) | 注意状態で人・物が主なら側後方注意 | 4.0 |
| 4 | risk_caution ∧ ¬vehicle ∧ ¬ConvEv → Mode(alert_required) | それ以外の注意状態は警戒要 | 3.0 |
| 5 | ConvEv → Mode(conv_ongoing) | 近接会話の証拠があれば会話進行中 | 4.0 |
| 6 | SpkOnly → Mode(conv_ongoing) | speaking リンク優勢なら会話進行中 | 4.0 |
| 7 | AddrEv ∧ ¬SpkOnly ∧ ¬risk_danger → Mode(conv_request) | 呼びかけ証拠(進行中でも危険でもない)なら発話要求 | 4.0 |
| 8 | CrowdEv ∧ ¬ConvEv → Mode(surround_activity) | 群衆の気配(単一会話でない)なら周囲活動 | 4.0 |
| 9 | approaching → Mode(forward_caution) | 接近中なら前方注意 | 4.0 |
| 10 | LowQ → Mode(env_change) | 観測品質の劣化なら環境変化 | 4.0 |
| 11 | ⊤ → Mode(quiet_standby) | 既定は静穏(prior) | 0.8 |

## role(音の主)への7本

| # | 論理式 | 意味 | 初期重み |
|---|---|---|---:|
| 12 | siren → Role(source_alarm) | サイレンは警報源 | 2.0 |
| 13 | alarm → Role(source_alarm) | 警報音は警報源 | 2.0 |
| 14 | vehicle ∧ ¬siren ∧ ¬alarm → Role(source_vehicle) | 緊急音がなければ車両源 | 1.5 |
| 15 | SpeechSrc → Role(source_speech) | 発話者らしさがあれば発話源 | 2.0 |
| 16 | HumanSrc ∧ ¬SpeechSrc ∧ ¬alarm → Role(source_human) | 人らしさ(発話でない)なら人源 | 1.0 |
| 17 | ObjSrc ∧ ¬siren → Role(source_object) | 物体らしさがあれば物体源 | 1.0 |
| 18 | ⊤ → Role(unknown) | 既定は不明(prior) | 0.6 |

16・17 は supreme2 では構造的に出力不能だった source_human / source_object への新設ルートです
(本評価で role が全システム最高値 0.6929 になった主因)。

## relation(ユーザーとの関係)への5本

| # | 論理式 | 意味 | 初期重み |
|---|---|---|---:|
| 19 | AddrEv → Rel(addressing_user) | 呼びかけ証拠があれば宛先はユーザー | 2.5 |
| 20 | approaching → Rel(approaching) | 接近中なら接近関係 | 2.0 |
| 21 | ConvEv → Rel(near_user) | 近接会話なら近傍関係 | 1.5 |
| 22 | CrowdEv → Rel(grouped) | 群衆なら集団関係 | 2.0 |
| 23 | ⊤ → Rel(grouped) | 既定は集団(prior) | 0.6 |

## 層間整合の4本(supreme2 ではハードコードだった結線の宣言化)

| # | 論理式 | 意味 | 初期重み |
|---|---|---|---:|
| 24 | Mode(conv_ongoing) → Role(source_speech) | 会話中なら主は発話者のはず | 1.0 |
| 25 | Mode(emergency) → Role(source_alarm) | 緊急なら主は警報源のはず | 1.0 |
| 26 | Mode(conv_request) → Rel(addressing_user) | 発話要求なら宛先はユーザーのはず | 1.0 |
| 27 | Mode(surround_activity) → Rel(grouped) | 周囲活動なら集団関係のはず | 1.0 |

## 時間持続の1本(ヒステリシスの PSL 化)

| # | 論理式 | 意味 | 初期重み |
|---|---|---|---:|
| 28 | Mode(f−1, m) → Mode(f, m) | 前フレームの様相は続きやすい | 1.2 |

28 番は重みとしては1本ですが、推論時には「(フレーム数 − 1)× 9 モード」ぶん接地され、
これがシナリオ全体を一つの結合 MAP 問題にしています。

## 補足: 式に登場する原子(atom)と意味論

これらの式に登場する原子は次の3種類です。

- **観測述語 12 個**(入力の値をそのまま真理値として使う): siren / alarm / vehicle / speech /
  risk_danger / risk_caution / approaching / call_user / addr_link / spk_link / humans_n / objects_n
- **ニューラル述語 9 個**(微小 MLP が生特徴から軟真理値を出力し、学習される): ConvEv(近接会話らしさ)/
  AddrEv(呼びかけらしさ)/ SpkOnly(speaking リンク優勢)/ CrowdEv(群衆らしさ)/ NearEv(至近らしさ)/
  SpeechSrc(主が発話者らしい)/ HumanSrc(主が人らしい)/ ObjSrc(主が物体らしい)/ LowQ(品質劣化)
- **開述語(推論対象)**: Mode(9値)/ Role(6値)/ Rel(4値)

意味論は Łukasiewicz 緩和で、連言は I(A∧B) = max(0, a + b − 1)、否定は ¬a = 1 − a、
含意 A→B の違反量は max(0, I(A) − I(B)) と定義し、「重み × 違反量」の総和をエネルギーとする
HL-MRF をシナリオ単位で最小化(結合 MAP 推論)しています。
