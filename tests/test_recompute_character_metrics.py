from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "evaluation" / "recompute_character_metrics.py"
SPEC = importlib.util.spec_from_file_location("recompute_character_metrics", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_recompute_preserves_original_and_primary_metric(tmp_path: Path) -> None:
    refs = tmp_path / "refs.jsonl"
    preds = tmp_path / "preds.jsonl"
    original = tmp_path / "metrics.original.json"
    output = tmp_path / "metrics.corrected.json"
    row = {"item_id": "x", "song_id": "s", "character_index": 0, "normalized_character": "你", "start_sec": 0.0, "end_sec": 1.0}
    refs.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
    preds.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
    original.write_text(json.dumps({"loss": 2.0, "metric": {"song_macro_boundary_mae_sec": 0.0}}), encoding="utf-8")
    result = MODULE.recompute(references=refs, predictions=preds, original_metrics=original, output=output)
    assert original.read_text(encoding="utf-8")
    assert result["metric"]["metric_schema_version"] == "character_interval_metrics_v3_tolerant"
    assert result["primary_metric_unchanged"] is True
    assert json.loads(output.read_text(encoding="utf-8"))["loss"] == 2.0
