"""F-001-2: 合成フィクスチャの突合（(scenario_id, ts) 単位）。

specs/GT_SCHEMA.md「突合(F-001-2)」:
- 突合キーは (scenario_id, ts)。
- baseline 結果GT(F-005)・封印GT(F-002) も canonical 形に正規化してから突合する。
- F-001 時点の検証は合成フィクスチャ（ダミー封印GT・ダミー baseline 結果GT）で行う（2段階方式）。

テストが前提とする supreme.datagov の公開 API:
- datagov.normalize(record) -> canonical record（既に canonical ならそのまま妥当な形を返す）。
- datagov.reconcile(records_a, records_b) -> ReconcileResult
    .matched: list[(scenario_id, ts)]（両者に存在するキー）
    .only_a: list[(scenario_id, ts)]（a にのみ存在）
    .only_b: list[(scenario_id, ts)]（b にのみ存在）
  （a=封印GT 相当、b=baseline 結果GT 相当の「同一フォーマットで突合可能」を検証する。）
"""

import fixtures_gt as fx
from supreme import datagov


def _keys(records):
    """便宜: レコード列から (scenario_id, ts) キー集合を作る。"""
    ks = set()
    for r in records:
        sid = r["gt"]["scenario_id"]
        for fr in r["gt"]["frames"]:
            ks.add((sid, fr["ts"]))
    return ks


def test_F001_2_synthetic_seal_and_baseline_reconcile_by_scenario_ts():
    """F-001-2: ダミー封印GT と ダミー baseline 結果GT を (scenario_id, ts) で突合できる。

    両者を canonical 形に正規化したうえで、共通の (scenario_id, ts) が matched に入る。
    """
    # ダミー封印GT（人手・封印適格）。3フレーム。
    seal_gt = [
        fx.make_record("seal-s1", gt_origin="human", split="seal",
                       n_frames=3, ts_start=0.0, ts_step=1.0),
    ]
    # ダミー baseline 結果GT（同一 scenario_id・同一 ts で同一フォーマット）。
    baseline_gt = [
        fx.make_record("seal-s1", gt_origin="cross_checked",
                       n_frames=3, ts_start=0.0, ts_step=1.0),
    ]

    seal_norm = [datagov.normalize(r) for r in seal_gt]
    base_norm = [datagov.normalize(r) for r in baseline_gt]

    result = datagov.reconcile(seal_norm, base_norm)

    expected = {("seal-s1", 0.0), ("seal-s1", 1.0), ("seal-s1", 2.0)}
    assert set(result.matched) == expected
    assert set(result.only_a) == set()
    assert set(result.only_b) == set()


def test_F001_2_reconcile_reports_unmatched_keys():
    """F-001-2: 一方にしか無い (scenario_id, ts) は only_a / only_b に分離される。"""
    seal_gt = [
        fx.make_record("seal-s1", gt_origin="human",
                       n_frames=3, ts_start=0.0, ts_step=1.0),  # ts 0,1,2
    ]
    baseline_gt = [
        fx.make_record("seal-s1", gt_origin="cross_checked",
                       n_frames=2, ts_start=0.0, ts_step=1.0),  # ts 0,1
        fx.make_record("extra-s2", gt_origin="cross_checked",
                       n_frames=1, ts_start=5.0),               # baseline 側のみ
    ]

    seal_norm = [datagov.normalize(r) for r in seal_gt]
    base_norm = [datagov.normalize(r) for r in baseline_gt]

    result = datagov.reconcile(seal_norm, base_norm)

    assert set(result.matched) == {("seal-s1", 0.0), ("seal-s1", 1.0)}
    assert set(result.only_a) == {("seal-s1", 2.0)}            # 封印のみ
    assert set(result.only_b) == {("extra-s2", 5.0)}          # baseline のみ


def test_F001_2_normalize_is_idempotent_on_canonical_record():
    """F-001-2: 既に canonical なレコードを normalize しても突合キーが保たれる。"""
    rec = fx.make_record("seal-s1", gt_origin="human", n_frames=2)
    norm = datagov.normalize(rec)
    assert _keys([norm]) == {("seal-s1", 0.0), ("seal-s1", 1.0)}
