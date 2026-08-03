#!/usr/bin/env python3
"""阶段 B：build_behavior_manifest —— 生成合法 baseline + 百分比 mutation 的行为 manifest。

输入：M4_LABELS（qwen_fa_labels.jsonl，含 lyrics_normalized/item_id/song_id/duration）。
输出：manifest.jsonl，每行一个 behavior request 描述（含 text_units、mutation_type、
ratio、source、donor、timestamp_slot_indices），供 run_alignment_behavior 消费。

百分比按 00 §7：过量 +10/25/50/100/200%，缺失 10/25/50/75/90%，替换 10/25/50/75/100%，
跨歌 strict no-match（donor song != target，同语言等长，固定 seed）。纯文本，无模型。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from lyricalign.research_v7.mutations import (
    DonorSpec,
    extra_ratio,
    missing_ratio,
    no_match,
    replace_ratio,
)

EXTRA_RATIOS = [0.1, 0.25, 0.5, 1.0, 2.0]
MISSING_RATIOS = [0.1, 0.25, 0.5, 0.75, 0.9]
REPLACE_RATIOS = [0.1, 0.25, 0.5, 0.75, 1.0]
POSITIONS = ["tail", "head", "middle", "dispersed", "whole"]


def units_of(lyrics: str) -> list[str]:
    """按字符切分（中文逐字、连续拉丁词内聚）。"""
    out = []
    buf = ""
    for ch in lyrics:
        if ch == " ":
            if buf:
                out.append(buf)
                buf = ""
        elif ch.isascii() and ch.isalpha():
            buf += ch
        else:
            if buf:
                out.append(buf)
                buf = ""
            out.append(ch)
    if buf:
        out.append(buf)
    return out


def make_donor_list(labels: list[dict], this_song: str, seed: int = 0) -> list[DonorSpec]:
    """构造跨歌 donor 池（donor_song != target，方便 no-match/replace 用）。"""
    import random

    rng = random.Random(seed)
    pool = [x for x in labels if x.get("song_id") != this_song]
    donors = []
    for x in rng.sample(pool, min(20, len(pool))):
        u = units_of(x.get("lyrics_normalized", ""))
        if not u:
            continue
        donors.append(DonorSpec(
            donor_song_id=x.get("song_id", "?"),
            donor_start_index=0,
            donor_units=tuple(u),
            language="zh",
            unit_mode="char",
        ))
    return donors


def build(cfg: dict, labels: list[dict], limit: int) -> list[dict]:
    import random

    rng = random.Random(cfg.get("seed", 0))
    items = labels if not limit else rng.sample(labels, min(limit, len(labels)))
    rows: list[dict] = []
    for it in items:
        item_id = it.get("item_id")
        song = it.get("song_id", "?")
        base = units_of(it.get("lyrics_normalized", ""))
        if not base:
            continue
        donors = make_donor_list(labels, song, seed=cfg.get("seed", 0))
        dur = float(it.get("duration_sec", 0.0) or 0.0)
        # baseline
        rows.append({
            "item_id": item_id, "song_id": song, "duration_sec": dur,
            "mutation_type": "baseline", "text_units": base,
        })
        # extra
        for r in EXTRA_RATIOS:
            for pos in ("tail",):
                m = extra_ratio(base, r, source="future", position=pos)
                rows.append({"item_id": item_id, "song_id": song, "duration_sec": dur,
                             "mutation_type": "extra", "ratio": r, "position": pos,
                             "text_units": m.mutated_units, "source": "future"})
        # missing
        for r in MISSING_RATIOS:
            for pos in ("tail", "head", "dispersed"):
                m = missing_ratio(base, r, position=pos, seed=cfg.get("seed", 0))
                rows.append({"item_id": item_id, "song_id": song, "duration_sec": dur,
                             "mutation_type": "missing", "ratio": r, "position": pos,
                             "text_units": m.mutated_units})
        # replace (whole, tail)
        for r in REPLACE_RATIOS:
            if not donors:
                break
            d = donors[0]
            m = replace_ratio(base, r, donor=d, position="whole", seed=cfg.get("seed", 0))
            rows.append({"item_id": item_id, "song_id": song, "duration_sec": dur,
                         "mutation_type": "replace", "ratio": r, "position": "whole",
                         "text_units": m.mutated_units, "donor": d.donor_song_id})
        # no_match
        if donors:
            d = donors[1] if len(donors) > 1 else donors[0]
            m = no_match(base, donor=d, language="zh", unit_mode="char")
            rows.append({"item_id": item_id, "song_id": song, "duration_sec": dur,
                         "mutation_type": "no_match", "text_units": m.mutated_units,
                         "donor": d.donor_song_id})
    return rows


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--labels", required=True, help="m4singer_qwen_fa_labels.jsonl")
    p.add_argument("--out", required=True)
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--seed", type=int, default=0)
    args = p.parse_args(argv)

    labels = [json.loads(l) for l in Path(args.labels).read_text().splitlines() if l.strip()]
    cfg = {"seed": args.seed}
    rows = build(cfg, labels, args.limit)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    from collections import Counter

    c = Counter(r["mutation_type"] for r in rows)
    print(json.dumps({"ok": True, "n_items": len({r['item_id'] for r in rows}),
                      "n_rows": len(rows), "by_type": dict(c), "out": args.out}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
