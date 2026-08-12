#!/usr/bin/env python
"""audit_wp4_light_merge_before_after.py - WP4 read-only reporter (Codex).

Consumes existing artifacts only (never trains / loads GPU models / re-runs the
window-gate logistic fit / rebuilds manifests / runs recovery):

  --before / --after   detector eval JSON (M4_SONG_HELDOUT / FAMILY_LOO) or a
                       directory containing both files. Same cohort, only the
                       postprocess (light-merge fix) version is expected to differ.
  --frozen             FROZEN_OPERATING_POINTS.json (raw/official ->
                       standardized_logistic -> operating_points.T_accept/T_reject).
  --labels             LABELS.jsonl (per-unit rows: request_identity/target/label/
                       family/split/song_id) used for per-song unit boundary table.
  --window-report      high-level window_gate_report.json (BAD_HIT100=0.7, 90
                       requests, fit B-train -> score A-test). p_bad aggregates are
                       carried from this existing report (fit is NOT re-run).
  --rerun-90           rerun_90.jsonl rows (request_id/condition/request_type/
                       source_split) for song-failure concentration.
  --scores-dir         rerun_gpu/evidence/*.json (one file per row; n_rows per
                       request_id counted by streaming each file separately).
  --scores-jsonl       rerun_gpu/reagg/PER_REQUEST.jsonl (request_id ->
                       metrics.tolerance_hit_rates_ms["100"] / start_mae_sec /
                       n_evaluated / song_id), read line by line.

Gate contract (fail closed): before/after must share cohort identity (schema,
model_kind, combo, n_train, n_test), score+model identity, threshold values
(T_accept/T_reject equal between before/after AND vs frozen operating points),
and label+metric schema (tri_unit_metrics / interval_metrics / by_family key
sets). Only the postprocess version may differ
-> result_status = retrospective_after_light_merge_fix.
Any difference -> fail_closed error record instead of results.

Writes 8 provenance-headed artifacts under the results dir.
"""
from __future__ import annotations

import argparse
import csv
import glob
import hashlib
import json
import os
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

BAD_HIT100 = 0.7
THRESH_GRID = [round(float(x), 2) for x in (i / 100.0 for i in range(10, 51, 5))]
CANDIDATES = ("mean_pb", "p90_pb", "frac_gt_Taccept")

STATUS_FIX = "retrospective_after_light_merge_fix"
STATUS_FAIL = "fail_closed"
STATUS_MISSING = "not_reproduced_source_missing"
STATUS_OK = "ok"

REPO_HEAD_FILE = Path(__file__).resolve()
RESULTS_DEFAULT = Path("/home/hyan/LyricAlignment_20260812_quick_correction/results")


# --------------------------------------------------------------------------
# small utilities
# --------------------------------------------------------------------------
def sha256_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def git_head() -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(Path.cwd()), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=20)
        return out.stdout.strip()
    except Exception:
        return "unknown"


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_json(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def jsonl_rows(path: str):
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def provenance(inputs: dict, result_status: str) -> dict:
    """inputs: name -> (abs_path, schema_or_None)."""
    rec = {}
    for name, (p, schema) in sorted(inputs.items()):
        entry = {"path": str(Path(p).resolve())}
        if p and Path(p).exists() and Path(p).is_file():
            entry["sha256"] = sha256_of(str(p))
        else:
            entry["sha256"] = None
            if p and Path(p).exists() and Path(p).is_dir():
                entry["type"] = "directory"
        if schema is not None:
            entry["schema"] = schema
        rec[name] = entry
    return {
        "generated_by": "scripts/research_transition_recovery_detector/"
                        "audit_wp4_light_merge_before_after.py",
        "command": " ".join(sys.argv),
        "utc_timestamp": utc_now(),
        "git_head": git_head(),
        "result_status": result_status,
        "inputs": rec,
    }


def md_header(provenance: dict, title: str) -> list:
    L = [f"# {title}", ""]
    L.append("## Provenance")
    L.append("")
    L.append(f"- generated_by: `{provenance['generated_by']}`")
    L.append(f"- command: `{provenance['command']}`")
    L.append(f"- utc_timestamp: {provenance['utc_timestamp']}")
    L.append(f"- git_head: {provenance['git_head']}")
    L.append(f"- result_status: `{provenance['result_status']}`")
    for name, entry in sorted(provenance["inputs"].items()):
        sha = entry.get("sha256") or "N/A"
        schema = entry.get("schema")
        s = f"- input[{name}]: `{entry['path']}` sha256=`{sha}`"
        if schema:
            s += f" schema=`{schema}`"
        L.append(s)
    L.append("")
    return L


# --------------------------------------------------------------------------
# gate (fail closed)
# --------------------------------------------------------------------------
def eval_pair_targets(before: dict, after: dict, rk: str):
    b = before["targets"][rk]
    a = after["targets"][rk]
    return b, a


def gate_checks(before: dict, after: dict, frozen: dict) -> tuple:
    """Returns (status, checks, mismatches)."""
    checks = []
    b_schema = before.get("schema")
    a_schema = after.get("schema")
    checks.append(("schema", b_schema, a_schema))
    checks.append(("model_kind", before.get("model_kind"), after.get("model_kind")))
    for rk in ("raw", "official"):
        b, a = eval_pair_targets(before, after, rk)
        checks.append((f"{rk}.combo", b.get("combo"), a.get("combo")))
        checks.append((f"{rk}.n_train", b.get("n_train"), a.get("n_train")))
        checks.append((f"{rk}.n_test", b.get("n_test"), a.get("n_test")))
        checks.append((f"{rk}.T_accept", b.get("T_accept"), a.get("T_accept")))
        checks.append((f"{rk}.T_reject", b.get("T_reject"), a.get("T_reject")))
        checks.append((f"{rk}.model_kind", b.get("model_kind"), a.get("model_kind")))
        checks.append((
            f"{rk}.tri_unit_metrics.keys",
            sorted((b.get("tri_unit_metrics") or {}).keys()),
            sorted((a.get("tri_unit_metrics") or {}).keys())))
        checks.append((
            f"{rk}.interval_metrics.keys",
            sorted((b.get("interval_metrics") or {}).keys()),
            sorted((a.get("interval_metrics") or {}).keys())))
        checks.append((
            f"{rk}.by_family.keys",
            sorted((b.get("by_family") or {}).keys()),
            sorted((a.get("by_family") or {}).keys())))
        # frozen operating point must match the after eval threshold
        op = ((frozen or {}).get(rk) or {}).get("standardized_logistic", {}).get(
            "operating_points", {})
        for key in ("T_accept", "T_reject"):
            fv = op.get(key)
            av = a.get(key)
            if av is not None:
                checks.append((f"frozen.{rk}.{key}==after.{rk}.{key}", fv, av))
    mismatches = [c for c in checks if c[1] != c[2]]
    status = STATUS_FIX if not mismatches else STATUS_FAIL
    return status, checks, mismatches


# --------------------------------------------------------------------------
# detector summary
# --------------------------------------------------------------------------
def unit_metrics(target: dict) -> dict:
    tm = target.get("tri_unit_metrics") or {}
    im = target.get("interval_metrics") or {}
    out = {}
    for k in ("protected_recall", "reject_recall", "safe_accept_rate",
              "unsafe_false_accept_rate", "n_unsafe_units", "n_safe_units",
              "n_grey_units"):
        if k in tm:
            out[k] = tm[k]
    if "counts" in tm:
        out["counts"] = tm["counts"]
    for k in ("protected_interval_recall_at_100", "reject_interval_recall_at_100",
              "n_unsafe_intervals", "longest_consecutive_unsafe_accept_run"):
        if k in im:
            out[k] = im[k]
    return out


def split_summary(eval_doc: dict) -> dict:
    out = {}
    for rk in ("raw", "official"):
        t = eval_doc["targets"][rk]
        fam = {}
        for fam_key, v in sorted((t.get("by_family") or {}).items()):
            e = {"n_units": v.get("n_units")}
            vtm = v.get("tri_unit_metrics") or {}
            if vtm:
                for k in ("protected_recall", "safe_accept_rate",
                          "reject_recall"):
                    if k in vtm:
                        e[k] = vtm[k]
            for k in ("protected_recall_95", "safe_accept_rate"):
                if k in v:
                    e[k] = v[k]
            e["interval_metrics"] = v.get("interval_metrics")
            fam[fam_key] = e
        out[rk] = {
            "unit_metrics": unit_metrics(t),
            "by_family": fam,
        }
    return out


def per_song_units(labels_path: str) -> dict:
    cnt = defaultdict(lambda: {"n_units": 0, "n_unsafe": 0, "n_safe": 0,
                               "n_grey": 0, "targets": defaultdict(int)})
    n_rows = 0
    for row in jsonl_rows(labels_path):
        n_rows += 1
        song = row.get("song_id")
        fam = row.get("family")
        key = (str(song), str(fam))
        c = cnt[key]
        c["n_units"] += 1
        lab = row.get("label")
        if lab == "unsafe":
            c["n_unsafe"] += 1
        elif lab == "safe":
            c["n_safe"] += 1
        elif lab == "grey":
            c["n_grey"] += 1
        c["targets"][str(row.get("target"))] += 1
    out = []
    for (song, fam), c in sorted(cnt.items()):
        out.append({
            "song_id": song,
            "family": fam,
            "n_units": c["n_units"],
            "n_unsafe": c["n_unsafe"],
            "n_safe": c["n_safe"],
            "n_grey": c["n_grey"],
            "n_targets": dict(c["targets"]),
        })
    return {"n_rows": n_rows, "per_song": out}


def build_detector_summary(before_docs: dict, after_docs: dict, frozen: dict,
                           labels_path: str) -> dict:
    gates = {}
    summaries = {}
    for name in ("M4_SONG_HELDOUT", "FAMILY_LOO"):
        b = before_docs.get(name)
        a = after_docs.get(name)
        if b is None or a is None:
            continue
        status, checks, mismatches = gate_checks(b, a, frozen)
        gates[name] = {
            "status": status,
            "n_checks": len(checks),
            "mismatches": mismatches,
        }
        summaries[name] = {
            "gate": gates[name],
            "before": split_summary(b),
            "after": split_summary(a),
        }
        if status == STATUS_FIX:
            for rk in ("raw", "official"):
                be = summaries[name]["before"][rk]["unit_metrics"]
                af = summaries[name]["after"][rk]["unit_metrics"]
                summaries[name]["delta_" + rk] = {
                    k: ({"before": be.get(k), "after": af.get(k),
                         "delta": _delta(be.get(k), af.get(k))})
                    for k in ("protected_recall", "reject_recall",
                              "safe_accept_rate", "unsafe_false_accept_rate")
                    if k in af
                }
    per_song = None
    if labels_path and Path(labels_path).exists():
        per_song = per_song_units(labels_path)
    return {
        "gates": gates,
        "summaries": summaries,
        "per_song_units": per_song,
        "note": ("per-song tri-unit metrics are not available in the eval "
                 "artifact (only by_family: baseline/missing and family LOO); "
                 "per-song table above is unit-count boundary from LABELS only."),
    }


def _delta(b, a):
    if isinstance(b, (int, float)) and isinstance(a, (int, float)):
        return a - b
    return None


def _fmt3(v):
    if v is None:
        return "-"
    return f"{v:.3f}"


# --------------------------------------------------------------------------
# window-gate score consumption (streamed)
# --------------------------------------------------------------------------
def build_score_table(scores_dir: str, scores_jsonl: str,
                      report_path: str) -> tuple:
    """Returns (rows, info). p_bad aggregates carried from report (fit not re-run)."""
    rows_by_req = defaultdict(int)
    n_evidence = 0
    for p in sorted(glob.glob(str(Path(scores_dir) / "*.json"))):
        n_evidence += 1
        d = load_json(p)
        rid = (((d.get("attempt") or {}).get("request") or {}).get("request_id"))
        if rid:
            rows_by_req[rid] += 1

    met = {}
    n_per = 0
    for row in jsonl_rows(scores_jsonl):
        n_per += 1
        m = row.get("metrics") or {}
        hit = (m.get("tolerance_hit_rates_ms") or {}).get("100")
        met[row.get("request_id")] = {
            "hit100": hit,
            "start_mae_sec": m.get("start_mae_sec"),
            "n_evaluated": m.get("n_evaluated"),
            "song_id": row.get("song_id"),
        }

    pb_agg = {}
    t_accept = None
    if report_path and Path(report_path).exists():
        rep = load_json(report_path)
        t_accept = rep.get("T_ACCEPT")
        for r in rep.get("all_requests", []):
            pb_agg[r["request_id"]] = {
                "mean_pb": r.get("mean_pb"),
                "p90_pb": r.get("p90_pb"),
                "frac_gt_Taccept": r.get("frac_gt_Taccept"),
                "max_pb": r.get("max_pb"),
            }

    rows = []
    for rid in sorted(set(rows_by_req) | set(met)):
        m = met.get(rid, {})
        hit = m.get("hit100")
        row = {
            "request_id": rid,
            "n_rows": int(rows_by_req.get(rid, 0)),
            "hit100": hit,
            "start_mae_sec": m.get("start_mae_sec"),
            "n_evaluated": m.get("n_evaluated"),
            "song_id": m.get("song_id"),
            "bad": (hit is not None and hit < BAD_HIT100),
        }
        row.update(pb_agg.get(rid, {}))
        rows.append(row)
    n_bad = sum(1 for r in rows if r["bad"])
    info = {
        "BAD_HIT100": BAD_HIT100,
        "T_ACCEPT": t_accept,
        "n_evidence_files": n_evidence,
        "n_per_request_rows": n_per,
        "n_requests": len(rows),
        "n_bad": n_bad,
        "n_good": len(rows) - n_bad,
        "score_definition": (
            "per-request hit100/start_mae_sec/n_evaluated/n_rows read from "
            "rerun_gpu/evidence/*.json + rerun_gpu/reagg/PER_REQUEST.jsonl "
            "(streamed); bad := hit100 < 0.7 (E1 contract). p_bad aggregates "
            "(mean_pb/p90_pb/frac_gt_Taccept/max_pb) carried from existing "
            "window_gate_report.json (standardized_logistic fit B-train -> "
            "score A-test, fit NOT re-run). Exploratory only."),
        "exploratory": True,
    }
    return rows, info


def auroc(scores_bad, scores_good):
    if not scores_bad or not scores_good:
        return None
    s = c = 0
    for a in scores_bad:
        for b in scores_good:
            s += (a > b) + 0.5 * (a == b)
            c += 1
    return s / c


def threshold_sweep(rows: list) -> list:
    bad = [r for r in rows if r["bad"]]
    good = [r for r in rows if not r["bad"]]
    out = []
    for cand in CANDIDATES:
        sb = [r[cand] for r in bad if r.get(cand) is not None]
        sg = [r[cand] for r in good if r.get(cand) is not None]
        auc = auroc(sb, sg)
        for t in THRESH_GRID:
            cap = sum(r.get(cand) is not None and r[cand] > t for r in bad)
            fp = sum(r.get(cand) is not None and r[cand] > t for r in good)
            out.append({
                "candidate": cand,
                "threshold": t,
                "auroc": auc,
                "captured_bad": cap,
                "n_bad": len(bad),
                "capture_ratio": cap / len(bad) if bad else None,
                "fp_good": fp,
                "n_good": len(good),
                "fp_ratio": fp / len(good) if good else None,
                "exploratory_test_tuned_threshold": True,
                "formal_threshold": False,
            })
    return out


# --------------------------------------------------------------------------
# song failure concentration (per-song, from unit-level LABELS)
# --------------------------------------------------------------------------
COHORT_NA = "not_available_cohort_identity"

SFC_CSV_COLUMNS = [
    "cohort", "target", "song_id", "family", "n_labeled", "n_safe", "n_grey",
    "n_unsafe", "n_gt_unavailable", "unsafe_fraction",
    "share_of_target_all_unsafe", "cumulative_unsafe_share",
]

DETECTOR_DECISION_UNAVAILABLE_REASON = (
    "no repaired unit-level detector decision artifact keyed by "
    "(song_id, canonical_unit_id, target) is present; only request-level "
    "PER_REQUEST.jsonl / rerun_gpu evidence files exist, so per-song "
    "unsafe_accept/unsafe_protected/protected_recall/safe_accept are not "
    "reported (GT failure concentration only).")


def load_cohort_song_sets(cohort_a_formal: str, cohort_a_diag: str,
                          cohort_b_dev: str) -> tuple:
    """Reads cohort song_id membership from COHORT jsonl files.

    cohort_a_songs union = A (split=test); cohort_b_songs = B (validation).
    Missing files are recorded in meta so all un-joinable songs are labeled
    not_available_cohort_identity instead of silently assuming membership.
    """
    a, b, missing = set(), set(), []

    def load(path, into):
        p = Path(path)
        if p.exists() and p.is_file():
            for row in jsonl_rows(str(p)):
                sid = row.get("song_id")
                if sid is not None:
                    into.add(str(sid))
        else:
            missing.append(str(p))

    load(cohort_a_formal, a)
    load(cohort_a_diag, a)
    load(cohort_b_dev, b)
    meta = {
        "cohort_a_sources": [cohort_a_formal, cohort_a_diag],
        "cohort_b_sources": [cohort_b_dev],
        "missing_cohort_files": missing,
        "n_cohort_a_songs": len(a),
        "n_cohort_b_songs": len(b),
    }
    return a, b, meta


def song_failure_concentration_from_labels(
        label_rows, cohort_a_songs: set, cohort_b_songs: set) -> tuple:
    """Per-(cohort,target,song_id,family) GT failure concentration.

    label_rows: iterable of dicts with song_id / target(raw|official) /
        family(baseline|missing) / label(safe|grey|unsafe|gt_unavailable).
        gt_unavailable is excluded from n_labeled (reported as
        n_gt_unavailable). cohort is derived from song_id membership:
        cohort_a_songs -> "A", cohort_b_songs -> "B", else
        not_available_cohort_identity.
    Sorted per target by share_of_target_all_unsafe DESC, song_id, family;
    cumulative_unsafe_share accumulates over that order.
    Returns (rows, meta). meta carries detector_decision_status (detector
    decision join is not available: no unit-level decision artifact).
    """
    stats = defaultdict(lambda: {"n_labeled": 0, "n_safe": 0, "n_grey": 0,
                                 "n_unsafe": 0, "n_gt_unavailable": 0})
    target_unsafe_total = defaultdict(int)
    n_rows = 0
    for row in label_rows:
        n_rows += 1
        song = row.get("song_id")
        target = row.get("target")
        family = row.get("family")
        label = row.get("label")
        if song is None or target is None or family is None or label is None:
            continue
        if str(song) in cohort_a_songs:
            cohort = "A"
        elif str(song) in cohort_b_songs:
            cohort = "B"
        else:
            cohort = COHORT_NA
        key = (cohort, str(target), str(song), str(family))
        s = stats[key]
        if label == "gt_unavailable":
            s["n_gt_unavailable"] += 1
            continue
        s["n_labeled"] += 1
        if label == "safe":
            s["n_safe"] += 1
        elif label == "grey":
            s["n_grey"] += 1
        elif label == "unsafe":
            s["n_unsafe"] += 1
            target_unsafe_total[str(target)] += 1

    rows = []
    for (cohort, target, song, family), s in sorted(stats.items()):
        n_unsafe = s["n_unsafe"]
        n_labeled = s["n_labeled"]
        tot = target_unsafe_total.get(target, 0)
        rows.append({
            "cohort": cohort,
            "target": target,
            "song_id": song,
            "family": family,
            "n_labeled": n_labeled,
            "n_safe": s["n_safe"],
            "n_grey": s["n_grey"],
            "n_unsafe": n_unsafe,
            "n_gt_unavailable": s["n_gt_unavailable"],
            "unsafe_fraction": (n_unsafe / n_labeled) if n_labeled else None,
            "share_of_target_all_unsafe": (n_unsafe / tot) if tot else None,
            "cumulative_unsafe_share": None,
        })

    out = []
    per_target = defaultdict(list)
    for r in rows:
        per_target[r["target"]].append(r)
    for target in sorted(per_target):
        group = per_target[target]
        group.sort(key=lambda r: (
            -1 if r["share_of_target_all_unsafe"] is None
            else -r["share_of_target_all_unsafe"],
            r["song_id"], r["family"]))
        cum = 0.0
        for r in group:
            sh = r["share_of_target_all_unsafe"]
            if sh is not None:
                cum += sh
            r["cumulative_unsafe_share"] = cum
        out.extend(group)

    meta = {
        "detector_decision_status": "not_available",
        "detector_decision_reason": DETECTOR_DECISION_UNAVAILABLE_REASON,
        "n_rows": n_rows,
        "n_targets": len(per_target),
        "n_cohort_not_available_songs": sum(
            1 for r in out if r["cohort"] == COHORT_NA),
    }
    return out, meta


# --------------------------------------------------------------------------
# writer
# --------------------------------------------------------------------------
def write_json(path: Path, obj: dict) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def write_csv(path: Path, fieldnames: list, rows: list) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r.get(k) is None else r.get(k))
                        for k in fieldnames})


def run(args) -> dict:
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    def resolve_eval(spec):
        p = Path(spec)
        if p.is_dir():
            docs = {}
            files = []
            for name in ("M4_SONG_HELDOUT.json", "FAMILY_LOO.json"):
                f = p / name
                if f.exists():
                    docs[name.replace(".json", "")] = load_json(str(f))
                    files.append(str(f))
            return p, docs, files
        if p.suffix == ".json":
            d = load_json(str(p))
            name = "M4_SONG_HELDOUT" if "M4" in p.name else \
                ("FAMILY_LOO" if "FAMILY" in p.name.upper() else
                 p.stem.replace(".json", ""))
            return p, {name: d}, [str(p)]
        raise SystemExit(f"cannot resolve eval spec: {spec}")

    before_path, before_docs, before_files = resolve_eval(args.before)
    after_path, after_docs, after_files = resolve_eval(args.after)
    if not before_docs or not after_docs:
        raise SystemExit("empty before/after eval docs; need M4_SONG_HELDOUT "
                         "and/or FAMILY_LOO")

    frozen = load_json(args.frozen) if Path(args.frozen).exists() else {}

    # ---- gate + detector summary ------------------------------------------
    summary = build_detector_summary(before_docs, after_docs, frozen,
                                     args.labels)
    gate_status = STATUS_FIX
    for g in summary["gates"].values():
        if g["status"] == STATUS_FAIL:
            gate_status = STATUS_FAIL
    if not summary["gates"]:
        gate_status = STATUS_FAIL

    inputs = {}
    for f in before_files:
        base = Path(f).name.replace(".json", "")
        inputs["before_" + base] = (f, "detector_eval")
    for f in after_files:
        base = Path(f).name.replace(".json", "")
        inputs["after_" + base] = (f, "detector_eval")
    inputs.update({
        "frozen": (args.frozen, "FROZEN_OPERATING_POINTS"),
        "labels": (args.labels, "LABELS"),
        "cohort_a_formal": (args.cohort_a_formal, "COHORT_A_FORMAL"),
        "cohort_a_diag": (args.cohort_a_diag, "COHORT_A_DIAGNOSTIC"),
        "cohort_b_dev": (args.cohort_b_dev, "COHORT_B_DEVELOPMENT"),
        "window_report": (args.window_report, "window_gate_report_v1"),
        "rerun_90": (args.rerun_90, "rerun_90_requests"),
        "scores_dir": (args.scores_dir, "rerun_gpu_evidence"),
        "scores_jsonl": (args.scores_jsonl, "PER_REQUEST"),
    })
    if gate_status == STATUS_FAIL:
        prov = provenance(inputs, STATUS_FAIL)
        fail_doc = {
            "provenance": prov,
            "error": "gate fail_closed: before/after cohort identity, score+model "
                     "identity, threshold values, or label+metric schema differ",
            "gates": {k: {"status": v["status"],
                          "mismatches": v["mismatches"]}
                      for k, v in summary["gates"].items()},
            "result_status": STATUS_FAIL,
        }
        write_json(out_dir / "corrected_detector_summary.json", fail_doc)
        write_json(out_dir / "window_gate_score_summary.json",
                   {"provenance": prov,
                    "result_status": STATUS_FAIL,
                    "error": "gate fail_closed; score files not consumed"})
        return {"status": STATUS_FAIL}

    # ---- detector summary (gate passed) ------------------------------------
    prov = provenance(inputs, STATUS_FIX)
    summary["provenance"] = prov
    summary["result_status"] = STATUS_FIX
    write_json(out_dir / "corrected_detector_summary.json", summary)

    # markdown
    md = md_header(prov, "Corrected Detector Summary (light-merge fix)")
    md.append(f"- gate result_status: `{STATUS_FIX}`")
    for name, g in sorted(summary["gates"].items()):
        md.append(f"- gate[{name}]: {g['status']} "
                  f"({g['n_checks']} checks, {len(g['mismatches'])} mismatches)")
    md.append("")
    for name, s in sorted(summary["summaries"].items()):
        md.append(f"## {name}")
        md.append("")
        md.append("| split | metric | before | after | delta |")
        md.append("|---|---|---|---|---|")
        for rk in ("raw", "official"):
            for k, v in sorted(s.get("delta_" + rk, {}).items()):
                md.append(f"| {rk} | {k} | {v['before']} | {v['after']} | "
                          f"{v['delta']} |")
        for rk in ("raw", "official"):
            bf = s["before"][rk]["by_family"]
            af = s["after"][rk]["by_family"]
            for fam in sorted(set(bf) | set(af)):
                bm = (bf.get(fam) or {}).get("tri_unit_metrics") or {}
                am = (af.get(fam) or {}).get("tri_unit_metrics") or {}
                md.append("")
                md.append(f"### {name} {rk} by_family[{fam}]")
                md.append("")
                md.append("| metric | before | after |")
                md.append("|---|---|---|")
                for k in ("protected_recall", "safe_accept_rate", "reject_recall"):
                    md.append(f"| {k} | {bm.get(k)} | {am.get(k)} |")
        md.append("")
    if summary.get("per_song_units"):
        ps = summary["per_song_units"]
        md.append(f"## Per-song unit boundary (LABELS, {ps['n_rows']} rows)")
        md.append("")
        md.append("| song_id | family | n_units | n_unsafe | n_safe |")
        md.append("|---|---|---|---|---|")
        for r in ps["per_song"][:200]:
            md.append(f"| {r['song_id']} | {r['family']} | {r['n_units']} | "
                      f"{r['n_unsafe']} | {r['n_safe']} |")
        md.append("")
        md.append("> " + summary["note"])
    (out_dir / "corrected_detector_summary.md").write_text("\n".join(md) + "\n",
                                                           encoding="utf-8")

    # ---- light merge before/after -------------------------------------------
    lmd = md_header(prov, "Light Merge Before/After (detector eval)")
    lmd.append("## Gate 验证结论")
    lmd.append("")
    for name, g in sorted(summary["gates"].items()):
        lmd.append(f"- **{name}**: `{g['status']}` — {g['n_checks']} 项检查，"
                   f"{len(g['mismatches'])} 项不一致")
        for m in g["mismatches"]:
            lmd.append(f"  - MISMATCH {m[0]}: before={m[1]} after={m[2]}")
    lmd.append("")
    lmd.append("结论：before/after 仅 postprocess（light-merge fix）版本变化，"
               "cohort identity / score+model identity / threshold values / "
               "label+metric schema 完全一致，"
               f"result_status=`{STATUS_FIX}`。")
    lmd.append("")
    for name, s in sorted(summary["summaries"].items()):
        lmd.append(f"## {name} delta")
        lmd.append("")
        for rk in ("raw", "official"):
            lmd.append(f"### {rk}")
            lmd.append("")
            lmd.append("| metric | before | after | delta |")
            lmd.append("|---|---|---|---|")
            for k, v in sorted(s.get("delta_" + rk, {}).items()):
                lmd.append(f"| {k} | {v['before']} | {v['after']} | {v['delta']} |")
            lmd.append("")
    (out_dir / "light_merge_before_after.md").write_text(
        "\n".join(lmd) + "\n", encoding="utf-8")

    # ---- window-gate scores --------------------------------------------------
    scores_missing = not (args.scores_dir and args.scores_jsonl
                          and Path(args.scores_dir).is_dir()
                          and Path(args.scores_jsonl).exists())
    if scores_missing:
        wp = provenance(inputs, STATUS_MISSING)
        miss = {"provenance": wp, "result_status": STATUS_MISSING,
                "error": ("--scores-dir/--scores-jsonl not given or missing; "
                          "window-gate score source unavailable"),
                "BAD_HIT100": BAD_HIT100}
        write_json(out_dir / "window_gate_score_summary.json", miss)
        with open(out_dir / "window_gate_threshold_sweep.csv", "w",
                  newline="", encoding="utf-8") as f:
            f.write(f"# result_status={STATUS_MISSING} "
                    "window-gate score source missing\n")
        (out_dir / "window_gate_exploratory.md").write_text(
            "\n".join(md_header(wp, "Window-Gate Exploratory")) +
            f"\n\nERROR: {miss['error']}\n", encoding="utf-8")
    else:
        rows, info = build_score_table(args.scores_dir, args.scores_jsonl,
                                       args.window_report)
        sweep = threshold_sweep(rows)
        wp = provenance(inputs, STATUS_OK)
        wp_doc = {"provenance": wp, "info": info,
                  "result_status": STATUS_OK,
                  "requests": rows}
        write_json(out_dir / "window_gate_score_summary.json", wp_doc)
        write_csv(out_dir / "window_gate_threshold_sweep.csv",
                  ["candidate", "threshold", "auroc", "captured_bad", "n_bad",
                   "capture_ratio", "fp_good", "n_good", "fp_ratio",
                   "exploratory_test_tuned_threshold", "formal_threshold"],
                  sweep)
        wmd = md_header(wp, "Window-Gate Exploratory (score source)")
        wmd.append("## score definition (exploratory)")
        wmd.append("")
        wmd.append(info["score_definition"])
        wmd.append("")
        wmd.append(f"- n_requests={info['n_requests']} "
                   f"n_bad(hit100<{BAD_HIT100})={info['n_bad']} "
                   f"n_good={info['n_good']}")
        wmd.append(f"- T_ACCEPT={info['T_ACCEPT']}")
        wmd.append("")
        wmd.append("## 阈值扫描（exploratory_test_tuned_threshold=true, "
                   "formal_threshold=false；不修改任何冻结 working point）")
        wmd.append("")
        wmd.append("| candidate | thresh | capt_bad | n_bad | capt% | fp_good | "
                   "n_good | fp% | AUROC |")
        wmd.append("|---|---|---|---|---|---|---|---|---|")
        for r in sweep:
            wmd.append(f"| {r['candidate']} | {r['threshold']:.2f} | "
                       f"{r['captured_bad']} | {r['n_bad']} | "
                       f"{(r['capture_ratio'] or 0)*100:.0f}% | {r['fp_good']} | "
                       f"{r['n_good']} | {(r['fp_ratio'] or 0)*100:.0f}% | "
                       f"{r['auroc']} |")
        wmd.append("")
        ok = [r for r in sweep if r["capture_ratio"] == 1.0
              and r["fp_ratio"] is not None and r["fp_ratio"] <= 0.15]
        wmd.append("## 结论")
        wmd.append("")
        if ok:
            ok_sorted = sorted(ok, key=lambda r: (r["fp_ratio"], -r["threshold"]))
            best = ok_sorted[0]
            wmd.append(f"- 存在全捕获且误伤<=15% 组合 "
                       f"({len(ok)} 个)：最优 "
                       f"candidate={best['candidate']} threshold={best['threshold']:.2f} "
                       f"fp_ratio={best['fp_ratio']*100:.1f}% "
                       f"(exploratory，未落地，formal_threshold=false)")
        else:
            wmd.append("- 无满足全部 bad 捕获且误伤<=15% 的组合"
                       "（exploratory 结论，不改变冻结阈值）")
        wmd.append("")
        wmd.append("> 所有 threshold/扫描均为 exploratory；冻结 operating point 未改动。")
        (out_dir / "window_gate_exploratory.md").write_text(
            "\n".join(wmd) + "\n", encoding="utf-8")

    # ---- song failure concentration (per-song, from LABELS) -----------------
    labels_ok = bool(args.labels) and Path(args.labels).exists()
    if labels_ok:
        cohort_a_songs, cohort_b_songs, cohort_meta = load_cohort_song_sets(
            args.cohort_a_formal, args.cohort_a_diag, args.cohort_b_dev)
        sfc, sfc_meta = song_failure_concentration_from_labels(
            jsonl_rows(args.labels), cohort_a_songs, cohort_b_songs)
        sfc_meta.update(cohort_meta)
        sfc_status = STATUS_OK
    else:
        sfc, sfc_meta = [], {
            "detector_decision_status": "not_available",
            "detector_decision_reason": DETECTOR_DECISION_UNAVAILABLE_REASON,
            "error": "--labels missing; per-song concentration not produced",
        }
        sfc_status = STATUS_MISSING
    sp = provenance(inputs, sfc_status)
    write_csv(out_dir / "song_failure_concentration.csv", SFC_CSV_COLUMNS, sfc)
    smd = md_header(sp, "Song Failure Concentration (per-song, GT)")
    smd.append(f"- result_status: `{sfc_status}`")
    smd.append(f"- detector_decision_status: `{sfc_meta.get('detector_decision_status')}`")
    smd.append(f"- detector_decision_reason: "
               f"{sfc_meta.get('detector_decision_reason')}")
    if sfc_meta.get("missing_cohort_files"):
        smd.append("- cohort file(s) missing -> un-joinable songs marked "
                   f"`{COHORT_NA}`: {', '.join(sfc_meta['missing_cohort_files'])}")
    smd.append("- cohort by song_id join: cohort_a (formal+diagnostic, "
               "split=test) -> `A`; cohort_b (development, split=validation) "
               "-> `B`; else `not_available_cohort_identity`.")
    smd.append("- n_labeled = safe+grey+unsafe (gt_unavailable 计入 "
               "n_gt_unavailable，不进分母)；share_of_target_all_unsafe = "
               "该歌该 family n_unsafe / 该 target 全部 n_unsafe；目标内按 "
               "share DESC, song_id, family 排序后累计 cumulative_unsafe_share。")
    smd.append("")
    smd.append("| cohort | target | song_id | family | n_labeled | n_safe | "
               "n_grey | n_unsafe | n_gt_unavail | unsafe_frac | share | cum |")
    smd.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for r in sfc:
        smd.append(f"| {r['cohort']} | {r['target']} | {r['song_id']} | "
                   f"{r['family']} | {r['n_labeled']} | {r['n_safe']} | "
                   f"{r['n_grey']} | {r['n_unsafe']} | {r['n_gt_unavailable']} | "
                   f"{_fmt3(r['unsafe_fraction'])} | "
                   f"{_fmt3(r['share_of_target_all_unsafe'])} | "
                   f"{_fmt3(r['cumulative_unsafe_share'])} |")
    smd.append("")
    smd.append("## Top-k cumulative unsafe share (per target)")
    smd.append("")
    for target in sorted({r["target"] for r in sfc}):
        tg = [r for r in sfc if r["target"] == target]
        tg.sort(key=lambda r: (
            -1 if r["share_of_target_all_unsafe"] is None
            else -r["share_of_target_all_unsafe"], r["song_id"], r["family"]))
        tot = sum(r["n_unsafe"] for r in tg)
        smd.append(f"### target={target} (total unsafe={tot})")
        smd.append("")
        smd.append("| k | songs | cumulative_unsafe_share |")
        smd.append("|---|---|---|")
        cum = 0.0
        for k, r in enumerate(tg, start=1):
            if r["share_of_target_all_unsafe"] is not None:
                cum += r["share_of_target_all_unsafe"]
            if k in (1, 2, 3, 5):
                smd.append(f"| top-{k} | {r['song_id']}/{r['family']} | "
                           f"{_fmt3(cum)} |")
        smd.append("")
    (out_dir / "song_failure_concentration.md").write_text(
        "\n".join(smd) + "\n", encoding="utf-8")

    return {"status": gate_status}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--before", required=True,
                    help="before eval json (or dir with M4_SONG_HELDOUT/FAMILY_LOO)")
    ap.add_argument("--after", required=True,
                    help="after eval json (or dir)")
    ap.add_argument("--frozen", required=True,
                    help="FROZEN_OPERATING_POINTS.json")
    ap.add_argument("--labels", required=True,
                    help="LABELS.jsonl")
    handoff = ("/home/hyan/Data/lyricalign/runs/"
               "research_transition_recovery_detector_"
               "20260810_realgt_expansion_handoff")
    ap.add_argument("--cohort-a-formal",
                    default=handoff + "/COHORT_A_FORMAL.jsonl",
                    help="cohort A formal song list jsonl (split=test)")
    ap.add_argument("--cohort-a-diag",
                    default=handoff + "/COHORT_A_DIAGNOSTIC.jsonl",
                    help="cohort A diagnostic song list jsonl (split=test)")
    ap.add_argument("--cohort-b-dev",
                    default=handoff + "/COHORT_B_DEVELOPMENT.jsonl",
                    help="cohort B development song list jsonl (split=validation)")
    ap.add_argument("--window-report",
                    default="/tmp/opencode/window_gate_report.json")
    ap.add_argument("--rerun-90", default="/tmp/opencode/rerun_90.jsonl")
    ap.add_argument("--scores-dir",
                    default=("/home/hyan/Data/lyricalign/runs/"
                             "research_transition_recovery_detector_"
                             "20260810_realgt_expansion_handoff/"
                             "stage3b_cohort_a_reagg/rerun_gpu/evidence"))
    ap.add_argument("--scores-jsonl",
                    default=("/home/hyan/Data/lyricalign/runs/"
                             "research_transition_recovery_detector_"
                             "20260810_realgt_expansion_handoff/"
                             "stage3b_cohort_a_reagg/rerun_gpu/reagg/"
                             "PER_REQUEST.jsonl"))
    ap.add_argument("--out", default=str(RESULTS_DEFAULT))
    args = ap.parse_args()
    res = run(args)
    print("result_status:", res["status"])
    print("written:", args.out)


if __name__ == "__main__":
    main()
