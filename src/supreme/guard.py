"""F-014: ガードレール検証（guard）。

過学習防止3規律（①param数≪data数 / ②封印不可触 / ③選定は練習用のみ）＋
撤退基準（④探索試行回数上限・候補）を機械的に検査し、違反を探索・封印評価の前に
止める横断的制御点。封印の開封トークン（評価フェーズの機械的定義）の発行・失効も担う。

契約の最終根拠は specs/SPEC.md「F-014」節、ADR 0002（開封トークン方式）、
ADR 0007（fail-closed ①・機構のみ④・契約のテスト駆動定義）、および tests/test_F014_*.py。

本モジュールは stdlib のみに依存し、時刻・乱数を内部で取得しない（ts は全て引数で受ける
決定的設計）。永続化・ファイルI/O は持たない（インメモリ）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# 例外
# ---------------------------------------------------------------------------

class GuardInputError(Exception):
    """構築時の入力検証に失敗したことを示す例外。

    ガード検査関数（check_*）は不正入力を fail-closed で「不合格」の GuardResult として
    返すため、本例外を送出しない。

    本例外を送出する箇所は以下の2つ:
    1. SealGuard の構築時 — initial_session_count が非負整数でない
       （負数・非整数・bool・文字列等）。
    2. SealStore の production=True 時 — 外部からの seal_guard 注入を拒否する
       （本番は自前生成＋状態ファイル復元のみ許可・ADR 0010 決定3追記）。
    """


class PrecheckFailed(Exception):
    """事前検査不合格のままで開封トークンの発行を要求した（発行しない）。"""


class SessionLimitExceeded(Exception):
    """本番封印（production=True）で生涯1回の開封セッション枠を超えて発行を要求した。"""


class Blocked(Exception):
    """ガード不合格により後続（封印評価の開封トークン発行）をブロックした。"""


# ---------------------------------------------------------------------------
# データ型（レコード契約）
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GuardResult:
    """全ガード共通の検査結果レコード。

    passed   : 検査に合格したか。
    guard_id : "F-014-1" 等の検査識別子。
    checked  : 実際に検査を行ったか（④の未検査スキップと区別する）。
    reason   : 判定理由（人間可読・空でない）。
    """

    passed: bool
    guard_id: str
    checked: bool
    reason: str


@dataclass(frozen=True)
class AggregateResult:
    """複数ガードの集約結果レコード。

    passed    : 後続を許可してよいか（checked=True が全合格・空集約は不合格）。
    results   : 入力 GuardResult をそのまま保持（報告用）。
    blocked_by: passed=False だった checked ガードの guard_id（因果の根拠）。
    reason    : 判定理由（人間可読・空でない）。空集約や不合格の根拠を記す
                （ADR 0008 決定6 で空集約の真実な理由報告を要求）。
    """

    passed: bool
    results: tuple
    blocked_by: tuple
    reason: str


@dataclass
class OpenToken:
    """開封トークン（封印アクセスの「評価フェーズ」の機械的定義）。

    session_id : 開封セッションID。
    issued_ts  : 発行時刻（入力で受ける・決定的）。
    revoked_ts : 失効時刻（未失効は None）。
    active     : 未失効なら True（revoked_ts が None かどうかで決まる派生値）。
    """

    session_id: str
    issued_ts: float
    revoked_ts: Optional[float] = None

    @property
    def active(self) -> bool:
        return self.revoked_ts is None


# ---------------------------------------------------------------------------
# 内部ユーティリティ
# ---------------------------------------------------------------------------

def _is_nonneg_int(value) -> bool:
    """非負整数か（bool は計数として不正なので除外）。"""
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


# ---------------------------------------------------------------------------
# F-014-1 / ガードレール①: 過学習ガード（param数 ≪ data数）
# ---------------------------------------------------------------------------

def check_param_budget(param_count, data_count, k=None) -> GuardResult:
    """学習モジュール総パラメータ数 < 練習用データ数 × k を検査（ガードレール①）。

    合格 ⇔ (k is not None) かつ param_count < data_count * k（「<」厳密・等号は不合格）。
    k 未供給（None）は fail-closed で不合格（ADR 0007 決定1・検査は実施＝checked=True）。
    param_count / data_count が負数・非整数（bool 含む）・k≤0 は不正値として不合格。
    """
    guard_id = "F-014-1"

    if not _is_nonneg_int(param_count):
        return GuardResult(
            passed=False, guard_id=guard_id, checked=True,
            reason=f"不正値: param_count={param_count!r} は非負整数でない（fail-closed で不合格）。",
        )
    if not _is_nonneg_int(data_count):
        return GuardResult(
            passed=False, guard_id=guard_id, checked=True,
            reason=f"不正値: data_count={data_count!r} は非負整数でない（fail-closed で不合格）。",
        )
    if k is None:
        return GuardResult(
            passed=False, guard_id=guard_id, checked=True,
            reason="fail-closed: 係数 k 未供給（U24 未確定）のため検査不能。安全側に不合格（ADR 0007 決定1）。",
        )
    if not isinstance(k, (int, float)) or isinstance(k, bool) or k <= 0:
        return GuardResult(
            passed=False, guard_id=guard_id, checked=True,
            reason=f"不正値: 係数 k={k!r} は正の数でない（fail-closed で不合格）。",
        )

    budget = data_count * k
    passed = param_count < budget
    if passed:
        reason = f"合格: param_count={param_count} < data_count×k={budget}（過学習ガード①）。"
    else:
        reason = f"不合格: param_count={param_count} ≥ data_count×k={budget}（過学習の疑い）。"
    return GuardResult(passed=passed, guard_id=guard_id, checked=True, reason=reason)


# ---------------------------------------------------------------------------
# F-014-2 / ガードレール②: 封印保全（開封トークンの発行・失効・ログ検査）
# ---------------------------------------------------------------------------

class SealGuard:
    """封印開封トークンの発行・失効・生涯セッション計数を持つ制御オブジェクト。

    production はキーワード明示必須（既定なし・ADR 0008 決定1）。引数省略の
    `SealGuard()` は TypeError とし、「書き忘れによる silent fail-open」を型レベルで
    排除する（監査の最重点欠陥）。

    production=True で本番封印を縛り、生涯開封セッション数を1に強制する。
    production=False は複数発行を許す（ログ検査・失効検査のような構成検証用）。
    fail-open（False）の選択を呼び出し側の自覚的判断にするため、向きは常に明示させる。

    initial_session_count は生涯計数の復元用（既定 0・キーワード専用・ADR 0010 決定3）。
    プロセス跨ぎの「生涯1回」最終保証で F-002 が永続状態から読んだ計数を構築時注入する。
    既定値付きのため既存契約は非破壊。不正値（負数・非整数・bool・文字列）は GuardInputError
    （check_trial_cap の cap 検証と同流儀で bool も明示拒否）。
    """

    def __init__(self, *, production: bool, initial_session_count: int = 0):
        # production はキーワード専用・既定なし（明示しないと生成不能）。
        # initial_session_count は復元用。非負整数のみ受理（bool 含む不正値は GuardInputError）。
        if not _is_nonneg_int(initial_session_count):
            raise GuardInputError(
                f"initial_session_count={initial_session_count!r} は非負整数でない"
                f"（負数・非整数・bool・文字列等は復元値として不正・ADR 0010 決定3）。"
            )
        self.production = production
        self._lifetime_session_count = initial_session_count

    def issue_token(self, session_id, issued_ts, *, precheck_passed) -> OpenToken:
        """事前検査合格時のみトークンを発行する。

        precheck_passed=False なら PrecheckFailed を送出（発行せず・セッション枠不消費）。
        production=True で2回目の発行要求は SessionLimitExceeded（失効後でも生涯1回）。
        """
        if not precheck_passed:
            raise PrecheckFailed(
                "事前検査が合格していないため開封トークンを発行できない。"
            )
        if self.production and self._lifetime_session_count >= 1:
            raise SessionLimitExceeded(
                "本番封印は生涯1回のみ開封可能。2セッション目の発行は拒否（失効後も復活しない）。"
            )
        token = OpenToken(session_id=session_id, issued_ts=float(issued_ts), revoked_ts=None)
        self._lifetime_session_count += 1
        return token

    def revoke_token(self, token, *, revoked_ts) -> None:
        """トークンを失効させる（F-013 終了相当）。

        revoked_ts はキーワード明示必須（ADR 0008 決定4）。省略時に窓が issued_ts へ
        一点退縮し、セッション中の正当アクセス（ts > issued_ts）が遡って全て「期間外」と
        なる偽陽性（運用罠）を、引数必須化で構造的に排除する（省略は TypeError）。
        与えられた revoked_ts は有効期間の終端（半開区間 [issued_ts, revoked_ts) の上端）。
        """
        if token is None:
            return
        token.revoked_ts = float(revoked_ts)

    def is_access_allowed(self, token, ts) -> bool:
        """与トークンが「発行済み・未失効・かつ ts が有効期間内」かを判定する。

        有効期間は半開区間 [issued_ts, revoked_ts)（未失効なら [issued_ts, +inf)・
        ADR 0008 決定3）。ts == issued_ts は窓内、ts == revoked_ts は窓外。
        失効後 / 未発行 / None トークンは False。発行時刻より前のアクセスも False。
        """
        if token is None:
            return False
        if not token.active:
            return False
        return ts >= token.issued_ts

    def lifetime_session_count(self) -> int:
        """これまでに発行した開封セッション数（production 検査の根拠）。"""
        return self._lifetime_session_count


def _within_token_window(token, ts) -> bool:
    """ts がトークンの有効期間 [issued_ts, revoked_ts) 内か（半開区間・ADR 0008 決定3）。

    下端は閉（ts == issued_ts は窓内）、上端は開（ts == revoked_ts は窓外＝fail-closed 側）。
    未失効（revoked_ts is None）なら上端は +inf（[issued_ts, +inf)）。
    """
    if ts < token.issued_ts:
        return False
    if token.revoked_ts is not None and ts >= token.revoked_ts:
        return False
    return True


def audit_seal_access(log, token) -> GuardResult:
    """封印アクセスログを開封トークンの有効期間と突合する（ガードレール②）。

    合格 ⇔ 全アクセスが「token.session_id 一致」かつ「token の有効期間内」。
    期間外アクセス・別セッション・session_id None のアクセスが1件でもあれば不合格。
    空ログ（0件）は期間外アクセス0件で合格。
    """
    guard_id = "F-014-2"
    violations = []
    for rec in log:
        rec_session = rec.get("session_id")
        rec_ts = rec.get("ts")
        if rec_session is None:
            violations.append(f"トークン無し（session_id=None, ts={rec_ts}）のアクセス。")
            continue
        if rec_session != token.session_id:
            violations.append(
                f"別セッション（session_id={rec_session!r} ≠ {token.session_id!r}, ts={rec_ts}）のアクセス。"
            )
            continue
        if not _within_token_window(token, rec_ts):
            violations.append(f"有効期間外（ts={rec_ts}）のアクセス。")

    if violations:
        return GuardResult(
            passed=False, guard_id=guard_id, checked=True,
            reason="不合格: 封印への不正アクセスを検出 — " + " ".join(violations),
        )
    return GuardResult(
        passed=True, guard_id=guard_id, checked=True,
        reason=f"合格: 全 {len(log)} 件のアクセスが有効トークン期間内・同一セッション。",
    )


# ---------------------------------------------------------------------------
# F-014-3 / ガードレール③: 選定純度（組み合わせ選定は練習用のみ）
# ---------------------------------------------------------------------------

def check_selection_purity(provenance, seal_access_log=None) -> GuardResult:
    """組み合わせ選定が練習用のみで行われたことを検査（ガードレール③）。

    合格 ⇔ 全評価レコードの split が "train"（train と確証できない split は fail-closed で不合格）。
    seal_access_log を与えられた場合、選定期間中の封印アクセスが0件であることも合格条件に加える。

    seal_access_log 未供給（None）時は封印アクセス検査を実施しない。この場合の合格 reason は
    「封印アクセス検査は未実施」と明記し、検査していない事実を隠さない（虚偽の「0件」報告を
    排除・ADR 0008 決定5）。なお provenance の split・seal_access_log はいずれも呼び出し側の
    自己申告に依存する（TEST_STRATEGY 穴3/穴8 と同種の限界）。本ガードはその自己申告ラベルの
    機械的検査であり、ラベルの真正性そのものを保証しない。
    """
    guard_id = "F-014-3"
    violations = []

    for rec in provenance:
        split = rec.get("split")
        if split != "train":
            violations.append(
                f"非 train 評価（eval_id={rec.get('eval_id')!r}, split={split!r}, "
                f"scenario_id={rec.get('scenario_id')!r}）。"
            )

    seal_checked = seal_access_log is not None
    if seal_checked:
        n_seal = len(seal_access_log)
        if n_seal > 0:
            targets = [r.get("target") for r in seal_access_log]
            violations.append(
                f"選定期間中の封印アクセス {n_seal} 件（target={targets}）。"
            )

    if violations:
        return GuardResult(
            passed=False, guard_id=guard_id, checked=True,
            reason="不合格: 選定純度違反（封印汚染の疑い）— " + " ".join(violations),
        )

    if seal_checked:
        seal_phrase = "封印アクセス0件（供給ログを検査）"
    else:
        seal_phrase = "封印アクセス検査は未実施（seal_access_log 未供給）"
    return GuardResult(
        passed=True, guard_id=guard_id, checked=True,
        reason=f"合格: 全 {len(provenance)} 評価が練習用（train）・{seal_phrase}。",
    )


# ---------------------------------------------------------------------------
# F-014-4 / ガードレール④（候補）: 撤退基準（探索試行回数上限）
# ---------------------------------------------------------------------------

def check_trial_cap(trial_count, cap=None) -> GuardResult:
    """探索試行回数の上限超過を検査（ガードレール④・候補・機構のみ）。

    cap 未供給（None）→ checked=False の未検査（U18 未確定。合否に算入しない・ADR 0007 決定2）。
    cap 供給時: 合格 ⇔ trial_count <= cap（上限ちょうどは合格・超過で不合格）。
    trial_count が不正値（負数・非整数）で cap 供給時は不合格（検査不能）。
    cap 自体が不正値（負数・非整数・bool）なら checked=True かつ不合格（ADR 0008 決定7・
    ①の k 検証と同形）。cap=None の「未検査（checked=False）」とは明確に区別する：
    不正な上限の供給は「検査して不合格」であり、候補ガードのスルーには倒さない
    （不正値で合格を出さない fail-closed）。
    """
    guard_id = "F-014-4"

    if cap is None:
        return GuardResult(
            passed=True, guard_id=guard_id, checked=False,
            reason="未検査: 探索試行回数上限が未供給（U18 未確定）。候補ガードのため合否に算入しない（ADR 0007 決定2）。",
        )

    if not _is_nonneg_int(cap):
        return GuardResult(
            passed=False, guard_id=guard_id, checked=True,
            reason=f"不正値: 上限 cap={cap!r} は非負整数でない（無効な上限・fail-closed で不合格）。",
        )

    if not _is_nonneg_int(trial_count):
        return GuardResult(
            passed=False, guard_id=guard_id, checked=True,
            reason=f"不正値: trial_count={trial_count!r} は非負整数でない（検査不能で不合格）。",
        )

    passed = trial_count <= cap
    if passed:
        reason = f"合格: trial_count={trial_count} ≤ cap={cap}（撤退基準④・上限内）。"
    else:
        reason = f"不合格: trial_count={trial_count} > cap={cap}（撤退基準④・上限超過）。"
    return GuardResult(passed=passed, guard_id=guard_id, checked=True, reason=reason)


# ---------------------------------------------------------------------------
# 集約・後続制御
# ---------------------------------------------------------------------------

def combine_guards(results) -> AggregateResult:
    """複数ガードの結果を集約する。

    集約規則: checked=True のガードが全て passed=True → 全体合格。
    checked=False（④未検査）のガードは合否に算入しない（候補ガード・ADR 0007）。
    checked=True のガードが1件でも passed=False → 全体不合格・blocked_by に guard_id。
    空リスト（[]）は不合格（ADR 0008 決定6・fail-closed）。検査が1件も無いことは
    合格の根拠が無いことであり、空虚合格（empty-vacuous pass）を排除する。reason に
    空集約である旨を明示し、後続（探索続行・トークン発行）をブロックする。
    """
    results_tuple = tuple(results)

    if not results_tuple:
        return AggregateResult(
            passed=False,
            results=results_tuple,
            blocked_by=(),
            reason="不合格: 集約対象のガード結果が0件（空集約）。合格の根拠が無いため "
                   "fail-closed で後続をブロックする（ADR 0008 決定6・空虚合格の排除）。",
        )

    blocked_by = tuple(
        r.guard_id for r in results_tuple if r.checked and not r.passed
    )
    passed = len(blocked_by) == 0
    if passed:
        n_checked = sum(1 for r in results_tuple if r.checked)
        reason = (
            f"合格: checked ガード {n_checked} 件が全て合格（未検査の候補ガードは算入せず）。"
        )
    else:
        reason = (
            f"不合格: checked ガードに不合格あり（blocked_by={blocked_by}）— 後続をブロックする。"
        )
    return AggregateResult(
        passed=passed,
        results=results_tuple,
        blocked_by=blocked_by,
        reason=reason,
    )


class SearchGate:
    """探索の続行許可ゲート＋封印評価の開封トークン発行（F-012/F-013 が経由する制御点）。

    構築時に SealGuard を内包する（ADR 0008 決定2・発行経路の統合）。開封トークンの発行は
    必ず内包 SealGuard を経由し、生涯セッション計数を消費する（不合格＝Blocked 時は不消費）。
    自己申告 bool を受ける別経路は持たない（事前検査は AggregateResult を直接受ける）。
    """

    def __init__(self, seal_guard: SealGuard):
        self._seal_guard = seal_guard

    def request_continue(self, aggregate) -> bool:
        """集約合格時のみ探索続行を許可する（不合格ならブロック＝False）。"""
        return aggregate.passed

    def open_token_for_eval(self, aggregate, session_id, issued_ts) -> OpenToken:
        """集約合格時のみ封印評価の開封トークンを発行する（唯一のアプリ正規発行経路）。

        事前検査は AggregateResult を直接受ける（ADR 0008 決定2）。precheck_passed を
        本物の AggregateResult.passed から導出し、自己申告 bool（True 等）の素通しを
        統合境界で排除する。aggregate が AggregateResult でない（.passed が無い）場合は
        合格扱いにならず、発行前に弾かれる（計数も消費しない）。

        合格時は内包 SealGuard.issue_token 経由で発行し、生涯セッション計数を消費する。
        不合格なら Blocked を送出（トークンを発行しない＝封印評価をブロック・計数不消費）。
        内包 SealGuard が production=True の場合、2回目の発行は SealGuard 側の生涯1回制約
        により SessionLimitExceeded で拒否される。
        """
        if not aggregate.passed:
            raise Blocked(
                "ガード不合格のため封印評価の開封トークンを発行しない（後続ブロック）。"
                f" blocked_by={aggregate.blocked_by}"
            )
        return self._seal_guard.issue_token(
            session_id, issued_ts, precheck_passed=aggregate.passed
        )
