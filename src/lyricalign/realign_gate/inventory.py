"""00_inventory stage for Detector Production Audit + Realign Gate.

Pure read-only inventory: real GT projection summary (across cohort manifests),
old baseline evidence census, constructible window counts, test-demo item
discovery and baseline identity (incl. repo HEAD). No GPU.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lyricalign.realign_gate import identity
from lyricalign.research_transition_recovery_detector.real_gt import load_real_gt_with_audit

AUDIO_EXTS = frozenset({".wav", ".mp3", ".m4a", ".flac", ".mp4", ".mov", ".aac"})
LANGUAGES = ("chinese", "english", "japanese", "cantonese")

SCHEMAS = {
    "data_inventory": "realign_gate/data_inventory/1",
    "baseline_identity": "realign_gate/detector_baseline_identity/1",
    "test_demo_inventory": "realign_gate/test_demo_inventory/1",
}


def _sha256_file(path: str | Path) -> str | None:
    p = Path(path)
    if not p.is_file():
        return None
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _count_jsonl_lines(path: str | Path) -> int:
    p = Path(path)
    if not p.is_file():
        return 0
    n = 0
    with p.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                n += 1
    return n


def load_real_gt_with_audit_map(
    annotations_path: str | Path,
    manifest_paths: list[str | Path],
) -> tuple[dict[str, dict[int, dict]], dict[str, dict[str, int]]]:
    """Load real GT per manifest and merge (union over songs/units, sum audits)."""
    merged_gt: dict[str, dict[int, dict]] = {}
    merged_audit: dict[str, dict[str, int]] = {}
    for manifest in manifest_paths:
        gt, audit = load_real_gt_with_audit(annotations_path, manifest)
        for song, units in gt.items():
            merged_gt.setdefault(song, {}).update(units)
        for song, reasons in audit.items():
            merged_audit.setdefault(song, {})
            for reason, count in reasons.items():
                merged_audit[song][reason] = merged_audit[song].get(reason, 0) + count
    return merged_gt, merged_audit


def _manifest_summary(manifest: str | Path) -> dict[str, Any]:
    """Per-cohort census from a LONG_TIMELINE_MANIFEST.jsonl."""
    n_songs = 0
    n_units = 0
    total_duration = 0.0
    constructible = 0
    for line in Path(manifest).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        n_songs += 1
        n_units += len(r.get("canonical_units", []))
        dur = float(r.get("duration_sec", 0.0))
        total_duration += dur
        if dur >= identity.CORE_SEC:
            constructible += 1
    return {
        "manifest": str(manifest),
        "manifest_sha256": _sha256_file(manifest),
        "n_songs": n_songs,
        "n_canonical_units": n_units,
        "total_duration_sec": round(total_duration, 3),
        "constructible_windows": constructible,
        "constructible_rule": f"duration_sec >= core_sec({identity.CORE_SEC:g}s)",
    }


def _existing_evidence(old_requests: str | Path) -> dict[str, Any]:
    ev_root = identity.OLD_RUN / "e5_proposals"
    evidence_dirs = []
    for cand in ("raw", "candidate_bank", "formal"):
        p = ev_root / cand
        if p.is_dir():
            evidence_dirs.append({"path": str(p), "exists": True, "n_entries": len(list(p.iterdir()))})
    return {
        "requests_path": str(old_requests),
        "n_requests": _count_jsonl_lines(old_requests),
        "requests_sha256": _sha256_file(old_requests),
        "old_run": str(identity.OLD_RUN),
        "evidence_dirs": evidence_dirs,
    }


def build_data_inventory(run_root: str | Path, cfg: dict) -> dict:
    """DATA_INVENTORY payload: real_gt summary, cohorts, windows, evidence, inputs."""
    run_root = Path(run_root)
    inputs_cfg = cfg["inputs"]
    annotations = Path(inputs_cfg["real_gt_annotations"])
    manifests = [Path(m) for m in inputs_cfg["cohort_manifests"]]
    frozen_op = Path(inputs_cfg["frozen_op"])
    old_requests = Path(inputs_cfg["old_run_requests"])
    demo_roots = inputs_cfg["test_demo_roots"]

    real_gt, audit = load_real_gt_with_audit_map(annotations, manifests)

    cohorts = []
    pooled = {"n_songs": 0, "n_canonical_units": 0, "total_duration_sec": 0.0, "constructible_windows": 0}
    for m in manifests:
        c = _manifest_summary(m)
        cohorts.append(c)
        for k in pooled:
            if k != "constructible_rule":
                pooled[k] += c[k]

    unlabeled_by_reason: dict[str, int] = {}
    for reasons in audit.values():
        for reason, count in reasons.items():
            unlabeled_by_reason[reason] = unlabeled_by_reason.get(reason, 0) + count
    real_gt_summary = {
        "n_songs": len(real_gt),
        "accepted_units": sum(len(u) for u in real_gt.values()),
        "n_unlabeled_total": sum(unlabeled_by_reason.values()),
        "unlabeled_by_reason": unlabeled_by_reason,
    }

    demo_items = discover_test_demo_items(demo_roots)
    by_lang = Counter(i["lang"] for i in demo_items)
    by_root = Counter(i["root"] for i in demo_items)

    input_paths = [annotations, frozen_op, old_requests] + manifests
    inputs_sha = {str(p): _sha256_file(p) for p in input_paths}

    return {
        "run_root": str(run_root),
        "identity": identity.baseline_identity(),
        "real_gt_summary": real_gt_summary,
        "cohorts": cohorts,
        "constructible_windows": pooled,
        "existing_evidence": _existing_evidence(old_requests),
        "demo_summary": {
            "n_items": len(demo_items),
            "by_language": dict(by_lang),
            "by_root": dict(by_root),
        },
        "inputs": inputs_sha,
    }


def plan_baseline_windows(duration: float) -> list[tuple[int, float, float, float]]:
    """Plan production baseline windows: 60s core stride / 10s context.

    Only builds when duration >= CORE_SEC. core_start starts at 0 and steps by
    CORE_SEC while core_start + CORE_SEC <= duration.
    Returns [(window_index, core_start, window_start, window_end)].
    """
    if duration < identity.CORE_SEC:
        return []
    windows: list[tuple[int, float, float, float]] = []
    window_index = 0
    core_start = 0.0
    while core_start + identity.CORE_SEC <= duration:
        window_start = max(0.0, core_start - identity.LEFT_CONTEXT_SEC)
        window_end = min(duration, core_start + identity.CORE_SEC + identity.RIGHT_CONTEXT_SEC)
        windows.append((window_index, core_start, window_start, window_end))
        window_index += 1
        core_start += identity.CORE_SEC
    return windows


def build_baseline_population(run_root: str | Path, cfg: dict) -> dict:
    """Build production raw baseline population (P0).

    Traverses cfg["inputs"]["cohort_manifests"] and writes, under
    run_root/00_inventory/:
      - BASELINE_WINDOW_INDEX.jsonl      (one row per planned window)
      - BASELINE_UNITS.jsonl             (unit membership per window)
      - BASELINE_DETECTOR_SHADOW.jsonl   (placeholder, backfilled by stage 01)
      - DETECTOR_BASELINE_POPULATION.json (summary)
    """
    run_root = Path(run_root)
    out_dir = run_root / "00_inventory"
    out_dir.mkdir(parents=True, exist_ok=True)

    idx_rows: list[dict] = []
    unit_rows: list[dict] = []
    shadow_rows: list[dict] = []
    warnings: list[str] = []
    seen_window_keys: set[tuple[str, str]] = set()

    for manifest in cfg["inputs"]["cohort_manifests"]:
        for line in Path(manifest).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            song_id = r["song_id"]
            duration = float(r["duration_sec"])
            audio_path = r.get("concat_audio_path")
            timeline_id = r.get("timeline_id")
            units = sorted(r.get("canonical_units", []), key=lambda u: (u["start_sec"], u["end_sec"]))

            for window_index, core_start, window_start, window_end in plan_baseline_windows(duration):
                window_id = f"{song_id}:{window_index}"
                if (song_id, window_id) in seen_window_keys:
                    if timeline_id is None:
                        raise ValueError(
                            f"duplicate baseline window key ({song_id!r}, {window_id!r}) "
                            "without timeline_id; refusing to emit an ambiguous "
                            "(song_id, window_id) population key (P0 fail-fast)"
                        )
                    window_id = f"{window_id}#{timeline_id}"
                    warnings.append(
                        f"window_id collision on {song_id}:{window_index}; disambiguated via #{timeline_id}"
                    )
                seen_window_keys.add((song_id, window_id))

                in_window = [
                    u for u in units
                    if u["start_sec"] < window_end and u["end_sec"] > window_start
                ]
                core_end = core_start + identity.CORE_SEC
                in_core = [
                    u for u in in_window
                    if u["end_sec"] >= core_start and u["start_sec"] < core_end
                ]
                target_unit_ids = [u["canonical_unit_id"] for u in in_core]
                canonical_unit_ids = [u["canonical_unit_id"] for u in in_window]
                text_unit_start = in_window[0]["canonical_unit_id"] if in_window else None
                text_unit_end = in_window[-1]["canonical_unit_id"] if in_window else None

                idx_rows.append({
                    "song_id": song_id,
                    "window_id": window_id,
                    "window_index": window_index,
                    "window_start_sec": window_start,
                    "window_end_sec": window_end,
                    "text_unit_start": text_unit_start,
                    "text_unit_end": text_unit_end,
                    "target_unit_ids": target_unit_ids,
                    "canonical_unit_ids": canonical_unit_ids,
                    "audio_path": audio_path,
                    "audio_start_sec": window_start,
                    "audio_end_sec": window_end,
                    "provenance": {
                        "source_window_id": window_id,
                        "text_unit_start": text_unit_start,
                        "text_unit_end": text_unit_end,
                    },
                })

                for u in in_window:
                    unit_rows.append({
                        "song_id": song_id,
                        "window_id": window_id,
                        "canonical_unit_id": u["canonical_unit_id"],
                        "start_sec": u["start_sec"],
                        "end_sec": u["end_sec"],
                        "text": u["text"],
                    })

                shadow_rows.append({
                    "song_id": song_id,
                    "window_id": window_id,
                    "window_index": window_index,
                    "detector_shadow": {"decision": None, "unsafe_intervals": [], "units": {}},
                })

    def _dump(name: str, rows: list[dict]) -> None:
        with (out_dir / name).open("w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

    _dump("BASELINE_WINDOW_INDEX.jsonl", idx_rows)
    _dump("BASELINE_UNITS.jsonl", unit_rows)
    _dump("BASELINE_DETECTOR_SHADOW.jsonl", shadow_rows)

    summary = {
        "population_kind": "production_raw_baseline",
        "n_baseline_windows": len(idx_rows),
        "n_baseline_units": len(unit_rows),
        "warnings": warnings,
    }
    (out_dir / "DETECTOR_BASELINE_POPULATION.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return summary


def build_baseline_identity() -> dict:
    """identity.baseline_identity() + repo HEAD."""
    bl = identity.baseline_identity()
    proc = subprocess.run(
        ["git", "-C", str(identity.REPO_ROOT), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    bl["repo_head"] = proc.stdout.strip() if proc.returncode == 0 else None
    return bl


def discover_test_demo_items(roots: list[str | Path]) -> list[dict]:
    """Recursively discover audio+same-name-txt demo items with language inference."""
    items: list[dict] = []
    for root in roots:
        root = Path(root)
        if not root.is_dir():
            continue
        for audio in sorted(root.rglob("*")):
            if not audio.is_file() or audio.suffix.lower() not in AUDIO_EXTS:
                continue
            txt = audio.with_suffix(".txt")
            if not txt.is_file():
                continue
            lang = "unknown"
            lowered = {p.lower() for p in audio.relative_to(root).parts}
            for cand in LANGUAGES:
                if cand in lowered:
                    lang = cand
                    break
            items.append({"audio": str(audio), "txt": str(txt), "lang": lang, "root": str(root)})
    return items


def run_stage(run_root: str | Path, cfg_path: str | Path) -> dict:
    """Stage entry: write 00_inventory/*.json and return a summary dict."""
    run_root = Path(run_root)
    cfg = json.loads(Path(cfg_path).read_text(encoding="utf-8"))
    out_dir = run_root / "00_inventory"
    out_dir.mkdir(parents=True, exist_ok=True)

    data_inv = build_data_inventory(run_root, cfg)
    bl_identity = build_baseline_identity()
    demo_items = discover_test_demo_items(cfg["inputs"]["test_demo_roots"])
    by_lang = Counter(i["lang"] for i in demo_items)
    by_root = Counter(i["root"] for i in demo_items)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    command = " ".join(sys.argv) or "n/a"

    def wrap(schema: str, payload: dict, inputs: dict) -> dict:
        return {
            "schema": schema,
            "inputs": {str(k): v for k, v in inputs.items()},
            "command": command,
            "generated_at_utc": now,
            "result_status": "ok",
            **payload,
        }

    docs = {
        "DATA_INVENTORY.json": wrap(SCHEMAS["data_inventory"], data_inv, data_inv["inputs"]),
        "DETECTOR_BASELINE_IDENTITY.json": wrap(SCHEMAS["baseline_identity"], bl_identity, {}),
        "TEST_DEMO_INVENTORY.json": wrap(
            SCHEMAS["test_demo_inventory"],
            {"items": demo_items, "summary": {"n_items": len(demo_items), "by_language": dict(by_lang), "by_root": dict(by_root)}},
            {},
        ),
    }

    for name, doc in docs.items():
        (out_dir / name).write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    baseline_pop = build_baseline_population(run_root, cfg)
    baseline_outputs = {name: str(out_dir / name) for name in (
        "BASELINE_WINDOW_INDEX.jsonl",
        "BASELINE_UNITS.jsonl",
        "BASELINE_DETECTOR_SHADOW.jsonl",
        "DETECTOR_BASELINE_POPULATION.json",
    )}

    return {
        "stage": "00_inventory",
        "run_root": str(run_root),
        "outputs": {**{name: str(out_dir / name) for name in docs}, **baseline_outputs},
        "result_status": "ok",
        "n_real_gt_songs": data_inv["real_gt_summary"]["n_songs"],
        "n_real_gt_units": data_inv["real_gt_summary"]["accepted_units"],
        "n_cohort_songs": data_inv["constructible_windows"]["n_songs"],
        "constructible_windows": data_inv["constructible_windows"]["constructible_windows"],
        "n_baseline_windows": baseline_pop["n_baseline_windows"],
        "n_old_requests": data_inv["existing_evidence"]["n_requests"],
        "n_demo_items": len(demo_items),
        "repo_head": bl_identity.get("repo_head"),
    }
