# -*- coding: utf-8 -*-
"""Detector V2 run labeling CLI tests (Dev-G)：字符对齐 / gt_unavailable / 双目标独立 /
family×split 分层分母 / 防泄漏（只写 LABELS.jsonl，不写 evidence_v2）。"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "research_v7" / "label_detector_v2_run.py"
spec = importlib.util.spec_from_file_location("label_detector_v2_run", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def _gt_row(item_id, lyrics, ids, status="accepted_rule_based_pinyin_validated"):
    return {"item_id": item_id, "song_id": "songA", "lyrics_normalized": lyrics,
            "timestamp_class_ids": ids, "timestamp_segment_sec": 0.08,
            "mapping_status": status}


def _evidence(request_id, gci_rows):
    return {"content_identity": request_id, "attempt": {
        "ok": True, "request": {"request_id": request_id},
        "decoder_outputs": {"official": {"rows": [
            {"global_character_index": gci, **keys} for gci, keys in gci_rows
        ]}}}}  # raw block/_posterior/_repair_trace 缺省，converter 容忍


def _request_row(rid, family, split, n_canonical, item="songA", gt_ambiguity=False):
    return {"request_id": rid, "item_id": f"{item}:0:{family}:full", "view_id": "full",
            "family": family, "split": split, "gt_ambiguity": gt_ambiguity,
            "canonical_ids": list(range(n_canonical)),
            "canonical_to_local": {str(i): i for i in range(n_canonical)},
            "audio_path": f"/x/audio/{item}.wav"}


def test_align_units_to_gt_exact_and_unavailable():
    binds = mod.align_units_to_gt(["a", "b", "c", "d", "x"], ["a", "b", "c", "d"])
    assert binds == [0, 1, 2, 3, None]
    assert mod.align_units_to_gt([], []) == []


def test_align_units_to_gt_skips_gt_extra():
    binds = mod.align_units_to_gt(["a", "b", "c", "d"], ["a", "x", "b", "c", "d"])
    assert binds == [0, 2, 3, 4]


def test_build_song_gt_times_and_exclusions():
    rows = [
        _gt_row("s#0", "ab", [5, 10, 10, 15]),
        _gt_row("s#1", "cd", [15, 20, 20, 25]),
        _gt_row("s#2", "xy", [0, 0, 0, 0], status="rejected"),     # 状态过滤
        _gt_row("s#3", "zz", [1, 2, 3], status="accepted_rule_based_pinyin_validated"),  # 长度不符
        _gt_row("s#4", "yy", [5, 2, 10, 15]),                      # end<=start 无效
    ]
    gt = mod.build_song_gt(rows)
    assert gt["chars"] == ["a", "b", "c", "d"]
    assert gt["starts"] == [0.40, 0.80, 1.20, 1.60]
    assert gt["ends"] == [0.80, 1.20, 1.60, 2.00]
    assert len(gt["excluded"]) == 3


def test_gt_map_for_request_binds_real_times():
    timeline = {"song_id": "songA", "canonical_units": [
        {"canonical_unit_id": i, "text": ch} for i, ch in enumerate("abcdx")]}
    gt = mod.build_song_gt([_gt_row("s#0", "abcd", [5, 10, 10, 15, 15, 20, 20, 25])])
    canon_gt, unavailable = mod.gt_map_for_request(timeline, gt, [0, 1, 2, 3])
    assert canon_gt == {0: (0.40, 0.80), 1: (0.80, 1.20), 2: (1.20, 1.60), 3: (1.60, 2.00)}
    assert unavailable == set()
    canon_gt2, unavailable2 = mod.gt_map_for_request(timeline, gt, [0, 1, 2, 3, 4])
    assert unavailable2 == {4} and 4 not in canon_gt2


def test_dual_target_independent_no_cross_fallback():
    req = _request_row("songA:0:baseline_legal:legal:full", "baseline_legal", "train", 4)
    gci_rows = [
        (0, {"raw_global_start_sec": 0.42, "raw_global_end_sec": 0.78,
             "official_fixed_global_start_sec": 0.44, "official_fixed_global_end_sec": 0.82}),
        (1, {"raw_global_start_sec": 0.93, "raw_global_end_sec": 1.28,
             "official_fixed_global_start_sec": 0.95, "official_fixed_global_end_sec": 1.30}),
        (2, {"raw_global_start_sec": 1.70, "raw_global_end_sec": 2.00,
             "official_fixed_global_start_sec": 1.70, "official_fixed_global_end_sec": 2.00}),
        (3, {"raw_global_start_sec": 1.65, "raw_global_end_sec": 2.05}),  # official 单边 → 不跨 target 回退
    ]
    timeline = {"song_id": "songA", "canonical_units": [
        {"canonical_unit_id": i, "text": ch} for i, ch in enumerate("abcd")]}
    gt = mod.build_song_gt([_gt_row("s#0", "abcd", [5, 10, 10, 15, 15, 20, 20, 25])])
    out, labeled, n_gu = mod.label_one_request(req, _evidence(req["request_id"], gci_rows),
                                               timeline, gt, [], split_override=None)
    assert n_gu == 0 and len(labeled) == 8
    by = {(r["canonical_unit_id"], r["target"]): r["label"] for r in out}
    assert by[(0, "raw")] == "safe" and by[(0, "official")] == "safe"
    assert by[(1, "raw")] == "grey" and by[(1, "official")] == "grey"
    assert by[(2, "raw")] == "unsafe" and by[(2, "official")] == "unsafe"
    assert by[(3, "raw")] == "safe"          # raw 有同源几何
    assert by[(3, "official")] == "unsafe"   # official 单边 → missing，绝不消费 raw 键


def test_ambiguous_whole_request_independent():
    req = _request_row("songA:0:end_late:legal:full", "end_late", "test", 3, gt_ambiguity=True)
    gci_rows = [(i, {"raw_global_start_sec": 0.42 + i, "raw_global_end_sec": 0.80 + i,
                     "official_fixed_global_start_sec": 0.42 + i,
                     "official_fixed_global_end_sec": 0.80 + i}) for i in range(3)]
    timeline = {"song_id": "songA", "canonical_units": [
        {"canonical_unit_id": i, "text": ch} for i, ch in enumerate("abcd")]}
    gt = mod.build_song_gt([_gt_row("s#0", "abcd", [5, 10, 10, 15, 15, 20, 20, 25])])
    out, _, _ = mod.label_one_request(req, _evidence(req["request_id"], gci_rows),
                                      timeline, gt, [], split_override="test")
    assert all(r["label"] == "ambiguous" for r in out)
    assert all(r["audit"]["reason"] == "occurrence_ambiguous" for r in out)


def test_gt_unavailable_rows_both_targets_and_song_missing():
    req = _request_row("songA:0:baseline_legal:legal:full", "baseline_legal", "train", 3)
    gci_rows = [(i, {"raw_global_start_sec": 0.4 + i, "raw_global_end_sec": 0.8 + i,
                     "official_fixed_global_start_sec": 0.4 + i,
                     "official_fixed_global_end_sec": 0.8 + i}) for i in range(3)]
    timeline = {"song_id": "songA", "canonical_units": [
        {"canonical_unit_id": 0, "text": "a"}, {"canonical_unit_id": 1, "text": "b"},
        {"canonical_unit_id": 2, "text": "z"}]}   # z 无 GT
    gt = mod.build_song_gt([_gt_row("s#0", "ab", [5, 10, 10, 15])])
    out, labeled, n_gu = mod.label_one_request(req, _evidence(req["request_id"], gci_rows),
                                               timeline, gt, [], split_override=None)
    assert n_gu == 2
    gu = [r for r in out if r["label"] == "gt_unavailable"]
    assert {r["target"] for r in gu} == {"raw", "official"}
    assert all(r["gt_unavailable"] is True and r["canonical_unit_id"] == 2 for r in gu)
    assert len(labeled) == 4
    # 整歌无 GT → 全部 gt_unavailable（不进 label 训练）
    out2, labeled2, _ = mod.label_one_request(req, _evidence(req["request_id"], gci_rows),
                                              None, None, [], split_override=None)
    assert len(out2) == 6 and not labeled2
    assert all(r["audit"]["reason"] == "song_gt_unavailable" for r in out2)


def _write_fixture_run(tmp_path):
    run = tmp_path / "run"
    ev = run / "evidence"
    ev.mkdir(parents=True)
    (run / "manifests").mkdir(parents=True)

    timeline = {"song_id": "songA", "concat_audio_path": "/x/audio/songA.wav", "canonical_units": [
        {"canonical_unit_id": i, "text": ch} for i, ch in enumerate("abcdx")]}
    (tmp_path / "LONG_TIMELINE_MANIFEST.jsonl").write_text(
        json.dumps(timeline, ensure_ascii=False) + "\n")
    gt = [_gt_row("s#0", "abcd", [5, 10, 10, 15, 15, 20, 20, 25])]
    (tmp_path / "m4singer_qwen_fa_labels.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in gt))

    reqs = [
        _request_row("songA:0:baseline_legal:legal:full", "baseline_legal", "train", 5),
        _request_row("songA:0:end_late:legal:full", "end_late", "test", 4, gt_ambiguity=True),
        _request_row("songA:0:crop_early:legal:full", "crop_early", "validation", 4),
    ]
    (run / "manifests" / "ANOMALY_MANIFEST.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in reqs))

    baseline_rows = [
        (0, {"raw_global_start_sec": 0.42, "raw_global_end_sec": 0.78,
             "official_fixed_global_start_sec": 0.44, "official_fixed_global_end_sec": 0.82}),
        (1, {"raw_global_start_sec": 0.93, "raw_global_end_sec": 1.28,
             "official_fixed_global_start_sec": 0.95, "official_fixed_global_end_sec": 1.30}),
        (2, {"raw_global_start_sec": 1.70, "raw_global_end_sec": 2.00,
             "official_fixed_global_start_sec": 1.70, "official_fixed_global_end_sec": 2.00}),
        (3, {"raw_global_start_sec": 1.65, "raw_global_end_sec": 2.05}),
        (4, {"raw_global_start_sec": 2.2, "raw_global_end_sec": 2.6,
             "official_fixed_global_start_sec": 2.2, "official_fixed_global_end_sec": 2.6}),
    ]
    (ev / "sha256:base.json").write_text(
        json.dumps(_evidence("songA:0:baseline_legal:legal:full", baseline_rows)))
    end_late_rows = [(i, {"raw_global_start_sec": 0.42 + i, "raw_global_end_sec": 0.80 + i,
                          "official_fixed_global_start_sec": 0.42 + i,
                          "official_fixed_global_end_sec": 0.80 + i}) for i in range(4)]
    (ev / "sha256:end.json").write_text(
        json.dumps(_evidence("songA:0:end_late:legal:full", end_late_rows)))
    crop_rows = [(i, {"raw_global_start_sec": 0.42 + i, "raw_global_end_sec": 0.78 + i,
                      "official_fixed_global_start_sec": 0.42 + i,
                      "official_fixed_global_end_sec": 0.78 + i}) for i in range(2)]
    (ev / "sha256:crop.json").write_text(
        json.dumps(_evidence("songA:0:crop_early:legal:full", crop_rows)))
    (ev / "sha256:fail.json").write_text(json.dumps({
        "attempt": {"ok": False, "request": {"request_id": "songA:0:nope:full"}}}))
    (ev / "sha256:unmatched.json").write_text(json.dumps(
        {"attempt": {"ok": True, "request": {"request_id": "songA:0:ghost:full"},
                     "decoder_outputs": {"official": {"rows": []}}}}))
    return run


def test_label_run_strata_denominators_and_no_evidence_write(tmp_path):
    run = _write_fixture_run(tmp_path)
    out = tmp_path / "out"
    summary = mod.label_run(run, tmp_path / "LONG_TIMELINE_MANIFEST.jsonl",
                            tmp_path / "m4singer_qwen_fa_labels.jsonl", out)
    assert sorted(p.name for p in out.iterdir()) == ["LABELS.jsonl", "LABEL_SUMMARY.json"]
    assert not (run / "evidence_v2").exists()

    assert summary["n_requests_labeled"] == 3
    assert summary["skipped"]["evidence_not_ok"] == 1
    assert summary["skipped"]["evidence_unmatched_request"] == 1
    assert summary["pooled"]["n_units"] == 8 + 8 + 8
    assert summary["pooled"]["n_gt_unavailable"] == 2

    st = summary["by_family_split_target"]
    assert st["baseline_legal|train|raw"]["n_units"] == 5
    assert st["baseline_legal|train|raw"]["safe"] == 2
    assert st["baseline_legal|train|raw"]["grey"] == 1
    assert st["baseline_legal|train|raw"]["unsafe"] == 1
    assert st["baseline_legal|train|raw"]["gt_unavailable"] == 1
    assert st["baseline_legal|train|official"]["n_units"] == 5
    assert st["baseline_legal|train|official"]["safe"] == 1   # gci3 单边 → unsafe，无跨 target 回退
    assert st["baseline_legal|train|official"]["unsafe"] == 2
    assert st["baseline_legal|train|official"]["gt_unavailable"] == 1

    assert st["end_late|test|raw"]["n_units"] == 4
    assert st["end_late|test|raw"]["ambiguous"] == 4
    assert st["crop_early|validation|raw"]["n_units"] == 4
    assert st["crop_early|validation|raw"]["safe"] == 1
    assert st["crop_early|validation|raw"]["unsafe"] == 3    # gci1 偏移 + 缺输出行

    bf = summary["by_family"]
    assert bf["baseline_legal"]["n_units"] == 10
    assert bf["baseline_legal"]["unsafe"] == 3
    assert bf["crop_early"]["n_units"] == 8

    rows = [json.loads(l) for l in (out / "LABELS.jsonl").read_text().splitlines()]
    assert len(rows) == 10 + 8 + 8
    gu = [r for r in rows if r["label"] == "gt_unavailable"]
    assert all(r["gt_unavailable"] is True for r in gu)
    assert {(r["family"], r["split"]) for r in rows} == {
        ("baseline_legal", "train"), ("end_late", "test"), ("crop_early", "validation")}


def test_split_override_from_source_song_split(tmp_path):
    run = _write_fixture_run(tmp_path)
    preflight = run / "preflight"
    preflight.mkdir()
    (preflight / "SOURCE_SONG_SPLIT.json").write_text(json.dumps(
        {"songs": {"songA": "validation"}}))
    out = tmp_path / "out2"
    summary = mod.label_run(run, tmp_path / "LONG_TIMELINE_MANIFEST.jsonl",
                            tmp_path / "m4singer_qwen_fa_labels.jsonl", out)
    assert summary["source_song_split_used"] is True
    rows = [json.loads(l) for l in (out / "LABELS.jsonl").read_text().splitlines()]
    assert all(r["split"] == "validation" for r in rows)
    assert "baseline_legal|validation|raw" in summary["by_family_split_target"]
