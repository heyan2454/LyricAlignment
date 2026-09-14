#!/usr/bin/env python3
"""Build a timestamped decision/trigger timeline from the launch logs and sentinel files.

Purpose: the night is decided by rules written before the results, executed by detached chains.  In the
morning you want one list: what fired, when, on what reading, and what it caused — without opening six logs.

    PYTHONPATH=src python scripts/evaluation/make_night_timeline.py --repo . \
        --out docs/status/20260914_night_timeline.md
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

LOG_LINES = re.compile(r"^\[(\d{2}:\d{2}:\d{2})\]\s*(.*)$")
EXIT_PATTERNS = ("exit=", "开始", "结束", "等", "触发", "跳过", "停止", "完成")


def harvest(log_dir: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    if not log_dir.exists():
        return entries
    for path in sorted(log_dir.glob("*.log")):
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            match = LOG_LINES.match(line.strip())
            if not match:
                continue
            clock, message = match.group(1), match.group(2)
            if not any(token in message for token in EXIT_PATTERNS):
                continue
            if len(message) > 150:
                message = message[:150] + "…"
            entries.append({"time": clock, "source": path.name, "message": message})
    # same clock appears in several logs; keep first occurrence per (time, message)
    seen: set[tuple[str, str]] = set()
    unique = []
    for entry in sorted(entries, key=lambda item: item["time"]):
        key = (entry["time"], entry["message"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(entry)
    return unique


def sentinels(log_dir: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not log_dir.exists():
        return out
    for path in sorted(log_dir.iterdir()):
        if path.is_file() and (".done" in path.name or "TRIGGERED" in path.name or "stopped" in path.name):
            try:
                content = path.read_text(encoding="utf-8", errors="replace").strip()[:120]
            except OSError:
                content = ""
            out.append({"file": path.name, "modified": datetime.fromtimestamp(path.stat().st_mtime).strftime("%H:%M:%S"),
                        "content": content})
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument("--log-dir", type=Path,
                        default=Path("/home/hyan/Data/lyricalign/runs/_launch_logs"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    entries = harvest(args.log_dir)
    marks = sentinels(args.log_dir)
    lines = ["# 今晚的时间线（自动汇总：日志与哨兵，不手抄）", "",
             f"> 生成于 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}，来源目录 `{args.log_dir}`；"
             "只收录带时间戳的关键行（开始/结束/exit/等待/触发/跳过/停止）。", "",
             "## 事件流", "", "| 时间 | 来源日志 | 内容 |", "|---|---|---|"]
    for entry in entries:
        lines.append(f"| {entry['time']} | `{entry['source']}` | {entry['message']} |")
    lines += ["", "## 哨兵与标记文件（存在即说明那一步发生过）", "",
              "| 文件 | 最后修改 | 内容 |", "|---|---|---|"]
    for mark in marks:
        lines.append(f"| `{mark['file']}` | {mark['modified']} | {mark['content'] or '（空）'} |")
    lines += ["", "## 怎么用", "",
              "- 想知道\"某条预注册规则有没有真的被执行\"：看事件流里的 `触发`/`停止` 行与哨兵表是否对应；",
              "- 想知道\"某段结果是哪一步产出的\"：按时间对齐日志名与 `results/by_run/` 下的目录时间戳；",
              "- 本文件只反映启动器层面，科学判据的正文仍在各预注册与判决文件里。", ""]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"written": str(args.out), "events": len(entries), "sentinels": len(marks)},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
