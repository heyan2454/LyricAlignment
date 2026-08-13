"""True R-S contract: full text, sparse timestamps, frozen-slot remerge."""
from __future__ import annotations

import pytest

from lyricalign.research_v7.real_executor import remerge_fixed_slots
from lyricalign.research_v7.requests import AlignmentRequest


def _request(**changes):
    base = dict(
        request_id="r-s", item_id="song", parent_request_id=None,
        audio_source="audio.wav", audio_start_sec=0.0, audio_end_sec=2.0,
        text_source="lyrics", text_start_index=0, text_end_index=3,
        text_units=("a", "b", "c"), timestamp_slot_indices=(1,),
        workflow_mode="unit_realign", mutation_type="realign",
        mutation_parameters={}, model_id="model", checkpoint_id="checkpoint",
        input_variant="R-S_sparse", active_slot_indices=(1,),
        fixed_slot_rows=(
            {"local_index": 0, "fixed_global_start_sec": 0.0, "fixed_global_end_sec": 0.2},
            {"local_index": 2, "fixed_global_start_sec": 1.0, "fixed_global_end_sec": 1.2},
        ),
        slot_constraint_schema="realign_sparse_fixed_v1",
    )
    base.update(changes)
    return AlignmentRequest(**base)


def test_real_sparse_request_requires_complete_active_fixed_partition():
    request = _request()
    request.validate()
    changed = _request(
        active_slot_indices=(0,), timestamp_slot_indices=(0,),
        fixed_slot_rows=(
            {"local_index": 1, "start_sec": .5, "end_sec": .7},
            {"local_index": 2, "start_sec": 1., "end_sec": 1.2},
        ))
    changed.validate()
    assert request.request_identity() != changed.request_identity()
    with pytest.raises(ValueError, match="partition"):
        _request(fixed_slot_rows=(
            {"local_index": 0, "start_sec": 0., "end_sec": .2},)).validate()


def test_remerge_fixed_slots_keeps_baseline_and_requires_complete_coverage():
    rows = remerge_fixed_slots(
        [{"global_character_index": 1, "fixed_global_start_sec": .45,
          "fixed_global_end_sec": .8, "decoder_kind": "official"}],
        [
            {"local_index": 0, "fixed_global_start_sec": 0., "fixed_global_end_sec": .2},
            {"local_index": 2, "fixed_global_start_sec": 1., "fixed_global_end_sec": 1.2},
        ],
        total_units=3,
    )
    assert [r["slot_origin"] for r in rows] == [
        "fixed_baseline", "active_forward", "fixed_baseline"]
    assert rows[0]["fixed_global_start_sec"] == 0.
    assert rows[2]["fixed_global_end_sec"] == 1.2
    with pytest.raises(ValueError, match="does not cover"):
        remerge_fixed_slots([], [], total_units=1)
