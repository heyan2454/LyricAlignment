"""Per-character loss weighting for timestamp slots.

Why this exists: item-level oversampling saturates (replicating items also replicates their short
characters, so the long-character exposure share tops out at ×2.58 — see
`docs/status/20260914_concat_arm_prereg.md` §3g).  The knob that does not dilute is the loss: weight
the two slots of a character by how atypical its labelled duration is.

The implementation is deliberately a *reimplementation with a check*: with `weight == 1` it must
reproduce the model's own mean cross-entropy exactly, because the alternative — a subtly different
normalisation — would make every arm-to-arm comparison silently invalid.
"""

from __future__ import annotations

from typing import Any

import torch

IGNORE_INDEX = -100


def slot_weights(labels: Any, *, step_sec: float, long_sec: float, weight: float) -> Any:
    """Weight 1.0 everywhere except the two slots of characters whose label duration ≥ long_sec.

    `labels` holds IGNORE_INDEX except at timestamp slots, which come in adjacent (start, end) pairs
    in character order, so the duration of a character is read straight off the label ids.
    """
    weights = torch.ones_like(labels, dtype=torch.float32)
    valid_rows = (labels != IGNORE_INDEX).any(dim=1) if labels.dim() == 2 else None
    for row in range(labels.shape[0]):
        positions = (labels[row] != IGNORE_INDEX).nonzero(as_tuple=False).flatten()
        ids = labels[row, positions]
        pairs = int(positions.numel() // 2)
        for index in range(pairs):
            start = int(ids[2 * index])
            end = int(ids[2 * index + 1])
            duration = (end - start) * step_sec
            if duration >= long_sec:
                weights[row, positions[2 * index]] = weight
                weights[row, positions[2 * index + 1]] = weight
    del valid_rows
    return weights


def weighted_timestamp_loss(logits: Any, labels: Any, *, step_sec: float, long_sec: float,
                            weight: float) -> Any:
    """Weighted mean cross-entropy over supervised slots.

    `weight == 1.0` reduces to the unweighted mean over valid slots, which is asserted by tests
    against both `F.cross_entropy` and the HF token-classification loss.
    """
    if weight <= 0:
        raise ValueError(f"loss weight must be positive, got {weight}")
    per_token = torch.nn.functional.cross_entropy(
        logits.reshape(-1, logits.shape[-1]).float(), labels.reshape(-1),
        ignore_index=IGNORE_INDEX, reduction="none").reshape(labels.shape)
    weights = slot_weights(labels, step_sec=step_sec, long_sec=long_sec, weight=weight).to(per_token.device)
    supervised = (labels != IGNORE_INDEX).float().to(per_token.device)
    denominator = (weights * supervised).sum()
    if float(denominator) <= 0:
        return per_token.sum() * 0.0
    return (per_token * weights * supervised).sum() / denominator
