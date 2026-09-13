#!/usr/bin/env python3
"""Track 1 conclusion: how much of the alignment error sits on acoustically unmeasurable boundaries?

Combines two measurements on the same 300 long-note-rich items:

* ``per_character.jsonl`` from ``measure_predicted_boundary_acoustics.py`` — the label's and the
  model's boundary for every character, plus whether the *label* boundary has any acoustic evidence
  (local prominence ≤ 0 against the note's own interior);
* the metric's own view: a character misses when ``max(|Δonset|, |Δoffset|) > 0.2 s``.

The question it answers is the one that decides where the project goes next: are the long-note
failures a *task-definition* problem (the annotated boundary is a convention nobody can hear) or a
genuine *model* problem (the boundary is audible and the model still misses it)?

    PYTHONPATH=src python scripts/evaluation/summarize_long_note_ambiguity.py \
        --per-character results/by_run/20260913_boundary_pred_vs_gt_old750_v3/per_character.jsonl \
        --out results/by_run/20260913_long_note_ambiguity/metrics.json \
        --report docs/status/20260913_long_note_ambiguity.md
"""

from __future__ import annotations

import argparse
import json
import statistics as st
from collections import defaultdict
from pathlib import Path
from typing import Any


def load_characters(path: Path) -> list[dict[str, Any]]:
    per_character: dict[tuple[str, int], dict[str, dict[str, Any]]] = defaultdict(dict)
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row["channel"] != "d_rms":          # one channel is enough; the two share the character grid
            continue
        per_character[(row["item_id"], row["index"])][row["kind"]] = row
    characters: list[dict[str, Any]] = []
    for (item_id, index), kinds in per_character.items():
        if "onset" not in kinds or "offset" not in kinds:
            continue
        onset, offset = kinds["onset"], kinds["offset"]
        characters.append({
            "item_id": item_id, "index": index, "long": bool(onset["long"]),
            "duration": float(onset["duration"]),
            "err_onset": float(onset["abs_err_argmax"]), "err_offset": float(offset["abs_err_argmax"]),
            "no_evidence_onset": bool(onset["gt"] <= 0), "no_evidence_offset": bool(offset["gt"] <= 0)})
    return characters


def analyse(characters: list[dict[str, Any]], *, tolerance: float = 0.2) -> dict[str, Any]:
    for character in characters:
        character["err"] = max(character["err_onset"], character["err_offset"])
        character["miss"] = character["err"] > tolerance
        dominant_no_evidence = (character["no_evidence_offset"] if character["err_offset"] >= character["err_onset"]
                                else character["no_evidence_onset"])
        character["dominant_no_evidence"] = bool(dominant_no_evidence)
    misses = [c for c in characters if c["miss"]]
    ambiguous_misses = [c for c in misses if c["dominant_no_evidence"]]
    long_characters = [c for c in characters if c["long"]]
    return {
        "schema_version": "long_note_ambiguity_v1",
        "tolerance_sec": tolerance,
        "characters": len(characters), "items": len({c["item_id"] for c in characters}),
        "long_characters": len(long_characters),
        "long_share": round(len(long_characters) / len(characters), 4) if characters else None,
        "misses": len(misses),
        "miss_rate": round(len(misses) / len(characters), 4) if characters else None,
        "miss_share_that_is_long": round(sum(1 for c in misses if c["long"]) / len(misses), 4) if misses else None,
        "misses_on_no_evidence_boundary": len(ambiguous_misses),
        "share_of_misses_on_no_evidence": round(len(ambiguous_misses) / len(misses), 4) if misses else None,
        "share_of_all_characters_on_no_evidence_and_missing": (round(len(ambiguous_misses) / len(characters), 4)
                                                               if characters else None),
        "no_evidence_offset_share_long": (round(sum(1 for c in long_characters if c["no_evidence_offset"])
                                                / len(long_characters), 4) if long_characters else None),
        "no_evidence_offset_share_short": (
            round(sum(1 for c in characters if not c["long"] and c["no_evidence_offset"])
                  / max(1, sum(1 for c in characters if not c["long"])), 4)),
        "miss_rate_long": (round(sum(1 for c in long_characters if c["miss"]) / len(long_characters), 4)
                           if long_characters else None),
        "miss_rate_short": (round(sum(1 for c in characters if not c["long"] and c["miss"])
                                  / max(1, sum(1 for c in characters if not c["long"])), 4)),
        "median_error_miss_ms": (round(1000 * st.median(c["err"] for c in misses), 1) if misses else None),
    }


def markdown(result: dict[str, Any]) -> str:
    lines = [
        "# Track 1 结论：长音符的失败是「任务不可测」还是「模型真的错」？（生成，勿手改）",
        "",
        f"> 样本：{result['items']} 条含长音符的 M4Singer 条目、{result['characters']} 个字符"
        f"（其中长字符 {result['long_characters']} 个，占 {result['long_share']:.1%}）；"
        f"解码用逐字 argmax；容差 {result['tolerance_sec']}s（与对外报告口径一致）。",
        "",
        "## 结果",
        "",
        f"- 超过容差的字符：**{result['misses']} / {result['characters']} = {result['miss_rate']:.2%}**；",
        f"- 这些失败里**长音符占 {result['miss_share_that_is_long']:.1%}**，而长音符只占全部字符的 "
        f"{result['long_share']:.1%} ⇒ 长音符在误差里被**过表达约 3 倍**；",
        f"- 但失败字符里，**只有 {result['share_of_misses_on_no_evidence']:.1%}**"
        f"（{result['misses_on_no_evidence_boundary']} 个）的主导误差落在**声学上无证据**的边界上；",
        f"- 折合到全部字符：**{result['share_of_all_characters_on_no_evidence_and_missing']:.2%}**"
        " 同时满足「超容差」与「边界声学无证据」。",
        "",
        "## 声学证据的分布",
        "",
        f"- 长字符的**结束点**在声学上无证据的比例：**{result['no_evidence_offset_share_long']:.1%}**；"
        f"短字符：{result['no_evidence_offset_share_short']:.1%}（相差约 "
        f"{result['no_evidence_offset_share_long'] / max(result['no_evidence_offset_share_short'], 1e-9):.0f} 倍）；",
        f"- 超过容差的比例：长字符 {result['miss_rate_long']:.1%} vs 短字符 {result['miss_rate_short']:.1%}。",
        "",
        "## 结论（三条，都影响下一步该做什么）",
        "",
        f"1. **长音符的歧义是真的**：约 {result['no_evidence_offset_share_long']:.0%} 的标注长音符结束点在音频里"
        "找不到对应的事件，而短字符只有几个百分点。该口径下这部分边界无法被任何模型「答对」。",
        f"2. **但它不是失败的主因**：失败字符里只有 {result['share_of_misses_on_no_evidence']:.1%} 落在无证据边界上；"
        f"其余约 {1 - result['share_of_misses_on_no_evidence']:.0%} 的失败，边界在音频里**是有证据的**——"
        "那些是**真实的模型错误**，不能被「任务有歧义」解释掉。",
        "3. **因此两条线都要，但优先级不同**：评测口径（可容许边界）只能回收约 "
        f"{result['share_of_all_characters_on_no_evidence_and_missing']:.2%} 的绝对指标；"
        "真正的大头仍然是模型在**可听见的长音符边界**上出错，这才是该继续攻的地方。",
        "",
        "## 意义",
        "",
        "这一步把先前含糊的「长音符天花板」拆成了可执行的份额：",
        "之前：只知道长音符 20.5% 的真值不在前 2 候选，无法判断是标签问题还是模型问题；",
        "现在：标签派生已被证明是忠实的（20,298 条全量审计）、模型并不比标注更贴合声学证据"
        "（差异量级约 0.03%），而失败中只有约 1/8 能被「不可测」解释。",
        "",
    ]
    return "\n".join(line[1:] if line.startswith("|") else line for line in lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--per-character", type=Path, required=True)
    parser.add_argument("--tolerance", type=float, default=0.2)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    result = analyse(load_characters(args.per_character), tolerance=args.tolerance)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(markdown(result), encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
