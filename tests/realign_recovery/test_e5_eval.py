"""Synthetic offline-GT evaluation tests for E5 proposals (realign_recovery)."""
from __future__ import annotations

import json

import pytest

from lyricalign.realign_recovery.e5_eval import evaluate_e5_episodes

TEXTS = ["甲", "乙", "丙", "丁", "戊", "己", "庚", "辛", "壬"]
GT_SEC = {i: (float(i), float(i) + 1.0) for i in range(9)}
GT_STATUS = "accepted_rule_based_pinyin_validated"


def _write_manifest(path, song: str, unit_count: int) -> None:
    units = [
        {
            "canonical_unit_id": i,
            "source_segment_id": "seg0",
            "source_unit_index": i,
            "start_sec": GT_SEC[i][0],
            "end_sec": GT_SEC[i][1],
            "text": TEXTS[i],
        }
        for i in range(unit_count)
    ]
    row = {
        "song_id": song,
        "duration_sec": float(unit_count),
        "concat_audio_path": f"audio/{song}.wav",
        "segment_offsets": [{"source_segment_id": "seg0", "global_start_sec": 0.0}],
        "canonical_units": units,
    }
    path.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_annotations(path, songs: list[str]) -> None:
    lines = []
    for song in songs:
        for i in range(6):
            s, e = GT_SEC[i]
            lines.append(json.dumps({
                "song_id": song,
                "item_id": "seg0",
                "character_index": i,
                "start_sec": s,
                "end_sec": e,
                "mapping_status": GT_STATUS,
                "normalized_character": TEXTS[i],
                "raw_character": TEXTS[i],
            }, ensure_ascii=False))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _row(gci: int, text_units: list[str], start: float, end: float) -> dict:
    return {
        "global_character_index": gci,
        "character": text_units[gci],
        "raw_global_start_sec": start,
        "raw_global_end_sec": end,
    }


def _rows(gci_list, text_units, start, end):
    return [_row(i, text_units, start, end) for i in gci_list]


def _req(rid: str, song: str, variant: str, method: str, episode_id: str,
         target_ids: list[int], text_unit_start: int, text_unit_end: int,
         family: str = "natural") -> dict:
    text_units = [TEXTS[i] for i in range(text_unit_start, text_unit_end + 1)]
    return {
        "request_id": rid,
        "item_id": song,
        "source_song_id": song,
        "input_variant": variant,
        "text_units": text_units,
        "provenance": {
            "episode_id": episode_id,
            "episode_family": family,
            "episode_kind": "natural",
            "source_window_id": f"{song}:w0:full",
            "target_unit_start": target_ids[0],
            "target_unit_end": target_ids[-1],
            "target_unit_ids": target_ids,
            "text_unit_start": text_unit_start,
            "text_unit_end": text_unit_end,
            "proposal_method": method,
        },
    }


def _evidence(rid: str, rows: list[dict]) -> dict:
    return {
        "attempt": {
            "request": {"request_id": rid},
            "decoder_outputs": {"raw": {"rows": rows}},
        },
        "metadata": {"source": "test"},
    }


def _write_evidence_dir(evidence_dir, evidence_by_rid: dict[str, dict]) -> None:
    for i, (rid, payload) in enumerate(sorted(evidence_by_rid.items())):
        (evidence_dir / f"sha256:{i:04d}.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _run(tmp_path, requests: list[dict], evidence: dict[str, dict],
         annotations_songs: list[str]) -> dict:
    req_path = tmp_path / "REQUESTS.jsonl"
    req_path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in requests) + "\n",
        encoding="utf-8")
    manifest_a = tmp_path / "manifest_cohort_a.jsonl"
    manifest_b = tmp_path / "manifest_cohort_b.jsonl"
    _write_manifest(manifest_a, "songA", 6)
    _write_manifest(manifest_b, "songB", 6)
    ann = tmp_path / "annotations.jsonl"
    _write_annotations(ann, annotations_songs)
    ev_dir = tmp_path / "evidence"
    ev_dir.mkdir(parents=True, exist_ok=True)
    _write_evidence_dir(ev_dir, evidence)
    out = tmp_path / "summary.json"
    return evaluate_e5_episodes(
        req_path, ev_dir, ann, [manifest_a, manifest_b], out,
        catastrophic_sec=(1, 2, 5, 10))


def test_per_episode_grouping_and_repair_thresholds(tmp_path):
    requests = [
        _req("r-orig", "songA", "original_full", "original", "ep1",
             [1, 2, 3], 0, 5),
        _req("r-rc1", "songA", "R-C_subdiv_0.5", "R-C", "ep1", [1, 2, 3], 0, 2),
        _req("r-rc2", "songA", "R-C_subdiv_0.5_hi", "R-C", "ep1", [1, 2, 3], 3, 5),
    ]
    evidence = {
        "r-orig": _evidence("r-orig", [
            _row(0, TEXTS[0:6], 0.0, 1.0), _row(1, TEXTS[0:6], 1.5, 2.5),
            _row(2, TEXTS[0:6], 2.1, 3.1), _row(3, TEXTS[0:6], 5.0, 6.0),
            _row(4, TEXTS[0:6], 4.0, 5.0), _row(5, TEXTS[0:6], 5.0, 6.0),
        ]),
        "r-rc1": _evidence("r-rc1", [
            _row(0, TEXTS[0:3], 0.0, 1.0), _row(1, TEXTS[0:3], 1.0, 2.0),
            _row(2, TEXTS[0:3], 2.0, 3.0),
        ]),
        "r-rc2": _evidence("r-rc2", [
            _row(0, TEXTS[3:6], 3.0, 4.0), _row(1, TEXTS[3:6], 4.0, 5.0),
            _row(2, TEXTS[3:6], 5.0, 6.0),
        ]),
    }
    summary = _run(tmp_path, requests, evidence, ["songA"])

    assert summary["labeled_episode_count"] == 1
    assert summary["unlabeled_episode_count"] == 0
    ep1 = summary["per_episode"]["ep1"]
    assert set(ep1["variants"]) == {"original_full", "R-C_subdiv_0.5", "R-C_subdiv_0.5_hi"}

    orig = ep1["variants"]["original_full"]
    assert orig["n_units"] == 3
    assert orig["n_repaired"]["1.0"] == 2
    assert orig["n_repaired"]["2.0"] == 3
    assert orig["repair_rate"]["1.0"] == pytest.approx(2 / 3)
    assert orig["repair_rate"]["2.0"] == 1.0

    pm = summary["per_method"]
    assert pm["original"]["n_units"] == 3
    assert pm["R-C"]["n_units"] == 3
    assert pm["R-C"]["repair_rate"]["1.0"] == 1.0


def test_coverage_missing_excess_handcount(tmp_path):
    requests = [
        _req("r-orig", "songA", "original_full", "original", "ep1", [1, 2, 3], 0, 5),
        _req("r-ra", "songA", "R-A_unsafe_old_range", "R-A", "ep1", [1, 2, 3], 0, 5),
    ]
    evidence = {
        # orig: all 3 targets valid -> coverage 1.0, extras = units 0,4,5
        "r-orig": _evidence("r-orig", [
            _row(0, TEXTS[0:6], 0.0, 1.0), _row(1, TEXTS[0:6], 1.0, 2.0),
            _row(2, TEXTS[0:6], 2.0, 3.0), _row(3, TEXTS[0:6], 3.0, 4.0),
            _row(4, TEXTS[0:6], 4.0, 5.0), _row(5, TEXTS[0:6], 5.0, 6.0),
        ]),
        # R-A: unit 3 (丁) missing, rest present -> missing=1, coverage=2/3
        "r-ra": _evidence("r-ra", [
            _row(0, TEXTS[0:6], 0.0, 1.0), _row(1, TEXTS[0:6], 1.0, 2.0),
            _row(2, TEXTS[0:6], 2.0, 3.0),
            _row(4, TEXTS[0:6], 4.0, 5.0), _row(5, TEXTS[0:6], 5.0, 6.0),
        ]),
    }
    summary = _run(tmp_path, requests, evidence, ["songA"])
    orig = summary["per_episode"]["ep1"]["variants"]["original_full"]
    assert orig["character_coverage"] == 1.0
    assert orig["missing_prediction_count"] == 0
    assert orig["extra_prediction_count"] == 3
    assert orig["invalid_prediction_rate"] == 0.0
    assert orig["reference_character_count"] == 3

    ra = summary["per_episode"]["ep1"]["variants"]["R-A_unsafe_old_range"]
    assert ra["character_coverage"] == pytest.approx(2 / 3)
    assert ra["missing_prediction_count"] == 1
    assert ra["missing_prediction_rate"] == pytest.approx(1 / 3)
    assert ra["extra_prediction_count"] == 3


def test_unlabeled_episode_excluded_from_denominator(tmp_path):
    requests = [
        _req("r-a", "songA", "original_full", "original", "ep1", [1, 2, 3], 0, 5),
        _req("r-b", "songB", "original_full", "original", "ep2", [1, 2, 3], 0, 5),
        _req("r-b2", "songB", "oracle_O0", "oracle_O0", "ep2", [1, 2, 3], 1, 3),
    ]
    evidence = {
        "r-a": _evidence("r-a", [_row(i, TEXTS[0:6], GT_SEC[i][0], GT_SEC[i][1]) for i in range(6)]),
        "r-b": _evidence("r-b", [_row(i, TEXTS[0:6], GT_SEC[i][0], GT_SEC[i][1]) for i in range(6)]),
        "r-b2": _evidence("r-b2", [_row(i, TEXTS[1:4], GT_SEC[1 + i][0], GT_SEC[1 + i][1]) for i in (0, 1, 2)]),
    }
    summary = _run(tmp_path, requests, evidence, ["songA"])

    assert summary["labeled_episode_count"] == 1
    assert summary["unlabeled_episode_count"] == 1
    assert summary["unlabeled_episodes"][0]["episode_id"] == "ep2"
    assert summary["unlabeled_episodes"][0]["labeled"] is False

    pm = summary["per_method"]
    assert pm["original"]["n_units"] == 3
    assert pm["original"]["n_repaired"]["1.0"] == 3
    assert "oracle_O0" not in pm or pm["oracle_O0"]["n_units"] == 0
    assert "ep2" not in summary["per_episode"]["ep1"]["variants"]


def test_oracle_best_selection(tmp_path):
    requests = [
        _req("o0", "songA", "oracle_O0", "oracle_O0", "ep1", [1, 2, 3], 1, 3),
        _req("o1", "songA", "oracle_O1", "oracle_O1", "ep1", [1, 2, 3], 1, 3),
        _req("o2", "songA", "oracle_O2", "oracle_O2", "ep1", [1, 2, 3], 1, 3),
        _req("o3", "songA", "oracle_O3", "oracle_O3", "ep1", [1, 2, 3], 1, 3),
    ]
    evidence = {
        # O0 all err 1.5s -> not repaired at <=1.0
        "o0": _evidence("o0", [_row(i, TEXTS[1:4], GT_SEC[1 + i][0] + 1.5, GT_SEC[1 + i][1] + 1.5) for i in (0, 1, 2)]),
        # O1/O2/O3 err 0.5s -> repaired at <=1.0
        "o1": _evidence("o1", [_row(i, TEXTS[1:4], GT_SEC[1 + i][0] + 0.5, GT_SEC[1 + i][1] + 0.5) for i in (0, 1, 2)]),
        "o2": _evidence("o2", [_row(i, TEXTS[1:4], GT_SEC[1 + i][0] + 0.5, GT_SEC[1 + i][1] + 0.5) for i in (0, 1, 2)]),
        "o3": _evidence("o3", [_row(i, TEXTS[1:4], GT_SEC[1 + i][0] + 0.5, GT_SEC[1 + i][1] + 0.5) for i in (0, 1, 2)]),
    }
    summary = _run(tmp_path, requests, evidence, ["songA"])
    best = summary["per_episode"]["ep1"]["oracle_best"]
    assert best["1.0"]["repair_rate"] == 1.0
    assert best["1.0"]["variant"] == "oracle_O1"
    assert best["5.0"]["repair_rate"] == 1.0


def test_oracle_noncontiguous_text_maps_to_target_ids(tmp_path):
    # Regression: oracle text == episode target ids, which may contain
    # windowing gaps (units 211..237 absent from fixed 60s windows). The eval
    # must map via target_unit_ids, not assume contiguous text.
    target_ids = [0, 1, 2, 4, 5]  # gap at 3
    text_units = [TEXTS[i] for i in target_ids]
    req = {
        "request_id": "r-o",
        "item_id": "songA",
        "source_song_id": "songA",
        "input_variant": "oracle_O0",
        "text_units": text_units,
        "provenance": {
            "episode_id": "ep1",
            "episode_family": "natural",
            "episode_kind": "natural",
            "source_window_id": "songA:w0:full",
            "target_unit_start": target_ids[0],
            "target_unit_end": target_ids[-1],
            "target_unit_ids": target_ids,
            "text_unit_start": 1,
            "text_unit_end": 8,
            "proposal_method": "oracle_O0",
        },
    }
    # evidence rows: gci 0..5 map to target ids 1,2,3,6,7,8 respectively
    evidence = {
        "r-o": _evidence("r-o", [
            _row(i, text_units, GT_SEC[c][0], GT_SEC[c][1])
            for i, c in enumerate(target_ids)
        ]),
    }
    summary = _run(tmp_path, [req], evidence, ["songA"])
    v = summary["per_episode"]["ep1"]["variants"]["oracle_O0"]
    assert v["n_units"] == 5
    assert v["repair_rate"]["1.0"] == 1.0
    assert v["character_coverage"] == 1.0
    assert v["missing_prediction_count"] == 0
    assert v["extra_prediction_count"] == 0


def test_per_family_grouping(tmp_path):
    requests = [
        _req("r-a", "songA", "original_full", "original", "ep1", [1, 2, 3], 0, 5,
             family="natural"),
        _req("r-b", "songA", "original_full", "original", "ep2", [4, 5], 0, 5,
             family="P3"),
    ]
    evidence = {
        "r-a": _evidence("r-a", [_row(i, TEXTS[0:6], GT_SEC[i][0], GT_SEC[i][1]) for i in range(6)]),
        "r-b": _evidence("r-b", [_row(i, TEXTS[0:6], GT_SEC[i][0], GT_SEC[i][1]) for i in range(6)]),
    }
    summary = _run(tmp_path, requests, evidence, ["songA"])
    assert summary["per_family"]["natural"]["n_units"] == 3
    assert summary["per_family"]["P3"]["n_units"] == 2
    assert summary["per_song"]["songA"]["n_units"] == 5
