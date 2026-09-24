#!/usr/bin/env python3
"""文档层新鲜度与索引完整性自检（纯 CPU、只读仓库）。

存在的理由：2026-09-24 的清点发现 `docs/status/project_current.md` 快照停在 2026-07-28（其后 591 次提交无人更新，
仍写着"下一步是 server GPU smoke/formal"，而那批 GPU 早已跑完并被否证），`docs/sessions/SESSION_INDEX.md` 缺
`20260912_gtsinger_gt_deep_analysis/` 登记，`docs/status/README.md` 停在 07-21 未登记 30 份 9 月状态件。
这类"过期叙述被当成当前事实"是本项目最贵的一类错误，所以把它变成一条可跑的门禁。

    python scripts/docs/check_doc_freshness.py            # 人读输出
    python scripts/docs/check_doc_freshness.py --json     # 机器读
    python scripts/docs/check_doc_freshness.py --max-age-days 21   # 自定义 stale 阈值

退出码：0 = 无发现；1 = 有发现（可当 CI/收尾门禁）。本脚本不写任何文件。
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SNAPSHOT_RE = re.compile(r"(?:Snapshot date|快照日期|最后更新|生成)[:：]?\s*\**\s*(20\d{2})[-/](\d{2})[-/](\d{2})")
DATE_IN_NAME_RE = re.compile(r"20\d{6}")
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s#]+)")
ENTRY_DATE_RE = re.compile(r"^##\s+(20\d{2})-(\d{2})-(\d{2})", re.M)


def git_date(path: Path) -> date | None:
    out = subprocess.run(["git", "-C", str(REPO), "log", "-1", "--format=%cd", "--date=short", "--", str(path)],
                         capture_output=True, text=True)
    raw = out.stdout.strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return None


def declared_date(path: Path) -> date | None:
    """优先取文内声明的快照日期，其次取文件名里的 YYYYMMDD。"""
    head = path.read_text(encoding="utf-8", errors="ignore")[:4000]
    match = SNAPSHOT_RE.search(head)
    if match:
        year, month, day = (int(x) for x in match.groups())
        return date(year, month, day)
    name = DATE_IN_NAME_RE.search(path.name)
    if name:
        return datetime.strptime(name.group(0), "%Y%m%d").date()
    return None


def status_stale(max_age_days: int, today: date) -> list[dict]:
    findings = []
    for path in sorted((REPO / "docs" / "status").glob("*.md")):
        stamp = declared_date(path) or git_date(path)
        if stamp is None:
            findings.append({"file": rel(path), "kind": "no_date",
                             "detail": "既无声明的快照日期，也无 git 提交日期可判定新鲜度"})
            continue
        age = (today - stamp).days
        if age > max_age_days:
            findings.append({"file": rel(path), "kind": "stale", "age_days": age,
                             "snapshot": stamp.isoformat(),
                             "detail": f"快照日期 {stamp} 已 {age} 天 > 阈值 {max_age_days} 天"})
    return findings


def status_readme_gap() -> list[dict]:
    """docs/status/README.md 是否登记了目录里实际存在的活跃件。"""
    readme = REPO / "docs" / "status" / "README.md"
    if not readme.is_file():
        return [{"file": "docs/status/README.md", "kind": "missing_readme"}]
    listed = readme.read_text(encoding="utf-8", errors="ignore")
    missing = [rel(p) for p in sorted((REPO / "docs" / "status").glob("*.md"))
               if p.name not in ("README.md",) and p.name not in listed]
    return [{"file": "docs/status/README.md", "kind": "unregistered_status_files",
             "count": len(missing), "detail": ", ".join(missing[:6]) + (" …" if len(missing) > 6 else "")}] \
        if missing else []


def session_index_gap() -> list[dict]:
    """docs/sessions/ 下每个目录/文件都应在 SESSION_INDEX.md 出现。"""
    index = REPO / "docs" / "sessions" / "SESSION_INDEX.md"
    if not index.is_file():
        return [{"file": "docs/sessions/SESSION_INDEX.md", "kind": "missing_index"}]
    text = index.read_text(encoding="utf-8", errors="ignore")
    sessions = REPO / "docs" / "sessions"
    missing = []
    for path in sorted(sessions.iterdir()):
        if path.name in ("README.md", "_templates", "SESSION_INDEX.md"):
            continue
        needle = path.name if path.is_dir() else path.name
        if needle not in text:
            missing.append(needle + ("/" if path.is_dir() else ""))
    return [{"file": "docs/sessions/SESSION_INDEX.md", "kind": "unregistered_sessions",
             "count": len(missing), "detail": ", ".join(missing)}] if missing else []


def dead_links() -> list[dict]:
    """仓库 md 里的相对链接指向不存在的文件（跳过外链、绝对路径与 runs/results 外置件）。"""
    bad = []
    for path in sorted(REPO.rglob("*.md")):
        if any(part in {".git", "legacy", "archive", "__pycache__", ".dsh"} for part in path.parts):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for target in set(LINK_RE.findall(text)):
            if target.startswith(("http", "mailto:", "/", "#")):
                continue
            if not (path.parent / target).resolve().exists():
                bad.append({"file": rel(path), "kind": "dead_link", "detail": target})
    return bad[:40]


def entry_consistency(today: date) -> list[dict]:
    """AGENTS.md 里写死的"当前最新段/入口日期"是否仍是 AI_SESSION_ENTRY.md 的顶部段。"""
    entry = REPO / "AI_SESSION_ENTRY.md"
    agents = REPO / "AGENTS.md"
    if not (entry.is_file() and agents.is_file()):
        return []
    top = ENTRY_DATE_RE.search(entry.read_text(encoding="utf-8", errors="ignore")[:6000])
    if not top:
        return []
    top_date = date(*(int(x) for x in top.groups()))
    findings = []
    text = agents.read_text(encoding="utf-8", errors="ignore")
    for match in re.finditer(r"(?:当前最新段为|最新段[:：]?\s*)\s*(20\d{2})[-/](\d{2})[-/](\d{2})", text):
        cited = date(*(int(x) for x in match.groups()))
        if cited < top_date:
            findings.append({"file": "AGENTS.md", "kind": "stale_entry_pointer",
                             "detail": f"AGENTS.md 指向 {cited}，而 AI_SESSION_ENTRY.md 顶部段是 {top_date}；"
                                       "AGENTS.md 不应写死入口日期"})
    if (today - top_date).days > 30:
        findings.append({"file": "AI_SESSION_ENTRY.md", "kind": "stale_top_addendum",
                         "detail": f"顶部段日期 {top_date} 距今 {(today - top_date).days} 天，"
                                   "确认是否该补一段新的 override/addendum（或明确当前无自动段）"})
    return findings


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO))
    except ValueError:
        return str(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-age-days", type=int, default=21)
    parser.add_argument("--today", default=None, help="覆盖'今天'（YYYY-MM-DD），便于复算历史快照")
    parser.add_argument("--skip-links", action="store_true", help="跳过全仓 md 死链扫描（较慢）")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    today = datetime.strptime(args.today, "%Y-%m-%d").date() if args.today else date.today()

    findings = status_stale(args.max_age_days, today) + status_readme_gap() + session_index_gap() \
        + entry_consistency(today)
    if not args.skip_links:
        findings += dead_links()

    if args.json:
        print(json.dumps({"today": today.isoformat(), "max_age_days": args.max_age_days,
                          "findings": findings}, ensure_ascii=False, indent=2))
    else:
        print(f"文档新鲜度自检（today={today}，阈值 {args.max_age_days} 天）：{len(findings)} 条发现")
        for item in findings:
            print(f"  [{item['kind']}] {item['file']}"
                  + (f" — {item['detail']}" if item.get("detail") else ""))
    raise SystemExit(1 if findings else 0)


if __name__ == "__main__":
    sys.exit(main())
