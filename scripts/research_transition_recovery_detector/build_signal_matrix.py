#!/usr/bin/env python
"""09 §3 P4：构建 SIGNAL_COMPLETION_MATRIX.json（8 个固定 ablation 行）。

用法：
  python scripts/research_transition_recovery_detector/build_signal_matrix.py \
    --session-root <SESSION> [--status <pending|executed|negative|failed|skipped_budget>] \
    [--overrides <{branch_id: {...}} JSON 文件>]

完成语义：status in {executed, negative} 算完成；failed / skipped_budget 不算完成。
H 若 blocked 必须保留失败原因（failure_or_block_reason），不能标 complete。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = "signal_completion_matrix_v1"
CORRECTION_PLAN = "20260808_correction_v1"
COMPLETED_STATUSES = ("executed", "negative")

ABLATION_ROWS = [
    {"branch_id": "H", "signal_groups": ["H"]},
    {"branch_id": "R", "signal_groups": ["R"]},
    {"branch_id": "O", "signal_groups": ["O"]},
    {"branch_id": "H+R", "signal_groups": ["H", "R"]},
    {"branch_id": "H+O", "signal_groups": ["H", "O"]},
    {"branch_id": "R+O", "signal_groups": ["R", "O"]},
    {"branch_id": "H+R+O", "signal_groups": ["H", "R", "O"]},
    {"branch_id": "H+R+O+selected(V/P/S)", "signal_groups": ["H", "R", "O", "V", "P", "S"]},
]

DEFAULT_INPUT_ARTIFACTS = {
    "H": ["06_detector/evidence_hidden.jsonl"],
    "R": ["06_detector/evidence_raw.jsonl"],
    "O": ["06_detector/evidence_official.jsonl"],
    "H+R": ["06_detector/evidence_hidden.jsonl", "06_detector/evidence_raw.jsonl"],
    "H+O": ["06_detector/evidence_hidden.jsonl", "06_detector/evidence_official.jsonl"],
    "R+O": ["06_detector/evidence_raw.jsonl", "06_detector/evidence_official.jsonl"],
    "H+R+O": [
        "06_detector/evidence_hidden.jsonl",
        "06_detector/evidence_raw.jsonl",
        "06_detector/evidence_official.jsonl",
    ],
    "H+R+O+selected(V/P/S)": [
        "06_detector/evidence_hidden.jsonl",
        "06_detector/evidence_raw.jsonl",
        "06_detector/evidence_official.jsonl",
        "06_detector/evidence_cross_window.jsonl",
        "06_detector/evidence_posterior.jsonl",
        "06_detector/evidence_trajectory.jsonl",
    ],
}

ROW_FIELDS = (
    "branch_id",
    "signal_groups",
    "status",
    "input_artifacts",
    "n_train_songs",
    "n_val_songs",
    "n_test_songs",
    "n_units",
    "n_intervals",
    "metrics_artifact",
    "failure_or_block_reason",
)


def build_matrix(status: str = "pending", overrides: dict | None = None) -> dict:
    """构造 8 行固定 ablation matrix；overrides 按 branch_id 覆盖默认值。"""
    overrides = overrides or {}
    rows = []
    for spec in ABLATION_ROWS:
        row = {
            "branch_id": spec["branch_id"],
            "signal_groups": list(spec["signal_groups"]),
            "status": status,
            "input_artifacts": list(DEFAULT_INPUT_ARTIFACTS[spec["branch_id"]]),
            "n_train_songs": None,
            "n_val_songs": None,
            "n_test_songs": None,
            "n_units": None,
            "n_intervals": None,
            "metrics_artifact": None,
            "failure_or_block_reason": None,
        }
        if spec["branch_id"] in overrides:
            row.update(overrides[spec["branch_id"]])
        rows.append(row)
    return {
        "schema_version": SCHEMA_VERSION,
        "correction_plan": CORRECTION_PLAN,
        "n_rows": len(rows),
        "n_completed": sum(1 for r in rows if r["status"] in COMPLETED_STATUSES),
        "completed_rows": [r["branch_id"] for r in rows if r["status"] in COMPLETED_STATUSES],
        "rows": rows,
        "built_at": datetime.now(timezone.utc).isoformat(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build SIGNAL_COMPLETION_MATRIX.json (09 §3 P4)")
    parser.add_argument("--session-root", required=True, help="session root（写入 06_detector/）")
    parser.add_argument("--status", default="pending", help="所有行的默认状态")
    parser.add_argument(
        "--overrides",
        default=None,
        help="JSON 文件：{branch_id: {status/…}} 逐行覆盖",
    )
    parser.add_argument("--dry-run", action="store_true", help="只打印 matrix 不写文件")
    args = parser.parse_args(argv)

    overrides: dict = {}
    if args.overrides:
        overrides = json.loads(Path(args.overrides).read_text(encoding="utf-8"))

    matrix = build_matrix(status=args.status, overrides=overrides)
    if args.dry_run:
        print(json.dumps(matrix, indent=2, ensure_ascii=False))
        return 0

    out_dir = Path(args.session_root) / "06_detector"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "SIGNAL_COMPLETION_MATRIX.json"
    tmp_path = out_path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(matrix, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp_path.replace(out_path)
    print(f"wrote {out_path} (n_completed={matrix['n_completed']}/{matrix['n_rows']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
