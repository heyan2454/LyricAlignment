#!/usr/bin/env python3
"""WP0-lite：Long-Slot-Region preflight（只读核对，不做推理）。

产出 PRECHECK.json，包含（15 蓝图 §2/§8 与 14 合同 §8 的子集，能在离线前完成的部分）：
- pytest 通过/总数；
- 人工标签审计：demo 主批已填（VALID_STABLE…UNRESOLVED 计数） vs C10/弱人声/伴奏控制 缺填；
- 潜在 >=90s/>=180s 源发现（同 song_id 片段按 duration 累积）；
- 现状代码 WP 项存在性（identity/timeline/mapping/features/assessor/sparse_slots）；
- git commit 与 dirty 信息。

只读、纯 CPU；不得启动模型推理或覆盖既有 evidence。输出到 --out。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))


def _git_state() -> dict:
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True).stdout.strip() != ""
        return {"git_commit": commit, "dirty_tree": dirty}
    except Exception as e:  # noqa
        return {"git_commit": None, "dirty_tree": None, "error": str(e)}


def run_pytest() -> dict:
    env = dict(__import__("os").environ, PYTHONPATH=str(ROOT / "src"))
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "tests/research_v7"],
                       cwd=ROOT, capture_output=True, text=True, env=env)
    tail = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr.strip()
    return {"passed": tail, "rc": r.returncode, "stdout_tail": tail[:120]}


def audit_human_review() -> dict:
    base = Path("/home/hyan/Data/lyricalign/runs/research_v7_align_behavior")
    out = {"filled": {}, "missing": [], "found_dir": None}
    # demo 主批
    hr = base / "demo_all_partitioned_20260804/human_review/20260804_user_csv"
    summary = hr / "summary.json"
    if summary.exists():
        d = json.loads(summary.read_text())
        out["found_dir"] = str(hr)
        out["filled"]["demo_all_partitioned"] = {"labels": d, "src": str(summary)}
    # C10 / 弱人声 / 伴奏控制 —— 期望缺人工结果
    for cand in ["demo_c10_repeated_sections_20260804", "demo_low_vocal_energy_controls_20260804",
                 "demo_accompaniment_controls_20260804"]:
        p = base / cand
        if p.exists():
            has = list(p.rglob("*human_review*")) or list(p.rglob("*user_csv*"))
            out["missing"].append({"run": cand, "human_results_present": bool(has) and len(has) > 0})
        else:
            out["missing"].append({"run": cand, "exists": False})
    return out


def discover_long_sources(labels_path: Path) -> dict:
    per_song = defaultdict(float)
    n = 0
    for line in labels_path.read_text().splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        dur = float(d.get("duration_sec", 0.0) or 0.0)
        per_song[d.get("song_id", "?")] += dur
        n += 1
    ge90 = {k: round(v, 2) for k, v in per_song.items() if v >= 90}
    ge180 = {k: round(v, 2) for k, v in per_song.items() if v >= 180}
    ge90sorted = sorted(ge90.items(), key=lambda x: -x[1])[:8]
    ge180sorted = sorted(ge180.items(), key=lambda x: -x[1])[:8]
    return {
        "labels_items": n,
        "n_songs": len(per_song),
        "n_songs_ge90": len(ge90),
        "n_songs_ge180": len(ge180),
        "sample_ge90": [{"song": k, "duration": v} for k, v in ge90sorted],
        "sample_ge180": [{"song": k, "duration": v} for k, v in ge180sorted],
    }


def audit_blueprint_wp() -> dict:
    files = {
        "sparse_slots": "src/lyricalign/research_v7/sparse_slots.py",
        "real_executor": "src/lyricalign/research_v7/real_executor.py",
        "timeline": "src/lyricalign/research_v7/timeline.py",
        "identity(after this patch)": "src/lyricalign/research_v7/requests.py",
        "canonical_mapping": "src/lyricalign/research_v7/canonical_mapping.py",
        "slot_planning": "src/lyricalign/research_v7/slot_planning.py",
        "features": "src/lyricalign/research_v7/features.py",
        "region_metrics": "src/lyricalign/research_v7/region_metrics.py",
        "region_assessor": "src/lyricalign/research_v7/region_assessor.py",
        "preflight": "scripts/research_v7/preflight_long_slot_region.py",
        "build_timeline_manifest": "scripts/research_v7/build_long_timeline_manifest.py",
        "run_long_slot_smoke": "scripts/research_v7/run_long_slot_smoke.py",
    }
    return {name: {"exists": (ROOT / rel).exists(), "path": rel} for name, rel in files.items()}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", required=True, help="PRECHECK.json 输出路径")
    p.add_argument("--labels", default="/home/hyan/Data/lyricalign/derived/20260723_qwen_fa_lora_v1/labels/m4singer_qwen_fa_labels.jsonl")
    args = p.parse_args(argv)

    precheck = {
        "schema_version": "research_v7_long_slot_v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "draft": True,
        "git": _git_state(),
        "pytest": run_pytest(),
        "human_review_audit": audit_human_review(),
        "long_sources": discover_long_sources(Path(args.labels)),
        "blueprint_wp_audit": audit_blueprint_wp(),
        "note": "preflight-lite：只读核对+人工标签审计+源发现+WP存在性；formal 未启动，长时间线/hidden 未实现。",
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(precheck, ensure_ascii=False, indent=1))
    print(json.dumps({
        "ok": True,
        "pytest": precheck["pytest"]["passed"],
        "human_filled": list(precheck["human_review_audit"]["filled"].keys()),
        "human_missing": [m["run"] for m in precheck["human_review_audit"]["missing"]],
        "songs_ge90": precheck["long_sources"]["n_songs_ge90"],
        "songs_ge180": precheck["long_sources"]["n_songs_ge180"],
        "out": args.out,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
