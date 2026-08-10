"""stage3b 回归：Research V7 long-slot timing reaggregation on accepted real GT。

合成小 manifest（2 歌）+ 混合 annotations（accepted/review_required/缺时间）+ REQUESTS，
断言：
- denom 只含 accepted 且被 query 的单位；
- 四类计数（canonical_units / accepted_real_gt_units / unlabeled_units /
  context_only_not_queried）正确；
- 无 accepted 单位的 request 指标为 None（不产生数值）；
- 缺身份等价预测 / canonical mapping 的 request 进 RERUN_REQUESTS_GPU.jsonl；
- 确定性（同输入两次运行输出一致）；
- tolerance 命中率计算正确。
"""
from __future__ import annotations

import json
from pathlib import Path

from scripts.research_v7.reaggregate_long_slot_real_gt import reaggregate

COHORT = [
    {"song_id": "songA", "split": "train", "role": "source"},
    {"song_id": "songB", "split": "validation", "role": "target"},
]

# songA 6 units，seg "segA" offset 0.0
SONGA_UNITS = [
    {"canonical_unit_id": 10, "text": "a", "start_sec": 0.0, "end_sec": 0.5},
    {"canonical_unit_id": 11, "text": "b", "start_sec": 0.5, "end_sec": 1.0},
    {"canonical_unit_id": 12, "text": "c", "start_sec": 1.0, "end_sec": 1.6},
    {"canonical_unit_id": 13, "text": "d", "start_sec": 1.6, "end_sec": 2.2},
    {"canonical_unit_id": 14, "text": "e", "start_sec": 2.2, "end_sec": 2.8},
    {"canonical_unit_id": 15, "text": "f", "start_sec": 2.8, "end_sec": 3.4},
]
SONGB_UNITS = [
    {"canonical_unit_id": 20, "text": "a", "start_sec": 0.0, "end_sec": 0.4},
    {"canonical_unit_id": 21, "text": "b", "start_sec": 0.4, "end_sec": 0.9},
    {"canonical_unit_id": 22, "text": "c", "start_sec": 0.9, "end_sec": 1.4},
    {"canonical_unit_id": 23, "text": "d", "start_sec": 1.4, "end_sec": 2.0},
    {"canonical_unit_id": 24, "text": "e", "start_sec": 2.0, "end_sec": 2.6},
]


def _manifest_row(song: str, units: list[dict]) -> dict:
    return {
        "song_id": song,
        "segment_offsets": [{"source_segment_id": f"seg{song[-1]}", "global_start_sec": 0.0}],
        "canonical_units": [
            {**u, "source_segment_id": f"seg{song[-1]}",
             "source_unit_index": i}
            for i, u in enumerate(units)
        ],
    }


def _status_row(status: str, start: float | None, end: float | None) -> dict:
    return {"mapping_status": status, "start_sec": start, "end_sec": end}


def _annotation(song: str, unit: dict, status: str,
                start: float | None, end: float | None,
                index: int | None = None) -> dict:
    return {
        "song_id": song,
        "item_id": f"seg{song[-1]}",
        "character_index": unit["source_unit_index"] if index is None else index,
        "normalized_character": unit["text"],
        "raw_character": unit["text"],
        **_status_row(status, start, end),
    }


def _requests(song: str, rid: str, cids: list[int]) -> dict:
    return {
        "request_id": rid,
        "item_id": rid,
        "canonical_ids": cids,
        "text_units": [{"index": i} for i in range(len(cids))],
        "source_window_sec": [0.0, 3.4],
        "mutation_type": "baseline",
        "split": "train" if song == "songA" else "validation",
    }


def _write(tmp: Path) -> dict[str, Path]:
    cohort = tmp / "COHORT_A_FORMAL.jsonl"
    cohort.write_text("".join(json.dumps(r) + "\n" for r in COHORT), encoding="utf-8")

    timeline = tmp / "LONG_TIMELINE_MANIFEST.jsonl"
    timeline.write_text(
        json.dumps(_manifest_row("songA", SONGA_UNITS)) + "\n"
        + json.dumps(_manifest_row("songB", SONGB_UNITS)) + "\n",
        encoding="utf-8")

    annotations = tmp / "m4singer_character_annotations.jsonl"
    ann_rows = [
        # songA: 10/11/13/15 accepted；12 review_required；14 缺时间
        _annotation("songA", SONGA_UNITS[0], "accepted_rule_based_pinyin_validated", 0.0, 0.5, index=0),
        _annotation("songA", SONGA_UNITS[1], "accepted_rule_based_pinyin_validated", 0.5, 1.0, index=1),
        _annotation("songA", SONGA_UNITS[2], "review_required_something", 1.0, 1.6, index=2),
        _annotation("songA", SONGA_UNITS[3], "accepted_rule_validated_held_vowel", 1.6, 2.2, index=3),
        _annotation("songA", SONGA_UNITS[4], "accepted_rule_based_pinyin_validated", None, None, index=4),
        _annotation("songA", SONGA_UNITS[5], "accepted_rule_based_pinyin_validated", 2.8, 3.4, index=5),
        # songB: 20-24 全 accepted
        _annotation("songB", SONGB_UNITS[0], "accepted_rule_based_pinyin_validated", 0.0, 0.4, index=0),
        _annotation("songB", SONGB_UNITS[1], "accepted_rule_based_pinyin_validated", 0.4, 0.9, index=1),
        _annotation("songB", SONGB_UNITS[2], "accepted_rule_based_pinyin_validated", 0.9, 1.4, index=2),
        _annotation("songB", SONGB_UNITS[3], "accepted_rule_based_pinyin_validated", 1.4, 2.0, index=3),
        _annotation("songB", SONGB_UNITS[4], "accepted_rule_based_pinyin_validated", 2.0, 2.6, index=4),
    ]
    annotations.write_text("".join(json.dumps(r) + "\n" for r in ann_rows), encoding="utf-8")

    reqs = tmp / "REQUESTS.jsonl"
    req_rows = [
        _requests("songA", "songA:w0:full", [10, 11, 12, 13, 14, 15]),
        _requests("songB", "songB:w0:full", [20, 21, 22, 23, 24]),
        _requests("songA", "songA:w2:full", [12, 14]),          # 无 accepted -> metrics None
        _requests("songA", "songA:w1:full", [10, 11, 13]),      # 历史行映射缺失
        _requests("songA", "songA:w0:nog", [10, 11]),           # 无历史预测
    ]
    reqs.write_text("".join(json.dumps(r) + "\n" for r in req_rows), encoding="utf-8")

    hist = tmp / "historical_predictions.json"
    hist.write_text(json.dumps({
        "schema": "research_v7_gt_eval_v1",
        "per_request": [
            {"request_id": "songA:w0:full", "prediction_sha": "shaAAA",
             "rows": [
                 {"canonical_unit_id": 10, "pred_start_sec": 0.06, "pred_end_sec": 0.56},
                 {"canonical_unit_id": 11, "pred_start_sec": 0.5, "pred_end_sec": 1.05},
                 {"canonical_unit_id": 13, "pred_start_sec": 1.6, "pred_end_sec": 2.25},
                 {"canonical_unit_id": 15, "pred_start_sec": 2.8, "pred_end_sec": 3.45},
             ]},
            {"request_id": "songB:w0:full",
             "rows": [
                 {"canonical_unit_id": 20, "pred_start_sec": 0.0, "pred_end_sec": 0.4},
                 {"canonical_unit_id": 21, "pred_start_sec": 0.4, "pred_end_sec": 0.9},
                 {"canonical_unit_id": 22, "pred_start_sec": 0.9, "pred_end_sec": 1.4},
                 {"canonical_unit_id": 23, "pred_start_sec": 1.4, "pred_end_sec": 2.0},
                 {"canonical_unit_id": 24, "pred_start_sec": 2.0, "pred_end_sec": 2.6},
             ]},
            {"request_id": "songA:w2:full",
             "rows": [
                 {"canonical_unit_id": 12, "pred_start_sec": 1.1, "pred_end_sec": 1.7},
                 {"canonical_unit_id": 14, "pred_start_sec": 2.3, "pred_end_sec": 2.9},
             ]},
            # 行带越界 global_character_index -> canonical mapping 缺失
            {"request_id": "songA:w1:full",
             "rows": [
                 {"global_character_index": 99, "pred_start_sec": 0.1, "pred_end_sec": 0.6},
             ]},
        ],
    }, ensure_ascii=False), encoding="utf-8")
    return {"cohort": cohort, "timeline": timeline, "annotations": annotations,
            "requests": reqs, "hist": hist}


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def test_denom_accepted_queried_and_counts(tmp_path: Path) -> None:
    files = _write(tmp_path)
    out = tmp_path / "out1"
    reaggregate(files["cohort"], files["timeline"], files["annotations"],
                files["requests"], historical_predictions=files["hist"], out=out,
                metric_tolerances=[50, 100, 250])

    summary = json.loads((out / "REAGGREGATION_SUMMARY.json").read_text(encoding="utf-8"))
    per_request = {r["request_id"]: r for r in _read_jsonl(out / "PER_REQUEST.jsonl")}

    a0 = per_request["songA:w0:full"]
    # denom = accepted ∩ queried = {10,11,13,15}
    assert a0["counts"]["accepted_real_gt_units"] == 4
    assert a0["n_denom"] == 4
    assert [u["canonical_unit_id"] for u in a0["unit_errors"]] == [10, 11, 13, 15]
    assert a0["counts"]["canonical_units"] == 6
    assert a0["counts"]["unlabeled_units"] == 2  # cid12 review_required, cid14 缺时间
    assert a0["prediction_sha"] == "shaAAA"

    # 四类计数（macro 级 = 各 song 并集后求和）
    counts = summary["counts"]
    # queried 并集 songA={10..15} songB={20..24}；accepted 并集 songA=4 songB=5
    assert counts["canonical_units"] == 11
    assert counts["accepted_real_gt_units"] == 9
    assert counts["unlabeled_units"] == 2
    assert counts["context_only_not_queried"] == 0  # timeline 无未 query 单位

    # 被 exclusion 的 unit 不进 denom/unit_errors（cid12/14 只在无 accepted 的 request 中出现）
    b0 = per_request["songB:w0:full"]
    assert b0["n_denom"] == 5
    assert b0["metrics"]["start_mae_sec"] == 0.0
    assert b0["metrics"]["end_mae_sec"] == 0.0


def test_no_accepted_metrics_none(tmp_path: Path) -> None:
    files = _write(tmp_path)
    out = tmp_path / "out2"
    reaggregate(files["cohort"], files["timeline"], files["annotations"],
                files["requests"], historical_predictions=files["hist"], out=out,
                metric_tolerances=[50, 100, 250])
    per_request = {r["request_id"]: r for r in _read_jsonl(out / "PER_REQUEST.jsonl")}
    a2 = per_request["songA:w2:full"]
    assert a2["n_denom"] == 0
    assert a2["metrics"]["start_mae_sec"] is None
    assert a2["metrics"]["end_mae_sec"] is None
    assert a2["metrics"]["n_evaluated"] == 0
    assert all(v is None for v in a2["metrics"]["tolerance_hit_rates_ms"].values())


def test_rerun_requests_gpu(tmp_path: Path) -> None:
    files = _write(tmp_path)
    out = tmp_path / "out3"
    reaggregate(files["cohort"], files["timeline"], files["annotations"],
                files["requests"], historical_predictions=files["hist"], out=out,
                metric_tolerances=[50, 100, 250])
    rerun = {r["request_id"]: r for r in _read_jsonl(out / "RERUN_REQUESTS_GPU.jsonl")}
    assert rerun["songA:w0:nog"]["reason"] == "missing_identity_equivalent_prediction"
    assert rerun["songA:w1:full"]["reason"] == "missing_canonical_mapping"
    assert rerun["songA:w0:nog"]["song_id"] == "songA"
    # 这两个 request 不进 CPU reaggregate 输出
    per_request = {r["request_id"]: r for r in _read_jsonl(out / "PER_REQUEST.jsonl")}
    assert "songA:w0:nog" not in per_request
    assert "songA:w1:full" not in per_request
    summary = json.loads((out / "REAGGREGATION_SUMMARY.json").read_text(encoding="utf-8"))
    assert summary["n_requests_rerun_gpu"] == 2
    assert summary["n_requests_reaggregated"] == 3


def test_no_historical_all_rerun(tmp_path: Path) -> None:
    files = _write(tmp_path)
    out = tmp_path / "out4"
    reaggregate(files["cohort"], files["timeline"], files["annotations"],
                files["requests"], historical_predictions=None, out=out,
                metric_tolerances=[50, 100, 250])
    rerun = {r["request_id"]: r for r in _read_jsonl(out / "RERUN_REQUESTS_GPU.jsonl")}
    assert len(rerun) == 5
    assert all(r["reason"] == "missing_identity_equivalent_prediction"
               for r in rerun.values())
    summary = json.loads((out / "REAGGREGATION_SUMMARY.json").read_text(encoding="utf-8"))
    assert summary["n_requests_reaggregated"] == 0
    assert summary["n_requests_rerun_gpu"] == 5


def test_tolerance_hit_rate_and_determinism(tmp_path: Path) -> None:
    files = _write(tmp_path)
    out1 = tmp_path / "out5a"
    out2 = tmp_path / "out5b"
    reaggregate(files["cohort"], files["timeline"], files["annotations"],
                files["requests"], historical_predictions=files["hist"], out=out1,
                metric_tolerances=[50, 100, 250])
    reaggregate(files["cohort"], files["timeline"], files["annotations"],
                files["requests"], historical_predictions=files["hist"], out=out2,
                metric_tolerances=[50, 100, 250])
    # 确定性：两次运行输出一致（时间戳字段除外）
    for name in ("REAGGREGATION_SUMMARY.json", "PER_REQUEST.jsonl", "PER_SONG.jsonl",
                 "RERUN_REQUESTS_GPU.jsonl", "REAGGREGATION_FREEZE.json"):
        if name.endswith(".json"):
            lhs = json.loads((out1 / name).read_text(encoding="utf-8"))
            rhs = json.loads((out2 / name).read_text(encoding="utf-8"))
            lhs.pop("generated_at_utc", None)
            rhs.pop("generated_at_utc", None)
            lhs.get("structural_appendix", {}).pop("dir", None)
            rhs.get("structural_appendix", {}).pop("dir", None)
            assert lhs == rhs, name
        else:
            assert (out1 / name).read_bytes() == (out2 / name).read_bytes(), name

    per_request = {r["request_id"]: r for r in _read_jsonl(out1 / "PER_REQUEST.jsonl")}
    a0 = per_request["songA:w0:full"]
    m = a0["metrics"]
    # 期望误差：cid10 (0.06,0.06)；cid11 (0.0,0.05)；cid13 (0.0,0.05)；cid15 (0.0,0.05)
    assert m["n_evaluated"] == 4
    assert abs(m["start_mae_sec"] - 0.015) < 1e-9
    assert abs(m["end_mae_sec"] - 0.0525) < 1e-9
    rates = m["tolerance_hit_rates_ms"]
    assert rates["50"] == 0.75   # cid10 双边界 0.06 > 0.05 miss
    assert rates["100"] == 1.0
    assert rates["250"] == 1.0

    # macro 指标 = 全部 request 合并
    summary = json.loads((out1 / "REAGGREGATION_SUMMARY.json").read_text(encoding="utf-8"))
    macro = summary["macro_metrics"]
    # 4 个有 accepted 的 request（songA 4 误差 + songB 5 零误差 + songA:w2 无误差样本）
    # songA:w2 denom=0 -> n_evaluated=0，不贡献样本
    assert macro["n_evaluated"] == 9
    assert abs(macro["start_mae_sec"] - 0.015 * 4 / 9) < 1e-9
    assert abs(macro["end_mae_sec"] - 0.0525 * 4 / 9) < 1e-9


def test_freeze_and_out_of_cohort(tmp_path: Path) -> None:
    files = _write(tmp_path)
    out = tmp_path / "out6"
    # 额外加一首不在 cohort 的 request -> 跳过
    extra = tmp_path / "REQUESTS_extra.jsonl"
    extra.write_text(
        (files["requests"].read_text(encoding="utf-8"))
        + json.dumps(_requests("songX", "songX:w0:full", [30, 31])) + "\n",
        encoding="utf-8")
    reaggregate(files["cohort"], files["timeline"], files["annotations"], extra,
                historical_predictions=files["hist"], out=out,
                metric_tolerances=[50, 100, 250])
    freeze = json.loads((out / "REAGGREGATION_FREEZE.json").read_text(encoding="utf-8"))
    assert len(freeze["input_sha256"]) == 5
    assert isinstance(freeze["input_sha256"]["cohort_manifest"], str)
    assert len(freeze["input_sha256"]["cohort_manifest"]) == 64
    assert freeze["deterministic"] is True
    summary = json.loads((out / "REAGGREGATION_SUMMARY.json").read_text(encoding="utf-8"))
    assert summary["n_requests_skipped_out_of_cohort"] == 1
    # structural appendix 占位
    appendix = out / "structural_appendix" / "STRUCTURAL_APPENDIX_PLACEHOLDER.json"
    assert appendix.is_file()
    note = json.loads(appendix.read_text(encoding="utf-8"))
    assert "NOT merged into timing" in note["note"]
