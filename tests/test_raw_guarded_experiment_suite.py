from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import wave
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def load_script(name: str, relative: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_raw_batch_defaults_to_demucs_and_supports_basename(tmp_path: Path) -> None:
    (tmp_path / "Song.txt").write_text("你好\n", encoding="utf-8")
    (tmp_path / "Song.wav").write_bytes(b"not decoded during discovery")
    module = load_script("raw_guarded_batch_suite_test", "scripts/demo/run_raw_guarded_karaoke_batch.py")
    args = module.build_parser().parse_args([str(tmp_path / "Song")])
    assert args.separator == "demucs"
    assert args.lyrics_override is None
    jobs = module.discover_jobs(tmp_path / "Song")
    assert len(jobs) == 1
    assert jobs[0].stem == "Song"



def test_explicit_lyrics_allows_different_media_basename(tmp_path: Path) -> None:
    media = tmp_path / "NightSoda.mp4"
    lyrics = tmp_path / "歌词.txt"
    media.write_bytes(b"not decoded during discovery")
    lyrics.write_text("夜苏打\n", encoding="utf-8")
    module = load_script("raw_guarded_batch_lyrics_override_test", "scripts/demo/run_raw_guarded_karaoke_batch.py")
    args = module.build_parser().parse_args([str(media), "--lyrics", str(lyrics)])
    jobs = module.discover_jobs_with_lyrics_override(args)
    assert len(jobs) == 1
    assert jobs[0].stem == "NightSoda"
    assert jobs[0].lyrics == lyrics.resolve()
    assert jobs[0].video == media.resolve()

def test_demucs_resolution_prefers_active_python_module(monkeypatch) -> None:
    module = load_script("qwen_batch_demucs_resolution_test", "scripts/demo/run_qwen_fa_batch.py")
    monkeypatch.setattr(module.shutil, "which", lambda command: None)
    monkeypatch.setattr(module.importlib.util, "find_spec", lambda name: object() if name == "demucs" else None)
    command = module._demucs_command(SimpleNamespace(demucs_command=None, demucs_env="demucs"))
    assert command == [sys.executable, "-m", "demucs"]


def test_forced_clean_control_really_bypasses_anomaly_gate() -> None:
    module = load_script("realign_quick_forced_control_test", "scripts/demo/run_demo_realign_quick.py")
    candidates = [
        {
            "mode": "local_raw_bounded_remerge",
            "anchor_mode": "runtime_A4",
            "crop_mode": "exact_anchor",
            "context_units": 0,
            "splice": {"valid": True},
            "acceptance": {"before_anomaly": {"score": 0}, "after_anomaly": {"score": 0}},
            "modification_summary": {"boundary_change_abs_sec": {"mean": 0.1}},
        }
    ]
    selection = module.forced_clean_control_selection(candidates)
    assert selection["selected"] is True
    assert selection["forced_write_back_control"] is True
    assert "bypasses" in selection["reason"]


def test_nonoverlap_replay_removes_duplicate_cases() -> None:
    module = load_script("raw_guarded_analysis_nonoverlap_test", "scripts/demo/analyze_raw_guarded_experiments.py")
    def case(case_id: str, start: int, end: int, severity: float):
        return {
            "case_id": case_id,
            "item_id": "song",
            "audio_variant": "demucs",
            "core_sec": 30.0,
            "source_candidate": {
                "dependency_character_start": start,
                "dependency_character_end": end,
                "severity_score": severity,
            },
        }
    candidate = {"target_indices": [0], "changed_rows": []}
    entries = [
        (case("a", 2, 4, 1.0), candidate),
        (case("b", 3, 5, 9.0), candidate),
        (case("c", 8, 8, 1.0), candidate),
    ]
    selected = module._nonoverlap_entries(entries)
    assert [row[0]["case_id"] for row in selected] == ["b", "c"]


def write_wav(path: Path, duration_sec: float = 0.1) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x00\x00" * int(16000 * duration_sec))


def test_materialize_long_subset_marks_clean_vocal_provenance(tmp_path: Path) -> None:
    audio_root = tmp_path / "derived"
    source_audio = audio_root / "audio" / "bucket_60" / "0000.wav"
    write_wav(source_audio)
    manifest = tmp_path / "manifest.jsonl"
    characters = tmp_path / "characters.jsonl"
    manifest.write_text(json.dumps({
        "item_id": "synthetic:a+b",
        "audio_relpath": "audio/bucket_60/0000.wav",
        "lyrics_normalized": "甲乙",
        "duration_sec": 0.1,
        "target_duration_sec": 60,
        "song_id": "song",
        "singer_id": "singer",
        "join_points_sec": [0.05],
        "seam_mask": [[0.05, 0.05]],
        "source_item_ids": ["a", "b"],
    }, ensure_ascii=False) + "\n", encoding="utf-8")
    characters.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in [
        {"item_id": "synthetic:a+b", "character_index": 0, "normalized_character": "甲", "start_sec": 0.0, "end_sec": 0.04},
        {"item_id": "synthetic:a+b", "character_index": 1, "normalized_character": "乙", "start_sec": 0.05, "end_sec": 0.09},
    ]), encoding="utf-8")
    out = tmp_path / "subset"
    subprocess.run([
        sys.executable,
        str(ROOT / "scripts/demo/materialize_synthetic_long_demo_subset.py"),
        "--manifest", str(manifest),
        "--characters", str(characters),
        "--audio-root", str(audio_root),
        "--out-dir", str(out),
    ], check=True, env={**os.environ, "PYTHONPATH": str(ROOT / "src")})
    provenance = json.loads((out / "items/m4long_0000/source_manifest.json").read_text(encoding="utf-8"))
    assert provenance["audio_origin"] == "m4singer_clean_vocal_not_demucs_output"
    assert (out / "items/m4long_0000/audio/demucs_htdemucs_ft_vocals.wav").exists()
