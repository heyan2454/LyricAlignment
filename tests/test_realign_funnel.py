from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_module():
    path = ROOT / "scripts" / "demo" / "build_realign_funnel.py"
    spec = importlib.util.spec_from_file_location("realign_funnel_test_module", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_evidence(root: Path, decoder: str, spans: list[tuple[int, int]]) -> None:
    path = root / "evidence" / "core_30s" / "demucs" / "song.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": "complete",
        "request": {"item_id": "song", "audio_variant": "demucs", "core_sec": 30.0},
        "natural_candidates": [
            {
                "case_id": f"{decoder}_{start}_{end}",
                "dependency_character_start": start,
                "dependency_character_end": end,
                "severity_score": float(end - start + 1),
                "candidate_type": "collapse",
            }
            for start, end in spans
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_union_merges_overlapping_candidates_from_three_decoders(tmp_path: Path) -> None:
    module = load_module()
    roots = {
        "official": tmp_path / "official",
        "gpu_tcn": tmp_path / "tcn",
        "gpu_transformer": tmp_path / "transformer",
    }
    write_evidence(roots["official"], "official", [(3, 5)])
    write_evidence(roots["gpu_tcn"], "tcn", [(5, 7), (12, 13)])
    write_evidence(roots["gpu_transformer"], "transformer", [(6, 9)])
    rows = module.union_plan(roots, max_cases=100, max_target_units=8)
    assert len(rows) == 2
    merged = min(rows, key=lambda row: row["target_start"])
    assert (merged["target_start"], merged["target_end"]) == (3, 9)
    assert merged["source_decoders"] == ["gpu_tcn", "gpu_transformer", "official"]
    assert merged["paired_decoders"] == ["gpu_tcn", "gpu_transformer", "official"]


def test_round_robin_cap_retains_multiple_items() -> None:
    module = load_module()
    rows = [
        {"item_id": item, "severity_score": score, "pair_id": f"{item}-{score}"}
        for item in ("a", "b", "c")
        for score in (3, 2, 1)
    ]
    selected = module.round_robin_cap(rows, 4)
    assert len(selected) == 4
    assert len({row["item_id"] for row in selected}) == 3


def test_decoder_root_cli_parser_requires_unique_names(tmp_path: Path) -> None:
    module = load_module()
    roots = module.parse_decoder_roots([
        f"official={tmp_path / 'o'}",
        f"gpu_tcn={tmp_path / 't'}",
        f"gpu_transformer={tmp_path / 'x'}",
    ])
    assert set(roots) == {"official", "gpu_tcn", "gpu_transformer"}
