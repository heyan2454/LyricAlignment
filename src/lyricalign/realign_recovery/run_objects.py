"""B1 run objects: six persisted dataclasses + atomic IO infrastructure.

All six objects are frozen dataclasses carrying a ``schema_version``.  They are
pure data + strict (de)serialization contracts; no model backend is attached.
Large model raw output is never stored inline -- ``Candidate`` keeps only a
content-addressed path and its sha256.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, fields, is_dataclass

MANIFEST_SCHEMA_VERSION = "realign_recovery_run_objects_v1"

KIND_NATURAL = "natural"
KIND_PROPAGATED = "propagated"
KIND_CHOICES = (KIND_NATURAL, KIND_PROPAGATED)

METHOD_R_A = "R-A"
METHOD_R_B = "R-B"
METHOD_R_C = "R-C"
METHOD_CHOICES = (METHOD_R_A, METHOD_R_B, METHOD_R_C)

_STATUS_CHOICES = (
    "pending",
    "in_progress",
    "succeeded",
    "failed",
    "skipped",
)


class _Undefined:
    """Sentinel for required-field detection in from_dict."""


_REQUIRED_DEFAULTS: dict[type, dict[str, object]] = {}


def _required_field_marker(dc: type) -> object:
    for typ, d in _REQUIRED_DEFAULTS.items():
        if typ is dc:
            return d.get("_marker")
    marker = _Undefined()
    _REQUIRED_DEFAULTS[dc] = {"_marker": marker}
    return marker


@dataclass(frozen=True)
class Episode:
    id: str
    song_id: str
    source_role: str
    kind: str
    source_window: dict
    state_checkpoint: dict
    target_unit_ids: list[int]
    family: str
    attempt_status: str
    effective_status: str
    schema_version: str = MANIFEST_SCHEMA_VERSION

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Episode":
        return _from_dict_strict(cls, d)


@dataclass(frozen=True)
class Proposal:
    id: str
    method: str
    audio_span: list[float]
    text_span: list[int]
    anchors: dict
    context: dict
    no_gt_inputs: dict
    identity: str
    schema_version: str = MANIFEST_SCHEMA_VERSION

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Proposal":
        return _from_dict_strict(cls, d)


@dataclass(frozen=True)
class Candidate:
    id: str
    proposal_id: str
    forward_identity: str
    raw_output_path: str
    raw_output_sha256: str
    ownership: str
    status: str
    failure: str | None
    schema_version: str = MANIFEST_SCHEMA_VERSION

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Candidate":
        return _from_dict_strict(cls, d)


@dataclass(frozen=True)
class Decision:
    id: str
    trigger: str
    old_no_gt_scores: dict
    new_no_gt_scores: dict
    rank: int
    accept_reject_reason: str
    writeback_span: list[int] | None
    schema_version: str = MANIFEST_SCHEMA_VERSION

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Decision":
        return _from_dict_strict(cls, d)


@dataclass(frozen=True)
class Continuation:
    id: str
    before_state: dict
    after_state: dict
    committed_provenance: dict
    next_windows: list[dict]
    cost: dict
    schema_version: str = MANIFEST_SCHEMA_VERSION

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Continuation":
        return _from_dict_strict(cls, d)


@dataclass(frozen=True)
class Evaluation:
    id: str
    gt_binding_hash: str
    labeled: int
    unlabeled: int
    metrics: dict
    stage_labels: list[str]
    schema_version: str = MANIFEST_SCHEMA_VERSION

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Evaluation":
        return _from_dict_strict(cls, d)


def _from_dict_strict(dc: type, d: dict) -> object:
    if not isinstance(d, dict):
        raise ValueError(f"{dc.__name__}.from_dict requires a dict, got {type(d).__name__}")
    schema = d.get("schema_version")
    if schema != MANIFEST_SCHEMA_VERSION:
        raise ValueError(
            f"unsupported schema_version {schema!r} for {dc.__name__}; "
            f"expected {MANIFEST_SCHEMA_VERSION!r}"
        )
    field_names = [f.name for f in fields(dc)]
    missing = [k for k in field_names if k not in d]
    if missing:
        raise ValueError(f"{dc.__name__} missing required fields: {sorted(missing)}")
    unknown = [k for k in d if k not in field_names]
    if unknown:
        raise ValueError(f"{dc.__name__} unknown fields: {sorted(unknown)}")
    cleaned = {k: d[k] for k in field_names}
    _validate_common(dc, cleaned)
    return dc(**cleaned)


def _validate_common(dc: type, cleaned: dict) -> None:
    ident = cleaned.get("id")
    if ident is None or (isinstance(ident, str) and not ident.strip()):
        raise ValueError(f"{dc.__name__}.id must be a non-empty string")
    if dc is Episode:
        kind = cleaned["kind"]
        if kind not in KIND_CHOICES:
            raise ValueError(
                f"Episode.kind {kind!r} not in {list(KIND_CHOICES)}"
            )
        _require_status(dc, cleaned, "attempt_status")
        _require_status(dc, cleaned, "effective_status")
        _require_monotonic_ids(dc, cleaned["target_unit_ids"])
    elif dc is Proposal:
        method = cleaned["method"]
        if method not in METHOD_CHOICES:
            raise ValueError(
                f"Proposal.method {method!r} not in {list(METHOD_CHOICES)}"
            )
    elif dc is Candidate:
        _require_status(dc, cleaned, "status")


def _require_status(dc: type, cleaned: dict, key: str) -> None:
    val = cleaned[key]
    if val not in _STATUS_CHOICES:
        raise ValueError(
            f"{dc.__name__}.{key} {val!r} not in {list(_STATUS_CHOICES)}"
        )


def _require_monotonic_ids(dc: type, unit_ids: list[int]) -> None:
    if not isinstance(unit_ids, list) or any(
        not isinstance(u, int) or isinstance(u, bool) for u in unit_ids
    ):
        raise ValueError(f"{dc.__name__}.target_unit_ids must be a list of ints")
    for prev, cur in zip(unit_ids, unit_ids[1:]):
        if cur < prev:
            raise ValueError(
                f"{dc.__name__}.target_unit_ids must be non-decreasing, got {unit_ids}"
            )


def atomic_write_text(path: str, text: str) -> str:
    """Atomically write ``text`` to ``path`` via ``path.partial`` then rename."""
    path = os.fspath(path)
    partial = path + ".partial"
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(partial, "w", encoding="utf-8") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(partial, path)
    return path


def write_jsonl(path: str, rows: list[dict]) -> str:
    """Write all rows as JSONL; rows are read back strictly unchanged."""
    lines = [json.dumps(r, ensure_ascii=False, sort_keys=True) for r in rows]
    atomic_write_text(path, "\n".join(lines) + ("\n" if lines else ""))
    _verify_jsonl(path, rows)
    return path


def append_jsonl(path: str, row: dict) -> str:
    """Append a single row; the row must read back strictly unchanged."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    text = json.dumps(row, ensure_ascii=False, sort_keys=True)
    existing = _read_existing(path)
    if existing and not existing.endswith("\n"):
        text = "\n" + text
    atomic_write_text(path, existing + text)
    _verify_jsonl(path, [row])
    return path


def _read_existing(path: str) -> str:
    if not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def _verify_jsonl(path: str, rows: list[dict]) -> None:
    expected = [json.dumps(r, ensure_ascii=False, sort_keys=True) for r in rows]
    with open(path, "r", encoding="utf-8") as fh:
        got = [line for line in fh.read().splitlines() if line.strip()]
    if got[-len(expected):] != expected:
        raise ValueError(f"jsonl read-back mismatch in {path}")


def stage_completed(out_dir: str, name: str, summary: dict) -> str:
    """Write ``out_dir/name.COMPLETED.json`` with a stable summary."""
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{name}.COMPLETED.json")
    payload = {
        "stage": name,
        "status": "completed",
        "summary": dict(summary),
        "schema_version": MANIFEST_SCHEMA_VERSION,
    }
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return path


def append_failure(out_dir: str, name: str, row: dict) -> str:
    """Append a failure row to ``out_dir/name.FAILURES.jsonl``."""
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{name}.FAILURES.jsonl")
    return append_jsonl(path, row)


def file_sha256(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()
