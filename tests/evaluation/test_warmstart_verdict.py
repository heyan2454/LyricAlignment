from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "warmstart_ab_verdict", ROOT / "scripts" / "evaluation" / "warmstart_ab_verdict.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def _view(path: Path, checkpoint: str, scores: dict[str, float], mae: float = 60.0) -> None:
    path.write_text(json.dumps({"checkpoints": {checkpoint: {
        "variants": {"fixed": {"per_song": {song: {"within_200ms": value} for song, value in scores.items()},
                                                 "mae_all_ms": mae}}}}}), encoding="utf-8")


def test_song_scores_reads_the_primary_decoder(tmp_path: Path):
    first = tmp_path / "a.json"
    _view(first, "old-r2-750", {"s1": 0.96, "s2": 0.97})
    scores = MODULE.song_scores([json.loads(first.read_text(encoding="utf-8"))])
    assert scores == {"old-r2-750": {"s1": 0.96, "s2": 0.97}}


def test_paired_by_song_reports_sign_and_rejects_thin_samples():
    left = {f"s{i}": 0.90 for i in range(6)}
    right = {f"s{i}": 0.92 for i in range(6)}
    block = MODULE.paired_by_song(left, right)
    assert block["status"] == "measured" and block["songs"] == 6
    assert block["mean_delta_pp"] == 2.0 and block["better"] == 6
    assert block["z"] is None                      # 零方差不给 z
    thin = MODULE.paired_by_song({"s1": 0.9, "s2": 0.9}, {"s1": 0.95, "s2": 0.95})
    assert thin["status"] == "insufficient_data"


def test_missing_song_intersection_is_reported_not_invented(tmp_path: Path):
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    _view(a, "control", {f"s{i}": 0.95 for i in range(8)})
    _view(b, "treatment", {f"other{i}": 0.96 for i in range(8)})
    scores = MODULE.song_scores([json.loads(a.read_text(encoding="utf-8")),
                                 json.loads(b.read_text(encoding="utf-8"))])
    block = MODULE.paired_by_song(scores["control"], scores["treatment"])
    assert block["status"] == "insufficient_data" and block["songs"] == 0


def test_duration_ratio_reports_not_run_when_the_arm_was_never_measured():
    assert MODULE.duration_ratio([], "warmstart-oversample") == {"status": "not_run"}
    block = {"label": "warmstart-oversample",
             "buckets": {"2-+s": {"miss_median_duration_ratio": 0.82, "miss_share": 0.09, "characters": 240}}}
    assert MODULE.duration_ratio([block], "warmstart-oversample")["miss_median_duration_ratio"] == 0.82


def test_missing_view_file_is_recorded_as_not_run_instead_of_crashing(tmp_path: Path, capsys):
    """08:29 的真实缺陷：一个输入文件不存在就让整个判决崩溃（错误还被调用方的 sed 吞掉）。"""
    import subprocess
    real = tmp_path / "present.json"
    _view(real, "old-r2-750", {f"s{i}": 0.95 for i in range(6)})
    out = tmp_path / "verdict"
    script = ROOT / "scripts" / "evaluation" / "warmstart_ab_verdict.py"
    completed = subprocess.run(
        ["python", str(script), "--view", str(real), "--view", str(tmp_path / "absent.json"),
         "--control", "warmstart-control", "--treatment", "warmstart-oversample",
         "--baseline", "old-r2-750", "--out", str(out)],
        capture_output=True, text=True, env={"PYTHONPATH": str(ROOT / "src"), "PATH": __import__("os").environ["PATH"]})
    assert completed.returncode == 0, completed.stderr[-500:]
    payload = json.loads((out / "metrics.json").read_text(encoding="utf-8"))
    assert payload["missing_view_files"][0]["status"] == "not_run"
    assert "absent.json" in payload["missing_view_files"][0]["requested"]
    assert "warmstart-control" in payload["missing"]
    report = (out / "REPORT.md").read_text(encoding="utf-8")
    assert "未测到" in report                     # 缺数据必须显式出现在报告里
