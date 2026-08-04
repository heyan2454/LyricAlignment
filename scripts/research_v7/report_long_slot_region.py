#!/usr/bin/env python3
"""WP7：report_long_slot_region —— draft 汇总与 budget/pilot 报告。

读取 smoke/pilot/formal 结果，输出 AUTO_SUMMARY.json + AUTO_FINDINGS_DRAFT.md + RUNTIME_BUDGET.json。
P0-5：除非提供的 --formal-approved-manifest 真实存在且其 sha256 与 --expected-manifest-sha256
一致，否则一律 draft=true；不可仅凭“传了参数”就降级。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run-root", required=True)
    p.add_argument("--formal-approved-manifest", default="", help="正式汇总才使用该 manifest")
    p.add_argument("--expected-manifest-sha256", default="", help="冻结 manifest 的 sha256（须匹配才 formal_approved）")
    args = p.parse_args(argv)

    run = Path(args.run_root)
    smoke_f = run / "smoke" / "LONG_SLOT_SMOKE.json"
    if not smoke_f.exists():
        print(json.dumps({"ok": False, "reason": "no smoke result"}), ensure_ascii=False)
        return 3
    d = json.loads(smoke_f.read_text())

    # P0-5：formal_approved 必须 manifest 存在 + sha256 匹配；否则 draft
    formal_approved = False
    reasons = []
    if args.formal_approved_manifest:
        mp = Path(args.formal_approved_manifest)
        if not mp.is_file():
            reasons.append("formal-approved-manifest not a file")
        elif not args.expected_manifest_sha256:
            reasons.append("expected-manifest-sha256 not provided")
        elif _sha256(mp) != args.expected_manifest_sha256:
            reasons.append("manifest sha256 mismatch (frozen expected)")
        else:
            formal_approved = True
    else:
        reasons.append("no formal-approved-manifest (smoke/pilot draft)")
    draft = not formal_approved

    auto = {
        "schema": "research_v7_long_slot_report_v1",
        "created_at_utc": "2026-08-04T00:00:00Z",
        "draft": draft,
        "formal_approved": formal_approved,
        "draft_reasons": reasons,
        "status": "formal" if formal_approved else "smoke_draft",
        "key": {
            "timeline_duration_sec": d.get("timeline", {}).get("duration_sec"),
            "timeline_ge180": d.get("timeline", {}).get("ge180"),
            "slot_topology": d.get("slot", {}).get("topology"),
            "non_contiguous": d.get("slot", {}).get("non_contiguous"),
            "unit_recall": d.get("metrics", {}).get("unit_recall"),
            "correct_unit_fpr": d.get("metrics", {}).get("fpr"),
            "gap_recall": d.get("metrics", {}).get("gap_recall"),
            "assessor_op": d.get("assessor", {}).get("operating_points"),
        },
    }

    (run / "report").mkdir(parents=True, exist_ok=True)
    (run / "report" / "AUTO_SUMMARY.json").write_text(json.dumps(auto, ensure_ascii=False, indent=1))

    budget = {
        "schema": "runtime_budget_v1", "draft": True,
        "formal_target_h": 10, "formal_hard_cap_h": 12,
        "smoke": "run in CPU (no model)", "note": "pilot must measure elapsed/forward/cache before formal",
    }
    (run / "report" / "RUNTIME_BUDGET.json").write_text(json.dumps(budget, ensure_ascii=False, indent=1))

    md = f"""# AUTO_FINDINGS_{(not draft and 'SUMMARY' or 'DRAFT')}

- status: {'formal (approved)' if formal_approved else 'smoke/pilot draft'}
- Timeline: {auto['key']['timeline_duration_sec']}s (ge180={auto['key']['timeline_ge180']})
- Slot topology: {auto['key']['slot_topology']} (non-contiguous={auto['key']['non_contiguous']})
- unit_recall={auto['key']['unit_recall']}, correct_unit_fpr={auto['key']['correct_unit_fpr']}, gap_recall={auto['key']['gap_recall']}
- Assessor operating points: {auto['key']['assessor_op']}

> 自动。draft={draft}; reasons={reasons}。正式结论需 sha-matched frozen manifest；否则仅作 draft。
"""
    (run / "report" / "AUTO_FINDINGS_DRAFT.md").write_text(md)

    print(json.dumps({"ok": True, "draft": draft, "formal_approved": formal_approved,
                      "reasons": reasons, "out": str(run / "report"), "key": auto["key"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
