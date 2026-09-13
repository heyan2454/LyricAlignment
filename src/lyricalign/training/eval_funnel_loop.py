"""Loop-side machinery for funnelled validation and a cyclic learning rate.

Lives outside `scripts/training/run_qwen_fa_lora.py` so the trainer patch stays short:

* :class:`CyclicCosineScheduler` — anneals to zero every ``cycle_len`` steps, with a decaying peak per
  cycle, and keeps only a step counter in its state.  That removes the failure mode where restoring a
  saved HF cosine scheduler re-imports the *old* total horizon (so a stopped-then-resumed run trains at
  a learning rate shaped for a different budget).
* :func:`argmax_character_predictions` — the raw decode: the same per-slot argmax the official
  processor computes, without its monotonicity repair, which is the only way to see the model's own
  candidate quality (rounds 44-45 showed the repair flattens whole spans).
* :func:`evaluate_variants` — one forward pass, three decodes (`fixed`, `raw`, `raw+targeted`), each
  with per-song test-scale values, so a later dispute can be settled from the leaderboard alone.
* :func:`build_funnel` / :func:`run_pending_evals` — nested by-song subsets and the job runner.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable

import numpy as np

from lyricalign.analysis.monotone_repair import repair_targeted_blocks
from lyricalign.metrics.test_scale import test_scale_metrics
from lyricalign.training.eval_funnel import FunnelPlanner
from lyricalign.training.lr_schedule import cyclic_cosine_factor

DEFAULT_TOLERANCES_SEC = (0.10, 0.20, 0.25)


def atomic_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    tmp.replace(path)


class CyclicCosineScheduler:
    """Cosine-with-restarts LR scheduler whose horizon comes from config, never from a checkpoint."""

    def __init__(self, optimizer: Any, *, cycle_len: int, warmup_ratio: float = 0.05,
                 cycle_peak_decay: float = 1.0) -> None:
        if int(cycle_len) <= 1:
            raise ValueError(f"cycle_len must be > 1, got {cycle_len!r}")
        self.optimizer = optimizer
        self.cycle_len = int(cycle_len)
        self.warmup_ratio = float(warmup_ratio)
        self.cycle_peak_decay = float(cycle_peak_decay)
        self.base_lrs = [float(group.get("initial_lr", group["lr"])) for group in optimizer.param_groups]
        self.last_step = 0
        self._apply(1)

    def _apply(self, step: int) -> None:
        factor = cyclic_cosine_factor(step, cycle_len=self.cycle_len,
                                      warmup_ratio=self.warmup_ratio,
                                      cycle_peak_decay=self.cycle_peak_decay)
        for group, base in zip(self.optimizer.param_groups, self.base_lrs, strict=True):
            group["lr"] = base * factor

    def step(self) -> None:
        self.last_step += 1
        self._apply(self.last_step + 1)

    def get_last_lr(self) -> list[float]:
        return [float(group["lr"]) for group in self.optimizer.param_groups]

    def state_dict(self) -> dict[str, Any]:
        return {"last_step": self.last_step}

    def load_state_dict(self, state: dict[str, Any]) -> None:
        self.last_step = int(state.get("last_step", self.last_step))
        self._apply(self.last_step + 1)


def argmax_character_predictions(logits: Any, input_ids: Any, word_lists: list[list[str]],
                                 timestamp_token_id: int, records: list[dict[str, Any]], *,
                                 segment_sec: float) -> list[dict[str, Any]]:
    """Raw per-slot argmax timestamps (no monotonicity repair), in metric row shape."""
    pred_ids = np.asarray(logits.detach().float().argmax(dim=-1).cpu().numpy())
    ids = np.asarray(input_ids.detach().cpu().numpy() if hasattr(input_ids, "detach") else input_ids)
    rows: list[dict[str, Any]] = []
    for sample, (record, words) in enumerate(zip(records, word_lists, strict=True)):
        classes = pred_ids[sample][ids[sample] == timestamp_token_id]
        times = np.asarray(classes, dtype=float) * float(segment_sec)
        expected = 2 * len(words)
        if times.size < expected:      # a truncated decode leaves those characters missing, not guessed
            times = np.concatenate([times, np.full(expected - times.size, np.nan)])
        for index, word in enumerate(words):
            start, end = times[2 * index], times[2 * index + 1]
            rows.append({"item_id": record["item_id"],
                         "song_id": record.get("song_id", record["item_id"]),
                         "character_index": index, "normalized_character": word,
                         "start_sec": (None if not np.isfinite(start) else float(start)),
                         "end_sec": (None if not np.isfinite(end) else float(end))})
    return rows


def raw_plus_targeted_rows(raw_rows: list[dict[str, Any]], *, grid_sec: float) -> list[dict[str, Any]]:
    """Redistribute only the collapsed/inverted stretches of a raw decode (rounds 46-47 repair)."""
    by_item: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    for row in raw_rows:
        by_item[row["item_id"]].append(row)
    out: list[dict[str, Any]] = []
    for rows in by_item.values():
        rows = sorted(rows, key=lambda r: int(r["character_index"]))
        starts = np.array([float(r["start_sec"]) if r.get("start_sec") is not None else np.nan
                           for r in rows], dtype=float)
        ends = np.array([float(r["end_sec"]) if r.get("end_sec") is not None else np.nan
                         for r in rows], dtype=float)
        finite = ends[np.isfinite(ends)]
        duration = float(finite.max() + grid_sec) if finite.size else None
        fixed = repair_targeted_blocks(starts, ends, min_dur=grid_sec, duration=duration)
        for index, row in enumerate(rows):
            new = dict(row)
            new["start_sec"] = float(fixed["starts"][index])
            new["end_sec"] = float(fixed["ends"][index])
            out.append(new)
    return out


def evaluate_variants(model: Any, processor: Any, collator: Any, records: list[dict[str, Any]],
                      references: dict[str, list[dict[str, Any]]], *, device: str, dtype: Any,
                      batch_size: int, segment_sec: float,
                      tolerances: tuple[float, ...] = DEFAULT_TOLERANCES_SEC) -> dict[str, Any]:
    """One forward pass, three decodes, per-song test-scale metrics for each."""
    import torch

    from lyricalign.training.qwen_fa_runtime import move_inputs

    model.eval()
    reference = [row for record in records for row in references[record["item_id"]]]
    fixed_rows: list[dict[str, Any]] = []
    raw_rows: list[dict[str, Any]] = []
    losses: list[float] = []
    with torch.no_grad():
        for offset in range(0, len(records), int(batch_size)):
            chunk = records[offset:offset + int(batch_size)]
            inputs, words = collator(chunk)
            batch = move_inputs(inputs, device, dtype)
            output = model(**batch)
            losses.append(float(output.loss))
            decoded = processor.decode_forced_alignment(output.logits, batch["input_ids"], words,
                                                        model.config.timestamp_token_id)
            for record, items in zip(chunk, decoded, strict=True):
                for index, item in enumerate(items):
                    fixed_rows.append({"item_id": record["item_id"],
                                       "song_id": record.get("song_id", record["item_id"]),
                                       "character_index": index, "normalized_character": item["text"],
                                       "start_sec": float(item["start_time"]),
                                       "end_sec": float(item["end_time"])})
            raw_rows.extend(argmax_character_predictions(
                output.logits, batch["input_ids"], words, model.config.timestamp_token_id, chunk,
                segment_sec=segment_sec))
    variants = {"fixed": fixed_rows, "raw": raw_rows,
                "raw_targeted": raw_plus_targeted_rows(raw_rows, grid_sec=segment_sec)}
    out: dict[str, Any] = {"val_loss": round(float(np.mean(losses)), 6) if losses else None,
                           "items": len(records), "characters": len(reference), "variants": {}}
    for name, rows in variants.items():
        metric = test_scale_metrics(reference, rows, tolerances=tolerances)
        metric.pop("per_unit", None)
        out["variants"][name] = metric
    out["variants_summary"] = {name: {"macro_within_primary": v["macro_song_within_primary"],
                                       "usable_rate": v["usable_rate"],
                                       "mae_all_ms": v["mae_all_ms"],
                                       "collapse_longest_run": v["collapse_longest_run"]}
                               for name, v in out["variants"].items()}
    model.train()
    return out


def nested_subsets(records: list[dict[str, Any]], *, fractions: dict[str, float]) -> dict[str, list[dict[str, Any]]]:
    """Whole-song nested subsets (l1 ⊆ l2 ⊆ l3), so levels stay comparable and no song is split."""
    by_song: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_song[str(record.get("song_id") or record["item_id"])].append(record)
    order = sorted(by_song, key=lambda s: hashlib.sha256(s.encode()).hexdigest())
    total = len(order)
    out: dict[str, list[dict[str, Any]]] = {}
    for level, frac in fractions.items():
        keep = max(1, min(total, int(round(total * float(frac)))))
        picked: list[dict[str, Any]] = []
        for song in order[:keep]:
            picked.extend(by_song[song])
        out[level] = picked
    return out


def build_funnel(cfg: dict[str, Any], valid: list[dict[str, Any]],
                 run_dir: Path) -> tuple[FunnelPlanner, dict[str, list[dict[str, Any]]], dict[str, Any]]:
    training = cfg.get("training") or {}
    funnel_cfg = dict(training.get("eval_funnel") or {})
    planner = FunnelPlanner(l1_every=int(funnel_cfg.get("l1_every", 50)),
                            l2_max=int(funnel_cfg.get("l2_max", 16)),
                            l3_every=int(funnel_cfg.get("l3_every", 1000)),
                            l3_top_k=int(funnel_cfg.get("l3_top_k", 8)),
                            ucb_scale=float(funnel_cfg.get("ucb_scale", 1.5)),
                            l2_per_round=(int(funnel_cfg["l2_per_round"])
                                          if funnel_cfg.get("l2_per_round") else None))
    fractions = {"l1": float(funnel_cfg.get("l1_fraction", 0.25)),
                 "l2": float(funnel_cfg.get("l2_fraction", 0.5)),
                 "l3": 1.0}
    subsets = nested_subsets(valid, fractions=fractions)
    funnel_cfg["subset_items"] = {level: len(rows) for level, rows in subsets.items()}
    funnel_cfg["selection"] = {"variant": str(funnel_cfg.get("selection_variant", "fixed")),
                              "metric": str(funnel_cfg.get("selection_metric", "macro_song_within_primary"))}
    return planner, subsets, funnel_cfg


def _read_selection(variant_block: dict[str, Any], selection: dict[str, str]) -> tuple[float, float | None]:
    value = float(variant_block[selection["metric"]])
    se_key = "macro_song_se_primary"
    se = variant_block.get(se_key)
    return value, (float(se) if isinstance(se, (int, float)) and se > 0 else None)


def run_pending_evals(planner: FunnelPlanner, *, step: int, model: Any, processor: Any,
                      collator: Any, subsets: dict[str, list[dict[str, Any]]],
                      references: dict[str, list[dict[str, Any]]], device: str, dtype: Any,
                      batch_size: int, segment_sec: float, selection: dict[str, str],
                      run_dir: Path,
                      log: Callable[[dict[str, Any]], None] | None = None) -> list[dict[str, Any]]:
    """Run whatever the funnel asks for at this step (each candidate once per level) and persist it."""
    done: list[dict[str, Any]] = []
    for level, candidate in planner.pending(step):
        records = subsets.get(level) or subsets["l3"]
        result = evaluate_variants(model, processor, collator, records, references, device=device,
                                   dtype=dtype, batch_size=batch_size, segment_sec=segment_sec)
        block = result["variants"][selection["variant"]]
        value, se = _read_selection(block, selection)
        planner.record(candidate, level, value, se=se, at_step=step)
        entry = {"step_now": int(step), "evaluated_step": int(candidate), "level": level,
                 "selection": selection, "value": round(value, 4),
                 "se": (round(se, 4) if se else None), "val_loss": result["val_loss"],
                 "variants": result["variants_summary"]}
        done.append(entry)
        if log:
            log({"funnel_eval": entry})
    if done:
        atomic_json(run_dir / "LEADERBOARD.json", planner.status(step))
    return done


def early_stop_decision(l3_rounds: list[dict[str, Any]], *, patience_cycles: int = 2,
                        min_gain_se: float = 1.0) -> dict[str, Any]:
    """Stop after consecutive full-set rounds that fail to beat the incumbent by more than noise.

    `l3_rounds` entries carry ``best`` (macro value of the best candidate at that round) and
    optionally ``best_se``; a round counts as progress only when it clears `best + min_gain_se * se`.
    """
    best: float | None = None
    stale = 0
    for row in l3_rounds:
        value = row.get("best")
        if value is None:
            continue
        se = float(row.get("best_se") or 0.0)
        if best is None or value > best + min_gain_se * se:
            best = value if best is None else max(best, value)
            stale = 0
        else:
            best = max(best, value)
            stale += 1
    return {"stop": bool(best is not None and stale >= int(patience_cycles)),
            "stale_rounds": int(stale), "best": best,
            "patience_cycles": int(patience_cycles), "min_gain_se": float(min_gain_se)}
