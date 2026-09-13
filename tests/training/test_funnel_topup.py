"""CPU tests for the post-hoc funnel top-up planner (`scripts/training/run_funnel_topup.py`)."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("run_funnel_topup", ROOT / "scripts" / "training" / "run_funnel_topup.py")
assert SPEC and SPEC.loader
TOPUP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TOPUP)

SELECTION = {"variant": "fixed", "metric": "macro_song_within_primary"}


def _record(step: int, level: str, value: float, se: float, variant: str = "fixed") -> str:
    return json.dumps({"funnel_eval": {"step_now": step, "evaluated_step": step, "level": level,
                                       "selection": {"variant": variant, "metric": SELECTION["metric"]},
                                       "value": value, "se": se,
                                       "variants": {variant: {"macro_within_primary": value}}}})


def test_rows_from_jsonl_reads_the_summary_alias_and_keeps_the_latest_per_step(tmp_path: Path):
    path = tmp_path / "funnel_evals.jsonl"
    path.write_text("\n".join([_record(50, "l1", 0.70, 0.05),
                               _record(100, "l1", 0.80, 0.04),
                               _record(100, "l1", 0.81, 0.04),          # later record wins
                               _record(100, "l2", 0.90, 0.01),
                               "{not json"]), encoding="utf-8")
    l1 = TOPUP.rows_from_jsonl(path, "l1", SELECTION)
    assert set(l1) == {50, 100} and l1[100]["value"] == 0.81 and l1[100]["se"] == 0.04
    assert TOPUP.rows_from_jsonl(path, "l2", SELECTION)[100]["value"] == 0.90
    assert TOPUP.rows_from_jsonl(tmp_path / "missing.jsonl", "l1", SELECTION) == {}


def test_rows_from_jsonl_tolerates_blank_lines(tmp_path: Path):
    path = tmp_path / "funnel_evals.jsonl"
    path.write_text("\n" + _record(50, "l1", 0.7, 0.05) + "\n\n", encoding="utf-8")
    assert TOPUP.rows_from_jsonl(path, "l1", SELECTION)[50]["value"] == 0.7


def test_one_se_shortlist_widens_to_the_leader_band_and_respects_exclusions():
    rows = [{"step": 10, "value": 0.90, "se": 0.02},   # leader, floor = 0.88
            {"step": 20, "value": 0.885, "se": 0.01},  # inside the band
            {"step": 30, "value": 0.87, "se": 0.01},   # outside
            {"step": 40, "value": 0.95, "se": 0.05}]   # would be the leader if not excluded
    picked = TOPUP.one_se_shortlist(rows, top_k=5, se_scale=1.0, exclude={40})
    assert [row["step"] for row in picked] == [10, 20]
    assert [row["step"] for row in TOPUP.one_se_shortlist(rows, top_k=5, se_scale=0.2, exclude={40})] == [10]
    # the cap is a hard maximum, and it keeps the best first
    assert [row["step"] for row in TOPUP.one_se_shortlist(rows, top_k=1, se_scale=1.0, exclude={40})] == [10]
    assert TOPUP.one_se_shortlist([], top_k=3, se_scale=1.0) == []


def test_sha256_strings_matches_the_trainer_calling_convention():
    values = ["a", "b"]
    expected = hashlib.sha256(b"a\0b\0").hexdigest()
    assert TOPUP.sha256_strings(values) == expected


def test_load_valid_refuses_a_different_validation_split(tmp_path: Path):
    characters = tmp_path / "characters.jsonl"
    characters.write_text(json.dumps({"item_id": "i1", "song_id": "s1"}) + "\n", encoding="utf-8")
    labels = tmp_path / "labels.jsonl"
    labels.write_text(json.dumps({"item_id": "i1", "split": "validation"}) + "\n", encoding="utf-8")
    cfg = {"data": {"labels": str(labels), "characters": str(characters)},
           "training": {"seed": 1}, "stages": {"r2": {"validation_items": 0}}}
    valid, references = TOPUP.load_valid(cfg, {"selected_validation_item_ids_sha256": TOPUP.sha256_strings(["i1"])}, "r2")
    assert [row["item_id"] for row in valid] == ["i1"] and references["i1"][0]["song_id"] == "s1"
    with pytest.raises(SystemExit):
        TOPUP.load_valid(cfg, {"selected_validation_item_ids_sha256": "deadbeef"}, "r2")


def test_item_sample_falls_back_to_the_full_split():
    rows = [{"item_id": f"i{index}"} for index in range(5)]
    assert TOPUP.item_sample(rows, 0, 7) == rows
    assert len(TOPUP.item_sample(rows, 99, 7)) == 5
    assert len(TOPUP.item_sample(rows, 2, 7)) == 2


def _block(step: int, value: float, se: float, *, source: str = "run", level: str = "l2") -> dict:
    return {"level": level, "label": f"step-{step:06d}", "step": step, "source": source,
            "variants": {"fixed": {"macro_song_within_primary": value, "macro_song_se_primary": se}}}


def test_next_level_shortlist_merges_historical_records_and_drops_foreign_baselines():
    historical = {50: {"step": 50, "value": 0.785, "se": 0.01}}
    rounds = [_block(100, 0.80, 0.01), _block(200, 0.79, 0.01),
              _block(750, 0.99, 0.0, source="foreign")]  # collides with the run's own step 750
    picked = TOPUP.next_level_shortlist(current_records=historical, round_results=rounds, done_next=set(),
                                        selection=SELECTION, cap=5, se_scale=1.0)
    assert [row["step"] for row in picked] == [100, 200]          # foreign never promoted
    picked = TOPUP.next_level_shortlist(current_records=historical, round_results=rounds, done_next={100},
                                        selection=SELECTION, cap=5, se_scale=1.0)
    assert [row["step"] for row in picked] == [200, 50]           # already-done step excluded, 1-SE band kept
    picked = TOPUP.next_level_shortlist(current_records=historical, round_results=rounds, done_next=set(),
                                        selection=SELECTION, cap=1, se_scale=0.0)
    assert [row["step"] for row in picked] == [100]               # se_scale=0 -> strict argmax
