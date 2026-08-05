"""Coverage-matrix gate for Detector V2 experiments."""
from __future__ import annotations

from pathlib import Path
from typing import Mapping

ALLOWED_STATUSES = ("pending", "partial", "complete", "blocked")

FORBIDDEN_METRIC_NAMES = {
    "wrong_output_recall",
    "replaced_gt_omission_recall",
    "tail_gap_recall",
}

REQUIRED_CELLS = (
    "gates.gt_label_audit",
    "gates.request_identity_audit",
    "gates.hidden_extraction_audit",
    "targets.raw.song_heldout",
    "targets.official.song_heldout",
    "families.crop_shift",
    "families.cursor_shift",
    "families.end_early",
    "families.repeated_section",
    "families.acoustic_difficulty",
    "families.slot_multiview",
    "stress.replace_1_2_4_8",
    "stress.missing_extra_stress",
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


def _artifact_exists(root: Path | None, artifact: str) -> bool:
    path = Path(artifact)
    if path.is_absolute():
        return path.exists()
    return root is not None and (root / path).exists()


def validate_coverage_matrix(
    matrix: Mapping, *, repo_root: str | Path | None = None, run_root: str | Path | None = None
) -> dict:
    """Validate required cells, statuses, denominators, artifacts and forbidden metrics.

    Status contract: ``pending`` (not started) / ``partial`` (requires ``note``) /
    ``complete`` (requires positive denominator + existing ``artifact``) /
    ``blocked`` (requires ``reason``). Artifact existence is checked against
    ``run_root`` (artifact dir) when given, else ``repo_root``.
    """
    errors: list[str] = []
    warnings: list[str] = []
    root = Path(run_root or repo_root).resolve() if (run_root or repo_root) is not None else None

    forbidden = _find_forbidden_names(matrix)
    if forbidden:
        errors.append(f"forbidden deprecated detector metrics present: {forbidden}")

    for path in REQUIRED_CELLS:
        cell = _walk(matrix, path)
        if not isinstance(cell, Mapping):
            errors.append(f"missing required coverage cell: {path}")
            continue
        status = cell.get("status")
        if status not in ALLOWED_STATUSES:
            errors.append(f"invalid status for {path}: {status!r}")
            continue
        if status == "pending":
            continue
        if status == "partial":
            if not (cell.get("note") or "").strip():
                errors.append(f"partial cell requires note: {path}")
            continue
        if status == "blocked":
            if not (cell.get("reason") or "").strip():
                errors.append(f"blocked cell requires reason: {path}")
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
        elif root is not None and not _artifact_exists(root, artifact):
            errors.append(f"artifact does not exist for {path}: {artifact} (root={root})")

    hidden = _walk(matrix, "ablations.H")
    if isinstance(hidden, Mapping) and hidden.get("status") == "blocked":
        for path in ("ablations.H_R", "ablations.H_O", "ablations.H_R_O", "ablations.H_R_O_V"):
            cell = _walk(matrix, path)
            if isinstance(cell, Mapping) and cell.get("status") == "complete":
                errors.append(f"{path} cannot be complete while hidden is blocked")
        warnings.append("hidden gate blocked; R/O formal may continue but H conclusions are unavailable")

    return {"ok": not errors, "errors": errors, "warnings": warnings}


def populate_status_from_artifacts(matrix: Mapping, run_root: str | Path) -> dict:
    """Mark still-pending cells as ``partial`` when matching artifacts exist under ``run_root``.

    Matching is a normalized substring match (underscores removed, case-folded)
    between the cell key and artifact file names, scanned up to one level deep.
    Returns ``{cell_path: [file names]}``.
    """
    run_root = Path(run_root)
    found: dict[str, list[str]] = {}
    candidates = [p for p in list(run_root.glob("*")) + list(run_root.glob("*/*")) if p.is_file()]
    for path in REQUIRED_CELLS:
        cell = _walk(matrix, path)
        if not isinstance(cell, Mapping) or cell.get("status") != "pending":
            continue
        needle = path.rsplit(".", 1)[-1].lower().replace("_", "")
        if len(needle) < 4:
            continue
        hits = sorted({p.name for p in candidates if needle in p.name.lower().replace("_", "")})
        if hits:
            cell["status"] = "partial"
            cell["note"] = "artifacts found under run-root: " + ", ".join(hits[:5])
            found[path] = hits
    return found
