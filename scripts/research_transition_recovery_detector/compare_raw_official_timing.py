#!/usr/bin/env python3
"""11 计划实验 B：raw vs official timing 同数据对照（同 request/unit/split）。"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

from lyricalign.research_transition_recovery_detector import gt_provenance  # noqa: E402

TOLERANCES_MS = (100, 250, 500, 1000)
SERIAL_PATTERN = __import__("re").compile(
    r"^(?P<song>.+)__(?P<transition>T[123]_direct_serial|T[123]_core_boundary_serial|T[123]_stable_boundary_serial)\.jsonl$")


def _rate(errs: list[float | None], ms: int) -> float:
    n = len(errs)
    return round(sum(1 for e in errs if e is not None and e <= ms / 1000.0) / max(n, 1), 4)


def _stats(errs: list[float | None]) -> dict:
    valid = [e for e in errs if e is not None]
    return {
        "n": len(valid), "mae": round(sum(valid) / max(len(valid), 1), 4),
        "median": round(statistics.median(valid), 4) if valid else None,
        "zero_duration": sum(1 for e in valid if e == 0.0),
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--session-root", required=True)
    p.add_argument("--timeline-manifest", required=True)
    p.add_argument("--role", default="model_selection")
    p.add_argument("--out", required=True)
    args = p.parse_args()
    corrected = Path("/home/hyan/Data/lyricalign/runs/research_transition_recovery_detector_20260808_corrected")
    manifest = {json.loads(l)["song_id"]: json.loads(l)
                for l in Path(args.timeline_manifest).read_text(encoding="utf-8").splitlines() if l.strip()}
    split = json.loads((corrected / "00_meta" / "DATASET_SPLIT.json").read_text(encoding="utf-8"))
    role_songs = split["roles"][args.role]

    per_song: dict[str, dict] = {}
    pooled_raw: list[float | None] = []
    pooled_off: list[float | None] = []
    for pth in sorted((corrected / "02_transition").glob("*.jsonl")):
        m = SERIAL_PATTERN.match(pth.name)
        if not m or m.group("song") not in role_songs:
            continue
        song = m.group("song")
        gt = {int(u["canonical_unit_id"]): u for u in manifest[song]["canonical_units"]}
        errs_raw: list[float | None] = []
        errs_off: list[float | None] = []
        for line in pth.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            before = int(rec["state_before"]["committed_end_exclusive"])
            after = int(rec["decision"]["committed_end_exclusive"])
            for r in rec["evidence_summary"]["raw_global_rows"]:
                cid = int(r["global_character_index"])
                if not (before <= cid < after):
                    continue
                g = gt.get(cid)
                pred_raw = r.get("fixed_global_start_sec")
                pred_off = r.get("official_fixed_global_start_sec")
                errs_raw.append(abs(float(pred_raw) - float(g["start_sec"])) if pred_raw is not None and g else None)
                errs_off.append(abs(float(pred_off) - float(g["start_sec"])) if pred_off is not None and g else None)
        pooled_raw.extend(errs_raw)
        pooled_off.extend(errs_off)
        per_song[song] = {
            "n": len(errs_raw),
            "raw": {"r100": _rate(errs_raw, 100), "r250": _rate(errs_raw, 250),
                    "r500": _rate(errs_raw, 500), "r1000": _rate(errs_raw, 1000), **_stats(errs_raw)},
            "official": {"r100": _rate(errs_off, 100), "r250": _rate(errs_off, 250),
                         "r500": _rate(errs_off, 500), "r1000": _rate(errs_off, 1000), **_stats(errs_off)},
        }
    # pooled + paired delta（同 unit 位置配对）
    paired = [abs(r - o) for r, o in zip(pooled_raw, pooled_off, strict=True)
              if r is not None and o is not None]
    out = {
        "schema_version": "raw_official_timing_comparison_v1",
        "scope": "development_selection", "target": "serial committed units (T1/T2/T3)",
        "pooled": {
            "n": len(pooled_raw),
            "raw": {"r100": _rate(pooled_raw, 100), "r250": _rate(pooled_raw, 250),
                    "r500": _rate(pooled_raw, 500), "r1000": _rate(pooled_raw, 1000), **_stats(pooled_raw)},
            "official": {"r100": _rate(pooled_off, 100), "r250": _rate(pooled_off, 250),
                         "r500": _rate(pooled_off, 500), "r1000": _rate(pooled_off, 1000), **_stats(pooled_off)},
            "paired_abs_delta": {
                "n": len(paired), "mean": round(sum(paired) / max(len(paired), 1), 4),
                "median": round(statistics.median(paired), 4) if paired else None,
                "pct_units_disagree_gt100ms": round(
                    sum(1 for d in paired if d > 0.1) / max(len(paired), 1), 4),
            },
        },
        "per_song": per_song,
        "provenance": gt_provenance.synthetic_uniform_timeline_provenance(),
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    gt_provenance.warn_synthetic_gt()
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(json.dumps({"pooled_raw_r250": out["pooled"]["raw"]["r250"],
                      "pooled_off_r250": out["pooled"]["official"]["r250"],
                      "pooled_raw_r500": out["pooled"]["raw"]["r500"],
                      "pooled_off_r500": out["pooled"]["official"]["r500"],
                      "paired_mean_abs_delta": out["pooled"]["paired_abs_delta"]["mean"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
