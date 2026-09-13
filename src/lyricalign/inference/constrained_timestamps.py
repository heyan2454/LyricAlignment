"""Constrained decoding for character timestamps: monotone, minimum-duration Viterbi.

The production path takes each character's two timestamp slots independently (`argmax`), then patches
up the resulting illegalities afterwards — upstream `_fix_timestamps` fills whole blocks with one
constant (16.28% zero-length characters on a real batch), and our targeted repair only re-spreads
those blocks.  Neither uses the fact that the *sequence* must be legal, and neither lets a later
character's uncertainty inform an earlier boundary.

This module does the global thing instead: over the model's own per-slot distributions it finds

    max  Σ_i [ log p_i^start(s_i) + log p_i^end(e_i) ]
    s.t. min_duration ≤ e_i − s_i   and   e_i ≤ s_{i+1}

with a linear-time DP.  Because the objective separates per character and the constraints couple only
through `e_i ≤ s_{i+1}`, the whole problem is a chain of cumulative maxima:

    P(s)   = max_{e ≤ s} DP_{i-1}(e)                  (prefix max, O(K))
    h(s)   = P(s) + log p_i^start(s)
    M(e)   = max_{s ≤ e − min_duration} h(s)          (cumulative max, O(K))
    DP_i(e)= M(e) + log p_i^end(e)

so a 30-character item over 5000 bins costs ~150k operations instead of a quadratic search.
"""

from __future__ import annotations

from typing import Any

import numpy as np

NEG_INF = -1e30


def slot_logprobs(logits: Any, input_ids: Any, *, timestamp_token_id: int,
                  num_classes: int = 5000) -> np.ndarray:
    """Per-character (start, end) log-probabilities over the timestamp classes.

    Returns an array of shape ``(n_characters, 2, num_classes)``; a truncated decode yields fewer
    slots and therefore fewer characters, exactly as the raw decoder treats it.
    """
    array = logits.detach().float().cpu().numpy() if hasattr(logits, "detach") else np.asarray(logits)
    ids = input_ids.detach().cpu().numpy() if hasattr(input_ids, "detach") else np.asarray(input_ids)
    if array.ndim == 3:
        array = array[0]
    if ids.ndim == 2:
        ids = ids[0]
    selected = array[ids == timestamp_token_id][:, :num_classes]
    if selected.size == 0:
        return np.zeros((0, 2, num_classes), dtype=np.float32)
    shifted = selected - selected.max(axis=1, keepdims=True)
    logp = shifted - np.log(np.exp(shifted).sum(axis=1, keepdims=True))
    pairs = (logp.shape[0] // 2) * 2
    return logp[:pairs].reshape(-1, 2, num_classes).astype(np.float32)


def viterbi_monotone(start_logp: np.ndarray, end_logp: np.ndarray, *,
                     min_duration: int = 1) -> dict[str, Any]:
    """Optimal monotone assignment of (start, end) bins to a character sequence.

    ``start_logp`` / ``end_logp`` are ``(n_characters, n_bins)`` log-probabilities.  Returns the
    chosen bins, the achieved score, and the score the independent per-slot argmax would achieve on
    the same distributions (so a caller can tell whether the constraint actually bought anything).
    """
    start_logp = np.asarray(start_logp, dtype=np.float64)
    end_logp = np.asarray(end_logp, dtype=np.float64)
    if start_logp.shape != end_logp.shape or start_logp.ndim != 2:
        raise ValueError("start and end log-probability arrays must share shape (n_characters, n_bins)")
    n_characters, n_bins = start_logp.shape
    if n_characters == 0 or n_bins == 0:
        return {"starts": [], "ends": [], "score": 0.0, "argmax_score": None, "feasible": True}
    if int(min_duration) < 1:
        raise ValueError("min_duration must be >= 1 bin")
    min_duration = int(min_duration)

    # The first character has no predecessor: the empty maximum is 0, not -inf (using -inf here
    # makes every sequence infeasible, which is how the first version of this DP failed).
    prefix_prev = np.zeros(n_bins, dtype=np.float64)            # max_{e <= s} DP_{i-1}(e)
    h_stack = np.empty((n_characters, n_bins), dtype=np.float64)
    dp_stack = np.empty((n_characters, n_bins), dtype=np.float64)
    for index in range(n_characters):
        h = prefix_prev + start_logp[index]
        h_stack[index] = h
        reachable = np.full(n_bins, NEG_INF, dtype=np.float64)
        if n_bins > min_duration:
            reachable[min_duration:] = np.maximum.accumulate(h[: n_bins - min_duration])
        dp = reachable + end_logp[index]
        dp_stack[index] = dp
        prefix_prev = np.maximum.accumulate(dp)
    if not np.isfinite(dp_stack[-1]).any() or dp_stack[-1].max() <= NEG_INF / 2:
        return {"starts": [], "ends": [], "score": None, "argmax_score": None, "feasible": False}

    ends = [0] * n_characters
    starts = [0] * n_characters
    ends[-1] = int(np.argmax(dp_stack[-1]))
    for index in range(n_characters - 1, -1, -1):
        e = ends[index]
        limit = e - min_duration
        if limit < 0:
            return {"starts": [], "ends": [], "score": None, "argmax_score": None, "feasible": False}
        starts[index] = int(np.argmax(h_stack[index][: limit + 1]))
        if index > 0:
            ends[index - 1] = int(np.argmax(dp_stack[index - 1][: starts[index] + 1]))
    score = float(sum(start_logp[i, starts[i]] + end_logp[i, ends[i]] for i in range(n_characters)))
    argmax_starts = start_logp.argmax(axis=1)
    argmax_ends = end_logp.argmax(axis=1)
    argmax_score = float(sum(start_logp[i, argmax_starts[i]] + end_logp[i, argmax_ends[i]]
                             for i in range(n_characters)))
    return {"starts": starts, "ends": ends, "score": score, "argmax_score": argmax_score,
            "feasible": True,
            # whether the *independent per-slot argmax* would already have been legal
            "argmax_legal": bool(
                all(argmax_ends[i] >= argmax_starts[i] + min_duration for i in range(n_characters))
                and all(argmax_ends[i] <= argmax_starts[i + 1] for i in range(n_characters - 1)))}


def constrained_rows(logits: Any, input_ids: Any, records: list[dict[str, Any]],
                     word_lists: list[list[str]], *, timestamp_token_id: int, segment_sec: float,
                     min_duration: int = 1) -> list[dict[str, Any]]:
    """Metric-row adapter: monotone Viterbi decode instead of independent per-slot argmax."""
    array = logits.detach().float().cpu().numpy() if hasattr(logits, "detach") else np.asarray(logits)
    ids = input_ids.detach().cpu().numpy() if hasattr(input_ids, "detach") else np.asarray(input_ids)
    batch = array.shape[0] if array.ndim == 3 else 1
    rows: list[dict[str, Any]] = []
    for sample in range(batch):
        single_logits = array[sample: sample + 1]
        single_ids = ids[sample: sample + 1]
        probabilities = slot_logprobs(single_logits, single_ids, timestamp_token_id=timestamp_token_id)
        result = viterbi_monotone(probabilities[:, 0, :], probabilities[:, 1, :], min_duration=min_duration)
        record = records[sample]
        words = word_lists[sample]
        starts = result["starts"]
        ends = result["ends"]
        for index, word in enumerate(words):
            start = starts[index] if index < len(starts) else None
            end = ends[index] if index < len(ends) else None
            rows.append({"item_id": record["item_id"],
                         "song_id": record.get("song_id", record["item_id"]),
                         "character_index": index, "normalized_character": word,
                         "start_sec": (None if start is None else float(start) * segment_sec),
                         "end_sec": (None if end is None else float(end) * segment_sec),
                         "constrained_score": (None if result["score"] is None
                                               else round(result["score"], 4))})
    return rows
