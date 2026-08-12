"""Tests for realign_gate.test_demo (04_test_demo no-GT stress helpers)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from lyricalign.realign_gate import test_demo as td

CN_TEXT = "明月几时有把酒问青天不知天上宫阙今夕是何年\n"
EN_TEXT = "hello world this is a song about the morning sky today\n"


def _make_demo_root(tmp_path):
    root = tmp_path / "demo"
    cn = root / "Chinese"
    en = root / "English"
    cn.mkdir(parents=True)
    en.mkdir(parents=True)
    (cn / "song.wav").write_bytes(b"RIFF" + b"\x00" * 64)
    (cn / "song.txt").write_text(CN_TEXT, encoding="utf-8")
    (en / "track.mp3").write_bytes(b"ID3")
    (en / "track.txt").write_text(EN_TEXT, encoding="utf-8")
    (root / "orphan.mp4").write_bytes(b"\x00" * 16)
    (root / "meta.txt").write_text("no audio pair", encoding="utf-8")
    (root / "lonely.wav").write_bytes(b"RIFF" + b"\x00" * 16)
    return root


def test_discover_items_exts_same_name_txt_and_lang(tmp_path):
    root = _make_demo_root(tmp_path)
    items = td.discover_items([root])
    by_name = {str(i["audio"].name): i for i in items}
    assert set(by_name) == {"song.wav", "track.mp3"}
    assert by_name["song.wav"]["lang"] == "chinese"
    assert by_name["track.mp3"]["lang"] == "english"
    assert by_name["song.wav"]["txt"] == root / "Chinese" / "song.txt"
    assert by_name["song.wav"]["root"] == root
    for item in items:
        assert item["txt"].is_file()
        assert item["audio"].is_file()


def test_detector_summary_structure(tmp_path):
    root = _make_demo_root(tmp_path)
    items = td.discover_items([root])
    summary = td.detector_summary(items, td._mock_detector_adapter({}))
    assert summary["schema"] == "TEST_DEMO_DETECTOR_SUMMARY_v1"
    assert summary["no_gt"] is True
    assert summary["n_items"] == 2
    assert summary["n_failed"] == 0
    assert summary["detector"]["T_accept"] == pytest.approx(0.16546343952822562)
    assert summary["detector"]["merge"] == "light_merge"
    songs = {r["item"]: r for r in summary["per_song"]}
    assert len(songs) == 2
    rec = songs["Chinese/song.wav"]
    for key in ("text", "raw_rows", "unit_states", "anomalies", "detector_segments",
                "suspicious_score", "tristate"):
        assert key in rec
    kinds = {a["kind"] for a in rec["anomalies"]}
    assert "zero_duration" in kinds
    assert "posterior_multimodal" in kinds
    assert "raw_official_divergence" in kinds
    assert len(rec["unit_states"]) == rec["n_units"]
    assert rec["tristate"]["reject"] >= 1
    assert rec["raw_official_mean_diff_sec"] > 0.0


def test_select_suspicious_cross_lang_quota_and_topk(tmp_path):
    root = _make_demo_root(tmp_path)
    items = td.discover_items([root])
    summary = td.detector_summary(items, td._mock_detector_adapter({}))
    sel = td.select_suspicious(summary, top_k=6, min_per_lang=2)
    assert 0 < len(sel) <= 6
    per_lang: dict[str, int] = {}
    for w in sel:
        per_lang[w["lang"]] = per_lang.get(w["lang"], 0) + 1
    assert per_lang.get("chinese", 0) >= 2
    assert per_lang.get("english", 0) >= 2
    scores = [w["score"] for w in sel]
    assert scores == sorted(scores, reverse=True)
    keys = [(w["item"], w["unit_start"], w["unit_end"], w["anomaly_kind"]) for w in sel]
    assert len(set(keys)) == len(keys)


def test_build_demo_requests_narrow_and_context_no_gt(tmp_path):
    root = _make_demo_root(tmp_path)
    items = td.discover_items([root])
    summary = td.detector_summary(items, td._mock_detector_adapter({}))
    sel = td.select_suspicious(summary, top_k=4, min_per_lang=2)
    requests = td.build_demo_requests(
        sel, items, detector_state={"kind": "standardized_logistic", "merge": "light_merge"})
    assert len(requests) == len(sel) * 2
    assert {r["kind"] for r in requests} == {"narrow", "context"}
    forbidden_exact = {"accuracy", "harm", "gt_pair", "label", "old_start_error_ms",
                       "new_start_error_ms", "delta_error_ms"}

    def walk(obj, path="root"):
        if isinstance(obj, dict):
            for k, v in obj.items():
                kl = k.lower()
                assert kl not in forbidden_exact, f"forbidden key {path}/{k}"
                assert not kl.endswith(("_label", "_accuracy", "_harm")), f"forbidden key {path}/{k}"
                walk(v, f"{path}/{k}")
        elif isinstance(obj, list):
            for x in obj:
                walk(x, path)

    walk(requests)
    for r in requests:
        assert r["schema"] == "realign_gate_test_demo_request_v1"
        assert r["no_gt"] is True
        for key in ("character_index", "audio_path", "text", "raw_rows",
                    "detector_state", "signals", "span"):
            assert key in r
        assert r["signals"]["displacement"] is not None
        assert "structure_anomaly" in r["signals"]
    ctx = [r for r in requests if r["kind"] == "context"]
    assert any(r.get("anchor") for r in ctx)
    narrow = requests[::2]
    assert all(r["kind"] == "narrow" and r["anchor"] == [] for r in narrow)


def test_module_does_not_import_e5_proposals():
    source = Path(td.__file__).read_text(encoding="utf-8")
    assert "e5_proposals" not in source
    assert "build_proposals" not in source


def test_run_stage_outputs_schema(tmp_path):
    root = _make_demo_root(tmp_path)
    run_root = tmp_path / "run"
    cfg_path = tmp_path / "cfg.json"
    cfg_path.write_text(json.dumps(
        {"adapter": "mock", "demo_roots": [str(root)], "command": "pytest"},
        ensure_ascii=False))
    summary = td.run_stage(run_root, cfg_path, top_k=6)
    out = run_root / "04_test_demo"
    for name in ("TEST_DEMO_DETECTOR_SUMMARY.json",
                 "TEST_DEMO_SUSPICIOUS_WINDOWS.jsonl",
                 "TEST_DEMO_REALIGN_BEHAVIOR.jsonl"):
        assert (out / name).is_file()
    s = json.loads((out / "TEST_DEMO_DETECTOR_SUMMARY.json").read_text(encoding="utf-8"))
    assert s["schema"] == "TEST_DEMO_DETECTOR_SUMMARY_v1"
    assert s["no_gt"] is True
    assert s["n_requests"] == s["n_windows"] * 2
    suspicious = [json.loads(line) for line in
                  (out / "TEST_DEMO_SUSPICIOUS_WINDOWS.jsonl").read_text(encoding="utf-8").splitlines()
                  if line.strip()]
    assert 0 < len(suspicious) <= 6
    assert all("song_record" not in w for w in suspicious)
    behavior = [json.loads(line) for line in
                (out / "TEST_DEMO_REALIGN_BEHAVIOR.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()]
    assert len(behavior) == len(suspicious) * 2
    assert {r["kind"] for r in behavior} == {"narrow", "context"}
    assert all(r["no_gt"] is True for r in behavior)
    assert summary["n_items"] == 2
