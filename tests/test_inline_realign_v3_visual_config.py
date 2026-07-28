from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

from lyricalign.demo.experiment_config import apply_if_unsupplied, get_path, supplied_flags


ROOT = Path(__file__).resolve().parents[1]


def load_script(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / "demo" / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def make_minimal_result(root: Path) -> str:
    item_id = "demo_Chinese_song_ab12cd34"
    manifest = {
        "item_id": item_id,
        "dataset": "demo",
        "profile": "long_serial",
        "language": "Chinese",
        "alignment_unit_mode": "cjk_character",
        "duration_bucket": "short",
        "selection_role": "all_demo",
        "gt_path": None,
    }
    (root / "experiment_manifest.jsonl").write_text(json.dumps(manifest) + "\n", encoding="utf-8")
    write_json(root / "experiment_summary.json", {"completed_item_count": 1, "failed_item_count": 0})
    item_root = root / "items" / item_id
    write_json(item_root / "item_summary.json", manifest)
    rows = [
        {"global_character_index": 0, "character": "歌", "start_sec": 0.0, "end_sec": 0.4},
        {"global_character_index": 1, "character": "词", "start_sec": 0.4, "end_sec": 0.4},
    ]
    alignment = {
        "characters": rows,
        "summary": {"character_count": 2, "window_count": 1, "audio_duration_sec": 1.0, "gt": {}},
        "window_trace": [],
    }
    for branch in ("B0_60_fixed_official", "B1_30_fixed_official", "B2_30_silence_official"):
        write_json(item_root / "branches" / branch / "alignment.json", alignment)
        write_json(item_root / "branches" / branch / "summary.json", alignment["summary"])
    write_json(item_root / "visuals" / "visual_analysis.json", {
        "tracks": ["B2_30_silence_official"],
        "metrics": {
            "B2_30_silence_official": {
                "timing": None,
                "duration": {"unit_count": 2, "zero_duration_count": 1},
            }
        },
        "inconsistency": {},
        "detector_span_count": 0,
    })
    return item_id


def test_yaml_values_apply_only_without_explicit_cli_override() -> None:
    args = SimpleNamespace(value=3)
    supplied = supplied_flags(["--value=9"])
    apply_if_unsupplied(args, supplied=supplied, flag="--value", attribute="value", value=7)
    assert args.value == 3
    args2 = SimpleNamespace(value=3)
    apply_if_unsupplied(args2, supplied=set(), flag="--value", attribute="value", value=7)
    assert args2.value == 7
    assert get_path({"a": {"b": 4}}, "a.b") == 4


def test_summary_uses_manifest_only_and_emits_grouped_totals(tmp_path: Path) -> None:
    item_id = make_minimal_result(tmp_path)
    (tmp_path / "items" / "stale_old").mkdir(parents=True)
    module = load_script("summary_v3", "summarize_inline_realign_followup.py")
    payload = module.summarize(tmp_path)
    assert payload["experiment_status"]["summarized_item_count"] == 1
    assert payload["experiment_status"]["stale_item_directory_count"] == 1
    assert payload["items"][0]["item_id"] == item_id
    total = next(
        row for row in payload["grouped_results"]
        if row["dataset"] == "__TOTAL__" and row["variant"] == "B2_30_silence_official"
    )
    assert total["unit_count"] == 2
    assert total["zero_duration_rate"] == 0.5


def test_evidence_collection_uses_manifest_only_and_reports_stale(tmp_path: Path) -> None:
    item_id = make_minimal_result(tmp_path)
    (tmp_path / "items" / "stale_old").mkdir(parents=True)
    module = load_script("collector_v3", "collect_inline_realign_evidence.py")
    staging = tmp_path / "staging"
    staging.mkdir()
    metadata = module.collect(tmp_path, staging, mode="minimal", max_cases=2)
    assert metadata["item_count"] == 1
    assert metadata["stale_item_directory_count"] == 1
    report = json.loads((staging / "stale_item_report.json").read_text(encoding="utf-8"))
    assert report["stale_item_directories"] == ["stale_old"]
    summaries = json.loads((staging / "item_summaries.json").read_text(encoding="utf-8"))
    assert [row["item_id"] for row in summaries] == [item_id]
