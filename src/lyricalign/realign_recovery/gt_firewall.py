"""Phase 0 GT firewall: pure-logic, no-GPU, contract-level enforcement.

The no-GT control API never accepts GT-bearing parameters, and the oracle
API never forwards character-level timestamps to the aligner. This module is
deliberately minimal and model-free; it only implements the firewall rules
plus the artifacts/runner/evaluator contracts described in Phase 0 (A2).
"""

from __future__ import annotations

import copy
import hashlib
import json
import os

from . import SCHEMA_VERSION

_NO_GT_FORBIDDEN_KEYS = ("gt", "gt_path", "timeline_gt", "gt_timestamps")
_NO_GT_PREFIXES = ("gt_", "timeline_gt")
_NO_GT_SUBSTRINGS = ("gt_path", "gt_timestamp")


def _key_matches_no_gt(key: str) -> bool:
    k = str(key).lower()
    if k in _NO_GT_FORBIDDEN_KEYS:
        return True
    if any(k.startswith(p) for p in _NO_GT_PREFIXES):
        return True
    if any(s in k for s in _NO_GT_SUBSTRINGS):
        return True
    return False


_ORACLE_FORBIDDEN_KEYS = (
    "char_times",
    "char_start_sec",
    "char_end_sec",
    "gt_decoder_correction",
    "gt_timestamp",
)
_ORACLE_FORBIDDEN_PREFIXES = ("char_time", "char_start_", "char_end_", "gt_", "timeline_gt")
_ORACLE_ALLOWED_KEYS = ("audio_span", "text_span", "unit_ids", "text", "units", "audio_path")


def validate_no_gt_request(spec: dict) -> list[str]:
    """Return forbidden GT field names present in a control request spec."""
    return [k for k in spec if _key_matches_no_gt(k)]


def validate_oracle_spec(spec: dict) -> list[str]:
    """Return fields in an oracle spec that must not be forwarded to the aligner.

    Only audio-range / text-unit / non-GT configuration keys are allowed.
    """
    violations: list[str] = []
    for k in spec:
        key = str(k).lower()
        if key in _ORACLE_FORBIDDEN_KEYS or any(
            key.startswith(p) for p in _ORACLE_FORBIDDEN_PREFIXES
        ):
            violations.append(k)
    if spec and not any(k in _ORACLE_ALLOWED_KEYS for k in spec):
        violations.append("__no_aligner_config__")
    return violations


def _spec_identity(spec: dict) -> str:
    payload = json.dumps(spec, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class NoGTControlRunner:
    """Contract-level no-GT control runner (no model backend attached).

    Accepts only a request spec plus a raw output dir. Never reads GT: a fake
    filesystem watcher passed via ``_fs_trace`` records every path touched so
    tests can prove no GT object/path was observed.
    """

    def __init__(self, spec: dict, raw_output_dir: str, _fs_trace: list[str] | None = None):
        violations = validate_no_gt_request(spec)
        if violations:
            raise ValueError(
                f"no-GT control request must not contain GT fields: {sorted(violations)}"
            )
        self._spec = dict(spec)
        self._raw_output_dir = str(raw_output_dir)
        self._fs_trace = _fs_trace if _fs_trace is not None else []

    def _touch(self, path: str) -> None:
        self._fs_trace.append(path)

    def run(self) -> dict:
        self._touch(self._raw_output_dir)
        out_path = os.path.join(self._raw_output_dir, "raw_output.json")
        self._touch(out_path)
        artifact = {
            "schema": SCHEMA_VERSION,
            "request_identity": _spec_identity(self._spec),
            "raw_output_path": out_path,
            "detector_state": {"seen": 0, "proposal": None},
            "writeback_state": {"actual_writeback": 0},
        }
        return copy.deepcopy(artifact)


class Evaluator:
    """Read-only joiner of a control artifact with a real-GT binding.

    ``evaluate()`` never mutates the control artifact; it returns a copy with
    metrics attached so a run can be scored independently after the fact.
    """

    def __init__(self, control_artifact: dict, real_gt_binding: dict):
        self._artifact = control_artifact
        self._binding = dict(real_gt_binding)

    def evaluate(self) -> dict:
        before = copy.deepcopy(self._artifact)
        raw = self._artifact.get("raw_output_path")
        observed = self._binding.get("expected")
        correct = int(raw is not None and observed is not None)
        metrics = {
            "schema": SCHEMA_VERSION,
            "correct": correct,
            "wrong_fields": ["raw_output_path"] if correct == 0 else [],
        }
        result = copy.deepcopy(self._artifact)
        result["metrics"] = metrics
        assert self._artifact == before, "evaluator must not mutate control artifact"
        return result
