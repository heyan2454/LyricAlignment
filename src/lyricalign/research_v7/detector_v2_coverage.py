"""Coverage-matrix gate for Detector V2 experiments."""
from __future__ import annotations

from pathlib import Path
from typing import Mapping


FORBIDDEN_METRIC_NAMES = {
    "wrong_output_recall",
    "replaced_gt_omission_recall",
    "tail_gap_recall",
}

REQUIRED_CELLS = (
    "gates.gt_label_audit",
    "gates.request_identity_audit",
    "targets.raw.song_heldout",
    "targets.official.song_heldout",
    "families.crop_shift",
    "families.cursor_shift",
    "families.end_early",
    "families.repeated_section",
    "families.acoustic_difficulty",
    "families.slot_multiview",
    "stress.replace_1_2_4_8",
    "generalization.family_loo",
    "generalization.m4_to_mir_by_family",
    "metrics.tristate_unit",
    "metrics.interval_75_100",
    "ablations.H",
    "ablations.R",
    "ablations.O",
    "ablations.H_R",
    "ablations.H_O",
    "ablations.R_O",
    "ablations.H_R_O",
    "ablations.H_R_O_V",
    "views.single",
    "views.multi",
    "serial.closed_loop",
)


def _walk(mapping: Mapping, path: str):
    value = mapping
    for part in path.split("."):
        if not isinstance(value, Mapping) or part not in value:
            return None
        value = value[part]
    return value


def _find_forbidden_names(value, prefix: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if key in FORBIDDEN_METRIC_NAMES:
                found.append(path)
            found.extend(_find_forbidden_names(child, path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_find_forbidden_names(child, f"{prefix}[{index}]"))
    return found


def validate_coverage_matrix(matrix: Mapping, *, repo_root: str | Path | None = None) -> dict:
    """Validate required cells, nonzero denominators, artifacts and forbidden metrics."""
    errors: list[str] = []
    warnings: list[str] = []
    root = Path(repo_root).resolve() if repo_root is not None else None

    forbidden = _find_forbidden_names(matrix)
    if forbidden:
        errors.append(f"forbidden deprecated detector metrics present: {forbidden}")

    for path in REQUIRED_CELLS:
        cell = _walk(matrix, path)
        if not isinstance(cell, Mapping):
            errors.append(f"missing required coverage cell: {path}")
            continue
        status = cell.get("status")
        if path == "ablations.H" and status == "blocked":
            reason = cell.get("reason")
            if not reason:
                errors.append("ablations.H blocked without reason")
            continue
        if status != "complete":
            errors.append(f"coverage cell not complete: {path} status={status!r}")
            continue
        denominators = [
            cell.get("n_source_songs"),
            cell.get("n_unsafe_units"),
            cell.get("n_safe_units"),
            cell.get("n_error_intervals"),
            cell.get("n_requests"),
        ]
        if not any(isinstance(x, (int, float)) and x > 0 for x in denominators):
            errors.append(f"complete cell has no positive denominator: {path}")
        artifact = cell.get("artifact")
        if not artifact:
            errors.append(f"complete cell missing artifact: {path}")
        elif root is not None and not (root / str(artifact)).exists():
            errors.append(f"artifact does not exist for {path}: {artifact}")

    hidden = _walk(matrix, "ablations.H")
    if isinstance(hidden, Mapping) and hidden.get("status") == "blocked":
        for path in ("ablations.H_R", "ablations.H_O", "ablations.H_R_O", "ablations.H_R_O_V"):
            cell = _walk(matrix, path)
            if isinstance(cell, Mapping) and cell.get("status") == "complete":
                errors.append(f"{path} cannot be complete while hidden is blocked")
        warnings.append("hidden gate blocked; R/O formal may continue but H conclusions are unavailable")

    return {"ok": not errors, "errors": errors, "warnings": warnings}
