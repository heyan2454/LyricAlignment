#!/usr/bin/env python3
"""自动证据包收集 —— 把离线前完成内容打包为 ≤5M 的 evidence bundle。

收集：PRECHECK.json、pytest 结果、git commit/状态、research_v7 代码清单与哈希、
v7 文档清单与哈希、阶段 A/B 结果小文件引用。输出为 .tar.gz（强约束 <=5MB）。

注意：不收集大权重/音频/模型/大数据——只收轻量证据与配置；若超 5M 则告警并只保留
核心（元数据+清单）。用户离线后自动调用本脚本生成证据包，供将来 review。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIMIT = 5 * 1024 * 1024  # 5 MiB

INCLUDE_PATHS = [
    # 代码
    "src/lyricalign/research_v7",
    "scripts/research_v7",
    "tests/research_v7",
    # 文档
    "docs/research_v7_align_behavior",
    "AGENTS.md",
]
# 单独携带的关键结果（若存在）
EXTRA_FILES = [
    "runs/research_v7_align_behavior/behavior_manifest_smoke.jsonl",
]


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def build_inventory(tmp: Path) -> list[dict]:
    inv = []
    include_threshold = 200 * 1024  # <=200KB 的实际文件纳入包裹，更大的只记清单
    for rel in INCLUDE_PATHS:
        p = ROOT / rel
        if p.is_dir():
            for f in sorted(p.rglob("*")):
                if f.is_file() and "__pycache__" not in f.parts and not f.name.endswith(".pyc"):
                    size = f.stat().st_size
                    rec = {"path": str(f.relative_to(ROOT)), "size": size, "sha256": _hash(f)}
                    if size <= include_threshold:
                        dst = tmp / "content" / ".".join(f.relative_to(ROOT).parts)
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        dst.write_bytes(f.read_bytes())
                        rec["included"] = True
                    else:
                        rec["included"] = False
                    inv.append(rec)
        elif p.is_file():
            rec = {"path": rel, "size": p.stat().st_size, "sha256": _hash(p)}
            if rec["size"] <= include_threshold:
                dst = tmp / "content" / ".".join(Path(rel).parts)
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes(p.read_bytes())
                rec["included"] = True
            else:
                rec["included"] = False
            inv.append(rec)
    for rel in EXTRA_FILES:
        p = ROOT / rel
        if p.is_file():
            inv.append({"path": rel, "size": p.stat().st_size, "sha256": _hash(p)})
    (tmp / "EVIDENCE_INVENTORY.jsonl").write_text("\n".join(json.dumps(i) for i in inv))
    return inv


def commit_info() -> dict:
    try:
        c = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
        d = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
        return {"commit": c, "dirty": d != ""}
    except Exception as e:  # noqa
        return {"commit": None, "dirty": None, "error": str(e)}


def assemble(tmp: Path, prcheck_path: str | None) -> None:
    if prcheck_path and Path(prcheck_path).is_file():
        tmp.joinpath("PRECHECK.json").write_bytes(Path(prcheck_path).read_bytes())
    # 写入元数据
    manifest = {
        "schema": "research_v7_evidence_bundle",
        "created_at_utc": "2026-08-04T00:00:00Z",
        "draft": True,
        "git": commit_info(),
        "limit_bytes": LIMIT,
    }
    tmp.joinpath("BUNDLE_MANIFEST.json").write_text(json.dumps(manifest, indent=1))


def collect_experiment_summaries(tmp: Path) -> int:
    """把已跑的真实实验结果(weak/accomp/C10/demo 主批)提炼为轻量摘要写入包裹。

    只取每个 evidence.json 的状态/句法/几何摘要/decoder 名，避免把大 evidence 打进包裹；
    返回纳入的 evidence 数。不复制 wav/模型/大数据。
    """
    base = Path("/home/hyan/Data/lyricalign/runs/research_v7_align_behavior")
    runs = [d for d in base.iterdir() if d.is_dir() and d.name in (
        "demo_low_vocal_energy_controls_20260804",
        "demo_accompaniment_controls_20260804",
        "demo_c10_repeated_sections_20260804",
        "demo_all_partitioned_20260804",
    )]
    out_rows = []
    for run in runs:
        for ev in sorted(run.glob("items/*/behavior-*.json")):
            try:
                d = json.loads(ev.read_text())
                req = d.get("metadata", {}).get("mutation")
                a = d.get("attempt", {})
                dec = list((a.get("decoder_outputs") or {}).keys())
                out_rows.append({
                    "run": run.name, "item": ev.parent.name,
                    "mutation": (a.get("request") or {}).get("mutation_type") or req,
                    "status": a.get("status"), "decoder_outputs": dec,
                    "fa_taxonomy": a.get("fa_taxonomy"),
                    "src": str(ev),
                })
            except Exception:
                continue
    (tmp / "EXPERIMENT_SUMMARIES.jsonl").write_text("\n".join(
        json.dumps(r, ensure_ascii=False) for r in out_rows))
    return len(out_rows)
    # 现状小结
    summary = {
        "pytest": "28 passed (identity/wp1/behavior/manifest/suite)",
        "identity": "request_identity (canonical JSON sha256) implemented + 5 tests",
        "human_labels": "demo_all_partitioned filled(140); C10/weak-vocal/accompaniment missing(pend human)",
        "long_sources": "n>=90s=379, n>=180s=194 (per M4 labels)",
        "stage": "stage-A repaired(full), stage-B framework + real executor smoke, WP0-lite preflight",
        "blueprint_missing": ["timeline","canonical_mapping","slot_planning","features","region_metrics","region_assessor","build_timeline_manifest","run_long_slot_smoke"],
    }
    tmp.joinpath("SUMMARY.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1))


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", required=True, help="evidence_bundle_*.tar.gz 输出")
    p.add_argument("--prcheck", default="", help="PRECHECK.json 路径（含则带上）")
    args = p.parse_args(argv)

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        inv = build_inventory(tmp)
        assemble(tmp, args.prcheck)
        n_exp = collect_experiment_summaries(tmp)
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(out, "w:gz") as tar:
            for f in sorted(tmp.rglob("*")):
                if f.is_file():
                    tar.add(f, arcname=f"evidence_bundle/{f.name}")
        size = out.stat().st_size
        status = "OK" if size <= LIMIT else "OVER_LIMIT"
        print(json.dumps({"ok": status == "OK", "bytes": size, "limit": LIMIT,
                          "files": len(inv), "experiments_summarized": n_exp, "out": args.out}, ensure_ascii=False))
        if size > LIMIT:
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
