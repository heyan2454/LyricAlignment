#!/usr/bin/env python3
"""cross_view 一致性信号存在率审计（23_FUTURE_DIRECTIONS 方向 4，结构性缺失路径）。

只读审计：统计 run-root/evidence_v2 中 cross_view / posterior 信息存在率，
并 join LABELS.jsonl 给出 train/validation 下 label 分布与 cross_view 非空率。
当前数据（run2）cross_view 仅含成员元数据（view_group/n_views/view_ids/unit_covered_by），
无 posterior_distance/posterior_vectors，且每 request 单 view —— 无法离线重算，
因此本脚本不重算任何指标，只产出存在率证据与结构性缺失结论。

用法：
  python scripts/research_v7/audit_cross_view_signal.py --run-root <run> --out <audit.json> [--max-rows N]
输出 schema: cross_view_audit_v1（status=structural_missing）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_SCHEMA = "cross_view_audit_v1"
_REASON = (
    "evidence 行 cross_view 仅含成员元数据（view_group/n_views/view_ids/unit_covered_by），"
    "无 posterior_distance/posterior_vectors 字段；且每 request 只落单 view 证据，"
    "raw 仅存 top-16 截断后验，无法离线重算多视图 posterior 距离。"
)
_RECOMMENDATION = "需请求管线显式计算 posterior distance 落盘（同单位 >=2 view 覆盖时以 pairwise L2 计算并写入 cross_view.posterior_distance）"


def _load_rows(path: Path) -> list[dict]:
    """证据文件兼容两种形态：JSON 数组文件（run2 evidence_v2）与单行 JSON 对象。"""
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        return [data]
    if isinstance(data, list):
        return data
    raise ValueError(f"unexpected evidence format: {path.name}")


def _empty_stats() -> dict:
    return {
        "total_rows": 0,
        "rows_with_features_key": 0,
        "rows_cross_view_nonempty": 0,
        "rows_with_posterior_distance": 0,
        "rows_with_posterior_vectors": 0,
        "rows_with_cv_start_diff_sec": 0,
        "rows_with_cv_end_diff_sec": 0,
    }


def audit_evidence(evidence_dir: Path, labels_path: Path | None, max_rows: int | None = None) -> dict:
    """统计 evidence_v2 中 cross_view 信息存在率，并按 LABELS 分组 label 分布。

    返回 cross_view_audit_v1 负载（含 evidence 统计与 splits 分组）。
    """
    files = sorted(evidence_dir.glob("sha256:*.jsonl"))
    stats = _empty_stats()
    truncated = False

    labels: dict[tuple[str, str, int], dict] = {}
    if labels_path is not None and labels_path.is_file():
        for line in labels_path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            key = (row["request_identity"], row["view_id"], row["canonical_unit_id"])
            prev = labels.get(key)
            if prev is None:
                labels[key] = row
            elif prev.get("target") != "official" and row.get("target") == "official":
                labels[key] = row

    splits: dict[str, dict] = {}
    for file in files:
        for row in _load_rows(file):
            if max_rows is not None and stats["total_rows"] >= max_rows:
                truncated = True
                break
            stats["total_rows"] += 1
            if "features" in row:
                stats["rows_with_features_key"] += 1
            cv = row.get("cross_view") or {}
            if cv:
                stats["rows_cross_view_nonempty"] += 1
                if cv.get("posterior_distance") is not None:
                    stats["rows_with_posterior_distance"] += 1
                if cv.get("posterior_vectors") is not None:
                    stats["rows_with_posterior_vectors"] += 1
                if cv.get("start_diff_sec") is not None or cv.get("onset_diff_sec") is not None:
                    stats["rows_with_cv_start_diff_sec"] += 1
                if cv.get("end_diff_sec") is not None or cv.get("offset_diff_sec") is not None:
                    stats["rows_with_cv_end_diff_sec"] += 1
            lab = labels.get((row["request_identity"], row["view_id"], row["canonical_unit_id"]))
            split = (lab or {}).get("split", "unlabeled")
            s = splits.setdefault(split, {"total": 0, "labeled": 0, "cross_view_nonempty": 0, "safe": 0, "unsafe": 0})
            s["total"] += 1
            if lab:
                s["labeled"] += 1
                if lab.get("label") == "safe":
                    s["safe"] += 1
                elif lab.get("label") == "unsafe":
                    s["unsafe"] += 1
            if cv:
                s["cross_view_nonempty"] += 1
        if truncated:
            break

    stats["evidence_files_scanned"] = len(files)
    stats["truncated_by_max_rows"] = truncated
    for s in splits.values():
        s["cross_view_nonempty_rate"] = (s["cross_view_nonempty"] / s["total"]) if s["total"] else None

    return {
        "schema": _SCHEMA,
        "status": "structural_missing",
        "evidence": stats,
        "reason": _REASON,
        "recommendation": _RECOMMENDATION,
        "label_target": "official",
        "label_join_note": ("LABELS 每 (request_identity, view_id, canonical_unit_id) 恰好 2 行"
                            "（raw+official）；join 键不含 target，多行时优先保留 official 行"
                            "（review P1-1：label 分布口径全部为 official target）"),
        "splits": splits,
    }


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="cross_view 信号存在率审计（只读，不重算）")
    parser.add_argument("--run-root", required=True, type=Path, help="run 根目录（含 evidence_v2/ 与 LABELS.jsonl）")
    parser.add_argument("--out", required=True, type=Path, help="输出 JSON 路径")
    parser.add_argument("--max-rows", type=int, default=None, help="采样行数上限（默认全量）")
    args = parser.parse_args(argv)

    evidence_dir = args.run_root / "evidence_v2"
    if not evidence_dir.is_dir():
        print(f"ERROR: evidence_v2 目录不存在: {evidence_dir}", file=sys.stderr)
        return 1
    labels_path = args.run_root / "LABELS.jsonl"
    payload = audit_evidence(evidence_dir, labels_path if labels_path.is_file() else None, args.max_rows)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {args.out} (status={payload['status']}, rows={payload['evidence']['total_rows']})")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
