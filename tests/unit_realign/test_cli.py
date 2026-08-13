import json
import subprocess
import sys
from pathlib import Path


def test_population_and_expansion_cli(tmp_path):
    shadow = tmp_path / "shadow.jsonl"
    shadow.write_text(json.dumps({"song_id": "s", "window_index": 0, "detector_shadow": {
        "units": {"0": {"state": "ACCEPT"}, "1": {"state": "REJECT"}, "2": {"state": "ACCEPT"}}}}) + "\n")
    script = Path(__file__).parents[2] / "scripts/unit_realign/run_unit_realign.py"
    out = tmp_path / "run"
    env = {"PYTHONPATH": str(Path(__file__).parents[2] / "src")}
    first = subprocess.run([sys.executable, str(script), "population", "--out-root", str(out),
                            "--shadow", str(shadow), "--target", "2"],
                           text=True, capture_output=True, env=env)
    assert first.returncode == 0, first.stderr
    second = subprocess.run([sys.executable, str(script), "expand", "--out-root", str(out),
                             "--target", "1"], text=True, capture_output=True, env=env)
    assert second.returncode == 0, second.stderr
    assert (out / "01_requests/EXPANSION_REGIONS.jsonl").exists()


def _identity_context():
    return {
        "audio_sha256": "sha256:" + "a" * 64,
        "baseline_digest": "sha256:" + "b" * 64,
        "model_identity": "model:test",
        "checkpoint_identity": "ckpt:test",
        "decoder_identity": "decoder:test",
        "mapping_schema": "unit_realign_local_v2",
        "code_identity": "code:test",
        "text_adapter_identity": "adapter:test",
    }


def _local_units():
    return [
        {"canonical_unit_id": 1, "start_sec": 1.0, "end_sec": 1.4, "text": "a"},
        {"canonical_unit_id": 2, "start_sec": 1.5, "end_sec": 1.9, "text": "b"},
        {"canonical_unit_id": 3, "start_sec": 2.0, "end_sec": 2.4, "text": "c"},
    ]


def _run_cli(args, env):
    script = Path(__file__).parents[2] / "scripts/unit_realign/run_unit_realign.py"
    return subprocess.run([sys.executable, str(script), *args], text=True, capture_output=True, env=env)


def _read_jsonl(path):
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def test_execute_end_to_end_forwards_and_failures(tmp_path):
    from lyricalign.unit_realign.request_families import build_family_request
    env = {"PYTHONPATH": str(Path(__file__).parents[2] / "src")}
    root = tmp_path / "run"
    ready = build_family_request(family="R-U", song_id="s", region_id="r1",
                                 audio_path="s.wav", units=_local_units(), target_unit_ids=[2],
                                 identity_context=_identity_context())
    null = {"schema": "unit_realign_request_v2", "family": "R-NULL", "requested_family": "R-U",
            "song_id": "s", "region_id": "r2", "reason": "target_ids_not_in_local_units"}
    failed = dict(ready)
    failed.update(region_id="r3", request_id="s:r3:R-U", text_units=["a", "B", "c"],
                  request_identity="sha256:" + "f" * 64)
    requests = root / "01_requests" / "REQUESTS.jsonl"
    requests.parent.mkdir(parents=True)
    requests.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in (ready, null, failed)))
    proc = _run_cli(["execute", "--out-root", str(root)], env)
    assert proc.returncode == 0, proc.stderr
    forwards = _read_jsonl(root / "02_forwards" / "FORWARDS.jsonl")
    failures = _read_jsonl(root / "02_forwards" / "FAILURES.jsonl")
    status_rows = _read_jsonl(root / "01_requests" / "REQUEST_STATUS.jsonl")
    state = json.loads((root / "07_runtime" / "RUN_STATE.json").read_text())
    assert len(forwards) == 1
    assert forwards[0]["request_identity"] == ready["request_identity"]
    assert forwards[0]["region_id"] == "r1" and forwards[0]["family"] == "R-U"
    assert forwards[0]["status"] == "queued" and "forwarding" in forwards[0]
    assert len(failures) == 2
    assert {x["status"] for x in failures} == {"null", "invalid"}
    by_status = {x["status"]: x for x in failures}
    assert by_status["null"]["region_id"] == "r2" and by_status["null"]["reason"]
    assert by_status["invalid"]["region_id"] == "r3"
    assert len(status_rows) == 3
    assert {x["status"] for x in status_rows} == {"ready", "null", "invalid"}
    assert state["completed_identities"] == []
    assert state["queued_identities"] == [ready["request_identity"]]
    assert state["planned_identities"] == [ready["request_identity"]]
    assert state["null_identities"] == ["r2"]
    assert state["failed_identities"] == [failed["request_identity"]]
    assert state["completed_region_ids"] == []


def test_execute_materializes_requests_from_p1_regions(tmp_path):
    from lyricalign.unit_realign.request_families import build_family_request
    env = {"PYTHONPATH": str(Path(__file__).parents[2] / "src")}
    root = tmp_path / "run"
    region = {
        "region_id": "s:w0:unsafe:0", "song_id": "s", "language": "zh", "window_index": 0,
        "seed_kind": "unsafe_region", "target_unit_ids": [2], "detector_state": "UNSAFE",
        "overlap_interval_sec": [1.5, 1.9], "baseline_available": True,
        "left_anchor_candidates": [1], "right_anchor_candidates": [3],
        "stratum": "S1", "stratum_status": "eligible", "origin": "natural",
        "units": _local_units(), "identity_context": _identity_context(),
    }
    (root / "00_population").mkdir(parents=True)
    (root / "00_population" / "REGION_POOL.jsonl").write_text(json.dumps(region) + "\n")
    (root / "01_requests").mkdir(parents=True)
    (root / "01_requests" / "P1_SELECTED_REGIONS.jsonl").write_text(json.dumps(region) + "\n")
    proc = _run_cli(["execute", "--out-root", str(root)], env)
    assert proc.returncode == 0, proc.stderr
    requests = _read_jsonl(root / "01_requests" / "REQUESTS.jsonl")
    assert len(requests) == 4
    assert {r["family"] for r in requests} == {"R-U", "R-A", "R-B", "R-S"}
    assert {r["stratum"] for r in requests} == {"S1"}
    assert all(not r.get("status") for r in requests)
    expected = build_family_request(family="R-U", song_id="s", region_id=region["region_id"],
                                    audio_path="s.wav", units=region["units"], target_unit_ids=[2],
                                    identity_context=region["identity_context"])
    by_family = {r["family"]: r for r in requests}
    assert by_family["R-U"]["request_identity"] == expected["request_identity"]
    forwards = _read_jsonl(root / "02_forwards" / "FORWARDS.jsonl")
    assert len(forwards) == 4
    assert {f["region_id"] for f in forwards} == {region["region_id"]}
    assert {f["stratum"] for f in forwards} == {"S1"}
    state = json.loads((root / "07_runtime" / "RUN_STATE.json").read_text())
    assert state["completed_region_ids"] == []
    assert state["completed_identities"] == []
    assert sorted(state["queued_identities"]) == sorted(r["request_identity"] for r in requests)
    assert sorted(state["planned_identities"]) == sorted(r["request_identity"] for r in requests)


def test_execute_materializes_all_families_and_threads_stratum(tmp_path):
    """P1-2/P1-3: one case materializes all four P1-A families, stratum threads
    through, and an over-span R-U case lands as R-NULL not a forwarded request."""
    env = {"PYTHONPATH": str(Path(__file__).parents[2] / "src")}
    root = tmp_path / "run"
    wide_units = [{"canonical_unit_id": i, "start_sec": float(i), "end_sec": float(i + 1), "text": f"u{i}"}
                  for i in range(1, 8)]
    cases = [
        {"region_id": "s:w0:unsafe:0", "song_id": "s", "language": "zh", "window_index": 0,
         "seed_kind": "unsafe_region", "target_unit_ids": [2], "detector_state": "UNSAFE",
         "overlap_interval_sec": [1.5, 1.9], "baseline_available": True,
         "left_anchor_candidates": [1], "right_anchor_candidates": [3],
         "stratum": "S1", "stratum_status": "eligible", "origin": "natural",
         "units": _local_units(), "identity_context": _identity_context()},
        {"region_id": "s2:w0:unsafe:1", "song_id": "s2", "language": "zh", "window_index": 0,
         "seed_kind": "unsafe_region", "target_unit_ids": [2, 3, 4, 5], "detector_state": "UNSAFE",
         "overlap_interval_sec": [2.0, 6.0], "baseline_available": True,
         "left_anchor_candidates": [1], "right_anchor_candidates": [6],
         "stratum": "S2", "stratum_status": "eligible", "origin": "natural",
         "units": wide_units, "identity_context": _identity_context()},
    ]
    for sub in ("00_population", "01_requests"):
        (root / sub).mkdir(parents=True)
    (root / "00_population" / "REGION_POOL.jsonl").write_text(
        "".join(json.dumps(c, ensure_ascii=False) + "\n" for c in cases))
    (root / "01_requests" / "P1_SELECTED_REGIONS.jsonl").write_text(
        "".join(json.dumps(c, ensure_ascii=False) + "\n" for c in cases))
    proc = _run_cli(["execute", "--out-root", str(root)], env)
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout)
    assert result["n_requests"] == 8
    requests = _read_jsonl(root / "01_requests" / "REQUESTS.jsonl")
    by_region = {}
    for r in requests:
        by_region.setdefault(r["region_id"], set()).add(r["family"])
    assert by_region["s:w0:unsafe:0"] == {"R-U", "R-A", "R-B", "R-S"}
    assert by_region["s2:w0:unsafe:1"] == {"R-A", "R-B", "R-S", "R-NULL"}
    r_u_wide = [r for r in requests if r["region_id"] == "s2:w0:unsafe:1" and r.get("requested_family") == "R-U"]
    assert r_u_wide and r_u_wide[0]["family"] == "R-NULL"
    assert r_u_wide[0]["requested_family"] == "R-U"
    assert r_u_wide[0]["reason"] == "invalid_unit_target_span"
    assert r_u_wide[0]["stratum"] == "S2"
    status_rows = _read_jsonl(root / "01_requests" / "REQUEST_STATUS.jsonl")
    status_by_key = {(r["region_id"], r["family"]): r["status"] for r in status_rows}
    assert status_by_key[("s2:w0:unsafe:1", "R-NULL")] == "null"
    assert status_by_key[("s:w0:unsafe:0", "R-U")] == "ready"
    assert {r["stratum"] for r in status_rows} == {"S1", "S2"}
    forwards = _read_jsonl(root / "02_forwards" / "FORWARDS.jsonl")
    assert len(forwards) == 7
    assert {f["stratum"] for f in forwards} == {"S1", "S2"}


def test_evaluate_groups_candidates_and_reports_missing_evidence(tmp_path):
    env = {"PYTHONPATH": str(Path(__file__).parents[2] / "src")}
    root = tmp_path / "run"
    requests = [
        {"schema": "unit_realign_request_v2", "request_id": "s1:r1:R-U", "request_identity": "id-a",
         "song_id": "s1", "region_id": "r1", "family": "R-U",
         "active_target_unit_ids": [2], "target_unit_ids": [2], "fixed_context_unit_ids": [1, 3]},
        {"schema": "unit_realign_request_v2", "request_id": "s2:r2:R-S", "request_identity": "id-b",
         "song_id": "s2", "region_id": "r2", "family": "R-S",
         "active_target_unit_ids": [2], "target_unit_ids": [2], "fixed_context_unit_ids": [1, 3]},
        {"schema": "unit_realign_request_v2", "request_id": "s3:r3:R-U", "request_identity": "id-c",
         "song_id": "s3", "region_id": "r3", "family": "R-U",
         "active_target_unit_ids": [2], "target_unit_ids": [2], "fixed_context_unit_ids": [1, 3]},
    ]
    req_path = root / "01_requests" / "REQUESTS.jsonl"
    req_path.parent.mkdir(parents=True)
    req_path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in requests))
    gt_rows = []
    for song in ("s1", "s2"):
        for cid, (start, end) in {1: (1.0, 1.4), 2: (1.5, 1.9), 3: (2.0, 2.4)}.items():
            gt_rows.append({"song_id": song, "canonical_unit_id": cid, "start_sec": start, "end_sec": end})
    gt_path = tmp_path / "baseline_gt.jsonl"
    gt_path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in gt_rows))
    ev = tmp_path / "evidence"
    ev.mkdir()
    for rid in ("s1:r1:R-U", "s2:r2:R-S"):
        (ev / f"{rid}.baseline.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in [
            {"canonical_unit_id": 1, "start_sec": 1.0, "end_sec": 1.4},
            {"canonical_unit_id": 2, "start_sec": 1.8, "end_sec": 2.2},
            {"canonical_unit_id": 3, "start_sec": 2.0, "end_sec": 2.4}]))
        (ev / f"{rid}.candidate.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in [
            {"canonical_unit_id": 1, "start_sec": 1.0, "end_sec": 1.4},
            {"canonical_unit_id": 2, "start_sec": 1.5, "end_sec": 1.9},
            {"canonical_unit_id": 3, "start_sec": 2.0, "end_sec": 2.4}]))
    proc = _run_cli(["evaluate", "--out-root", str(root), "--requests", str(req_path),
                     "--baseline-gt", str(gt_path), "--evidence-dir", str(ev)], env)
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout)
    assert result["n_regions"] == 2
    assert result["n_not_evaluated"] == 1
    candidate_rows = _read_jsonl(root / "03_unit_outcomes" / "CANDIDATE_OUTCOMES.jsonl")
    assert len(candidate_rows) == 2
    assert {row["group_key"] for row in candidate_rows} == {"s1::id-a::R-U::unknown", "s2::id-b::R-S::unknown"}
    assert {row["n_regions"] for row in candidate_rows} == {1}
    for row in candidate_rows:
        assert row["outcome"] == "beneficial"
    not_eval = _read_jsonl(root / "03_unit_outcomes" / "NOT_EVALUATED.jsonl")
    assert len(not_eval) == 1 and not_eval[0]["reason"] == "missing_evidence"
    assert not_eval[0]["request_identity"] == "id-c" and not_eval[0]["family"] == "R-U"
    report = json.loads((root / "05_analysis" / "MISSING_EVIDENCE_REPORT.json").read_text())
    assert report["counts_by_family_stratum"]["R-U"]["unknown"] == 1
    state = json.loads((root / "07_runtime" / "RUN_STATE.json").read_text())
    assert state["completed_identities"] == ["id-a", "id-b"]
    assert state["completed_region_ids"] == ["r1", "r2"]
    resume = json.loads(_run_cli(["execute", "--out-root", str(root), "--resume"], env).stdout)
    assert resume["skipped_resume"] == 2


def test_cli_population_with_real_inventory_source_context(tmp_path):
    """P0-A integration: population --inventory attaches units/audio/identity and
    materializes to ready vs not_constructible with the right reasons."""
    from lyricalign.unit_realign.source_adapter import IDENTITY_KEYS
    env = {"PYTHONPATH": str(Path(__file__).parents[2] / "src")}
    root = tmp_path / "run"
    inv = tmp_path / "inventory"
    audio_dir = tmp_path / "audio"
    inv.mkdir()
    audio_dir.mkdir()
    payload = b"fake-audio-bytes-001"
    (audio_dir / "songA.wav").write_bytes(payload)
    identity = {"model_id": "M", "model_revision": "R", "checkpoint_id": "C",
                "checkpoint_path": "/ckpt", "repo_head": "h" * 40}
    (inv / "DETECTOR_BASELINE_IDENTITY.json").write_text(json.dumps(identity))
    shadow = [{"song_id": "songA", "window_index": 0, "detector_shadow": {"units": {
        str(i): {"start_sec": float(i), "end_sec": float(i + 1), "state": s}
        for i, s in ((0, "ACCEPT"), (1, "REJECT"), (2, "ACCEPT"))}}}]
    (inv / "BASELINE_DETECTOR_SHADOW.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in shadow))
    units = [{"song_id": "songA", "window_index": 0, "canonical_unit_id": i,
              "start_sec": float(i), "end_sec": float(i + 1), "text": f"u{i}"} for i in range(3)]
    (inv / "BASELINE_UNITS.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in units))
    window = {"song_id": "songA", "window_index": 0, "audio_path": "songA.wav"}
    (inv / "BASELINE_WINDOW_INDEX.jsonl").write_text(json.dumps(window) + "\n")

    proc = _run_cli(["population", "--out-root", str(root), "--shadow",
                     str(inv / "BASELINE_DETECTOR_SHADOW.jsonl"), "--inventory", str(inv),
                     "--audio-dir", str(audio_dir), "--target", "10"], env)
    assert proc.returncode == 0, proc.stderr
    pool = _read_jsonl(root / "00_population" / "REGION_POOL.jsonl")
    assert len(pool) > 0
    assert all("units" in row and "identity_context" in row for row in pool)
    assert all(all(row["identity_context"].get(k) for k in IDENTITY_KEYS) for row in pool)
    assert all(row["audio_path"] for row in pool)
    audit = json.loads((root / "00_population" / "SOURCE_ADAPTER_AUDIT.json").read_text())
    assert audit["n_ready"] == len(pool)
    assert audit["audio_audit"]["missing_audio"] == 0

    (root / "01_requests").mkdir(parents=True)
    (root / "01_requests" / "P1_SELECTED_REGIONS.jsonl").write_bytes(
        (root / "00_population" / "SCREEN_SAMPLE.jsonl").read_bytes())
    execute = json.loads(_run_cli(["execute", "--out-root", str(root)], env).stdout)
    assert execute["n_requests"] == 4 * len(pool)
    assert execute["n_failures"] == 2
    assert execute["n_forwards"] == 4 * len(pool) - 2
    requests = _read_jsonl(root / "01_requests" / "REQUESTS.jsonl")
    status_rows = _read_jsonl(root / "01_requests" / "REQUEST_STATUS.jsonl")
    assert len(requests) == 4 * len(pool)
    assert all(row["status"] in {"ready", "not_constructible"} for row in status_rows)
    failures = _read_jsonl(root / "02_forwards" / "FAILURES.jsonl")
    assert {f["reason"] for f in failures} == {"missing_bilateral_anchor"}
    assert all(f["family"] == "R-B" for f in failures)


def test_cli_population_missing_audio_lands_not_constructible(tmp_path):
    env = {"PYTHONPATH": str(Path(__file__).parents[2] / "src")}
    root = tmp_path / "run"
    inv = tmp_path / "inventory"
    inv.mkdir()
    identity = {"model_id": "M", "model_revision": "R", "checkpoint_id": "C",
                "checkpoint_path": "/ckpt", "repo_head": "h" * 40}
    (inv / "DETECTOR_BASELINE_IDENTITY.json").write_text(json.dumps(identity))
    shadow = [{"song_id": "songA", "window_index": 0, "detector_shadow": {"units": {
        "1": {"start_sec": 1.0, "end_sec": 2.0, "state": "REJECT"}}}}]
    (inv / "BASELINE_DETECTOR_SHADOW.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in shadow))
    units = [{"song_id": "songA", "window_index": 0, "canonical_unit_id": 1,
              "start_sec": 1.0, "end_sec": 2.0, "text": "u1"}]
    (inv / "BASELINE_UNITS.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in units))
    (inv / "BASELINE_WINDOW_INDEX.jsonl").write_text(
        json.dumps({"song_id": "songA", "window_index": 0, "audio_path": "missing.wav"}) + "\n")

    proc = _run_cli(["population", "--out-root", str(root), "--shadow",
                     str(inv / "BASELINE_DETECTOR_SHADOW.jsonl"), "--inventory", str(inv),
                     "--audio-dir", str(tmp_path / "audio"), "--target", "10"], env)
    assert proc.returncode == 0, proc.stderr
    audit = json.loads((root / "00_population" / "SOURCE_ADAPTER_AUDIT.json").read_text())
    assert audit["n_ready"] == 0
    assert audit["audio_audit"]["missing_audio"] == 1
    assert audit["audio_audit"]["missing_audio_records"][0]["reason"] == "file_missing"
    (root / "01_requests").mkdir(parents=True)
    (root / "01_requests" / "P1_SELECTED_REGIONS.jsonl").write_bytes(
        (root / "00_population" / "SCREEN_SAMPLE.jsonl").read_bytes())
    execute = json.loads(_run_cli(["execute", "--out-root", str(root)], env).stdout)
    assert execute["n_forwards"] == 0
    assert execute["n_failures"] == 4
    failure_rows = _read_jsonl(root / "02_forwards" / "FAILURES.jsonl")
    assert len(failure_rows) == 4
    assert {r["family"] for r in failure_rows} == {"R-U", "R-A", "R-B", "R-S"}


def _forward_cli(args, env):
    script = Path(__file__).parents[2] / "scripts/unit_realign/run_forward_real.py"
    return subprocess.run([sys.executable, str(script), *args], text=True, capture_output=True, env=env)


def _seed_inventory_and_run(root, tmp_path):
    """Shared fixture: population --inventory -> execute -> return (env, roots)."""
    env = {"PYTHONPATH": str(Path(__file__).parents[2] / "src")}
    inv = tmp_path / "inventory"
    audio_dir = tmp_path / "audio"
    inv.mkdir()
    audio_dir.mkdir()
    (audio_dir / "songA.wav").write_bytes(b"fake-audio-bytes-001")
    identity = {"model_id": "M", "model_revision": "R", "checkpoint_id": "C",
                "checkpoint_path": "/ckpt", "repo_head": "h" * 40}
    (inv / "DETECTOR_BASELINE_IDENTITY.json").write_text(json.dumps(identity))
    shadow = [{"song_id": "songA", "window_index": 0, "detector_shadow": {"units": {
        str(i): {"start_sec": float(i), "end_sec": float(i + 1), "state": s}
        for i, s in ((0, "ACCEPT"), (1, "REJECT"), (2, "ACCEPT"))}}}]
    (inv / "BASELINE_DETECTOR_SHADOW.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in shadow))
    units = [{"song_id": "songA", "window_index": 0, "canonical_unit_id": i,
              "start_sec": float(i), "end_sec": float(i + 1), "text": f"u{i}"} for i in range(3)]
    (inv / "BASELINE_UNITS.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in units))
    (inv / "BASELINE_WINDOW_INDEX.jsonl").write_text(
        json.dumps({"song_id": "songA", "window_index": 0, "audio_path": "songA.wav"}) + "\n")
    proc = _run_cli(["population", "--out-root", str(root), "--shadow",
                     str(inv / "BASELINE_DETECTOR_SHADOW.jsonl"), "--inventory", str(inv),
                     "--audio-dir", str(audio_dir), "--target", "10"], env)
    assert proc.returncode == 0, proc.stderr
    (root / "01_requests").mkdir(parents=True)
    (root / "01_requests" / "P1_SELECTED_REGIONS.jsonl").write_bytes(
        (root / "00_population" / "SCREEN_SAMPLE.jsonl").read_bytes())
    execute = json.loads(_run_cli(["execute", "--out-root", str(root)], env).stdout)
    assert execute["n_forwards"] > 0, execute
    return env, root, inv, execute


def test_forward_smoke_writes_flat_evidence_pairs_and_evaluate_consumes(tmp_path):
    """R4 end-to-end: execute -> run_forward_real --smoke -> evaluate.

    The forward adapter must emit exactly <rid>.baseline.jsonl/.candidate.jsonl
    in 02_forwards/evidence and map decoder rows back to canonical_unit_id, so
    the evaluator (which reads those flat files) yields outcomes instead of
    missing_evidence.  FORWARDS.jsonl now points at the adapter, not the v7
    behavior suite.
    """
    root = tmp_path / "run"
    env, root, inv, execute = _seed_inventory_and_run(root, tmp_path)
    forwards = _read_jsonl(root / "02_forwards" / "FORWARDS.jsonl")
    assert all("run_forward_real.py" in f["forwarding"]["executor"] for f in forwards)
    forward = _forward_cli(["--out-root", str(root), "--smoke"], env)
    assert forward.returncode == 0, forward.stderr
    result = json.loads(forward.stdout)
    assert result["n_failed"] == 0, result["failed"]
    assert result["n_executed"] == execute["n_forwards"]
    evidence = root / "02_forwards" / "evidence"
    baseline_pairs = sorted(evidence.glob("*.baseline.jsonl"))
    candidate_pairs = sorted(evidence.glob("*.candidate.jsonl"))
    assert len(baseline_pairs) == len(candidate_pairs) == execute["n_forwards"]
    for rid, bp in zip(sorted(r["request_id"] for r in _read_jsonl(root / "01_requests" / "REQUESTS.jsonl")
                               if r.get("status") in {"ready", "valid"}), baseline_pairs):
        assert bp.name == f"{rid}.baseline.jsonl"
        rows = _read_jsonl(bp)
        assert rows and all(isinstance(r["canonical_unit_id"], int) for r in rows)

    gt_path = tmp_path / "baseline_gt.jsonl"
    gt_rows = []
    for song in ("songA",):
        for cid in range(3):
            gt_rows.append({"song_id": song, "canonical_unit_id": cid,
                            "start_sec": float(cid), "end_sec": float(cid + 1)})
    gt_path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in gt_rows))
    evaluate = _run_cli(["evaluate", "--out-root", str(root),
                         "--requests", str(root / "01_requests" / "REQUESTS.jsonl"),
                         "--baseline-gt", str(gt_path), "--evidence-dir", str(evidence)], env)
    assert evaluate.returncode == 0, evaluate.stderr
    result_eval = json.loads(evaluate.stdout)
    assert result_eval["n_regions"] == execute["n_forwards"]
    assert result_eval["n_not_evaluated"] == 0
    outcomes = _read_jsonl(root / "03_unit_outcomes" / "UNIT_OUTCOMES.jsonl")
    assert outcomes
    state = json.loads((root / "07_runtime" / "RUN_STATE.json").read_text())
    assert len(state["completed_identities"]) == execute["n_forwards"]


def test_forward_smoke_resume_skips_existing_evidence(tmp_path):
    root = tmp_path / "run"
    env, root, inv, execute = _seed_inventory_and_run(root, tmp_path)
    first = _forward_cli(["--out-root", str(root), "--smoke"], env)
    assert first.returncode == 0, first.stderr
    second = _forward_cli(["--out-root", str(root), "--smoke", "--resume"], env)
    assert second.returncode == 0, second.stderr
    result = json.loads(second.stdout)
    assert result["n_executed"] == 0
    assert result["n_skipped_resume"] == execute["n_forwards"]
