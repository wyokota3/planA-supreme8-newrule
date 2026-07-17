"""F-002: 封印テストセット構築（sealset）。

人手の本物シナリオ＋人手確認GTを少数（精鋭）封印登録し、学習・調整に不可触、
最終評価で一度だけ開封する機構。封印データの分離保管・トークンゲートによる
アクセス制御・永続 JSONL ログを束ねる。

契約の最終根拠は specs/SPEC.md「F-002」節、ADR 0009（機構のみ・分離保管+
トークンゲート+永続ログ・ダミーモード）、specs/GUARD_IF.md（F-002 はこれに従う側）、
および tests/test_F002_*.py。

本モジュールは stdlib のみに依存し、時刻・乱数を内部で取得しない（ts は全て引数で
受ける決定的設計）。スキーマ検証・リネージ検証は supreme.datagov を、開封トークン
制御・生涯計数は supreme.guard.SealGuard を再利用する（独自に再発明しない）。
ファイルI/O（分離保管・永続ログ・セッション状態）が本モジュール固有の責務。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from . import datagov
from . import guard


# ---------------------------------------------------------------------------
# 例外
# ---------------------------------------------------------------------------

class LineageCrossError(datagov.LineageCrossError):
    """封印登録しようとした root 親系統が練習用（train）と交差している。

    datagov.LineageCrossError を継承する（GUARD_IF/テスト docstring の
    「datagov.LineageCrossError を継承 or 同一でもよい」に従う）。
    """


class AccessDenied(Exception):
    """評価フェーズ外（トークン無し/失効後/窓外 ts）の封印 gt 本体アクセス（拒否）。"""


class LogCorruptionError(Exception):
    """永続アクセスログの破損（不正 JSON 行・SealAccessRecord 契約違反）を検出。"""


class SealOverwriteError(Exception):
    """封印済みレコードの上書き試行（同一 scenario_id の再 register）を拒否。

    不可触の機構的担保（ADR 0010 決定1）。試行は access_log に session_id=None で
    記録（tripwire）した後に送出する（記録が先・例外が後）。
    """


# ---------------------------------------------------------------------------
# 結果オブジェクト
# ---------------------------------------------------------------------------

@dataclass
class RegisterResult:
    """SealStore.register の戻り値。

    datagov.RegisterResult は scenario_id/warnings のみのため、封印固有の
    来歴（split/gt_origin）を含む専用の結果型を用意する。
    """
    scenario_id: str
    split: str
    gt_origin: str
    warnings: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# SealStore
# ---------------------------------------------------------------------------

class SealStore:
    """封印データの分離保管・アクセス制御・永続ログ／状態を束ねる機構。

    root_dir : pathlib.Path | str  封印データ/ログ/状態ファイルを置く専用ディレクトリ
                                   （リポジトリ外想定。テストは tmp_path を注入）。
    production: bool  キーワード明示必須（GUARD_IF / SealGuard と同じ向き・ADR 0008 決定1）。
                      省略は TypeError。True=本番封印（生涯1回）、
                      False=ダミーモード（常用テスト・複数回開封可）。
    seal_guard: guard.SealGuard | None  省略時は production に応じて内部生成する。

    ストレージレイアウト（root_dir 配下にのみ書く＝分離保管）:
      sealed/<scenario_id>.json   … 封印レコード本体（JSON）
      access_log.jsonl            … SealAccessRecord の JSONL 永続ログ
      session_state.json          … 生涯開封セッション状態（プロセス跨ぎ用）
    """

    def __init__(self, *, root_dir, production: bool, seal_guard=None):
        self._root = Path(root_dir)
        self._sealed_dir = self._root / "sealed"
        self._log_path = self._root / "access_log.jsonl"
        self._state_path = self._root / "session_state.json"

        self.production = production

        if seal_guard is None:
            # 自前生成: 永続セッション状態を「先に」読み、その計数で SealGuard を
            # 構築時注入する（公開復元API・ADR 0010 決定3）。private 代入は廃止。
            # 状態ファイルが不正なら guard の検証で GuardInputError が伝播（fail-closed）。
            initial = self._read_persisted_session_count()
            seal_guard = guard.SealGuard(
                production=production, initial_session_count=initial
            )
        else:
            # 注入 guard（dummy のみ可）: production での外部注入は禁止（fail-closed・
            # ADR 0010 追記）。注入 guard へ状態ファイル計数を適用できない（構築時注入の
            # ため）ので、本番封印の生涯1回を取りこぼさないよう構築時に拒否する。
            if production:
                raise guard.GuardInputError(
                    "production=True での seal_guard 注入は禁止（fail-closed・ADR 0010）。"
                    "本番は自前生成＋状態ファイル復元のみ。"
                )
            # dummy 注入時は状態ファイルを読まない（注入側が復元責任を持つ）。
        self._guard = seal_guard

    # --- 内部: ディレクトリ確保 -------------------------------------------

    def _ensure_root(self):
        self._root.mkdir(parents=True, exist_ok=True)

    def _ensure_sealed_dir(self):
        self._ensure_root()
        self._sealed_dir.mkdir(parents=True, exist_ok=True)

    # --- 登録 -------------------------------------------------------------

    def register(self, record, *, governor, ts) -> RegisterResult:
        """封印への登録。

        datagov の GT_SCHEMA バリデーションとリネージ検証を再利用してから封印保管する。
        - スキーマ違反は datagov.ValidationError（封印に書かない）。
        - record の root 親系統が governor 上の train 親系統集合と交われば
          sealset.LineageCrossError（封印に書かない・孫経由含む）。
        - 同一 scenario_id の封印が既存なら sealset.SealOverwriteError（上書き拒否・
          不可触の機構的担保・ADR 0010 決定1）。試行は access_log に session_id=None で
          記録（tripwire）してから送出する（記録が先・例外が後）。
        ts はキーワード必須（既定なし・省略 TypeError・GUARD_IF 運用規約4「時刻は呼び出し
        側供給」と一貫）。ts は上書き試行の記録時刻にのみ使う（正常登録は無記録）。
        成功時は record を root_dir/sealed/<scenario_id>.json に書き、RegisterResult を返す。
        """
        # 1) スキーマ検証（datagov 契約の再利用）。違反は ValidationError。
        result = datagov.validate_record(record)
        if not result.ok:
            raise datagov.ValidationError("; ".join(result.errors))

        meta = record["meta"]
        sid = meta["scenario_id"]

        # 2) リネージ交差検証（孫経由含む・推移閉包で root へ畳む）。
        record_roots = self._resolve_record_roots(record, governor)
        train_roots = governor.lineage_set("train")
        crossing = record_roots & train_roots
        if crossing:
            raise LineageCrossError(
                f"seal record {sid!r} crosses train root lineage(s): "
                f"{sorted(crossing)!r}"
            )

        # 3) 上書き拒否（不可触の機構的担保・ADR 0010 決定1）。封印済みが既存なら
        #    試行を access_log に記録（session_id=None の tripwire）してから拒否する
        #    （記録が先・例外が後＝既存の拒否経路と同じ順序）。production/dummy 共通。
        if self._body_path(sid).exists():
            self._append_log(
                {"session_id": None, "ts": float(ts), "target": sid}
            )
            raise SealOverwriteError(
                f"封印済みレコード {sid!r} の上書きは拒否される（不可触の機構的担保・"
                f"ADR 0010 決定1）。試行は access_log に記録した（ts={ts}）。"
            )

        # 4) 封印保管（split=seal として meta を上書きして書く）。
        self._ensure_sealed_dir()
        stored = json.loads(json.dumps(record))  # deep copy（呼び出し側の改変から守る）
        stored["meta"]["split"] = "seal"
        gt_origin = stored["meta"]["gt_origin"]
        self._body_path(sid).write_text(
            json.dumps(stored, ensure_ascii=False), encoding="utf-8"
        )

        return RegisterResult(
            scenario_id=sid,
            split="seal",
            gt_origin=gt_origin,
            warnings=list(result.warnings),
        )

    def _resolve_record_roots(self, record, governor):
        """封印登録しようとする record の root 親系統ID集合を解決する。

        - record 自身が root 宣言（parents=[]）なら root は自身の scenario_id。
        - 子孫なら parents をたどる。parents の各 scenario_id は governor 上で
          推移閉包により root へ畳む（孫経由リーク検出。テスト docstring の
          「governor は train として既に系統を保持しているので root へ畳んで判定」）。
        """
        meta = record["meta"]
        sid = meta["scenario_id"]
        parents = meta["parents"]
        if not parents:
            return {sid}
        roots = set()
        for p in parents:
            roots.add(governor.resolve_root(p))
        return roots

    def _body_path(self, scenario_id):
        return self._sealed_dir / (scenario_id + ".json")

    def _load_body(self, scenario_id):
        path = self._body_path(scenario_id)
        if not path.exists():
            raise KeyError(f"sealed scenario {scenario_id!r} not found")
        return json.loads(path.read_text(encoding="utf-8"))

    # --- 封印リネージ集合 -------------------------------------------------

    def sealed_lineage_set(self) -> set:
        """現在封印に登録済みの root 親系統ID集合。

        封印保管した各レコードの root を推移閉包で畳む。封印は人手 root（自身が root）
        を素材とするが、機構としては parents の root（自身が parents=[] なら自身）を返す。
        """
        roots = set()
        if not self._sealed_dir.exists():
            return roots
        for path in self._sealed_dir.iterdir():
            if not path.is_file() or path.suffix != ".json":
                continue
            body = json.loads(path.read_text(encoding="utf-8"))
            meta = body["meta"]
            if not meta["parents"]:
                roots.add(meta["scenario_id"])
            else:
                roots.add(meta["parent_lineage_id"])
        return roots

    # --- メタ参照（トークン不要・秘匿対象は gt 本体のみ）-----------------

    def stored_meta(self, scenario_id) -> dict:
        """封印に保管したレコードの meta 層（来歴）を返す。

        メタデータは秘匿対象でない（トークン無しでも参照可）。秘匿対象は gt 本体のみ。
        """
        body = self._load_body(scenario_id)
        return body["meta"]

    # --- 開封トークン（内包 SealGuard へ委譲）-----------------------------

    def issue_open_token(self, session_id, issued_ts, *, precheck_passed):
        """内包 SealGuard.issue_token への委譲（生涯計数を消費）。

        precheck_passed=False は guard.PrecheckFailed、production の2回目は
        guard.SessionLimitExceeded（いずれも guard が送出）。発行成功時は
        session_state.json を更新し、別インスタンス（同一 root_dir）でも生涯計数を
        引き継ぐ（GUARD_IF 運用規約2）。

        注: 本メソッドは本番封印（F-013）の正規経路ではない。SearchGate × SealStore の
        経路合成の解決（ADR 0010 決定2）まで、F-013 から本メソッドを直接使用してはならない
        （SearchGate 経由の aggregate 検査を素通しにしないため）。
        """
        token = self._guard.issue_token(
            session_id, issued_ts, precheck_passed=precheck_passed
        )
        # 発行成功時のみここに到達（失敗は guard が例外送出）。永続状態を更新。
        self._persist_session_state()
        return token

    def open_eval_session(self, aggregate, session_id, issued_ts):
        """F-013 の唯一の正規開封経路（SearchGate × SealStore の経路合成・ADR 0023 決定1）。

        内部で gate = guard.SearchGate(self._guard) を作り、
        gate.open_token_for_eval(aggregate, session_id, issued_ts) で aggregate 検査を
        **強制**してトークンを発行する（ADR 0010 決定2「store 側 guard を SearchGate に渡す」）。
        store 自身の内包 guard で発行するので、後続 read_sealed_gt(..., token=token, ...) が
        このトークンを受理する。

        - aggregate 不合格は open_token_for_eval が guard.Blocked を送出する
          （枠不消費＝lifetime_session_count 不変・session_state.json 不変）。例外は
          発行前に SearchGate 側で送出されるため、本メソッドの _persist_session_state は
          呼ばれない（永続状態にも枠消費が漏れない・ADR 0023 決定1）。
        - production=True の2回目は内包 SealGuard 側の生涯1回制約により
          guard.SessionLimitExceeded（同じく発行前送出のため persist しない）。
        - 発行成功でのみ _persist_session_state()（生涯計数を session_state.json に永続化・
          GUARD_IF 運用規約2）。

        F-013 経路で issue_open_token は使わない（GUARD_IF 運用規約5 を維持）。
        """
        gate = guard.SearchGate(self._guard)
        # 不合格は gate が Blocked / SessionLimitExceeded を送出（ここで止まり persist しない）。
        token = gate.open_token_for_eval(aggregate, session_id, issued_ts)
        # 発行成功時のみここに到達（枠を消費した）。永続状態を更新する。
        self._persist_session_state()
        return token

    def revoke_open_token(self, token, *, revoked_ts) -> None:
        """内包 SealGuard.revoke_token への委譲（F-013 終了相当）。"""
        self._guard.revoke_token(token, revoked_ts=revoked_ts)

    def lifetime_session_count(self) -> int:
        """永続セッション状態を反映した生涯開封セッション数。"""
        return self._guard.lifetime_session_count()

    # --- 封印 gt 本体の読み出し（トークンゲート）-------------------------

    def read_sealed_gt(self, scenario_id, *, token, ts) -> dict:
        """封印された gt 本体（dict）を読み出す。

        token が有効（発行済み・未失効・ts が有効期間内＝半開区間 [issued, revoked)）なら
        gt を返し、access_log に session_id 付きで記録する。
        token が None / 失効後 / 窓外 ts なら AccessDenied を送出し、access_log に
        session_id=None で記録する（拒否がログに残ることが本質）。
        """
        if self._guard.is_access_allowed(token, ts):
            self._append_log(
                {"session_id": token.session_id, "ts": float(ts),
                 "target": scenario_id}
            )
            body = self._load_body(scenario_id)
            return body["gt"]

        # 評価フェーズ外アクセス: 拒否し、session_id=None で記録する。
        self._append_log(
            {"session_id": None, "ts": float(ts), "target": scenario_id}
        )
        raise AccessDenied(
            f"封印 {scenario_id!r} への評価フェーズ外アクセス（ts={ts}）を拒否・記録した。"
        )

    # --- 永続アクセスログ（JSONL）----------------------------------------

    def _append_log(self, record) -> None:
        """SealAccessRecord 1件を root_dir/access_log.jsonl に追記する（1行=1レコード）。"""
        self._ensure_root()
        with self._log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def access_log(self) -> list:
        """永続ログ（root_dir/access_log.jsonl）を読み戻した SealAccessRecord のリスト。

        不正 JSON 行・SealAccessRecord 契約（session_id/ts/target）違反行を検出したら
        LogCorruptionError を送出する（黙って読み飛ばさない）。
        """
        records: list = []
        if not self._log_path.exists():
            return records
        text = self._log_path.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines()):
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except (ValueError, json.JSONDecodeError) as exc:
                raise LogCorruptionError(
                    f"access_log.jsonl 行 {i} が不正 JSON: {line!r}"
                ) from exc
            if not isinstance(rec, dict) or not (
                {"session_id", "ts", "target"} <= set(rec.keys())
            ):
                raise LogCorruptionError(
                    f"access_log.jsonl 行 {i} が SealAccessRecord 契約違反"
                    f"（session_id/ts/target 欠落）: {line!r}"
                )
            records.append(rec)
        return records

    # --- 永続セッション状態（生涯計数のプロセス跨ぎ保証）------------------

    def _persist_session_state(self) -> None:
        """内包 SealGuard の生涯開封セッション数を session_state.json に書き出す。"""
        self._ensure_root()
        state = {
            "lifetime_session_count": self._guard.lifetime_session_count(),
        }
        self._state_path.write_text(
            json.dumps(state, ensure_ascii=False), encoding="utf-8"
        )

    def _read_persisted_session_count(self) -> int:
        """session_state.json があれば生涯計数を読んで返す（不在時は 0）。

        プロセス再起動相当の新インスタンスが永続状態を読み戻し、production の
        生涯1回をプロセス跨ぎで担保する（GUARD_IF 運用規約2・インメモリ計数のみに
        依存しない）。読んだ計数は SealGuard の公開復元API（initial_session_count）に
        構築時注入する（private 属性への代入は廃止・ADR 0010 決定3）。状態ファイルの
        値が不正なら guard の検証で GuardInputError が伝播する（fail-closed）。
        """
        if not self._state_path.exists():
            return 0
        state = json.loads(self._state_path.read_text(encoding="utf-8"))
        return state.get("lifetime_session_count", 0)
