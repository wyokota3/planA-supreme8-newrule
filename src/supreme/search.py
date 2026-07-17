"""F-012: 組み合わせ探索・探索オーケストレーション（search）。

ADR 0021（U8/U18）で確定した「探索の規律」エンジン。改良モジュール構成の組み合わせを
**決定的 greedy 座標上昇**で探索し、**注入された練習スコアラ**の値のみで最良構成を選ぶ。

本モジュールの核心は探索の規律（= 方法論検証層）:
  - F-012-1 封印非アクセス: 封印（sealset.SealStore）を一切 import・参照しない。
    seal 引数を持たず、封印開封トークンも発行しない（探索フェーズは生涯計数を消費しない）。
  - F-012-2 練習スコアのみ: 選定は注入 scorer の返り値だけで行う。封印スコア等で上書きしない。
  - F-012-3 試行上限: 試行回数は cap（U18=50）を超えない。無改善 patience（U18=10）で撤退。
  - 決定的（F-004-2 の精神）: 乱数・時刻を一切使わず、固定順走査・dict 反復順（挿入順）に
    のみ依存する。同じ axes + scorer で2回 search すると best_config / best_score /
    trial_count / trials / provenance / scorer 呼び出し順が完全一致する。
  - ガードレール違反候補の不採用: candidate_guards（注入）の集約が SearchGate.request_continue
    で不合格になる候補は、練習スコアが高くても採用しない（合格候補からのみ選ぶ）。

契約の最終根拠:
  - specs/SPEC.md「F-012」節（F-012-1/2/3）
  - decisions/0021-u8-u18-f012-search.md（探索空間・手法・停止・試行上限の正）
  - specs/GUARD_IF.md（SearchGate.request_continue / combine_guards / check_trial_cap /
    SelectionProvenanceRecord の dict 契約 {eval_id, split, scenario_id, score}）
  - tests/test_F012_*.py（テスト駆動で固定された前提 API）

guard（SearchGate / combine_guards 等）は **再利用のみ**（本モジュールは guard を改修しない）。
スコアラ（supreme を練習データで走らせる end-to-end）は **上流注入**（本モジュールは実装しない）。

依存: stdlib のみ（dataclasses）。封印（sealset）・ハーネス（harness）は import しない。
"""

from __future__ import annotations

from dataclasses import dataclass

from . import guard


# ---------------------------------------------------------------------------
# 探索結果レコード
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SearchResult:
    """探索結果（練習ベスト構成と決定的な試行来歴）。

    best_config : dict   練習ベスト構成（module_name -> 選択値）。
    best_score  : float  best_config の練習スコア（= scorer(best_config)）。
    trial_count : int    実施した探索試行回数（>=0・cap 以下）。1 試行 = scorer 1 評価。
    provenance  : tuple  選定来歴（SelectionProvenanceRecord の dict 列・全 split="train"）。
                         guard.check_selection_purity に通せる（封印由来0件）。
    trials      : tuple  試行列（決定的）。各要素は評価した candidate と score を含む dict。
    """

    best_config: dict
    best_score: float
    trial_count: int
    provenance: tuple
    trials: tuple


# ---------------------------------------------------------------------------
# 内部ユーティリティ
# ---------------------------------------------------------------------------

def _scenario_id(candidate) -> str:
    """候補構成から決定的・安定なシナリオ識別子を作る。

    axes は挿入順 dict なので、その順序で key=value を連結すれば乱数・時刻に依存しない
    決定的な文字列になる（2回の探索で同一）。
    """
    return ";".join(f"{k}={candidate[k]!r}" for k in candidate)


def _passes_guards(candidate, candidate_guards, search_gate) -> bool:
    """候補の guard 集約合否を SearchGate.request_continue で判定する。

    candidate_guards が None なら guard 制約なし（常に続行可＝True）。
    供給時は candidate の GuardResult 列を combine_guards で集約し、search_gate の
    request_continue にかける。集約不合格（param 予算超・強い項目 δ_strong 違反等）は
    False を返し、その候補は不採用となる（ガードレール違反候補の不採用・ADR 0021）。

    封印開封トークンは一切発行しない（open_token_for_eval を呼ばない）= 探索フェーズで
    SealGuard の生涯計数を消費しない（F-012-1）。
    """
    if candidate_guards is None:
        return True
    aggregate = guard.combine_guards(candidate_guards(candidate))
    return search_gate.request_continue(aggregate)


# ---------------------------------------------------------------------------
# 探索オーケストレーション（決定的 greedy 座標上昇）
# ---------------------------------------------------------------------------

def search(axes, scorer, *, search_gate, candidate_guards=None,
           cap=50, patience=10) -> SearchResult:
    """決定的 greedy 座標上昇で練習ベスト構成を探索する（F-012 の本体）。

    axes        : 順序付き dict {module_name: [候補値, ...]}。各リスト先頭が基準構成
                  （greedy 開始点）。挿入順で走査するため決定的（dict 反復順=挿入順）。
    scorer      : 注入練習スコアラ。scorer(candidate) -> float。candidate は
                  module_name -> 選択値 の dict（封印には一切触れない）。
    search_gate : guard.SearchGate（キーワード専用）。候補 guard 集約の続行可否判定。
    candidate_guards: 省略可。candidate -> list[GuardResult]。combine_guards で集約し
                  request_continue にかける。集約不合格の候補は不採用。None なら制約なし。
    cap         : 試行上限（ハード上限・既定 50・U18）。試行回数は cap を超えない。
    patience    : 無改善撤退基準（既定 10・U18）。連続 patience 試行で改善が無ければ撤退。

    アルゴリズム:
      1. 基準構成（各軸の先頭値）から開始。基準を 1 評価して incumbent（暫定最良）にする。
      2. パスを繰り返す。1 パスでは各軸を固定順に走査し、その軸の各候補値（現値以外）を
         固定順に試して練習スコアを評価する。パス全体で「最も改善する単一の変更」を採用し、
         次のパスへ進む（改善が無ければ収束＝停止）。
      3. 停止条件: 収束（改善する変更が無い） / 試行回数が cap に到達 / 連続無改善が
         patience に到達。いずれも決定的（乱数・時刻なし）。

    返り値 SearchResult（best_config / best_score / trial_count / provenance / trials）。
    """
    # 基準構成 = 各軸の先頭値（挿入順 dict なので決定的）。
    incumbent = {name: values[0] for name, values in axes.items()}

    trials = []
    provenance = []

    def _evaluate(candidate):
        """候補を 1 評価する（= 1 試行）。scorer 呼び出しと来歴記録を行う。

        scorer の返り値は float に正規化して記録する（best_score == scorer(best_config)・
        provenance の score が float であることを満たす）。封印には触れない。
        """
        raw = scorer(candidate)
        score = float(raw)
        eval_id = f"train-{len(trials):04d}"
        snapshot = dict(candidate)
        trials.append({"eval_id": eval_id, "candidate": snapshot, "score": score})
        # SelectionProvenanceRecord（GUARD_IF: {eval_id, split, scenario_id, score}）。
        # 探索は練習用評価のみ = 全 split="train"（封印由来0件）。
        provenance.append({
            "eval_id": eval_id,
            "split": "train",
            "scenario_id": _scenario_id(snapshot),
            "score": score,
        })
        return score

    # 基準構成を評価して暫定最良にする（= 試行 1）。
    best_score = _evaluate(incumbent)
    no_improve_streak = 0

    while True:
        # cap・patience は試行（scorer 評価）単位の停止条件。次の評価前に判定する。
        if len(trials) >= cap:
            break
        if no_improve_streak >= patience:
            break

        # このパスで「最も改善する単一の変更」を探す（決定的・固定順走査）。
        best_move = None          # (axis_name, value, score)
        best_move_score = best_score
        stopped = False

        for axis_name, values in axes.items():
            current_value = incumbent[axis_name]
            for value in values:
                if value == current_value:
                    continue  # 現値は変更でないので評価しない。
                # cap に達したら走査を打ち切る（試行回数が cap を超えないため）。
                if len(trials) >= cap:
                    stopped = True
                    break
                # patience に達したら撤退（連続無改善が続いた）。
                if no_improve_streak >= patience:
                    stopped = True
                    break

                candidate = dict(incumbent)
                candidate[axis_name] = value
                score = _evaluate(candidate)

                # ガードレール違反候補は不採用（高スコアでも採用候補にしない）。
                if not _passes_guards(candidate, candidate_guards, search_gate):
                    no_improve_streak += 1
                    continue

                if score > best_score:
                    # incumbent best_score を厳密に上回る改善＝採用候補。
                    no_improve_streak = 0
                    if score > best_move_score:
                        best_move = (axis_name, value, score)
                        best_move_score = score
                else:
                    # 改善しない試行＝無改善ストリークを伸ばす（撤退判定用）。
                    no_improve_streak += 1
            if stopped:
                break

        if best_move is None:
            # このパスで改善する合格候補が無い＝収束（greedy 停止）。
            break

        # 最も改善する変更を 1 つ採用して次のパスへ。
        axis_name, value, score = best_move
        incumbent = dict(incumbent)
        incumbent[axis_name] = value
        best_score = score

    return SearchResult(
        best_config=dict(incumbent),
        best_score=best_score,
        trial_count=len(trials),
        provenance=tuple(provenance),
        trials=tuple(trials),
    )
