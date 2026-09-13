"""CPU tests for the funnelled-validation and cyclic-schedule machinery."""

from __future__ import annotations

import json

import pytest

torch = pytest.importorskip("torch")

from lyricalign.training.eval_funnel import FunnelPlanner, disk_mode
from lyricalign.training.eval_funnel_loop import (CyclicCosineScheduler, early_stop_decision,
                                                  nested_subsets)
from lyricalign.training.lr_schedule import cyclic_cosine_factor, is_cycle_end, warmup_steps_for


def test_cyclic_schedule_warms_up_anneals_and_decays_each_cycle():
    assert cyclic_cosine_factor(0, cycle_len=2000) == 0.0
    assert cyclic_cosine_factor(1, cycle_len=2000) == pytest.approx(0.01, abs=1e-6)
    warm = warmup_steps_for(2000, 0.05)
    assert cyclic_cosine_factor(warm, cycle_len=2000) == pytest.approx(1.0, abs=1e-6)
    assert cyclic_cosine_factor(2000, cycle_len=2000) == pytest.approx(0.0, abs=1e-6)
    assert cyclic_cosine_factor(2001, cycle_len=2000, cycle_peak_decay=0.8) == pytest.approx(0.008, abs=1e-6)
    assert cyclic_cosine_factor(2000 + warm, cycle_len=2000, cycle_peak_decay=0.8) == pytest.approx(0.8, abs=1e-6)
    assert is_cycle_end(2000, cycle_len=2000) and not is_cycle_end(2001, cycle_len=2000)


def test_scheduler_object_sets_group_lrs_and_survives_state_round_trip():
    parameter = torch.nn.Parameter(torch.zeros(1))
    optimizer = torch.optim.AdamW([{"params": [parameter], "lr": 1e-4}], weight_decay=0.0)
    scheduler = CyclicCosineScheduler(optimizer, cycle_len=100, warmup_ratio=0.05, cycle_peak_decay=0.5)
    assert scheduler.get_last_lr()[0] == pytest.approx(1e-4 * 0.2, rel=1e-6)
    for _ in range(100):
        scheduler.step()
    state = scheduler.state_dict()
    fresh = CyclicCosineScheduler(optimizer, cycle_len=100, warmup_ratio=0.05, cycle_peak_decay=0.5)
    fresh.load_state_dict(state)
    assert fresh.get_last_lr() == scheduler.get_last_lr()


def test_nested_subsets_are_nested_and_never_split_a_song():
    records = [{"item_id": f"i{k}", "song_id": f"s{k // 4}"} for k in range(120)]
    subsets = nested_subsets(records, fractions={"l1": 0.25, "l2": 0.5, "l3": 1.0})
    ids = {level: {row["item_id"] for row in rows} for level, rows in subsets.items()}
    assert ids["l1"] < ids["l2"] < ids["l3"]
    assert len(ids["l3"]) == len(records)
    for level, rows in subsets.items():
        per_song: dict[str, int] = {}
        for row in rows:
            per_song[row["song_id"]] = per_song.get(row["song_id"], 0) + 1
        assert all(count == 4 for count in per_song.values()), (level, per_song)


def test_funnel_evaluates_each_candidate_once_per_level_and_promotes_by_ucb():
    planner = FunnelPlanner(l1_every=10, l2_max=2, l3_every=100, l3_top_k=1)
    for step in range(10, 61, 10):
        assert planner.register(step)
    assert planner.register(10) is False
    assert planner.pending(10) == [("l1", step) for step in range(10, 61, 10)]
    planner.record(10, "l1", 0.60, se=0.01)
    planner.record(20, "l1", 0.58, se=0.30)
    planner.record(30, "l1", 0.10, se=0.00)
    for step in (40, 50, 60):
        planner.record(step, "l1", 0.05, se=0.00)
    jobs = planner.pending(10)
    assert ("l2", 20) in jobs and len([j for j in jobs if j[0] == "l2"]) <= 2
    assert not any(j[1] == 30 for j in jobs)
    for _, step in list(jobs):
        planner.record(step, "l2", 0.6, se=0.01)
    assert planner.pending(11) == []
    l3_jobs = planner.pending(100)
    assert len(l3_jobs) == 1 and l3_jobs[0][0] == "l3"
    first_l3 = l3_jobs[0][1]
    planner.record(first_l3, "l3", 0.62, se=0.01)
    # a later round may admit the *next* ranked candidate (bounded by l3_top_k per round) ...
    second_round = planner.pending(200)
    assert len(second_round) <= 1 and all(j[0] == "l3" for j in second_round)
    # ... but a candidate is never evaluated at the same level twice
    assert all(j[1] != first_l3 for j in second_round)
    planner.record(second_round[0][1], "l3", 0.61, se=0.01)
    assert planner.pending(200) == []


def test_pick_uses_one_standard_error_and_prefers_the_earlier_step():
    planner = FunnelPlanner(l1_every=10, l2_max=8, l3_every=10, l3_top_k=8)
    for step, value, se in ((10, 0.90, 0.02), (20, 0.905, 0.02), (30, 0.95, 0.05)):
        planner.register(step)
        planner.record(step, "l3", value, se=se)
    pick = planner.pick()
    assert pick["rule"] == "one_standard_error_earliest"
    assert pick["selected_step"] == 10
    assert pick["selected_from_level"] == "l3"


def test_early_stop_fires_only_after_repeated_flat_rounds():
    assert early_stop_decision([{"best": 0.90, "best_se": 0.01}] * 3, patience_cycles=2)["stop"] is True
    progressing = [{"best": 0.90, "best_se": 0.01}, {"best": 0.95, "best_se": 0.01},
                   {"best": 0.952, "best_se": 0.01}]
    assert early_stop_decision(progressing, patience_cycles=2)["stop"] is False
    assert early_stop_decision([{"best": None}], patience_cycles=1)["stop"] is False


def test_disk_mode_degrades_to_weights_only_near_the_floor():
    assert disk_mode(25.0, floor_gb=20.0) == "full"
    assert disk_mode(19.9, floor_gb=20.0) == "weights_only"


def test_funnel_status_is_json_serialisable():
    planner = FunnelPlanner(l1_every=10)
    planner.register(10)
    planner.record(10, "l1", 0.5, se=0.1)
    assert json.loads(json.dumps(planner.status(10)))["candidates"] == 1


def test_l2_per_round_spreads_promotions_instead_of_letting_early_steps_starve_the_budget():
    """Reproduces the first from-official run: 16/16 L2 slots eaten by steps <= 900."""
    planner = FunnelPlanner(l1_every=10, l2_max=4, l3_every=100, l3_top_k=8,
                            ucb_scale=0.0, l2_per_round=1)
    for step in range(10, 60, 10):
        planner.register(step)
        planner.record(step, "l1", 0.5, se=0.0, at_step=step)
    first = [job for job in planner.pending(10) if job[0] == "l2"]
    assert len(first) == 1, first
    planner.record(first[0][1], "l2", 0.5, se=0.0, at_step=10)
    # the round quota is spent, so no further promotion inside the same round ...
    assert [job for job in planner.pending(10) if job[0] == "l2"] == []
    # ... but the next round may promote the next-ranked candidate
    second = [job for job in planner.pending(100) if job[0] == "l2"]
    assert len(second) == 1 and second[0][1] != first[0][1], second


def test_saturated_l2_pool_still_feeds_later_l3_rounds_with_a_per_round_quota():
    planner = FunnelPlanner(l1_every=10, l2_max=2, l3_every=100, l3_top_k=1,
                            ucb_scale=0.0, l2_per_round=1)
    for step in (10, 20, 30):
        planner.register(step)
        planner.record(step, "l1", 0.5, se=0.0, at_step=step)
    for job in list(planner.pending(10)):
        planner.record(job[1], job[0], 0.5, se=0.0, at_step=10)
    assert planner.best("l2") is not None
    l3_first = [job for job in planner.pending(100) if job[0] == "l3"]
    assert len(l3_first) == 1
    planner.record(l3_first[0][1], "l3", 0.5, se=0.0, at_step=100)
    # a candidate promoted in round 1 is eligible for the round-2 full-set evaluation
    promoted = [job for job in planner.pending(200) if job[0] == "l2"]
    assert len(promoted) == 1
    planner.record(promoted[0][1], "l2", 0.5, se=0.0, at_step=200)
    l3_second = [job for job in planner.pending(200) if job[0] == "l3"]
    assert len(l3_second) == 1 and l3_second[0][1] != l3_first[0][1]


def test_public_best_level_reports_the_incumbent():
    planner = FunnelPlanner(l1_every=10, l2_max=4, l3_every=100)
    planner.register(10)
    planner.record(10, "l1", 0.5, se=0.01, at_step=10)
    planner.register(20)
    planner.record(20, "l1", 0.7, se=0.02, at_step=20)
    assert planner.best("l1") == (20, 0.7, 0.02)
    assert planner.best("l2") is None
    with pytest.raises(ValueError):
        planner.best("bogus")
    assert planner.status(20)["params"]["l2_per_round"] is None


def test_keep_best_admission_lets_a_late_challenger_displace_a_weak_early_finalist():
    """The first from-official run filled all 16 finalist slots with steps <= 900."""
    planner = FunnelPlanner(l1_every=10, l2_max=2, l2_budget=3, l3_every=100, l3_top_k=1,
                            ucb_scale=0.0)
    planner.register(10)
    planner.record(10, "l1", 0.60, se=0.0, at_step=10)   # weak on the medium subset, arrives first
    planner.record(20, "l1", 0.60, se=0.0, at_step=20)
    jobs = [job for job in planner.pending(20) if job[0] == "l2"]
    assert sorted(job[1] for job in jobs) == [10, 20]
    planner.record(10, "l2", 0.30, se=0.0, at_step=20)
    planner.record(20, "l2", 0.60, se=0.0, at_step=20)
    # the finalist set is full and the budget is not: a weak newcomer is not worth an evaluation ...
    planner.record(30, "l1", 0.31, se=0.0, at_step=30)
    assert [job for job in planner.pending(30) if job[0] == "l2"] == []
    # ... but a strong one displaces step 10, whose L2 (0.30) is the weakest finalist
    planner.record(40, "l1", 0.95, se=0.0, at_step=40)
    assert [job[1] for job in planner.pending(40) if job[0] == "l2"] == [40]
    planner.record(40, "l2", 0.90, se=0.0, at_step=40)
    assert planner.best("l2")[0] == 40
    # with the budget (3 = 2 initial + 1 churn) spent, not even a perfect newcomer gets in
    planner.record(50, "l1", 0.99, se=0.0, at_step=50)
    assert [job for job in planner.pending(50) if job[0] == "l2"] == []


def test_without_a_budget_keep_best_admission_never_admits_a_challenger():
    planner = FunnelPlanner(l1_every=10, l2_max=1, l3_every=100, ucb_scale=0.0)
    planner.register(10)
    planner.record(10, "l1", 0.30, se=0.0, at_step=10)
    assert [job[1] for job in planner.pending(10) if job[0] == "l2"] == [10]
    planner.record(10, "l2", 0.30, se=0.0, at_step=10)
    planner.record(20, "l1", 0.99, se=0.0, at_step=20)
    assert [job for job in planner.pending(20) if job[0] == "l2"] == []   # default budget == l2_max
