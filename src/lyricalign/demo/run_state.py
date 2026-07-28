"""Persistent run/item/stage state for resumable demo experiments.

The state protocol deliberately separates model/analysis completion from slow
visual and video rendering.  A resume is accepted only when the frozen run
identity matches; otherwise the caller must start a new output directory or
explicitly invalidate a stage.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

RUN_STATE_SCHEMA = "inline_realign_run_state_v1"
STAGE_STATE_SCHEMA = "inline_realign_stage_state_v1"
ITEM_STATE_SCHEMA = "inline_realign_item_state_v1"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False, suffix=".tmp"
    ) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def file_identity(path: Path, *, include_sha256: bool = True) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if not path.is_file():
        return {"path": str(path), "exists": False}
    stat = path.stat()
    payload: dict[str, Any] = {
        "path": str(path), "exists": True, "size": stat.st_size, "mtime_ns": stat.st_mtime_ns,
    }
    if include_sha256:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        payload["sha256"] = digest.hexdigest()
    return payload


def outputs_exist(paths: Iterable[Path]) -> bool:
    return all(path.is_file() and path.stat().st_size > 0 for path in paths)


def output_snapshots(paths: Iterable[Path]) -> list[dict[str, Any]]:
    snapshots: list[dict[str, Any]] = []
    for path in paths:
        resolved=path.expanduser().resolve()
        if not resolved.is_file():
            snapshots.append({"path":str(resolved),"exists":False})
            continue
        stat=resolved.stat()
        digest=hashlib.sha256()
        with resolved.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        snapshots.append({
            "path":str(resolved),"exists":True,"size":stat.st_size,
            "mtime_ns":stat.st_mtime_ns,"sha256":digest.hexdigest(),
        })
    return snapshots


def snapshots_match(stored: Any, paths: Iterable[Path]) -> bool:
    if not isinstance(stored,list):
        return False
    return stored == output_snapshots(paths)


class RunState:
    """Manage frozen run identity and resumable stage records."""

    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()
        self.state_root = self.root / "state"
        self.run_path = self.state_root / "run_state.json"
        self.stage_root = self.state_root / "stages"
        self.item_root = self.state_root / "items"

    def initialize(self, identity: dict[str, Any], *, resume: bool) -> dict[str, Any]:
        identity_hash = canonical_hash(identity)
        current = read_json(self.run_path)
        if current:
            old_hash = current.get("identity_hash")
            if old_hash != identity_hash:
                raise RuntimeError(
                    "resume identity mismatch: existing output belongs to a different manifest/config/model/input request; "
                    "use a new OUT_ROOT or explicitly clean/invalidate the old run"
                )
            if not resume:
                raise RuntimeError(
                    "output directory already contains a resumable run. Re-run with --resume, or clean the output first"
                )
            current["last_resumed_at"] = utc_now()
            current["resume_count"] = int(current.get("resume_count", 0)) + 1
            atomic_json(self.run_path, current)
            return current
        payload = {
            "schema_version": RUN_STATE_SCHEMA,
            "created_at": utc_now(),
            "identity": identity,
            "identity_hash": identity_hash,
            "resume_count": 0,
            "status": "initialized",
        }
        atomic_json(self.run_path, payload)
        return payload

    def set_run_status(self, status: str, **extra: Any) -> None:
        payload = read_json(self.run_path)
        if not payload:
            raise RuntimeError("run state has not been initialized")
        payload.update({"status": status, "updated_at": utc_now(), **extra})
        atomic_json(self.run_path, payload)

    def stage_path(self, name: str) -> Path:
        return self.stage_root / f"{name}.json"

    def stage_is_complete(self, name: str, *, request_hash: str, outputs: Iterable[Path]) -> bool:
        payload = read_json(self.stage_path(name))
        output_list=list(outputs)
        return (
            payload.get("status") == "complete"
            and payload.get("request_hash") == request_hash
            and outputs_exist(output_list)
            and snapshots_match(payload.get("output_snapshots"),output_list)
        )

    def begin_stage(self, name: str, *, request: dict[str, Any], outputs: Iterable[Path]) -> str:
        output_list=list(outputs)
        request_hash = canonical_hash(request)
        atomic_json(self.stage_path(name), {
            "schema_version": STAGE_STATE_SCHEMA,
            "stage": name,
            "status": "running",
            "started_at": utc_now(),
            "request": request,
            "request_hash": request_hash,
            "expected_outputs": [str(path) for path in output_list],
        })
        return request_hash

    def finish_stage(
        self, name: str, *, status: str, request_hash: str, outputs: Iterable[Path],
        returncode: int | None = None, error: str | None = None,
    ) -> None:
        output_list=list(outputs)
        payload = read_json(self.stage_path(name))
        payload.update({
            "schema_version": STAGE_STATE_SCHEMA,
            "stage": name,
            "status": status,
            "finished_at": utc_now(),
            "request_hash": request_hash,
            "expected_outputs": [str(path) for path in output_list],
            "outputs_present": outputs_exist(output_list),
            "output_snapshots": output_snapshots(output_list),
            "returncode": returncode,
            "error": error,
        })
        atomic_json(self.stage_path(name), payload)

    def invalidate_stage(self, name: str) -> None:
        path = self.stage_path(name)
        if path.exists():
            payload = read_json(path)
            payload.update({"status": "invalidated", "invalidated_at": utc_now()})
            atomic_json(path, payload)

    def item_path(self, item_id: str) -> Path:
        return self.item_root / f"{item_id}.json"

    def item_is_complete(self, item_id: str, *, request_hash: str, outputs: Iterable[Path]) -> bool:
        payload = read_json(self.item_path(item_id))
        output_list=list(outputs)
        return (
            payload.get("status") == "complete"
            and payload.get("request_hash") == request_hash
            and outputs_exist(output_list)
            and snapshots_match(payload.get("output_snapshots"),output_list)
        )

    def begin_item(self, item_id: str, *, request: dict[str, Any], outputs: Iterable[Path]) -> str:
        output_list=list(outputs)
        request_hash = canonical_hash(request)
        previous = read_json(self.item_path(item_id))
        atomic_json(self.item_path(item_id), {
            "schema_version": ITEM_STATE_SCHEMA,
            "item_id": item_id,
            "status": "running",
            "started_at": utc_now(),
            "request": request,
            "request_hash": request_hash,
            "expected_outputs": [str(path) for path in output_list],
            "attempt": int(previous.get("attempt", 0)) + 1,
        })
        return request_hash

    def finish_item(
        self, item_id: str, *, status: str, request_hash: str, outputs: Iterable[Path],
        error: str | None = None,
    ) -> None:
        output_list=list(outputs)
        outputs_present=outputs_exist(output_list)
        if status == "complete" and not outputs_present:
            missing=[
                str(path.expanduser().resolve())
                for path in output_list
                if not path.is_file() or path.stat().st_size <= 0
            ]
            raise FileNotFoundError(
                f"refusing to mark item {item_id!r} complete; expected outputs missing or empty: {missing}"
            )
        payload = read_json(self.item_path(item_id))
        payload.update({
            "schema_version": ITEM_STATE_SCHEMA,
            "item_id": item_id,
            "status": status,
            "finished_at": utc_now(),
            "request_hash": request_hash,
            "expected_outputs": [str(path) for path in output_list],
            "outputs_present": outputs_present,
            "output_snapshots": output_snapshots(output_list),
            "error": error,
        })
        atomic_json(self.item_path(item_id), payload)
