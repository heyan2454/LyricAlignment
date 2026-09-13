from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "confidence_abstention", ROOT / "scripts" / "evaluation" / "confidence_abstention.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_auc_perfect_reversed_and_ties():
    labels = [0, 0, 1, 1]
    assert MODULE.auc([0.1, 0.2, 0.8, 0.9], labels) == 1.0
    assert MODULE.auc([0.9, 0.8, 0.2, 0.1], labels) == 0.0
    assert MODULE.auc([0.5, 0.5, 0.5, 0.5], labels) == 0.5          # 全平局 = 无信息
    assert MODULE.auc([0.1, 0.3, 0.2, 0.9], labels) == 0.75         # 一对反序
    assert MODULE.auc([0.1, 0.2], [0, 0]) is None                   # 缺一类就无法定义


def test_abstention_curve_accounts_for_every_dropped_unit():
    risk = [0.9, 0.8, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1]
    bad = [1, 1, 0, 0, 0, 0, 0, 0, 0, 0]
    curve = MODULE.abstention_curve(risk, bad, fractions=(0.1, 0.2))
    assert curve["drop_10pct"]["removed_units"] == 1
    assert curve["drop_10pct"]["removed_error_share"] == 0.5
    assert curve["drop_10pct"]["residual_rate"] == round(1 / 9, 4)
    assert curve["drop_20pct"]["removed_error_share"] == 1.0
    assert curve["drop_20pct"]["residual_rate"] == 0.0


def test_from_dump_reads_only_the_confidence_bearing_rows(tmp_path: Path):
    rows = [
        {"channel": "d_rms", "kind": "offset", "long": False, "duration": 0.4, "abs_err_argmax": 0.05,
         "p_top1": 0.8, "entropy_nats": 0.5, "label_rank": 1, "top5_mass": 0.98},
        {"channel": "d_rms", "kind": "offset", "long": True, "duration": 2.0, "abs_err_argmax": 0.5,
         "p_top1": 0.2, "entropy_nats": 3.0, "label_rank": 40, "top5_mass": 0.4},
        {"channel": "flux", "kind": "offset", "long": False, "duration": 0.4, "abs_err_argmax": 0.9,
         "p_top1": 0.1, "entropy_nats": 4.0, "label_rank": 99, "top5_mass": 0.1},
        {"channel": "d_rms", "kind": "onset", "long": False, "duration": 0.4, "abs_err_argmax": 0.9},
    ]
    path = tmp_path / "per_character.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    out = MODULE.from_dump(path)
    assert out["units"] == 2                                   # flux 行与缺诊断字段的行都不计入
    assert out["error_rate"] == 0.5
    assert out["by_duration"]["long"]["units"] == 1
    assert out["by_duration"]["short"]["units"] == 1
