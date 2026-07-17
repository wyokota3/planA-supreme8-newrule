# Claude Orchestration Template

Claude Code で「役割分離型マルチエージェント開発」を始めるためのテンプレート。

人間が**意思決定**を握りつつ、**実装の細部**はAIに任せる。そのためのワークフローを、
すぐに使える形でパッケージ化したものです。

---

## このテンプレートは何か(初めての人へ)

普通に Claude Code に「これ作って」と頼むと、AIが仕様の解釈・テスト・実装・検証を
すべて一人でやってしまい、**気づいたら自分が説明できないコードができている**という事故が起きます。

このテンプレートは、それを構造的に防ぎます。仕事を4つの役割に分け、それぞれ別のAIエージェントに担当させます。

| 役割 | エージェント | やること | やらないこと |
| --- | --- | --- | --- |
| 仕様レビュー | `spec-reviewer` | 仕様の曖昧さ・矛盾を洗い出す | 実装 |
| テスト作成 | `test-writer` | 仕様からテストを書く | 実装コードは見ない |
| 実装 | `implementer` | テストを通す実装を書く | テストの変更 |
| 監査 | `auditor` | 仕様と実装を突き合わせる | 実装 |

メインのあなた(Claude Code セッション)は**オーケストレーター**で、コードは書きません。
上の4エージェントを指揮し、要所であなた(人間)に判断を仰ぎます。

```
        あなた(人間) ── 意思決定
            │
     オーケストレーター(Claude Code メインセッション)
       ├── spec-reviewer  仕様をチェック
       ├── test-writer    テストを書く
       ├── implementer    実装する
       └── auditor        監査する
```

### この進め方で得られること

- AIに思考の射程を広げさせつつ、**意思決定は自分が握れる**
- 「説明できないコードができた」を構造的に防げる
- 仕様 → テスト → 実装 → 監査が役割分離され、**相互チェックが効く**
- 判断の理由が ADR と監査レポートとして**後から追える形で残る**

---

## 5分で全体像をつかむ

開発は4つのフェーズで進みます。**前半2つは外部チャット(ChatGPT / Claude チャット)、後半2つは Claude Code** で行うのがポイントです。

```
[フェーズ0] アーキテクチャ議論       → 外部チャット
   ↓  .prompts/phase0_architecture_kickoff.md
[フェーズ1] 仕様生成(SPEC / TEST)  → 外部チャット
   ↓  .prompts/phase1_spec_generation.md
[フェーズ2] 環境構築                 → Claude Code  /setup-env
   ↓
[フェーズ3] 実装ループ               → Claude Code  /start-feature F-001, F-002, ...
   ↓
[フェーズ4] 仕様変更(必要時)        → 外部チャット → Claude Code
       .prompts/spec_update.md
```

> **なぜ仕様作りを外部チャットで?**
> 実装中の Claude Code セッションには既存実装のコンテキストが乗っているため、そこで仕様を議論すると
> 「今あるコードを変えやすい方向」に判断が引きずられます。設計はまっさらな場で行うのが鉄則です。

---

## クイックスタート

```bash
# 1. このテンプレートから新規リポジトリを作成
gh repo create my-new-system \
  --template <あなたのユーザー名>/claude-orchestration-template \
  --private --clone
cd my-new-system

# 2. 外部チャット(ChatGPT / Claude チャット)で仕様を作る
#    -> .prompts/phase0_architecture_kickoff.md と
#       .prompts/phase1_spec_generation.md を順に使う

# 3. 生成された SPEC.md と TEST_STRATEGY.md を specs/ に配置

# 4. Claude Code で実装開始
claude
> /set-plan max5      # 利用プランに合わせてモデル設定(pro/max5/max20)
> /setup-env          # 初期スカフォールド構築(status.json と dashboard.html も生成)
> /spec-review        # 仕様の曖昧さチェック(推奨)
> /start-feature F-001 # 機能単位で実装ループ
```

> **プランを最初に設定する:** 既定は `max5`。Pro プランなら `/set-plan pro`、Max20 なら `/set-plan max20`。
> 全部を Opus で回すと Pro の制限を即消費するため、最初に合わせておく(詳細 `docs/VISUALIZATION.md`)。

以下、各フェーズの詳しい手順です。

---

## フェーズ0: アーキテクチャ議論

**場所:** ChatGPT または Claude チャット(claude.ai)。Claude Code ではありません。

**やること:** 作りたいシステムを、AIにインタビューしてもらいながら設計を固める。

**手順:**
1. ChatGPT または Claude チャットを新規で開く
2. `.prompts/phase0_architecture_kickoff.md` の「---」以下を貼り付け
3. 最後に「作りたいシステム」を1〜3行で書く
4. インタビューに答えていく
5. 議論が網羅されたとAIが判断すると、中間まとめが提示される
6. 中間まとめに納得したら、フェーズ1へ

**終わったとき:** チャット履歴にアーキテクチャ議論が一通り溜まっている状態。
ファイル成果物はまだありません。次のフェーズで成果物にします。

---

## フェーズ1: 仕様生成

**場所:** フェーズ0と同じチャット内(履歴を引き継ぐため)。

**やること:** 議論の内容を整理し、`SPEC.md` と `TEST_STRATEGY.md` の2ファイルにまとめる。

**手順:**
1. 同じチャットで `.prompts/phase1_spec_generation.md` の「---」以下を貼り付け
2. 段階1〜5を順に進める。**各段階の出力を必ずレビューする**
   - 段階1: 議論の棚卸し(4つのリスト)
   - 段階2: 構造化(章立てに振り分け)
   - 段階3: 自己レビュー(10個以上の見落とし検出)
   - 段階4: SPEC.md 生成
   - 段階5: TEST_STRATEGY.md 生成
3. 各段階で「次へ」と指示するまで先に進ませない
4. 最終的に SPEC.md と TEST_STRATEGY.md が出力される

**終わったとき:** SPEC.md と TEST_STRATEGY.md が手元にある。コピーするか、ファイルとして保存する。

**チェックポイント:**
- 段階3の自己レビューで10個以上の見落としが出ているか
- 「未決定事項」セクションに項目が**ある**か(ゼロは不健全)
- 受け入れ条件が「テストコードに変換できる粒度」になっているか

---

## フェーズ2: 環境構築

**場所:** ローカル + Claude Code。

**やること:** テンプレートから新規プロジェクトを起こし、Claude Code で初期環境を構築する。

### 2-1. テンプレートから新規プロジェクト作成

```bash
gh repo create my-new-system \
  --template <あなたのユーザー名>/claude-orchestration-template \
  --private --clone
cd my-new-system
```

### 2-2. SPEC.md と TEST_STRATEGY.md を配置

フェーズ1で生成した内容を `specs/` に配置します。

```bash
# テンプレートファイルを削除(または上書き)
rm specs/SPEC.template.md specs/TEST_STRATEGY.template.md

# フェーズ1の出力を specs/SPEC.md と specs/TEST_STRATEGY.md として保存
git add specs/
git commit -m "Add SPEC.md and TEST_STRATEGY.md"
```

### 2-3. Claude Code で初期化

```bash
claude
```

最初のメッセージで:

```
/setup-env
```

SPEC.md に書かれた技術スタックに応じた最小スカフォールドが構築されます。

### 2-4. 仕様の事前レビュー(推奨)

実装に入る前に、Claude Code 側からも仕様をレビューさせます:

```
/spec-review
```

`spec-reviewer` が SPEC.md を読み、曖昧さや矛盾を指摘します。見つかった問題は、
フェーズ1に戻って外部チャットで仕様を修正するか、その場で決められるものは決めて SPEC.md を更新します。

**終わったとき:** スカフォールド(package.json、テスト設定など)が構築され、
spec-reviewer のレビュー対応も済み、実装を始める準備が整っている。

---

## フェーズ3: 実装ループ

**場所:** Claude Code。

**やること:** 機能単位で `WORKFLOW.md` の8ステップを回す。

機能ごとに以下を繰り返します:

```
/start-feature F-001
```

その後の具体的なチャット指示の流れは `docs/CHAT_PATTERNS.md` を参照。

**機能ごとの完了条件:**
- 全テストが通っている
- auditor の監査レポートで未実装ゼロ
- 必要なら ADR が `./decisions/` に追加されている
- git にコミット・push されている

**全機能完了後:**
- 全体の統合テストを実行
- この README を「テンプレートの説明」から「このプロジェクトの説明」に書き換える
- 必要に応じてリリースタグを打つ

---

## フェーズ4: 仕様変更

開発を進めると、ほぼ確実に仕様変更が必要になります。
焦って Claude Code で「ここ変えて」と指示する前に、**外部チャットで設計し直す**のが鉄則です。

**場所:** 外部チャット(新規セッション) → Claude Code。

**手順:**
1. 外部チャットの**新規セッション**で `.prompts/spec_update.md` を使う
2. 現在の SPEC.md、TEST_STRATEGY.md、変更動機を貼り付ける
3. 影響分析・移行戦略を含めた変更計画を作る
4. 新 SPEC.md と「Claude Code 引き継ぎ指示書」を得る
5. Claude Code に戻り、指示書に従って変更を反映する

**Claude Code 側での反映手順:**
1. SPEC.md を新しい内容で上書き
2. 影響を受ける機能を `/audit F-XXX` で再監査(現状把握)
3. 必要に応じて `/start-feature F-XXX` で WORKFLOW を再実行
4. 変更理由を `./decisions/` に ADR として記録

**なぜ別チャットで設計するか:** 実装中のセッションには既存実装のコンテキストが乗っており、
そこで仕様変更を議論すると「変更しやすい方向」に引きずられるためです(詳細は `.prompts/spec_update.md` 冒頭)。

---

## 監査のモデル差し替え(任意)

監査(`/audit` → `auditor`)は**既定では今までどおり Claude Code 上で動く**。
そのうえで、**Copilot CLI が使える人だけ**が、監査モデルとして Copilot 経由の GPT-5.5 系などを選べる。

> Copilot / GPT-5.5 は**必須ではない**。組織ポリシーで Copilot CLI を使えない人は、**何も設定しなければ既存監査がそのまま動く**。

provider は環境変数で選ぶ(既定 `existing`)。`/audit F-XXX` でも `.harness/audit/run-audit.ps1` でも使える。

**既定(現在の監査方式。何も設定しない):**

```powershell
pwsh -NoProfile -File .harness/audit/run-audit.ps1 -Feature F-001
```

**既存providerを明示:**

```powershell
$env:HARNESS_AUDIT_PROVIDER="existing"
pwsh -NoProfile -File .harness/audit/run-audit.ps1 -Feature F-001
```

**Copilot CLI を使う:**

```powershell
$env:HARNESS_AUDIT_PROVIDER="copilot"
pwsh -NoProfile -File .harness/audit/run-audit.ps1 -Feature F-001
```

**Copilot CLI + GPT-5.5 系モデルを使う:**

```powershell
$env:HARNESS_AUDIT_PROVIDER="copilot"
$env:HARNESS_AUDIT_COPILOT_MODEL="<copilot で利用可能な GPT-5.5 のモデルID>"   # 実IDは copilot /model で確認
pwsh -NoProfile -File .harness/audit/run-audit.ps1 -Feature F-001
```

**auto(使えれば Copilot、ダメなら既存にフォールバック):**

```powershell
$env:HARNESS_AUDIT_PROVIDER="auto"
pwsh -NoProfile -File .harness/audit/run-audit.ps1 -Feature F-001
```

**厳密に Copilot を要求(フォールバックさせない。CI / 品質ゲート向け):**

```powershell
$env:HARNESS_AUDIT_PROVIDER="copilot"
$env:HARNESS_AUDIT_STRICT_PROVIDER="1"
pwsh -NoProfile -File .harness/audit/run-audit.ps1 -Feature F-001
```

### 注意事項

- Copilot CLI を使うには、**GitHub Copilot CLI policy が Organization で有効**である必要がある。
- `/login` に成功しても、`/model` や `copilot -p` が **policy で拒否**される場合がある。
- 利用可能なモデルIDは**組織契約やポリシーに依存**する。実IDは `copilot /model`(対話)または `copilot help` で確認する。
- このテンプレートは **Copilot を必須としない**。Copilot を使えない人は既存provider のまま監査できる。
- GPT-5.5 を使いたい人は、**実際のモデルIDを自分の環境で確認して**設定する(`gpt-5.5` とは限らない)。

詳細(exit code・capability check・ログ・互換性)は **`docs/AUDIT_PROVIDERS.md`** を参照。

---

## 全力モード(デーモンモード)(任意)

`/set-plan` がプラン別に「節約しながら」モデルを割り当てるのに対し、
**デーモンモードは制限消費を度外視して、全エージェントを最上位モデル `fable` で回す全力モード**。
品質最優先・短期決戦向け。

> **注意:** これは Max5 の**5時間/週を最速で消費する**。常用ではなく、ここぞの難機能・難所だけに使うのが現実的。
> 消費は `reports/worklog.jsonl` / `/report-effort` で監視し、制限に当たったら `/log-limit` で記録、`/daemon-mode off` で即戻せる。

```
/daemon-mode on       # 全エージェント(spec-reviewer/test-writer/implementer/auditor)を fable に
/model fable          # メインセッション(オーケストレーター)は手動で切り替え
/daemon-mode status   # 今 on/off か・各エージェントの現モデルを確認
/daemon-mode off      # 元のプラン設定(/set-plan の値)に復元
```

- **`/set-plan` との関係:** `/daemon-mode on` は plan より優先される。逆に **`/set-plan` を打つと daemon は自動解除**されプリセットに戻る。状態は `specs/status.json` の `daemon` に記録される。
- **モデル名の注意:** フロントマターに書く値は `fable`。Claude Code が `fable` を受理しない場合は、`/model` 等で確認した**正式なモデルID/エイリアスに置換**する(実IDは `fable` とは限らない)。

---

## オレ流モード(Oreryu mode)(任意)

全力モードが**全部 Fable で殴る**のに対し、オレ流モードは **Fable を「監督役(オーケストレータ)」に固定し、重い推論だけを Opus / Sonnet に動的ルーティング**する中間モード。
「daemon は重すぎるが、`/set-plan max5` より品質が欲しい」ときの選択肢。

- **Fable は指揮に専念**(分解・ルーティング・統合・人間への確認)。手は動かさない。
- **重い推論は Opus**(実装・監査・仕様レビュー)、**機械的な作業は Sonnet**(テスト作成)。
- **ダイナミックフロー**:固定 preset を下限(floor)としつつ、Fable がタスクごとに推論重量を見て `opus ↔ sonnet` を昇格/降格する(例:単純CRUD なら implementer を sonnet に降格、opus でも2回詰まったら fable に昇格)。判断ルールは `docs/ORERYU_ROUTING.md`。

```
/oreryu-mode on       # spec-reviewer/implementer/auditor=opus, test-writer=sonnet に。動的ルーティング有効化
/model fable          # メインセッション(監督役)は手動で fable に切り替え ← このモードの肝
/oreryu-mode status   # 今 on/off か・各エージェントの現モデルを確認
/oreryu-mode off      # 元のプラン設定(/set-plan の値)に復元
```

| 役割 | モデル | 意図 |
| --- | --- | --- |
| オーケストレーター(メインセッション) | fable | 監督・分解・動的ルーティング(速い・全体把握) |
| spec-reviewer | opus | 見落としが最も高コスト=深い推論 |
| test-writer | sonnet | 仕様→テスト変換=機械的 |
| implementer | opus | テストを通す=推論勝負(最重量) |
| auditor | opus | 仕様↔実装の突合=深い検証 |

> **daemon / set-plan との関係:** `/oreryu-mode on` / `/daemon-mode on` / `/set-plan` は互いに排他。最後に実行したものが勝つ。`/set-plan` を打つと oreryu も daemon も解除されプリセットに戻る。状態は `specs/status.json` の `oreryu` に記録される。
>
> **消費の目安:** 全 Fable の daemon よりは軽いが、`max5` プリセットより重い(implementer / auditor / spec-reviewer が常時 opus 以上、要所で fable)。`reports/worklog.jsonl` / `/report-effort` で監視し、`/oreryu-mode off` で即戻せる。

---

## 人間が握る4つのポイント

このワークフローで、あなた(人間)が必ず判断すべき場所は4つです。

1. **SPEC.md と TEST_STRATEGY.md のレビュー**(フェーズ1で生成後、即チェック)
2. **機能分割の判断**(フェーズ3の最初、計画提案時)
3. **各ステップの承認**(WORKFLOW のステップ3、ステップ8)
4. **ADR への記録**(各機能完了時に `decisions/` へ追加)

---

## どこで何を使うか早見表

| やりたいこと | 場所 | 使うもの |
| --- | --- | --- |
| アーキテクチャを議論したい | 外部チャット | `.prompts/phase0_architecture_kickoff.md` |
| 仕様書を作りたい | 外部チャット | `.prompts/phase1_spec_generation.md` |
| プロジェクトを起こしたい | ローカル | `gh repo create --template` |
| 初期スカフォールドを作りたい | Claude Code | `/setup-env` |
| 仕様の曖昧さを確認したい | Claude Code | `/spec-review` |
| 機能を実装したい | Claude Code | `/start-feature F-XXX` |
| 監査だけしたい | Claude Code | `/audit F-XXX` |
| 監査のモデルを差し替えたい(任意) | 環境変数 + Claude Code | `HARNESS_AUDIT_PROVIDER`(`docs/AUDIT_PROVIDERS.md`) |
| 進捗を絵で見たい | Claude Code → ブラウザ | `/dashboard` → `start dashboard.html` |
| プランに合わせモデル設定したい | Claude Code | `/set-plan <pro\|max5\|max20>` |
| 全エージェントを最上位モデルで回したい(全力モード) | Claude Code | `/daemon-mode on`(`off` で復元) |
| Fableを監督役にし重い推論だけ Opus/Sonnet にしたい(オレ流モード) | Claude Code | `/oreryu-mode on`(`off` で復元) |
| 利用制限に当たった | Claude Code | `/log-limit` |
| 規模・スケジュールのエビデンスが欲しい | Claude Code | `/report-effort` |
| 仕様を変更したい | 外部チャット → Claude Code | `.prompts/spec_update.md` |
| 実装が意図と違った | Claude Code | `docs/FIXING_DEVIATIONS.md` を参照 |

---

## ハマりやすいポイント

- **フェーズ1で段階を飛ばす** — 「一気に SPEC.md 出して」は密度が下がる。段階1〜5は飛ばさない。特に段階3の自己レビューが品質のキモ。
- **フェーズ2で実装を始める** — `/setup-env` はスカフォールドだけを作るコマンド。`/start-feature` を呼ぶまで実装に入らない。
- **フェーズ3で複数機能を並行する** — 「F-001 と F-002 を一緒に」は禁止。一機能ずつ完結させる(WORKFLOW.md 参照)。
- **フェーズ4で外部チャットを経由しない** — 「ちょっとした変更だから」と直接仕様をいじると、影響範囲の見落としが必ず起きる。

---

## ディレクトリ構造

```
.claude/
  agents/                4つの専門サブエージェント定義
    spec-reviewer.md     仕様の曖昧さを洗い出す
    test-writer.md       仕様からテストを書く(実装は見ない)
    implementer.md       テストを通す実装を書く(テストは変更不可)
    auditor.md           仕様と実装の突き合わせ監査
  commands/              スラッシュコマンド
    setup-env.md         /setup-env     プロジェクト初期化(status.json も生成)
    spec-review.md       /spec-review   仕様の曖昧さチェック
    start-feature.md     /start-feature F-XXX  実装ループ開始
    audit.md             /audit F-XXX   単独監査
    dashboard.md         /dashboard     進捗ダッシュボード(dashboard.html)を生成
    set-plan.md          /set-plan <pro|max5|max20>  プラン別にモデル設定
    daemon-mode.md       /daemon-mode <on|off|status>  全エージェントを fable に(全力モード)
    oreryu-mode.md       /oreryu-mode <on|off|status>  Fable監督 + 重い推論を Opus/Sonnet に動的ルーティング(オレ流モード)
    log-limit.md         /log-limit     利用制限到達を記録
    report-effort.md     /report-effort 規模・スケジュール・制限のエフォートレポート
  hooks/
    log-event.ps1        worklog自動記録ロガー(フックから呼ばれる)
  settings.json          (任意)フック設定。同梱せず docs/VISUALIZATION.md の手順で各自有効化

.prompts/                外部チャット(ChatGPT / Claude)用プロンプト
  phase0_architecture_kickoff.md   フェーズ0: アーキテクチャ議論キックオフ
  phase1_spec_generation.md        フェーズ1: 仕様生成(図化の段階を含む)
  spec_update.md                   仕様変更が必要になったとき

.harness/                ハーネス補助ツール
  audit/                 監査 provider ランナー(監査モデルの差し替え。既定では未使用)
    run-audit.ps1        provider runner(existing/copilot/auto, strict, exit code)
    lib/prompt.ps1       監査プロンプトビルダー(auditor.md を再利用)
    lib/copilot.ps1      Copilot CLI provider(capability check / invoke / 正規化)
    README.md            ランナーのローカル仕様

docs/                    補助ドキュメント
  CHAT_PATTERNS.md       Claude Code でのチャット指示パターン集
  FIXING_DEVIATIONS.md   意図と違うものができたときの修正フロー
  VISUALIZATION.md       可視化(status.json→dashboard)とエフォートログの仕組み
  AUDIT_PROVIDERS.md     監査の LLM provider / model 差し替え(Copilot CLI 対応)
  ORERYU_ROUTING.md      オレ流モードの動的ルーティング規約(タスク別のモデル昇格/降格)
  dashboard.template.html 進捗ダッシュボードのHTMLテンプレート
  vendor/mermaid.min.js  オフライン描画用(同梱)

specs/
  SPEC.template.md            仕様書テンプレート
  TEST_STRATEGY.template.md   テスト戦略テンプレート
  ARCHITECTURE.template.md    アーキテクチャ図テンプレート(Mermaid)
  status.template.json        進捗マップの真実の源テンプレート
  (フェーズ1完了後、ここに SPEC.md / TEST_STRATEGY.md / ARCHITECTURE.md を配置)

decisions/               ADR(設計判断記録)を蓄積
reports/                 監査レポート・worklog.jsonl・エフォートレポートを蓄積
tests/                   test-writer がここに書く
dashboard.html           (生成物)進捗ダッシュボード。start dashboard.html で開く

CLAUDE.md                Claude Code が自動で読む基本ルール
WORKFLOW.md              8ステップの実装ワークフロー
DEVELOPMENT_FLOW.md      フロー全体の思想と背景
```

---

## もっと詳しく知りたいとき

| 場面 | 見るべきドキュメント |
| --- | --- |
| Claude Code に何を打てばいいか | `docs/CHAT_PATTERNS.md` |
| 実装が意図と違った | `docs/FIXING_DEVIATIONS.md` |
| 8ステップの詳細 | `WORKFLOW.md` |
| 進捗の可視化・プラン設定・エフォートログ | `docs/VISUALIZATION.md` |
| 設計思想・背景 | `DEVELOPMENT_FLOW.md` |
| Claude Code の基本ルール | `CLAUDE.md` |

---

## カスタマイズ

このテンプレートは出発点です。使いながら自分用にチューニングするのが前提です。

- プロジェクト固有のルールは `CLAUDE.md` に追記(ただし300行以内推奨)
- 専門サブエージェントを追加したい場合: `.claude/agents/` に新規 md ファイル
- 繰り返しワークフローがあれば `.claude/commands/` に新規スラッシュコマンド
- よく使う外部チャットプロンプトがあれば `.prompts/` に追加

なお、`gh repo create --template` で派生した**過去の新規プロジェクトには、
テンプレート側の改善は自動反映されません**。テンプレート自体の改善は元のリポジトリで行ってください。
