"""Cross-family no-GT consensus, grouped at (song, region, canonical unit)."""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from statistics import median
from typing import Any


def aggregate_consensus(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, int], list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        cid = row.get("canonical_unit_id")
        if isinstance(cid, int):
            groups[(str(row.get("song_id")), str(row.get("region_id")), cid)].append(row)
    out = []
    for (song_id, region_id, cid), items in sorted(groups.items()):
        values = [float(x["mean_boundary_displacement_ms"]) for x in items
                  if isinstance(x.get("mean_boundary_displacement_ms"), (int, float))]
        center = median(values) if values else None
        mad = median([abs(x - center) for x in values]) if center is not None else None
        protected = [x.get("context_protected") for x in items if x.get("context_protected") is not None]
        out.append({
            "schema": "unit_realign_consensus_v1",
            "song_id": song_id, "region_id": region_id, "canonical_unit_id": cid,
            "n_families": len({str(x.get("family")) for x in items}),
            "n_observations": len(items), "median_displacement_ms": center,
            "mad_displacement_ms": mad,
            "context_protection_ratio": (
                sum(bool(v) for v in protected) / len(protected) if protected else None),
            "families": sorted({str(x.get("family")) for x in items}),
        })
    return out
