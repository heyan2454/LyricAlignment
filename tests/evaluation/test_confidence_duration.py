from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "confidence_duration_interaction", ROOT / "scripts" / "evaluation" / "confidence_duration_interaction.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def _dump(tmp_path: Path, rows: list[dict]) -> Path:
    path = tmp_path / "per_character.jsonl"
    lines = []
    for index, row in enumerate(rows):
        item = f"singer#song#000{index % 3}"
        base = {"item_id": item, "index": index, "channel": "d_rms", "duration": row["dur"],
                "pred_sec": 1.0 + index * 0.01}
        onset = dict(base, kind="onset", abs_err_argmax=row["err"], entropy_nats=row["ent"], p_top1=1 - row["ent"] / 5)
        offset = dict(base, kind="offset", duration=row["dur"],
                      pred_sec=base["pred_sec"] + row["dur"], abs_err_argmax=row["err"],
                      entropy_nats=row["ent"], p_top1=1 - row["ent"] / 5)
        lines.append(json.dumps(onset))
        lines.append(json.dumps(offset))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_exact_predictions_report_ratio_one_even_when_long_items_are_uncertain(tmp_path: Path):
    """长字符只是更不确信时，不得凭空报出『时长被压短』——这正是分桶交叉要防的混杂。"""
    rows = [{"dur": 0.3, "ent": 0.2, "err": 0.01}] * 30 + [{"dur": 2.4, "ent": 2.0, "err": 0.05}] * 30
    parsed = MODULE.characters(_dump(tmp_path, rows))
    cuts = MODULE.quartiles(parsed)
    table = MODULE.table(parsed, cuts)
    durations = set()
    for name, cell in table.items():
        if name.startswith("_"):
            continue
        for block in cell.values():
            durations.add(block["median_ratio"])
    assert all(abs(value - 1.0) < 0.05 for value in durations), durations
    totals = table["_bucket_totals"]
    assert totals["0-0.5s"]["characters"] == 30 and totals["2s+"]["characters"] == 30


def test_pooled_correlation_can_be_positive_while_within_bucket_correlation_vanishes(tmp_path: Path):
    """混池相关由时长驱动；分桶后必须归零，否则报告会误以为存在『回归到众数』。"""
    rows = [{"dur": 0.3, "ent": 0.2, "err": 0.01}, {"dur": 0.3, "ent": 0.25, "err": 0.01},
            {"dur": 2.4, "ent": 2.0, "err": 0.05}, {"dur": 2.4, "ent": 2.4, "err": 0.05}] * 20
    parsed = MODULE.characters(_dump(tmp_path, rows))
    pooled = MODULE.correlation(parsed)
    inside = MODULE.correlation(parsed, only="0-0.5s")
    assert pooled["status"] == "measured" and pooled["pearson_r"] > 0.5
    assert inside["status"] == "degenerate_variance", inside   # 恒定序列不得算出相关（浮点残差会造假）


def test_degenerate_variance_does_not_raise_and_incomplete_pairs_are_dropped(tmp_path: Path):
    rows = [{"dur": 0.4, "ent": 0.5, "err": 0.02}] * 40
    parsed = MODULE.characters(_dump(tmp_path, rows))
    assert len(parsed) == 40
    result = MODULE.correlation(parsed)              # 熵与距离都无方差 ⇒ 走退化保护分支
    assert result["status"] == "degenerate_variance"
    assert math.isfinite(result["n"])
    path = _dump(tmp_path, rows)
    broken = path.read_text().splitlines()[:-2]      # 拆掉最后一对，留下不完整字符
    path.write_text("\n".join(broken) + "\n", encoding="utf-8")
    assert len(MODULE.characters(path)) == 39


def test_bucket_edges_are_monotonic_and_named():
    assert MODULE.bucket(0.4) == "0-0.5s" and MODULE.bucket(0.9) == "0.5-1s"
    assert MODULE.bucket(1.5) == "1-2s" and MODULE.bucket(2.0) == "2s+"
