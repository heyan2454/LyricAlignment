import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AUDIT_PY = REPO_ROOT / "scripts" / "research_transition_recovery_detector" / "quick_correction_audit.py"


def _load_audit():
    spec = importlib.util.spec_from_file_location("quick_correction_audit", AUDIT_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


audit = _load_audit()


def test_truth_table_start_only_vs_two_boundary():
    """truth-table：good-start/bad-end 应命中 start-only 1s，但不得命中双边界 100ms。"""
    cases = [
        # (start_err_sec, end_err_sec, expect_start_hit_1s, expect_two_boundary_100ms)
        (0.05, 2.0, True, False),    # good-start / bad-end
        (0.05, 0.08, True, True),    # both good
        (1.5, 0.05, False, False),   # bad-start / good-end
        (1.5, 3.0, False, False),    # both bad
        (1.0, 0.0, True, False),     # start 恰在 1s 边界
        (0.0, 0.1, True, True),      # end 恰在 100ms 边界（含）
        (0.0, 0.100001, True, False),  # end 略超 100ms → 双边界 miss
        (0.100001, 0.0, True, False),  # start 略超 100ms → 双边界 miss，但 start-only 1s 命中
    ]
    for start_err, end_err, exp_start, exp_two in cases:
        got_start = audit.start_hit_1s(start_err)
        got_two = audit.both_boundaries_hit(start_err, end_err)
        assert got_start is exp_start, (
            f"start_hit_1s({start_err})={got_start}, expected {exp_start}"
        )
        assert got_two is exp_two, (
            f"both_boundaries_hit({start_err},{end_err})={got_two}, expected {exp_two}"
        )


def test_deprecated_alias_emit_compatible():
    """emit 同时给 canonical start_hit_1s 与 legacy_hit100(+deprecated)，legacy reader 可兼容。"""
    for start_err, exp_hit in ((0.05, True), (2.0, False)):
        metric = audit.emit_hit_metric(start_err)
        assert "start_hit_1s" in metric
        assert metric["start_hit_1s"] is exp_hit
        # legacy 兼容别名：值一致且显式 deprecated，绝不静默别名
        assert metric["legacy_hit100"] is exp_hit
        assert metric["legacy_hit100_deprecated"] is True
        # legacy reader 路径仍可用
        assert bool(metric["legacy_hit100"]) is exp_hit


def test_emit_no_aliasing_to_two_boundary():
    """canonical emit 不得把 start-only 语义伪装成双边界 100ms 字段。"""
    metric = audit.emit_hit_metric(0.05)
    assert "boundary_hit_100ms" not in metric
    assert "tolerance_hit_rates_ms" not in metric
    # start-only 1s 命中不应被当作双边界 100ms 命中读取
    assert audit.both_boundaries_hit(0.05, 2.0) is False


def test_classify_unknown_hit100_flagged():
    """无证据的 hit100 出现点必须 unknown+flagged，禁止臆测归类。"""
    cls = audit.classify_metric_token("hit100", "some_legacy_json: {\"hit100\": 0.9}", "unknown_source")
    assert cls["classification"] == "unknown"
    assert cls["flagged"] is True
    assert cls["canonical_name"] is None


def test_classify_known_hit100_with_evidence():
    """source_hint=window_gate_report.json 的 hit100 是双边界 100ms（keep，不 flag）。"""
    cls = audit.classify_metric_token(
        "hit100",
        "all_requests[] 字段名",
        "/tmp/opencode/window_gate_report.json",
    )
    assert cls["classification"] == "both_boundaries_100ms"
    assert cls["canonical_name"] == "hit100"
    assert cls["action"] == "keep"
    assert cls["flagged"] is False
    assert "tolerance_hit_rates_ms" in cls["evidence"] or "100" in cls["evidence"]


def test_classify_hit100_three_source_hints():
    """同一 token hit100 在不同 source_hint 下必须得到不同且正确的分类。"""
    win = audit.classify_metric_token("hit100", "", "/tmp/opencode/window_gate_report.json")
    assert win["classification"] == "both_boundaries_100ms", "window_gate 绝不允许 start_only_1s"
    assert win["canonical_name"] == "hit100"
    assert win["action"] == "keep"
    assert win["flagged"] is False

    sub = audit.classify_metric_token("hit100", "", "/tmp/opencode/eval_subwindow.py")
    assert sub["classification"] == "start_only_1s"
    assert sub["canonical_name"] == "start_hit_1s"
    assert sub["action"] == "rename"
    assert sub["flagged"] is False

    bare = audit.classify_metric_token("hit100", "hit100: 0.9", "")
    assert bare["classification"] == "unknown"
    assert bare["flagged"] is True
    assert bare["action"] == "none"

    sub_rule = audit.classify_metric_token("hit100", "", "/tmp/opencode/eval_rule_subwindow.py")
    assert sub_rule["classification"] == "start_only_1s"
    assert sub_rule["action"] == "rename"


def test_classify_two_boundary_tokens():
    """双边界 100ms 命中保留显式名，不归 start_only_1s。"""
    for token, canon in (
        ("tolerance_hit_rates_ms", "tolerance_hit_rates_ms"),
        ("SAFE_MAX_ERROR_SEC", "SAFE_MAX_ERROR_SEC"),
        ("safe100_label_schema", "safe100_grey100_250_unsafe250_structural_v1"),
        ("interval@100", "interval@100"),
    ):
        cls = audit.classify_metric_token(token, "boundary Safe <=100ms", "src")
        assert cls["classification"] == "both_boundaries_100ms", token
        assert cls["canonical_name"] == canon, token
        assert cls["flagged"] is False
