#!/usr/bin/env python3
"""Render human-reviewable B-tier diagnostic figures from auditable metadata."""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from matplotlib.font_manager import FontProperties

from lyricalign.datasets.m4singer import SPECIAL_PHONEMES, group_phonemes, normalize_lyrics


COLORS = {"<SP>": "#f4a261", "<AP>": "#e76f51", "<SIL>": "#9d4edd"}


def cumulative(values: list[object]) -> list[tuple[float, float]]:
    cursor, result = 0.0, []
    for value in values:
        end = cursor + float(value)
        result.append((cursor, end)); cursor = end
    return result


def draw_item(record: dict, raw: dict, output: Path, cjk_font: FontProperties | None) -> None:
    phonemes = [str(x) for x in raw["phs"]]
    ph_intervals = cumulative(raw["ph_dur"])
    note_intervals = cumulative(raw["notes_dur"])
    groups, special = group_phonemes(phonemes)
    normalized = normalize_lyrics(raw["txt"]).text
    fig, axes = plt.subplots(3, 1, figsize=(16, 10), constrained_layout=True)
    title = f"{record['primary_reason']} | {record['item_id']}\nChinese text is shown in the HTML caption; plot uses code points because this host has no CJK font."
    fig.suptitle(title, fontsize=11, fontweight="bold", fontproperties=cjk_font)
    # Do not invent a character-to-syllable alignment for B-tier.  This lane
    # makes the failed cardinality condition visible: C slots versus G groups.
    max_count = max(len(normalized), len(groups), 1)
    for index, char in enumerate(normalized):
        axes[0].add_patch(Rectangle((index, .55), .9, .32, color="#bde0fe"))
        axes[0].text(index + .45, .71, f"C{index}\n{char}\nU+{ord(char):04X}", ha="center", va="center", fontsize=7, fontproperties=cjk_font)
    for index, group in enumerate(groups):
        tokens = " ".join(phonemes[token] for token in group)
        axes[0].add_patch(Rectangle((index, .08), .9, .32, color="#ffd6a5"))
        axes[0].text(index + .45, .24, f"G{index}: {tokens}", ha="center", va="center", fontsize=7)
    axes[0].set(title=f"Cardinality diagnosis: characters C={len(normalized)}; candidate syllable groups G={len(groups)}; delta=G-C={len(groups)-len(normalized)}. No link is drawn when unequal.", xlim=(0, max_count), ylim=(0, 1), yticks=[], xticks=[])
    for index, ((start, end), token) in enumerate(zip(ph_intervals, phonemes, strict=True)):
        color = COLORS.get(token, "#457b9d")
        axes[1].add_patch(Rectangle((start, 0.25), end - start, .5, color=color, alpha=.82))
        axes[1].text((start + end) / 2, .5, token, ha="center", va="center", fontsize=7, rotation=45)
        if index < len(raw["is_slur"]) and raw["is_slur"][index]:
            axes[1].plot((start + end) / 2, .91, marker="*", color="#d62828", markersize=9)
    for number, group in enumerate(groups):
        start, end = ph_intervals[group[0]][0], ph_intervals[group[-1]][1]
        axes[1].plot([start, end], [1.05, 1.05], color="#1d3557", linewidth=2)
        axes[1].text((start + end) / 2, 1.12, f"syllable {number}", ha="center", fontsize=7)
    axes[1].set(title=f"Phoneme timeline from ph_dur (star = is_slur; total={ph_intervals[-1][1]:.3f}s)", ylim=(0, 1.28), yticks=[])
    for note_index, ((start, end), note) in enumerate(zip(note_intervals, raw["notes"], strict=True)):
        if note:
            axes[2].add_patch(Rectangle((start, float(note) - .35), end - start, .7, color="#2a9d8f", alpha=.82))
            axes[2].text((start + end) / 2, float(note), f"N{note_index}={note}", ha="center", va="center", fontsize=7)
        else:
            axes[2].add_patch(Rectangle((start, 0), end - start, 1, color="#adb5bd", alpha=.45))
    pitched = [int(note) for note in raw["notes"] if note]
    axes[2].set(title=f"Note events from notes_dur (independent time axis; total={note_intervals[-1][1]:.3f}s; labels are token index/MIDI)", xlabel="seconds", ylabel="MIDI", ylim=((min(pitched) - 2 if pitched else -1), (max(pitched) + 2 if pitched else 2)))
    for axis in axes:
        axis.grid(axis="x", alpha=.25)
    axes[1].set_xlim(0, ph_intervals[-1][1]); axes[2].set_xlim(0, note_intervals[-1][1])
    details = record["reason_details"]
    fig.text(.01, .01, f"RULE EVIDENCE: tags={', '.join(record['secondary_tags']) or 'none'} | slur={details['slur_marker_count']} | syllable_delta={details['syllable_group_delta']} | zero_initial_groups={details['zero_initial_group_count']} | multi_note_groups={details['multiple_note_group_count']} | special={record['special_token_types']}", fontsize=8)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=160); plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--meta", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--per-class", type=int, default=10)
    parser.add_argument("--cjk-font", type=Path, help="CJK OpenType/TrueType font for actual Chinese glyphs in PNG")
    args = parser.parse_args()
    cjk_font = FontProperties(fname=str(args.cjk_font)) if args.cjk_font else None
    raw_by_id = {x["item_name"]: x for x in json.loads(args.meta.read_text(encoding="utf-8"))}
    records = [json.loads(line) for line in args.audit.read_text(encoding="utf-8").splitlines() if line]
    grouped: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        if record["taxonomy"] != "accepted_rule_based": grouped[record["primary_reason"]].append(record)
    counts = {reason: len(rows) for reason, rows in sorted(grouped.items())}
    fig, axis = plt.subplots(figsize=(12, 5), constrained_layout=True)
    labels, values = list(counts), list(counts.values())
    axis.barh(labels, values, color="#457b9d"); axis.invert_yaxis(); axis.set_xlabel("B-tier records"); axis.set_title("M4Singer B-tier primary reason review")
    for index, value in enumerate(values): axis.text(value, index, f" {value} ({value / sum(values):.1%})", va="center", fontsize=8)
    args.out_dir.mkdir(parents=True, exist_ok=True); fig.savefig(args.out_dir / "00_primary_reason_overview.png", dpi=160); plt.close(fig)
    index_lines = ["<html><body><h1>B-tier visual review</h1><p>Stars denote is_slur. Top lane derives from ph_dur; bottom lane independently derives from notes_dur.</p>"]
    for reason, rows in sorted(grouped.items()):
        chosen = sorted(rows, key=lambda row: row["item_id"])[:args.per_class]
        index_lines.append(f"<h2>{reason} ({len(rows)})</h2>")
        for number, record in enumerate(chosen, 1):
            name = f"{reason}/{number:02d}_{record['item_id'].replace('#', '_')}.png"
            draw_item(record, raw_by_id[record["item_id"]], args.out_dir / name, cjk_font)
            raw = raw_by_id[record["item_id"]]
            text = normalize_lyrics(raw["txt"]).text
            index_lines.append(f"<div><a href='{name}'><img src='{name}' width='1000'></a><p><b>{record['item_id']}</b><br>raw text: {raw['txt']}<br>normalized characters: {' | '.join(f'C{i}={char} (U+{ord(char):04X})' for i, char in enumerate(text))}<br>candidate syllable groups: {' | '.join(' '.join(raw['phs'][i] for i in group) for group in group_phonemes(raw['phs'])[0])}<br>reason: {record['primary_reason']}; evidence: {record['reason_details']}</p></div>")
    index_lines.append("</body></html>")
    (args.out_dir / "index.html").write_text("\n".join(index_lines), encoding="utf-8")
    (args.out_dir / "review_summary.json").write_text(json.dumps({"b_tier": sum(counts.values()), "counts": counts, "per_class": args.per_class}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
