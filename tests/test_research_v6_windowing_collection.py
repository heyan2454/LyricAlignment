from __future__ import annotations
import json
from pathlib import Path
import subprocess
import sys
import tarfile

from lyricalign.research_v6.windowing import SilenceInterval, cap_silence_mapping, map_time, split_text_chunks, build_dynamic_window_plan


def test_silence_cap_preserves_order_and_caps_duration():
    mapping = cap_silence_mapping(duration_sec=20.0, silences=[SilenceInterval(5,15)], cap_sec=4.0)
    assert abs(mapping[-1].transformed_end_sec - 14.0) < 1e-9
    assert abs(map_time(15.0, mapping, direction="original_to_transformed") - 9.0) < 1e-9
    assert abs(map_time(9.0, mapping, direction="transformed_to_original") - 15.0) < 1e-9


def test_chunks_and_dynamic_plan_are_continuous():
    chunks = split_text_chunks(0, 96, chunk_units=40, overlap_units=8, commit_units=32)
    assert chunks[0] == {"text_start":0,"text_end":40,"commit_start":0,"commit_end":32}
    assert chunks[-1]["commit_end"] == 96
    plan = build_dynamic_window_plan(duration_sec=135, target_core_sec=60, left_context_sec=10, right_context_sec=10,
        safe_boundaries=[{"time_sec":58.0,"global_character_index":100,"safe_boundary_score":.9}, {"time_sec":119.0,"global_character_index":210,"safe_boundary_score":.8}])
    windows=plan["windows"]
    assert plan["active_span_duration_sec"] == 135
    assert all(abs(windows[i]["core_end_sec"]-windows[i+1]["core_start_sec"])<1e-9 for i in range(len(windows)-1))


def test_light_collector_stays_under_3m(tmp_path: Path):
    root=tmp_path/"run"; root.mkdir()
    for i in range(40):
        p=root/f"items/i{i}/item_summary.json"; p.parent.mkdir(parents=True); p.write_text(json.dumps({"i":i,"x":"a"*1000}))
    output=tmp_path/"light.tar.gz"
    subprocess.run([sys.executable,"scripts/research/collect_research_evidence.py","--run-root",str(root),"--output",str(output),"--profile","light3m"],check=True)
    assert output.stat().st_size <= 3*1024*1024
    with tarfile.open(output,"r:gz") as tf:
        assert "EVIDENCE_MANIFEST.json" in tf.getnames()
