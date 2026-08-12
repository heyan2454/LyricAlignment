"""Stage-02 case selection tests: pure functions, no GPU / no real suite.

Covers stratum sampling constraints, GT firewall on built requests, R-A/R-B
variants only, skipped GT-bearing rows, no_gt_check, candidate index rebuild,
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


@pytest.fixture
def timeline_manifest(tmp_path):
    path = tmp_path / "LONG_TIMELINE_MANIFEST.jsonl"
    rows = [{
        "song_id": "s0",
        "duration_sec": 60.0,
        "concat_audio_path": str(tmp_path / "fake.wav"),
        "canonical_units": _unit_rows(30),
    }]
    with open(path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    return path


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


def _case(song="s0", case_id="case-a"):
    return {
        "case_id": case_id, "song_id": song, "window_id": f"{song}:w0:full",
        "stratum": "S3", "target_unit_ids": [5, 6, 7],
        "old_detector_state": "REJECT", "sampling_label": "bad",
    }


def test_build_requests_ra_rb_and_gt_clean(timeline_manifest, baseline_rows):
    requests, plan, skipped = case_selection.build_requests(
        [_case()], [str(timeline_manifest)], case_selection.load_jsonl(baseline_rows),
        model_id="model-x", checkpoint_id="ckpt-x",
    )
    assert skipped == []
    variants = {r["input_variant"] for r in requests}
    assert variants == {"R-A_unsafe_old_range", "R-B_safe_anchor_bounded"}
    for r in requests:
        assert r["schema_version"] == "research_v7_long_slot_v1"
        assert validate_no_gt_request(r) == []
        assert r["provenance"]["episode_id"] == "case-a"


def test_build_requests_skips_gt_rows(timeline_manifest, baseline_rows, monkeypatch):
    gt_row = {"request_id": "bad-1", "item_id": "s0", "gt_start_sec": 1.0}
    valid_row = {"request_id": "ok-1", "item_id": "s0", "input_variant": "R-A_unsafe_old_range"}

    def fake_build_proposals(*args, **kwargs):
        return [gt_row, valid_row], []

    monkeypatch.setattr(case_selection, "build_proposals", fake_build_proposals)
    requests, _plan, skipped = case_selection.build_requests(
        [_case()], [str(timeline_manifest)], case_selection.load_jsonl(baseline_rows),
        model_id="m", checkpoint_id="c",
    )
    assert [r["request_id"] for r in requests] == ["ok-1"]
    assert len(skipped) == 1
    assert skipped[0]["request_id"] == "bad-1"
    assert "gt_start_sec" in skipped[0]["forbidden"]


def test_no_gt_check_records(timeline_manifest, baseline_rows):
    requests, _plan, _skipped = case_selection.build_requests(
        [_case()], [str(timeline_manifest)], case_selection.load_jsonl(baseline_rows),
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


def test_run_stage_mocked(tmp_path, timeline_manifest, baseline_rows, monkeypatch):
    run_root = tmp_path / "run"
    pool_dir = run_root / "01_detector_audit"
    pool_dir.mkdir(parents=True)
    (pool_dir / "CASE_POOL.jsonl").write_text(
        "\n".join(json.dumps(c, ensure_ascii=False) for c in _make_pool(25)) + "\n"
    )
    meta_dir = run_root / "00_meta"
    meta_dir.mkdir(parents=True)
    cfg = {
        "timeline_manifests": [str(timeline_manifest)],
        "baseline_rows": str(baseline_rows),
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
    assert summary["n_requests"] > 0
    assert summary["n_candidate_index"] == summary["n_requests"]
    for artifact in ("cases", "requests", "no_gt_check", "forward", "candidate_index"):
        assert summary["artifacts"][artifact] is not None
    for name in ("CASES.jsonl", "REQUESTS.jsonl", "NO_GT_CHECK.jsonl", "CANDIDATE_INDEX.jsonl"):
        assert (run_root / "02_behavior" / name).exists()
