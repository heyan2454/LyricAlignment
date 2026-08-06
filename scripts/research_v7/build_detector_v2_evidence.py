#!/usr/bin/env python3
"""Detector V2 evidence converter CLI（Dev-F）：真实 runner evidence → EvidenceRow v2。

读 <run-root>/evidence/<identity>.json（run_behavior_suite --real 旧 schema 产物）+
<run-root>/manifests/ANOMALY_MANIFEST.jsonl（REQUESTS 行，提供 canonical_to_local/view_id/
hidden_schema）+ <run-root>/manifests/MULTIVIEW_MANIFEST.jsonl（跨视图组），
按 request_id 配对；输出 <run-root>/evidence_v2/<identity>.jsonl（每请求一行 JSON 数组的
EvidenceRow dict）+ FEATURE_SCHEMA.json（schema 引用，供 feature extractor 消费）。

防泄漏：每 row 输出前递归 assert_no_label_leak；任何 GT/mutation/family 字段进入 row →
该请求整体失败并记入 evidence_v2/failures.jsonl，批次继续。纯 CPU。

--keep-posterior（backlog #4 接线）：透传 converter 的 keep_posterior，在 cross_view 落盘
posterior_vectors（体积大，默认关闭）。group_posteriors（跨视图全量后验距离）需真实
forward 采集完整 posterior 后由调用方提供，本 CLI 尚未接线（启用步骤见 22 文档登记）。

用法：
  PYTHONPATH=src python scripts/research_v7/build_detector_v2_evidence.py --run-root <run>
  PYTHONPATH=src python scripts/research_v7/build_detector_v2_evidence.py \
      --run-root <run> --out <dir>        # 自定义输出目录
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from lyricalign.research_v7.detector_v2_evidence_converter import (  # noqa: E402
    SCHEMA_VERSION,
    convert_evidence,
)

MANIFEST_NAME = "ANOMALY_MANIFEST.jsonl"
MULTIVIEW_NAME = "MULTIVIEW_MANIFEST.jsonl"


def _load_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run-root", required=True, help="run 根（含 evidence/ 与 manifests/）")
    p.add_argument("--out", default=None, help="输出目录（默认 <run-root>/evidence_v2）")
    p.add_argument("--keep-posterior", action="store_true",
                   help="cross_view 落盘 posterior_vectors（backlog #4，默认关闭）")
    a = p.parse_args(argv)

    run = Path(a.run_root)
    if not run.is_dir():
        p.error(f"run-root not found: {run}")
    out = Path(a.out) if a.out else run / "evidence_v2"
    out.mkdir(parents=True, exist_ok=True)

    evidence_dir = run / "evidence"
    manifests = run / "manifests"
    req_rows = _load_jsonl(manifests / MANIFEST_NAME)
    mv_groups = _load_jsonl(manifests / MULTIVIEW_NAME)
    if not req_rows:
        print(f"warning: no rows in {manifests / MANIFEST_NAME}")
    req_by_id = {}
    for r in req_rows:
        rid = r.get("request_id")
        if rid:
            req_by_id.setdefault(rid, r)

    files = sorted(evidence_dir.glob("*.json")) if evidence_dir.is_dir() else []
    converted = 0
    failed = 0
    n_rows = 0
    failures: list[dict] = []
    for f in files:
        req_id = None
        try:
            evidence = json.loads(f.read_text(encoding="utf-8"))
            attempt = evidence.get("attempt") or {}
            status = attempt.get("status")
            if status not in (None, "ok"):
                raise ValueError(f"attempt status={status!r}, not ok")
            req_id = ((attempt.get("request") or {}).get("request_id")
                      or (evidence.get("metadata") or {}).get("request_id"))
            request_row = req_by_id.get(req_id) if req_id else None
            if request_row is None:
                raise ValueError(f"no ANOMALY_MANIFEST row for request_id={req_id!r}")
            rows = convert_evidence(evidence, request_row, multiview_groups=mv_groups,
                                    keep_posterior=a.keep_posterior)
            line = json.dumps([r.to_dict() for r in rows], ensure_ascii=False)
            _atomic_write_text(out / f"{f.stem}.jsonl", line + "\n")
            converted += 1
            n_rows += len(rows)
        except Exception as e:  # noqa
            failed += 1
            failures.append({"evidence_file": str(f), "request_id": req_id,
                             "status": "convert_error", "error": str(e), "kind": type(e).__name__})
    failures_f = out / "failures.jsonl"
    if failures:
        _atomic_write_text(failures_f, "\n".join(
            json.dumps(x, ensure_ascii=False, sort_keys=True) for x in failures) + "\n")
    elif failures_f.exists():
        failures_f.unlink()

    schema = {
        "schema_version": SCHEMA_VERSION,
        "row_schema": "detector_v2_evidence.EvidenceRow.to_dict (20 §3; raw/official/hidden/cross_view)",
        "leak_guard": "assert_no_label_leak recursive (converter enforces; any leak -> request failed)",
        "source": {"evidence_dir": str(evidence_dir), "requests_manifest": str(manifests / MANIFEST_NAME),
                   "multiview_manifest": str(manifests / MULTIVIEW_NAME)},
        "output": str(out),
        "counts": {"evidence_files": len(files), "converted": converted,
                   "failed": failed, "rows": n_rows},
    }
    _atomic_write_text(out / "FEATURE_SCHEMA.json",
                       json.dumps(schema, ensure_ascii=False, indent=1) + "\n")
    print(json.dumps({"ok": True, "out": str(out), "evidence_files": len(files),
                      "converted": converted, "failed": failed, "rows": n_rows,
                      "failures": failures_f.name if failures else None}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
