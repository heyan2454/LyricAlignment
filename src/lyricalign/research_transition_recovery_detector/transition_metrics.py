"""Transition metrics（纯函数）：unit accuracy / coverage / cursor drift / first error
window / missing-duplicate / occurrence jump / cost summary。

仅消费 committed rows、GT、窗口 records，不触碰模型/音频。
时间字段均为 model/compressed clock；GT 与 rows 的 id 均为 global_character_index。
"""

from __future__ import annotations

from collections import Counter
from typing import Optional

DEFAULT_TOLERANCE_SEC = 0.32  # legacy 兼容（09 §1：正式标签使用 100/250/500/1000ms）
FORMAL_TOLERANCES_MS = (100, 250, 500, 1000)


def error_distribution(committed_rows: list[dict], gt: dict[int, dict]) -> dict:
    """连续 start error 分布（09 P0.5）：所有已评估行的 |pred-gt| 秒。"""
    errors = []
    for row in committed_rows:
        g = gt.get(int(row["global_character_index"]))
        if g is None:
            continue
        errors.append(abs(float(row["start_sec"]) - float(g["start_sec"])))
    errors_sorted = sorted(errors)
    n = len(errors_sorted)
    return {
        "n": n,
        "min_sec": errors_sorted[0] if n else None,
        "median_sec": errors_sorted[n // 2] if n else None,
        "p90_sec": errors_sorted[int(n * 0.9)] if n else None,
        "max_sec": errors_sorted[-1] if n else None,
        "mean_sec": sum(errors_sorted) / n if n else None,
    }


def multi_tolerance_accuracy(committed_rows: list[dict], gt: dict[int, dict],
                             *, tolerances_ms: tuple[int, ...] = FORMAL_TOLERANCES_MS) -> dict:
    """100/250/500/1000ms 多容差正确率（09 §1）；320ms 仅 legacy_320ms。"""
    out = {}
    for ms in tolerances_ms:
        acc = unit_accuracy(committed_rows, gt, tolerance_sec=ms / 1000.0)
        out[f"correct_rate_{ms}ms"] = acc["correct_rate"]
        out[f"correct_{ms}ms"] = acc["correct"]
    out["legacy_320ms"] = unit_accuracy(committed_rows, gt, tolerance_sec=0.32)["correct_rate"]
    return out


def _sorted_gt(gt: dict[int, dict]) -> list[tuple[int, dict]]:
    return sorted((int(k), v) for k, v in gt.items())


def _committed_sorted(committed_rows: list[dict]) -> list[dict]:
    return sorted(committed_rows, key=lambda r: int(r["global_character_index"]))


def unit_accuracy(committed_rows: list[dict], gt: dict[int, dict], *,
                  tolerance_sec: float = DEFAULT_TOLERANCE_SEC) -> dict:
    """逐 committed 行与 GT 同 id 的 start_sec 比较；committed 外不评估。"""
    correct = 0
    wrong = 0
    for row in committed_rows:
        g = gt.get(int(row["global_character_index"]))
        if g is None:
            wrong += 1
            continue
        pred_start = next(
            (float(row[k]) for k in ("original_global_start_sec", "fixed_global_start_sec", "start_sec")
             if row.get(k) is not None),
            None,
        )
        if abs(pred_start - float(g["start_sec"])) <= tolerance_sec:
            correct += 1
        else:
            wrong += 1
    total = correct + wrong
    return {
        "correct": correct,
        "wrong": wrong,
        "total": total,
        "correct_rate": correct / total if total else 0.0,
        "wrong_rate": wrong / total if total else 0.0,
    }


def coverage_stats(total_units: int, committed_count: int) -> dict:
    committed = max(0, min(int(committed_count), int(total_units)))
    return {
        "total_units": int(total_units),
        "committed": committed,
        "uncommitted": max(0, int(total_units) - committed),
        "coverage_rate": committed / total_units if total_units else 0.0,
    }


def _window_committed_end(record: dict) -> int:
    state_after = record["state_after"]
    if isinstance(state_after, dict):
        return int(state_after.get("committed_end_exclusive", 0))
    return int(getattr(state_after, "committed_end_exclusive", 0))


def cursor_time_drift(records: list[dict], gt: dict[int, dict] | None = None) -> dict:
    """每窗：期望时间 = 第 committed_end 个 GT 行 start_sec（gt 参数或外部提供）；
    漂移 = |期望时间 - 该窗最后 committed 行的 start_sec|。

    注意：records 不携带 GT（runner 只存 evidence），调用方必须传 gt；
    gt 缺失时返回空（不再从 evidence 猜测）。
    """
    last_committed = {}
    drifts: list[float] = []
    for record in records:
        committed = _window_committed_rows(record)
        for row in committed:
            last_committed[int(row["global_character_index"])] = row
        end = _window_committed_end(record)
        if gt and end in gt and last_committed:
            expected = float(gt[end]["start_sec"])
            last_row = last_committed[max(last_committed)]
            last_start = next(
                (float(last_row[k]) for k in ("original_global_start_sec", "fixed_global_start_sec", "start_sec")
                 if last_row.get(k) is not None),
                0.0,
            )
            drifts.append(abs(expected - last_start))
    return {
        "window_drifts_sec": drifts,
        "max_drift_sec": max(drifts) if drifts else 0.0,
        "final_drift_sec": drifts[-1] if drifts else 0.0,
    }


def _window_committed_rows(record: dict) -> list[dict]:
    """本窗提交行（兼容 runner 的 evidence schema raw_global_rows + decision 范围）。"""
    evidence = record.get("evidence_summary") or {}
    if not isinstance(evidence, dict):
        return []
    raw = list(evidence.get("raw_global_rows") or [])
    if not raw:
        return list(evidence.get("committed_rows") or [])
    before = int((record.get("state_before") or {}).get("committed_end_exclusive", 0))
    decision = record.get("decision") or {}
    if decision.get("mode") == "oracle_independent":
        return raw
    after = decision.get("committed_end_exclusive")
    if after is None:
        return []
    return [r for r in raw if before <= int(r["global_character_index"]) < int(after)]


def first_error_window(records: list[dict], gt: dict[int, dict], *,
                       tolerance_sec: float = DEFAULT_TOLERANCE_SEC) -> Optional[int]:
    """第一个出现 wrong committed 行的窗；无错误返回 None。"""
    for i, record in enumerate(records):
        acc = unit_accuracy(_window_committed_rows(record), gt, tolerance_sec=tolerance_sec)
        if acc["wrong"] > 0:
            return i
    return None


def missing_duplicate_committed(committed_rows: list[dict], gt: dict[int, dict]) -> dict:
    committed = _committed_sorted(committed_rows)
    if not committed:
        return {"missing_count": 0, "duplicate_count": 0, "missing_ids": []}
    committed_end = int(committed[-1]["global_character_index"]) + 1
    expected = set(range(committed_end))
    actual = [int(r["global_character_index"]) for r in committed]
    counts = Counter(actual)
    duplicates = sum(c - 1 for c in counts.values() if c > 1)
    missing_ids = sorted(expected - set(actual))
    return {"missing_count": len(missing_ids), "duplicate_count": duplicates, "missing_ids": missing_ids}


def occurrence_jump_rate(committed_rows: list[dict], gt_occurrences: dict[int, str]) -> dict:
    jumps = 0
    total = 0
    for row in committed_rows:
        cid = int(row["global_character_index"])
        expected = gt_occurrences.get(cid)
        if expected is None:
            continue
        total += 1
        if str(row.get("occurrence")) != str(expected):
            jumps += 1
    return {"jumps": jumps, "total": total, "jump_rate": jumps / total if total else 0.0}


def cost_summary(records: list[dict], forward_wall_sec: Optional[float] = None) -> dict:
    windows = len(records)
    audio_seconds = 0.0
    for record in records:
        request = record.get("request")
        if isinstance(request, dict):
            bounds = request.get("model_bounds")
        else:
            bounds = getattr(request, "model_bounds", None) if request is not None else None
        if bounds:
            audio_seconds += float(bounds[3]) - float(bounds[0])
    return {
        "windows": windows,
        "forward_count": windows,
        "audio_seconds": audio_seconds,
        "wall_sec": forward_wall_sec,
    }
