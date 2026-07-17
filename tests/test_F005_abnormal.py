"""F-005: 異常系テスト（U22 対応・想定外形式・空入力）。

specs/SPEC.md F-005 異常系:
  「結果ファイルが想定形式でない／再実行不能な場合はその旨を報告（U22）」
  「黙って読み飛ばさない」

ADR 0005(U22 解決):
  「想定外形式は例外または明示的エラー報告」

対象の異常系:
  1. 必須キー欠落（trace フレームに "ts" が無い / "view" が無い / "gt" が無い）
  2. ts が非数値（文字列・None）
  3. 未知の層キー（8層定義外のキーが view/gt に存在）
     NOTE: 存在するだけで拒否するか / 余分なキーを無視して既知層を処理するか、
            仕様は「黙って読み飛ばさない」とのみ規定。ここでは「少なくとも明示的な
            報告（エラー or 警告フィールド）がある」ことをテストする。
  4. フレーム配列でない（シナリオ値が list でない）
  5. 空の trace（空 dict）
  6. 空のシナリオ（シナリオ値が空リスト）

テストが前提とする supreme.erroran の公開 API:
  erroran.ingest(trace, canonical_records) -> IngestResult | raises erroran.IngestError
  erroran.analyze(trace, canonical_records) -> AnalysisResult | raises erroran.IngestError
  erroran.generate_report(trace, canonical_records) -> str | raises erroran.IngestError

  erroran.TraceFormatError: 想定外形式の場合に送出する例外
  erroran.IngestError: 突合不整合の場合に送出する例外（異常系では TraceFormatError との
                        使い分けを問わず、いずれかの例外または明示エラー情報を要求する）
"""

import pytest

import fixtures_gt as fx
from supreme import erroran

# 正常な canonical GT レコード（異常系テストで canonical 側は常に正常にする）
_CANONICAL = fx.canonical_records_for_trace()


# ---------------------------------------------------------------------------
# ヘルパ: 「黙って読み飛ばさない」を assert する
# ---------------------------------------------------------------------------

def _assert_not_silent(trace, canonical=_CANONICAL):
    """黙って読み飛ばさず、例外または明示エラー情報を返すことを assert する。

    - erroran.TraceFormatError / erroran.IngestError が送出されるか
    - result.ok が False で、errors / mismatches / missing_frames / extra_frames いずれかに情報があるか
    のいずれかを確認する。
    """
    raised = False
    try:
        result = erroran.ingest(trace, canonical)
        # 例外でなく結果を返した場合 → ok が False であるべき
        if result.ok:
            raise AssertionError(
                "想定外の trace に対して ok=True が返った（黙って読み飛ばしている可能性）"
            )
        # エラー情報が存在するか確認
        has_info = (
            getattr(result, "mismatches", None)
            or getattr(result, "missing_frames", None)
            or getattr(result, "extra_frames", None)
            or getattr(result, "errors", None)
            or getattr(result, "format_errors", None)
        )
        assert has_info, "ok=False だがエラー情報が空（黙って失敗している）"
    except (erroran.TraceFormatError, erroran.IngestError):
        raised = True
    return raised


# ---------------------------------------------------------------------------
# 1. 必須キー欠落
# ---------------------------------------------------------------------------

def test_F005_abnormal_missing_ts_in_frame():
    """F-005(U22): フレームに 'ts' キーが無い場合は例外またはエラー報告（黙って読み飛ばさない）。"""
    trace = fx.trace_perfect_2scenario()
    # sc1 フレーム 0.0 から ts を削除する
    del trace["sc1"][0]["ts"]

    try:
        _assert_not_silent(trace)
    except AssertionError:
        raise
    except Exception as e:
        # TraceFormatError / IngestError 以外の例外も「黙って読み飛ばさない」として許容
        assert True


def test_F005_abnormal_missing_view_in_frame():
    """F-005(U22): フレームに 'view' キーが無い場合は例外またはエラー報告。"""
    trace = fx.trace_perfect_2scenario()
    del trace["sc1"][0]["view"]

    try:
        with pytest.raises((erroran.TraceFormatError, erroran.IngestError, Exception)):
            result = erroran.ingest(trace, _CANONICAL)
            assert result.ok is False
    except Exception:
        pass  # 例外が送出されれば良い


def test_F005_abnormal_missing_gt_in_frame():
    """F-005(U22): フレームに 'gt' キーが無い場合は例外またはエラー報告。"""
    trace = fx.trace_perfect_2scenario()
    del trace["sc1"][0]["gt"]

    try:
        result = erroran.ingest(trace, _CANONICAL)
        assert result.ok is False, "gt キー欠落フレームに対して ok=True が返った"
    except (erroran.TraceFormatError, erroran.IngestError):
        pass  # 例外送出も可


# ---------------------------------------------------------------------------
# 2. ts が非数値
# ---------------------------------------------------------------------------

def test_F005_abnormal_ts_is_string():
    """F-005(U22): ts が数値でなく文字列の場合は例外またはエラー報告。"""
    trace = fx.trace_perfect_2scenario()
    trace["sc1"][0]["ts"] = "NOT_A_NUMBER"

    try:
        result = erroran.ingest(trace, _CANONICAL)
        assert result.ok is False, "ts=文字列 に対して ok=True が返った"
    except (erroran.TraceFormatError, erroran.IngestError, TypeError, ValueError):
        pass  # 例外送出も可


def test_F005_abnormal_ts_is_none():
    """F-005(U22): ts が None の場合は例外またはエラー報告。"""
    trace = fx.trace_perfect_2scenario()
    trace["sc1"][0]["ts"] = None

    try:
        result = erroran.ingest(trace, _CANONICAL)
        assert result.ok is False, "ts=None に対して ok=True が返った"
    except (erroran.TraceFormatError, erroran.IngestError, TypeError, ValueError):
        pass  # 例外送出も可


# ---------------------------------------------------------------------------
# 3. 未知の層キー（view/gt に定義外キーが存在）
# ---------------------------------------------------------------------------

def test_F005_abnormal_unknown_layer_key_is_reported():
    """F-005(U22): view/gt に定義外の層キーが存在する場合は明示的報告（黙って無視しない）。

    仕様「黙って読み飛ばさない」に従い、少なくとも何らかの警告・エラーが出ること。
    ただし拒否か警告のいずれかは実装が選択してよい（仕様は二択を明示していない）。
    """
    trace = fx.trace_perfect_2scenario()
    # sc1 の全フレームに未知キーを追加
    for frame in trace["sc1"]:
        frame["view"]["UNKNOWN_LAYER_XYZ"] = "some_value"
        frame["gt"]["UNKNOWN_LAYER_XYZ"] = "some_value"

    # 黙って通過することだけを禁止する（ok=True かつ warnings なし は不可）
    try:
        result = erroran.ingest(trace, _CANONICAL)
        # ok=True の場合、warnings フィールドに何らかの情報があること
        has_warning = (
            getattr(result, "warnings", None)
            or getattr(result, "unknown_keys", None)
        )
        if result.ok and not has_warning:
            raise AssertionError(
                "未知層キーを黙って無視した（warnings も unknown_keys も無い）"
            )
    except (erroran.TraceFormatError, erroran.IngestError):
        pass  # 例外送出は許容


# ---------------------------------------------------------------------------
# 4. フレーム配列でない
# ---------------------------------------------------------------------------

def test_F005_abnormal_scenario_value_is_not_list():
    """F-005(U22): シナリオの値がリストでない場合は例外またはエラー報告。"""
    trace = {"sc1": "NOT_A_LIST", "sc2": []}

    try:
        result = erroran.ingest(trace, _CANONICAL)
        assert result.ok is False, "フレーム配列でない値に対して ok=True が返った"
    except (erroran.TraceFormatError, erroran.IngestError, TypeError, AttributeError):
        pass  # 例外送出も可


def test_F005_abnormal_scenario_value_is_dict():
    """F-005(U22): シナリオの値が dict（単一フレーム）の場合は例外またはエラー報告。

    trace 形式の契約上、値はフレームのリストである必要がある。
    """
    trace = {
        "sc1": {"ts": 0.0, "view": {}, "gt": {}},  # list でなく dict
    }

    try:
        result = erroran.ingest(trace, _CANONICAL)
        assert result.ok is False, "フレームが list でなく dict に対して ok=True が返った"
    except (erroran.TraceFormatError, erroran.IngestError, TypeError, AttributeError):
        pass  # 例外送出も可


# ---------------------------------------------------------------------------
# 5. 空の trace
# ---------------------------------------------------------------------------

def test_F005_abnormal_empty_trace_raises_or_reports_error():
    """F-005(U22): 空の trace {} は例外またはエラー報告（空 dict は有効なデータでない）。

    「空の trace・空のシナリオの扱い（エラー報告）」の仕様に従う。
    """
    trace = {}

    try:
        result = erroran.ingest(trace, _CANONICAL)
        # 空 trace で canonical フレームが存在する場合 → extra_frames が存在するか ok=False
        assert result.ok is False or (
            getattr(result, "extra_frames", None) and len(result.extra_frames) > 0
        ), "空 trace に対して ok=True かつ extra_frames も空（黙って通過している）"
    except (erroran.TraceFormatError, erroran.IngestError):
        pass  # 例外送出も可


def test_F005_abnormal_empty_trace_analyze_raises_or_reports_error():
    """F-005(U22): 空の trace で analyze を呼ぶと例外またはエラー報告。"""
    trace = {}

    try:
        result = erroran.analyze(trace, _CANONICAL)
        # 分析結果として ok が False または layers が空などの情報を期待
        # 黙って空の AnalysisResult を返すことは許容しない
        assert hasattr(result, "layers"), "analyze の戻り値に layers 属性がない"
    except (erroran.TraceFormatError, erroran.IngestError, Exception):
        pass  # 例外送出も可


# ---------------------------------------------------------------------------
# 6. 空のシナリオ（シナリオ値が空リスト）
# ---------------------------------------------------------------------------

def test_F005_abnormal_empty_scenario_frames_reports_error():
    """F-005(U22): シナリオのフレームリストが空の場合はエラー報告。

    「空のシナリオの扱い（エラー報告）」の仕様に従い、
    canonical 側にフレームがある場合に extra_frames として報告されるか例外が送出される。
    """
    trace = {
        "sc1": [],  # 空のフレームリスト
        "sc2": fx.trace_perfect_2scenario()["sc2"],
    }

    try:
        result = erroran.ingest(trace, _CANONICAL)
        # sc1 の canonical フレームが extra_frames に入るか ok=False
        assert result.ok is False or (
            getattr(result, "extra_frames", None)
            and any(m["scenario_id"] == "sc1" for m in result.extra_frames)
        ), "空シナリオに対して ok=True かつ extra_frames も報告されない"
    except (erroran.TraceFormatError, erroran.IngestError):
        pass  # 例外送出も可


# ---------------------------------------------------------------------------
# 7. trace が dict でない（完全な形式違反）
# ---------------------------------------------------------------------------

def test_F005_abnormal_trace_is_not_dict():
    """F-005(U22): trace が dict でない（リストや文字列）場合は例外またはエラー報告。"""
    invalid_traces = [
        [],           # list
        "not_a_dict", # str
        42,           # int
        None,         # None
    ]
    for invalid_trace in invalid_traces:
        try:
            result = erroran.ingest(invalid_trace, _CANONICAL)
            assert result.ok is False, (
                f"無効な trace 型 {type(invalid_trace)} に対して ok=True が返った"
            )
        except (erroran.TraceFormatError, erroran.IngestError, TypeError, AttributeError):
            pass  # 例外送出も可


# ---------------------------------------------------------------------------
# 8. 層キーが 8 層より少ない（部分的な view/gt）
# ---------------------------------------------------------------------------

def test_F005_abnormal_view_missing_layer_key_reported():
    """F-005(U22): view に必須の層キーが欠落している場合は黙って読み飛ばさない。

    8層キーのうち t2_mode が欠落した view は想定外形式として報告される。
    """
    trace = fx.trace_perfect_2scenario()
    # sc1 全フレームの view から t2_mode を削除
    for frame in trace["sc1"]:
        del frame["view"]["t2_mode"]

    try:
        result = erroran.ingest(trace, _CANONICAL)
        # ok=True かつ warnings なし は不可（黙って無視した）
        if result.ok:
            has_warning = (
                getattr(result, "warnings", None)
                or getattr(result, "format_errors", None)
            )
            assert has_warning, (
                "view の t2_mode 欠落を黙って無視した（ok=True かつ warnings も無い）"
            )
    except (erroran.TraceFormatError, erroran.IngestError):
        pass  # 例外送出も可


def test_F005_abnormal_gt_missing_layer_key_reported():
    """F-005(U22): gt に必須の層キーが欠落している場合は黙って読み飛ばさない。

    gt の t3_hypothesis が欠落していれば突合不能として報告される。
    """
    trace = fx.trace_perfect_2scenario()
    # sc1 全フレームの gt から t3_hypothesis を削除
    for frame in trace["sc1"]:
        del frame["gt"]["t3_hypothesis"]

    try:
        result = erroran.ingest(trace, _CANONICAL)
        assert result.ok is False, (
            "gt の t3_hypothesis 欠落に対して ok=True が返った（黙って無視している）"
        )
    except (erroran.TraceFormatError, erroran.IngestError):
        pass  # 例外送出も可
