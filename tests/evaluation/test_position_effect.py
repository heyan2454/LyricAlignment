from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "position_vs_duration_test", ROOT / "scripts" / "evaluation" / "position_vs_duration_test.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def _dump(tmp_path: Path, items: dict[str, list[tuple[float, float]]]) -> Path:
    """items: item_id -> list of (duration, offset_err) in character order."""
    lines = []
    for item, chars in items.items():
        for index, (duration, error) in enumerate(chars):
            base = {"item_id": item, "index": index, "channel": "d_rms",
                    "duration": duration, "abs_err_argmax": error,
                    "entropy_nats": 0.5, "p_top1": 0.9, "pred_sec": 1.0 + index * duration}
            onset = dict(base, kind="onset")
            offset = dict(base, kind="offset", pred_sec=base["pred_sec"] + duration)
            lines.append(json.dumps(onset))
            lines.append(json.dumps(offset))
    path = tmp_path / "per_character.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_characters_marks_only_the_true_last_position(tmp_path: Path):
    path = _dump(tmp_path, {"A#s#1": [(0.3, 0.01)] * 4 + [(2.0, 0.5)]})
    rows = MODULE.characters(path)
    assert len(rows) == 5
    assert [row["last"] for row in rows] == [False, False, False, False, True]


def test_short_items_are_skipped_instead_of_diluting_the_test(tmp_path: Path):
    path = _dump(tmp_path, {"A#s#1": [(0.3, 0.01), (0.3, 0.01)], "B#s#2": [(0.3, 0.01)] * 5})
    rows = MODULE.characters(path)
    assert {row["item"] for row in rows} == {"B#s#2"}


def test_confound_is_reported_and_raw_gap_is_not_called_a_result(tmp_path: Path):
    # 末字全是长音、内部全是短音 ⇒ 任何"末字更差"都必须归因于时长而非位置
    items = {f"S#x#{index}": [(0.3, 0.01)] * 20 + [(2.5, 0.9)] for index in range(6)}
    rows = MODULE.characters(_dump(tmp_path, items))
    payload = MODULE.analyse(rows)
    assert payload["confound"]["share_long_last"] == 1.0
    assert payload["confound"]["share_long_interior"] < 0.05
    long_block = payload["stratified"].get("2s+", {})
    assert long_block.get("status") != "measured"     # 内部层没有长音样本，绝不给出"位置有效"的结论
    assert long_block.get("interior_characters", 0) < MODULE.MIN_CELL


def test_two_proportion_reports_significance_only_for_real_separation():
    good = [{"max_err": 0.01, "dur": 0.3} for _ in range(200)]
    bad = [{"max_err": 0.5 if index % 20 == 0 else 0.01, "dur": 0.3} for index in range(200)]
    block = MODULE.two_proportion(bad, good, "max_err")
    assert block["status"] == "measured" and block["delta_pp"] > 4 and block["p"] < 0.01
    # 两群都零缺陷时不得编造显著性（pooled=0 ⇒ se=0 ⇒ z 与 p 都取保守值）
    same = MODULE.two_proportion(good, good, "max_err")
    assert same["z"] == 0.0 and same["p"] == 1.0


def test_analysis_confirmes_a_clean_separation_and_flags_a_weak_one():
    """同一套判定：强分离必须"确证"，微弱分离只能"迹象"或"无证据"，不许一律写成结论。"""
    strong, weak = [], []
    for index in range(400):
        strong.append({"last": index < 200, "position": 0.5, "dur": 0.3,
                       "max_err": 0.5 if (index < 200 and index % 5 == 0) else 0.01,
                       "offset_err": 0.01, "item": "S#x#1"})
    for index in range(400):
        weak.append({"last": index < 200, "position": 0.5, "dur": 0.3,
                     "max_err": 0.5 if (index < 200 and index % 100 == 0) else 0.01,
                     "offset_err": 0.01, "item": "S#x#2"})
    strong_verdict = MODULE.analyse(strong)["stratified"]["0-0.5s"]["verdict"]
    weak_verdict = MODULE.analyse(weak)["stratified"]["0-0.5s"]["verdict"]
    assert strong_verdict == "确证", strong_verdict
    assert weak_verdict != "确证", weak_verdict
