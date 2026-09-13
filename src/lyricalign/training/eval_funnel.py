"""The validation funnel: cheap screen for everyone, expensive evaluation for few, each level once.

Dense validation on a big run is only affordable if two rules hold, and this module is the
bookkeeping for exactly those rules:

* **evaluate nothing that was never saved** — candidates appear on the checkpoint cadence
  (`l1_every`), so the funnel never pays for weights that cannot be selected anyway;
* **each candidate is evaluated at a level at most once** — promotion happens when a candidate
  becomes UCB-eligible, not by re-scoring the whole layer every round, which is what makes the cost
  of "top-8 of 80" roughly 16 evaluations instead of 8 x 16.

Screening uses an upper confidence bound (`value + ucb_scale * se`) rather than a raw top-N, because
the smallest subset is only a handful of songs: a candidate with a mediocre mean but a large standard
error may well be the best model, and hard pruning would throw it away on subset noise.  The final
pick is delegated to `metrics.scale_metrics.select_with_one_se`.
"""

from __future__ import annotations

from typing import Any, Iterable

LEVELS = ("l1", "l2", "l3")


class FunnelPlanner:
    """Plan and record funnel validations for checkpoint selection.

    Parameters
    ----------
    l1_every:      candidate cadence; a candidate enters L1 once, at/after this interval.
    l2_max:        size of the **finalist set**: only this many candidates are meant to hold a
                   medium-subset score.  Admission is quality-ranked, not arrival-ordered — once the
                   set is full, a newcomer is evaluated only when it looks at least as good as the
                   *weakest finalist* (UCB on L1), so a late-but-better checkpoint is never locked
                   out by earlier arrivals.
    l2_budget:     total number of medium evaluations allowed (defaults to `l2_max`, i.e. no churn).
                   Displacing a finalist costs one extra evaluation, so this is what actually bounds
                   the cost of keep-best admission; `2 * l2_max` is a reasonable setting.
    l2_per_round:  if set, at most this many *new* L2 admissions per `l3_every` round, still bounded
                   by `l2_budget` in total.  Smooths the load instead of admitting a burst in round 1.
                   Requires `record(..., at_step=)` to be supplied by the caller.
    l3_every:      L3 may only be queued on multiples of this step (aligned with cycle ends).
    l3_top_k:      how many *new* candidates one L3 round may admit.  A candidate is never
                   evaluated at the same level twice, so over a long run the number of full-set
                   evaluations grows by at most `l3_top_k` per promotion round; with one round per
                   `l3_every` steps that bounds the expensive evaluations by
                   `ceil(steps / l3_every) * l3_top_k`, which is what the cost plan assumed.
    ucb_scale:     how generous promotion is; 0.0 degenerates to plain top-N.
    """

    def __init__(self, *, l1_every: int = 50, l2_max: int = 16, l3_every: int = 1000,
                 l3_top_k: int = 8, ucb_scale: float = 1.5, l2_ucb_scale: float | None = None,
                 l2_per_round: int | None = None, l2_budget: int | None = None) -> None:
        for name, value in (("l1_every", l1_every), ("l2_max", l2_max), ("l3_every", l3_every),
                            ("l3_top_k", l3_top_k)):
            if int(value) < 1:
                raise ValueError(f"{name} must be >= 1, got {value!r}")
        if l2_per_round is not None and int(l2_per_round) < 1:
            raise ValueError(f"l2_per_round must be >= 1 or None, got {l2_per_round!r}")
        if l2_budget is not None and int(l2_budget) < 1:
            raise ValueError(f"l2_budget must be >= 1 or None, got {l2_budget!r}")
        if float(ucb_scale) < 0:
            raise ValueError("ucb_scale must be >= 0")
        self.l1_every = int(l1_every)
        self.l2_max = int(l2_max)
        self.l3_every = int(l3_every)
        self.l3_top_k = int(l3_top_k)
        self.l2_per_round = (int(l2_per_round) if l2_per_round is not None else None)
        self.l2_budget = (int(l2_budget) if l2_budget is not None else None)
        self.ucb_scale = float(ucb_scale)
        self.l2_ucb_scale = float(l2_ucb_scale) if l2_ucb_scale is not None else float(ucb_scale)
        self.candidates: dict[int, dict[str, dict[str, float]]] = {}
        self.registered: set[int] = set()

    # ---- registration -------------------------------------------------------------
    def register(self, step: int) -> bool:
        """Record a saved checkpoint as a candidate.  Returns True when newly registered."""
        step = int(step)
        if step <= 0 or step % self.l1_every != 0:
            return False
        if step in self.registered:
            return False
        self.registered.add(step)
        self.candidates[step] = {}
        return True

    def register_many(self, steps: Iterable[int]) -> int:
        return sum(1 for s in steps if self.register(s))

    # ---- results -------------------------------------------------------------------
    def record(self, step: int, level: str, value: float, *, se: float | None = None,
               at_step: int | None = None) -> None:
        if level not in LEVELS:
            raise ValueError(f"unknown funnel level {level!r}")
        step = int(step)
        if step not in self.candidates:
            self.register(step)
        entry: dict[str, Any] = {"value": float(value),
                                   "se": (float(se) if se is not None and se > 0 else 0.0)}
        if at_step is not None:
            entry["at_step"] = int(at_step)
            entry["round"] = int(at_step) // self.l3_every
        self.candidates[step][level] = entry

    def _best(self, level: str) -> tuple[int, float, float] | None:
        scored = [(s, r[level]["value"], r[level]["se"]) for s, r in self.candidates.items()
                  if level in r]
        if not scored:
            return None
        return max(scored, key=lambda row: row[1])

    def best(self, level: str) -> tuple[int, float, float] | None:
        """Public (step, value, se) of the best candidate at `level`, or None if unscored."""
        if level not in LEVELS:
            raise ValueError(f"unknown funnel level {level!r}")
        return self._best(level)

    @staticmethod
    def _ucb(entry: dict[str, float], scale: float) -> float:
        return entry["value"] + scale * entry["se"]

    # ---- planning ------------------------------------------------------------------
    def pending(self, step_now: int) -> list[tuple[str, int]]:
        """Jobs to run right now, in cost order: cheapest first, and never a repeated level."""
        jobs: list[tuple[str, int]] = []
        for step in sorted(self.candidates):
            if "l1" not in self.candidates[step]:
                jobs.append(("l1", step))
        best_l1 = self._best("l1")
        if best_l1 is not None:
            threshold = best_l1[1] + self.ucb_scale * best_l1[2]
            l1_scored = [s for s, r in self.candidates.items() if "l1" in r]
            ranked = sorted(l1_scored, key=lambda s: self._ucb(self.candidates[s]["l1"], self.ucb_scale),
                            reverse=True)
            already_l2 = {s for s, r in self.candidates.items() if "l2" in r}
            spent = len(already_l2)
            budget = self.l2_max if self.l2_budget is None else self.l2_budget
            capacity = max(0, budget - spent)
            if self.l2_per_round is not None:
                round_index = int(step_now) // self.l3_every
                admitted = sum(1 for s, r in self.candidates.items()
                               if "l2" in r and r["l2"].get("round") == round_index)
                capacity = min(capacity, max(0, self.l2_per_round - admitted))
            # Keep-best (heap) admission: once the finalist set is full, a challenger is worth a
            # medium evaluation only if it looks at least as good as the *weakest finalist* — that is
            # what stops a late-but-better checkpoint from being locked out by earlier arrivals.
            displace_floor: float | None = None
            if spent >= self.l2_max:
                weakest_step = min(already_l2, key=lambda s: self.candidates[s]["l2"]["value"])
                weakest_l1 = self.candidates[weakest_step].get("l1")
                if weakest_l1 is not None:
                    displace_floor = self._ucb(weakest_l1, self.ucb_scale)
            for step in ranked:
                if capacity <= 0:
                    break
                entry = self.candidates[step]["l1"]
                if step in already_l2:
                    continue
                score = self._ucb(entry, self.ucb_scale)
                if displace_floor is not None and score < displace_floor:
                    break  # `ranked` is descending, so nothing further can displace either
                # promote on UCB overlap, but always keep the raw leader in play
                if score >= threshold or step == best_l1[0]:
                    jobs.append(("l2", step))
                    capacity -= 1
        if int(step_now) > 0 and int(step_now) % self.l3_every == 0:
            best_l2 = self._best("l2") or self._best("l1")
            if best_l2 is not None:
                base_level = "l2" if "l2" in self.candidates[best_l2[0]] else "l1"
                pool = [s for s, r in self.candidates.items() if base_level in r]
                ranked = sorted(pool, key=lambda s: self._ucb(self.candidates[s][base_level],
                                                             self.l2_ucb_scale), reverse=True)
                threshold = best_l2[1] + self.l2_ucb_scale * best_l2[2]
                already_l3 = {s for s, r in self.candidates.items() if "l3" in r}
                # at most l3_top_k *new* full-set evaluations per round; a candidate is never
                # re-evaluated at the same level, so this bounds the expensive work by
                # ceil(steps / l3_every) * l3_top_k.
                slots = max(0, self.l3_top_k)
                for step in ranked:
                    if slots <= 0:
                        break
                    if step in already_l3:
                        continue
                    if self._ucb(self.candidates[step][base_level], self.l2_ucb_scale) >= threshold \
                            or step == best_l2[0]:
                        jobs.append(("l3", step))
                        slots -= 1
        return jobs

    # ---- output --------------------------------------------------------------------
    def leaderboard(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for step in sorted(self.candidates):
            entry = self.candidates[step]
            row: dict[str, Any] = {"step": step}
            for level in LEVELS:
                if level in entry:
                    row[f"{level}_value"] = round(entry[level]["value"], 4)
                    row[f"{level}_se"] = round(entry[level]["se"], 4)
            rows.append(row)
        return rows

    def pick(self) -> dict[str, Any]:
        """Final selection: best available level, one-standard-error rule, earliest such step."""
        from lyricalign.metrics.scale_metrics import select_with_one_se

        for level in reversed(LEVELS):  # l3 first, then l2, then l1
            rows = [{"step": s, "score": r[level]["value"], "se": r[level]["se"]}
                    for s, r in self.candidates.items() if level in r]
            if rows:
                chosen = select_with_one_se(
                    [{"step": row["step"], "score": row["score"],
                      "macro_song_se_primary": row["se"]} for row in rows],
                    score_key="score", se_key="macro_song_se_primary", higher_is_better=True)
                chosen["selected_from_level"] = level
                chosen["candidates_at_level"] = len(rows)
                return chosen
        return {"selected_step": None, "reason": "no evaluations recorded yet"}

    def status(self, step_now: int | None = None) -> dict[str, Any]:
        out: dict[str, Any] = {
            "candidates": len(self.candidates),
            "scored": {level: sum(1 for r in self.candidates.values() if level in r)
                       for level in LEVELS},
            "params": {"l1_every": self.l1_every, "l2_max": self.l2_max,
                       "l2_per_round": self.l2_per_round, "l2_budget": self.l2_budget,
                       "l3_every": self.l3_every, "l3_top_k": self.l3_top_k,
                       "ucb_scale": self.ucb_scale, "l2_ucb_scale": self.l2_ucb_scale},
            "leaderboard": self.leaderboard(),
            "pick": self.pick(),
        }
        if step_now is not None:
            out["pending"] = [{"level": level, "step": step}
                              for level, step in self.pending(int(step_now))]
        return out


def disk_mode(free_gb: float, *, floor_gb: float = 20.0) -> str:
    """`full` keeps optimizer state (resumable); `weights_only` keeps only the deliverable weights.

    Storage, not compute, is what a long unattended run can exhaust: a full checkpoint here is 50 MB
    while the weights alone are 17.6 MB, so dropping optimizer state near the floor keeps the run
    alive and the evaluation pipeline identical.
    """
    if float(free_gb) < float(floor_gb):
        return "weights_only"
    return "full"
