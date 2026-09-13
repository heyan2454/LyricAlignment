#!/usr/bin/env python3
"""Post-hoc funnel top-up: re-run the frozen validation protocol over an explicit candidate list.

Why this exists
---------------
The in-training funnel (`lyricalign.training.eval_funnel`) keeps `l2_max` as a *total* budget with
first-come-first-served admission.  In the first from-official run that budget was consumed by
steps <= 900, so every later checkpoint stayed at L1, no new L3 job was ever produced, and the
early-stop rule could never fire.  The live run cannot be patched (its Python process already
holds the old code), so the authoritative selection for that run is produced here, after the fact,
from the saved checkpoints under the *identical* metric/variant/tolerances.

It can also evaluate foreign checkpoints (for example the previous `r2` run) under the same
protocol, which is what makes a like-for-like "did the retrain help?" comparison possible.

Examples
--------
    # plan only, no model loading
    PYTHONPATH=src python scripts/training/run_funnel_topup.py --run-dir <run> --dry-run

    # check that every candidate checkpoint loads into a freshly built r2-stage model (CPU)
    PYTHONPATH=src python scripts/training/run_funnel_topup.py --run-dir <run> --verify-weights

    # real top-up: promote the 1-SE leaders to L2, then the L2 winners to L3
    PYTHONPATH=src python scripts/training/run_funnel_topup.py --run-dir <run> \
        --levels l2,l3 --top-k 8 --l3-top-k 3 \
        --extra old-r2-750=/home/hyan/Data/lyricalign/runs/<old>/checkpoints/step-000750
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from lyricalign.training.eval_funnel_loop import atomic_json, evaluate_variants, nested_subsets
from lyricalign.training.qwen_fa_model import apply_audio_lora, freeze_all, unfreeze_projector
from lyricalign.training.qwen_fa_runtime import QwenFABatchCollator, read_jsonl

VARIANTS = ("fixed", "raw", "raw_targeted")
DEFAULT_TOLERANCES_SEC = (0.10, 0.20, 0.25)


# --------------------------------------------------------------------------------------- helpers
def sha256_strings(values: list[str]) -> str:
    """NUL-separated, identical to `run_qwen_fa_lora.sha256_strings` (the identity check depends on it)."""
    digest = hashlib.sha256()
    for value in values:
        digest.update(str(value).encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def item_sample(rows: list[dict], count: int, seed: int) -> list[dict]:
    """Byte-for-byte the selection used by `run_qwen_fa_lora.py` (kept in sync deliberately)."""
    if count <= 0 or count >= len(rows):
        return list(rows)
    ordered = sorted(rows, key=lambda row: hashlib.sha256(f"{seed}:{row['item_id']}".encode()).hexdigest())
    return ordered[:count]


def load_valid(cfg: dict[str, Any], identity: dict[str, Any], stage: str) -> tuple[list[dict], dict[str, list[dict]]]:
    """Rebuild the run's validation split and refuse to continue if it is not the same one."""
    labels = read_jsonl(Path(cfg["data"]["labels"]))
    characters = read_jsonl(Path(cfg["data"]["characters"]))
    references: dict[str, list[dict]] = {}
    for row in characters:
        references.setdefault(row["item_id"], []).append(row)
    available_valid = [row for row in labels if row["split"] == "validation"]
    limit = int((cfg["stages"].get(stage) or {}).get("validation_items", 0))
    valid = item_sample(available_valid, limit, int(cfg["training"]["seed"]))
    digest = sha256_strings([str(row["item_id"]) for row in valid])
    expected = identity.get("selected_validation_item_ids_sha256")
    if expected and digest != expected:
        raise SystemExit(f"validation identity mismatch: rebuilt {digest[:12]} != run identity "
                         f"{str(expected)[:12]}; refusing to write incomparable numbers")
    return valid, references


def rows_from_jsonl(path: Path, level: str, selection: dict[str, str]) -> dict[int, dict[str, Any]]:
    """Latest per-step `level` record, ranked on the frozen selection variant.

    `funnel_evals.jsonl` stores the *summary* block, which spells the primary tolerance metric
    `macro_within_primary` while the full block spells it `macro_song_within_primary`.
    """
    summary_key = {"macro_song_within_primary": "macro_within_primary"}.get(selection["metric"],
                                                                           selection["metric"])
    out: dict[int, dict[str, Any]] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = (json.loads(line) or {}).get("funnel_eval")
        except json.JSONDecodeError:  # a partially flushed trailing line must not kill the analysis
            continue
        if not record or record.get("level") != level:
            continue
        summary = (record.get("variants") or {}).get(selection["variant"]) or {}
        value = summary.get(summary_key)
        if value is None:
            continue
        se = record.get("se") if selection["variant"] == record.get("selection", {}).get("variant") else None
        out[int(record["evaluated_step"])] = {"step": int(record["evaluated_step"]), "value": float(value),
                                              "se": (float(se) if isinstance(se, (int, float)) else 0.0)}
    return out


def one_se_shortlist(rows: list[dict[str, Any]], *, top_k: int, se_scale: float,
                     exclude: set[int] | None = None) -> list[dict[str, Any]]:
    """Highest scores first, widened to everything within `se_scale` SE of the leader, capped at k."""
    exclude = exclude or set()
    pool = [row for row in rows if row["step"] not in exclude]
    if not pool:
        return []
    leader = max(pool, key=lambda row: row["value"])
    floor = leader["value"] - se_scale * float(leader.get("se") or 0.0)
    eligible = [row for row in pool if row["value"] >= floor]
    eligible.sort(key=lambda row: (-row["value"], row["step"]))
    return eligible[: max(1, int(top_k))]


def next_level_shortlist(*, current_records: dict[int, dict[str, Any]], round_results: list[dict[str, Any]],
                         done_next: set[int], selection: dict[str, str], cap: int,
                         se_scale: float) -> list[dict[str, Any]]:
    """Merge historical records at the level just run with the fresh ones, minus what is already done.

    Foreign (`source != "run"`) blocks are a comparison baseline only: their step numbers collide
    with the run's own and would be loaded from the wrong checkpoint directory.
    """
    pool = dict(current_records)
    for block in round_results:
        if block["source"] != "run":
            continue
        metric = block["variants"][selection["variant"]]
        pool[int(block["step"])] = {"step": int(block["step"]),
                                    "value": float(metric[selection["metric"]]),
                                    "se": float(metric.get("macro_song_se_primary") or 0.0)}
    return one_se_shortlist(list(pool.values()), top_k=cap, se_scale=se_scale, exclude=done_next)


# --------------------------------------------------------------------------------------- model io
def build_stage_model(cfg: dict[str, Any], stage: str, device: str, local_files_only: bool) -> tuple[Any, Any]:
    import torch
    from transformers import AutoModelForTokenClassification, AutoProcessor

    dtype = getattr(torch, cfg["training"].get("dtype", "bfloat16"))
    model_cfg = cfg["model"]
    cache_dir = os.environ.get("HF_HUB_CACHE")
    load_kwargs: dict[str, Any] = {"revision": model_cfg["revision"], "local_files_only": local_files_only}
    if cache_dir:
        load_kwargs["cache_dir"] = cache_dir
    processor = AutoProcessor.from_pretrained(model_cfg["id"], **load_kwargs)
    model = AutoModelForTokenClassification.from_pretrained(
        model_cfg["id"], dtype=cfg["training"].get("dtype", "bfloat16"), **load_kwargs).to(device)
    freeze_all(model)
    if stage in {"r1", "r2", "r3"}:
        unfreeze_projector(model)
    if stage in {"r2", "r3"}:
        model, _targets = apply_audio_lora(model, scope="top_half" if stage == "r2" else "all")
        for name, parameter in model.named_parameters():
            if "multi_modal_projector" in name:
                parameter.requires_grad = True
    return model, processor


def load_weights(path: Path, model: Any) -> int:
    """Copy the checkpoint's trainable tensors (projector + LoRA) into a freshly built model."""
    import torch

    state = torch.load(path / "trainer_state.pt", map_location="cpu", weights_only=False)
    current = dict(model.named_parameters())
    trainable = state["trainable_state"]
    if not trainable:
        raise SystemExit(f"{path}: empty trainable_state")
    missing = sorted(set(trainable) - set(current))
    if missing:
        raise SystemExit(f"{path}: not loadable into a {len(current)}-parameter model; "
                         f"first missing names: {missing[:3]}")
    with torch.no_grad():
        for name, value in trainable.items():
            target = current[name]
            target.data.copy_(value.to(target.device, target.dtype))
    return int(state["step"])


# ------------------------------------------------------------------------------------------- main
def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--config", type=Path, help="defaults to <run-dir>/config.yaml")
    parser.add_argument("--stage", default="r2")
    parser.add_argument("--levels", default="l2", help="comma list, cheapest first; l3 uses the L2 winners")
    parser.add_argument("--top-k", type=int, default=8, help="max candidates admitted to the first level")
    parser.add_argument("--l3-top-k", type=int, default=3)
    parser.add_argument("--se-scale", type=float, default=1.0, help="1-SE widening when shortlisting")
    parser.add_argument("--rank-variant", default=None,
                        help="variant used for ranking (default: the frozen selection variant)")
    parser.add_argument("--extra", action="append", default=[],
                        help="foreign checkpoint as label=<checkpoint dir>; evaluated at the first level")
    parser.add_argument("--out", type=Path, default=None, help="defaults to <run-dir>/TOPUP.json")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--max-items", type=int, default=0, help="debug: cap the subset size")
    parser.add_argument("--local-files-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="print the plan and exit (no model)")
    parser.add_argument("--verify-weights", action="store_true",
                        help="build the model on the chosen device and check every checkpoint loads")
    args = parser.parse_args()

    run_dir = args.run_dir
    config_path = args.config or (run_dir / "config.yaml")
    cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    funnel_cfg = dict((cfg.get("training") or {}).get("eval_funnel") or {})
    selection = {"variant": args.rank_variant or str(funnel_cfg.get("selection_variant", "fixed")),
                 "metric": str(funnel_cfg.get("selection_metric", "macro_song_within_primary"))}
    identity_path = run_dir / "resolved_dataset_identity.json"
    identity = json.loads(identity_path.read_text(encoding="utf-8")) if identity_path.exists() else {}

    valid, references = load_valid(cfg, identity, args.stage)
    fractions = {"l1": float(funnel_cfg.get("l1_fraction", 0.25)),
                 "l2": float(funnel_cfg.get("l2_fraction", 0.5)), "l3": 1.0}
    subsets = nested_subsets(valid, fractions=fractions)
    levels = [level.strip() for level in args.levels.split(",") if level.strip()]
    for level in levels:
        if level not in {"l1", "l2", "l3"}:
            raise SystemExit(f"unknown level {level!r}")
    if args.max_items:
        subsets = {level: rows[: args.max_items] for level, rows in subsets.items()}

    evals_path = run_dir / "funnel_evals.jsonl"
    extras: list[tuple[str, Path]] = []
    for spec in args.extra:
        if "=" not in spec:
            raise SystemExit(f"--extra needs label=<checkpoint dir>, got {spec!r}")
        label, path = spec.split("=", 1)
        extras.append((label, Path(path)))

    planned: list[dict[str, Any]] = []
    first_level = levels[0]
    scored_at_first = set(rows_from_jsonl(evals_path, first_level, selection))
    shortlist = one_se_shortlist(list(rows_from_jsonl(evals_path, "l1", selection).values()),
                                top_k=args.top_k, se_scale=args.se_scale, exclude=scored_at_first)
    planned.extend({"level": first_level, "label": f"step-{row['step']:06d}", "step": row["step"],
                    "l1_value": row["value"], "source": "run"} for row in shortlist)
    planned.extend({"level": first_level, "label": label, "step": None, "l1_value": None,
                    "source": str(path)} for label, path in extras)

    plan = {"run_dir": str(run_dir), "identity": {"validation_items": len(valid),
                                                  "validation_sha256": identity.get("selected_validation_item_ids_sha256")},
            "selection": selection, "levels": levels,
            "subset_items": {level: len(rows) for level, rows in subsets.items()},
            "scored": {level: len(rows_from_jsonl(evals_path, level, selection)) for level in ("l1", "l2", "l3")},
            "planned": planned}
    if args.dry_run:
        print(json.dumps(plan, indent=2, ensure_ascii=False))
        return

    if args.verify_weights:
        return verify_weights(cfg, args, planned)

    out_path = args.out or (run_dir / "TOPUP.json")
    log_path = run_dir / "topup_evals.jsonl"
    started = time.time()
    model, processor = build_stage_model(cfg, args.stage, args.device, args.local_files_only or
                                         os.environ.get("HF_HUB_OFFLINE", "").lower() in {"1", "true", "yes", "on"})
    collator = QwenFABatchCollator(processor, audio_root=Path(cfg["data"]["audio_root"]),
                                   language=cfg["data"]["language"],
                                   timestamp_token_id=model.config.timestamp_token_id)
    segment_sec = float(cfg["training"].get("timestamp_segment_sec", 0.08))

    def evaluate_candidate(level: str, label: str, path: Path, step: int | None) -> dict[str, Any]:
        import torch

        loaded_step = load_weights(path, model)
        dtype = getattr(torch, cfg["training"].get("dtype", "bfloat16"))
        outcome = evaluate_variants(model, processor, collator, subsets[level], references,
                                    device=args.device, dtype=dtype,
                                    batch_size=args.batch_size, segment_sec=segment_sec,
                                    tolerances=DEFAULT_TOLERANCES_SEC)
        block = {"level": level, "label": label, "step": step if step is not None else loaded_step,
                 "checkpoint": str(path), "subset_items": len(subsets[level]),
                 # batch size is part of the measurement identity: bf16 padding changes the argmax at
                 # near-ties (observed: old-r2/750 at L2 = 0.9555 with batch 4 vs 0.9561 with batch 6)
                 "eval_batch_size": int(args.batch_size),
                 "source": ("run" if run_dir in path.parents else "foreign"),
                 "elapsed_sec": round(time.time() - started, 1),
                 "variants": outcome["variants"], "variants_summary": outcome["variants_summary"],
                 "val_loss": outcome["val_loss"]}
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"topup_eval": block}, ensure_ascii=False) + "\n")
        return block

    def path_for(entry: dict[str, Any]) -> Path:
        if entry["source"] == "run":
            return run_dir / "checkpoints" / f"step-{int(entry['step']):06d}"
        return Path(entry["source"])

    completed: list[dict[str, Any]] = []
    current = planned
    for level in levels:
        round_results: list[dict[str, Any]] = []
        for entry in current:
            block = evaluate_candidate(level, entry["label"], path_for(entry), entry.get("step"))
            round_results.append(block)
            mark = block["variants_summary"][selection["variant"]]["macro_within_primary"]
            print(f"[{level}] {entry['label']} -> {selection['variant']} {mark:.4f} "
                  f"({block['elapsed_sec']:.0f}s)", flush=True)
        completed.extend(round_results)
        if level == levels[-1]:
            break
        # promote the leaders of this level into the next (cheapest next level is the natural one)
        next_level = levels[levels.index(level) + 1]
        # never re-run a level a candidate already has (historical records included)
        done_next = set(rows_from_jsonl(evals_path, next_level, selection))
        done_next.update(int(block["step"]) for block in completed if block["level"] == next_level)
        cap = args.top_k if next_level == "l2" else args.l3_top_k
        current = [{"level": next_level, "label": f"step-{row['step']:06d}", "step": row["step"],
                    "l1_value": None, "source": "run"}
                   for row in next_level_shortlist(current_records=rows_from_jsonl(evals_path, level, selection),
                                                   round_results=round_results, done_next=done_next,
                                                   selection=selection, cap=cap, se_scale=args.se_scale)]
        print(f"[plan] {next_level}: {[entry['label'] for entry in current]}", flush=True)

    ranked: dict[str, Any] = {}
    for variant in VARIANTS:
        rows = [{"step": block["step"], "score": block["variants"][variant][selection["metric"]],
                 "macro_song_se_primary": block["variants"][variant].get("macro_song_se_primary") or 0.0,
                 "label": block["label"], "level": block["level"]}
                for block in completed
                if block["level"] == levels[-1] and block["source"] == "run"]
        if rows:
            from lyricalign.metrics.scale_metrics import select_with_one_se
            chosen = select_with_one_se(rows, score_key="score", se_key="macro_song_se_primary",
                                        higher_is_better=True)
            ranked[variant] = chosen
    payload = {"schema_version": 1, "run_dir": str(run_dir), "config": str(config_path),
               "selection": selection, "levels": levels, "plan": plan, "extras": [label for label, _ in extras],
               "evaluated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "results": completed,
               "pick_by_variant": ranked}
    atomic_json(out_path, payload)
    print(json.dumps({"written": str(out_path), "pick_by_variant": ranked}, indent=2, ensure_ascii=False))


def verify_weights(cfg: dict[str, Any], args: argparse.Namespace, planned: list[dict[str, Any]]) -> None:
    device = "cpu" if args.device == "cuda" else args.device
    model, _processor = build_stage_model(cfg, args.stage, device, args.local_files_only or
                                          os.environ.get("HF_HUB_OFFLINE", "").lower() in {"1", "true", "yes", "on"})
    report: list[dict[str, Any]] = []
    for entry in planned:
        path = (args.run_dir / "checkpoints" / f"step-{int(entry['step']):06d}") if entry["source"] == "run" \
            else Path(entry["source"])
        try:
            step = load_weights(path, model)
            ok, error = True, None
        except SystemExit as exc:  # loud incompatibility, reported not raised
            step, ok, error = None, False, str(exc)
        report.append({"label": entry["label"], "checkpoint": str(path), "loadable": ok,
                       "loaded_step": step, "error": error})
        print(f"{entry['label']}: loadable={ok} {error or ''}", flush=True)
    atomic_json(args.run_dir / "TOPUP_WEIGHT_CHECK.json", {"stage": args.stage, "checks": report})
    if not all(row["loadable"] for row in report):
        raise SystemExit("at least one checkpoint is not loadable; see TOPUP_WEIGHT_CHECK.json")


if __name__ == "__main__":
    main()
