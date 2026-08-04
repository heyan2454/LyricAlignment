# -*- coding: utf-8 -*-
"""阶段 B：behavior manifest 与 run behavior suite 的 smoke 测试（纯 CPU）。"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENV = dict(os.environ, PYTHONPATH=str(ROOT / "src"))


def _labels(tmp_path, n=6):
    songs = ["水星记", "月半小夜曲", "红豆", "东风破", "晴天", "稻香"]
    rows = [
        {"item_id": f"Sky-1#{s}#{i}", "song_id": s, "duration_sec": str(3.0 + i * 0.4),
         "lyrics_normalized": "庭后天台风声借"[: 4 + i]}
        for i, s in enumerate(songs[:n])
    ]
    f = tmp_path / "labels.jsonl"
    f.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows))
    return f, len(rows)


def test_build_behavior_manifest(tmp_path):
    labels, n = _labels(tmp_path, n=4)
    out = tmp_path / "manifest.jsonl"
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts/research_v7/build_behavior_manifest.py"),
         "--labels", str(labels), "--out", str(out), "--limit", "4"],
        capture_output=True, text=True, env=ENV,
    )
    assert r.returncode == 0, r.stderr
    rows = [json.loads(line) for line in out.read_text().splitlines() if line.strip()]
    bytype = Counter(r["mutation_type"] for r in rows)
    assert bytype["baseline"] >= 1
    assert bytype["extra"] >= 1
    assert bytype["missing"] >= 1
    assert bytype["replace"] >= 1
    assert bytype["no_match"] >= 1


def test_run_behavior_suite_smoke(tmp_path):
    labels, _ = _labels(tmp_path, n=2)
    man = tmp_path / "manifest.jsonl"
    subprocess.run([sys.executable, str(ROOT / "scripts/research_v7/build_behavior_manifest.py"),
                    "--labels", str(labels), "--out", str(man), "--limit", "2"],
                   capture_output=True, text=True, env=ENV, check=True)
    outroot = tmp_path / "suite"
    r = subprocess.run([sys.executable, str(ROOT / "scripts/research_v7/run_behavior_suite.py"),
                        "--manifest", str(man), "--out-root", str(outroot), "--smoke"],
                       capture_output=True, text=True, env=ENV)
    assert r.returncode == 0, r.stderr
    evs = list(outroot.glob("evidence/*.json"))
    manifest_rows = [json.loads(line) for line in man.read_text().splitlines() if line.strip()]
    assert len(evs) == len(manifest_rows)  # position variants must never overwrite each other
    ev = json.loads(evs[0].read_text())
    assert ev["attempt"]["status"] == "ok"
    assert ev["attempt"]["request"]["mutation_type"] in {
        "baseline", "extra", "missing", "replace", "no_match",
    }


def test_run_behavior_suite_resume_requires_identical_request(tmp_path):
    # review4-3：resume 按 content identity 命中；同一请求重复→cache hit；请求变化→不同 key 重新执行(不误命中旧缓存)
    manifest = tmp_path / "manifest.jsonl"
    row = {"request_id": "stable", "item_id": "song", "duration_sec": 10,
           "mutation_type": "baseline", "text_units": list("AB")}
    manifest.write_text(json.dumps(row) + "\n")
    outroot = tmp_path / "suite"
    base = [sys.executable, str(ROOT / "scripts/research_v7/run_behavior_suite.py"),
            "--manifest", str(manifest), "--out-root", str(outroot), "--smoke"]
    import json as _j
    r1 = _j.loads(subprocess.run(base, capture_output=True, text=True, env=ENV).stdout)
    assert r1["cache_hit"] == 0 and r1["written"] == 1
    r2 = _j.loads(subprocess.run(base + ["--resume"], capture_output=True, text=True, env=ENV).stdout)
    assert r2["cache_hit"] == 1 and r2["forward"] == 0   # 相同 identity → 命中
    # review6-4：不改 --resume 重跑同 identity → 拒覆盖记 failure，但批次不崩(rc==0)，旧 evidence 未被覆盖
    r_over = subprocess.run(base, capture_output=True, text=True, env=ENV)
    assert r_over.returncode == 0, r_over.stderr
    rm = _j.loads((outroot / "RUN_MANIFEST.json").read_text())
    assert any("refusing to overwrite" in (f.get("error") or "") for f in rm["failures"])
    # 请求变化(text_units) → 不同 content identity → 重新执行(非误命中)，且不拒绝
    row["text_units"] = list("ABC")
    manifest.write_text(json.dumps(row) + "\n")
    r3 = _j.loads(subprocess.run(base + ["--resume"], capture_output=True, text=True, env=ENV).stdout)
    assert r3["cache_hit"] == 0 and r3["forward"] == 1  # 旧缓存未被当命中，重算新 identity


def test_provenance_index_hashes_existing_artifacts_and_keeps_missing_visible(tmp_path):
    root = tmp_path / "real_run"
    root.mkdir()
    (root / "manifest.jsonl").write_text('{"request_id":"a"}\n')
    (root / "collection.json").write_text(json.dumps({"records": [{"request_id": "a"}]}))
    index = tmp_path / "index.json"
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/research_v7/build_research_v7_provenance_index.py"),
         "--run-root", str(root), "--out", str(index)], capture_output=True, text=True, env=ENV,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(index.read_text())
    entry = payload["runs"][0]
    assert entry["artifacts"]["manifest.jsonl"]["sha256"]
    assert entry["manifest_files"]["manifest.jsonl"]["sha256"]
    assert entry["artifacts"]["freeze.json"] is None
    assert entry["collection_summary"]["records"] == 1


def test_source_song_coverage_audit_distinguishes_song_and_segment_completeness(tmp_path):
    population = tmp_path / "population.jsonl"
    population.write_text("\n".join(json.dumps(row) for row in [
        {"item_id": "a1", "source_song_id": "a", "dataset": "m4", "split": "test"},
        {"item_id": "a2", "source_song_id": "a", "dataset": "m4", "split": "test"},
        {"item_id": "b1", "source_song_id": "b", "dataset": "m4", "split": "test"},
    ]) + "\n")
    selected = tmp_path / "selected.jsonl"
    selected.write_text("\n".join(json.dumps(row) for row in [
        {"item_id": "a2", "source_song_id": "a"}, {"item_id": "b1", "source_song_id": "b"},
    ]) + "\n")
    out = tmp_path / "coverage.json"
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/research_v7/audit_source_song_coverage.py"),
         "--population-manifest", str(population), "--selected-manifest", str(selected),
         "--dataset", "m4", "--split", "test", "--out", str(out)],
        capture_output=True, text=True, env=ENV,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text())
    assert payload["source_song_population_complete"] is True
    assert payload["population_item_count"] == 3
    assert payload["selected_item_count"] == 2


def test_c10_multi_answer_evaluator_uses_best_legal_location(tmp_path):
    gt = tmp_path / "gt.jsonl"
    gt.write_text("\n".join(json.dumps({"normalized_character": c, "start_sec": i, "end_sec": i + .5})
                            for i, c in enumerate("ABCDABCD")) + "\n")
    root = tmp_path / "run"; item = root / "items" / "song"; item.mkdir(parents=True)
    request = {"request_id": "c10", "item_id": "song", "text_source": str(gt), "mutation_type": "baseline",
               "mutation_parameters": {"c10_case": "single_ambiguous_repeat", "repeat_gt_starts": [0, 4], "repeat_unit_count": 4}}
    evidence = {"attempt": {"status": "ok", "request": request, "decoder_outputs": {"official": {"rows": [
        {"global_character_index": i, "fixed_global_start_sec": 4 + i, "fixed_global_end_sec": 4.5 + i} for i in range(4)
    ]}}}}
    source = item / "behavior-baseline.json"; source.write_text(json.dumps(evidence))
    collection = tmp_path / "collection.json"
    collection.write_text(json.dumps({"out_root": str(root), "records": [{"source": str(source.relative_to(root))}]}))
    out = tmp_path / "result.json"
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/research_v7/evaluate_c10_multi_answer_gt.py"),
         "--collection", str(collection), "--out", str(out)], capture_output=True, text=True, env=ENV,
    )
    assert result.returncode == 0, result.stderr
    row = json.loads(out.read_text())["results"][0]
    assert row["best_legal_location"] == 1
    assert row["best_legal_mae_sec"] == 0.0


def test_manifest_covers_positions_and_preserves_donor_provenance(tmp_path):
    labels, _ = _labels(tmp_path, n=4)
    out = tmp_path / "manifest.jsonl"
    subprocess.run([sys.executable, str(ROOT / "scripts/research_v7/build_behavior_manifest.py"),
                    "--labels", str(labels), "--out", str(out), "--limit", "4"],
                   capture_output=True, text=True, env=ENV, check=True)
    rows = [json.loads(line) for line in out.read_text().splitlines() if line.strip()]
    assert {r["position"] for r in rows if r["mutation_type"] == "extra"} == {"head", "middle", "tail"}
    assert {r["position"] for r in rows if r["mutation_type"] == "missing"} == {"head", "middle", "tail", "dispersed"}
    assert all("donor_units" in r for r in rows if r["mutation_type"] == "no_match")


def test_collect_analyze_verify_behavior_outputs(tmp_path):
    labels, _ = _labels(tmp_path, n=2)
    manifest = tmp_path / "manifest.jsonl"
    outroot = tmp_path / "run"
    subprocess.run([sys.executable, str(ROOT / "scripts/research_v7/build_behavior_manifest.py"),
                    "--labels", str(labels), "--out", str(manifest), "--limit", "2"],
                   capture_output=True, text=True, env=ENV, check=True)
    subprocess.run([sys.executable, str(ROOT / "scripts/research_v7/run_behavior_suite.py"),
                    "--manifest", str(manifest), "--out-root", str(outroot), "--smoke"],
                   capture_output=True, text=True, env=ENV, check=True)
    collection = tmp_path / "collection.json"
    subprocess.run([sys.executable, str(ROOT / "scripts/research_v7/collect_alignment_behavior.py"),
                    "--out-root", str(outroot), "--out", str(collection)],
                   capture_output=True, text=True, env=ENV, check=True)
    verified = subprocess.run([sys.executable, str(ROOT / "scripts/research_v7/verify_research_v7_outputs.py"),
                               "--collection", str(collection)], capture_output=True, text=True, env=ENV)
    assert verified.returncode == 0, verified.stdout
    analysis = tmp_path / "analysis.json"
    subprocess.run([sys.executable, str(ROOT / "scripts/research_v7/analyze_alignment_behavior.py"),
                    "--collection", str(collection), "--out", str(analysis)],
                   capture_output=True, text=True, env=ENV, check=True)
    output = json.loads(analysis.read_text())
    assert output["total_count"] > 0
    assert output["by_mutation"]["baseline"]["rate"] == 1.0


def test_pilot_freeze_is_idempotent_and_refuses_drift(tmp_path):
    manifest = tmp_path / "manifest.jsonl"
    catalog = tmp_path / "catalog.yaml"
    manifest.write_text('{"request_id":"frozen"}\n')
    catalog.write_text("schema_version: test\n")
    freeze = tmp_path / "pilot_freeze.json"
    cmd = [sys.executable, str(ROOT / "scripts/research_v7/freeze_behavior_pilot.py"),
           "--behavior-manifest", str(manifest), "--mutation-catalog", str(catalog), "--out", str(freeze),
           "--seed", "3407", "--commit-policy", "prefix", "--slot-policy", "sparse"]
    subprocess.run(cmd, capture_output=True, text=True, env=ENV, check=True)
    subprocess.run(cmd, capture_output=True, text=True, env=ENV, check=True)
    manifest.write_text('{"request_id":"changed"}\n')
    changed = subprocess.run(cmd, capture_output=True, text=True, env=ENV)
    assert changed.returncode != 0


def test_workflow_manifest_runs_p1_p2_d_and_sparse_smoke(tmp_path):
    baseline = tmp_path / "baseline.jsonl"
    baseline.write_text(json.dumps({"item_id": "song-1", "song_id": "song", "duration_sec": 30,
                                    "mutation_type": "baseline", "text_units": list("ABCDEFGHI")}) + "\n")
    workflow = tmp_path / "workflow.jsonl"
    subprocess.run([sys.executable, str(ROOT / "scripts/research_v7/build_behavior_workflow_manifest.py"),
                    "--behavior-manifest", str(baseline), "--out", str(workflow), "--chunk-units", "4"],
                   capture_output=True, text=True, env=ENV, check=True)
    rows = [json.loads(line) for line in workflow.read_text().splitlines()]
    assert {row["workflow_mode"] for row in rows} >= {
        "production_full_once", "strict_serial_same_audio", "strict_serial_progressive_crop",
        "independent_short_text_diagnostic", "strict_serial_sparse_slots",
    }
    sparse = next(row for row in rows if row["workflow_mode"] == "strict_serial_sparse_slots" and row["request_id"].endswith("001"))
    assert sparse["timestamp_slot_indices"] == [4, 5, 6, 7]
    outroot = tmp_path / "run"
    subprocess.run([sys.executable, str(ROOT / "scripts/research_v7/run_behavior_suite.py"),
                    "--manifest", str(workflow), "--out-root", str(outroot), "--smoke"],
                   capture_output=True, text=True, env=ENV, check=True)
    evidence = [json.loads(path.read_text()) for path in outroot.glob("evidence/*.json")]
    p2 = next(row for row in evidence if row["attempt"]["request"]["workflow_mode"] == "strict_serial_progressive_crop"
              and row["attempt"]["request"]["parent_request_id"] is not None)
    assert p2["attempt"]["cursor_prev_end"] is not None


def test_malformed_and_blocked_row_still_produce_manifest(tmp_path):
    # review7-1：整行隔离——malformed row 与 serial-parent 失败后批次继续并产 RUN_MANIFEST
    import json as _j
    manifest = tmp_path / "badman.jsonl"
    # row0 正常；row1 malformed(缺 text_units 且 text 越界)；row2 依赖 role1(parent 未完成)
    rows = [
        {"request_id": "ok", "item_id": "s", "text_units": ["a", "b"], "duration_sec": 10, "mutation_type": "baseline"},
        {"request_id": "bad", "item_id": "s2", "text_units": [], "text_start_index": 0, "text_end_index": 5,
         "duration_sec": 10, "mutation_type": "baseline"},
        {"request_id": "blk", "item_id": "s3", "parent_request_id": "ghost", "text_units": ["x"],
         "workflow_mode": "strict_serial_progressive_crop", "duration_sec": 10, "mutation_type": "baseline"},
    ]
    manifest.write_text("\n".join(_j.dumps(r) for r in rows))
    outroot = tmp_path / "run"
    r = subprocess.run([sys.executable, str(ROOT / "scripts/research_v7/run_behavior_suite.py"),
                        "--manifest", str(manifest), "--out-root", str(outroot), "--smoke"],
                       capture_output=True, text=True, env=ENV)
    assert r.returncode == 0, r.stderr  # malformed/blocked 不中止批次
    rm = _j.loads((outroot / "RUN_MANIFEST.json").read_text())
    kinds = {f.get("kind") for f in rm["failures"]}
    assert "malformed_row" in kinds    # bad row 记为 malformed
    assert "blocked_by_parent" in kinds  # blk row 记为 blocked_by_parent
    # 正常 row0 仍被执行
    assert any(i["request_id"] == "ok" and i["status"] == "ok" for i in rm["requests_identity"])
    # FAILURES.jsonl 存在
    assert (outroot / "FAILURES.jsonl").exists()


def test_array_row_and_type_error_row_do_not_abort_batch(tmp_path):
    # review8-6：数组行(非 object)、字符串时间算术 TypeError 都在循环开头 try 内记 malformed，
    # 独立正常行继续执行并产最终 RUN_MANIFEST（不再中止全批）。
    import json as _j
    manifest = tmp_path / "badrows.jsonl"
    manifest.write_text(
        "\n".join([
            _j.dumps({"request_id": "ok", "item_id": "s1", "text_units": ["a"],
                      "text_start_index": 0, "text_end_index": 1,
                      "audio_path": "/tmp/nonexistent.wav", "mutation_type": "baseline"}),
            _j.dumps(["not", "an", "object"]),                      # 数组行
            _j.dumps({"request_id": "bad2", "item_id": "s2", "files": ["/tmp/x.wav"],
                      "duration_sec": "1.5", "audio_end_sec": 3,    # 字符串时间 → 减法 TypeError
                      "text_units": [], "mutation_type": "baseline"}),
        ]) + "\n")
    outroot = tmp_path / "run"
    r = subprocess.run([sys.executable, str(ROOT / "scripts/research_v7/run_behavior_suite.py"),
                        "--manifest", str(manifest), "--out-root", str(outroot), "--smoke"],
                       capture_output=True, text=True, env=ENV)
    assert r.returncode == 0, r.stderr  # 批次不被前置错误中止
    rm = _j.loads((outroot / "RUN_MANIFEST.json").read_text())
    kinds = {f.get("kind") for f in rm["failures"]}
    assert "malformed_row" in kinds
    # 数组行被记为 malformed（id=None），字符串时间同样 malformed；正常行 ok 且列身份中可见
    assert any(i["request_id"] == "ok" and i["status"] == "ok" for i in rm["requests_identity"])
    assert len([f for f in rm["failures"] if f["kind"] == "malformed_row"]) >= 2


def test_train_filter_gate_lists_rejected_not_trainable(tmp_path):
    # review8-7：入口把 probe demo 明确拒绝并列出 rejected 身份，lyrics_aligned 才进 trainable。
    import json as _j
    manifest = tmp_path / "mf.jsonl"
    manifest.write_text("\n".join([
        _j.dumps({"request_id": "ok", "item_id": "song1", "text_units": ["a"], "text_start_index": 0,
                  "text_end_index": 1, "audio_path": "/tmp/nonexistent.wav", "mutation_type": "baseline",
                  "evaluation_role": "lyrics_aligned", "text_window_aligned": True}),
        _j.dumps({"request_id": "pr", "item_id": "probe1", "text_units": ["p"], "text_start_index": 0,
                  "text_end_index": 1, "audio_path": "/tmp/nonexistent.wav", "mutation_type": "baseline",
                  "evaluation_role": "acoustic_probe", "text_window_aligned": False}),
    ]) + "\n")
    outroot = tmp_path / "run"
    r = subprocess.run([sys.executable, str(ROOT / "scripts/research_v7/run_behavior_suite.py"),
                        "--manifest", str(manifest), "--out-root", str(outroot), "--smoke"],
                       capture_output=True, text=True, env=ENV)
    assert r.returncode == 0, r.stderr
    rm = _j.loads((outroot / "RUN_MANIFEST.json").read_text())
    tf = rm["train_filter"]
    assert tf["trainable_identity_count"] == 1
    assert [t["item_id"] for t in tf["trainable"]] == ["song1"]        # 只放行 lyrics_aligned
    assert tf["rejected_count"] == 1
    assert [t["item_id"] for t in tf["rejected"]] == ["probe1"]        # probe 被拒且列出
    assert tf["rejected"][0]["reason"] == "role_not_lyrics_aligned"
    assert tf["denominator"]["all_success_or_cache"] == 2              # 全部成功/命中身份
    assert tf["denominator"]["trainable"] == 1 and tf["denominator"]["rejected"] == 1


def test_failure_rows_carry_role_and_source_audit(tmp_path):
    # review8-8：malformed/blocked 行 failure 均带 role/alignment/parent/source_row_sha256；
    # row_audit 对每 manifest 行给出 status 分类，包含成功与失败/阻塞行。
    import json as _j
    manifest = tmp_path / "aud.jsonl"
    manifest.write_text("\n".join([
        _j.dumps({"request_id": "ok", "item_id": "s", "text_units": ["a"], "text_start_index": 0,
                  "text_end_index": 1, "audio_path": "/tmp/nonexistent.wav", "mutation_type": "baseline",
                  "evaluation_role": "lyrics_aligned", "text_window_aligned": True}),
        _j.dumps({"request_id": "bad", "item_id": "s2", "text_units": [],
                  "text_start_index": 0, "text_end_index": 5, "audio_path": "/tmp/nonexistent.wav",
                  "mutation_type": "baseline", "evaluation_role": "lyrics_aligned"}),
        _j.dumps({"request_id": "blk", "item_id": "s3", "parent_request_id": "ghost",
                  "text_units": ["x"], "workflow_mode": "strict_serial_progressive_crop",
                  "audio_path": "/tmp/nonexistent.wav", "mutation_type": "baseline",
                  "evaluation_role": "lyrics_aligned", "text_window_aligned": True}),
    ]) + "\n")
    outroot = tmp_path / "run"
    r = subprocess.run([sys.executable, str(ROOT / "scripts/research_v7/run_behavior_suite.py"),
                        "--manifest", str(manifest), "--out-root", str(outroot), "--smoke"],
                       capture_output=True, text=True, env=ENV)
    assert r.returncode == 0, r.stderr
    rm = _j.loads((outroot / "RUN_MANIFEST.json").read_text())
    # 失败/阻塞行 failure 带 role + source digest（review8-8）
    for f in rm["failures"]:
        assert "source_row_sha256" in f
        if f["kind"] == "blocked_by_parent":
            assert f["parent_request_id"] == "ghost"
        if f["kind"] in ("malformed_row",):
            assert f["evaluation_role"] in ("lyrics_aligned",)
    # row_audit 每行有 status 分类，覆盖成功/阻塞/失败
    auds = {a["row_index"]: a["status"] for a in rm["row_audit"]}
    assert auds[0] == "ok"
    assert auds[1] == "malformed_row"
    assert auds[2] == "blocked_by_parent"
    # 分母交集：成功身份 + 失败/阻塞 都在行审计中体现
    assert all(a["source_row_sha256"] for a in rm["row_audit"])
