#!/usr/bin/env python3
"""round01：GT 逐字符评价接线 —— formal 指标分子计算（GT_EVAL）。
round02：--domain mir1k 跨域复用（MIR 弱标签 timeline 作 GT 轴，按域分开汇报）。

输入：
  --run-root            formal_run_authoritative 目录（内含 evidence/，每份 json 的
                        attempt.decoder_outputs.official.rows[*] 带 request-local
                        global_character_index / character / official_fixed_global_*_sec）
  --timeline-manifest   --domain m4: LONG_TIMELINE_MANIFEST.jsonl；--domain mir1k:
                        MIR_TIMELINE_MANIFEST.jsonl。两者每行 schema 相同
                        {song_id, canonical_units: [{canonical_unit_id, text,
                        start_sec, end_sec}]}
输出（不修改 RUN_MANIFEST / evidence）：
  --out                 默认 <run-root>/GT_EVAL.json（schema: research_v7_gt_eval_v1）
                        或 <run-root>/MIR_CROSS_DOMAIN_EVAL.json
                        （schema: research_v7_mir1k_cross_domain_eval_v1）

GT 轴说明：
  LONG_TIMELINE_MANIFEST 是 timeline 均匀合成轴（synthetic uniform），不是人工逐字 GT；
  输出统一带 gt_axis_note="synthetic_uniform_timeline_axis (not human GT)"。
  MIR_TIMELINE_MANIFEST 是 qwen_fa 弱标注时间戳轴（validation_basis=null，非人工 GT）；
  输出带 gt_axis_note="weak_labeled_qwen_fa_timestamps (validation_basis=null, not human GT)"。

跨域口径（13 §10.3）：评价逻辑与 m4 完全同一套（evaluate_evidence/evaluate），
metrics 保持单域不合并分母；mir1k 输出顶层并列 domain="mir1k" 与可选的
m4_reference（--m4-gt-eval 指向真实 M4 GT_EVAL.json，只读 unit_recall/gap_recall/
n_units_evaluated 并列展示，不参与本域计算）。

评价口径（baseline/missing 配对，missing request_id = baseline request_id + ":missing"）：
  - row -> canonical unit：request.canonical_ids[global_character_index]；越界时若 canonical_ids
    是连续轴（canonical_text_start+i），用 canonical_text_start+global_character_index 解析
    （该位置文本缺失导致对齐偏移的行会落在被删 canonical 单位上），否则记为 None。
  - baseline：无真 unsafe；所有 row 都在请求文本内 -> unsafe_pred 应为空。
  - missing：真 unsafe = 被删尾部 canonical ids = baseline.canonical_ids[len(missing.canonical_ids):]；
    unsafe_pred = row 的 canonical id 不在请求文本覆盖 ids（set(canonical_ids[:len(text_units)])）的行。
    分子分母用共同评分子集：missing 只评其 text_units 覆盖的 canonical ids（retained GT）。
  - unit_metrics 的空集情形（truly_unsafe 与 unsafe_pred 均为空）按“完全正确”约定报 recall=1.0
    （region_metrics.unit_metrics 对 0/0 返回 0.0，本脚本在此处做调用方约定覆盖）。
  - gap（仅 missing）：GT gap = 被删尾部单位（omitted），pred gap = 请求文本末尾到窗尾之间无 row
    覆盖的区间；用 gap_metrics(gt_gaps, pred_gap_ids, gt_gap_omitted) 计算事件 recall 与
    omitted-unit 加权 recall；加权 pooled 时按 omitted units 跨请求求和。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from lyricalign.research_v7.region_metrics import gap_metrics, unit_metrics

SCHEMA = "research_v7_gt_eval_v1"
SCHEMA_MIR1K = "research_v7_mir1k_cross_domain_eval_v1"
GT_AXIS_NOTE = "synthetic_uniform_timeline_axis (not human GT)"
MIR1K_GT_AXIS_NOTE = "weak_labeled_qwen_fa_timestamps (validation_basis=null, not human GT)"
DOMAINS = ("m4", "mir1k")
M4_REFERENCE_KEYS = ("unit_recall", "gap_recall", "n_units_evaluated")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_timeline(manifest: Path) -> dict[str, dict[int, dict]]:
    """LONG_TIMELINE_MANIFEST.jsonl -> {song_id: {canonical_unit_id: unit}}。"""
    out: dict[str, dict[int, dict]] = {}
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        units = {}
        for u in row["canonical_units"]:
            units[int(u["canonical_unit_id"])] = u
        out[row["song_id"]] = units
    return out


def load_evidence(run_root: Path) -> list[dict]:
    ev_dir = run_root / "evidence"
    evs = []
    for p in sorted(ev_dir.glob("*.json")):
        evs.append(json.loads(p.read_text(encoding="utf-8")))
    return evs


def _song_id(request: dict) -> str | None:
    item_id = request.get("item_id") or ""
    return item_id.split(":")[0] or None


def _request_text_ids(request: dict) -> set[int]:
    """请求文本覆盖的 canonical ids（text_units 长度限定的 canonical_ids 前缀）。"""
    cids = [int(c) for c in (request.get("canonical_ids") or [])]
    text_units = request.get("text_units") or []
    if text_units:
        cids = cids[: len(text_units)]
    return set(cids)


def _row_canonical_id(request: dict, gci: int) -> int | None:
    """row 的 canonical unit id：canonical_ids[gci]；越界时对连续轴解析到被删位置。"""
    cids = [int(c) for c in (request.get("canonical_ids") or [])]
    if 0 <= gci < len(cids):
        return cids[gci]
    start = request.get("canonical_text_start")
    if (
        start is not None
        and cids
        and all(cids[i] == start + i for i in range(len(cids)))
    ):
        # 连续轴：越界 gci 对应“文本缺失导致对齐偏移”的 canonical 位置（落在被删区）
        return start + gci
    return None


def _row_geometry(row: dict) -> tuple[float, float] | None:
    for key in ("official_fixed_global_start_sec", "fixed_global_start_sec",
                "raw_global_start_sec"):
        if key in row and row[key] is not None:
            start = float(row[key])
            break
    else:
        return None
    for key in ("official_fixed_global_end_sec", "fixed_global_end_sec",
                "raw_global_end_sec"):
        if key in row and row[key] is not None:
            end = float(row[key])
            break
    else:
        return None
    return start, end


def _deleted_ids(baseline_req: dict, missing_req: dict) -> list[int]:
    b = [int(c) for c in (baseline_req.get("canonical_ids") or [])]
    m = [int(c) for c in (missing_req.get("canonical_ids") or [])]
    return b[len(m):]


def _is_missing_rid(request_id: str) -> str | None:
    """识别 missing 请求的 id 并返回其 baseline id；非 missing 返回 None。

    round08 review CRITICAL：支持两种后缀——旧单档 ":missing" 与多档 ":missing0.10/0.25/0.50"
    （round08 builder 引入）。只匹配精确 ":missing" 会让多档/新默认档配对静默失效。
    """
    if request_id is None:
        return None
    if request_id.endswith(":missing"):
        return request_id[: -len(":missing")]
    # ":missing<ratio>"（ratio 为 0<r<1 的浮点字面量）
    import re as _re
    m = _re.search(r":missing\d+(?:\.\d+)?$", request_id)
    if m:
        return request_id[: m.start()]
    return None


def _gap_omitted_ids(units: dict[int, dict], deleted: list[int],
                     window_sec: list[float]) -> list[int]:
    ws, we = window_sec
    out = []
    for cid in deleted:
        u = units.get(cid)
        if u is None:
            continue
        if u["end_sec"] > ws and u["start_sec"] < we:  # 与窗有交集
            out.append(cid)
    return out


def evaluate_evidence(
    evidence: dict,
    baseline_req: dict | None,
    timeline: dict[int, dict],
) -> dict | None:
    """单份 evidence 的 GT 逐字符评价；无法评价（缺 rows/几何/GT 轴）时返回 None。"""
    attempt = evidence.get("attempt") or {}
    if attempt.get("status") != "ok":
        return None
    request = attempt.get("request") or {}
    rows = ((attempt.get("decoder_outputs") or {}).get("official") or {}).get("rows") or []
    if not rows:
        return None
    song = _song_id(request)
    units = timeline.get(song) if song else None
    if units is None:
        return None
    mutation = request.get("mutation_type") or "baseline"
    window_sec = [float(v) for v in (request.get("source_window_sec") or [0.0, 0.0])]
    text_ids = _request_text_ids(request)
    n_retained = len(text_ids)

    # row -> canonical id + GT 时间轴 join
    row_records = []
    unsafe_pred = []
    for r in rows:
        gci = int(r.get("global_character_index", -1))
        cid = _row_canonical_id(request, gci)
        gt = units.get(cid) if cid is not None else None
        geom = _row_geometry(r)
        if cid is None or cid not in text_ids:
            unsafe_pred.append(cid)
        row_records.append({
            "global_character_index": gci,
            "canonical_unit_id": cid,
            "character": r.get("character"),
            "gt_start_sec": gt["start_sec"] if gt else None,
            "gt_end_sec": gt["end_sec"] if gt else None,
            "pred_start_sec": geom[0] if geom else None,
            "pred_end_sec": geom[1] if geom else None,
        })

    result = {
        "request_id": request.get("request_id"),
        "mutation_type": mutation,
        "song_id": song,
        "window_sec": window_sec,
        "n_rows": len(rows),
        # 共同评分子集：本 evidence 参与评价的 text 覆盖 canonical ids（与 RUN_MANIFEST
        # metrics.n_units 同口径，见 13 计划「只评共同 queried units」）
        "n_units_evaluated": n_retained,
        "rows": row_records,
    }

    # ---- unit 评价 ----
    if mutation == "missing":
        # MAJOR（round1 review）：missing 必须有配对 baseline 才能定义真 unsafe
        # （被删 canonical ids）；缺失时不得按"无真 unsafe"评价（会把 recall 真空膨成 1.0）。
        if baseline_req is None:
            return None
        deleted = _deleted_ids(baseline_req, request)
        truly_unsafe = set(deleted)
    else:
        deleted, truly_unsafe = [], set()
    um = unit_metrics(
        total_gt_units=len(truly_unsafe),
        unsafe_pred_units=[c for c in unsafe_pred if c is not None],
        truly_unsafe_indices=truly_unsafe,
        correct_retained_units=n_retained,
        total_retained_gt=n_retained,
    )
    if not truly_unsafe and not unsafe_pred:
        # 空集情形：无真 unsafe 且未误报 -> 完全正确（recall=1，fpr=0）
        um["unit_recall"] = 1.0
    result["unit"] = {
        "truly_unsafe_canonical_ids": sorted(truly_unsafe),
        "deleted_canonical_ids": sorted(deleted),
        "unsafe_pred_canonical_ids": sorted(c for c in unsafe_pred if c is not None),
        "n_unsafe_pred_rows": len(unsafe_pred),
        "unit_recall": um["unit_recall"],
        "correct_unit_fpr": um["correct_unit_fpr"],
        "n_hit": um["n_hit"], "n_fp": um["n_fp"], "n_fn": um["n_fn"],
        "n_retained_units": n_retained,
    }

    # ---- gap 评价（仅 missing）----
    gap = {
        "gt_gap_ids": [], "pred_gap_ids": [], "omitted_canonical_ids": [],
        "gap_event_recall": None, "gap_weighted_recall": None,
        "gap_size_sec": None, "last_row_end_sec": None,
    }
    if mutation == "missing":
        ends = [r["pred_end_sec"] for r in row_records if r["pred_end_sec"] is not None]
        last_end = max(ends) if ends else None
        omitted = _gap_omitted_ids(units, deleted, window_sec)
        gt_gaps = [0] if omitted else []
        gap_size = (window_sec[1] - last_end) if last_end is not None else None
        pred_gaps = [0] if (gap_size is not None and gap_size > 1e-3) else []
        gm = gap_metrics(gt_gaps=gt_gaps, pred_gap_ids=pred_gaps,
                         gt_gap_omitted={0: omitted})
        gap = {
            "gt_gap_ids": gt_gaps,
            "pred_gap_ids": pred_gaps,
            "omitted_canonical_ids": omitted,
            "gap_event_recall": gm["gap_event_recall"],
            "gap_weighted_recall": gm["gap_omitted_unit_weighted_recall"],
            "gap_fp": gm["gap_fp"], "gap_fn": gm["gap_fn"],
            "gap_size_sec": round(gap_size, 4) if gap_size is not None else None,
            "last_row_end_sec": round(last_end, 4) if last_end is not None else None,
        }
    result["gap"] = gap
    return result


def _load_m4_reference(m4_gt_eval: Path | None) -> dict | None:
    """从 M4 GT_EVAL.json 读取并列展示的 m4_reference（只读，不参与本域计算）。

    文件缺失/不存在时返回 None；metrics 键缺失时对应值为 None（不做兜底数值）。
    """
    if m4_gt_eval is None or not m4_gt_eval.is_file():
        return None
    try:
        data = json.loads(m4_gt_eval.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"warning: m4-gt-eval unreadable, m4_reference=None: {e}", file=sys.stderr)
        return None
    m = data.get("metrics") or {}
    return {k: m.get(k) for k in M4_REFERENCE_KEYS}


def evaluate(run_root: Path, timeline_manifest: Path, domain: str = "m4",
             m4_gt_eval: Path | None = None) -> dict:
    if domain not in DOMAINS:
        raise ValueError(f"domain must be one of {DOMAINS}, got {domain!r}")
    timeline = load_timeline(timeline_manifest)
    evs = load_evidence(run_root)

    by_request_id = {}
    for ev in evs:
        req = (ev.get("attempt") or {}).get("request") or {}
        rid = req.get("request_id")
        if rid:
            by_request_id[rid] = ev
    baseline_reqs = {}
    for rid, ev in by_request_id.items():
        req = (ev.get("attempt") or {}).get("request") or {}
        # round08 review CRITICAL：missing id 有两种后缀（旧 ":missing" 与多档 ":missing0.10"），
        # 统一用 rsplit 识别，不能只匹配 ":missing" 精确后缀。
        if req.get("mutation_type") != "missing" and _is_missing_rid(rid) is None:
            baseline_reqs[rid] = req

    per_request = []
    n_ok = n_skipped = 0
    sum_text_units = 0
    sparse_checked = []  # (per_request 条目, 请求) 配对，供 sparse 子集自检
    for rid, ev in sorted(by_request_id.items(), key=lambda kv: kv[0]):
        req = (ev.get("attempt") or {}).get("request") or {}
        base_of = _is_missing_rid(rid)
        if req.get("mutation_type") == "missing" or base_of is not None:
            baseline = baseline_reqs.get(base_of)
        else:
            baseline = None
        r = evaluate_evidence(ev, baseline, timeline)
        if r is None:
            n_skipped += 1
            continue
        n_ok += 1
        per_request.append(r)
        sum_text_units += len(req.get("text_units") or [])
        if req.get("phase") == "sparse":
            sparse_checked.append((r, req))

    # ---- pooled 汇总 ----
    n_units_evaluated = sum(r["n_units_evaluated"] for r in per_request)
    n_decoder_rows = sum(r["n_rows"] for r in per_request)
    n_retained = sum(r["unit"]["n_retained_units"] for r in per_request)
    n_truly = sum(len(r["unit"]["truly_unsafe_canonical_ids"]) for r in per_request)
    n_pred = sum(r["unit"]["n_unsafe_pred_rows"] for r in per_request)
    n_hit = sum(r["unit"]["n_hit"] for r in per_request)
    n_fp = sum(r["unit"]["n_fp"] for r in per_request)
    n_fn = sum(r["unit"]["n_fn"] for r in per_request)
    n_baseline = sum(1 for r in per_request if r["mutation_type"] == "baseline")
    n_missing = sum(1 for r in per_request if r["mutation_type"] == "missing")
    if n_truly or n_pred:
        unit_recall = round(n_hit / n_truly, 4) if n_truly else 0.0
    elif n_ok == 0:
        unit_recall = None  # 无任何可评价 evidence → 不给出虚假的 vacuous 1.0
    else:
        unit_recall = 1.0  # 空集约定：无真 unsafe 且未误报 -> 完全正确
    fpr = round(n_fp / n_retained, 4) if n_retained else 0.0

    gap_rows = [r for r in per_request if r["mutation_type"] == "missing"]
    n_gt_gaps = sum(len(r["gap"]["gt_gap_ids"]) for r in gap_rows)
    n_gap_hits = sum(len(set(r["gap"]["pred_gap_ids"]) & set(r["gap"]["gt_gap_ids"]))
                     for r in gap_rows)
    gap_fp = sum(r["gap"].get("gap_fp", 0) for r in gap_rows)
    gap_fn = sum(r["gap"].get("gap_fn", 0) for r in gap_rows)
    gt_omitted = sum(len(r["gap"]["omitted_canonical_ids"]) for r in gap_rows)
    hit_omitted = 0
    for r in gap_rows:
        if set(r["gap"]["pred_gap_ids"]) & set(r["gap"]["gt_gap_ids"]):
            hit_omitted += len(r["gap"]["omitted_canonical_ids"])

    # ---- self-check（只读诊断，不改任何指标语义）----
    # 1) n_units_evaluated 应等于所有已评价请求 text_units 数之和；
    # 2) phase=="sparse" 请求的 n_units_evaluated 应等于共同评分子集长度
    #    （text 覆盖 canonical ids 的子集，即 _request_text_ids 口径）；
    # 3) counts_consistent：n_units_evaluated == n_retained_units。
    sparse_subset_ok = all(
        rr["n_units_evaluated"] == len(_request_text_ids(rq))
        for rr, rq in sparse_checked
    )
    self_check = {
        "units_match_text_units": n_units_evaluated == sum_text_units,
        "n_units_from_text_units": sum_text_units,
        "sparse_subset_ok": sparse_subset_ok,
        "n_sparse_requests": len(sparse_checked),
        "counts_consistent": n_units_evaluated == n_retained,
    }

    result = {
        "schema": SCHEMA_MIR1K if domain == "mir1k" else SCHEMA,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "run_root": str(run_root),
        "timeline_manifest": str(timeline_manifest),
        "timeline_sha256": _sha256(timeline_manifest),
        "gt_axis_note": MIR1K_GT_AXIS_NOTE if domain == "mir1k" else GT_AXIS_NOTE,
        "metrics": {
            "unit_recall": unit_recall,
            "correct_unit_fpr": fpr,
            "gap_recall": round(n_gap_hits / n_gt_gaps, 4) if n_gt_gaps else 0.0,
            "gap_event_recall": round(n_gap_hits / n_gt_gaps, 4) if n_gt_gaps else 0.0,
            "gap_weighted_recall": round(hit_omitted / gt_omitted, 4) if gt_omitted else 0.0,
            "n_units_evaluated": n_units_evaluated,
            "n_decoder_rows": n_decoder_rows,
            "n_retained_units": n_retained,
            "n_truly_unsafe_gt_units": n_truly,
            "n_unsafe_pred_units": n_pred,
            "n_hit": n_hit, "n_fp": n_fp, "n_fn": n_fn,
            "n_gt_gaps": n_gt_gaps, "n_gap_hits": n_gap_hits,
            "gap_fp": gap_fp, "gap_fn": gap_fn,
            "n_baseline": n_baseline,
            "n_missing": n_missing,
            "n_evidence_ok": n_ok,
            "n_evidence_skipped": n_skipped,
            "self_check": self_check,
        },
        "per_request": [
            {k: v for k, v in r.items() if k != "rows"} for r in per_request
        ],
        "rows": [
            {**row, "request_id": r["request_id"], "mutation_type": r["mutation_type"]}
            for r in per_request for row in r["rows"]
        ],
    }
    if domain == "mir1k":
        # 跨域并列字段：domain 标识 GT 轴来源；m4_reference 只读 M4 GT_EVAL 并列展示，
        # 不合并分母、不参与本域 metrics 计算（13 §10.3）。
        result["domain"] = "mir1k"
        result["m4_reference"] = _load_m4_reference(m4_gt_eval)
    return result


def _atomic_write(path: Path, payload: dict) -> None:
    import os
    import tempfile
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run-root", required=True,
                   help="formal run 目录（含 evidence/），只读")
    p.add_argument("--timeline-manifest", required=True,
                   help="GT 轴 timeline manifest：--domain m4 用 LONG_TIMELINE_MANIFEST.jsonl，"
                        "--domain mir1k 用 MIR_TIMELINE_MANIFEST.jsonl（两者 schema 相同）")
    p.add_argument("--domain", choices=DOMAINS, default="m4",
                   help="GT 轴域：m4=synthetic uniform timeline（默认），"
                        "mir1k=weak_labeled_qwen_fa_timestamps 跨域评价")
    p.add_argument("--m4-gt-eval", default=None,
                   help="M4 GT_EVAL.json 路径（仅 --domain mir1k 有意义）："
                        "只读 unit_recall/gap_recall/n_units_evaluated 并列展示")
    p.add_argument("--out", default=None,
                   help="输出路径（默认 <run-root>/GT_EVAL.json 或 "
                        "<run-root>/MIR_CROSS_DOMAIN_EVAL.json）")
    a = p.parse_args(argv)
    if a.domain == "m4" and a.m4_gt_eval:
        print("warning: --m4-gt-eval ignored for domain=m4", file=sys.stderr)
    run_root = Path(a.run_root)
    default_name = "MIR_CROSS_DOMAIN_EVAL.json" if a.domain == "mir1k" else "GT_EVAL.json"
    out = Path(a.out) if a.out else (run_root / default_name)
    m4_gt_eval = Path(a.m4_gt_eval) if a.m4_gt_eval else None
    result = evaluate(run_root, Path(a.timeline_manifest),
                      domain=a.domain, m4_gt_eval=m4_gt_eval)
    _atomic_write(out, result)
    m = result["metrics"]
    print(json.dumps({
        "ok": True,
        "schema": result["schema"],
        "domain": result.get("domain", "m4"),
        "gt_axis_note": result["gt_axis_note"],
        "m4_reference": result.get("m4_reference"),
        "unit_recall": m["unit_recall"],
        "correct_unit_fpr": m["correct_unit_fpr"],
        "gap_recall": m["gap_recall"],
        "gap_weighted_recall": m["gap_weighted_recall"],
        "n_units_evaluated": m["n_units_evaluated"],
        "n_baseline": m["n_baseline"],
        "n_missing": m["n_missing"],
        "out": str(out),
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
