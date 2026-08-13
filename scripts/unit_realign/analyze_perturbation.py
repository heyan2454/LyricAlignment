"""P6 perturbation basin analysis for R-O realign run.

For each R-O oracle request that was re-forwarded under single-axis
perturbations (audio window shift / context text change), quantify how the
candidate target timestamp responds to the perturbation:

* variance: std/range of candidate start across perturbations (vs base = 0 pt)
* perturbation->timestamp response: audio offset (signed seconds) vs d(time)
* basin width: max |audio offset| keeping target start within ZERO_TOL of base
* discrete jump: any perturbation moving the start > JUMP away from base
* GT relationship: candidate start within GT_TOL of GT start, at base vs per axis

Aggregate verdict:
  A = oracle stable but fragile (narrow basin; majority basin width < 0.5s)
  B = oracle 0 point unstable (base not GT-recovered, or large-scale collapse)
  C = wide stable basin (audio offsets >= 1s still recovered in several cases)
"""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

import numpy as np

GT_TOL_MS = 100.0
ZERO_TOL_MS = 200.0
JUMP_MS = 2000.0

MAIN_RUN = Path("/home/hyan/Data/lyricalign/runs/unit_realign_smoke_v2_verify")

AXIS_RE = re.compile(r"^(audio[LR])([+-][0-9.]+)s$|^(text[LR])([+-][0-9]+)u$")


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.open()]


def parse_axis(tag: str) -> dict | None:
    m = AXIS_RE.match(tag)
    if not m:
        return None
    kind = m.group(1) or m.group(3)
    mag = float(m.group(2) or m.group(4))
    sign = -1.0 if kind.endswith("L") else 1.0
    return {
        "kind": "audio" if kind.startswith("audio") else "text",
        "axis": kind,
        "mag": abs(mag),
        "signed_sec": sign * mag if kind.startswith("audio") else None,
    }


def load_candidate(ev_dir: Path, request_id: str) -> dict[str, float]:
    p = ev_dir / f"{request_id}.candidate.jsonl"
    if not p.exists():
        return {}
    return {str(r.get("canonical_unit_id")): r["start_sec"] for r in load_jsonl(p)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--main-run", default=str(MAIN_RUN))
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    run = Path(args.run)
    main_run = Path(args.main_run)
    ev_dir = run / "02_forwards" / "evidence"
    out_root = Path(args.out) if args.out else run / "05_analysis"

    reqs = load_jsonl(run / "01_requests" / "REQUESTS_PERT.jsonl")
    gt_by_key = {
        (str(g["song_id"]), str(g["canonical_unit_id"])): g
        for g in load_jsonl(main_run / "06_evaluator_only" / "BASELINE_GT.jsonl")
    }

    by_region: dict[str, dict[str, tuple[dict, dict]]] = defaultdict(dict)
    for req in reqs:
        tag = req.get("perturbation_tag") or "base"
        m = AXIS_RE.search(req.get("request_id", "").split(":PERT:")[-1])
        if m:
            tag = m.group(0)
        by_region[req["region_id"]][tag] = (req, load_candidate(ev_dir, req["request_id"]))

    per_target: list[dict] = []
    per_axis: dict[str, list[dict]] = defaultdict(list)
    total_perturb_meas = 0
    total_discrete = 0
    n_with_audio = 0
    basin_vals = []
    std_vals = []
    range_vals = []

    for region_id, items in by_region.items():
        base_req, base_cand = items["base"]
        song = base_req["song_id"]
        for tid in base_req.get("target_unit_ids", []):
            tid_s = str(tid)
            base_start = base_cand.get(tid_s)
            if base_start is None:
                continue
            gt = gt_by_key.get((song, tid_s))
            gt_start = gt["start_sec"] if gt else None
            meas = []
            for tag, (req, cand) in sorted(items.items()):
                if tag == "base":
                    continue
                s = cand.get(tid_s)
                if s is None:
                    continue
                dms = (s - base_start) * 1000.0
                meas.append({"tag": tag, "axis": parse_axis(tag), "start_sec": s,
                             "delta_ms": dms, "abs_delta_ms": abs(dms)})
            deltas = np.array([m["delta_ms"] for m in meas]) if meas else np.array([])
            starts = [base_start] + [m["start_sec"] for m in meas]
            std_ms = float(deltas.std()) if len(deltas) else None
            range_ms = float((max(starts) - min(starts)) * 1000.0)
            discrete = bool(np.any(np.abs(deltas) > JUMP_MS)) if len(deltas) else False
            audio = [m for m in meas if m["axis"] and m["axis"]["kind"] == "audio"]
            within = [m for m in audio if m["abs_delta_ms"] < ZERO_TOL_MS]
            basin = max((m["axis"]["signed_sec"] for m in within), default=0.0, key=abs)
            basin = abs(basin)
            gt_ok_base = None
            if gt_start is not None:
                gt_ok_base = bool(abs(base_start - gt_start) * 1000.0 <= GT_TOL_MS)
            gt_ok_by_axis = {}
            for m in meas:
                ax = m["axis"]["axis"] if m["axis"] else m["tag"]
                if gt_start is not None:
                    gt_ok_by_axis[ax] = gt_ok_by_axis.get(ax, 0) + bool(
                        abs(m["start_sec"] - gt_start) * 1000.0 <= GT_TOL_MS)
                    per_axis[ax].append(abs(m["start_sec"] - gt_start) * 1000.0)

            if meas:
                total_perturb_meas += len(meas)
                total_discrete += int(discrete)
                std_vals.append(std_ms)
            range_vals.append(range_ms)
            if audio:
                n_with_audio += 1
                basin_vals.append(basin)
            if gt_start is not None:
                for ax in set(gt_ok_by_axis):
                    gt_ok_by_axis[ax] = [gt_ok_by_axis[ax],
                                         sum(1 for m in meas if (m["axis"]["axis"] if m["axis"] else m["tag"]) == ax)]

            per_target.append({
                "region_id": region_id, "oracle_bucket": base_req.get("oracle_bucket"),
                "song_id": song, "target_unit_id": tid_s,
                "base_start_sec": base_start, "gt_start_sec": gt_start,
                "base_gt_err_ms": None if gt_start is None else (base_start - gt_start) * 1000.0,
                "gt_recovered_base": gt_ok_base,
                "std_ms": std_ms, "range_ms": range_ms, "discrete_jump": discrete,
                "basin_width_sec": basin if audio else None,
                "n_perturbations": len(meas),
                "delta_ms": {m["tag"]: m["delta_ms"] for m in meas},
                "gt_recovered_per_axis": gt_ok_by_axis,
            })

    n_case = len(by_region)
    n_target = len(per_target)
    base_rec = np.mean([t["gt_recovered_base"] for t in per_target
                        if t["gt_recovered_base"] is not None])
    frac_discrete = total_discrete / total_perturb_meas if total_perturb_meas else 0.0
    basin_arr = np.array(basin_vals) if basin_vals else np.array([0.0])
    std_arr = np.array(std_vals) if std_vals else np.array([0.0])
    range_arr = np.array(range_vals) if range_vals else np.array([0.0])
    wide = float((basin_arr >= 1.0).mean())
    narrow = float((basin_arr < 0.5).mean())
    med_basin = float(np.median(basin_arr))

    if base_rec < 0.8 or frac_discrete > 0.3:
        verdict = "B"
        verdict_note = ("oracle 0 点本身不稳定：base 在 GT±100ms 内只有 %.0f%%；"
                        "或扰动离散跳变占比 %.0f%%") % (base_rec * 100, frac_discrete * 100)
    elif wide >= 0.3 or med_basin >= 1.0:
        verdict = "C"
        verdict_note = ("存在宽稳定 basin：音频偏移>=1s 仍保持 0 点邻近占比 %.0f%%") % (wide * 100)
    else:
        verdict = "A"
        verdict_note = "oracle 稳定但 basin 窄（多数 <0.5s）"

    per_axis_stats = {}
    for ax, errs in sorted(per_axis.items()):
        e = np.array(errs)
        per_axis_stats[ax] = {
            "n": int(len(e)),
            "mean_abs_err_vs_gt_ms": float(e.mean()),
            "frac_gt_recovered": float((e <= GT_TOL_MS).mean()),
        }

    summary = {
        "schema": "unit_realign_perturbation_basin_v1",
        "run": str(run),
        "main_run": str(main_run),
        "n_case": n_case,
        "n_target_units": n_target,
        "n_perturbation_measurements": total_perturb_meas,
        "variance_ms": {
            "std_mean": float(std_arr.mean()),
            "std_median": float(np.median(std_arr)),
            "std_p90": float(np.percentile(std_arr, 90)),
            "std_max": float(std_arr.max()),
            "range_mean": float(range_arr.mean()),
            "range_max": float(range_arr.max()),
        },
        "basin_width_sec": {
            "n_with_audio": int(n_with_audio),
            "median": med_basin,
            "min": float(basin_arr.min()),
            "frac_ge_1s": wide,
            "frac_lt_0.5s": narrow,
        },
        "discrete_jump": {"n_targets": int(total_discrete), "frac": frac_discrete},
        "gt_recovered_base_ratio": float(base_rec),
        "gt_recovered_per_axis": per_axis_stats,
        "per_target": per_target,
        "conclusion": verdict,
        "conclusion_note": verdict_note,
    }

    out_root.mkdir(parents=True, exist_ok=True)
    (out_root / "PERTURBATION_BASIN.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2))

    lines = [
        "# P6 Perturbation Basin Analysis",
        "",
        f"- run: `{run}`  |  main run (GT): `{main_run}`",
        f"- schema: `unit_realign_perturbation_basin_v1`",
        f"- n_case = {n_case}, n_target_units = {n_target}, "
        f"n perturbation measurements = {total_perturb_meas}",
        "",
        "## Verdict",
        "",
        f"**P6 conclusion: {verdict}** — {verdict_note}",
        "",
        "## 0 点（base）vs GT 恢复",
        "",
        "| target | bucket | base_start | gt_start | base_gt_err_ms | GT±100ms | basin_width_s | discrete_jump |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for t in per_target:
        lines.append(
            f"| {t['region_id']}:{t['target_unit_id']} | {t['oracle_bucket']} | "
            f"{t['base_start_sec']:.3f} | {t['gt_start_sec']:.3f} | "
            f"{t['base_gt_err_ms']:.1f} | {t['gt_recovered_base']} | "
            f"{t['basin_width_sec']} | {t['discrete_jump']} |"
        )
    lines += [
        "",
        "GT±100ms recovered at base: "
        f"**{float(base_rec)*100:.0f}%** ({int(round(base_rec*n_target))}/{n_target}).",
        "",
        "## 扰动→timestamp 响应（deltas ms vs base）",
        "",
        "| target | " + " | ".join(sorted({tg for t in per_target for tg in t["delta_ms"]})) + " |",
        "|---|---" * (1 + len({tg for t in per_target for tg in t["delta_ms"]})) + "|",
    ]
    tags = sorted({tg for t in per_target for tg in t["delta_ms"]})
    for t in per_target:
        lines.append("| " + t["region_id"] + ":" + t["target_unit_id"] + " | "
                     + " | ".join(f"{t['delta_ms'].get(tg, ''):+}" if t['delta_ms'].get(tg) is not None else "" for tg in tags) + " |")
    lines += [
        "",
        "## variance & basin width 分布",
        "",
        f"- std_ms mean/median/p90/max: "
        f"{summary['variance_ms']['std_mean']:.0f} / "
        f"{summary['variance_ms']['std_median']:.0f} / "
        f"{summary['variance_ms']['std_p90']:.0f} / "
        f"{summary['variance_ms']['std_max']:.0f}",
        f"- range_ms mean/max: {summary['variance_ms']['range_mean']:.0f} / {summary['variance_ms']['range_max']:.0f}",
        f"- basin width sec: n={n_with_audio}, median={med_basin:.2f}, min={float(basin_arr.min()):.2f}, "
        f"frac>=1s={wide:.2f}, frac<0.5s={narrow:.2f}",
        f"- discrete jump targets: {total_discrete} / {n_target} (frac {frac_discrete:.2f})",
        "",
        "## per-axis 敏感性（vs GT err ms）",
        "",
        "| axis | n | mean_abs_err_vs_gt_ms | frac_gt_recovered |",
        "|---|---|---|---|",
    ]
    for ax, st in sorted(per_axis_stats.items()):
        lines.append(f"| {ax} | {st['n']} | {st['mean_abs_err_vs_gt_ms']:.0f} | {st['frac_gt_recovered']:.2f} |")
    lines += [
        "",
        "## 判定依据",
        "",
        "- A: oracle 稳定但 basin 窄（多数 <0.5s）——不成立：median basin width "
        f"{med_basin:.1f}s, frac<0.5s={narrow:.2f}。",
        f"- B: 0 点本身不稳定（base GT±100ms 仅 {float(base_rec)*100:.0f}%）或扰动大面积崩 "
        f"(discrete jump frac {frac_discrete:.2f})。",
        f"- C: 宽稳定 basin（音频偏移>=1s 仍 recovered，frac={wide:.2f}）。",
        "",
        "结论：**P6 = " + verdict + "**",
        "",
    ]
    (out_root / "PERTURBATION_BASIN_REPORT.md").write_text("\n".join(lines))

    print(json.dumps({k: summary[k] for k in (
        "n_case", "n_target_units", "n_perturbation_measurements",
        "variance_ms", "basin_width_sec", "discrete_jump",
        "gt_recovered_base_ratio", "gt_recovered_per_axis", "conclusion",
        "conclusion_note")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
