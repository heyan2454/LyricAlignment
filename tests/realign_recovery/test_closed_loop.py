"""Unit tests for E9 closed-loop core pure functions (pure-CPU synthetic data)."""

import pytest

from lyricalign.realign_recovery.closed_loop import (
    aggregate_repair_metrics,
    aggregate_route_cost,
    build_route_plan,
    build_shrink_candidates,
    classify_serial_recovery,
    route_decision,
)


class TestClassifySerialRecovery:
    def test_no_error_empty(self):
        assert classify_serial_recovery([]) == "no_error"

    def test_no_error_all_clean(self):
        assert classify_serial_recovery(["clean", "clean", "clean"]) == "no_error"

    def test_self_recover_single_error_then_clean(self):
        assert classify_serial_recovery(["clean", "error", "clean"]) == "self_recover"

    def test_self_recover_error_at_start_then_clean(self):
        assert classify_serial_recovery(["error", "clean", "clean"]) == "self_recover"

    def test_slow_recover_multiple_errors_then_clean(self):
        assert classify_serial_recovery(["clean", "error", "error", "clean"]) == "slow_recover"

    def test_persistent_single_tail_error(self):
        assert classify_serial_recovery(["clean", "error"]) == "persistent"

    def test_persistent_error_keeps_to_end(self):
        assert classify_serial_recovery(["clean", "clean", "error"]) == "persistent"

    def test_amplifying_error_block_reaches_end(self):
        assert classify_serial_recovery(["clean", "error", "error"]) == "amplifying"

    def test_amplifying_all_error(self):
        assert classify_serial_recovery(["error", "error", "error"]) == "amplifying"

    def test_occurrence_jump(self):
        assert classify_serial_recovery(["error", "clean", "error"]) == "occurrence_jump"

    def test_occurrence_jump_priority_over_persistent(self):
        assert classify_serial_recovery(["error", "clean", "error", "error"]) == "occurrence_jump"

    def test_unsafe_equivalent_to_error(self):
        assert classify_serial_recovery(["clean", "unsafe", "clean"]) == "self_recover"
        assert classify_serial_recovery(["unsafe", "clean", "unsafe"]) == "occurrence_jump"

    def test_unknown_marker_raises(self):
        with pytest.raises(ValueError):
            classify_serial_recovery(["clean", "unknown"])


class TestRouteDecision:
    def test_c0_always_none(self):
        assert route_decision("C0", "reject", -1.0) == {"action": "none", "writeback": False}

    def test_c0s_accept(self):
        assert route_decision("C0S", "accept", 0.5) == {
            "action": "shadow_only",
            "trigger": False,
            "writeback": False,
        }

    def test_c0s_trigger(self):
        assert route_decision("C0S", "reject", 0.5) == {
            "action": "shadow_only",
            "trigger": True,
            "writeback": False,
        }

    def test_c1_hold_on_trigger(self):
        assert route_decision("C1", "uncertain", 0.5) == {
            "action": "hold",
            "trigger": True,
            "writeback": False,
        }

    def test_c1_commit_when_accept(self):
        assert route_decision("C1", "accept", 0.5) == {
            "action": "commit_original",
            "trigger": False,
            "writeback": False,
        }

    def test_c2_unconditional_writeback(self):
        assert route_decision("C2", "reject", -1.0) == {
            "action": "unconditional_writeback",
            "writeback": True,
        }

    @pytest.mark.parametrize("score_delta", [0.1, 1e-9])
    def test_c3_selective_writeback_when_improved(self, score_delta):
        decision = route_decision("C3", "uncertain", score_delta)
        assert decision["action"] == "selective_writeback"
        assert decision["writeback"] is True

    @pytest.mark.parametrize("score_delta", [0.0, -0.5, None])
    def test_c3_hold_when_not_improved(self, score_delta):
        decision = route_decision("C3", "uncertain", score_delta)
        assert decision["action"] == "hold"
        assert decision["writeback"] is False

    def test_invalid_route_raises(self):
        with pytest.raises(ValueError):
            route_decision("C9", "accept", None)

    def test_invalid_trigger_state_raises(self):
        with pytest.raises(ValueError):
            route_decision("C0", "bad_state", None)


class TestBuildRoutePlan:
    def _bank(self):
        return [
            {"ownership": "e5_proposal", "episode_id": "ep-1", "raw_output_path": "/run/ev/ep-1-w0.json", "status": "ok"},
            {"ownership": "e5_proposal", "episode_id": "ep-1", "raw_output_path": "/run/ev/ep-1-w1.json", "status": "ok"},
            {"ownership": "other", "episode_id": "ep-1", "raw_output_path": "/run/other.json", "status": "ok"},
            {"ownership": "e5_proposal", "episode_id": "ep-2", "raw_output_path": "/run/ev/ep-2-w0.json", "status": "ok"},
        ]

    def _requests(self):
        return [
            {"provenance": {"episode_id": "ep-1"}, "input_variant": "window-0"},
            {"provenance": {"episode_id": "ep-1"}, "input_variant": "window-1"},
            {"provenance": {"episode_id": "ep-2"}, "input_variant": "continuation-window"},
        ]

    def test_structure(self):
        plan = build_route_plan(self._bank(), self._requests())
        assert plan["schema_version"]
        assert set(plan["routes"]) == {"C0", "C0S", "C1", "C2", "C3"}
        assert plan["n_episodes"] == 2
        assert plan["n_routes"] == 10
        assert set(plan["per_episode"]) == {"ep-1", "ep-2"}
        for ep in ("ep-1", "ep-2"):
            assert set(plan["per_episode"][ep]) == {"C0", "C0S", "C1", "C2", "C3"}

    def test_needs_forward_flags(self):
        plan = build_route_plan(self._bank(), self._requests())
        for rid in ("C0", "C0S", "C1"):
            assert plan["per_episode"]["ep-1"][rid]["needs_forward"] is False
        assert plan["per_episode"]["ep-1"]["C2"]["needs_forward"] is True
        assert plan["per_episode"]["ep-1"]["C3"]["needs_forward"] is True
        assert plan["per_episode"]["ep-2"]["C2"]["needs_forward"] is True
        assert plan["per_episode"]["ep-2"]["C3"]["needs_forward"] is True

    def test_episode_without_continuation(self):
        plan = build_route_plan([], [{"provenance": {"episode_id": "ep-x"}, "input_variant": "single"}])
        assert plan["per_episode"]["ep-x"]["C0"]["needs_forward"] is False
        assert plan["per_episode"]["ep-x"]["C2"]["needs_forward"] is False
        assert plan["per_episode"]["ep-x"]["C3"]["needs_forward"] is False

    def test_writeback_strategies(self):
        plan = build_route_plan(self._bank(), self._requests())
        strategies = {rid: plan["routes"][rid]["writeback_strategy"] for rid in plan["routes"]}
        assert strategies == {
            "C0": "none",
            "C0S": "none",
            "C1": "none",
            "C2": "full",
            "C3": "improved_only",
        }
        assert plan["per_episode"]["ep-1"]["C2"]["writeback_strategy"] == "full"
        assert plan["per_episode"]["ep-1"]["C3"]["writeback_strategy"] == "improved_only"

    def test_candidate_paths_only_e5(self):
        plan = build_route_plan(self._bank(), self._requests())
        assert plan["per_episode"]["ep-1"]["C3"]["candidate_paths"] == [
            "/run/ev/ep-1-w0.json",
            "/run/ev/ep-1-w1.json",
        ]
        assert plan["per_episode"]["ep-1"]["C3"]["n_candidates"] == 2
        assert plan["per_episode"]["ep-1"]["C3"]["n_requests"] == 2


class TestAggregateRouteCost:
    def test_cost(self):
        rows = [
            {"extra_forwards": 1, "processed_audio_sec": 60.0, "retry_count": 2, "cache_hit": True},
            {"extra_forwards": 0, "processed_audio_sec": 60.0, "retry_count": 0, "cache_hit": False},
        ]
        out = aggregate_route_cost(rows)
        assert out["n"] == 2
        assert out["total_extra_forwards"] == 1
        assert out["total_audio_sec"] == pytest.approx(120.0)
        assert out["total_retries"] == 2
        assert out["cache_hit_rate"] == pytest.approx(0.5)
        assert out["mean_wall_multiplier"] == pytest.approx(1.5)

    def test_cost_no_baseline(self):
        out = aggregate_route_cost([])
        assert out["n"] == 0
        assert out["mean_wall_multiplier"] is None
        assert out["cache_hit_rate"] == 0.0
        assert out["total_extra_forwards"] == 0
        assert out["total_audio_sec"] == 0.0


class TestAggregateRepairMetrics:
    def test_repair(self):
        rows = [
            {"repair_success": True, "safe_damage": False, "harmful_writeback": False},
            {"repair_success": True, "safe_damage": True, "harmful_writeback": False},
            {"repair_success": False, "safe_damage": True, "harmful_writeback": True},
        ]
        out = aggregate_repair_metrics(rows)
        assert out["n"] == 3
        assert out["repair_success_rate"] == pytest.approx(2 / 3)
        assert out["safe_damage_rate"] == pytest.approx(2 / 3)
        assert out["harmful_writeback_rate"] == pytest.approx(1 / 3)

    def test_repair_empty(self):
        out = aggregate_repair_metrics([])
        assert out["n"] == 0
        assert out["repair_success_rate"] == 0.0
        assert out["safe_damage_rate"] == 0.0
        assert out["harmful_writeback_rate"] == 0.0


class TestBuildShrinkCandidates:
    def test_shrink_default_max_retries(self):
        fails = [
            {"episode_id": "ep-1", "window_index": 0},
            {"episode_id": "ep-1", "window_index": 3},
            {"episode_id": "ep-2", "window_index": 1},
        ]
        out = build_shrink_candidates(fails)
        assert out["n_episodes"] == 2
        assert out["n_retries_total"] == 6
        assert len(out["candidates"]) == 6
        for c in out["candidates"]:
            assert c["shrink"]["half_window"] is True
            assert c["shrink"]["alternate_anchor"] == (c["retry_index"] % 2 == 1)
            assert c["retry_index"] in (0, 1)

    def test_shrink_custom_max_retries(self):
        out = build_shrink_candidates([{"episode_id": "ep-1", "window_index": 0}], max_retries=3)
        assert out["n_episodes"] == 1
        assert out["n_retries_total"] == 3
        assert [c["retry_index"] for c in out["candidates"]] == [0, 1, 2]
        assert [c["shrink"]["alternate_anchor"] for c in out["candidates"]] == [False, True, False]

    def test_shrink_candidates_fields(self):
        out = build_shrink_candidates([{"episode_id": "ep-1", "window_index": 7}], max_retries=1)
        c = out["candidates"][0]
        assert c["episode_id"] == "ep-1"
        assert c["window_index"] == 7
        assert c["retry_index"] == 0

    def test_shrink_invalid_max_retries(self):
        with pytest.raises(ValueError):
            build_shrink_candidates([{"episode_id": "ep-1", "window_index": 0}], max_retries=0)
