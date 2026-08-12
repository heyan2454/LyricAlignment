"""Baseline identity tests (docs/sessions/20260812_realign_recovery_research/08, A1/A4)."""
from __future__ import annotations

import hashlib
import json

import pytest

from lyricalign.realign_recovery.baseline_identity import (
    REQUIRED_IDENTITY_FIELDS,
    canonical_identity_json,
    identity_digest,
    validate_identity,
)
from lyricalign.realign_recovery.frozen_baseline import (
    FROZEN_BASELINE_IDENTITY,
    FROZEN_OPERATING_POINTS_PATH,
)


def test_frozen_baseline_identity_is_complete() -> None:
    assert validate_identity(FROZEN_BASELINE_IDENTITY) == []


def test_validate_identity_reports_missing_fields() -> None:
    for field in REQUIRED_IDENTITY_FIELDS:
        identity = dict(FROZEN_BASELINE_IDENTITY)
        del identity[field]
        problems = validate_identity(identity)
        assert field in problems
        assert set(problems) <= set(REQUIRED_IDENTITY_FIELDS)


def test_validate_identity_reports_empty_values() -> None:
    for value in ("", None):
        for field in REQUIRED_IDENTITY_FIELDS:
            identity = dict(FROZEN_BASELINE_IDENTITY)
            identity[field] = value
            problems = validate_identity(identity)
            assert field in problems
        identity = dict(FROZEN_BASELINE_IDENTITY)
        identity["unknown_field"] = value
        assert validate_identity(identity) == []


def test_canonical_json_is_stable() -> None:
    assert canonical_identity_json(FROZEN_BASELINE_IDENTITY) == canonical_identity_json(
        FROZEN_BASELINE_IDENTITY
    )
    assert json.loads(canonical_identity_json(FROZEN_BASELINE_IDENTITY)) == FROZEN_BASELINE_IDENTITY


def test_identity_digest_format() -> None:
    digest = identity_digest(FROZEN_BASELINE_IDENTITY)
    assert isinstance(digest, str)
    assert len(digest) == 64
    int(digest, 16)
    assert identity_digest(FROZEN_BASELINE_IDENTITY) == digest


def test_identity_digest_changes_with_value() -> None:
    mutated = dict(FROZEN_BASELINE_IDENTITY)
    mutated["core_sec"] = 61
    assert identity_digest(mutated) != identity_digest(FROZEN_BASELINE_IDENTITY)


def test_frozen_detector_sha_matches_file() -> None:
    expected = hashlib.sha256(FROZEN_OPERATING_POINTS_PATH.read_bytes()).hexdigest()
    assert FROZEN_BASELINE_IDENTITY["detector_artifact_sha256"] == expected
