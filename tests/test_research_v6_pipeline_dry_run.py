from __future__ import annotations
from pathlib import Path
import subprocess
import sys


def test_pipeline_dry_run_builds_all_stages(tmp_path: Path):
    cmd=[sys.executable,"scripts/research/run_research_v6_pipeline.py","--mode","formal","--out-root",str(tmp_path/"out"),"--demo-root",str(tmp_path/"demo"),"--mir1k-subset-root",str(tmp_path/"mir"),"--m4-labels",str(tmp_path/"m4.jsonl"),"--m4-audio-root",str(tmp_path/"audio"),"--model","model","--revision","rev","--r2-checkpoint",str(tmp_path/"ckpt"),"--dry-run"]
    result=subprocess.run(cmd,check=True,text=True,capture_output=True)
    for stage in ("manifest","baseline","pilot","freeze","formal","visuals","collect_full","collect_light3m"):
        assert f'"stage": "{stage}"' in result.stdout
    # Complete formal is the default: zero means no case-level cap.
    assert '"--cases-per-item", "0"' in result.stdout
    assert '"--max-chunk-groups-per-item", "0"' in result.stdout
    assert '"--max-realign-cases-per-item", "0"' in result.stdout


def test_smoke_manifest_uses_bounded_smoke_defaults(tmp_path: Path):
    cmd=[sys.executable,"scripts/research/run_research_v6_pipeline.py","--mode","smoke","--out-root",str(tmp_path/"out"),"--demo-root",str(tmp_path/"demo"),"--mir1k-subset-root",str(tmp_path/"mir"),"--m4-labels",str(tmp_path/"m4.jsonl"),"--m4-audio-root",str(tmp_path/"audio"),"--model","model","--revision","rev","--r2-checkpoint",str(tmp_path/"ckpt"),"--dry-run"]
    result=subprocess.run(cmd,check=True,text=True,capture_output=True)
    manifest_line=next(line for line in result.stdout.splitlines() if '"stage": "manifest"' in line)
    assert '"--mode", "smoke"' in manifest_line
    assert '"--m4-native-cap", "0"' not in manifest_line
    assert '"--m4-long-cap", "0"' not in manifest_line
    assert '"--include-heldout"' not in manifest_line
