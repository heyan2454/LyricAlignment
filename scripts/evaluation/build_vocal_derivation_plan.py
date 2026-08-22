#!/usr/bin/env python3
"""Build a CPU-only vocal derivation plan for raw-mixture datasets.

This does NOT run separation. It lists the raw inputs that need vocal-only
derivation and the intended derived output paths, so a later GPU/CPU separation
batch can be executed with full provenance.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

RAW_MIX_DATASETS = {"mir_mlpop_cmn", "mir_mlpop_yue", "jamendolyrics_en"}


def load_rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--datasets-root", type=Path, required=True)
    parser.add_argument("--out-root", type=Path, required=True)
    parser.add_argument("--separator", default="htdemucs", help="Separator identity/config name")
    args = parser.parse_args()

    rows = load_rows(args.manifest)
    plan = []
    for row in rows:
        ds = row.get("dataset_id")
        if ds not in RAW_MIX_DATASETS:
            continue
        audio_rel = row.get("audio_relpath")
        if not audio_rel:
            continue
        dataset_dir_name = {
            "mir_mlpop_cmn": "mir_mlpop",
            "mir_mlpop_yue": "mir_mlpop",
            "jamendolyrics_en": "jamendolyrics_en",
        }[ds]
        input_abs = args.datasets_root / dataset_dir_name / audio_rel
        stem = Path(audio_rel).stem
        output_rel = Path("evaluation_v1_20260816") / ds / f"{stem}_vocals.wav"
        plan.append({
            "dataset_id": ds,
            "item_id": row.get("item_id"),
            "tier": row.get("tier"),
            "input_relpath": str(Path(dataset_dir_name) / audio_rel),
            "input_abs": str(input_abs),
            "input_exists": input_abs.exists(),
            "output_relpath": str(output_rel),
            "separator": args.separator,
            "status": "planned",
            "notes": [
                "Record separator config, input SHA-256, output SHA-256, and command before operational use.",
                "Do not overwrite raw mixture files.",
            ],
        })
    out_root = args.out_root
    out_root.mkdir(parents=True, exist_ok=True)
    plan_path = out_root / "vocal_derivation_plan.json"
    atomic_json(plan_path, {"schema_version": "vocal_derivation_plan_v1", "separator": args.separator, "items": plan})
    cleanup = [
        "# Cleanup Report — Vocal Derivation Plan",
        "",
        "This batch writes one small JSON plan only; no separation is run.",
        "",
        f"File: `{plan_path.relative_to(out_root)}` ({plan_path.stat().st_size} bytes)",
        "",
        "Recreate with:",
        "",
        f"```bash\npython scripts/evaluation/build_vocal_derivation_plan.py --manifest {args.manifest} --datasets-root {args.datasets_root} --out-root {out_root}\n```",
        "",
        f"Delete with:\n\n```bash\nrm -rf {out_root}\n```",
        "",
    ]
    (out_root / "cleanup_report.md").write_text("\n".join(cleanup), encoding="utf-8")
    print(json.dumps({"planned_items": len(plan), "out": str(plan_path)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
