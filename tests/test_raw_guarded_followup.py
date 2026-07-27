from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def load_script(name: str, filename: str):
    path = ROOT / "scripts" / "demo" / filename
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_runtime_anchor_allows_zero_automatic_policies() -> None:
    module = load_script("realign_quick_validation_test", "run_demo_realign_quick.py")
    module.validate_anchor_policy_args(SimpleNamespace(
        max_automatic_anchor_policies=0,
        runtime_anchor_policy=True,
        include_gt_anchor=False,
    ))
    with pytest.raises(ValueError, match="requires --runtime-anchor-policy"):
        module.validate_anchor_policy_args(SimpleNamespace(
            max_automatic_anchor_policies=0,
            runtime_anchor_policy=False,
            include_gt_anchor=False,
        ))


def test_two_way_media_composite(tmp_path: Path) -> None:
    from lyricalign.demo.media_render import render_composite

    sources = []
    for ordinal in range(2):
        path = tmp_path / f"source_{ordinal}.mp4"
        subprocess.run(
            [
                "ffmpeg", "-nostdin", "-y", "-v", "error",
                "-f", "lavfi", "-i", f"color=c=black:s=160x90:r=5:d=0.4",
                "-f", "lavfi", "-i", f"sine=frequency={440 + ordinal * 20}:duration=0.4",
                "-map", "0:v:0", "-map", "1:a:0",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
                str(path),
            ],
            check=True,
        )
        sources.append(path)
    output = tmp_path / "two.mp4"
    result = render_composite(
        sources=sources,
        source_hashes=["a", "b"],
        output_path=output,
        layout="two",
        force=True,
    )
    assert output.is_file()
    assert result["skipped"] is False
    probe = json.loads(subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height", "-of", "json", str(output),
        ],
        check=True,
        text=True,
        capture_output=True,
    ).stdout)
    assert probe["streams"][0]["width"] == 1920
    assert probe["streams"][0]["height"] == 540


def test_full_demo_defaults_use_current_r2_checkpoint() -> None:
    script = (ROOT / "scripts" / "demo" / "run_raw_guarded_karaoke_demo.sh").read_text(encoding="utf-8")
    assert "20260724_qwen_fa_r2_full_seed20260724/checkpoints/step-000750" in script
    assert "render_raw_guarded_karaoke.py" in script
    renderer = (ROOT / "scripts" / "demo" / "render_raw_guarded_karaoke.py").read_text(encoding="utf-8")
    assert "raw_guarded_demo.mp4" in renderer


def test_detector_analyzer_reports_false_detection_and_trigger_prf(tmp_path: Path) -> None:
    evidence_root = tmp_path / "run"
    evidence_path = evidence_root / "evidence" / "core_30s" / "demucs" / "song.json"
    evidence_path.parent.mkdir(parents=True)
    rows = [
        {
            "global_character_index": 0,
            "character": "甲",
            "final_start_sec": 0.0,
            "final_end_sec": 0.4,
            "start_sec": 0.0,
            "end_sec": 0.4,
        },
        {
            "global_character_index": 1,
            "character": "乙",
            "final_start_sec": 0.4,
            "final_end_sec": 1.0,
            "start_sec": 0.4,
            "end_sec": 1.0,
        },
    ]
    evidence_path.write_text(json.dumps({
        "status": "complete",
        "request": {"item_id": "song", "audio_variant": "demucs", "core_sec": 30.0},
        "ground_truth": [
            {"character_index": 0, "start_sec": 0.0, "end_sec": 0.4},
            {"character_index": 1, "start_sec": 0.4, "end_sec": 0.8},
        ],
        "characters": rows,
        "natural_candidates": [{
            "case_id": "case",
            "candidate_type": "structural",
            "character_indices": [0, 1],
            "trigger_counts": {"boundary_stacking": 1},
        }],
    }), encoding="utf-8")
    q2_path = evidence_root / "q2_natural_realign" / "cases" / "case.json"
    q2_path.parent.mkdir(parents=True)
    q2_path.write_text(json.dumps({
        "item_id": "song", "audio_variant": "demucs", "core_sec": 30.0,
        "final_non_gt_selection": {"selected": False},
        "repair_candidates": [],
    }), encoding="utf-8")
    output = evidence_root / "metrics.json"
    subprocess.run([
        sys.executable, str(ROOT / "scripts" / "demo" / "analyze_raw_detector_repair.py"),
        "--baseline-root", str(evidence_root), "--q2-root", str(evidence_root),
        "--output", str(output), "--tolerances-sec", "0.16",
    ], check=True, env={**__import__('os').environ, "PYTHONPATH": str(ROOT / "src")})
    report = json.loads(output.read_text(encoding="utf-8"))["by_tolerance"]["0.16"]
    assert report["population"]["true_error_unit_count"] == 1
    assert report["correct_units_false_detected_but_unmodified_count"] == 1
    assert "trigger:boundary_stacking" in report["detector_by_trigger"]
