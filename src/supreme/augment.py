"""F-003: 練習用データ増強（augment）。

親シナリオから派生（増強）データを生成し、親系統タグを付与して F-001
（DataGovernor）へ train として登録する単一窓口。生成器（AI生成器）は注入可能な
抽象（callable）とし、本モジュールは「機構」のみを担う（ADR 0011 決定1）。

責務:
  - F-003-1（機構）: 派生レコードに親系統タグ（parent_lineage_id / parents /
    generation）を Augmentor が確定で付与し、train として登録する。推移閉包で
    親へ遡及可能（datagov.resolve_root を再利用・独自再発明しない）。生成器が
    親系統タグを詐称しても Augmentor が上書き・検算する。
  - F-003-2（機構）: 増強GTの gt_origin が生成器と別系統（generator_lineage と
    非同一）であることを要求し、満たさない派生は破棄またはフラグする（SPEC 異常系）。
    具体的な U17 ワークフローは実データ投入時まで保留（ADR 0011 決定1）。
  - 着手条件（G1/D1）: 新規 train の root ∩ 封印 root = ∅ を登録の前に検査する。
    root は governor.resolve_root で再解決して求め（保存タグを無検算で信頼しない＝
    D1 回避）、封印 root 集合は seal_store から呼び出しのたびに最新取得する（G1 の
    継続検証点）。封印本体 gt には触れない（root 集合読みのみ・トークン不要）。

契約の最終根拠は specs/SPEC.md「F-003」節、decisions/0011-f003-augment-policies.md、
および tests/test_F003_*.py。本モジュールは datagov（train 権威）と sealset（封印
root 集合の供給元）を受領して突合する。sealset / guard / datagov は改修しない
（ADR 0011 決定3）。
"""

from __future__ import annotations

from dataclasses import dataclass

from . import datagov


# ---------------------------------------------------------------------------
# 既定の生成器系統識別子
#
# F-003-2 の「別系統で確定」契約上、gt_origin == generator_lineage の派生は検算
# 不成立とみなして破棄/フラグする。既定値は確定系統（"cross_checked" /
# "human_reviewed" 等）と衝突しない値にすること（衝突すると正常な増強が破棄される）。
# ---------------------------------------------------------------------------

_DEFAULT_GENERATOR_LINEAGE = "fake_generator"


# ---------------------------------------------------------------------------
# 例外
# ---------------------------------------------------------------------------

class ParentNotRegisteredError(Exception):
    """増強の親 scenario_id が governor に未登録（親系統へ遡及できない）。"""


class SealCrossError(datagov.LineageCrossError):
    """新規 train の root が封印 root と交差する（着手条件・逆方向交差 G1）。

    F-002 の datagov.LineageCrossError を継承する（train→seal 方向＝train を封印に
    足す方向であることが分かる専用名・ADR 0011 決定2「両方向を閉じる」可視化）。
    """


# ---------------------------------------------------------------------------
# 結果オブジェクト
# ---------------------------------------------------------------------------

@dataclass
class AugmentResult:
    """augment が登録に成功した派生1件の来歴。

    scenario_id      : 登録した派生の scenario_id（生成器が採番した derived_id）。
    parent_lineage_id: 付与された親系統タグ（= 親の root）。
    root             : governor.resolve_root による登録後の再解決 root（= 親の root）。
    generation       : 親の generation + 1（孫・ひ孫まで連鎖）。
    split            : "train"（増強は練習用）。
    gt_origin        : 増強GTの確定系統（記録）。
    unverified_gt    : 別系統で確定できていない場合 True（flag モード時のみ True 化）。
    """
    scenario_id: str
    parent_lineage_id: str
    root: str
    generation: int
    split: str
    gt_origin: str
    unverified_gt: bool


# ---------------------------------------------------------------------------
# Augmentor
# ---------------------------------------------------------------------------

class Augmentor:
    """練習用データ増強の単一窓口。

    governor          : datagov.DataGovernor  train 権威。派生は train として登録する。
    seal_store        : sealset.SealStore     封印 root 集合の供給元（突合用・root 集合
                        読みのみ／封印本体 gt には触れない）。
    generator         : callable              注入可能な抽象。署名:
                        generator(parent_record, *, index) -> derived_record。
                        派生レコードの親系統タグは Augmentor が確定で上書きする。
    generator_lineage : str                   生成器の系統識別子。gt_origin がこの値と
                        一致する派生は「生成器と同系統」＝検算不成立とみなす。省略可
                        （既定 "fake_generator"）。
    すべてキーワード専用（既存 datagov/sealset の流儀）。
    """

    def __init__(self, *, governor, seal_store, generator,
                 generator_lineage=_DEFAULT_GENERATOR_LINEAGE):
        self._governor = governor
        self._seal_store = seal_store
        self._generator = generator
        self.generator_lineage = generator_lineage

    # --- 増強 -------------------------------------------------------------

    def augment(self, parent_id, *, count, gt_origin="cross_checked",
                on_unverified="drop"):
        """親 parent_id から count 件の派生を生成し train として登録する。

        手順:
          1) parent_id が governor 未登録なら ParentNotRegisteredError。
          2) 封印突合（着手条件 G1/D1）: 新規 train の root を governor.resolve_root で
             再解決し（保存タグを信頼しない＝D1 回避）、seal_store.sealed_lineage_set()
             （呼び出しのたびに最新取得）と交差するなら SealCrossError（何も登録しない）。
          3) count 件、generator(parent_record, index=i) で派生を生成。生成器の親系統
             タグは信頼せず Augmentor が確定（parents=[parent_id] / parent_lineage_id=
             親の root / generation=親.generation+1 / split="train" / meta.gt_origin=
             gt_origin 引数）。
          4) gt_origin 検算（F-003-2）: gt_origin == generator_lineage なら別系統で確定
             できていない。on_unverified="drop"（既定）→ 登録せず破棄。
             "flag" → 登録するが AugmentResult.unverified_gt=True。
          5) 生き残った派生を governor へ train 登録し AugmentResult のリストを返す。
        """
        # 1) 親の存在確認（未登録なら遡及できないので拒否）。
        try:
            parent_root = self._governor.resolve_root(parent_id)
        except datagov.LineageError as exc:
            raise ParentNotRegisteredError(
                f"親 {parent_id!r} は governor に未登録（増強の親系統へ遡及できない）"
            ) from exc

        parent_generation = self._governor.generation_of(parent_id)
        parent_record = self._get_parent_record(parent_id)

        # 2) 封印突合（着手条件・G1/D1）。新規 train の root は親の root に畳まれる。
        #    保存タグを無検算で信頼せず resolve_root の再解決 root を使う（D1 回避）。
        #    封印 root 集合は呼び出しのたびに seal_store から最新取得する（G1 継続検証）。
        sealed_roots = self._seal_store.sealed_lineage_set()
        if parent_root in sealed_roots:
            raise SealCrossError(
                f"増強 train の root {parent_root!r} が封印 root と交差する"
                f"（train→seal 方向の逆方向交差・着手条件 G1）。何も登録しない。"
            )

        # 3) 検算: gt_origin が生成器系統と同一なら別系統で確定できていない。
        unverified = (gt_origin == self.generator_lineage)
        if unverified and on_unverified == "drop":
            # 既定 drop: 別系統で確定できない派生は登録せず破棄（戻り値に含めない）。
            return []

        derived_lineage_id = parent_root
        derived_generation = parent_generation + 1

        results = []
        for i in range(count):
            derived = self._generator(parent_record, index=i)
            derived = self._finalize_lineage(
                derived,
                parents=[parent_id],
                parent_lineage_id=derived_lineage_id,
                generation=derived_generation,
                gt_origin=gt_origin,
            )

            # 5) train として登録（datagov がスキーマ検証・リネージ検算をする）。
            self._governor.register(derived)
            sid = derived["meta"]["scenario_id"]
            results.append(AugmentResult(
                scenario_id=sid,
                parent_lineage_id=derived["meta"]["parent_lineage_id"],
                root=self._governor.resolve_root(sid),
                generation=derived["meta"]["generation"],
                split=derived["meta"]["split"],
                gt_origin=derived["meta"]["gt_origin"],
                unverified_gt=unverified,
            ))
        return results

    # --- 内部 -------------------------------------------------------------

    def _get_parent_record(self, parent_id):
        """親 scenario_id の登録済み canonical レコードを取得する。

        生成器は親レコードを受けて派生を作る。governor は payout で split ごとに払い出す
        が、親が train/seal/unassigned のどれでも生成器に渡せるよう全 split を探す。
        払い出しの非交差検査（payout）に依存しないよう、split を跨いで探索する。
        """
        for split in ("train", "seal", "unassigned"):
            try:
                records = self._governor.payout(split)
            except datagov.LineageCrossError:
                # payout は seal/train 交差時に送出するが、ここは親レコード取得のための
                # 探索なので交差している split があっても他 split を探す。
                continue
            for rec in records:
                if rec["meta"]["scenario_id"] == parent_id:
                    return rec
        # resolve_root が通る（親は登録済み）のに payout で見つからないのは
        # split 探索の穴。安全側で未登録扱いにする。
        raise ParentNotRegisteredError(
            f"親 {parent_id!r} の登録レコードを取得できない"
        )

    def _finalize_lineage(self, derived, *, parents, parent_lineage_id,
                          generation, gt_origin):
        """生成器が返した派生レコードの親系統タグ等を Augmentor が確定で上書きする。

        生成器が親系統タグ（parents/parent_lineage_id/generation）を詐称しても、ここで
        正しい値に確定する。split は train、gt_origin は引数で上書きする。
        meta.scenario_id（生成器の採番）は保持する。
        """
        meta = derived["meta"]
        meta["parents"] = list(parents)
        meta["parent_lineage_id"] = parent_lineage_id
        meta["generation"] = generation
        meta["split"] = "train"
        meta["gt_origin"] = gt_origin
        return derived
