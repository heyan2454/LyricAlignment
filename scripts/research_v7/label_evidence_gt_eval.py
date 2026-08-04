#!/usr/bin/env python3
"""round10：为 evidence 写入 gt_eval 弱标签（固化原先 ad-hoc 的标签注入步骤）。

背景（最终 review MAJOR-1）：formal/MIR/ratio 运行的 evidence 之前由 ad-hoc python 注入
`attempt.gt_eval.unsafe_unit_indices`（missing 尾部被删单位 = 真 unsafe），仓库内无脚本，
且标签定义与 GT_EVAL 的 virtual-gap 评价口径不同（详见 GT_AXIS_NOTE）。

本脚本把该步骤固化为可复现命令：
- missing 请求：unsafe = [n_kept, baseline_unit_count)（被删尾部单位，mutation 标签）
- baseline 请求：unsafe = []（期望全对）
- 标签写回 evidence json（保留原文件备份到同目录 .bak 或仅原地更新，--backup 控制）
- 输出每 item 的标签审计行（item/request/mutation/n_units/unsafe_count/gt_source）

用法：
  PYTHONPATH=src python scripts/research_v7/label_evidence_gt_eval.py \
      --requests <REQUESTS.jsonl> --evidence-dir <run>/evidence [--backup]
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

GT_SOURCE_MISSING = "missing_omitted_units"
GT_SOURCE_BASELINE = "baseline_expected_correct"


def label_evidence(requests_path: Path, evidence_dir: Path, *, backup: bool = False) -> dict:
    """按 REQUESTS 的 mutation 语义写 gt_eval 标签；返回审计摘要。"""
    reqs = {}
    for line in requests_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        reqs[r["request_id"]] = r
    audit = {"labeled": 0, "missing": 0, "baseline": 0, "skipped": 0}
    for p in sorted(evidence_dir.glob("*.json")):
        ev = json.loads(p.read_text(encoding="utf-8"))
        att = ev.get("attempt") or {}
        req = att.get("request") or {}
        rid = req.get("request_id")
        mrow = reqs.get(rid, {})
        mtype = mrow.get("mutation_type") or req.get("mutation_type") or "baseline"
        n_units = len(req.get("text_units") or [])
        if mtype == "missing":
            base_n = (mrow.get("mutation_parameters") or {}).get("baseline_unit_count") or n_units
            removed = max(0, base_n - n_units)
            unsafe = list(range(max(0, n_units - removed), n_units))
            gt = {"unsafe_unit_indices": unsafe, "gt_source": GT_SOURCE_MISSING,
                  "label_definition": "mutation label: deleted tail units (virtual gap GT); "
                                      "NOT boundary-error GT (see GT_AXIS_NOTE)"}
            audit["missing"] += 1
        else:
            gt = {"unsafe_unit_indices": [], "gt_source": GT_SOURCE_BASELINE,
                  "label_definition": "expected correct baseline"}
            audit["baseline"] += 1
        if backup and p.with_suffix(".bak.json").exists() is False:
            shutil.copy2(p, p.with_suffix(".bak.json"))
        att["gt_eval"] = gt
        ev["attempt"] = att
        p.write_text(json.dumps(ev, ensure_ascii=False, indent=1))
        audit["labeled"] += 1
    return audit


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--requests", required=True, help="REQUESTS.jsonl（label 依据）")
    p.add_argument("--evidence-dir", required=True, help="evidence 目录（*.json）")
    p.add_argument("--backup", action="store_true", help="写标签前备份原 evidence 到 .bak.json")
    a = p.parse_args(argv)
    audit = label_evidence(Path(a.requests), Path(a.evidence_dir), backup=a.backup)
    print(json.dumps({"ok": True, **audit}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
