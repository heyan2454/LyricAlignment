#!/usr/bin/env python3
"""Is part of the measured "long notes end early" bias an artefact of how the labels are built?

M4Singer ships exactly one timeline: a phone-level alignment.  Our character labels are cumulative sums of
`ph_dur` grouped by a character→phone mapping, and the TextGrid "character tier" is the same thing
(measured: 100% of its boundaries sit on phone boundaries; note boundaries are also phone boundaries).  So
no internal cross-check of boundary placement exists inside this corpus.

One comparison is still meaningful: for a character whose sung note continues after the labelled end, the
score says the note has not finished yet, while the label already cut it.  If that gap explains a large part
of the "early cut" error we measure against the labels, then the long-note conclusion is partly about the
annotation, not about the model — which is exactly what needs to be known before spending more training budget.

    PYTHONPATH=src python scripts/evaluation/check_note_span_vs_label_end.py --limit 3000 \
        --out results/by_run/20260915_note_span/metrics.json
"""

from __future__ import annotations

import argparse
import json
import statistics as st
from pathlib import Path
from typing import Any

META = Path("/home/hyan/Data/datasets/m4singer/raw/extracted/m4singer/meta.json")
LONG_SEC = 1.5


def character_groups(phonemes: list[str]) -> list[list[int]]:
    """Group phone indices into characters: a new character starts at a vowel-ish or syllable head.

    A full implementation already exists in the dataset module; here we only need per-character spans for
    the held-vowel test, and the repo's mapping is used when importable (see main()).
    """
    raise RuntimeError("callers must pass the repo mapping")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=3000)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    import importlib
    m4 = importlib.import_module("lyricalign.datasets.m4singer")

    rows = json.loads(META.read_text(encoding="utf-8"))
    stats: dict[str, list[float]] = {"all": [], "short": [], "long": []}
    label_ahead: dict[str, int] = {"all": 0, "short": 0, "long": 0}
    items_used = 0
    items_skipped = 0

    for item in rows[: args.limit]:
        ph_dur = [float(value) for value in (item.get("ph_dur") or [])]
        notes = [int(value) for value in (item.get("notes") or [])]
        is_slur = list(item.get("is_slur") or [])
        phonemes = [str(value) for value in (item.get("phs") or [])]
        text = m4.normalize_lyrics(str(item.get("txt", "")))
        if min(len(ph_dur), len(notes), len(phonemes)) < 4 or len(set(map(len, (ph_dur, notes, phonemes)))) != 1:
            items_skipped += 1
            continue
        mapping, status, _special = m4.character_phoneme_mapping(text.text, phonemes, is_slur=is_slur)
        if not status.startswith("accepted"):
            items_skipped += 1
            continue
        # 累计时间轴
        cursor = 0.0
        ends: list[float] = []
        for value in ph_dur:
            cursor += value
            ends.append(cursor)
        # 每个音素所属"音符段"的结束时间：连续同音高（且非休止 0）视为同一音符
        note_end: list[float | None] = [None] * len(phonemes)
        index = 0
        while index < len(phonemes):
            pitch = notes[index]
            tail = index
            while tail + 1 < len(phonemes) and notes[tail + 1] == pitch and pitch != 0:
                tail += 1
            value = ends[tail] if pitch != 0 else None
            for position in range(index, tail + 1):
                note_end[position] = value
            index = tail + 1
        for positions in mapping:
            if not positions:                       # 某些字没有可靠映射（None），跳过不猜
                continue
            phone_indices = [int(value) for value in positions]
            if not phone_indices:
                continue
            label_start = ends[min(phone_indices) - 1] if min(phone_indices) > 0 else 0.0
            label_end = ends[max(phone_indices)]
            candidates = [note_end[position] for position in phone_indices if note_end[position] is not None]
            if not candidates:
                continue
            span_end = max(candidates)
            duration = max(0.0, label_end - label_start)
            gap = span_end - label_end        # >0 ⇒ 音还没结束，标注已把这个字判结束
            bucket = "long" if duration >= LONG_SEC else ("short" if duration >= 0.5 else None)
            for name in ("all", bucket):
                if name:
                    stats[name].append(gap)
                    if gap > 0.05:
                        label_ahead[name] += 1
        items_used += 1

    def summarise(values: list[float]) -> dict[str, Any]:
        if not values:
            return {"n": 0}
        values_sorted = sorted(values)
        return {"n": len(values), "median_ms": round(1000 * st.median(values), 1),
                "p90_ms": round(1000 * values_sorted[int(0.90 * (len(values_sorted) - 1))], 1),
                "share_gap_gt_50ms": round(sum(1 for value in values if value > 0.05) / len(values), 4)}

    payload = {"schema_version": "note_span_vs_label_end_v1", "items_used": items_used,
               "items_skipped": items_skipped, "long_sec": LONG_SEC,
               "gap_note_end_minus_label_end": {name: summarise(values) for name, values in stats.items()},
               "reading": "gap>0 表示该字所属音符在标注判定的结束时刻之后仍未结束（标注提前收）。"
                          "若长字这一列的中位数/gap>50ms 比例明显高于短字，说明'提前收'里有标注构造的贡献。"}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
