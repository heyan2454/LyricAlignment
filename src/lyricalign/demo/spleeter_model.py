"""Strict discovery and validation for explicitly stored Spleeter models.

The upstream ``.probe`` file is treated as an optional download-completion hint,
not as the model itself.  A model is usable when a complete TensorFlow
checkpoint or SavedModel file group is present.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Iterable


_CHECKPOINT_RE = re.compile(r'model_checkpoint_path\s*:\s*["\']([^"\']+)["\']')


@dataclass(frozen=True)
class SpleeterModelInfo:
    requested_root: Path
    model_root: Path
    model_dir: Path
    model_name: str
    layout: str
    marker_present: bool
    files: tuple[Path, ...]

    def as_dict(self) -> dict[str, object]:
        records = []
        for path in self.files:
            stat = path.stat()
            records.append(
                {
                    "path": str(path.resolve()),
                    "relative_path": str(path.relative_to(self.model_dir)),
                    "size_bytes": stat.st_size,
                    "mtime_ns": stat.st_mtime_ns,
                }
            )
        identity_payload = {
            "schema_version": "spleeter_model_identity_v2",
            "model_name": self.model_name,
            "model_dir": str(self.model_dir.resolve()),
            "layout": self.layout,
            "files": records,
        }
        identity_sha256 = hashlib.sha256(
            json.dumps(identity_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return {
            **identity_payload,
            "requested_root": str(self.requested_root.resolve()),
            "model_root": str(self.model_root.resolve()),
            "marker_path": str((self.model_dir / ".probe").resolve()),
            "marker_present": self.marker_present,
            "identity_sha256": identity_sha256,
        }


def _nonempty(paths: Iterable[Path]) -> bool:
    return all(path.is_file() and path.stat().st_size > 0 for path in paths)


def _checkpoint_prefixes(model_dir: Path) -> list[Path]:
    prefixes: list[Path] = []
    checkpoint = model_dir / "checkpoint"
    if checkpoint.is_file():
        try:
            match = _CHECKPOINT_RE.search(checkpoint.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            match = None
        if match:
            prefix = Path(match.group(1))
            if not prefix.is_absolute():
                prefix = model_dir / prefix
            prefixes.append(prefix)
    for index_file in sorted(model_dir.glob("*.index")):
        prefixes.append(index_file.with_suffix(""))
    unique: list[Path] = []
    seen: set[str] = set()
    for prefix in prefixes:
        key = str(prefix.resolve(strict=False))
        if key not in seen:
            seen.add(key)
            unique.append(prefix)
    return unique


def _validate_checkpoint(model_dir: Path) -> tuple[str, tuple[Path, ...]] | None:
    checkpoint = model_dir / "checkpoint"
    for prefix in _checkpoint_prefixes(model_dir):
        index_file = Path(f"{prefix}.index")
        data_files = tuple(sorted(prefix.parent.glob(f"{prefix.name}.data-*")))
        required = (index_file, *data_files)
        if data_files and _nonempty(required):
            files: list[Path] = []
            if checkpoint.is_file() and checkpoint.stat().st_size > 0:
                files.append(checkpoint)
            files.extend(required)
            meta = Path(f"{prefix}.meta")
            if meta.is_file() and meta.stat().st_size > 0:
                files.append(meta)
            return "tensorflow_checkpoint", tuple(files)
    return None


def _validate_saved_model(model_dir: Path) -> tuple[str, tuple[Path, ...]] | None:
    saved_model = model_dir / "saved_model.pb"
    variables = model_dir / "variables"
    index_file = variables / "variables.index"
    data_files = tuple(sorted(variables.glob("variables.data-*")))
    required = (saved_model, index_file, *data_files)
    if data_files and _nonempty(required):
        return "tensorflow_saved_model", tuple(required)
    return None


def resolve_spleeter_model(model_root: Path, model_name: str = "2stems") -> SpleeterModelInfo:
    """Resolve either a model-root directory or the explicit model directory.

    Accepted inputs:
    - ``/path/to/models`` containing ``2stems/``;
    - ``/path/to/models/2stems`` itself.

    ``.probe`` is optional.  Actual checkpoint files are mandatory.
    """
    requested = Path(model_root).expanduser()
    candidates: list[tuple[Path, Path]] = []
    direct = requested
    nested = requested / model_name
    if requested.name == model_name:
        candidates.append((requested.parent, direct))
    candidates.append((requested, nested))
    if requested.name != model_name:
        candidates.append((requested.parent, direct))

    checked: list[str] = []
    for root, model_dir in candidates:
        key = str(model_dir.resolve(strict=False))
        if key in checked:
            continue
        checked.append(key)
        if not model_dir.is_dir():
            continue
        result = _validate_checkpoint(model_dir) or _validate_saved_model(model_dir)
        if result is None:
            continue
        layout, files = result
        return SpleeterModelInfo(
            requested_root=requested,
            model_root=root,
            model_dir=model_dir,
            model_name=model_name,
            layout=layout,
            marker_present=(model_dir / ".probe").is_file(),
            files=files,
        )

    locations = ", ".join(checked) if checked else str(requested)
    raise FileNotFoundError(
        "No complete Spleeter model weights were found. Checked: "
        f"{locations}. A .probe marker is optional, but the directory must contain "
        "a non-empty TensorFlow checkpoint pair (*.index + *.data-*) or a "
        "SavedModel (saved_model.pb + variables/*)."
    )
