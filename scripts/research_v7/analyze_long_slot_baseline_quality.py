#!/usr/bin/env python3
"""Baseline 质量与 GT 轴敏感性分析（13 §6.2 核心指标，只读 GT_EVAL，无新 forward）。

输入 GT_EVAL.json（research_v7_gt_eval_v1，rows 已物化 row→canonical join），输出
BASELINE_QUALITY_ANALYSIS.json（schema research_v7_baseline_quality_analysis_v1）：
- 覆盖率分层：按 mutation（baseline/missing）× slot（full/sparse）× 窗位（:wN:）的
  row 覆盖率（n_rows / n_units_evaluated）；
- 边界误差分布：有 row 行 start/end 的 |pred−gt| 分布（median/p90/p99/max）与阈值表
  （0.25/0.5/1/2/5s 超过比例；unsafe 定义 = 任一边界误差 >250ms，13 §10.1）；
- GT 轴敏感性：M4 synthetic-uniform 轴 unsafe 率 与 MIR weak（qwen_fa）轴 unsafe 率并列
  （后者从 ASSESSOR_CROSS_DOMAIN_EVAL.json mir1k 读取，缺省用硬编码引用值 592/4592=12.9%）；
- seam 近/远分层（有 --timeline-manifest 时）：seam ±near_sec 内 vs 远处行的边界误差对比；
- 特征 AUC（bonus，有 --evidence-dir 时）：evidence official rows 按 request_id+global_character_index
  与 GT_EVAL rows join，unit_features 11 特征对 unsafe（>250ms）标签的单特征 AUC（rank 版 Mann-Whitney）。

只读：不修改 GT_EVAL / evidence / timeline，不启动模型。纯 CPU。
"""
from __future__ import annotations

import argparse
import glob
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from lyricalign.research_v7.features import unit_features  # noqa: E402

SCHEMA = "research_v7_baseline_quality_analysis_v1"
DEFAULT_THRESHOLDS = (0.25, 0.5, 1.0, 2.0, 5.0)
UNSAFE_THRESHOLD_SEC = 0.25
SEAM_NEAR_SEC = 2.0
ASSESSOR_FEATURE_KEYS = [
    "has_repair", "official_duration_sec", "official_missing_geometry",
    "raw_duration_sec", "raw_end_entropy", "raw_end_margin", "raw_inverted",
    "raw_start_entropy", "raw_start_margin", "raw_zero", "ro_official_minus_raw_sec",
]
GEOMETRIC_FEATURE_KEYS = ["pred_duration_sec", "either_max_boundary_error_sec"]
# 缺省引用（mir1k_real_run_v2/cross_assessor/ASSESSOR_CROSS_DOMAIN_EVAL.json mir1k 段）
MIR_WEAK_AXIS_REFERENCE = {
    "n_gt_unsafe_units": 592, "n_units_labeled": 4592,
    "source": "ASSESSOR_CROSS_DOMAIN_EVAL.json mir1k (mir1k_real_run_v2), hardcoded reference",
}

# round08：兼容旧 ":missing" 与多档 ":missing0.10/0.25/0.50" 后缀
REQUEST_ID_RE = re.compile(r"^(.+):w(\d+):(full|sparse)(?::missing(?:\d+(?:\.\d+)?)?)?$")


def parse_request_id(request_id: str) -> dict | None:
    """'song:w2:sparse:missing0.25' -> {song_id, window_index, slot_kind}。"""
    m = REQUEST_ID_RE.match(request_id)
    if not m:
        return None
    return {"song_id": m.group(1), "window_index": int(m.group(2)),
            "slot_kind": m.group(3)}


def _round(v: float | None, nd: int = 4) -> float | None:
    return round(v, nd) if v is not None else None


def quantile(sorted_values: Sequence[float], q: float) -> float:
    if not sorted_values:
        return float("nan")
    idx = min(len(sorted_values) - 1, int(q * len(sorted_values)))
    return float(sorted_values[idx])


def _dist_stats(values: Sequence[float]) -> dict:
    s = sorted(float(v) for v in values)
    return {
        "n": len(s),
        "median": _round(quantile(s, 0.5)),
        "p90": _round(quantile(s, 0.9)),
        "p99": _round(quantile(s, 0.99)),
        "max": _round(s[-1]) if s else None,
    }


def row_boundary_errors(row: Mapping) -> tuple[float | None, float | None] | None:
    """(start_err, end_err) 或 None（几何不全）。"""
    gt_s, gt_e = row.get("gt_start_sec"), row.get("gt_end_sec")
    pr_s, pr_e = row.get("pred_start_sec"), row.get("pred_end_sec")
    if None in (gt_s, gt_e, pr_s, pr_e):
        return None
    return (abs(float(pr_s) - float(gt_s)), abs(float(pr_e) - float(gt_e)))


# --------------------------------------------------------------------------
# 覆盖率分层
# --------------------------------------------------------------------------

def coverage_table(per_request: Sequence[Mapping]) -> dict:
    def summarize(rows: Sequence[Mapping]) -> dict:
        n_rows = sum(int(r.get("n_rows") or 0) for r in rows)
        n_units = sum(int(r.get("n_units_evaluated") or 0) for r in rows)
        return {"n_rows": n_rows, "n_units_evaluated": n_units,
                "row_coverage": _round(n_rows / n_units, 6) if n_units else None}

    by_mut: dict[str, list] = defaultdict(list)
    by_slot: dict[str, list] = defaultdict(list)
    by_win: dict[str, list] = defaultdict(list)
    by_mut_slot_win: dict[tuple, list] = defaultdict(list)
    unknown = []
    for pr in per_request:
        rid = parse_request_id(str(pr.get("request_id") or ""))
        mut = str(pr.get("mutation_type") or "unknown")
        if rid is None:
            unknown.append(pr)
            continue
        by_mut[mut].append(pr)
        by_slot[rid["slot_kind"]].append(pr)
        by_win[f"w{rid['window_index']}"].append(pr)
        by_mut_slot_win[(mut, rid["slot_kind"], f"w{rid['window_index']}")].append(pr)
    strata = {f"{m}|{slot}|{win}": summarize(v)
              for (m, slot, win), v in sorted(by_mut_slot_win.items())}
    return {
        "n_requests": len(per_request),
        "n_requests_unparsed_request_id": len(unknown),
        "overall": summarize(per_request),
        "by_mutation": {k: summarize(v) for k, v in sorted(by_mut.items())},
        "by_slot": {k: summarize(v) for k, v in sorted(by_slot.items())},
        "by_window": {k: summarize(v) for k, v in sorted(by_win.items())},
        "by_mutation_slot_window": strata,
        "note": "row_coverage = n_rows / n_units_evaluated（13 §6.2 评价口径分母）",
    }


# --------------------------------------------------------------------------
# 边界误差分布与阈值表
# --------------------------------------------------------------------------

def boundary_error_table(rows: Sequence[Mapping],
                         thresholds: Sequence[float] = DEFAULT_THRESHOLDS) -> dict:
    start_errs, end_errs, either_max = [], [], []
    n_geo = 0
    n_missing_geo = 0
    for row in rows:
        errs = row_boundary_errors(row)
        if errs is None:
            n_missing_geo += 1
            continue
        n_geo += 1
        se, ee = errs
        start_errs.append(se)
        end_errs.append(ee)
        either_max.append(max(se, ee))
    thresholds_table = {}
    for t in thresholds:
        thresholds_table[str(t)] = {
            "threshold_sec": t,
            "n_exceed": {
                "start": sum(x > t for x in start_errs),
                "end": sum(x > t for x in end_errs),
                "either": sum(x > t for x in either_max),
            },
            "exceed_rate": {
                "start": _round(sum(x > t for x in start_errs) / n_geo) if n_geo else None,
                "end": _round(sum(x > t for x in end_errs) / n_geo) if n_geo else None,
                "either": _round(sum(x > t for x in either_max) / n_geo) if n_geo else None,
            },
        }
    by_mutation: dict[str, dict] = {}
    by_mut_rows: dict[str, list] = defaultdict(list)
    for row in rows:
        by_mut_rows[str(row.get("mutation_type") or "unknown")].append(row)
    for mut, group in sorted(by_mut_rows.items()):
        em = [max(e) for e in (row_boundary_errors(r) for r in group) if e is not None]
        by_mutation[mut] = {
            "n_rows_with_geometry": len(em),
            "median_either_max_sec": _round(quantile(sorted(em), 0.5)) if em else None,
            "p90_either_max_sec": _round(quantile(sorted(em), 0.9)) if em else None,
            "unsafe_rate_gt_0_25":
                _round(sum(x > UNSAFE_THRESHOLD_SEC for x in em) / len(em)) if em else None,
        }
    return {
        "n_rows_with_geometry": n_geo,
        "n_rows_geometry_missing": n_missing_geo,
        "by_boundary": {
            "start_abs_error_sec": _dist_stats(start_errs),
            "end_abs_error_sec": _dist_stats(end_errs),
            "either_max_abs_error_sec": _dist_stats(either_max),
        },
        "thresholds": thresholds_table,
        "by_mutation": by_mutation,
        "unsafe_note": "unsafe 定义（13 §10.1）：任一边界误差 >250ms；"
                       f"UNSAFE_THRESHOLD_SEC={UNSAFE_THRESHOLD_SEC}",
    }


# --------------------------------------------------------------------------
# GT 轴敏感性（M4 synthetic-uniform vs MIR weak qwen_fa）
# --------------------------------------------------------------------------

def axis_sensitivity(boundary_error: dict, cross_domain_eval: dict | None,
                     mir_boundary: dict | None = None) -> dict:
    """GT 轴敏感性：M4 synthetic 轴与 MIR weak 轴的**同口径边界误差率**对比。

    round10（最终 review MAJOR-1）：早期版本用 ASSESSOR_CROSS_DOMAIN_EVAL 的 mutation 标签
    命中率当 MIR unsafe 率（12.9%），与 M4 的边界误差率（66.6%）非同量，5.17x 结论不成立。
    正确做法：MIR 侧也用【真实边界误差】（pred vs weak-label GT 轴，与 M4 同阈值口径），
    由调用方传入 mir_boundary（analyze 主流程对 MIR evidence 计算）。若未提供则退回
    cross_domain_eval 的标签命中率并明确标注"标签口径，非同量"。
    """
    m4_rate = None
    for t in (str(UNSAFE_THRESHOLD_SEC),):
        if t in boundary_error.get("thresholds", {}):
            m4_rate = boundary_error["thresholds"][t]["exceed_rate"]["either"]
    m4_entry = {"unsafe_rate_gt_0_25": m4_rate,
                "axis": "synthetic_uniform_timeline_axis (M4 GT_EVAL rows)"}
    if mir_boundary and mir_boundary.get("n_rows_with_geometry"):
        mir_entry = {
            "unsafe_rate_gt_0_25": mir_boundary["thresholds"][str(UNSAFE_THRESHOLD_SEC)]["exceed_rate"]["either"],
            "n_rows": mir_boundary["n_rows_with_geometry"],
            "median_error_sec": mir_boundary["by_boundary"]["start_abs_error_sec"]["median"],
            "axis": "weak_labeled_qwen_fa_timestamps (MIR evidence, same boundary-error metric)",
            "metric": "boundary_error_same_metric",
        }
    elif cross_domain_eval:
        mir = (cross_domain_eval.get("mir1k") or {})
        n_unsafe = mir.get("n_gt_unsafe_units")
        n_units = mir.get("n_units_labeled")
        mir_entry = {"n_gt_unsafe_units": n_unsafe, "n_units_labeled": n_units,
                     "unsafe_rate": _round(n_unsafe / n_units) if n_units else None,
                     "source": "ASSESSOR_CROSS_DOMAIN_EVAL.json mir1k (provided)",
                     "metric": "mutation_label_hit_rate (NOT same metric; non-comparable)"}
    else:
        mir_entry = {**MIR_WEAK_AXIS_REFERENCE,
                     "unsafe_rate": _round(MIR_WEAK_AXIS_REFERENCE["n_gt_unsafe_units"]
                                           / MIR_WEAK_AXIS_REFERENCE["n_units_labeled"]),
                     "metric": "mutation_label_hit_rate (NOT same metric; non-comparable)"}
    ratio = None
    if m4_entry["unsafe_rate_gt_0_25"] and mir_entry.get("unsafe_rate_gt_0_25"):
        ratio = _round(m4_entry["unsafe_rate_gt_0_25"] / mir_entry["unsafe_rate_gt_0_25"], 2)
    if ratio is not None and mir_entry.get("metric") == "boundary_error_same_metric":
        conclusion = (
            "GT 轴敏感性（同口径边界误差）：M4 synthetic-uniform 轴任一边界误差>250ms 占 "
            f"{m4_entry['unsafe_rate_gt_0_25']}，MIR weak-label 轴同阈值仅 "
            f"{mir_entry['unsafe_rate_gt_0_25']}（约 {ratio}x）。差异主要来自 GT 轴构造方式"
            "（synthetic 均匀分字 vs 真实弱标签时间戳），并非 decoder 对齐质量的跨域差异——"
            "MIR 弱轴下模型边界误差 median 仅 "
            f"{mir_entry.get('median_error_sec')}s。绝对 unsafe 率必须先声明 GT 轴来源。")
    elif mir_entry.get("unsafe_rate") is not None:
        # round10：MIR 侧只有 mutation 标签命中率（非可比口径）→ 明确说明不可归因
        m4r = m4_entry["unsafe_rate_gt_0_25"]
        mirr = mir_entry["unsafe_rate"]
        approx = f"（{_round(m4r / mirr, 2)}x 若按此口径粗比）" if m4r and mirr else ""
        conclusion = (
            "GT 轴敏感性（口径不一致，仅示意）：M4 synthetic 轴边界误差率 "
            f"{m4r} vs MIR mutation 标签命中率 {mirr}{approx}。两率非同量，"
            "不可直接归因为'GT 轴差异'；需同口径边界误差对比（--mir-gt-eval）。")
    else:
        conclusion = "GT 轴敏感性结论不可计算（缺任一侧同口径边界误差率）。"
    return {
        "m4_synthetic_axis": m4_entry,
        "mir_weak_axis": mir_entry,
        "ratio_m4_over_mir": ratio,
        "conclusion": conclusion,
    }


# --------------------------------------------------------------------------
# seam 近/远分层
# --------------------------------------------------------------------------

def _load_timeline_seams(timeline_manifest: Path | None) -> dict[str, list[float]] | None:
    if timeline_manifest is None:
        return None
    seams_by_song: dict[str, list[float]] = {}
    for line in timeline_manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        seams = [float(s["timeline_sec"]) for s in (d.get("seams") or [])]
        seams_by_song[str(d.get("song_id"))] = seams
    return seams_by_song


def seam_strata(rows: Sequence[Mapping],
                seams_by_song: dict[str, list[float]] | None,
                near_sec: float = SEAM_NEAR_SEC) -> dict:
    if not seams_by_song:
        return {"note": "timeline-manifest 未提供，跳过 seam 分层"}
    near, far = [], []
    n_no_seams = 0
    n_no_song = 0
    for row in rows:
        rid = parse_request_id(str(row.get("request_id") or ""))
        seams = seams_by_song.get(rid["song_id"]) if rid else None
        if seams is None:
            n_no_song += 1
            continue
        if not seams:
            n_no_seams += 1
            continue
        errs = row_boundary_errors(row)
        if errs is None:
            continue
        center = (float(row["gt_start_sec"]) + float(row["gt_end_sec"])) / 2.0
        dist = min(abs(center - s) for s in seams)
        entry = {"either_max_abs_error_sec": max(errs),
                 "seam_distance_sec": dist}
        (near if dist <= near_sec else far).append(entry)

    def summarize(entries: list[dict]) -> dict:
        em = sorted(e["either_max_abs_error_sec"] for e in entries)
        d = [e["seam_distance_sec"] for e in entries]
        return {
            "n_rows": len(entries),
            "median_either_max_sec": _round(quantile(em, 0.5)) if em else None,
            "p90_either_max_sec": _round(quantile(em, 0.9)) if em else None,
            "unsafe_rate_gt_0_25": _round(sum(x > UNSAFE_THRESHOLD_SEC for x in em) / len(em)) if em else None,
            "median_seam_distance_sec": _round(quantile(sorted(d), 0.5)) if d else None,
        }

    return {
        "near_sec": near_sec,
        "n_rows_near_seam": len(near),
        "n_rows_far_from_seam": len(far),
        "n_rows_song_missing_in_timeline": n_no_song,
        "n_rows_song_without_seams": n_no_seams,
        "near_seam": summarize(near),
        "far_from_seam": summarize(far),
        "note": f"near = gt 区间中心距最近 seam ≤ {near_sec}s",
    }


# --------------------------------------------------------------------------
# 特征 AUC（bonus：evidence official rows join + unit_features）
# --------------------------------------------------------------------------

def _load_evidence_index(evidence_dir: Path | None) -> dict[str, dict[int, dict]] | None:
    if evidence_dir is None:
        return None
    idx: dict[str, dict[int, dict]] = defaultdict(dict)
    for f in sorted(glob.glob(str(evidence_dir / "*.json"))):
        ev = json.loads(Path(f).read_text(encoding="utf-8"))
        attempt = ev.get("attempt") or {}
        request = attempt.get("request") or {}
        rid = request.get("request_id")
        if not rid:
            continue
        rows = ((attempt.get("decoder_outputs") or {}).get("official") or {}).get("rows") or []
        for r in rows:
            gci = int(r.get("global_character_index", -1))
            idx[rid][gci] = r
    return dict(idx)


def _auc_rank(values: Sequence[float], labels: Sequence[int]) -> float:
    """rank-based Mann-Whitney U -> AUC（numpy，无 sklearn）。"""
    x = np.asarray(values, dtype=float)
    y = np.asarray(labels, dtype=int)
    pos = x[y == 1]
    neg = x[y == 0]
    if len(pos) == 0 or len(neg) == 0:
        return float("nan")
    order = np.argsort(x, kind="mergesort")
    ranks = np.empty_like(x, dtype=float)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and x[order[j + 1]] == x[order[i]]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2.0 + 1
        i = j + 1
    pos_mask = np.zeros(len(x), dtype=bool)
    pos_mask[y == 1] = True
    rank_pos_sum = ranks[pos_mask].sum()
    u = rank_pos_sum - len(pos) * (len(pos) + 1) / 2.0
    return float(u / (len(pos) * len(neg)))


def feature_auc_table(rows: Sequence[Mapping],
                      evidence_index: dict | None) -> dict:
    if evidence_index is None:
        return {"note": "evidence-dir 未提供，跳过特征 AUC（bonus）"}
    feats: list[dict] = []
    labels: list[int] = []
    n_joined = 0
    n_unjoined = 0
    for row in rows:
        rid = str(row.get("request_id") or "")
        ev_row = (evidence_index.get(rid) or {}).get(int(row.get("global_character_index", -1)))
        errs = row_boundary_errors(row)
        if ev_row is None:
            n_unjoined += 1
            continue
        if errs is None:
            continue
        n_joined += 1
        se, ee = errs
        em = max(se, ee)
        f = unit_features(ev_row)
        f["pred_duration_sec"] = _round(float(row["pred_end_sec"]) - float(row["pred_start_sec"]), 6)
        f["either_max_boundary_error_sec"] = _round(em, 6)
        feats.append(f)
        labels.append(1 if em > UNSAFE_THRESHOLD_SEC else 0)
    n_pos = sum(labels)
    per_feature: dict[str, dict] = {}
    for key in ASSESSOR_FEATURE_KEYS + GEOMETRIC_FEATURE_KEYS:
        values = []
        valid = 0
        for f in feats:
            v = f.get(key)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                valid += 1
                values.append(float(v))
            else:
                values.append(float("nan"))
        if valid < 2 or n_pos == 0 or n_pos == len(labels):
            per_feature[key] = {"auc": None, "n_valid": valid,
                                "reason": "样本不足或标签单值"}
            continue
        auc = _auc_rank(values, labels)
        per_feature[key] = {"auc": _round(auc), "n_valid": valid}
    return {
        "n_rows_joined": n_joined,
        "n_rows_not_joined": n_unjoined,
        "n_unsafe": n_pos,
        "n_trusted": len(labels) - n_pos,
        "unsafe_rate_gt_0_25": _round(n_pos / len(labels)) if labels else None,
        "join_note": "join key = request_id + global_character_index（evidence official rows）",
        "auc_note": "unsafe 标签 = 任一边界误差>250ms；AUC=0.5 表示无判别力（rank Mann-Whitney）",
        "per_feature": per_feature,
    }


# --------------------------------------------------------------------------
# 汇总与自检
# --------------------------------------------------------------------------

def build_self_check(gt_eval: dict, coverage: dict, boundary_error: dict,
                     seam: dict | None) -> dict:
    metrics = gt_eval.get("metrics") or {}
    n_rows = coverage["overall"]["n_rows"]
    n_units = coverage["overall"]["n_units_evaluated"]
    checks = {
        "n_rows_total_matches_metrics": n_rows == metrics.get("n_decoder_rows"),
        "n_units_evaluated_matches_metrics": n_units == metrics.get("n_units_evaluated"),
        "n_rows_equal_gt_eval_rows": n_rows == len(gt_eval.get("rows") or []),
        "all_rows_have_geometry": boundary_error["n_rows_geometry_missing"] == 0,
        "coverage_denominator_consistent": n_units == metrics.get("n_units_evaluated"),
        "thresholds_include_unsafe": str(UNSAFE_THRESHOLD_SEC)
        in boundary_error.get("thresholds", {}),
    }
    if seam is not None and "near_seam" in seam:
        checks["seam_strata_counts_consistent"] = (
            seam["n_rows_near_seam"] + seam["n_rows_far_from_seam"]
            + seam["n_rows_song_missing_in_timeline"] + seam["n_rows_song_without_seams"]
            <= len(gt_eval.get("rows") or []))
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "counts": {"n_rows": n_rows, "n_units_evaluated": n_units},
    }


def analyze(gt_eval: dict, timeline_manifest: Path | None = None,
            evidence_dir: Path | None = None,
            cross_domain_eval: dict | None = None,
            cross_domain_eval_path: str | None = None,
            mir_gt_eval: dict | None = None,
            thresholds: Sequence[float] = DEFAULT_THRESHOLDS,
            seam_near_sec: float = SEAM_NEAR_SEC) -> dict:
    rows = gt_eval.get("rows") or []
    per_request = gt_eval.get("per_request") or []
    coverage = coverage_table(per_request)
    boundary_error = boundary_error_table(rows, thresholds)
    # round10：MIR 侧同口径边界误差（pred vs weak-label GT 轴），用于诚实对比
    mir_boundary = None
    if mir_gt_eval and (mir_gt_eval.get("rows") or []):
        mir_boundary = boundary_error_table(mir_gt_eval["rows"], thresholds)
    axis = axis_sensitivity(boundary_error, cross_domain_eval, mir_boundary)
    seams = _load_timeline_seams(timeline_manifest)
    seam = seam_strata(rows, seams, seam_near_sec) if seams is not None else None
    evidence_index = _load_evidence_index(evidence_dir)
    auc = feature_auc_table(rows, evidence_index) if evidence_index is not None else None
    self_check = build_self_check(gt_eval, coverage, boundary_error, seam)
    return {
        "schema": SCHEMA,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "inputs": {
            "gt_eval_path": str(gt_eval.get("run_root") or "") + "/GT_EVAL.json",
            "gt_eval_schema": gt_eval.get("schema"),
            "gt_axis_note": gt_eval.get("gt_axis_note"),
            "timeline_manifest": str(timeline_manifest) if timeline_manifest else None,
            "evidence_dir": str(evidence_dir) if evidence_dir else None,
            "cross_domain_eval": cross_domain_eval_path,
        },
        "coverage": coverage,
        "boundary_error": boundary_error,
        "mir_boundary_error": mir_boundary,
        "axis_sensitivity": axis,
        "seam_strata": seam,
        "feature_auc": auc,
        "self_check": self_check,
    }


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
    p.add_argument("--gt-eval", required=True, help="GT_EVAL.json（research_v7_gt_eval_v1），只读")
    p.add_argument("--timeline-manifest", default=None,
                   help="LONG_TIMELINE_MANIFEST.jsonl（可选，seam 近/远分层）")
    p.add_argument("--evidence-dir", default=None,
                   help="evidence 目录（可选，特征 AUC join）")
    p.add_argument("--cross-domain-eval", default=None,
                   help="ASSESSOR_CROSS_DOMAIN_EVAL.json（可选，MIR weak 轴 mutation 标签命中率；"
                        "缺省用硬编码引用值 12.9%）")
    p.add_argument("--mir-gt-eval", default=None,
                   help="MIR 域 GT_EVAL.json（可选，--domain mir1k 输出；用于同口径边界误差对比）")
    p.add_argument("--out", required=True, help="输出目录（写 BASELINE_QUALITY_ANALYSIS.json）")
    p.add_argument("--thresholds", default=",".join(str(t) for t in DEFAULT_THRESHOLDS),
                   help="误差阈值表（逗号分隔秒，默认 0.25,0.5,1,2,5）")
    p.add_argument("--seam-near-sec", type=float, default=SEAM_NEAR_SEC)
    a = p.parse_args(argv)
    gt_eval = json.loads(Path(a.gt_eval).read_text(encoding="utf-8"))
    thresholds = tuple(float(t) for t in a.thresholds.split(",") if t.strip())
    timeline = Path(a.timeline_manifest) if a.timeline_manifest else None
    evidence_dir = Path(a.evidence_dir) if a.evidence_dir else None
    cross = json.loads(Path(a.cross_domain_eval).read_text(encoding="utf-8")) \
        if a.cross_domain_eval else None
    mir_gt = json.loads(Path(a.mir_gt_eval).read_text(encoding="utf-8")) \
        if a.mir_gt_eval else None
    result = analyze(gt_eval, timeline, evidence_dir, cross,
                     cross_domain_eval_path=a.cross_domain_eval,
                     mir_gt_eval=mir_gt,
                     thresholds=thresholds, seam_near_sec=a.seam_near_sec)
    out = Path(a.out)
    out_path = out / "BASELINE_QUALITY_ANALYSIS.json"
    _atomic_write(out_path, result)
    m = result["boundary_error"]
    cov = result["coverage"]["overall"]["row_coverage"]
    ax = result["axis_sensitivity"]
    print(json.dumps({
        "ok": True,
        "schema": result["schema"],
        "row_coverage": cov,
        "median_start_abs_error_sec": m["by_boundary"]["start_abs_error_sec"]["median"],
        "unsafe_rate_gt_0_25": m["thresholds"][str(UNSAFE_THRESHOLD_SEC)]["exceed_rate"]["either"],
        "axis_ratio_m4_over_mir": ax["ratio_m4_over_mir"],
        "self_check_ok": result["self_check"]["ok"],
        "out": str(out_path),
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
