#!/usr/bin/env python3
"""A4：条件指标分母审计。

对 v8 formal 全部 item_summary.phases 的 E5–E9 条件指标字段，输出每个 field 在
全量 item 上的分母审计：
  total_count / applicable_count / attempted_count / completed_count / non_null_count /
  success_count / failure_count / numerator / denominator / rate

这使“跳过 None 的均值”等口径暴露其非空分母与样本数，避免条件指标被误解为全覆盖。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

# phase -> 需要审计的条件指标字段（映射到 item_summary.phases[key]）
AUDIT_FIELDS: dict[str, list[str]] = {
    "E5": ["applicable", "variant_count"],
    "E6": ["applicable", "silence_count", "variant_count"],
    "E7": ["applicable", "record_count"],
    "E8": [
        "case_count",
        "candidate_propagation_failure_count",
        "candidate_propagation_complete_count",
        "selected_improvement_count",
        "selected_clean_harm_count",
        "oracle_match_count",
    ],
    "E9": [
        "applicable",
        "beam_window_count",
        "multi_hypothesis_window_count",
        "fallback_window_count",
        "selected_delta_mae_sec",
        "selected_matches_final_beam_oracle",
    ],
}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--formal-root", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--limit", type=int, default=0)
    args = p.parse_args(argv)

    items_dir = Path(args.formal_root) / "formal" / "items"
    item_ids = sorted(d.name for d in items_dir.iterdir() if d.is_dir())
    if args.limit:
        import random

        random.seed(2)
        item_ids = random.sample(item_ids, args.limit)

    total = len(item_ids)
    # field_audit[phase][field] = {non_null, total_nonzero, sum, count_applicable_true, ...
    audit: dict[str, dict[str, dict]] = {}

    def bump(phase, field, key):
        audit.setdefault(phase, {}).setdefault(field, {}).setdefault(key, 0)
        audit[phase][field][key] += 1

    for iid in item_ids:
        sp = items_dir / iid / "item_summary.json"
        if not sp.exists():
            continue
        try:
            summ = json.loads(sp.read_text())
        except Exception:
            continue
        phases = summ.get("phases", {})
        for phase, fields in AUDIT_FIELDS.items():
            pv = phases.get(phase, {})
            if not isinstance(pv, dict):
                continue
            for f in fields:
                if f not in pv:
                    continue
                val = pv[f]
                audit.setdefault(phase, {}).setdefault(f, {"total": total})
                auditsum = audit[phase][f]
                if val is not None:
                    auditsum["non_null"] = auditsum.get("non_null", 0) + 1
                # applicable=True
                if f == "applicable":
                    if val is True:
                        auditsum["applicable_true"] = auditsum.get("applicable_true", 0) + 1
                    if val is False:
                        auditsum["applicable_false"] = auditsum.get("applicable_false", 0) + 1
                # 数值型字段：>0 / =0 / 样本数
                if isinstance(val, (int, float)):
                    auditsum["numeric_present"] = auditsum.get("numeric_present", 0) + 1
                    if val > 0:
                        auditsum["numeric_gt0"] = auditsum.get("numeric_gt0", 0) + 1
                    auditsum["sum"] = auditsum.get("sum", 0) + float(val)

    # 汇总成标准分母结构
    out: dict[str, dict] = {"schema": "v7/conditional_denominator_audit_v1", "total_items": total, "phases": {}}
    for phase in sorted(audit):
        out["phases"][phase] = {"fields": {}}
        for field, st in sorted(audit[phase].items()):
            nn = st.get("non_null", 0)
            num = st.get("numeric_present", 0)
            applicable = st.get("applicable_true")
            numerator = st.get("numeric_gt0")
            # Boolean applicability rates use all items; numeric/non-null
            # condition rates use the values actually observed.
            denominator = total if field == "applicable" else nn
            rate = ((applicable if field == "applicable" else numerator) / denominator
                    if denominator and (applicable if field == "applicable" else numerator) is not None else None)
            out["phases"][phase]["fields"][field] = {
                "total_count": total,
                "applicable_count": applicable,
                # Historical compact summaries do not expose all lifecycle fields;
                # retain the required schema and mark unavailable values explicitly.
                "attempted_count": None,
                "completed_count": None,
                "non_null_count": nn,
                "success_count": None,
                "failure_count": None,
                "numeric_count": num,
                "numerator": applicable if field == "applicable" else numerator,
                "denominator": denominator,
                "rate": round(rate, 4) if rate is not None else None,
                "rate_non_null": round(rate, 4) if rate is not None else None,
                "sum": round(st.get("sum", 0.0), 4) if st.get("sum") else None,
            }

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=1))
    # 简洁 stdout
    has_issue = []
    for phase in out["phases"]:
        for field, st in out["phases"][phase]["fields"].items():
            if st["non_null_count"] < max(1, int(total * 0.3)):
                has_issue.append(f"{phase}.{field} non_null={st['non_null_count']}/{total}")
    print(json.dumps({"ok": True, "total_items": total, "audited_fields": out["phases"], "sparse_fields": has_issue}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
