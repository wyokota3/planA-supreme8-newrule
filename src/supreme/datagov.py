"""F-001: データ規律基盤（datagov）。

シナリオ+GT を親シナリオ単位で管理し、練習用／封印が親系統を跨がぬよう分割する。
版・親子リネージを記録し、GT 単一スキーマ（specs/GT_SCHEMA.md）でバリデーションする。

契約の最終根拠は specs/SPEC.md「F-001」節と specs/GT_SCHEMA.md。
本モジュールは stdlib のみに依存し、永続化・ファイルI/O は持たない（インメモリ）。
"""

from __future__ import annotations

import copy
import hashlib
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# 例外
# ---------------------------------------------------------------------------

class ValidationError(Exception):
    """GT 単一スキーマの拒否事由（必須キー欠落・型不一致・値域違反 等）。"""


class LineageError(Exception):
    """親系統が解決できない（親未登録かつ root 宣言でない／循環・解決不能）。"""


class LineageCrossError(Exception):
    """払い出し時に seal と train の root 親系統が交差している。"""


class SplitError(Exception):
    """分割割当の不正パラメータ（count と ratio の同時指定・件数超過 等）。"""


# ---------------------------------------------------------------------------
# t2 6分布のクラスキー集合（GT_SCHEMA.md の定義。突合可能性の契約）
# ---------------------------------------------------------------------------

_T2_KEY_SETS = {
    "mode": frozenset((
        "conv_request", "conv_ongoing", "surround_activity", "forward_caution",
        "side_rear_caution", "alert_required", "emergency", "quiet_standby",
        "env_change", "uncertain",
    )),
    "relations": frozenset((
        "addressing_user", "near_user", "approaching", "grouped",
        "departing", "unrelated",
    )),
    "roles": frozenset((
        "source_speech", "source_vehicle", "source_alarm", "unknown",
        "source_human", "source_object",
    )),
    "hazard": frozenset(("safe", "caution", "danger")),
    "dynamics": frozenset(("approach", "pass", "depart", "stop", "idle")),
    "episode": frozenset(("ongoing", "ending", "regime_change")),
}

# t3 のうち [0,1] に収まるべき確率フィールド（next_beat.p は別途検査）。
_T3_PROB_FIELDS = ("outdoor_prob", "stability")

_DIST_SUM_TOLERANCE = 0.01  # 分布合計の警告境界（1 ± 0.01）


# ---------------------------------------------------------------------------
# 結果オブジェクト
# ---------------------------------------------------------------------------

@dataclass
class ValidationResult:
    ok: bool
    errors: list
    warnings: list


@dataclass
class RegisterResult:
    """register の戻り値。警告を保持する。"""
    scenario_id: str
    warnings: list


@dataclass
class ReconcileResult:
    matched: list
    only_a: list
    only_b: list


@dataclass
class SplitAssignment:
    seal: tuple
    train: tuple
    version: int


# ---------------------------------------------------------------------------
# バリデーション
# ---------------------------------------------------------------------------

def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _in_unit_interval(v):
    return _is_number(v) and 0.0 <= v <= 1.0


def validate_record(record):
    """canonical GT record を検査し ValidationResult を返す。

    拒否（errors）と警告（warnings）を分離する。custom 配下は検査しない。
    リネージの「親未登録」は registry が必要なため本関数では検査しない
    （DataGovernor.register が LineageError として扱う）。
    """
    errors: list = []
    warnings: list = []

    if not isinstance(record, dict):
        errors.append("record must be a dict")
        return ValidationResult(False, errors, warnings)

    meta = record.get("meta")
    gt = record.get("gt")

    # --- meta 層 -----------------------------------------------------------
    if not isinstance(meta, dict):
        errors.append("missing or invalid 'meta'")
        meta = {}
    else:
        _validate_meta(meta, errors)

    # --- gt 層 -------------------------------------------------------------
    if not isinstance(gt, dict):
        errors.append("missing or invalid 'gt'")
        gt = {}
    else:
        _validate_gt(gt, errors, warnings)

    # --- meta.scenario_id == gt.scenario_id -------------------------------
    if isinstance(meta, dict) and isinstance(gt, dict):
        m_sid = meta.get("scenario_id")
        g_sid = gt.get("scenario_id")
        if m_sid is not None and g_sid is not None and m_sid != g_sid:
            errors.append(
                "meta.scenario_id != gt.scenario_id "
                f"({m_sid!r} != {g_sid!r})"
            )

    # custom は検査しない（不透明パススルー）。

    return ValidationResult(ok=(errors == []), errors=errors, warnings=warnings)


def _validate_meta(meta, errors):
    # 必須キーと型。文字列必須フィールドは非空も要求（空文字列は拒否）。
    required_str = ("scenario_id", "parent_lineage_id", "split", "gt_origin",
                    "registered_at")
    for key in required_str:
        if key not in meta:
            errors.append(f"meta.{key} missing")
        elif not isinstance(meta[key], str):
            errors.append(f"meta.{key} must be str")
        elif meta[key] == "":
            errors.append(f"meta.{key} must be non-empty")

    if "generation" not in meta:
        errors.append("meta.generation missing")
    elif not isinstance(meta["generation"], int) or isinstance(meta["generation"], bool):
        errors.append("meta.generation must be int")

    if "parents" not in meta:
        errors.append("meta.parents missing")
    elif not isinstance(meta["parents"], list):
        errors.append("meta.parents must be list")
    elif not all(isinstance(p, str) for p in meta["parents"]):
        errors.append("meta.parents entries must be str")

    source = meta.get("source")
    if "source" not in meta:
        errors.append("meta.source missing")
    elif not isinstance(source, dict):
        errors.append("meta.source must be dict")
    else:
        for key in ("repo", "commit", "path"):
            if key not in source:
                errors.append(f"meta.source.{key} missing")
            elif not isinstance(source[key], str):
                errors.append(f"meta.source.{key} must be str")
            elif source[key] == "":
                errors.append(f"meta.source.{key} must be non-empty")

    # root 宣言の3条件（GT_SCHEMA 改版・ADR 0004）。型が揃っているときだけ検査。
    # parents=[] を root 宣言とみなし、parent_lineage_id=自身 ∧ generation=0 を強制。
    sid = meta.get("scenario_id")
    plid = meta.get("parent_lineage_id")
    parents = meta.get("parents")
    gen = meta.get("generation")
    if (isinstance(parents, list) and parents == []
            and isinstance(sid, str) and isinstance(plid, str)
            and isinstance(gen, int) and not isinstance(gen, bool)):
        if plid != sid:
            errors.append(
                "root declaration inconsistent: parents=[] but "
                f"parent_lineage_id ({plid!r}) != scenario_id ({sid!r})"
            )
        if gen != 0:
            errors.append(
                "root declaration inconsistent: parents=[] but "
                f"generation ({gen!r}) != 0"
            )


def _validate_gt(gt, errors, warnings):
    if "scenario_id" not in gt:
        errors.append("gt.scenario_id missing")
    elif not isinstance(gt["scenario_id"], str):
        errors.append("gt.scenario_id must be str")
    elif gt["scenario_id"] == "":
        errors.append("gt.scenario_id must be non-empty")

    if "version" not in gt:
        errors.append("gt.version missing")
    elif not isinstance(gt["version"], str):
        errors.append("gt.version must be str")
    elif gt["version"] == "":
        errors.append("gt.version must be non-empty")

    # description 欠落は警告のみ。
    if "description" not in gt:
        warnings.append("gt.description missing")
    elif not isinstance(gt["description"], str):
        errors.append("gt.description must be str")

    frames = gt.get("frames")
    if "frames" not in gt:
        errors.append("gt.frames missing")
        return
    if not isinstance(frames, list):
        errors.append("gt.frames must be list")
        return

    prev_ts = None
    for i, fr in enumerate(frames):
        if not isinstance(fr, dict):
            errors.append(f"gt.frames[{i}] must be dict")
            continue
        prev_ts = _validate_frame(fr, i, prev_ts, errors, warnings)


def _validate_frame(fr, i, prev_ts, errors, warnings):
    # ts: float、系列内で狭義単調増加。
    ts = fr.get("ts")
    if "ts" not in fr:
        errors.append(f"gt.frames[{i}].ts missing")
    elif not _is_number(ts):
        errors.append(f"gt.frames[{i}].ts must be number")
    else:
        if prev_ts is not None and not (ts > prev_ts):
            errors.append(
                f"gt.frames[{i}].ts not strictly increasing "
                f"({ts!r} <= {prev_ts!r})"
            )
        prev_ts = ts

    _validate_t0(fr.get("t0"), i, errors)
    _validate_t1(fr.get("t1"), i, errors)
    _validate_t2(fr.get("t2"), i, errors, warnings)
    _validate_t3(fr.get("t3"), i, errors)

    return prev_ts


def _validate_t0(t0, i, errors):
    if not isinstance(t0, dict):
        errors.append(f"gt.frames[{i}].t0 missing or invalid")
        return
    # risk_tier / kind は str|null、range_m は float|null。
    for key in ("risk_tier", "kind"):
        if key not in t0:
            errors.append(f"gt.frames[{i}].t0.{key} missing")
        elif t0[key] is None:
            pass  # null は許容（str|null）。
        elif not isinstance(t0[key], str):
            errors.append(f"gt.frames[{i}].t0.{key} must be str or null")
        elif t0[key] == "":
            # 文字列を採るなら非空（空文字列は拒否。null と区別する）。
            errors.append(f"gt.frames[{i}].t0.{key} must be non-empty when str")
    if "range_m" not in t0:
        errors.append(f"gt.frames[{i}].t0.range_m missing")
    elif t0["range_m"] is not None and not _is_number(t0["range_m"]):
        errors.append(f"gt.frames[{i}].t0.range_m must be number or null")


def _validate_t1(t1, i, errors):
    if not isinstance(t1, dict):
        errors.append(f"gt.frames[{i}].t1 missing or invalid")
        return
    if "state" not in t1:
        errors.append(f"gt.frames[{i}].t1.state missing")
    elif not isinstance(t1["state"], str):
        errors.append(f"gt.frames[{i}].t1.state must be str")
    elif t1["state"] == "":
        errors.append(f"gt.frames[{i}].t1.state must be non-empty")
    for key in ("ttc_s", "min_range_m"):
        if key not in t1:
            errors.append(f"gt.frames[{i}].t1.{key} missing")
        elif not _is_number(t1[key]):
            errors.append(f"gt.frames[{i}].t1.{key} must be number")


def _validate_t2(t2, i, errors, warnings):
    if not isinstance(t2, dict):
        errors.append(f"gt.frames[{i}].t2 missing or invalid")
        return
    for dist_name, key_set in _T2_KEY_SETS.items():
        dist = t2.get(dist_name)
        if dist_name not in t2:
            errors.append(f"gt.frames[{i}].t2.{dist_name} missing")
            continue
        if not isinstance(dist, dict):
            errors.append(f"gt.frames[{i}].t2.{dist_name} must be dict")
            continue
        # クラスキー集合が定義と不一致なら拒否（突合可能性が壊れる）。
        if frozenset(dist.keys()) != key_set:
            errors.append(
                f"gt.frames[{i}].t2.{dist_name} class-key set mismatch"
            )
            continue
        # 各確率値 [0,1]、型。
        total = 0.0
        valid_total = True
        for k, v in dist.items():
            if not _is_number(v):
                errors.append(
                    f"gt.frames[{i}].t2.{dist_name}.{k} must be number"
                )
                valid_total = False
            elif not (0.0 <= v <= 1.0):
                errors.append(
                    f"gt.frames[{i}].t2.{dist_name}.{k} out of [0,1]"
                )
                valid_total = False
            else:
                total += v
        # 合計が 1±0.01 を外れるのは警告のみ（拒否しない）。
        if valid_total and abs(total - 1.0) > _DIST_SUM_TOLERANCE:
            warnings.append(
                f"gt.frames[{i}].t2.{dist_name} sum {total!r} off 1±0.01"
            )


def _validate_t3(t3, i, errors):
    if not isinstance(t3, dict):
        errors.append(f"gt.frames[{i}].t3 missing or invalid")
        return
    # 文字列フィールド（値集合は閉じないが、非空は拒否表で強制＝空文字列は拒否）。
    for key in ("scene_label", "hypothesis", "quality_regime", "scene_regime"):
        if key not in t3:
            errors.append(f"gt.frames[{i}].t3.{key} missing")
        elif not isinstance(t3[key], str):
            errors.append(f"gt.frames[{i}].t3.{key} must be str")
        elif t3[key] == "":
            errors.append(f"gt.frames[{i}].t3.{key} must be non-empty")

    if "vehicle_present" not in t3:
        errors.append(f"gt.frames[{i}].t3.vehicle_present missing")
    elif not isinstance(t3["vehicle_present"], bool):
        errors.append(f"gt.frames[{i}].t3.vehicle_present must be bool")

    for key in _T3_PROB_FIELDS:
        if key not in t3:
            errors.append(f"gt.frames[{i}].t3.{key} missing")
        elif not _in_unit_interval(t3[key]):
            errors.append(f"gt.frames[{i}].t3.{key} out of [0,1]")

    nb = t3.get("next_beat")
    if "next_beat" not in t3:
        errors.append(f"gt.frames[{i}].t3.next_beat missing")
    elif not isinstance(nb, dict):
        errors.append(f"gt.frames[{i}].t3.next_beat must be dict")
    else:
        if "state" not in nb:
            errors.append(f"gt.frames[{i}].t3.next_beat.state missing")
        elif not isinstance(nb["state"], str):
            errors.append(f"gt.frames[{i}].t3.next_beat.state must be str")
        elif nb["state"] == "":
            errors.append(f"gt.frames[{i}].t3.next_beat.state must be non-empty")
        if "p" not in nb:
            errors.append(f"gt.frames[{i}].t3.next_beat.p missing")
        elif not _in_unit_interval(nb["p"]):
            errors.append(f"gt.frames[{i}].t3.next_beat.p out of [0,1]")


# ---------------------------------------------------------------------------
# 正規化・突合
# ---------------------------------------------------------------------------

def normalize(record):
    """canonical record を正規化して返す（冪等・突合キー保持）。

    本フィクスチャは既に canonical 形のため、deep copy を返して
    呼び出し側の改変から守りつつ (scenario_id, ts) 突合キーを保つ。
    """
    return copy.deepcopy(record)


def _record_keys(record):
    sid = record["gt"]["scenario_id"]
    return [(sid, fr["ts"]) for fr in record["gt"]["frames"]]


def reconcile(records_a, records_b):
    """2つのレコード列を (scenario_id, ts) 単位で突合する。"""
    keys_a = []
    seen_a = set()
    for r in records_a:
        for k in _record_keys(r):
            if k not in seen_a:
                seen_a.add(k)
                keys_a.append(k)

    keys_b = []
    seen_b = set()
    for r in records_b:
        for k in _record_keys(r):
            if k not in seen_b:
                seen_b.add(k)
                keys_b.append(k)

    matched = [k for k in keys_a if k in seen_b]
    only_a = [k for k in keys_a if k not in seen_b]
    only_b = [k for k in keys_b if k not in seen_a]
    return ReconcileResult(matched=matched, only_a=only_a, only_b=only_b)


# ---------------------------------------------------------------------------
# DataGovernor
# ---------------------------------------------------------------------------

class DataGovernor:
    """レコード登録・リネージ解決・分割・払い出しを管理する（インメモリ）。"""

    def __init__(self):
        self._records: dict = {}            # scenario_id -> record
        self._split: dict = {}              # scenario_id -> "train"|"seal"|"unassigned"
        self._history: list = []            # SplitAssignment の版履歴
        self._version_counter = 0

    # --- 登録 -------------------------------------------------------------

    def register(self, record):
        """canonical GT record を登録する。

        拒否事由があれば ValidationError、親系統不明なら LineageError。
        正常時は警告を保持した RegisterResult を返す。
        """
        result = validate_record(record)
        if not result.ok:
            raise ValidationError("; ".join(result.errors))

        meta = record["meta"]
        sid = meta["scenario_id"]
        parents = meta["parents"]

        # scenario_id の再登録は拒否（リネージ不変性・ADR 0004 決定2）。
        # 既存レコードは一切変更しない（例外送出のみ。事後改変を許さない）。
        if sid in self._records:
            raise ValidationError(
                f"scenario_id {sid!r} already registered "
                f"(re-registration is forbidden for lineage immutability)"
            )

        # root 宣言（parents=[] かつ 3条件成立）。3条件の構造的整合は
        # validate_record で既に検査済み（不整合ならここに来ない）。
        is_root_decl = (parents == [] and meta["parent_lineage_id"] == sid
                        and meta["generation"] == 0)
        if not is_root_decl:
            # 親系統不明: parents の参照先が未登録なら LineageError。
            for p in parents:
                if p not in self._records:
                    raise LineageError(
                        f"unknown parent {p!r} for {sid!r} (not registered "
                        f"and not a root declaration)"
                    )
            # リネージ検算（ADR 0004 決定1）: parents 連鎖から解決した
            # root・generation と meta の宣言値が一致しなければ拒否。
            # 現仕様は単一親のみ（複数親は LineageError）。
            if len(parents) != 1:
                raise LineageError(
                    f"ambiguous lineage for {sid!r}: multiple parents "
                    f"{parents!r} (merge lineage is not allowed)"
                )
            parent = parents[0]
            resolved_root = self.resolve_root(parent)
            resolved_generation = self.generation_of(parent) + 1
            if meta["parent_lineage_id"] != resolved_root:
                raise ValidationError(
                    f"parent_lineage_id checksum mismatch for {sid!r}: "
                    f"declared {meta['parent_lineage_id']!r} but resolved "
                    f"{resolved_root!r} from parents chain"
                )
            if meta["generation"] != resolved_generation:
                raise ValidationError(
                    f"generation checksum mismatch for {sid!r}: "
                    f"declared {meta['generation']!r} but resolved "
                    f"{resolved_generation!r} from parents chain"
                )

        self._records[sid] = record
        self._split[sid] = meta.get("split", "unassigned") or "unassigned"
        return RegisterResult(scenario_id=sid, warnings=list(result.warnings))

    # --- リネージ解決（推移閉包）------------------------------------------

    def resolve_root(self, scenario_id):
        """推移閉包で root の scenario_id を一意に解決する。"""
        if scenario_id not in self._records:
            raise LineageError(f"unknown scenario_id {scenario_id!r}")

        current = scenario_id
        seen = set()
        while True:
            if current in seen:
                raise LineageError(f"cycle detected resolving {scenario_id!r}")
            seen.add(current)
            rec = self._records.get(current)
            if rec is None:
                raise LineageError(
                    f"lineage broken: {current!r} not registered "
                    f"(resolving {scenario_id!r})"
                )
            parents = rec["meta"]["parents"]
            if not parents:
                return current
            if len(parents) != 1:
                raise LineageError(
                    f"ambiguous lineage for {current!r}: multiple parents "
                    f"{parents!r}"
                )
            current = parents[0]

    def generation_of(self, scenario_id):
        """root からの世代数を返す（root=0）。推移閉包で数える。"""
        if scenario_id not in self._records:
            raise LineageError(f"unknown scenario_id {scenario_id!r}")

        gen = 0
        current = scenario_id
        seen = set()
        while True:
            if current in seen:
                raise LineageError(f"cycle detected resolving {scenario_id!r}")
            seen.add(current)
            rec = self._records.get(current)
            if rec is None:
                raise LineageError(
                    f"lineage broken: {current!r} not registered"
                )
            parents = rec["meta"]["parents"]
            if not parents:
                return gen
            if len(parents) != 1:
                raise LineageError(
                    f"ambiguous lineage for {current!r}: multiple parents "
                    f"{parents!r}"
                )
            current = parents[0]
            gen += 1

    # --- 分割 -------------------------------------------------------------
    #
    # 手動割当 API（set_split）は ADR 0004 で削除した。正規の割当経路は
    # assign_split のみ。split 状態の構成は register が meta.split を
    # そのまま受理することで行う（取込・状態復元・テストの違反状態構成用）。

    def lineage_set(self, split):
        """指定 split に属するレコードの root 親系統ID集合を返す。

        子孫は推移閉包で root へ畳まれる（孫経由リーク検出の前提）。
        """
        roots = set()
        for sid, s in self._split.items():
            if s == split:
                roots.add(self.resolve_root(sid))
        return roots

    def payout(self, split):
        """指定 split のレコード列を払い出す。

        seal と train の root 親系統が交差していれば LineageCrossError。
        """
        seal_roots = self.lineage_set("seal")
        train_roots = self.lineage_set("train")
        if seal_roots & train_roots:
            raise LineageCrossError(
                f"seal and train share root lineage(s): "
                f"{sorted(seal_roots & train_roots)!r}"
            )
        return [self._records[sid] for sid, s in self._split.items()
                if s == split]

    # --- 自動割当（決定的・sha256 安定ソート）----------------------------

    def assign_split(self, seal_count=None, seal_ratio=None, eligible=None):
        """適格 root を sha256 安定ソートし先頭から封印に割当（決定的）。

        seal_count と seal_ratio は排他。eligible は root レコードを受ける
        callable（省略時は全 root 適格）。割当は版として履歴に残す。
        """
        if seal_count is not None and seal_ratio is not None:
            raise SplitError("seal_count and seal_ratio are mutually exclusive")
        if seal_count is None and seal_ratio is None:
            raise SplitError("either seal_count or seal_ratio is required")

        # root レコードのみを対象に適格判定。
        root_ids = [sid for sid, rec in self._records.items()
                    if not rec["meta"]["parents"]]
        if eligible is None:
            eligible_roots = list(root_ids)
        else:
            eligible_roots = [sid for sid in root_ids
                              if eligible(self._records[sid])]

        n_eligible = len(eligible_roots)

        if seal_ratio is not None:
            if not _is_number(seal_ratio) or not (0.0 <= seal_ratio <= 1.0):
                raise SplitError(f"seal_ratio must be in [0,1], got {seal_ratio!r}")
            count = int(round(n_eligible * seal_ratio))
        else:
            if not isinstance(seal_count, int) or isinstance(seal_count, bool):
                raise SplitError(f"seal_count must be int, got {seal_count!r}")
            if seal_count < 0:
                raise SplitError(f"seal_count must be >= 0, got {seal_count!r}")
            if seal_count > n_eligible:
                raise SplitError(
                    f"seal_count {seal_count} exceeds eligible pool {n_eligible}"
                )
            count = seal_count

        ordered = sorted(
            eligible_roots,
            key=lambda s: hashlib.sha256(s.encode("utf-8")).hexdigest(),
        )
        seal_roots = ordered[:count]
        # 練習側は「全 root のうち封印に入らなかったもの」。
        seal_set = set(seal_roots)
        train_roots = [sid for sid in root_ids if sid not in seal_set]

        # split を全レコードに反映（子孫は root の split に従う＝root 単位で畳む）。
        for sid in self._records:
            root = self.resolve_root(sid)
            if root in seal_set:
                self._split[sid] = "seal"
            else:
                self._split[sid] = "train"

        self._version_counter += 1
        assignment = SplitAssignment(
            seal=tuple(seal_roots),
            train=tuple(train_roots),
            version=self._version_counter,
        )
        self._history.append(assignment)
        return assignment

    def assignment_history(self):
        """分割割当の版履歴を返す（再割当しても消えない）。"""
        return list(self._history)
