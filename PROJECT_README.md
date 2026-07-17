# NS-EPI L4 supreme（新アーキ）

> 注: ルートの `README.md` はオーケストレーション・テンプレートの運用マニュアル（CLAUDE.md から参照）。
> 本ファイルが**このプロジェクト自体**の README。

## 何を作るか（SPEC.md より）

baseline と独立に作る、同じ EPI 入出力契約を満たす新アーキ `supreme`。
弱い5項目（mode / relation / T3 / Scene regime / Quality regime）を「ルール改良＋少量学習の項目別混合」で底上げし、
強い項目（T0 / T1 / role / Anomaly）は baseline 実証ロジックを流用して守り、
**汚染ゼロの封印テスト**で baseline と同一土俵・項目別に勝敗を測る。

### 解決する問題

旧 supreme は20件のAI生成データに学習を盛りすぎ（最大ヘッド30k params ÷ 20件）、評価シナリオを学習に混入させて
0.828 を出した＝実力でなく丸暗記（部分メモライズ）。本プロジェクトは正しい手順
（データ規律＋汚染ゼロ封印評価）で、baseline を**フェアに**超える。

### 成功基準（項目別勝敗）

平均でなく**項目ごと**に判定する: 弱い5項目で supreme > baseline（封印再計測値）∧ 強い項目の低下が許容幅以内。

## 実装ブロッカー（着手前に要解決・SPEC.md「未決定事項」）

| ID | 内容 | ブロックされる機能 |
| --- | --- | --- |
| U7 | EPI 入出力契約の実体（契約バージョン表記も SPEC 内で v1.3 / v1.4 が混在・要確認） | F-006 以降ほぼ全て |
| U10 | 評価指標の正確な定義（フレーム/系列・macro/micro・正解率式） | F-004 / F-013 |
| U5 | 誤差許容幅 ε の数値（U23 環境一致と連動） | F-004 / F-013 |

## 技術スタック（暫定・U13）

- 言語: Python（>= 3.10）/ テスト: pytest — **SPEC.md U13 により暫定値**。確定時に選定理由を `decisions/` に記録する。
- PyTorch は未導入。学習が必要な機能の着手時に U13/U23 の決定とあわせて追加する。

## ディレクトリ

```
specs/      仕様・テスト戦略・アーキ図・進捗(status.json)
src/supreme/  supreme 本体（自己完結・baseline へ実行時非依存）
tests/      受け入れテスト（test-writer が作成。命名: test_<F-ID>_<観点>.py）
reports/    監査レポート・worklog
decisions/  ADR（設計判断の記録）
```

## 開発の進め方

機能単位（F-001〜F-014）で `/start-feature <機能ID>` により
spec-reviewer → test-writer → implementer → auditor のループを回す。詳細は `WORKFLOW.md` と `README.md`（運用マニュアル）。

進捗は `specs/status.json` が唯一の正。`/dashboard` で `dashboard.html` を再生成して可視化する。
