"""Stage-02 case selection tests: pure functions, no GPU / no real suite.

Covers stratum sampling constraints, GT firewall on built requests, R-A/R-B
variants only, skipped GT-bearing rows, no_gt_check, window-restricted text
unit ids, skipped_cases (no single-variant samples), candidate index rebuild,
and a fully mocked run_stage (subprocess seam never fires).
"""
from __future__ import annotations

import json

import pytest

from lyricalign.realign_gate import case_selection
from lyricalign.realign_recovery.gt_firewall import validate_no_gt_request


def _unit_rows(n=30, span=1.0):
    rows = []
    for i in range(n):
        rows.append({
            "canonical_unit_id": i,
            "start_sec": i * span,
            "end_sec": i * span + 0.8,
            "source_segment_id": 0,
            "source_unit_index": i,
            "text": "字",
        })
    return rows


def _timeline_rows(n_songs, n_units=30):
    rows = []
    for s in range(n_songs):
        rows.append({
            "song_id": f"s{s}",
            "duration_sec": 60.0,
            "concat_audio_path": "/fake/data/fake.wav",
            "canonical_units": _unit_rows(n_units),
        })
    return rows


def _window_rows(n_songs, n_units=30):
    """P0 BASELINE_WINDOW_INDEX rows: one 60s window per song."""
    rows = []
    for s in range(n_songs):
        rows.append({
            "song_id": f"s{s}",
            "window_index": 0,
            "window_id": f"s{s}:w0:full",
            "audio_path": f"/fake/data/s{s}_w0.wav",
            "audio_start_sec": 0.0,
            "audio_end_sec": float(n_units) * 1.0 - 0.2,
            "text_unit_start": 0,
            "text_unit_end": n_units - 1,
            "provenance": {
                "text_unit_start": 0,
                "text_unit_end": n_units - 1,
                "window_start_sec": 0.0,
                "window_end_sec": 60.0,
            },
        })
    return rows


def _shadow_rows(n_songs, n_units=30, unsafe_intervals=None, accept_ids=(4, 8)):
    """P0 BASELINE_DETECTOR_SHADOW rows: units carry start/end/p_bad/state."""
    unsafe_intervals = unsafe_intervals if unsafe_intervals is not None else [[15.0, 20.0]]
    rows = []
    for s in range(n_songs):
        units = {}
        for i in range(n_units):
            in_unsafe = any(i < b and i + 0.8 > a for a, b in unsafe_intervals)
            units[str(i)] = {
                "start_sec": i * 1.0,
                "end_sec": i * 1.0 + 0.8,
                "p_bad": 0.9 if in_unsafe else 0.1,
                "state": "ACCEPT" if i in accept_ids else ("REJECT" if in_unsafe else "UNCERTAIN"),
            }
        rows.append({
            "song_id": f"s{s}",
            "window_index": 0,
            "detector_shadow": {
                "unsafe_intervals": unsafe_intervals,
                "units": units,
            },
        })
    return rows


def _write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    return path


@pytest.fixture
def timeline_manifest(tmp_path):
    return _write_jsonl(tmp_path / "LONG_TIMELINE_MANIFEST.jsonl", _timeline_rows(1))


@pytest.fixture
def window_index_rows(tmp_path):
    return _write_jsonl(tmp_path / "BASELINE_WINDOW_INDEX.jsonl", _window_rows(1))


@pytest.fixture
def detector_shadow_rows(tmp_path):
    return _write_jsonl(tmp_path / "BASELINE_DETECTOR_SHADOW.jsonl", _shadow_rows(1))


@pytest.fixture
def baseline_rows(tmp_path):
    path = tmp_path / "BASELINE.jsonl"
    rows = [{
        "song_id": "s0",
        "window_index": 0,
        "detector_shadow": {"unsafe_intervals": [[15.0, 20.0]]},
    }]
    with open(path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    return path


def _make_pool(n_songs=25):
    rows = []
    spec = [
        ("S1", "ACCEPT", 50),
        ("S2", "REJECT", 100),
        ("S3", "REJECT", 2000),
        ("S4", "ACCEPT", 1500),
    ]
    for s in range(n_songs):
        sid = f"s{s}"
        for st, state, err in spec:
            rows.append({
                "case_id": f"{sid}-{st}",
                "song_id": sid,
                "window_id": f"{sid}:w0:full",
                "target_unit_ids": [5, 6, 7],
                "stratum_placeholder": st,
                "old_detector_state": state,
                "old_error_ms": err,
                "source": "test",
            })
    return rows


def _case(song="s0", case_id="case-a"):
    return {
        "case_id": case_id, "song_id": song, "window_id": f"{song}:w0:full",
        "stratum": "S3", "target_unit_ids": [5, 6, 7],
        "old_detector_state": "REJECT", "sampling_label": "bad",
    }


def test_parse_window_index_baseline_format():
    assert case_selection._parse_window_index("会长大的幸福:0") == 0
    assert case_selection._parse_window_index("会长大的幸福:1") == 1
    assert case_selection._parse_window_index("会长大的幸福:2") == 2
    assert case_selection._parse_window_index("已是两条路上的人:3") == 3


def test_parse_window_index_legacy_formats():
    assert case_selection._parse_window_index("s0:w0:full") == 0
    assert case_selection._parse_window_index("s0:w1:full") == 1
    assert case_selection._parse_window_index("s0:w2") == 2
    assert case_selection._parse_window_index(3) == 3
    assert case_selection._parse_window_index(None) == 0


def test_sample_strata_constraints():
    cases = case_selection.sample_strata(
        _make_pool(25), n_target=60, s2_share=0.30, seed=0,
        max_per_song=3, max_per_song_stratum=1,
    )
    assert 60 <= len(cases) <= 100
    strata = {}
    per_song_per_stratum = {}
    per_song = {}
    for c in cases:
        strata[c["stratum"]] = strata.get(c["stratum"], 0) + 1
        key = (c["song_id"], c["stratum"])
        per_song_per_stratum[key] = per_song_per_stratum.get(key, 0) + 1
        per_song[c["song_id"]] = per_song.get(c["song_id"], 0) + 1
        for field in ("case_id", "song_id", "window_id", "stratum",
                      "target_unit_ids", "old_detector_state", "sampling_label"):
            assert field in c
    assert strata.get("S2", 0) / len(cases) == pytest.approx(0.30)
    assert 0.25 <= strata.get("S2", 0) / len(cases) <= 0.35
    assert max(per_song_per_stratum.values()) <= 1
    assert max(per_song.values()) <= 3


def test_sample_strata_excludes_without_gt_error():
    pool = [{
        "case_id": "c1", "song_id": "s0", "window_id": "s0:w0:full",
        "target_unit_ids": [5, 6, 7], "old_detector_state": "REJECT",
        "old_error_ms": None,
    }]
    cases = case_selection.sample_strata(
        pool, n_target=60, s2_share=0.30, seed=0,
        max_per_song=3, max_per_song_stratum=1,
    )
    assert cases == []


def test_sample_strata_excludes_unclassifiable():
    pool = [{
        "case_id": "c-amb", "song_id": "s0", "window_id": "s0:w0:full",
        "target_unit_ids": [5, 6, 7], "old_detector_state": "ACCEPT",
        "old_error_ms": 500,
    }]
    cases = case_selection.sample_strata(
        pool, n_target=60, s2_share=0.30, seed=0,
        max_per_song=3, max_per_song_stratum=1,
    )
    assert cases == []


def test_window_text_unit_ids_windowed():
    assert case_selection._window_text_unit_ids(None) == []
    assert case_selection._window_text_unit_ids({}) == []
    assert case_selection._window_text_unit_ids({"text_unit_start": 5, "text_unit_end": 10}) == [5, 6, 7, 8, 9, 10]
    assert case_selection._window_text_unit_ids({"text_unit_end": 29, "text_unit_start": 0}) == list(range(30))
    prov_fallback = case_selection._window_text_unit_ids(
        {"provenance": {"text_unit_start": 2, "text_unit_end": 4}})
    assert prov_fallback == [2, 3, 4]
    assert case_selection._window_text_unit_ids(
        {"text_unit_start": 10, "text_unit_end": 5}) == [5, 6, 7, 8, 9, 10]


def test_build_requests_ra_rb_pair_shared_identity(
        timeline_manifest, window_index_rows, detector_shadow_rows):
    requests, plan, skipped_firewall, skipped_cases = case_selection.build_requests(
        [_case()], [str(timeline_manifest)],
        case_selection.load_jsonl(window_index_rows),
        detector_shadow_rows=case_selection.load_jsonl(detector_shadow_rows),
        model_id="model-x", checkpoint_id="ckpt-x",
    )
    assert skipped_firewall == []
    assert skipped_cases == []
    variants = {r["input_variant"] for r in requests}
    assert variants == {"R-U_unit_local", "R-A_unsafe_old_range", "R-B_safe_anchor_bounded"}
    assert len(requests) == 3
    assert len(plan) == 3

    ra = next(r for r in requests if r["input_variant"] == "R-A_unsafe_old_range")
    rb = next(r for r in requests if r["input_variant"] == "R-B_safe_anchor_bounded")
    for r in (ra, rb):
        assert r["schema_version"] == "research_v7_long_slot_v1"
        assert validate_no_gt_request(r) == []
        assert r["provenance"]["episode_id"] == "case-a"
    shared = ("item_id", "source_song_id", "audio_source")
    for field in shared:
        assert ra[field] == rb[field]
    for field in ("source_window_id", "window_start_sec", "window_end_sec",
                  "audio_start_sec", "audio_end_sec", "target_unit_ids",
                  "target_unit_start", "target_unit_end"):
        assert ra["provenance"][field] == rb["provenance"][field]
    assert ra["provenance"]["episode_id"] == rb["provenance"]["episode_id"]
    assert ra["mutation_parameters"]["proposal_method"] != rb["mutation_parameters"]["proposal_method"]
    assert ra["request_id"] != rb["request_id"]
    assert (ra["audio_start_sec"], ra["audio_end_sec"]) == (3.0, 9.8)
    assert (rb["audio_start_sec"], rb["audio_end_sec"]) == (4.8, 8.0)


def test_build_requests_sparse_uses_full_local_text_and_fixed_baseline(
        timeline_manifest, window_index_rows, detector_shadow_rows):
    requests, _plan, firewall, skipped = case_selection.build_requests(
        [_case()], [str(timeline_manifest)],
        case_selection.load_jsonl(window_index_rows),
        detector_shadow_rows=case_selection.load_jsonl(detector_shadow_rows),
        model_id="model-x", checkpoint_id="ckpt-x", include_sparse=True,
    )
    assert not firewall
    assert not [x for x in skipped if x["reason"] == "r_s_incomplete_active_fixed_partition"]
    sparse = next(r for r in requests if r["input_variant"] == "R-S_sparse_fixed")
    assert len(sparse["text_units"]) > len(sparse["active_slot_indices"])
    assert sparse["timestamp_slot_indices"] == sparse["active_slot_indices"]
    assert sparse["slot_constraint_schema"] == "realign_sparse_fixed_v1"
    active = set(sparse["active_slot_indices"])
    fixed = {r["local_index"] for r in sparse["fixed_slot_rows"]}
    assert active.isdisjoint(fixed)
    assert active | fixed == set(range(len(sparse["text_units"])))
    assert sparse["provenance"]["target_unit_ids"] == _case()["target_unit_ids"]
    assert sparse["canonical_ids"] == sorted(sparse["canonical_ids"])


def test_legacy_whole_window_target_is_localized_to_detector_span():
    units = {
        i: {"state": "REJECT" if 10 <= i <= 20 else "ACCEPT", "p_bad": .9 if i == 15 else .5}
        for i in range(30)
    }
    result = case_selection._localize_target_ids(list(range(30)), units)
    assert result == list(range(10, 18))


def test_sparse_invalid_shadow_geometry_falls_back_to_canonical_timeline(
        timeline_manifest, window_index_rows, detector_shadow_rows):
    shadows = case_selection.load_jsonl(detector_shadow_rows)
    shadows[0]["detector_shadow"]["units"]["4"].update({"start_sec": 10.0, "end_sec": 1.0})
    reqs, _plan, _fw, _skipped = case_selection.build_requests(
        [_case()], [str(timeline_manifest)], case_selection.load_jsonl(window_index_rows),
        detector_shadow_rows=shadows, model_id="m", checkpoint_id="c",
        include_sparse=True, require_paired_rb=False)
    sparse = next(r for r in reqs if r["input_variant"] == "R-S_sparse_fixed")
    repaired = next(r for r in sparse["fixed_slot_rows"] if r["canonical_unit_id"] == 4)
    assert repaired["baseline_source"] == "canonical_timeline_fallback_invalid_shadow_geometry"
    assert repaired["fixed_global_end_sec"] >= repaired["fixed_global_start_sec"]


def test_build_requests_rejects_null_rb(timeline_manifest, window_index_rows, detector_shadow_rows):
    shadows = case_selection.load_jsonl(detector_shadow_rows)
    # Remove the only left ACCEPT anchor for this target.
    shadows[0]["detector_shadow"]["units"]["4"]["state"] = "UNCERTAIN"
    reqs, _plan, _fw, skipped = case_selection.build_requests(
        [_case()], [str(timeline_manifest)], case_selection.load_jsonl(window_index_rows),
        detector_shadow_rows=shadows, model_id="m", checkpoint_id="c")
    assert reqs == []
    assert any(s["reason"] == "r_b_missing_bilateral_accept_anchors" for s in skipped)


def test_build_requests_adaptive_mode_keeps_core_families_without_rb(
        timeline_manifest, window_index_rows, detector_shadow_rows):
    shadows = case_selection.load_jsonl(detector_shadow_rows)
    shadows[0]["detector_shadow"]["units"]["4"]["state"] = "UNCERTAIN"
    reqs, _plan, _fw, skipped = case_selection.build_requests(
        [_case()], [str(timeline_manifest)], case_selection.load_jsonl(window_index_rows),
        detector_shadow_rows=shadows, model_id="m", checkpoint_id="c",
        include_sparse=True, require_paired_rb=False,
    )
    variants = {r["input_variant"] for r in reqs}
    assert {"R-U_unit_local", "R-A_unsafe_old_range", "R-S_sparse_fixed"} <= variants
    assert "R-B_safe_anchor_bounded" not in variants
    assert any(s["reason"] == "r_b_missing_bilateral_accept_anchors" for s in skipped)


def test_build_requests_skips_gt_rows(timeline_manifest, window_index_rows, monkeypatch):
    gt_row = {"request_id": "bad-1", "item_id": "s0", "gt_start_sec": 1.0, "gt_path": "x"}
    valid_row = {"request_id": "ok-1", "item_id": "s0", "input_variant": "R-A_unsafe_old_range"}

    def fake_construct(*args, **kwargs):
        return [gt_row, valid_row], [], []

    monkeypatch.setattr(case_selection, "construct_case_pairs", fake_construct)
    requests, _plan, skipped_firewall, skipped_cases = case_selection.build_requests(
        [_case()], [str(timeline_manifest)], case_selection.load_jsonl(window_index_rows),
        model_id="m", checkpoint_id="c",
    )
    assert [r["request_id"] for r in requests] == ["ok-1"]
    assert skipped_cases == []
    assert len(skipped_firewall) == 1
    assert skipped_firewall[0]["request_id"] == "bad-1"
    assert "gt_start_sec" in skipped_firewall[0]["forbidden"]


def test_build_requests_skips_unconstructable_cases(
        timeline_manifest, window_index_rows, detector_shadow_rows, tmp_path):
    cases = [
        {"case_id": "c-noshadow", "song_id": "s0", "window_id": "s0:w0:full",
         "stratum": "S3", "target_unit_ids": [5, 6, 7]},
        {"case_id": "c-nowindow", "song_id": "s0", "window_id": "s0:w5:full",
         "stratum": "S3", "target_unit_ids": [5, 6, 7]},
        {"case_id": "c-nounsafe", "song_id": "s9", "window_id": "s9:w0:full",
         "stratum": "S3", "target_unit_ids": [5, 6, 7]},
    ]
    no_unsafe = _shadow_rows(1, unsafe_intervals=[])
    no_unsafe[0]["song_id"] = "s9"
    no_unsafe[0]["window_id"] = "s9:w0:full"
    no_unsafe[0]["window_index"] = 0
    shadow_path = tmp_path / "SHADOW_PARTIAL.jsonl"
    _write_jsonl(shadow_path, no_unsafe)
    window_path = tmp_path / "WINDOW_PARTIAL.jsonl"
    _write_jsonl(window_path, _window_rows(1) + [{
        "song_id": "s9", "window_index": 0, "window_id": "s9:w0:full",
        "audio_path": "/fake/data/s9_w0.wav", "audio_start_sec": 0.0,
        "audio_end_sec": 29.8, "text_unit_start": 0, "text_unit_end": 29,
        "provenance": {"text_unit_start": 0, "text_unit_end": 29},
    }])

    requests, _plan, _fw, skipped_cases = case_selection.build_requests(
        cases, [str(timeline_manifest)],
        window_index_rows=case_selection.load_jsonl(window_path),
        detector_shadow_rows=case_selection.load_jsonl(shadow_path),
        model_id="m", checkpoint_id="c",
    )
    assert requests == []
    assert len(skipped_cases) == 3
    reasons = {s["case_id"]: s["reason"] for s in skipped_cases}
    assert reasons["c-noshadow"] == "detector_shadow_not_found"
    assert reasons["c-nowindow"] == "window_not_found_in_baseline_window_index"
    assert reasons["c-nounsafe"] == "no_unsafe_intervals"
    for s in skipped_cases:
        assert set(s) == {"song_id", "window_id", "case_id", "reason"}


def test_build_requests_window_restricted_text_ids(
        timeline_manifest, window_index_rows, detector_shadow_rows):
    requests, _plan, _fw, _skipped = case_selection.build_requests(
        [_case()], [str(timeline_manifest)],
        case_selection.load_jsonl(window_index_rows),
        detector_shadow_rows=case_selection.load_jsonl(detector_shadow_rows),
        model_id="m", checkpoint_id="c",
    )
    for r in requests:
        lo, hi = r["provenance"]["text_unit_start"], r["provenance"]["text_unit_end"]
        assert 0 <= lo <= hi <= 29
        assert hi - lo + 1 == len(r["text_units"])


def test_no_gt_check_records(timeline_manifest, window_index_rows):
    requests, _plan, _fw, _skipped = case_selection.build_requests(
        [_case()], [str(timeline_manifest)], case_selection.load_jsonl(window_index_rows),
        model_id="m", checkpoint_id="c",
    )
    checks = case_selection.no_gt_check(requests)
    assert len(checks) == len(requests)
    for c in checks:
        assert c["validated"] is True
        assert c["forbidden"] == []

    checks = case_selection.no_gt_check([{"request_id": "gt-x", "gt_path": "x"}])
    assert checks[0]["validated"] is False
    assert "gt_path" in checks[0]["forbidden"]


def test_build_candidate_index(tmp_path):
    out_root = tmp_path / "forward"
    evidence_dir = out_root / "evidence"
    evidence_dir.mkdir(parents=True)
    (evidence_dir / "cid-ra.json").write_text(json.dumps({"attempt": {"status": "ok"}}))
    manifest = {
        "requests_identity": [
            {"item_id": "s0", "request_id": "req-ra", "request_identity": "cid-ra", "status": "ok"},
            {"item_id": "s0", "request_id": "req-miss", "request_identity": None, "status": "ok"},
        ],
        "cache_keys": ["cid-ra"],
        "evidence_inventory": [{"path": str(evidence_dir / "cid-ra.json"), "sha256": "x", "status": "ok"}],
    }
    (out_root / "RUN_MANIFEST.json").write_text(json.dumps(manifest))

    requests = [
        {"request_id": "req-ra", "input_variant": "R-A_unsafe_old_range",
         "provenance": {"episode_id": "case-a"}},
        {"request_id": "req-rb", "input_variant": "R-B_safe_anchor_bounded",
         "provenance": {"episode_id": "case-a"}},
    ]
    index = case_selection.build_candidate_index(out_root, requests)
    by_id = {i["request_id"]: i for i in index}
    assert by_id["req-ra"]["variant"] == "R-A_unsafe_old_range"
    assert by_id["req-ra"]["case_id"] == "case-a"
    assert by_id["req-ra"]["content_idn"] == "cid-ra"
    assert by_id["req-ra"]["evidence_path"] == str(evidence_dir / "cid-ra.json")
    assert by_id["req-ra"]["status"] == "ok"
    assert by_id["req-rb"]["content_idn"] is None
    assert by_id["req-rb"]["evidence_path"] is None


def test_run_stage_mocked(tmp_path, monkeypatch):
    run_root = tmp_path / "run"
    pool_dir = run_root / "01_detector_audit"
    pool_dir.mkdir(parents=True)
    (pool_dir / "CASE_POOL.jsonl").write_text(
        "\n".join(json.dumps(c, ensure_ascii=False) for c in _make_pool(25)) + "\n"
    )
    inventory_dir = run_root / "00_inventory"
    inventory_dir.mkdir(parents=True)
    timeline_full = _write_jsonl(tmp_path / "LONG_TIMELINE_MANIFEST_FULL.jsonl", _timeline_rows(25))
    window_path = _write_jsonl(inventory_dir / "BASELINE_WINDOW_INDEX.jsonl", _window_rows(25))
    shadow_path = _write_jsonl(inventory_dir / "BASELINE_DETECTOR_SHADOW.jsonl", _shadow_rows(25))
    meta_dir = run_root / "00_meta"
    meta_dir.mkdir(parents=True)
    cfg = {
        "timeline_manifests": [str(timeline_full)],
        "baseline_rows": [str(window_path)],
        "n_target": 60, "s2_share": 0.30, "seed": 0,
        "max_per_song": 3, "max_per_song_stratum": 1,
        "model_id": "model-x", "checkpoint_id": "ckpt-x",
    }
    cfg_path = meta_dir / "CONFIG.json"
    cfg_path.write_text(json.dumps(cfg))

    called = []

    def fake_invoke(argv, env=None):
        called.append(argv)
        def argval(name):
            for i, a in enumerate(argv):
                if a == name and i + 1 < len(argv):
                    return argv[i + 1]
            return None
        out_root = __import__("pathlib").Path(argval("--out-root"))
        out_root.mkdir(parents=True, exist_ok=True)
        reqs = case_selection.load_jsonl(argval("--manifest"))
        identities = [{
            "item_id": r["item_id"], "request_id": r["request_id"],
            "request_identity": "cid-" + r["request_id"], "status": "ok",
        } for r in reqs]
        (out_root / "RUN_MANIFEST.json").write_text(json.dumps({
            "requests_identity": identities,
            "cache_keys": [i["request_identity"] for i in identities],
            "evidence_inventory": [],
        }))
        (out_root / "evidence").mkdir(exist_ok=True)
        for i in identities:
            (out_root / "evidence" / f"{i['request_identity']}.json").write_text(
                json.dumps({"attempt": {"status": "ok"}})
            )
        return {"returncode": 0, "stdout": "{}", "stderr": ""}

    monkeypatch.setattr(case_selection, "_invoke_suite", fake_invoke)
    summary = case_selection.run_stage(run_root, cfg_path, smoke=True, limit=2)

    assert called, "run_stage must reach the injected suite seam (no real subprocess)"
    assert summary["result_status"] == "ok"
    assert summary["n_cases"] == 60
    assert summary["n_gt_violations"] == 0
    assert summary["n_skipped"] == 0
    assert summary["n_requests"] == 3 * summary["n_cases"]
    assert summary["n_candidate_index"] == summary["n_requests"]
    for artifact in ("cases", "requests", "no_gt_check", "proposal_plan",
                     "skipped_cases", "forward", "candidate_index"):
        assert summary["artifacts"][artifact] is not None
    for name in ("CASES.jsonl", "REQUESTS.jsonl", "NO_GT_CHECK.jsonl",
                 "SKIPPED_CASES.jsonl", "CANDIDATE_INDEX.jsonl"):
        assert (run_root / "02_behavior" / name).exists()

    cases = case_selection.load_jsonl(run_root / "02_behavior" / "CASES.jsonl")
    requests = case_selection.load_jsonl(run_root / "02_behavior" / "REQUESTS.jsonl")
    index = case_selection.load_jsonl(run_root / "02_behavior" / "CANDIDATE_INDEX.jsonl")
    by_case = {}
    for r in requests:
        by_case.setdefault(r["provenance"]["episode_id"], []).append(r["input_variant"])
    for c in cases:
        assert sorted(by_case[c["case_id"]]) == ["R-A_unsafe_old_range", "R-B_safe_anchor_bounded", "R-U_unit_local"]
    assert len(index) == len(requests)
    variants = {i["request_id"]: i["variant"] for i in index}
    assert all(v in ("R-U_unit_local", "R-A_unsafe_old_range", "R-B_safe_anchor_bounded") for v in variants.values())
