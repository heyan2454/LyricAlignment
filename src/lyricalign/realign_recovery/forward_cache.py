"""Forward identity and content-addressed cache for realign-recovery (WP B2).

A forward key is the identity of a *model forward*: it must capture everything
that changes the model output, and nothing that does not. GT labels, detector
thresholds, ranking and writeback policy are deliberately excluded.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

from lyricalign.realign_recovery.baseline_identity import canonical_identity_json
from lyricalign.realign_recovery.frozen_baseline import FROZEN_BASELINE_IDENTITY

FORWARD_SCHEMA_VERSION = "realign_recovery_forward_v1"

REQUIRED_FORWARD_FIELDS = (
    "model_id",
    "model_revision",
    "checkpoint_id",
    "checkpoint_path",
    "processor_id",
    "audio_source",
    "audio_sha256",
    "audio_start_sec",
    "audio_end_sec",
    "text_unit_ids",
    "text_content_hash",
    "request_mode",
    "core_sec",
    "left_context_sec",
    "right_context_sec",
    "silence_aware_window_plan",
    "code_version",
    "schema_version",
)

# Fields whose default can come from the frozen Phase-0 baseline identity.
_FROZEN_DEFAULT_FIELDS = (
    "model_id",
    "model_revision",
    "checkpoint_path",
    "processor_id",
    "request_mode",
    "core_sec",
    "left_context_sec",
    "right_context_sec",
    "silence_aware_window_plan",
)


def _resolve_code_version(request: dict) -> str:
    """code_version: explicit request value > env override > frozen baseline > 'unknown'."""
    for candidate in (
        request.get("code_version"),
        os.environ.get("REALIGN_RECOVERY_CODE_VERSION"),
    ):
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    frozen = FROZEN_BASELINE_IDENTITY.get("code_version") or FROZEN_BASELINE_IDENTITY.get(
        "schema_version"
    )
    if isinstance(frozen, str) and frozen.strip():
        return frozen.strip()
    return "unknown"


def _is_empty(value: object) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def build_forward_key(request: dict) -> dict:
    """Extract the canonical forward key from an align request dict.

    Only forward-affecting fields are kept. GT / detector threshold / ranking /
    writeback fields never enter the key, even if present in the request.
    """
    key: dict = {}
    for field in REQUIRED_FORWARD_FIELDS:
        value = request.get(field)
        if not _is_empty(value):
            key[field] = value
        elif field in FROZEN_BASELINE_IDENTITY and field in _FROZEN_DEFAULT_FIELDS:
            key[field] = FROZEN_BASELINE_IDENTITY[field]

    key["code_version"] = _resolve_code_version(request)
    key.setdefault("schema_version", FORWARD_SCHEMA_VERSION)

    for extra in sorted(
        k for k in request if k.startswith("silence_") and k not in REQUIRED_FORWARD_FIELDS
    ):
        key[extra] = request[extra]
    return key


def canonical_forward_key(key: dict) -> str:
    """Stable sorted-key JSON serialization of a forward key."""
    return canonical_identity_json(key)


def forward_digest(key: dict) -> str:
    """sha256 hex digest of the canonical forward key."""
    return hashlib.sha256(canonical_forward_key(key).encode("utf-8")).hexdigest()


def validate_forward_key(key: dict) -> list[str]:
    """Return missing/empty required-field names; empty list means valid.

    A key with any reported field cannot be proven to identify a forward, so the
    cache status for it is ``not_reusable``.
    """
    problems: list[str] = []
    for field in REQUIRED_FORWARD_FIELDS:
        if field not in key or _is_empty(key[field]):
            problems.append(field)
    return problems


@dataclass
class CacheEntry:
    digest: str
    raw_output_path: str
    raw_output_sha256: str
    key: dict
    reusable: bool


class ContentAddressedCache:
    """Content-addressed cache: ``root/<forward_digest>/forward.json``.

    Concurrency: publishing is serialized with a ``.lock`` file in the digest
    directory using ``fcntl.flock``. flock is chosen over O_CREAT|O_EXCL because
    it survives the process (releases automatically on close) and is race-free
    for the check-then-publish sequence; the cache is a local-FS artifact in this
    project, so NFS limitations of flock are not a concern here.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def _digest_dir(self, digest: str) -> Path:
        return self.root / digest

    def _forward_path(self, digest: str) -> Path:
        return self._digest_dir(digest) / "forward.json"

    def _lock_path(self, digest: str) -> Path:
        return self._digest_dir(digest) / ".lock"

    def resolve(self, forward_key: dict) -> CacheEntry | None:
        """Return a reusable entry when the cache proves identity, else None.

        A missing field on the key, a missing cache file, or a cache file whose
        stored key does not canonically match the requested key all mean
        ``not_reusable`` and are reported as ``None``.
        """
        if validate_forward_key(forward_key):
            return None
        digest = forward_digest(forward_key)
        fwd_path = self._forward_path(digest)
        if not fwd_path.is_file():
            return None
        try:
            data = json.loads(fwd_path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return None
        stored_key = data.get("key")
        if not isinstance(stored_key, dict):
            return None
        if canonical_forward_key(stored_key) != canonical_forward_key(forward_key):
            return None
        output = data.get("raw_output_path")
        output_sha = data.get("raw_output_sha256")
        if not isinstance(output, str) or not output:
            return CacheEntry(
                digest=digest,
                raw_output_path="",
                raw_output_sha256=str(output_sha or ""),
                key=stored_key,
                reusable=False,
            )
        if not Path(output).is_file():
            return CacheEntry(
                digest=digest,
                raw_output_path=output,
                raw_output_sha256=str(output_sha or ""),
                key=stored_key,
                reusable=False,
            )
        return CacheEntry(
            digest=digest,
            raw_output_path=output,
            raw_output_sha256=str(output_sha or ""),
            key=stored_key,
            reusable=True,
        )

    def publish(self, forward_key: dict, raw_output_path: str, raw_output_sha256: str) -> str:
        """Write the forward record atomically (``.partial`` + rename) and return its digest.

        An invalid key (any required field missing/empty) raises ``ValueError``.
        The same key is only ever published once: if ``forward.json`` already
        exists with the identical key, the existing digest is returned untouched.
        """
        problems = validate_forward_key(forward_key)
        if problems:
            raise ValueError(
                "forward key is missing required fields; cannot publish: "
                + ", ".join(problems)
            )
        digest = forward_digest(forward_key)
        digest_dir = self._digest_dir(digest)
        digest_dir.mkdir(parents=True, exist_ok=True)

        lock_path = self._lock_path(digest)
        fwd_path = self._forward_path(digest)
        with open(lock_path, "w", encoding="utf-8") as lock_fh:
            fcntl.flock(lock_fh, fcntl.LOCK_EX)
            try:
                if fwd_path.is_file():
                    existing = json.loads(fwd_path.read_text(encoding="utf-8"))
                    existing_key = existing.get("key")
                    if isinstance(existing_key, dict) and (
                        canonical_forward_key(existing_key) == canonical_forward_key(forward_key)
                    ):
                        return existing.get("digest", digest)
                    raise ValueError(
                        f"digest collision: forward.json exists under {digest} "
                        "but its key does not match the published key"
                    )
                record = {
                    "digest": digest,
                    "key": forward_key,
                    "raw_output_path": raw_output_path,
                    "raw_output_sha256": raw_output_sha256,
                    "published_at": time.time(),
                    "schema_version": forward_key.get("schema_version", FORWARD_SCHEMA_VERSION),
                }
                partial = fwd_path.with_name("forward.json.partial")
                partial.write_text(
                    json.dumps(record, sort_keys=True, separators=(",", ":")),
                    encoding="utf-8",
                )
                os.replace(partial, fwd_path)
            finally:
                fcntl.flock(lock_fh, fcntl.LOCK_UN)
        return digest
