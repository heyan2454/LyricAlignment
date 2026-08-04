"""Tensor-level sparse timestamp-slot construction for Qwen forced alignment."""
from __future__ import annotations
from typing import Any, Sequence


def retain_timestamp_slots(inputs: Any, *, timestamp_token_id: int, unit_indices: Sequence[int], total_units: int) -> tuple[Any, tuple[int, ...]]:
    """Remove marker pairs of non-target units but retain the surrounding text/audio."""
    import torch
    chosen = tuple(int(i) for i in unit_indices)
    if not chosen or len(set(chosen)) != len(chosen) or any(i < 0 or i >= total_units for i in chosen):
        raise ValueError("timestamp slot indices must be unique, non-empty unit indices in range")
    ids = inputs["input_ids"]
    positions = (ids[0] == timestamp_token_id).nonzero(as_tuple=False).flatten()
    if len(positions) != 2 * total_units:
        raise RuntimeError(f"expected {2 * total_units} timestamp markers, got {len(positions)}")
    keep = torch.ones(ids.shape[-1], dtype=torch.bool, device=ids.device)
    selected = {2 * i + j for i in chosen for j in (0, 1)}
    for index, position in enumerate(positions.tolist()):
        if index not in selected:
            keep[position] = False
    result = inputs.copy()
    seq = ids.shape[-1]
    for key, value in inputs.items():
        if isinstance(value, torch.Tensor) and value.ndim >= 2 and value.shape[0] == 1 and value.shape[-1] == seq:
            result[key] = value[..., keep]
    return result, chosen
