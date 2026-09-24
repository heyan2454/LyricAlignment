#!/usr/bin/env python3
"""把塌陷块单独切出来重新喂模型：检验"标不出"是序列竞争还是声学不可辨。

动机：`20260924_opencpop_collapse.md` 里 5 个塌陷块（连续 ≥5 字共用同一结束点）全部是重复衬词
（啦/呜/嘟），窗内前向的 end mass-in-tolerance ≈ 0，看起来"候选里根本没有答案"。但那是**在 91 字的
长窗上下文里**算出来的候选分布——把同样的字单独切出来，候选可能完全不同。

三种条件（同一块，逐字 GT 平移到切片坐标）：
  A `block`   精确块边界（只有这些重复字，无上下文）
  B `ctx2`    块 ± 2 s（把落在该区间内的其他真值字一并放进歌词，避免"音频有声音但 prompt 没有"）
  C `half`    块的前一半（长度效应：竞争者变少时能否分辨）

产物是既有 runner 能直接吃的 evidence jsonl.gz（不新建 runner），外加一份 manifest 说明每段里
哪些单元是原块成员——**判决只算原块成员**，上下文单元只用于让 prompt 与音频一致。

    PYTHONPATH=src python scripts/evaluation/prepare_collapse_isolation.py \
        --dump /home/hyan/Data/lyricalign/runs/20260924_opencpop_eval/units_window_old750.jsonl.gz \
        --out-dir /home/hyan/Data/lyricalign/runs/20260924_opencpop_eval/isolation
"""

from __future__ import annotations

import argparse
import gzip
import json
import subprocess
from collections import defaultdict
from pathlib import Path

TOL = 0.2
MIN_BLOCK = 5
CONDITIONS = ("block", "ctx2", "half")


def load_units(path: Path) -> dict[str, list[dict]]:
    by_item: dict[str, list[dict]] = defaultdict(list)
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                row = json.loads(line)
                by_item[row["utt"]].append(row)
    for rows in by_item.values():
        rows.sort(key=lambda r: r["unit_index"])
    return dict(by_item)


def collapse_blocks(rows: list[dict]) -> list[list[dict]]:
    blocks: list[list[dict]] = []
    run: list[dict] = []
    for row in rows:
        if run and row.get("official_end_sec") != run[-1].get("official_end_sec"):
            if len(run) >= MIN_BLOCK:
                blocks.append(run)
            run = []
        run.append(row)
    if len(run) >= MIN_BLOCK:
        blocks.append(run)
    return blocks


def clip(source: Path, start: float, end: float, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        return
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(source), "-ss", f"{start:.3f}",
                    "-t", f"{end - start:.3f}", "-ac", "1", "-ar", "16000", str(target)], check=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dump", type=Path, required=True, help="ood_dp_replay --dump-units 的产物")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--max-blocks", type=int, default=4, help="默认取报告里的 1–4 块（第 5 块是近无声段）")
    parser.add_argument("--context-sec", type=float, default=2.0)
    args = parser.parse_args()

    by_item = load_units(args.dump)
    clips = args.out_dir / "clips"
    rows_out: list[dict] = []
    manifest: list[dict] = []
    picked = 0
    for utt, rows in sorted(by_item.items()):
        source = Path(utt)
        if not source.is_file():
            continue
        for block_index, block in enumerate(collapse_blocks(rows), start=1):
            if picked >= args.max_blocks:
                break
            picked += 1
            duration = None
            for cond in CONDITIONS:
                if cond == "block":
                    members = list(block)
                elif cond == "half":
                    members = block[: max(MIN_BLOCK, len(block) // 2)]
                else:  # ctx2：块 ± context，并纳入区间内的其他真值字
                    lo = block[0]["gt_start_sec"] - args.context_sec
                    hi = block[-1]["gt_end_sec"] + args.context_sec
                    members = [r for r in rows if r["gt_start_sec"] >= lo and r["gt_end_sec"] <= hi]
                    members.sort(key=lambda r: r["gt_start_sec"])
                if len(members) < 3:
                    continue
                lo = members[0]["gt_start_sec"]
                hi = max(r["gt_end_sec"] for r in members)
                if duration is None:
                    import wave
                    with wave.open(str(source), "rb") as handle:
                        duration = handle.getnframes() / float(handle.getframerate())
                hi = min(hi, duration - 0.001)
                segment = f"{source.stem}__b{block_index}__{cond}"
                target = clips / f"{segment}.wav"
                clip(source, lo, hi, target)
                block_keys = {(r["unit_index"]) for r in block if cond != "ctx2" or
                              (block[0]["unit_index"] <= r["unit_index"] <= block[-1]["unit_index"])}
                manifest.append({"segment": segment, "source": str(source), "condition": cond,
                                 "block": block_index, "clip_start_sec": round(lo, 3),
                                 "clip_end_sec": round(hi, 3), "units": len(members),
                                 "block_members": len(block_keys),
                                 # 原块在**本切片坐标**里的区间：ctx2 档靠它把块成员从上下文里筛出来
                                 "block_rel_start_sec": round(block[0]["gt_start_sec"] - lo, 4),
                                 "block_rel_end_sec": round(block[-1]["gt_end_sec"] - lo, 4),
                                 "lyrics": "".join(r["text"] for r in members)})
                for offset, row in enumerate(members):
                    is_block = row["unit_index"] in block_keys
                    rows_out.append({"model": "r2", "dataset": "opencpop-isolation", "utt": segment,
                                     "source_utt": str(source), "condition": cond, "block": block_index,
                                     "is_block_member": bool(is_block), "unit_index": offset,
                                     "audio_path": str(target), "text": row["text"],
                                     "gt_start_sec": round(row["gt_start_sec"] - lo, 4),
                                     "gt_end_sec": round(row["gt_end_sec"] - lo, 4),
                                     "gt_dur_sec": round(row["gt_end_sec"] - row["gt_start_sec"], 4)})
            if picked >= args.max_blocks:
                break
        if picked >= args.max_blocks:
            break

    args.out_dir.mkdir(parents=True, exist_ok=True)
    evidence = args.out_dir / "evidence_isolation.jsonl.gz"
    with gzip.open(evidence, "wt", encoding="utf-8") as handle:
        for row in rows_out:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    (args.out_dir / "MANIFEST.json").write_text(json.dumps(
        {"blocks_picked": picked, "conditions": list(CONDITIONS), "segments": manifest},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"blocks_picked": picked, "segments": len(manifest), "evidence": str(evidence)},
                     ensure_ascii=False))
    for item in manifest:
        print(f"  {item['segment']:46s} cond={item['condition']:5s} units={item['units']:2d} "
              f"块成员={item['block_members']:2d} 时长={item['clip_end_sec'] - item['clip_start_sec']:.2f}s "
              f"歌词={item['lyrics'][:24]}")


if __name__ == "__main__":
    main()
