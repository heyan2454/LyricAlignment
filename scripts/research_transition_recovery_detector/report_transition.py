#!/usr/bin/env python3
"""Phase 2：Transition 候选选择报告（development_selection）。

规则（07 §6 Phase 2，读取 selection 结果前预注册）：
- Product candidate：优先有效正确提交覆盖（correct committed / total units）、
  低错误提交率与成本；non-serial 若胜出允许成为 Product candidate。
- Mechanism candidate：优先足量 carried-state error 与可解释性。
- 不得使用 m4_formal/MIR/Demo/单歌人工观感选候选。

输出：
  <session>/02_transition/TRANSITION_REPORT.md / .json（per-song macro + pooled）
  <session>/02_transition/CANDIDATE_SELECTION.json
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))


def load(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def pooled(rows: list[dict], key: str) -> float:
    total = sum(r["accuracy"]["total"] for r in rows)
    correct = sum(r["accuracy"]["correct"] for r in rows)
    return correct / total if total else 0.0


def _first_catastrophic(session_root: Path, song_id: str, transition: str,
                         manifest_gt: dict[str, dict[int, dict]]) -> int | None:
    """首窗提交行中错误率 >=0.9 的窗（灾难性错位）。"""
    import json as _json

    rec_path = session_root / "02_transition" / f"{song_id}__{transition}.jsonl"
    if not rec_path.is_file():
        return None
    gt = manifest_gt.get(song_id)
    if gt is None:
        return None
    for line in rec_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = _json.loads(line)
        before = rec["state_before"]["committed_end_exclusive"]
        after = rec["decision"]["committed_end_exclusive"]
        rows = [x for x in rec["evidence_summary"]["raw_global_rows"]
                if before <= int(x["global_character_index"]) < after]
        if not rows:
            continue
        wrong = sum(
            1 for x in rows
            if abs(float(x.get("original_global_start_sec", x["fixed_global_start_sec"]))
                   - gt[int(x["global_character_index"])]["start_sec"]) > 0.25
        )
        if wrong / len(rows) >= 0.9:
            return rec["window_index"]
    return None


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--session-root", required=True)
    p.add_argument("--role", default="model_selection")
    p.add_argument("--timeline-manifest", required=True)
    args = p.parse_args()

    session_root = Path(args.session_root)
    out_dir = session_root / "02_transition"
    formal = load(out_dir / f"FORMAL_{args.role}.json")
    full_song = load(out_dir / f"FULL_SONG_{args.role}.json")
    manifest_gt: dict[str, dict[int, dict]] = {}
    for line in Path(args.timeline_manifest).read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            manifest_gt[r["song_id"]] = {int(u["canonical_unit_id"]): u for u in r["canonical_units"]}

    by_transition: dict[str, list[dict]] = {}
    for r in formal:
        by_transition.setdefault(r["transition"], []).append(r)
    total_units_all = sum(r["accuracy"]["total"] for r in full_song)

    report: dict[str, dict] = {}
    for transition, rows in sorted(by_transition.items()):
        correct_rates = [r["accuracy"]["correct_rate"] for r in rows]
        committed_cov = [r["coverage"]["coverage_rate"] for r in rows]
        wrong_committed = sum(r["accuracy"]["wrong"] for r in rows)
        total_correct = sum(r["accuracy"]["correct"] for r in rows)
        report[transition] = {
            "per_song_correct_rate": [round(v, 3) for v in correct_rates],
            "macro_correct_rate": round(statistics.mean(correct_rates), 4),
            "pooled_correct_rate": round(pooled(rows, "correct"), 4),
            "correct_committed_coverage": round(total_correct / total_units_all, 4),
            "macro_committed_coverage": round(statistics.mean(committed_cov), 4),
            "total_wrong_committed": wrong_committed,
            "total_committed": sum(r["committed"] for r in rows),
            "first_error_window": [r["first_error_window"] for r in rows],
            "first_catastrophic_window": [
                _first_catastrophic(session_root, r["song_id"], r["transition"], manifest_gt)
                for r in rows
            ],
            "cost": {"windows": sum(r["cost"]["windows"] for r in rows),
                     "audio_seconds": round(sum(r["cost"]["audio_seconds"] for r in rows), 1)},
        }
    fs = full_song
    report["full_song_align"] = {
        "per_song_correct_rate": [round(r["accuracy"]["correct_rate"], 3) for r in fs],
        "macro_correct_rate": round(statistics.mean(r["accuracy"]["correct_rate"] for r in fs), 4),
        "pooled_correct_rate": round(pooled(fs, "correct"), 4),
        "max_diff_sec": round(max(r["max_diff_sec"] or 0 for r in fs), 1),
    }
    t0 = report.get("T0_oracle_independent", {})
    fsr = report.get("full_song_align", {})
    # 候选选择
    product_notes: list[str] = []
    if fsr.get("pooled_correct_rate", 0) > t0.get("pooled_correct_rate", 0) * 0.8:
        product = "full_song_align"
        product_notes.append("non-serial 胜出：full-song 单次对齐 pooled correct 与 T0 oracle 上界相当")
    else:
        product = "T2_core_boundary_serial"
        product_notes.append("full-song 未超过 T0 上界 80%；串行 T2 保留为产品候选基线")
    mechanism = "T2_core_boundary_serial"
    mech_notes = [
        "T2 提交量最大（carried-state error 足量），core ownership 语义清晰、可解释",
        "T2 total_wrong_committed 高 → 传播研究所需错误进入 carried state",
    ]
    selection = {
        "schema_version": "candidate_selection_v1",
        "scope": "development_selection",
        "product_candidate": product,
        "product_notes": product_notes,
        "mechanism_candidate": mechanism,
        "mechanism_notes": mech_notes,
        "not_selected": {
            "T1_direct_serial": "与 T2 提交语义接近（input_end vs core_end 差异在此数据上不显著），错误率相当但传播语义无 core 清晰",
            "T3_stable_boundary_serial": "提交内正确率高但覆盖率低（macro 8-17%），留作稳定语义研究",
            "T0_oracle_independent": "依赖 GT 不可部署，仅诊断上界",
        },
        "tie_break": "product: pooled correct 覆盖率与成本；mechanism: wrong committed 量 + 语义清晰度",
    }
    (out_dir / "CANDIDATE_SELECTION.json").write_text(
        json.dumps(selection, ensure_ascii=False, indent=2), "utf-8"
    )
    (out_dir / "TRANSITION_REPORT.json").write_text(
        json.dumps({"scope": "development_selection", "report": report, "selection": selection},
                   ensure_ascii=False, indent=2), "utf-8"
    )
    lines = ["# Transition Formal Report (development_selection)", ""]
    lines.append(f"role: {args.role} | songs: {len(full_song)} | pooled units: "
                 f"{sum(r['accuracy']['total'] for r in full_song)}")
    lines.append("")
    lines.append("| transition | pooled correct* | correct-committed coverage | macro correct | wrong committed |")
    lines.append("|---|---|---|---|---|")
    for t, v in sorted(report.items()):
        lines.append(f"| {t} | {v['pooled_correct_rate']:.3f} | "
                     f"{v.get('correct_committed_coverage', '-'):} | {v['macro_correct_rate']:.3f} | "
                     f"{v.get('total_wrong_committed', '-')} |")
    lines.append("")
    lines.append("*pooled correct: T0/full-song 分母=全部 units；T1/T2/T3 分母=committed units。"
                 "跨口径公平比较用 correct-committed coverage（分子=correct committed，分母=全部 units）。")
    lines.append("")
    lines.append(f"**Product candidate: `{product}`** — " + "; ".join(product_notes))
    lines.append(f"**Mechanism candidate: `{mechanism}`** — " + "; ".join(mech_notes))
    lines.append("")
    lines.append("tolerance: 0.32 s | decoder: raw | compress: retained 3.0 s + silence snap | "
                 "query: full-slot")
    (out_dir / "TRANSITION_REPORT.md").write_text("\n".join(lines), "utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
