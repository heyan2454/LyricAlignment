"""Tests for the Evaluation V1 grouped split manifest builder."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/evaluation/build_evaluation_v1_split_manifest.py"


def load_script():
    spec = importlib.util.spec_from_file_location("evaluation_v1_split_manifest", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def mod():
    return load_script()


def test_allocate_simple_counts_and_determinism(mod):
    items = [{"group_id": f"s{i}"} for i in range(10)]
    mod.allocate_simple(items, (2, 5, 3), "seed-A", key="test")
    tiers = [r["tier"] for r in items]
    assert tiers.count("diagnostic_visible") == 2
    assert tiers.count("regression_selection") == 5
    assert tiers.count("sealed_final") == 3
    # Same seed reproduces exact assignment.
    items2 = [{"group_id": f"s{i}"} for i in range(10)]
    mod.allocate_simple(items2, (2, 5, 3), "seed-A", key="test")
    assert [r["tier"] for r in items2] == tiers


def test_stratified_allocate_spreads_hard_tags(mod):
    items = []
    for i in range(20):
        items.append({
            "group_id": f"j{i}",
            "lyric_overlap": i % 5 == 0,
            "polyphonic": i % 7 == 0,
            "non_lexical": i % 3 == 0,
        })
    mod.stratified_allocate(items, (4, 10, 6), "seed-B", strata_keys=("non_lexical", "polyphonic", "lyric_overlap"), key="jamendo")
    counts = {t: 0 for t in mod.TIERS}
    hard_counts = {t: 0 for t in mod.TIERS}
    for row in items:
        counts[row["tier"]] += 1
        if row["non_lexical"] or row["polyphonic"] or row["lyric_overlap"]:
            hard_counts[row["tier"]] += 1
    assert counts == {"diagnostic_visible": 4, "regression_selection": 10, "sealed_final": 6}
    # Every tier should contain at least one hard-case tag under this fixture.
    assert all(hard_counts[t] > 0 for t in mod.TIERS)


def test_leakage_audit_passes_and_detects_cross_tier(mod):
    rows = [
        {"item_id": "a1", "group_id": "g1", "song_id": "s1", "dataset_id": "d1", "tier": "diagnostic_visible"},
        {"item_id": "a2", "group_id": "g1", "song_id": "s1", "dataset_id": "d1", "tier": "diagnostic_visible"},
        {"item_id": "b1", "group_id": "g2", "song_id": "s2", "dataset_id": "d1", "tier": "regression_selection"},
    ]
    audit = mod.leakage_audit(rows)
    assert audit["passed"] is True

    bad = rows + [{"item_id": "a3", "group_id": "g1", "song_id": "s1", "dataset_id": "d1", "tier": "sealed_final"}]
    audit = mod.leakage_audit(bad)
    assert audit["passed"] is False
    assert audit["same_group_cross_tier"] == ["g1"]

    dup = rows + [{"item_id": "a1", "group_id": "g9", "song_id": "s9", "dataset_id": "d9", "tier": "sealed_final"}]
    audit = mod.leakage_audit(dup)
    assert audit["duplicate_item_ids"] == ["a1"]


def test_same_song_id_different_dataset_not_leak(mod):
    rows = [
        {"item_id": "m1", "group_id": "g1", "song_id": "23", "dataset_id": "mir_mlpop_cmn", "tier": "sealed_final"},
        {"item_id": "y1", "group_id": "g2", "song_id": "23", "dataset_id": "mir_mlpop_yue", "tier": "diagnostic_visible"},
    ]
    audit = mod.leakage_audit(rows)
    assert audit["passed"] is True


CHECK_SCRIPT = ROOT / "scripts/evaluation/check_split_access.py"


def load_check_script():
    spec = importlib.util.spec_from_file_location("evaluation_check_split_access", CHECK_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_check_split_access_group_integrity(mod):
    check = load_check_script()
    rows = [
        {"group_id": "g1", "tier": "diagnostic_visible"},
        {"group_id": "g1", "tier": "sealed_final"},
        {"group_id": "g2", "tier": "regression_selection"},
    ]
    assert check.check_group_integrity(rows) == ["g1"]
    rows_ok = [
        {"group_id": "g1", "tier": "diagnostic_visible"},
        {"group_id": "g1", "tier": "diagnostic_visible"},
    ]
    assert check.check_group_integrity(rows_ok) == []


def test_behavior_registry_is_valid_json():
    import json
    path = ROOT / "reports/behavior_registry.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["schema_version"] == "lyric_align_behavior_registry_v1"
    assert len(data["behaviors"]) >= 5
    for behavior in data["behaviors"]:
        assert behavior["behavior_id"]
        assert behavior["layer"]
        assert behavior["datasets"]
        assert behavior["productization_gate"]


GUARD_SCRIPT = ROOT / "scripts/evaluation/guarded_run.py"


def load_guard_script():
    spec = importlib.util.spec_from_file_location("evaluation_guarded_run", GUARD_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_guarded_run_policy():
    guard = load_guard_script()
    rows = [
        {"group_id": "g1", "tier": "diagnostic_visible"},
        {"group_id": "g2", "tier": "sealed_final"},
    ]
    problems = guard.check_policy(rows, allowed_tiers={"diagnostic_visible"}, allow_sealed=False)
    assert any("sealed_final" in p for p in problems)
    assert guard.check_policy(rows, allowed_tiers={"diagnostic_visible", "sealed_final"}, allow_sealed=True) == []


def test_guarded_run_cli_with_temp_manifest(tmp_path):
    import json
    import subprocess
    import sys

    manifest = tmp_path / "manifest.jsonl"
    rows = [
        {"group_id": "g1", "tier": "diagnostic_visible", "item_id": "a"},
        {"group_id": "g2", "tier": "sealed_final", "item_id": "b"},
    ]
    manifest.write_text("\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n", encoding="utf-8")
    cmd = [
        sys.executable, str(ROOT / "scripts/evaluation/guarded_run.py"),
        "--manifest", str(manifest), "--", "echo", "should_not_run",
    ]
    proc = subprocess.run(cmd, text=True, capture_output=True)
    assert proc.returncode == 2
    assert "sealed_final" in proc.stdout

    diag = tmp_path / "diag.jsonl"
    diag.write_text(json.dumps({"group_id": "g1", "tier": "diagnostic_visible", "item_id": "a"}, sort_keys=True) + "\n", encoding="utf-8")
    cmd = [
        sys.executable, str(ROOT / "scripts/evaluation/guarded_run.py"),
        "--manifest", str(diag), "--", "echo", "hello",
    ]
    proc = subprocess.run(cmd, text=True, capture_output=True)
    assert proc.returncode == 0
    assert "hello" in proc.stdout


def test_guarded_run_allow_sealed_milestone(tmp_path):
    import json
    import subprocess
    import sys

    manifest = tmp_path / "manifest.jsonl"
    rows = [
        {"group_id": "g1", "tier": "sealed_final", "item_id": "s1"},
    ]
    manifest.write_text("\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n", encoding="utf-8")
    cmd = [
        sys.executable, str(ROOT / "scripts/evaluation/guarded_run.py"),
        "--manifest", str(manifest),
        "--tiers", "sealed_final",
        "--allow-sealed", "--", "echo", "milestone_ok",
    ]
    proc = subprocess.run(cmd, text=True, capture_output=True)
    assert proc.returncode == 0
    assert "milestone_ok" in proc.stdout
