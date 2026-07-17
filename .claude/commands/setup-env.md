---
description: SPEC.md と TEST_STRATEGY.md が用意できた後、プロジェクトの初期スカフォールドを作る
---

`./specs/SPEC.md` と `./specs/TEST_STRATEGY.md` を読み、最小限のプロジェクトスカフォールドを構築してください。

## やること

1. SPEC.md の「アーキテクチャ」→「技術スタック」セクションから言語・フレームワークを特定
2. その技術スタックに応じた最小限のプロジェクト初期化:
   - 依存関係マニフェスト(package.json, pyproject.toml 等)
   - エントリーポイントの空ファイル
   - テストフレームワークの設定ファイル
   - `.gitignore` の言語固有エントリ追記
3. プロジェクトの README.md を生成(SPEC.md からの抜粋を含む)
4. **進捗マップの初期化**:`specs/SPEC.md` の機能一覧と `specs/ARCHITECTURE.md` のノード/データフローから `specs/status.json` を生成する(`specs/status.template.json` のスキーマに従う。`_` で始まるコメントキーは含めない)。全ノード・全機能の `status` は `todo`。`plan` は現在の設定(不明なら `max5`)。
5. `/dashboard` を実行して初期 `dashboard.html` を生成し、ブラウザで全体像を確認できるようにする。

## やらないこと

- 機能の実装(これは `/start-feature` で行う)
- SPEC.md にない技術選択の追加
- 余分なボイラープレートの大量生成

完了したら、ディレクトリ構造を tree で表示し、次に実行すべきコマンド(`/start-feature F-001` など)を提示してください。
