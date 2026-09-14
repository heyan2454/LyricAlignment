from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "arms_by_bucket_counts", ROOT / "scripts" / "evaluation" / "arms_by_bucket_counts.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def _dump(tmp_path: Path, name: str, errors: dict[int, float], durations: dict[int, float]) -> Path:
    lines = []
    for index in sorted(errors):
        base = {"item_id": f"S#x#{index % 3}", "index": index, "channel": "d_rms",
                "duration": durations[index], "abs_err_argmax": errors[index],
                "entropy_nats": 0.4, "p_top1": 0.9, "pred_sec": 1.0}
        lines.append(json.dumps(dict(base, kind="onset")))
        lines.append(json.dumps(dict(base, kind="offset", pred_sec=3.0)))
    path = tmp_path / name
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_counts_are_counts_not_rates_and_buckets_match_duration(tmp_path: Path):
    durations = {index: (0.3 if index < 5 else 2.5) for index in range(10)}
    errors_a = {index: (0.5 if index in (1, 6) else 0.01) for index in range(10)}
    errors_b = {index: (0.5 if index == 6 else (0.01 if index == 1 else 0.3)) for index in range(10)}
    a = _dump(tmp_path, "a.jsonl", errors_a, durations)
    b = _dump(tmp_path, "b.jsonl", errors_b, durations)
    arms = {"A": MODULE.offsets(a), "B": MODULE.offsets(b)}
    table = MODULE.tabulate(arms, reference="A", challenger="B")
    assert table["shared_characters"] == 10
    short = table["buckets"]["0-0.5s"]
    assert short["A"]["n"] == 5 and short["A"]["offset_miss"] == 1
    # index 1: A 缺陷 0.5>0.2, B 0.01 ⇒ 新修好；index 6 属 2s+ 桶，两边都缺陷 ⇒ 不算不一致
    # 短桶：A 只在 index1 缺陷、B 在 index1 修好，但 B 在 index 0/2/3/4 新弄坏 4 个
    assert short["discordant_challenger_vs_reference"]["newly_ok"] == 1
    assert short["discordant_challenger_vs_reference"]["newly_broken"] == 4
    assert short["B"]["offset_miss"] == 4
    assert table["buckets"]["2s+"]["discordant_challenger_vs_reference"]["newly_broken"] == 4  # index 7..10: 0.3>0.2
    assert table["totals"]["arms"]["A"] == 2


def test_only_the_offset_side_is_counted_never_onset_plus_offset(tmp_path: Path):
    durations = {index: 0.3 for index in range(4)}
    errors = {index: 0.01 for index in range(4)}
    a = _dump(tmp_path, "a.jsonl", errors, durations)
    parsed = MODULE.offsets(a)
    assert len(parsed) == 4
    assert all(value[1] == 0.01 for value in parsed.values())     # 只暴露 (时长, 结束点误差)


def test_missing_dump_is_refused_instead_of_silently_dropping_an_arm(tmp_path: Path):
    import subprocess
    import sys
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts/evaluation/arms_by_bucket_counts.py"),
         "--dump", f"A={tmp_path}/absent.jsonl", "--out", str(tmp_path / "out.json")],
        capture_output=True, text=True)
    assert completed.returncode != 0
    assert "拒绝用部分数据" in completed.stderr
