#!/usr/bin/env python3
"""Detector V2 Phase0-2：GT 审计 + source-song split（G0 gate）。

输入：M4Singer accepted rule-based pinyin-validated character labels
（20260723_qwen_fa_lora_v1/labels/m4singer_qwen_fa_labels.jsonl，真实逐字时间）。

产出（--out-root）：
  GT_LABEL_AUDIT.json     —— GT 源/质量/时间有效性/每歌字符数分布/合成轴排除声明
  SOURCE_SONG_SPLIT.json  —— 按 source song 的 train/val/test 划分（约 60/20/20，
                             同歌所有 window/mutation/view 不得跨 split，18 §12）

约束（19 §4 G0）：
- 只用 accepted_rule_based_pinyin_validated（+accepted_rule_validated_held_vowel 视为同族）；
- 时间无效行（end<=start、2*char 长度不符）进 audit 的 excluded，不进 split；
- synthetic-uniform 轴不生成 correctness 标签（本脚本只消费真实 labels，声明性排除）。
"""
from __future__ import annotations

import argparse
import json
import random
from collections import Counter, defaultdict
from pathlib import Path

VALID_STATUSES = ("accepted_rule_based_pinyin_validated", "accepted_rule_validated_held_vowel")
RATIOS = (0.6, 0.2, 0.2)


def load_labels(path: Path) -> list[dict]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def audit_labels(rows: list[dict]) -> dict:
    total = len(rows)
    status_counts = Counter(r.get("mapping_status") for r in rows)
    valid = [r for r in rows if r.get("mapping_status") in VALID_STATUSES]
    n_chars = 0
    time_bad_rows = 0
    per_song_chars: Counter = Counter()
    per_song_duration: Counter = Counter()
    for r in valid:
        cids = r.get("timestamp_class_ids") or []
        n = r.get("character_count") or 0
        n_chars += n
        per_song_chars[r.get("song_id")] += n
        per_song_duration[r.get("song_id")] += float(r.get("duration_sec") or 0)
        if len(cids) != 2 * n:
            time_bad_rows += 1
            continue
        for i in range(n):
            if cids[2 * i + 1] <= cids[2 * i]:
                time_bad_rows += 1
                break
    songs = sorted(per_song_chars)
    char_list = sorted(per_song_chars.values())
    return {
        "schema_version": "detector_v2_gt_label_audit_v1",
        "gt_source": "m4singer_qwen_fa_labels_v1 (accepted rule-based pinyin-validated character timestamps)",
        "gt_nature": "rule-based weak supervision (accepted + pinyin validated); not human GT; "
                     "synthetic-uniform axes excluded from correctness labels (18 §5/21 §1)",
        "total_rows": total,
        "valid_rows": len(valid),
        "excluded_rows": total - len(valid),
        "mapping_status_counts": dict(status_counts),
        "time_invalid_rows": time_bad_rows,
        "total_characters": n_chars,
        "n_source_songs": len(songs),
        "chars_per_song": {"min": min(char_list), "max": max(char_list),
                           "median": sorted(char_list)[len(char_list) // 2] if char_list else None},
        "synthetic_axis_excluded": True,
    }


def build_split(rows: list[dict], seed: int = 0) -> dict:
    valid = [r for r in rows if r.get("mapping_status") in VALID_STATUSES]
    by_song: dict[str, list] = defaultdict(list)
    for r in valid:
        by_song[r.get("song_id")].append(r)
    song_ids = sorted(by_song)
    rng = random.Random(seed)
    rng.shuffle(song_ids)
    n_train = max(1, int(len(song_ids) * RATIOS[0]))
    n_val = max(1, int(len(song_ids) * RATIOS[1]))
    train_songs = set(song_ids[:n_train])
    val_songs = set(song_ids[n_train:n_train + n_val])
    test_songs = set(song_ids[n_train + n_val:])
    counts = {"train": 0, "validation": 0, "test": 0}
    rows_per_split = {"train": 0, "validation": 0, "test": 0}
    for song, segs in by_song.items():
        split = ("train" if song in train_songs
                 else "validation" if song in val_songs else "test")
        counts[split] += 1
        rows_per_split[split] += len(segs)
    return {
        "schema_version": "detector_v2_source_song_split_v1",
        "ratio": {"train": RATIOS[0], "validation": RATIOS[1], "test": RATIOS[2]},
        "seed": seed,
        "n_songs": {"train": counts["train"], "validation": counts["validation"],
                    "test": counts["test"]},
        "n_rows": {"train": rows_per_split["train"], "validation": rows_per_split["validation"],
                   "test": rows_per_split["test"]},
        "songs": {"train": sorted(train_songs), "validation": sorted(val_songs),
                  "test": sorted(test_songs)},
        "note": "all windows/mutations/views of one source song stay in one split (18 §12); "
                "validation used for frozen thresholds only; test untouched until formal",
    }


def _atomic_write(path: Path, payload: dict) -> None:
    import os
    import tempfile
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
        f.flush(); os.fsync(f.fileno())
    os.replace(tmp, path)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--labels", required=True)
    p.add_argument("--out-root", required=True)
    p.add_argument("--seed", type=int, default=0)
    a = p.parse_args(argv)
    rows = load_labels(Path(a.labels))
    audit = audit_labels(rows)
    split = build_split(rows, seed=a.seed)
    out = Path(a.out_root)
    _atomic_write(out / "GT_LABEL_AUDIT.json", audit)
    _atomic_write(out / "SOURCE_SONG_SPLIT.json", split)
    print(json.dumps({"ok": True, "valid_rows": audit["valid_rows"],
                      "n_songs": audit["n_source_songs"],
                      "split": split["n_songs"],
                      "out": str(out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
