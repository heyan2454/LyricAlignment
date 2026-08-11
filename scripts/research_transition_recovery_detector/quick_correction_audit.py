#!/usr/bin/env python3
"""WP0 quick correction audit: provenance inventory and archive integrity (read-only).

子命令（全部只读，不写代码文件之外的东西，不跑 GPU，不加载模型）：
  repo-state     : git HEAD / status --short / dirty file SHA-256 / conda env identity
                   写入 <delivery>/00_meta/REPO_STATE.json
  synthetic-gt   : 扫描 correctness-GT 用法，产出 SYNTHETIC_GT_USAGE_AUDIT.md/.json
  archive-refs   : 扫描文档中的仓库相对路径引用，产出 ARCHIVE_REFERENCE_CHECK.md/.json
  changed-files  : 写 <delivery>/updated_docs/changed-files.txt（初始为空）

约束：禁止臆测——拿不准一律标 unknown；缺失且无法恢复一律标
"referenced but not present in current archive"，禁止伪造。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

DELIVERY_DEFAULT = "/home/hyan/LyricAlignment_20260812_quick_correction"

SCAN_PATTERNS = [
    ("canonical_units", r"canonical_units"),
    ("timeline_manifest", r"timeline_manifest"),
    ("gt_start", r"gt_start"),
    ("gt_end", r"gt_end"),
    ("oracle", r"\boracle\b"),
    ("uniform", r"\buniform\b"),
    ("recovery", r"\brecovery\b"),
    ("start_sec.end_sec", r"start_sec.{0,40}end_sec"),
    ("tolerance_cmp", r"<=?\s*TOLERANCE|\bTOLERANCE\b"),
]

# 已知结论的锁定覆盖（WP0 brief）：仅 run_oracle_recovery.py 有明确已知结论，
# 其余文件走保守启发式，拿不准标 unknown。
KNOWN_OVERRIDES = {
    "run_oracle_recovery.py": {
        "gt_source": "LONG_TIMELINE_MANIFEST.canonical_units (start_sec/end_sec)",
        "synthetic": True,
        "synthetic_kind": "synthetic_uniform_timeline",
        "used_for_correctness": True,
        "valid_for_realgt_correctness": False,
        "conclusion_affected": True,
        "method": "known_override",
        "notes": (
            "canonical_units 的 start_sec/end_sec 作 correctness GT（find_error_segments 定位错误段、"
            "full_song_correct/oracle_fixed/interval@75/@100 评分）；O0 legacy GT-range / O1 GT 设 head / "
            "O2 exact-pair 均用 GT 构造 query。"
        ),
    },
    "semantic_window_planning.py": {
        "gt_source": "canonical units (start_sec/end_sec) consumed for window geometry",
        "synthetic": "unknown",
        "synthetic_kind": "unknown",
        "used_for_correctness": False,
        "valid_for_realgt_correctness": "n/a",
        "conclusion_affected": False,
        "method": "known_override",
        "notes": (
            "仅把 canonical unit 的 start_sec/end_sec 用作窗口规划几何（run 与 window 求交、gap split），"
            "无 correctness 评分，不消费 GT 时间做对齐评估。"
        ),
    },
    "eval_rule_subwindow.py": {
        "gt_source": "LONG_TIMELINE_MANIFEST.canonical_units (start_sec)",
        "synthetic": True,
        "synthetic_kind": "synthetic_uniform_timeline",
        "used_for_correctness": True,
        "valid_for_realgt_correctness": False,
        "conclusion_affected": True,
        "method": "known_override",
        "notes": (
            "subwindow start-only 评分：maes = abs(raw_global_start_sec - canonical_units.start_sec)，"
            "hit = mae <= 1.0 命名为 hit100，实为 start_hit_1s（start-only 1s）；不用 GT end 做双边界评估。"
        ),
    },
    "eval_subwindow.py": {
        "gt_source": "LONG_TIMELINE_MANIFEST.canonical_units (start_sec)",
        "synthetic": True,
        "synthetic_kind": "synthetic_uniform_timeline",
        "used_for_correctness": True,
        "valid_for_realgt_correctness": False,
        "conclusion_affected": True,
        "method": "known_override",
        "notes": (
            "subwindow start-only 评分：mae = abs(raw_start - gt.start_sec)，hit = mae <= 1.0 命名为 "
            "hit100，实为 start_hit_1s（start-only 1s）；仅用 canonical_units.start_sec 作 GT。"
        ),
    },
    "build_long_timeline_manifest.py": {
        "gt_source": "produces LONG_TIMELINE_MANIFEST.canonical_units (uniform concatenation timeline)",
        "synthetic": True,
        "synthetic_kind": "synthetic_uniform_timeline (builder/origin)",
        "used_for_correctness": False,
        "valid_for_realgt_correctness": "n/a",
        "conclusion_affected": True,
        "method": "known_override",
        "notes": (
            "builder 本身不评分，但其产物 canonical_units（start_sec/end_sec）被下游作 correctness GT；"
            "依赖该 GT 的结论受 synthetic timeline 影响。"
        ),
    },
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run_git(repo_root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo_root), *args],
        capture_output=True, text=True, check=True,
    ).stdout


# ---------------------------------------------------------------- repo-state
def cmd_repo_state(args: argparse.Namespace) -> int:
    delivery = Path(args.delivery_dir)
    (delivery / "00_meta").mkdir(parents=True, exist_ok=True)
    head = run_git(REPO_ROOT, "rev-parse", "HEAD").strip()
    status_raw = run_git(REPO_ROOT, "status", "--short")
    dirty = {}
    for line in status_raw.splitlines():
        if not line.strip():
            continue
        code = line[:2]
        path = line[3:].strip()
        if "->" in path:
            path = path.split("->")[-1].strip()
        fpath = REPO_ROOT / path
        try:
            if code.startswith("??"):
                dirty[path] = {"kind": "untracked", "sha256": sha256_bytes(fpath.read_bytes())}
            elif "M" in code:
                diff = subprocess.run(
                    ["git", "-C", str(REPO_ROOT), "diff", "--", path],
                    capture_output=True, check=True,
                ).stdout.encode("utf-8")
                dirty[path] = {"kind": "modified", "sha256": sha256_bytes(diff), "git_diff": True}
            elif "D" in code:
                dirty[path] = {"kind": "deleted", "sha256": None,
                               "note": "deleted from worktree; sha256 unavailable"}
            elif "R" in code or "C" in code:
                if fpath.exists():
                    dirty[path] = {"kind": code.strip(), "sha256": sha256_bytes(fpath.read_bytes())}
                else:
                    dirty[path] = {"kind": code.strip(), "sha256": None}
            else:
                dirty[path] = {"kind": code.strip(), "sha256": sha256_bytes(fpath.read_bytes())}
        except OSError as exc:
            dirty[path] = {"kind": code.strip(), "sha256": None, "note": f"unreadable: {exc}"}
    env_ident = {
        "CONDA_DEFAULT_ENV": os.environ.get("CONDA_DEFAULT_ENV", ""),
        "CONDA_PREFIX": os.environ.get("CONDA_PREFIX", ""),
        "python": sys.version.split()[0],
    }
    state = {
        "schema": "quick_correction_repo_state_v1",
        "worktree_head_sha256": head,
        "git_status_short": status_raw,
        "dirty_files": dirty,
        "environment_identity": env_ident,
        "note": "read-only audit; no files modified in worktree",
    }
    out = delivery / "00_meta" / "REPO_STATE.json"
    out.write_text(json.dumps(state, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps({"head": head, "dirty_files": len(dirty),
                      "out": str(out)}, ensure_ascii=False))
    return 0


# ---------------------------------------------------------------- synthetic-gt
def classify_synthetic_gt(text: str, filename: str) -> dict:
    """按文本启发式分类；filename 命中 KNOWN_OVERRIDES 时用锁定结论。"""
    rel = filename.replace("\\", "/")
    base = rel.rsplit("/", 1)[-1]
    if base in KNOWN_OVERRIDES:
        return dict(KNOWN_OVERRIDES[base], pattern_counts=_count_patterns(text))

    counts = _count_patterns(text)
    has_canonical = counts["canonical_units"] > 0
    has_tl = counts["timeline_manifest"] > 0
    has_gt_times = (counts["gt_start"] > 0 or counts["gt_end"] > 0 or counts["start_sec.end_sec"] > 0)
    has_tol = counts["tolerance_cmp"] > 0
    has_oracle = counts["oracle"] > 0
    has_uniform = counts["uniform"] > 0
    has_recovery = counts["recovery"] > 0
    has_score_words = bool(
        re.search(r"correct(ness)?|recovery_rate|oracle_fixed|accuracy|error rate|@75|@100",
                  text, re.I)
    )
    score_compare = bool(
        (re.search(r"<=?\s*TOLERANCE", text) and re.search(r"gt\[", text))
        or "fixed_global_start_sec" in text
    )

    # GT source
    if has_tl and has_canonical:
        gt_source = "LONG_TIMELINE_MANIFEST.canonical_units"
    elif has_tl:
        gt_source = "LONG_TIMELINE_MANIFEST (specific field unknown)"
    elif has_canonical:
        gt_source = "canonical_units (source context unknown)"
    elif has_gt_times:
        gt_source = "inline start_sec/end_sec (provenance unknown)"
    elif has_oracle:
        gt_source = "oracle (semantics unknown)"
    else:
        gt_source = "none_detected"

    used_for_correctness = bool(gt_source != "none_detected" and score_compare)

    if gt_source == "LONG_TIMELINE_MANIFEST.canonical_units" and used_for_correctness:
        synthetic = True
        synthetic_kind = "synthetic_uniform_timeline (inherited from LONG_TIMELINE_MANIFEST)"
        valid = False
    elif gt_source == "LONG_TIMELINE_MANIFEST.canonical_units":
        synthetic = "unknown"
        synthetic_kind = "unknown"
        valid = "n/a"
    elif gt_source.startswith("canonical_units"):
        synthetic = "unknown"
        synthetic_kind = "unknown"
        valid = "unknown"
    elif has_uniform and used_for_correctness:
        synthetic = True
        synthetic_kind = "synthetic_uniform_timeline (uniform keyword + correctness scoring)"
        valid = False
    elif gt_source in ("none_detected", "oracle (semantics unknown)"):
        synthetic = "unknown"
        synthetic_kind = "unknown"
        valid = "n/a" if not used_for_correctness else "unknown"
    else:
        synthetic = "unknown"
        synthetic_kind = "unknown"
        valid = "unknown"

    if used_for_correctness and synthetic is True:
        conclusion_affected = True
    elif not used_for_correctness and not has_canonical and not has_tl and not has_gt_times:
        conclusion_affected = False
    else:
        conclusion_affected = "unknown"

    return {
        "gt_source": gt_source,
        "synthetic": synthetic,
        "synthetic_kind": synthetic_kind,
        "used_for_correctness": used_for_correctness,
        "valid_for_realgt_correctness": valid,
        "conclusion_affected": conclusion_affected,
        "method": "heuristic",
        "pattern_counts": counts,
        "notes": (
            "heuristic: canonical/timeline_manifest/oracle/uniform/recovery/gt times + "
            "tolerance/score keywords; 拿不准时标 unknown"
            + (f"; recovery={has_recovery}" if has_recovery else "")
            + (f"; uniform={has_uniform}" if has_uniform else ""),
        ),
    }


def _count_patterns(text: str) -> dict:
    return {name: len(re.findall(pat, text, re.I)) for name, pat in SCAN_PATTERNS}


def _scan_targets() -> list[Path]:
    targets = set()
    for pat in (
        "scripts/research_transition_recovery_detector/*.py",
        "/tmp/opencode/*.py",
        "src/lyricalign/research_v7/semantic_window_planning.py",
        "scripts/research_v7/build_long_timeline_manifest.py",
    ):
        p = Path(pat)
        if p.is_absolute():
            targets.update(p.parent.glob(p.name))
        else:
            targets.update((REPO_ROOT / p.parent).glob(p.name))
    return sorted(t for t in targets if t.name != "quick_correction_audit.py")


def cmd_synthetic_gt(args: argparse.Namespace) -> int:
    delivery = Path(args.delivery_dir)
    delivery.mkdir(parents=True, exist_ok=True)
    rows = []
    for path in _scan_targets():
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            rows.append({"file": str(path), "error": str(exc)})
            continue
        rel = path.resolve().relative_to(REPO_ROOT).as_posix() if path.is_relative_to(REPO_ROOT) else str(path)
        cls = classify_synthetic_gt(text, rel)
        sample_lines = []
        for name, pat in SCAN_PATTERNS:
            for m in re.finditer(pat, text, re.I):
                line = text.count("\n", 0, m.start()) + 1
                line_txt = text.splitlines()[line - 1].strip()[:200]
                sample_lines.append({"pattern": name, "line": line, "text": line_txt})
            if len(sample_lines) >= args.max_samples:
                break
        rows.append({
            "file": str(path), "relpath": rel,
            "gt_source": cls["gt_source"],
            "synthetic": cls["synthetic"],
            "synthetic_kind": cls["synthetic_kind"],
            "used_for_correctness": cls["used_for_correctness"],
            "valid_for_realgt_correctness": cls["valid_for_realgt_correctness"],
            "conclusion_affected": cls["conclusion_affected"],
            "method": cls["method"],
            "pattern_counts": cls["pattern_counts"],
            "sample_lines": sample_lines[:args.max_samples],
            "notes": cls["notes"],
        })
    out_json = delivery / "SYNTHETIC_GT_USAGE_AUDIT.json"
    out_json.write_text(json.dumps({"schema": "synthetic_gt_usage_audit_v1", "rows": rows},
                                   ensure_ascii=False, indent=2), "utf-8")
    lines = [
        "# Synthetic-GT Usage Audit (WP0)",
        "",
        "扫描范围：`scripts/research_transition_recovery_detector/*.py`、`/tmp/opencode/*.py`、"
        "`src/lyricalign/research_v7/semantic_window_planning.py`、`scripts/research_v7/build_long_timeline_manifest.py`。",
        "判定原则：禁止臆测，拿不准一律标 `unknown`。",
        "",
        "| File | GT source | synthetic/real | Used for correctness? | Conclusion affected? |",
        "|---|---|---|---|---|",
    ]
    for r in rows:
        f = r.get("relpath", r.get("file", "?"))
        lines.append(
            f"| `{f}` | {r.get('gt_source', '?')} | {r.get('synthetic', '?')} | "
            f"{r.get('used_for_correctness', '?')} | {r.get('conclusion_affected', '?')} |"
        )
    lines.append("")
    lines.append("## 命中详情（每文件 pattern 计数与样例行）")
    for r in rows:
        lines.append(f"### {r.get('relpath', r.get('file'))}")
        lines.append(f"- GT source: {r.get('gt_source')}")
        lines.append(f"- synthetic/real: {r.get('synthetic')} | kind: {r.get('synthetic_kind')}")
        lines.append(f"- Used for correctness: {r.get('used_for_correctness')} | "
                     f"valid_for_realgt_correctness: {r.get('valid_for_realgt_correctness')}")
        lines.append(f"- Conclusion affected: {r.get('conclusion_affected')} | method: {r.get('method')}")
        lines.append(f"- pattern_counts: {r.get('pattern_counts')}")
        for s in r.get("sample_lines", []):
            lines.append(f"  - [{s['pattern']}] L{s['line']}: `{s['text']}`")
        lines.append("")
    out_md = delivery / "SYNTHETIC_GT_USAGE_AUDIT.md"
    out_md.write_text("\n".join(lines), "utf-8")
    hits = [r["relpath"] for r in rows
            if r.get("synthetic") is True and r.get("used_for_correctness")]
    print(json.dumps({"scanned": len(rows), "synthetic_gt_correctness_hits": hits,
                      "out": str(out_md)}, ensure_ascii=False))
    return 0


# ---------------------------------------------------------------- archive-refs
_EXT_RE = re.compile(r"\.(?:py|md|json|jsonl|sh|yaml|yml|txt|cfg|toml|pkl|pt|ckpt|wav|mp3|png|pdf|log|out|ipynb)$", re.I)
_EXTERNAL_PREFIXES = ("http://", "https://", "mailto:", "#", "//", "/home/", "/root/", "/tmp/", "/mnt/", "C:", "$", "{", "~")
_KNOWN_PATH_PREFIXES = ("docs/", "runs/", "results/", "configs/", "scripts/", "src/")
_BASENAME_RE = re.compile(r"(?<!\S)(?:\.{0,2}/)?[A-Za-z0-9_.\-]+(?:/[A-Za-z0-9_.\-]+)+(?:\.(?:[A-Za-z0-9]{1,8}))?(?:[#?][\w.\-]+)?")
_NUM_SLASH_RE = re.compile(r"^\s*-?\d+(?:\.\d+)?\s*/\s*-?\d+(?:\.\d+)?\s*$")
_MATH_SLASH_RE = re.compile(r"^\s*[A-Za-z_][A-Za-z0-9_.]*\s*/\s*[A-Za-z_][A-Za-z0-9_.]*\s*$")
_NAT_LANG_FRAGMENTS = ("n_units", "duration", "density", "gt=")


def _normalise_candidate(raw: str) -> tuple[str | None, str]:
    """规范化单个 token，判断是否为可接受路径候选。

    返回 (normalised_path, classification)；path 为 None 表示被过滤（不可解析 token，
    不计入引用与 missing 分母）。只接受：可解析扩展名 / 已知路径前缀 / 外部绝对路径。
    显式过滤：纯数值比例、a/b 数学表达式、变量名、duration/density 等自然语言片段。
    """
    t = (raw or "").strip().strip("'\"` ")
    if not t:
        return None, "empty"
    t = re.sub(r"[.,;:)\]}>]+$", "", t)
    t = t.split("#")[0].split("?")[0].rstrip("/").strip()
    if not t or "/" not in t:
        return None, "not_path"
    if t.startswith(_EXTERNAL_PREFIXES):
        return t, "external"
    if _NUM_SLASH_RE.match(t):
        return None, "ratio_number"
    if _MATH_SLASH_RE.match(t):
        return None, "math_expression"
    if re.match(r"^[\w\-]+=", t) or any(f in t for f in _NAT_LANG_FRAGMENTS):
        return None, "natural_lang"
    if _EXT_RE.search(t) or t.startswith(_KNOWN_PATH_PREFIXES):
        return t, "path_candidate"
    return None, "not_path"


def _extract_candidates(line: str) -> list[dict]:
    """提取一行中的路径候选。返回 [{raw, path, classification}]；
    path 为 None 的为过滤 token（不计入引用/missing 分母）。

    只接受：① markdown link target `[..](..)`；② 反引号路径；③ 含 `/` 且有可接受扩展名
    或已知前缀的 token。过滤纯数值、比例、a/b 数学表达式、变量名、duration/density 片段。
    """
    out = []
    seen = set()
    for m in re.finditer(r"\[[^\]]*\]\(([^)]+)\)", line):
        raw = m.group(1).strip()
        norm, cls = _normalise_candidate(raw)
        key = norm or raw
        if key in seen:
            continue
        seen.add(key)
        out.append({"raw": raw, "path": norm, "classification": cls})
    for m in re.finditer(r"`([^`]+)`", line):
        raw = m.group(1).strip()
        norm, cls = _normalise_candidate(raw)
        key = norm or raw
        if key in seen:
            continue
        seen.add(key)
        out.append({"raw": raw, "path": norm, "classification": cls})
    for m in _BASENAME_RE.finditer(line):
        raw = m.group(0).rstrip(".,;:)")
        norm, cls = _normalise_candidate(raw)
        if norm is None:
            continue
        if norm in seen:
            continue
        seen.add(norm)
        out.append({"raw": raw, "path": norm, "classification": cls})
    return out


def _resolve(cand: str, source_dir: Path, repo_root: Path) -> Path:
    cand = cand.split("#")[0].split("?")[0].strip("'\" ")
    if cand.startswith("../"):
        return (source_dir / cand).resolve()
    if cand.startswith("./") or "/" in cand and not cand.startswith(("scripts", "docs", "src", "tests", "runs", "results", "configs", "ai")):
        return (source_dir / cand).resolve()
    return (repo_root / cand).resolve()


def classify_reference(cand: str, source_dir: Path, repo_root: Path, recovery=True) -> dict:
    """cand 为空/外部 URL/绝对路径 → external；否则按 worktree 存在性分类。"""
    if not cand or cand.startswith(("http://", "https://", "mailto:", "#", "//")) or cand.startswith("/"):
        return {"referenced_path": cand, "present": False, "missing": False,
                "recovered": None, "recovery_source": None,
                "notes": "external (URL/absolute/anchor); not an archive-relative path"}
    try:
        resolved = _resolve(cand, source_dir, repo_root)
    except Exception as exc:
        return {"referenced_path": cand, "present": False, "missing": True,
                "recovered": False, "recovery_source": None, "notes": f"resolve error: {exc}"}
    if resolved.exists():
        return {"referenced_path": cand, "present": True, "missing": False,
                "recovered": None, "recovery_source": None,
                "notes": f"resolved to {resolved}"}
    recovered = None
    if recovery:
        recovered = _recover_basename(resolved.name, repo_root)
    if recovered:
        return {"referenced_path": cand, "present": False, "missing": True,
                "recovered": True, "recovery_source": recovered,
                "notes": "referenced but not present at referenced path; recovered by basename"}
    return {"referenced_path": cand, "present": False, "missing": True,
            "recovered": False, "recovery_source": None,
            "notes": "referenced but not present in current archive"}


def _recover_basename(name: str, repo_root: Path) -> str | None:
    if not name:
        return None
    found = []
    skip = {".git", "runs", "Data", "data", "cache", "node_modules", "__pycache__"}
    for root, dirs, files in os.walk(repo_root):
        dirs[:] = [d for d in dirs if d not in skip]
        if name in files:
            found.append(Path(root) / name)
            if len(found) >= 3:
                break
    if found:
        try:
            return found[0].relative_to(repo_root).as_posix()
        except ValueError:
            return str(found[0])
    return None


def _iter_source_files(sources: list[Path]) -> list[tuple[Path, list[str]]]:
    out = []
    for src in sources:
        if src.is_file():
            out.append((src, _source_lines(src)))
        elif src.is_dir():
            for p in sorted(src.glob("**/*")):
                if p.is_file() and p.suffix.lower() in {".md", ".py", ".txt", ".json", ".jsonl", ".sh", ".yaml", ".yml"}:
                    out.append((p, _source_lines(p)))
    return out


def _source_lines(p: Path) -> list[str]:
    try:
        return p.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []


def cmd_archive_refs(args: argparse.Namespace) -> int:
    delivery = Path(args.delivery_dir)
    delivery.mkdir(parents=True, exist_ok=True)
    sources = [
        REPO_ROOT / "docs" / "research_transition_recovery_detector_20260808_correction",
        REPO_ROOT / "docs" / "research_transition_recovery_detector_20260807",
        REPO_ROOT / "AI_SESSION_ENTRY.md",
        REPO_ROOT / "runs" / "research_transition_recovery_detector_20260810_realgt_expansion_handoff" / "metadata" / "plans",
    ]
    sources_missing = [str(s) for s in sources if not s.exists()]
    rows = []
    seen = set()
    filtered = []
    for src, lines in _iter_source_files(sources):
        for ln, line in enumerate(lines, 1):
            for cr in _extract_candidates(line):
                path = cr["path"]
                if path is None:
                    filtered.append({"raw": cr["raw"], "classification": cr["classification"]})
                    continue
                key = (str(src), path)
                if key in seen:
                    continue
                seen.add(key)
                rec = classify_reference(path, src.parent, REPO_ROOT)
                rows.append({
                    "reference_source": str(src.relative_to(REPO_ROOT) if src.is_relative_to(REPO_ROOT) else src),
                    "source_line": ln,
                    "original_token": cr["raw"],
                    "token_classification": cr["classification"],
                    **rec,
                })
    missing_total = sum(1 for r in rows if r.get("missing"))
    recovered_total = sum(1 for r in rows if r.get("recovered"))
    filtered_count = len(filtered)
    filtered_examples = sorted({f"{f['raw']} ({f['classification']})" for f in filtered})[:20]
    out_json = delivery / "ARCHIVE_REFERENCE_CHECK.json"
    out_json.write_text(json.dumps({
        "schema": "archive_reference_check_v1",
        "sources_missing": sources_missing,
        "rows": rows,
        "filtered_count": filtered_count,
        "filtered_examples": filtered_examples,
    }, ensure_ascii=False, indent=2), "utf-8")
    lines_md = [
        "# Archive Reference Check (WP0)",
        "",
        "扫描来源：`docs/research_transition_recovery_detector_20260808_correction/`、"
        "`docs/research_transition_recovery_detector_20260807/`、`AI_SESSION_ENTRY.md`、"
        "`runs/.../20260810_realgt_expansion_handoff/metadata/plans/`。",
        "",
    ]
    if sources_missing:
        lines_md += ["## 警告：扫描来源在 worktree 中缺失",
                     "- " + "\n- ".join(f"`{s}`" for s in sources_missing), ""]
    lines_md += [
        f"统计：真实候选引用 {len(rows)} 条，过滤非路径 token {filtered_count} 个"
        f"（不计入引用与 missing 分母），缺失 {missing_total} 条，其中 basename 可恢复 {recovered_total} 条。",
        "",
        "### 过滤 token 示例（原始 token + 分类）",
        *(["- " + e for e in filtered_examples] or ["- 无"]),
        "",
        "| reference_source | original_token | token_classification | referenced_path | present | missing | recovered | recovery_source | notes |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines_md.append(
            f"| `{r['reference_source']}:{r['source_line']}` | `{r['original_token']}` | "
            f"{r['token_classification']} | `{r['referenced_path']}` | "
            f"{r['present']} | {r['missing']} | {r['recovered']} | {r.get('recovery_source') or '-'} | "
            f"{r.get('notes', '')} |"
        )
    out_md = delivery / "ARCHIVE_REFERENCE_CHECK.md"
    out_md.write_text("\n".join(lines_md), "utf-8")
    print(json.dumps({"rows": len(rows), "missing": missing_total,
                      "recovered": recovered_total, "filtered_count": filtered_count,
                      "sources_missing": sources_missing,
                      "out": str(out_md)}, ensure_ascii=False))
    return 0


def cmd_changed_files(args: argparse.Namespace) -> int:
    delivery = Path(args.delivery_dir)
    (delivery / "updated_docs").mkdir(parents=True, exist_ok=True)
    out = delivery / "updated_docs" / "changed-files.txt"
    out.write_text("", "utf-8")
    print(json.dumps({"out": str(out), "bytes": 0}, ensure_ascii=False))
    return 0


# ---------------------------------------------------------------- metric-schema
# WP1: 区分 start-only 1s 命中（legacy `hit100`）与双边界 100ms 命中。
# 规则（按来源修正，来源优先于 token 启发式）：
#   - `hit100` 语义由 source_hint 决定，禁止由名称/上下文自行臆测：
#       * source_hint 含 "window_gate"（window_gate.py / window_gate_report.json）→
#         hit100 取自 metrics.tolerance_hit_rates_ms["100"]，是每 unit start 与 end 均
#         在 100ms 内的双边界 real-GT 指标；bad := hit100<0.7，action=keep。
#       * source_hint 含 "eval_rule_subwindow" 或 "eval_subwindow" → hit100 实为
#         start-only 1s 命中（abs(raw_start - canonical_units.start_sec) <= 1.0），
#         action=rename 成 start_hit_1s。
#       * 其余无来源/无上下文 hit100 一律 unknown + flagged，禁止臆测。
#   - 真正双边界 100ms 命中保留显式名（`tolerance_hit_rates_ms` / `SAFE_MAX_ERROR_SEC` /
#     `safe100_grey100_250_unsafe250_structural_v1`），分类为 both_boundaries_100ms。
#   - 无法证明语义的出现点一律 unknown 并 flag，不臆测。

START_ONLY_HIT_THRESHOLD_SEC = 1.0
BOTH_BOUNDARY_100MS_SEC = 0.100
SECOND_BOUNDARY_250MS_SEC = 0.250

METRIC_SCAN_PATTERNS = [
    ("hit100", r"\bhit100\b"),
    ("start_hit_1s", r"\bstart_hit_1s\b"),
    ("legacy_hit100", r"\blegacy_hit100\b"),
    ("start_mae_sec", r"\bstart_mae_sec\b"),
    ("end_mae_sec", r"\bend_mae_sec\b"),
    ("tolerance_hit_rates_ms", r"\btolerance_hit_rates_ms\b"),
    ("SAFE_MAX_ERROR_SEC", r"\bSAFE_MAX_ERROR_SEC\b"),
    ("UNSAFE_MIN_ERROR_SEC", r"\bUNSAFE_MIN_ERROR_SEC\b"),
    ("safe100_label_schema", r"\bsafe100_grey100_250_unsafe250_structural_v1\b"),
    ("interval@100", r"interval\s*@\s*100"),
    ("interval@75", r"interval\s*@\s*75"),
    ("boundary_100ms", r"(?:边界|Safe|Grey|Unsafe|error\s*<=).{0,24}100\s*ms"),
    ("tolerance_250ms", r"(?:250\s*ms)"),
    ("multi_tolerance", r"\bmulti_tolerance\b"),
    ("MAE", r"\bMAE\b"),
]

# 已知语义的锁定分类（键 = token 名，与 METRIC_SCAN_PATTERNS 同名）。
KNOWN_METRIC_SEMANTICS = {
    # hit100 语义由 source_hint 决定（window_gate → both_boundaries_100ms；subwindow → start_only_1s）；
    # 此默认项仅用于已知项兜底，实际分支在 classify_metric_token 中按来源优先处理，禁止由名称自行推断。
    "hit100": {
        "classification": "unknown",
        "canonical_name": None,
        "deprecated": None,
        "flagged": True,
        "action": "none",
        "notes": (
            "hit100 默认未知（须由 source_hint 判定）：window_gate → both_boundaries_100ms（keep），"
            "eval_*_subwindow → start_only_1s（rename）；无来源一律 unknown+flagged，禁止臆测。"
        ),
    },
    "start_hit_1s": {
        "classification": "start_only_1s",
        "canonical_name": "start_hit_1s",
        "deprecated": False,
        "action": "none",
        "notes": "canonical start-only <=1.0s 命中名（WP1 命名）。",
    },
    "legacy_hit100": {
        "classification": "start_only_1s",
        "canonical_name": "start_hit_1s",
        "deprecated": True,
        "action": "rename",
        "notes": "legacy 兼容别名，必须带 deprecated=true，语义 = start_hit_1s。",
    },
    "start_mae_sec": {
        "classification": "start_only_1s",
        "canonical_name": "start_hit_1s",
        "deprecated": False,
        "action": "none",
        "notes": "start-only MAE 值字段；与 hit100（start_mae<=1.0s 命中）成对出现。",
    },
    "end_mae_sec": {
        "classification": "other",
        "canonical_name": "end_mae_sec",
        "deprecated": False,
        "action": "none",
        "notes": "end-only MAE 值字段，非命中；不属于 1s hit 语义。",
    },
    "tolerance_hit_rates_ms": {
        "classification": "both_boundaries_100ms",
        "canonical_name": "tolerance_hit_rates_ms",
        "deprecated": False,
        "action": "none",
        "notes": (
            "双边界命中率（start 与 end 绝对误差均 <= tol/1000s 才命中，见 "
            "reaggregate_long_slot_real_gt.py _metrics_from_errors）；tol=100 时即双边界 100ms。"
        ),
    },
    "SAFE_MAX_ERROR_SEC": {
        "classification": "both_boundaries_100ms",
        "canonical_name": "SAFE_MAX_ERROR_SEC",
        "deprecated": False,
        "action": "none",
        "notes": "detector_v2_labels 双边界 Safe 阈值 0.100s（onset & offset 均 <=100ms）。",
    },
    "UNSAFE_MIN_ERROR_SEC": {
        "classification": "other",
        "canonical_name": "UNSAFE_MIN_ERROR_SEC",
        "deprecated": False,
        "action": "none",
        "notes": "双边界 schema 的第二边界 0.250s（Unsafe 阈值），属 100/250ms 双边界体系但非 100ms 命中。",
    },
    "safe100_label_schema": {
        "classification": "both_boundaries_100ms",
        "canonical_name": "safe100_grey100_250_unsafe250_structural_v1",
        "deprecated": False,
        "action": "none",
        "notes": "train_detector_helpers_v2 LABEL_SCHEMA：Safe(|err|<=100ms)/Grey/Unsafe，双边界。",
    },
    "interval@100": {
        "classification": "both_boundaries_100ms",
        "canonical_name": "interval@100",
        "deprecated": False,
        "action": "none",
        "notes": "interval 级容差指标，双边界（100ms）；区别于 start-only 1s hit。",
    },
    "interval@75": {
        "classification": "other",
        "canonical_name": "interval@75",
        "deprecated": False,
        "action": "none",
        "notes": "interval 级 75ms 容差指标，双边界但非 100ms。",
    },
    "boundary_100ms": {
        "classification": "both_boundaries_100ms",
        "canonical_name": "boundary_hit_100ms",
        "deprecated": False,
        "action": "rename",
        "notes": "文档对 Safe/Grey/Unsafe 双边界 100ms 描述的表述；推荐显式名 boundary_hit_100ms。",
    },
    "tolerance_250ms": {
        "classification": "other",
        "canonical_name": "tolerance_250ms",
        "deprecated": False,
        "action": "none",
        "notes": "250ms 容差/阈值表述，非 100ms 命中。",
    },
    "multi_tolerance": {
        "classification": "other",
        "canonical_name": "multi_tolerance",
        "deprecated": False,
        "action": "none",
        "notes": "多容差交叉校验，非单一 100ms 命中。",
    },
    "MAE": {
        "classification": "other",
        "canonical_name": "MAE",
        "deprecated": False,
        "action": "none",
        "notes": "通用 MAE 表述，无 hit/阈值语义，无法归入 1s-hit 或 100ms-hit。",
    },
}


def start_hit_1s(start_err_sec: float, threshold_sec: float = START_ONLY_HIT_THRESHOLD_SEC) -> bool:
    """start-only <=1.0s 命中（canonical `start_hit_1s`）。"""
    return abs(float(start_err_sec)) <= threshold_sec


def both_boundaries_hit(start_err_sec: float, end_err_sec: float,
                        tol_sec: float = BOTH_BOUNDARY_100MS_SEC) -> bool:
    """双边界容差命中：start 与 end 绝对误差均 <= tol（100ms 时即 boundary_hit_100ms）。"""
    return abs(float(start_err_sec)) <= tol_sec and abs(float(end_err_sec)) <= tol_sec


def emit_hit_metric(start_err_sec: float) -> dict:
    """canonical emit：start_hit_1s；legacy reader 需要 hit100 时同时给 legacy_hit100+deprecated。"""
    hit = start_hit_1s(start_err_sec)
    return {
        "start_hit_1s": hit,
        "legacy_hit100": hit,
        "legacy_hit100_deprecated": True,
    }


def classify_metric_token(token: str, context_text: str = "", source_hint: str = "") -> dict:
    """分类单个 metric 出现点。来源级 known override 优先于 token 启发式；证据不足一律
    unknown 并 flag（禁止臆测）。

    `hit100` 语义由 source_hint 判定，不得由名称/上下文自行推断：
      - source_hint 含 "window_gate"（window_gate.py / window_gate_report.json）→
        双边界 100ms（start 与 end 均 <=100ms），action=keep；
      - source_hint 含 "eval_rule_subwindow" 或 "eval_subwindow" → start-only 1s
        （abs(raw_start - canonical_units.start_sec) <= 1.0），action=rename 为 start_hit_1s；
      - 其余无来源/无上下文 hit100 → unknown+flagged。
    返回结构含 action（keep/rename/none）与 evidence 字段。
    """
    t = token.strip().lower()
    hint = source_hint or ""
    if t == "hit100":
        if "window_gate" in hint:
            return {
                "token": token,
                "classification": "both_boundaries_100ms",
                "canonical_name": "hit100",
                "deprecated": False,
                "flagged": False,
                "action": "keep",
                "evidence": 'metrics.tolerance_hit_rates_ms["100"]',
                "notes": (
                    "window_gate.py hit100 取自 metrics.tolerance_hit_rates_ms[\"100\"]：每 unit 的 "
                    "start 与 end 均 <=100ms 才算命中（双边界 real-GT）；bad := hit100<0.7 保留，action=keep。"
                ),
                "context_evidence": context_text[:200],
                "source_hint": source_hint,
                "method": "source_override_window_gate",
            }
        if "eval_rule_subwindow" in hint or "eval_subwindow" in hint:
            return {
                "token": token,
                "classification": "start_only_1s",
                "canonical_name": "start_hit_1s",
                "deprecated": True,
                "flagged": False,
                "action": "rename",
                "evidence": "canonical_units.start_sec 与 abs(raw_start - gt.start_sec) <= 1.0 比较",
                "notes": (
                    "subwindow 脚本 hit100 实为 start-only 1s 命中：mae = abs(raw_global_start_sec - "
                    "canonical_units.start_sec)，hit = mae <= 1.0，命名为 hit100 属误导，应 rename 为 "
                    "start_hit_1s（仅用 start_sec 作 GT，不用 end 做双边界评估）。"
                ),
                "context_evidence": context_text[:200],
                "source_hint": source_hint,
                "method": "source_override_subwindow",
            }
        return {
            "token": token,
            "classification": "unknown",
            "canonical_name": None,
            "deprecated": None,
            "flagged": True,
            "action": "none",
            "evidence": None,
            "notes": "未分类 hit100 出现点：无来源/无法证明为 start-only 1s 或双边界 100ms，需人工核对。",
            "context_evidence": context_text[:200],
            "source_hint": source_hint,
            "method": "heuristic_unknown",
        }
    known = KNOWN_METRIC_SEMANTICS.get(token)
    if known:
        return {
            "token": token,
            "classification": known["classification"],
            "canonical_name": known["canonical_name"],
            "deprecated": known["deprecated"],
            "flagged": False,
            "action": known.get("action", "none"),
            "evidence": known["notes"],
            "notes": known["notes"],
            "context_evidence": context_text[:200],
            "source_hint": source_hint,
            "method": "known_override",
        }
    if "100ms" in t or "100 ms" in t:
        return {
            "token": token,
            "classification": "both_boundaries_100ms",
            "canonical_name": "boundary_hit_100ms",
            "deprecated": False,
            "flagged": False,
            "action": "rename",
            "evidence": "token 含 100ms 字面（保守归类）",
            "notes": "含 100ms 字面的 metric 名，按双边界 100ms 归类（未显式证明时保守归类）。",
            "context_evidence": context_text[:200],
            "source_hint": source_hint,
            "method": "heuristic_token",
        }
    return {
        "token": token,
        "classification": "unknown",
        "canonical_name": None,
        "deprecated": None,
        "flagged": True,
        "action": "none",
        "evidence": None,
        "notes": "无法分类的 metric 名，需人工核对。",
        "context_evidence": context_text[:200],
        "source_hint": source_hint,
        "method": "heuristic_unknown",
    }


def _context_lines(text: str, start: int, span: int = 2) -> str:
    lines = text.splitlines()
    lo = max(0, start - span)
    hi = min(len(lines), start + span + 1)
    return " | ".join(ln.strip()[:120] for ln in lines[lo:hi])


def _scan_metric_sources() -> list[dict]:
    """扫描 WP1 指定来源的 metric 出现点（只读；JSON 只读 all_requests 字段名归类）。"""
    rows = []
    doc_dir = REPO_ROOT / "docs" / "research_transition_recovery_detector_20260808_correction"
    targets = []
    if doc_dir.is_dir():
        targets.extend(sorted(doc_dir.glob("*.md")))
    for rel in ("AI_SESSION_ENTRY.md",
                "src/lyricalign/research_v7/detector_v2_labels.py",
                "scripts/research_transition_recovery_detector/train_detector_helpers_v2.py",
                "scripts/research_v7/reaggregate_long_slot_real_gt.py"):
        p = REPO_ROOT / rel
        if p.exists():
            targets.append(p)
    for path in targets:
        rel = path.relative_to(REPO_ROOT).as_posix()
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            rows.append({"path": rel, "line": 0, "token": None, "classification": "unknown",
                         "flagged": True, "error": str(exc)})
            continue
        for name, pat in METRIC_SCAN_PATTERNS:
            for m in re.finditer(pat, text):
                line_no = text.count("\n", 0, m.start()) + 1
                cls = classify_metric_token(name, _context_lines(text, line_no - 1), rel)
                rows.append({
                    "path": rel,
                    "line": line_no,
                    "token": name,
                    "classification": cls["classification"],
                    "canonical_name": cls["canonical_name"],
                    "deprecated": cls["deprecated"],
                    "flagged": cls["flagged"],
                    "action": cls["action"],
                    "evidence": cls["evidence"],
                    "context": cls["context_evidence"],
                    "method": cls["method"],
                    "notes": cls["notes"],
                })
    # result JSON：只读 all_requests 字段归类（读文件本身只取字段名，不加载数据）
    json_path = Path("/tmp/opencode/window_gate_report.json")
    if json_path.exists():
        try:
            data = json.loads(json_path.read_text(encoding="utf-8", errors="replace"))
            reqs = data.get("all_requests") or []
            n_reqs = len(reqs)
            keys = set()
            if reqs:
                keys = set(reqs[0].keys())
            note = (f"all_requests 共 {n_reqs} 条；示例键 {sorted(keys)}；"
                    f"hit100 由 source_hint=window_gate_report.json 判定为双边界 100ms "
                    f"（tolerance_hit_rates_ms['100']，start 与 end 均 <=100ms）。")
            for fname in ("hit100", "start_mae_sec"):
                if fname in keys:
                    cls = classify_metric_token(
                        fname,
                        "all_requests[] 字段：hit100 取自 metrics.tolerance_hit_rates_ms['100']（双边界 100ms），"
                        "start_mae_sec 为 start-only MAE 值",
                        str(json_path),
                    )
                    rows.append({
                        "path": str(json_path),
                        "line": 0,
                        "token": fname,
                        "classification": cls["classification"],
                        "canonical_name": cls["canonical_name"],
                        "deprecated": cls["deprecated"],
                        "flagged": cls["flagged"],
                        "action": cls["action"],
                        "evidence": cls["evidence"],
                        "context": cls["context_evidence"],
                        "method": cls["method"],
                        "notes": note,
                    })
            rows.append({
                "path": str(json_path),
                "line": 0,
                "token": "(report-level)",
                "classification": "other",
                "canonical_name": None,
                "deprecated": None,
                "flagged": False,
                "action": "none",
                "evidence": "BAD_HIT100=0.7 与 all_requests.hit100 同源（window_gate.py is_bad）",
                "context": f"顶层键: {sorted(data.keys())}",
                "method": "json_scan",
                "notes": "BAD_HIT100 顶层统计与 all_requests 的 hit100 同语义（双边界 100ms，"
                         "tolerance_hit_rates_ms['100']）；bad := hit100<0.7，action=keep。",
            })
        except Exception as exc:
            rows.append({"path": str(json_path), "line": 0, "token": None,
                         "classification": "unknown", "flagged": True, "error": str(exc)})
    return rows


def cmd_metric_schema(args: argparse.Namespace) -> int:
    delivery = Path(args.delivery_dir)
    delivery.mkdir(parents=True, exist_ok=True)
    rows = _scan_metric_sources()
    counts = {"start_only_1s": 0, "both_boundaries_100ms": 0, "other": 0, "unknown": 0}
    flagged = []
    for r in rows:
        c = r.get("classification", "unknown")
        counts[c] = counts.get(c, 0) + 1
        if r.get("flagged"):
            flagged.append(r)
    head = run_git(REPO_ROOT, "rev-parse", "HEAD").strip()
    from datetime import datetime, timezone
    provenance = {
        "schema": "metric_schema_audit_v1",
        "command": " ".join(sys.argv),
        "worktree": str(REPO_ROOT),
        "head_sha256": head,
        "utc_timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "result_status": "passed" if not flagged else "flagged",
        "sha256": {str(k): sha256_bytes(p.read_bytes()) if p.exists() else None
                   for k, p in [
                       ("audit_tool", Path(__file__)),
                       ("detector_v2_labels", REPO_ROOT / "src/lyricalign/research_v7/detector_v2_labels.py"),
                       ("train_detector_helpers_v2", REPO_ROOT / "scripts/research_transition_recovery_detector/train_detector_helpers_v2.py"),
                       ("reaggregate_long_slot_real_gt", REPO_ROOT / "scripts/research_v7/reaggregate_long_slot_real_gt.py"),
                   ]},
        "scan_targets": sorted({r["path"] for r in rows}),
    }
    out_json = delivery / "METRIC_SCHEMA_AUDIT.json"
    out_json.write_text(json.dumps({"provenance": provenance, "counts": counts,
                                    "rows": rows}, ensure_ascii=False, indent=2), "utf-8")
    lines = [
        "# Metric Schema Audit (WP1)",
        "",
        "## Provenance",
        f"- absolute_path: `{out_json.resolve()}`",
        f"- head_sha256: `{head}`",
        f"- command: `{provenance['command']}`",
        f"- utc_timestamp: `{provenance['utc_timestamp']}`",
        f"- result_status: `{provenance['result_status']}`",
        f"- sha256: {json.dumps(provenance['sha256'], ensure_ascii=False)}",
        "",
        f"## 分类统计：{json.dumps(counts, ensure_ascii=False)}",
        "",
        "| File / Artifact | Field | Actual definition | Correct interpretation | Action | evidence | method |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| `{r['path']}` | `{r.get('token')}` | {r.get('classification')} | "
            f"{r.get('canonical_name') or '-'} | {r.get('action') or '-'} | "
            f"{(r.get('evidence') or r.get('context', ''))[:120]} | {r.get('method')} |"
        )
    if flagged:
        lines.append("")
        lines.append("## Flagged（未分类/无法证明语义，禁止臆测）")
        for r in flagged:
            lines.append(f"- `{r['path']}:{r.get('line')}` `{r.get('token')}`: "
                         f"{r.get('notes', '')}  context=`{r.get('context', '')[:160]}`")
    out_md = delivery / "METRIC_SCHEMA_AUDIT.md"
    out_md.write_text("\n".join(lines), "utf-8")
    print(json.dumps({"scanned": len(rows), "counts": counts, "flagged": len(flagged),
                      "out": str(out_md)}, ensure_ascii=False))
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--delivery-dir", default=DELIVERY_DEFAULT)
    sub = p.add_subparsers(dest="cmd", required=True)
    p_repo = sub.add_parser("repo-state")
    p_repo.set_defaults(func=cmd_repo_state)
    p_sg = sub.add_parser("synthetic-gt")
    p_sg.add_argument("--max-samples", type=int, default=24)
    p_sg.set_defaults(func=cmd_synthetic_gt)
    p_ar = sub.add_parser("archive-refs")
    p_ar.set_defaults(func=cmd_archive_refs)
    p_cf = sub.add_parser("changed-files")
    p_cf.set_defaults(func=cmd_changed_files)
    p_ms = sub.add_parser("metric-schema")
    p_ms.set_defaults(func=cmd_metric_schema)
    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
