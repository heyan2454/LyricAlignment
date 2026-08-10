#!/usr/bin/env python3
"""stage3b：Research V7 long-slot timing reaggregation on accepted real GT（CPU-only）。

把历史预测（GT_EVAL/row stream）按 request 重新聚合成 timing 指标，denom 只取
「被 query 且是 accepted 真实 GT」的 canonical units —— 绝不使用 synthetic-uniform
timeline 轴的 GT 数值作分母（evaluate_long_slot_gt.py 的 GT 轴仅为 synthetic uniform）。

输入：
  --cohort-manifest   COHORT_A_FORMAL.jsonl：每行含 song_id/split；只处理在列的 song。
  --long-manifest     LONG_TIMELINE_MANIFEST.jsonl：{song_id, canonical_units, segment_offsets}。
  --annotations       m4singer_character_annotations.jsonl（overlay，经 load_real_gt_with_audit）。
  --requests          REQUESTS.jsonl：{request_id, item_id, canonical_ids, text_units, ...}。
  --historical-predictions  旧 GT_EVAL/row stream（可选）：目录（扫描 *.json/*.jsonl）或单文件。
    支持三种格式：
      - GT_EVAL 风格 JSON：{"per_request": [{request_id, rows: [...]}], "rows": [...]}
      - per-request JSONL：每行 {request_id, rows: [...], prediction_sha?}
      - 行流 JSONL：每行 {request_id, canonical_unit_id? 或 global_character_index?,
        pred_start_sec/pred_end_sec（回退 official_fixed_global_* / fixed_global_* / raw_global_*）}
  --out              输出目录。
  --metric-tolerances 100,250,500,1000（ms，joint 双边界命中）。

身份等价判定：request_id 匹配且存在可解析行级 canonical 映射（行带 canonical_unit_id，
或 global_character_index 落在该 request 的 canonical_ids 内）即视为身份等价预测；
request 若带 prediction_sha 会原样记录（判定时仅作备注，不强制与当前侧比对）。

无 --historical-predictions 或 request 匹配不到身份等价预测 →
  RERUN_REQUESTS_GPU.jsonl（reason=missing_identity_equivalent_prediction）；
行存在但 canonical 映射缺失 → reason=missing_canonical_mapping。两者均不进 CPU reaggregate。

输出：
  REAGGREGATION_SUMMARY.json  macro 指标 + 四类计数 + 各 request 行数 + rerun 统计
  PER_REQUEST.jsonl          {request_id, song_id, counts, metrics, unit_errors}
  PER_SONG.jsonl             {song_id, counts, metrics, n_requests}
  RERUN_REQUESTS_GPU.jsonl   {request_id, song_id, reason}
  REAGGREGATION_FREEZE.json  输入 sha256 + git HEAD
  structural_appendix/       virtual-gap/ownership 类历史输出（独立命名，绝不进 timing）

四类计数（按 request / song / macro 分开报告）：
  canonical_units            请求 query 覆盖的 canonical units（song 级取各 request 并集）
  accepted_real_gt_units     accepted 真实 GT 且被 query（= denom）
  unlabeled_units            query 中存在于 timeline 但非 accepted GT 的单位
  context_only_not_queried   timeline 中存在但未被任何 request query 的单位（song/macro 级）
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lyricalign.research_transition_recovery_detector.real_gt import load_real_gt_with_audit

SCHEMA = "research_v7_reaggregation_long_slot_real_gt_v1"
DEFAULT_TOLERANCES_MS = (100, 250, 500, 1000)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_head() -> str | None:
    try:
        r = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                           text=True, check=True)
        return r.stdout.strip() or None
    except Exception:
        return None


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        out.append(json.loads(line))
    return out


def load_cohort(path: Path) -> dict[str, dict[str, Any]]:
    cohort: dict[str, dict[str, Any]] = {}
    for r in load_jsonl(path):
        song = r.get("song_id")
        if song is None:
            raise ValueError(f"cohort row missing song_id: {r}")
        cohort[song] = r
    return cohort


def load_timeline(path: Path) -> dict[str, dict[int, dict[str, Any]]]:
    out: dict[str, dict[int, dict[str, Any]]] = {}
    for r in load_jsonl(path):
        song = r.get("song_id")
        units = {int(u["canonical_unit_id"]): u for u in (r.get("canonical_units") or [])}
        out[song] = units
    return out


def load_requests(path: Path) -> list[dict[str, Any]]:
    return load_jsonl(path)


def _song_of(req: dict) -> str | None:
    item = req.get("item_id") or req.get("request_id") or ""
    return item.split(":")[0] or None


def _queried_ids(req: dict) -> list[int]:
    return [int(c) for c in (req.get("canonical_ids") or [])]


def _row_geometry(row: dict) -> tuple[float, float] | None:
    start = None
    for key in ("pred_start_sec", "official_fixed_global_start_sec",
                "fixed_global_start_sec", "raw_global_start_sec"):
        if key in row and row[key] is not None:
            start = float(row[key])
            break
    end = None
    for key in ("pred_end_sec", "official_fixed_global_end_sec",
                "fixed_global_end_sec", "raw_global_end_sec"):
        if key in row and row[key] is not None:
            end = float(row[key])
            break
    if start is None or end is None:
        return None
    return start, end


def _row_canonical_id(row: dict, req: dict) -> int | None:
    cid = row.get("canonical_unit_id")
    if cid is not None:
        try:
            return int(cid)
        except (TypeError, ValueError):
            pass
    gci = row.get("global_character_index")
    if gci is not None:
        cids = req.get("canonical_ids") or []
        gci = int(gci)
        if 0 <= gci < len(cids):
            return int(cids[gci])
    return None


def load_historical(path: str | Path | None) -> dict[str, dict[str, Any]]:
    """historical predictions -> {request_id: {prediction_sha, rows}}（按文件序稳定合并）。"""
    if path is None:
        return {}
    p = Path(path)
    files: list[Path] = []
    if p.is_dir():
        files = sorted(f for f in p.iterdir() if f.suffix in (".json", ".jsonl"))
    elif p.is_file():
        files = [p]
    by_rid: dict[str, dict[str, Any]] = {}
    for f in files:
        if f.suffix == ".jsonl":
            for line in load_jsonl(f):
                if "rows" in line and "request_id" in line:
                    rec = {
                        "prediction_sha": line.get("prediction_sha"),
                        "rows": list(line["rows"] or []),
                    }
                    by_rid.setdefault(line["request_id"], rec)
                elif "request_id" in line:
                    by_rid.setdefault(line["request_id"], {
                        "prediction_sha": None, "rows": [],
                    })["rows"].append(line)
        else:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            if isinstance(data, dict) and data.get("per_request"):
                for pr in data["per_request"]:
                    rid = pr.get("request_id")
                    if rid is None:
                        continue
                    by_rid.setdefault(rid, {
                        "prediction_sha": pr.get("prediction_sha"),
                        "rows": list(pr.get("rows") or []),
                    })
            if isinstance(data, dict) and data.get("rows"):
                for row in data["rows"]:
                    rid = row.get("request_id")
                    if rid is None:
                        continue
                    by_rid.setdefault(rid, {
                        "prediction_sha": None, "rows": [],
                    })["rows"].append(row)
    return by_rid


def _metrics_from_errors(errors: list[tuple[int, float, float]],
                         tolerances_ms: list[int]) -> dict[str, Any]:
    """errors: [(canonical_unit_id, abs_start_err_sec, abs_end_err_sec)]。

    无样本时所有数值指标为 None（不产生数值）。tolerance 命中 = 双边界绝对误差
    均 <= tol/1000 秒；命中率 = 命中数 / 样本数。
    """
    n = len(errors)
    if n == 0:
        return {
            "n_evaluated": 0,
            "start_mae_sec": None,
            "end_mae_sec": None,
            "tolerance_hit_rates_ms": {t: None for t in tolerances_ms},
        }
    errors = [(cid, round(se, 6), round(ee, 6)) for cid, se, ee in errors]
    start_errs = [e[1] for e in errors]
    end_errs = [e[2] for e in errors]
    start_mae = sum(start_errs) / n
    end_mae = sum(end_errs) / n
    rates = {}
    for t in tolerances_ms:
        tol = t / 1000.0
        hits = sum(1 for e in errors if e[1] <= tol and e[2] <= tol)
        rates[t] = round(hits / n, 6)
    return {
        "n_evaluated": n,
        "start_mae_sec": round(start_mae, 6),
        "end_mae_sec": round(end_mae, 6),
        "tolerance_hit_rates_ms": {t: rates[t] for t in tolerances_ms},
    }


def _request_reaggregate(req: dict, real_gt_song: dict[int, dict],
                         timeline_song: dict[int, dict],
                         hist: dict[str, dict[str, Any]] | None,
                         tolerances_ms: list[int],
                         ) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """单 request 的 CPU reaggregate；返回 (per_request_line 或 None, rerun 行或 None)。

    per_request_line：含 counts/metrics/unit_errors。
    rerun：{request_id, song_id, reason}（缺失身份等价预测或 canonical mapping）。
    """
    rid = req.get("request_id")
    song = _song_of(req)
    queried = _queried_ids(req)
    denom = sorted(cid for cid in queried if cid in real_gt_song)
    counts = {
        "canonical_units": len(queried),
        "accepted_real_gt_units": len(denom),
        "unlabeled_units": sum(1 for cid in queried if cid in timeline_song and cid not in real_gt_song),
        "context_only_not_queried": 0,
    }
    base = {"request_id": rid, "song_id": song, "counts": counts}

    if hist is None:
        return None, {"request_id": rid, "song_id": song,
                      "reason": "missing_identity_equivalent_prediction"}
    rec = hist.get(rid)
    if rec is None:
        return None, {"request_id": rid, "song_id": song,
                      "reason": "missing_identity_equivalent_prediction"}

    rows = list(rec.get("rows") or [])
    pred_by_cid: dict[int, tuple[float, float]] = {}
    n_mapped = 0
    for row in rows:
        cid = _row_canonical_id(row, req)
        geom = _row_geometry(row)
        if cid is not None:
            n_mapped += 1
            if geom is not None:
                pred_by_cid.setdefault(cid, geom)
    if rows and n_mapped == 0 and queried:
        return None, {"request_id": rid, "song_id": song,
                      "reason": "missing_canonical_mapping"}

    errors: list[tuple[int, float, float]] = []
    for cid in denom:
        geom = pred_by_cid.get(cid)
        if geom is None:
            continue
        gt = real_gt_song[cid]
        errors.append((cid, abs(gt["start_sec"] - geom[0]), abs(gt["end_sec"] - geom[1])))
    metrics = _metrics_from_errors(errors, tolerances_ms)
    base["metrics"] = metrics
    base["n_denom"] = len(denom)
    base["prediction_sha"] = rec.get("prediction_sha")
    base["n_pred_rows"] = len(rows)
    base["unit_errors"] = [
        {"canonical_unit_id": cid, "start_error_sec": round(se, 6),
         "end_error_sec": round(ee, 6)}
        for cid, se, ee in sorted(errors)
    ]
    return base, None


def _aggregate_errors(lines: list[dict[str, Any]]) -> list[tuple[int, float, float]]:
    out = []
    for line in lines:
        for u in line.get("unit_errors") or []:
            out.append((u["canonical_unit_id"], u["start_error_sec"], u["end_error_sec"]))
    return out


def _merge_counts(counts_list: list[dict[str, int]]) -> dict[str, int]:
    out = {"canonical_units": 0, "accepted_real_gt_units": 0,
           "unlabeled_units": 0, "context_only_not_queried": 0}
    for c in counts_list:
        for k in out:
            out[k] += c.get(k, 0)
    return out


def reaggregate(
    cohort_manifest: str | Path,
    long_manifest: str | Path,
    annotations: str | Path,
    requests: str | Path,
    historical_predictions: str | Path | None = None,
    out: str | Path = "out",
    metric_tolerances: list[int] | None = None,
    structural_appendix: str | Path | None = None,
) -> dict[str, Any]:
    tolerances_ms = sorted(set(metric_tolerances or DEFAULT_TOLERANCES_MS))
    cohort = load_cohort(Path(cohort_manifest))
    timeline = load_timeline(Path(long_manifest))
    reqs = load_requests(Path(requests))
    real_gt, audit = load_real_gt_with_audit(annotations, long_manifest)
    hist = load_historical(historical_predictions)

    out_dir = Path(out)
    out_dir.mkdir(parents=True, exist_ok=True)

    per_request: list[dict[str, Any]] = []
    per_song_lines: dict[str, list[dict[str, Any]]] = {}
    rerun_lines: list[dict[str, Any]] = []
    skipped_out_of_cohort = 0

    for req in sorted(reqs, key=lambda r: (r.get("request_id") or "")):
        song = _song_of(req)
        rid = req.get("request_id")
        if song is None or rid is None or song not in cohort:
            skipped_out_of_cohort += 1
            continue
        real_gt_song = real_gt.get(song) or {}
        timeline_song = timeline.get(song) or {}
        line, rerun = _request_reaggregate(req, real_gt_song, timeline_song, hist,
                                           tolerances_ms)
        if line is not None:
            per_request.append(line)
            per_song_lines.setdefault(song, []).append(line)
        else:
            rerun_lines.append(rerun)

    # ---- per-song：合并 counts 与 unit_errors；context_only 取 timeline 未 query 单位 ----
    per_song_out = []
    queried_by_song: dict[str, set[int]] = {}
    for req in reqs:
        song = _song_of(req)
        if song is None or song not in cohort:
            continue
        queried_by_song.setdefault(song, set()).update(_queried_ids(req))
    for song in sorted(per_song_lines):
        lines = per_song_lines[song]
        queried = queried_by_song.get(song, set())
        real_gt_song = real_gt.get(song) or {}
        timeline_song = timeline.get(song) or {}
        counts = {
            "canonical_units": len(queried),
            "accepted_real_gt_units": sum(1 for cid in queried if cid in real_gt_song),
            "unlabeled_units": sum(1 for cid in queried
                                   if cid in timeline_song and cid not in real_gt_song),
            "context_only_not_queried": sum(
                1 for cid in timeline_song if cid not in queried),
        }
        metrics = _metrics_from_errors(_aggregate_errors(lines), tolerances_ms)
        per_song_out.append({
            "song_id": song,
            "n_requests": len(lines),
            "counts": counts,
            "metrics": metrics,
        })

    per_request_out = [l for l in per_request if l["request_id"]]
    per_request_out.sort(key=lambda l: l["request_id"])
    per_song_out.sort(key=lambda l: l["song_id"])

    macro_counts = _merge_counts([l["counts"] for l in per_song_out])
    macro_metrics = _metrics_from_errors(_aggregate_errors(per_request_out), tolerances_ms)

    # ---- structural appendix：virtual-gap/ownership 类历史输出独立存放 ----
    appendix_dir = out_dir / "structural_appendix"
    appendix_dir.mkdir(parents=True, exist_ok=True)
    appendix_entries: list[str] = []
    if historical_predictions is not None:
        src = Path(historical_predictions)
        cand = [f for f in (src.iterdir() if src.is_dir() else [src])
                if f.is_file() and re.search(r"(gap|ownership|virtual)", f.name, re.I)]
        for f in sorted(cand):
            dst = appendix_dir / f.name
            shutil.copy2(f, dst)
            appendix_entries.append(f.name)
    if not appendix_entries:
        (appendix_dir / "STRUCTURAL_APPENDIX_PLACEHOLDER.json").write_text(
            json.dumps({
                "note": "no virtual-gap/ownership historical outputs provided; "
                        "nothing copied. Structural outputs are NOT merged into timing "
                        "metrics and carry no timing labels.",
                "entries": [],
            }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # ---- 输出 ----
    rerun_reasons = {}
    for r in rerun_lines:
        rerun_reasons[r["reason"]] = rerun_reasons.get(r["reason"], 0) + 1
    summary = {
        "schema": SCHEMA,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "inputs": {
            "cohort_manifest": str(cohort_manifest),
            "long_manifest": str(long_manifest),
            "annotations": str(annotations),
            "requests": str(requests),
            "historical_predictions": str(historical_predictions),
        },
        "cohort": {"n_songs": len(cohort), "song_ids": sorted(cohort)},
        "counts": macro_counts,
        "macro_metrics": macro_metrics,
        "n_requests_reaggregated": len(per_request_out),
        "n_requests_rerun_gpu": len(rerun_lines),
        "n_requests_skipped_out_of_cohort": skipped_out_of_cohort,
        "rerun_reasons": rerun_reasons,
        "metric_tolerances_ms": tolerances_ms,
        "gt_axis_note": "accepted real GT (load_real_gt_with_audit); "
                        "synthetic-uniform timeline NOT used as denominator",
        "structural_appendix": {
            "dir": str(appendix_dir),
            "entries": appendix_entries,
            "note": "virtual-gap/ownership outputs are stored in the structural appendix "
                    "only and never merged into timing aggregation or accepted as timing labels",
        },
        "per_request_counts": {l["request_id"]: l["counts"] for l in per_request_out},
    }

    freeze = {
        "schema": SCHEMA,
        "generated_at_utc": summary["generated_at_utc"],
        "deterministic": True,
        "git": {"head": _git_head()},
        "input_sha256": {
            "cohort_manifest": _sha256(Path(cohort_manifest)),
            "long_manifest": _sha256(Path(long_manifest)),
            "annotations": _sha256(Path(annotations)),
            "requests": _sha256(Path(requests)),
        },
    }
    if historical_predictions is not None:
        hp = Path(historical_predictions)
        freeze["input_sha256"]["historical_predictions"] = (
            _sha256(hp) if hp.is_file() else None)

    def _atomic_write(path: Path, payload: Any) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")

    _atomic_write(out_dir / "REAGGREGATION_SUMMARY.json", summary)
    with (out_dir / "PER_REQUEST.jsonl").open("w", encoding="utf-8") as f:
        for line in per_request_out:
            f.write(json.dumps(line, ensure_ascii=False, sort_keys=True) + "\n")
    with (out_dir / "PER_SONG.jsonl").open("w", encoding="utf-8") as f:
        for line in per_song_out:
            f.write(json.dumps(line, ensure_ascii=False, sort_keys=True) + "\n")
    with (out_dir / "RERUN_REQUESTS_GPU.jsonl").open("w", encoding="utf-8") as f:
        for line in sorted(rerun_lines, key=lambda l: l["request_id"]):
            f.write(json.dumps(line, ensure_ascii=False, sort_keys=True) + "\n")
    _atomic_write(out_dir / "REAGGREGATION_FREEZE.json", freeze)
    return summary


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cohort-manifest", required=True)
    p.add_argument("--long-manifest", required=True)
    p.add_argument("--annotations", required=True)
    p.add_argument("--requests", required=True)
    p.add_argument("--historical-predictions", default=None)
    p.add_argument("--out", required=True)
    p.add_argument("--metric-tolerances", default="100,250,500,1000",
                   help="comma-separated ms tolerances for joint hit rate")
    p.add_argument("--structural-appendix", default=None,
                   help="dir of virtual-gap/ownership historical outputs to copy "
                        "into out/structural_appendix (independent naming, never timing)")
    a = p.parse_args(argv)
    tols = [int(x) for x in a.metric_tolerances.split(",") if x.strip()]
    if not tols:
        raise ValueError("--metric-tolerances must be non-empty")
    summary = reaggregate(
        a.cohort_manifest, a.long_manifest, a.annotations, a.requests,
        historical_predictions=a.historical_predictions, out=a.out,
        metric_tolerances=tols,
        structural_appendix=a.structural_appendix,
    )
    print(json.dumps({
        "ok": True,
        "schema": summary["schema"],
        "counts": summary["counts"],
        "macro_metrics": summary["macro_metrics"],
        "n_requests_reaggregated": summary["n_requests_reaggregated"],
        "n_requests_rerun_gpu": summary["n_requests_rerun_gpu"],
        "rerun_reasons": summary["rerun_reasons"],
        "out": str(Path(a.out)),
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
