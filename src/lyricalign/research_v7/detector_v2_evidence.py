"""Detector V2 evidence schema v2 and leak guards (20 §3).

Evidence row contract (H/R/O/V):
  request_identity, view_id, canonical_unit_id,
  raw {start_sec, end_sec, start_entropy, end_entropy, start_margin, end_margin, topk},
  official {start_sec, end_sec, repair_start_shift_sec, repair_end_shift_sec},
  hidden {available, schema, start, end},
  cross_view {view_group, n_views, ...} (populated by view aggregator)

Leak guard: GT, mutation mask, family and error magnitude are forbidden inside
feature-bearing evidence. `assert_no_label_leak` fails fast when any forbidden
field is present in a feature row.

Hidden audit (19 G1): token->row->canonical mapping, layer/boundary position,
numerical equivalence of hook on/off logits with raw/official, evidence
shape/hash. If hidden cannot be audited, mark `hidden=blocked` (R/O continue).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

FORBIDDEN_FEATURE_FIELDS = {
    "gt_start_sec", "gt_end_sec", "label", "unit_label", "raw_label", "official_label",
    "mutation_type", "mutation_family", "family", "replaced_canonical_ids",
    "deleted_canonical_ids", "error_magnitude", "unsafe", "safe", "grey",
}


@dataclass(frozen=True)
class RawView:
    start_sec: float | None = None
    end_sec: float | None = None
    start_entropy: float | None = None
    end_entropy: float | None = None
    start_margin: float | None = None
    end_margin: float | None = None
    topk: tuple = ()

    def to_dict(self) -> dict:
        return {"start_sec": self.start_sec, "end_sec": self.end_sec,
                "start_entropy": self.start_entropy, "end_entropy": self.end_entropy,
                "start_margin": self.start_margin, "end_margin": self.end_margin,
                "topk": list(self.topk)}


@dataclass(frozen=True)
class OfficialView:
    start_sec: float | None = None
    end_sec: float | None = None
    repair_start_shift_sec: float | None = None
    repair_end_shift_sec: float | None = None

    def to_dict(self) -> dict:
        return {"start_sec": self.start_sec, "end_sec": self.end_sec,
                "repair_start_shift_sec": self.repair_start_shift_sec,
                "repair_end_shift_sec": self.repair_end_shift_sec}


@dataclass(frozen=True)
class HiddenView:
    available: bool = False
    schema: str | None = None          # e.g. "boundary_last4_v1"
    start: dict = field(default_factory=dict)
    end: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"available": self.available, "schema": self.schema,
                "start": dict(self.start), "end": dict(self.end)}


@dataclass(frozen=True)
class EvidenceRow:
    request_identity: str
    view_id: str
    canonical_unit_id: int
    raw: RawView = field(default_factory=RawView)
    official: OfficialView = field(default_factory=OfficialView)
    hidden: HiddenView = field(default_factory=HiddenView)
    cross_view: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "request_identity": self.request_identity,
            "view_id": self.view_id,
            "canonical_unit_id": self.canonical_unit_id,
            "raw": self.raw.to_dict(),
            "official": self.official.to_dict(),
            "hidden": self.hidden.to_dict(),
            "cross_view": dict(self.cross_view),
        }


def assert_no_label_leak(feature_row: Mapping[str, Any]) -> dict:
    """Fail fast if any forbidden label/GT field appears in a feature row."""
    keys = set(feature_row)
    leak = sorted(keys & FORBIDDEN_FEATURE_FIELDS)
    if leak:
        raise ValueError(f"feature row leaks forbidden label fields: {leak}")
    return {"ok": True, "leak": [], "n_fields": len(keys)}


@dataclass(frozen=True)
class HiddenAuditResult:
    ok: bool
    mapping: dict | None = None        # token->row->canonical mapping audit
    numerical_equivalence: dict | None = None
    evidence_sha256: str | None = None
    reason: str | None = None

    def to_dict(self) -> dict:
        return {"ok": self.ok, "mapping": self.mapping,
                "numerical_equivalence": self.numerical_equivalence,
                "evidence_sha256": self.evidence_sha256, "reason": self.reason}


def hidden_blocked(reason: str) -> HiddenAuditResult:
    """Hidden route failed G1 audit; R/O continue, never fabricate zero hidden."""
    return HiddenAuditResult(ok=False, reason=reason)


def hidden_ok(*, mapping: dict, numerical_equivalence: dict, evidence_sha256: str) -> HiddenAuditResult:
    return HiddenAuditResult(ok=True, mapping=mapping,
                             numerical_equivalence=numerical_equivalence,
                             evidence_sha256=evidence_sha256)
