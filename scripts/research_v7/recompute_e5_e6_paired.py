#!/usr/bin/env python3
"""A2/A3：E5/E6 同子集 paired 重算。

在 gt_available（有 MAE）的 item 上，对每个 E5 variant（fixed/dynamic exact/−2/−4）与
E6 variant（baseline/hard/cap4/1.5/0.4）重算相对 baseline 的 paired delta，
输出 per-item delta、macro、improve/harm/no-change 与 source-song 分层计数。

输入：v8 formal root + manifest（item 元数据）。demo（无 GT、metrics=None）自动剔除。
输出：v7 目录下 recompute_e5_e6_paired.json + stdout 摘要。纯 CPU，不重新推理。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

MAE_KEY = "all_penalized_boundary_mae_sec"


def load_manifest_index(manifest_path: Path) -> dict[str, dict]:
    """从 active_manifest.jsonl 构建 item_id -> {dataset, source_song_id, gt_path}。"""
    index: dict[str, dict] = {}
    for line in manifest_path.read_text().splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        iid = d.get("item_id")
        if iid:
            index[iid] = {
                "dataset": d.get("dataset"),
                "source_song_id": d.get("source_song_id") or d.get("source_song"),
                "gt_path": d.get("gt_path"),
            }
    return index


def collect_item(file_phase: Path) -> dict | None:
    try:
        d = json.loads(file_phase.read_text())
    except Exception:
        return None
    variants = d.get("variants") or []
    rows = []
    for v in variants:
        if not isinstance(v, dict):
            continue
        m = v.get("metrics")
        if not isinstance(m, dict) or m.get(MAE_KEY) is None:
            continue
        rows.append({"name": v.get("name"), MAE_KEY: float(m[MAE_KEY]), "coverage": m.get("coverage")})
    if not rows:
        return None
    return {"applicable": d.get("applicable"), "rows": rows}


def paired_summary(rows: list[dict], baseline_name: str) -> list[dict]:
    """对单 item 的 variants，算各非 baseline 相对 baseline 的 delta。"""
    base = next((r for r in rows if r["name"] == baseline_name), rows[0])
    out = []
    base_mae = base[MAE_KEY]
    for r in rows:
        dmae = r[MAE_KEY] - base_mae
        out.append({
            "variant": r["name"],
            "mae": r[MAE_KEY],
            "delta_mae": dmae,
            "verdict": "no_change" if abs(dmae) < 1e-9 else ("improve" if dmae < 0 else "harm"),
        })
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--formal-root", required=True)
    p.add_argument("--manifest", default=None)
    p.add_argument("--out", required=True)
    p.add_argument("--limit", type=int, default=0)
    args = p.parse_args(argv)

    formal_items = Path(args.formal_root) / "formal" / "items"
    manifest_path = Path(args.manifest) if args.manifest else Path(args.formal_root) / "manifest" / "active_manifest.jsonl"
    index = load_manifest_index(manifest_path)

    items = sorted(d.name for d in formal_items.iterdir() if d.is_dir())
    if args.limit:
        import random

        random.seed(1)
        items = random.sample(items, args.limit)

    results: dict[str, dict] = {}  # {phase: {"paired": [...], "per_item": [...]}}
    for phase, cfg in (("E5", {"vars": ["E5_dynamic_windows.json"], "baseline": None}),
                       ("E6", {"vars": ["E6_silence.json"], "baseline": "S0_baseline"})):
        per_item = []
        for iid in items:
            meta = index.get(iid, {})
            if not meta.get("gt_path"):
                continue
            for vf in cfg["vars"]:
                fp = formal_items / iid / vf
                if not fp.exists():
                    continue
                ci = collect_item(fp)
                if not ci:
                    continue
                base = "dynamic_safe_minus0" if phase == "E5" else "S0_baseline"
                paired = paired_summary(ci["rows"], base)
                per_item.append({
                    "item_id": iid,
                    "dataset": meta.get("dataset"),
                    "source_song_id": meta.get("source_song_id"),
                    "paired": paired,
                })
        results[phase] = {"per_item": per_item}

    # 分层统计
    def summarize(phase_rows):
        all_verdicts = []
        deltas = []
        for it in phase_rows:
            for pr in it["paired"]:
                if pr["variant"] in ("dynamic_safe_minus0", "S0_baseline"):
                    continue
                deltas.append(pr["delta_mae"])
                all_verdicts.append(pr["verdict"])
        harm = sum(1 for v in all_verdicts if v == "harm")
        imp = sum(1 for v in all_verdicts if v == "improve")
        no_ch = sum(1 for v in all_verdicts if v == "no_change")
        return {
            "n_variant_pairs": len(deltas),
            "n_items": len({it["item_id"] for it in phase_rows}),
            "mean_delta": round(sum(deltas) / len(deltas), 4) if deltas else None,
            "improve": imp,
            "harm": harm,
            "no_change": no_ch,
        }

    out = {
        "schema": "v7/e5e6_paired_recompute_v1",
        "n_items_scanned": len(items),
        "E5": summarize(results["E5"]["per_item"]),
        "E6": summarize(results["E6"]["per_item"]),
        "per_item": results,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(json.dumps({
        "ok": True,
        "scanned": len(items),
        "E5": out["E5"],
        "E6": out["E6"],
        "out": args.out,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
