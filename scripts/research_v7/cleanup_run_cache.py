#!/usr/bin/env python3
"""Detector V2 run 缓存清理（40G 存储预算；只删内容寻址缓存，不删证据）。

删除对象（仅 --apply 时删除；缺省 dry-run 打印计划）：
- <run>/items/、<run>/evidence/、<run>/cached/（内容寻址缓存；--resume 复用需要，
  证据源是 evidence_v2/ + LABELS + 全部 JSON 产物；未来重新 forward 会重建）

保留：evidence_v2/、LABELS*.jsonl、LABEL_SUMMARY.json、全部评价 JSON、
manifests/、timeline_v4/LONG_TIMELINE_MANIFEST.jsonl（audio 可再生成）。

不 kill 任何进程；删除前逐项 du 复核。用法：
  PYTHONPATH=src python scripts/research_v7/cleanup_run_cache.py \
      --runs /home/hyan/Data/lyricalign/runs/research_v7_detector_v2/run1 \
      --runs /home/hyan/Data/lyricalign/runs/research_v7_detector_v2/run2
  # 追加 --apply 执行删除
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

CACHE_DIRS = ("items", "evidence", "cached")


def plan(runs: list[Path]) -> list[tuple[Path, int]]:
    plan_items: list[tuple[Path, int]] = []
    for run in runs:
        run = Path(run).expanduser().resolve()
        if run == run.anchor:
            print(f"refuse root path: {run}", file=sys.stderr)
            continue
        if not run.is_dir():
            print(f"skip (not dir): {run}", file=sys.stderr)
            continue
        for name in CACHE_DIRS:
            p = run / name
            if not p.is_dir() or p.is_symlink():
                continue
            size = sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
            plan_items.append((p, size))
    return plan_items


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--runs", action="append", required=True, help="run 根（可多次）")
    p.add_argument("--apply", action="store_true", help="实际删除（缺省 dry-run）")
    a = p.parse_args(argv)
    runs = [Path(r) for r in a.runs]
    items = plan(runs)
    if not items:
        print(json_dumps({"ok": True, "dry_run": not a.apply, "items": []}))
        return 0
    total = sum(s for _, s in items)
    print(json_dumps({"ok": True, "dry_run": not a.apply,
                      "items": [{"path": str(p), "bytes": s, "MB": round(s / 1e6, 1)}
                                for p, s in items],
                      "total_MB": round(total / 1e6, 1)}))
    if a.apply:
        removed, failed = [], []
        for p, s in items:
            try:
                shutil.rmtree(p)
                removed.append((str(p), s))
                print(f"removed {p} ({round(s / 1e6, 1)} MB)")
            except OSError as e:  # 权限/IO 失败不中断其余清理
                failed.append((str(p), str(e)))
                print(f"FAILED {p}: {e}", file=sys.stderr)
        print(json_dumps({"ok": not failed, "dry_run": False,
                          "removed": [{"path": p, "MB": round(s / 1e6, 1)} for p, s in removed],
                          "failed": failed}))
    return 0


def json_dumps(d):
    import json
    return json.dumps(d, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    raise SystemExit(main())
