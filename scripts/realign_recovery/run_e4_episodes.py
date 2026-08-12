#!/usr/bin/env python3
"""E4 upstream single-point propagation episodes（WP C2，纯 CPU manifest 构建）。

输入：
- --baseline        E3 产物 baseline.jsonl（含 window.text_unit_ids / detector_shadow /
                    request_identity）
- --evidence-v2-dir（可选）用于 P1 real-model-error 的 unsafe 时间区间 -> unit 映射
- --items-dirs      （可选）与 --evidence-v2-dir 配套的 items 目录

输出（每 target 一个目录）：
- episodes.jsonl              自然 + P1..P5 propagated episodes
- E4_EPISODE_SUMMARY.json     attempted / no_effect / effective 统计与
                              bounded_insufficient 标注（64 effective/family 未达标时）

语义（对齐 03 文档 P1--P5 与 09 契约）：
- 只对每首歌的最小 window_index（首窗）注入一次；后续窗 natural 不注入。
- P1  real model error forced commit：detector_shadow.unsafe_intervals 覆盖的单元
      （真实模型错误位置）作为绕过 detector 的 forced commit 目标；
- P2  lyric cursor ahead/behind（small/medium/large）：取后续窗文本单元的前/中/全部；
- P3  audio/time cursor ±1/±3/±6/±12s：按时间偏移取后续窗单元子集；
- P4  repeated occurrence jump：同歌最远窗口单元（模拟重复段 wrong occurrence）；
- P5  silence/boundary mistake：下一窗口开头单元（错误吸附/提前 boundary）。
- effective = 目标单元未被首窗覆盖（产生 propagated episode）；否则 no_effect。
- 每 family 目标 64 effective；不足标注 bounded_insufficient。

shadow-only：不读取 GT。--dry-run 只打印构造结果不写盘。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from lyricalign.realign_recovery.runners import episode_builder  # noqa: E402


def _load_jsonl(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        if isinstance(obj, list):
            rows.extend(obj)
        else:
            rows.append(obj)
    return rows


def _units_in_intervals(rows: list[dict], intervals: list) -> list[int]:
    """canonical_unit_id 的时间区间与 unsafe 时间区间相交 -> unit id。"""
    hits: set[int] = set()
    for row in rows:
        raw = row.get("raw") or {}
        start = raw.get("start_sec")
        end = raw.get("end_sec")
        if start is None or end is None:
            continue
        cid = row.get("canonical_unit_id")
        if cid is None:
            continue
        for a, b in intervals:
            if end > a and start < b:
                hits.add(int(cid))
                break
    return sorted(hits)


def _build_stages(song_id: str, per_song: dict, evidence: dict) -> list[dict]:
    """为歌曲首窗构造 P1..P5 stages（target units 均取自首窗之外）。"""
    windows = sorted(per_song[song_id], key=lambda r: int(r["window_index"]))
    first = windows[0]
    first_units = set(first["window"]["text_unit_ids"])
    later = windows[1:]
    if not later:
        return []
    later_units: list[int] = []
    for row in later:
        later_units.extend(row["window"]["text_unit_ids"])
    later_units = sorted(set(later_units))
    next_units = later[0]["window"]["text_unit_ids"]
    far_units = later[-1]["window"]["text_unit_ids"]

    def scoped(stage_id: str, units: list[int]) -> dict:
        return {"id": stage_id, "units": units, "song_id": song_id}

    stages: list[dict] = []
    # P1 real model error forced commit：首窗 unsafe 区间映射的真实错误单元。
    # 若映射为空，退化用首窗边界外的首 3 个后续单元。
    p1 = _units_in_intervals(
        evidence.get(first["request_identity"], []),
        first.get("detector_shadow", {}).get("unsafe_intervals", []),
    )
    if not p1:
        p1 = next_units[:3]
    stages.append(scoped("P1", p1))
    # P2 lyric cursor ahead/behind：small=后续前1/4、medium=前1/2、large=全部。
    n = len(later_units)
    if n:
        stages.append(scoped("P2-small", later_units[: max(1, n // 4)]))
        stages.append(scoped("P2-medium", later_units[: max(1, n // 2)]))
        stages.append(scoped("P2-large", later_units))
    # P3 audio/time cursor ±偏移：按时间取后续窗的前/中/后子集。
    if n:
        stages.append(scoped("P3-early", next_units[: max(1, len(next_units) // 4)]))
        stages.append(scoped("P3-mid", next_units))
        stages.append(scoped("P3-late", far_units))
    # P4 repeated occurrence jump：同歌最远窗单元。
    if far_units:
        stages.append(scoped("P4", far_units))
    # P5 silence/boundary mistake：下一窗口开头单元。
    if next_units:
        stages.append(scoped("P5", next_units[: max(1, len(next_units) // 5)]))
    return stages


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--baseline", required=True)
    p.add_argument("--evidence-v2-dir", default=None)
    p.add_argument("--items-dirs", default=None, nargs="+")
    p.add_argument("--out-root", required=True)
    p.add_argument("--target", default="raw", choices=("raw", "official"))
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)

    baseline = _load_jsonl(Path(args.baseline))
    if not baseline:
        raise SystemExit("baseline.jsonl 为空")
    per_song: dict[str, list[dict]] = {}
    for row in baseline:
        per_song.setdefault(row["song_id"], []).append(row)

    evidence: dict[str, list[dict]] = {}
    if args.evidence_v2_dir and os.path.isdir(args.evidence_v2_dir):
        for f in Path(args.evidence_v2_dir).glob("*.jsonl"):
            evidence[f.stem] = _load_jsonl(f)

    stages_by_song: dict[str, list[dict]] = {}
    for song in sorted(per_song):
        stages_by_song[song] = _build_stages(song, per_song, evidence)

    if args.dry_run:
        for song in sorted(stages_by_song):
            print(song, "->", [(s["id"], len(s["units"])) for s in stages_by_song[song]])
        return 0

    out_root = Path(args.out_root) / args.target
    out_root.mkdir(parents=True, exist_ok=True)
    propagated, summary = episode_builder(
        args.baseline, out_root,
        propagation_stages=[s for v in stages_by_song.values() for s in v],
    )
    eff = summary.get("effective", 0)
    eff_by_family = {"P1": 0, "P2": 0, "P3": 0, "P4": 0, "P5": 0}
    for line in open(propagated, encoding="utf-8").read().splitlines():
        row = json.loads(line)
        if row.get("kind") == "propagated":
            fam = row.get("family", "")
            for k in eff_by_family:
                if fam == k or fam.startswith(k):
                    eff_by_family[k] += 1
    bounded = {k: "ok" if v >= 64 else "bounded_insufficient"
               for k, v in eff_by_family.items()}
    summary["effective_by_family"] = eff_by_family
    summary["bounded_status"] = bounded
    summary["target"] = args.target
    summary["songs"] = len(per_song)
    summary_path = out_root / "E4_EPISODE_SUMMARY.json"
    with open(summary_path, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=1)
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    print(f"episodes -> {propagated}")
    print(f"summary  -> {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
