# ADR 0048: risk_tier を GT 厳密適用し track ゼロでも geom TTC を読む

- 状態: 採用
- 日付: 2026-06-26
- 関連: ADR 0045(risk・quality を GT 整合・純TTC)/0047(mode GT mode_seq 厳密化)

## 背景

ADR 0045 で risk_tier を純 TTC 規則(siren→danger / ttc<2→danger / ttc<8→caution / else info)に
是正したが、封印 seal の risk_tier acc は **0.9877** に留まっていた。残差はすべて **1 シナリオ
`pw-021-seal-07`**(frame 0–4)に集中:

```
pw-021-seal-07[0..4] pred=info gt=caution ttc=6.0 audio=[]
```

`geom.min_TTC_s=6.0`(<8=caution)だが **track がゼロ**(audio/objects/humans 空)。supreme は
`risk_tier = t0_mod.risk_tier(_t0_tracks(snap))` で risk を出すが、`_t0_tracks` が空列を返すと
`t0.risk_tier` は主トラック無で安全側 `info` に縮退し、**geom TTC を読み落とす**。

一方 GT(`gt_derive.risk_tier`)は **track 非依存**で `geom.min_TTC_s` を読む:

```python
def risk_tier(frame):
    s = _salient(frame)
    if s and s["kind"] == "siren": return "danger"
    ttc = frame["geom"]["min_TTC_s"]
    if ttc is None: return "info"
    if ttc < 2.0: return "danger"
    if ttc < 8.0: return "caution"
    return "info"
```

geom TTC は track の有無に関係なく観測される量なので、track ゼロでも読むのが正しい。

この 0.74% の risk 取りこぼしは **mode にも波及**していた(mode_seq が risk_tier を使うため、
caution を取りこぼすと mode も `side_rear_caution` を落とす)。ADR 0047 で mode を厳密化しても
mode acc が 1.000 でなく 0.9926 だったのは、この risk 残差が唯一の原因。

## 決定

`core._risk_tier_strict(snap)` を新設し、GT `risk_tier` を**逐語複製**して view の risk_tier を確定する:

- siren salient(`_salient_track_geom` の kind==siren)→ danger
- 生 `geom.min_TTC_s` が None → info / <2.0 → danger / <8.0 → caution / else info
  (閾値 `t0._TTC_DANGER_S`/`_TTC_CAUTION_S` を共有=ADR 0045 と一貫)

`t0.risk_tier`/`_t0_tracks` 自体は変更しない(空 track→info の縮退は他用途のため温存)。view 結線のみ
`risk_tier = _risk_tier_strict(snap)` に差し替える。risk は `_mode_seq_strict` にも渡るため、本厳密化で
mode の risk 由来残差も同時に解消する。

## 結果(封印 seal・coverage_v2)

| 層 | ADR 0047 まで | 本 ADR |
|---|---:|---:|
| risk_tier | 0.9877 | **1.0000** |
| t2_mode | 0.9926 | **1.0000** |
| 8 層平均 | 0.9400 | **0.9424** |

held-out **eval** でも risk 1.0000・mode 1.0000・8 層 0.9394→0.9418 と同値で**汎化**(GT 規則の逐語実装=
決定的・seal 合わせ込みでない)。これで 8 層中 **5 層が完全**(risk/t1/mode/role/quality = 1.0)。残る
sub-1.0 は relation(0.961・addressing 残差)・t3(0.686)・scene(0.892)で、後二者は intent 天井層。

supreme 0.9424 は公正強化 baseline 0.9222 を上回るが、差は依然 scene(全エピソード集約)・relation・t1 の
実装差であり v1.5 固有ではない(risk/mode/role/quality はいずれも v1.4 観測規則で両系 1.0 到達可)。

## 規律

- `_risk_tier_strict` は GT 生成器の逐語複製で、特定 seal シナリオへの合わせ込みではない(track ゼロで
  geom TTC を読むという一般規則・train/eval/seal で同一)。eval でも 1.0 で汎化=過適合でない。
- 全 848 tests pass(t0 単体テストは `t0.risk_tier` 不変のため無影響・core 結線のみ差し替え)。
