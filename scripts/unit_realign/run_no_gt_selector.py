"""WP7 — E5 no-GT candidate selection & safety (smoke/formal, pure CPU).

Reads already-cached forward evidence (no forward / GPU): builds no-GT feature
rows, audits which signals are actually exportable, freezes the simple selector
on the discovery split (never heldout), and evaluates the frozen selector ONCE
on the heldout split, reporting recovery-first and safety-first operating points
separately.  GT firewall is enforced on every feature row consumed.

Outputs (under ``--out-root``):
    01_signals/SIGNAL_AUDIT.json     signal availability audit
    02_selector/FROZEN_SELECTOR.json frozen rules (+ calibration stats on freeze split)
    03_heldout/HELDOUT_EVAL.json     single heldout evaluation, both operating points
    06_runtime/RUN_STATE.json        resume bookkeeping for the selector run
    FINAL_SELECTOR.json              the frozen selector shipped for downstream WP
"""
from __future__ import annotations

import argparse, json, os, time
from pathlib import Path

from lyricalign.unit_realign import no_gt_selector as ngs


def _iter_evidence(evidence_dir: str, limit: int | None = None):
    """Yield payload dicts from cached forward evidence (content-addressed JSON/JSONL)."""
    root = Path(evidence_dir)
    files = sorted([p for p in root.iterdir() if p.is_file()
                    and p.suffix in (".json", ".jsonl") and not p.name.startswith(".")])
    if limit is not None:
        files = files[:limit]
    for p in files:
        try:
            if p.suffix == ".jsonl":
                for line in p.open(encoding="utf-8", errors="replace"):
                    line = line.strip()
                    if line:
                        yield json.loads(line)
            else:
                yield json.loads(p.open(encoding="utf-8", errors="replace").read())
        except Exception as exc:  # pragma: no cover - defensive skip
            print(f"  [warn] skip {p.name}: {exc}")


def _load_features(path: str | None):
    if not path:
        return None
    p = Path(path)
    rows = []
    if p.suffix == ".jsonl":
        for line in p.open(encoding="utf-8"):
            line = line.strip()
            if line and line[0] in "{[":
                rows.append(json.loads(line))
    elif p.suffix == ".json":
        data = json.loads(p.open(encoding="utf-8").read())
        rows = data if isinstance(data, list) else (data.get("features") or data.get("rows") or [])
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--evidence-dir", help="cached forward evidence dir (content-addressed .json/.jsonl)")
    ap.add_argument("--features", default=None, help="optional existing no-GT feature matrix (unit_realign_no_gt_features_v1)")
    ap.add_argument("--out-root", required=True, help="output directory under /home/hyan/Data/lyricalign/runs/...")
    ap.add_argument("--split", default="validation", choices=["discovery", "validation", "validation_heldout", "heldout"],
                    help="which split to freeze vs evaluate; heldout is evaluated once only")
    ap.add_argument("--smoke", action="store_true", help="limit payload reading for a fast smoke")
    ap.add_argument("--max-payloads", type=int, default=60, help="payload cap (smoke or general)")
    args = ap.parse_args()

    out_root = Path(args.out_root)
    for d in ("01_signals", "02_selector", "03_heldout", "06_runtime"):
        (out_root / d).mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    # ---- read cached evidence (pure CPU) ----
    if args.evidence_dir and Path(args.evidence_dir).is_dir():
        cap = args.max_payloads if args.smoke else None
        payloads = list(_iter_evidence(args.evidence_dir, limit=cap))
    else:
        payloads = []
        print("[warn] no evidence-dir provided; audit/selection will run on features only (if any)")

    feat_rows = _load_features(args.features)

    # ---- 1. signal audit ----
    audit = ngs.audit_available_signals(payloads, feat_rows)
    audit.update({"smoke": args.smoke, "n_payloads_read": len(payloads)})
    (out_root / "01_signals" / "SIGNAL_AUDIT.json").write_text(
        json.dumps(audit, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[signals] usable={audit['usable_signals']}")
    print(f"[signals] missing={audit['missing_signals']}")

    # ---- 2. build feature rows (from evidence payloads) for selection ----
    # Prefer the FrozenScorer feature matrix when given (carries p_bad proxy);
    # otherwise derive rows from evidence payloads.
    if feat_rows:
        sel_features = feat_rows
    else:
        derived = []
        for payload in payloads:
            derived.extend(ngs.build_selector_features(payload))
        sel_features = derived

    # ---- freeze split vs heldout split ----
    freeze_split = args.split if args.split in ("discovery", "validation") else "validation"
    heldout_split = "heldout" if args.split in ("heldout", "validation_heldout") else "validation"

    # W-review P1-3: real (non-smoke) runs must evaluate heldout on a DISJOINT
    # region partition, never the same rows used for freezing.  Split feature rows
    # by region identity (region_id) into a discovery/freeze set and a heldout set,
    # then guard with disjoint_check (fail-fast if the freeze split leaks in).
    if not args.smoke:
        freeze_rows, heldout_rows = [], []
        for row in sel_features:
            target = freeze_rows if (len(freeze_rows) <= len(heldout_rows)) else heldout_rows
            target.append(row)
        # make the two partitions region-disjoint when possible
        region_buckets: dict[str, list[dict]] = {}
        for row in sel_features:
            region_buckets.setdefault(str(row.get("region_id") or "?"), []).append(row)
        keys = sorted(region_buckets)
        freeze_rows = [r for i, k in enumerate(keys) if i % 2 == 0 for r in region_buckets[k]]
        heldout_rows = [r for i, k in enumerate(keys) if i % 2 == 1 for r in region_buckets[k]]
        if not heldout_rows:
            # not enough regions -> cannot form a disjoint heldout; bail instead of
            # silently reusing the freeze set as heldout evidence.
            raise SystemExit("[error] not enough region partitions to form a disjoint "
                             "heldout; refusing to evaluate on the freeze split")
    else:
        freeze_rows, heldout_rows = list(sel_features), list(sel_features)

    frozen = ngs.freeze_simple_selector(freeze_rows, split=freeze_split)
    (out_root / "02_selector" / "FROZEN_SELECTOR.json").write_text(
        json.dumps(frozen, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[selector] frozen on split={freeze_split}, rules={frozen['rules']}")

    # ---- 3. heldout evaluation (once) ----
    heldout_features = heldout_rows
    if not args.smoke:
        if ngs.disjoint_check(frozen, heldout_features):
            raise SystemExit("[error] heldout split overlaps the freeze split; "
                             "cannot treat as valid heldout evidence")
    heldout_eval = ngs.evaluate_heldout_once(frozen, heldout_features)
    heldout_eval["_smoke_split_warning"] = (
        "smoke evaluated the frozen rules on the available cached set; real runs must "
        "split discovery/heldout by region identity BEFORE wiring into evaluate_heldout_once")
    heldout_eval["heldout_split_name"] = heldout_split
    (out_root / "03_heldout" / "HELDOUT_EVAL.json").write_text(
        json.dumps(heldout_eval, indent=2, ensure_ascii=False), encoding="utf-8")
    op = heldout_eval["operating_points"]
    print(f"[heldout] recovery_first: selected={op['recovery_first']['n_selected']} "
          f"safe_cov={op['recovery_first']['safe_coverage']} "
          f"reject={op['recovery_first']['reject_rate']}")
    print(f"[heldout] safety_first: selected={op['safety_first']['n_selected']} "
          f"safe_cov={op['safety_first']['safe_coverage']} "
          f"reject={op['safety_first']['reject_rate']} unsupported={op['safety_first']['n_unsupported']}")

    # ---- 4. final selector (shipped) ----
    final = dict(frozen)
    final.update({
        "ship_target": "WP8_adaptive_expansion_selection",
        "audit_summary": {s: audit["signals"].get(s, {}).get("n_available", 0) for s in audit["usable_signals"]},
        "proxy": ngs.NO_GT_PROXY,
        "proxy_available": audit["proxy_available"],
    })
    (out_root / "FINAL_SELECTOR.json").write_text(
        json.dumps(final, indent=2, ensure_ascii=False), encoding="utf-8")

    # ---- 6. runtime state ----
    run_state = {
        "schema": "unit_realign_no_gt_selector_run_state_v1",
        "phase": "wp7_e5_no_gt_selector",
        "completed": True,
        "smoke": args.smoke,
        "evidence_dir": str(args.evidence_dir) if args.evidence_dir else None,
        "features": args.features,
        "out_root": str(out_root),
        "split": args.split,
        "freeze_split": freeze_split, "heldout_split": heldout_split,
        "n_payloads_read": len(payloads),
        "payload_cap": args.max_payloads if args.smoke else None,
        "n_feature_rows": len(sel_features),
        "elapsed_sec": round(time.time() - t0, 3),
        "gt_firewall": {
            "assert_no_gt_feature_row": "enforced per feature row (unit_gate_features)",
            "assert_no_label_leak": "enforced on evidence payloads (no_gt_selector)",
            "gpu": False, "forward": 0,
        },
        "status": "done",
    }
    (out_root / "06_runtime" / "RUN_STATE.json").write_text(
        json.dumps(run_state, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[runtime] done in {run_state['elapsed_sec']}s -> {out_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
