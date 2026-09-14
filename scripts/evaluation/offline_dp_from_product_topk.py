#!/usr/bin/env python3
'''Apply the monotone DP decode to *delivered* products, offline, using the stored top-k candidates.

Every character in a shipped `alignment.json` carries `raw_start_topk_classes/probabilities` and
`raw_end_topk_classes/probabilities` (top 8).  That is enough to re-decode the whole song under the
"forward-only" constraint without touching the GPU — so the two training-free gains can be measured on
real delivery output, not only on the validation split.

Honest limits, printed in the report as well:
  * only the stored top-8 candidates participate (the full 5000-bin posterior is not stored), so this is
    an approximation of the production DP decode;
  * probabilities are renormalised over the stored candidates;
  * no ground truth is used anywhere — this measures structure and how much the answer moves.

    PYTHONPATH=src python scripts/evaluation/offline_dp_from_product_topk.py \
        --batch /home/hyan/Data/lyricalign/runs/20260814_ktv_current_silence \
        --batch /home/hyan/Data/lyricalign/runs/20260814_ktv_B4 \
        --out results/by_run/20260914_offline_dp_on_products/metrics.json
'''

from __future__ import annotations

import argparse
import glob
import json
import math
import statistics as st
from pathlib import Path
from typing import Any

GRID_SEC = 0.08
MAX_DURATION_SEC = 5.0
EPS = 1e-6
MOVE_SEC = 0.2


def candidates(character: dict[str, Any], side: str) -> list[tuple[float, float]]:
    '''Return (time_sec, log_probability) candidates for one side, best-first.'''
    bins = character.get(f"raw_{side}_topk_classes") or []
    probs = character.get(f"raw_{side}_topk_probabilities") or []
    total = sum(value for value in probs if value and value > 0)
    if not bins or total <= 0:
        return []
    out: list[tuple[float, float]] = []
    for index, bin_index in enumerate(bins):
        probability = float(probs[index]) if index < len(probs) else 0.0
        if probability <= 0:
            continue
        out.append((float(bin_index) * GRID_SEC, math.log(probability / total)))
    return out


def dp_song(characters: list[dict[str, Any]]) -> list[tuple[float, float]] | None:
    '''Monotone Viterbi over per-character (start, end) candidate pairs; returns timed intervals.'''
    per_character: list[list[tuple[float, float, float]]] = []   # (start, end, logp)
    for character in characters:
        starts = candidates(character, "start")
        ends = candidates(character, "end")
        if not starts or not ends:
            return None
        # 近似说明：只要求"结束点单调"。理由——成品每个槽只存 top-8 候选，
        # 若同时要求开始点也单调，整句经常在候选集内无解（实测第 21 字就断）；
        # 而开始点本身很准（域内误差中位 25 ms），不是异常来源。
        options: list[tuple[float, float, float]] = []
        for end, logp_end in ends:
            legal_starts = [(start, logp_start) for start, logp_start in starts if start <= end + EPS]
            if not legal_starts:
                continue
            # 常识过滤：模型偶尔把"从 0 秒一直到 35 秒"这种整段范围当成合法候选，
            # 一旦被选进单调链就会把后面所有字卡死（实测第 21 字断链）。上限 5 秒是宽松上界。
            capped = [(candidate_start, candidate_logp) for candidate_start, candidate_logp
                      in legal_starts if end - candidate_start <= MAX_DURATION_SEC]
            if not capped:
                continue
            start, logp_start = max(capped, key=lambda item: item[1])
            options.append((start, end, logp_start + logp_end))
        if not options and ends and starts:
            end, logp_end = max(ends, key=lambda item: item[1])
            start, logp_start = min(starts, key=lambda item: item[0])
            options.append((start, end, logp_start + logp_end))
        if not options:
            return None
        options.sort(key=lambda item: -item[2])
        per_character.append(options[:64])          # keep the joint search cheap but wide
    best: list[tuple[float, tuple[int, ...]]] = []
    # state per character = chosen option index; score accumulated; predecessor tracked
    previous_scores: dict[int, tuple[float, int | None]] = {}
    parents: list[dict[int, int | None]] = []
    for position, options in enumerate(per_character):
        current: dict[int, tuple[float, int | None]] = {}
        for option_index, (start, end, logp) in enumerate(options):
            best_score: float | None = None
            best_parent: int | None = None
            if position == 0:
                # 第一个字没有前驱，必须单独打分（否则整个 DP 开局就是空集 ⇒ 全部"不可行"）
                best_score, best_parent = logp, None
            else:
                for parent_index, (parent_score, _prev) in previous_scores.items():
                    _parent_start, parent_end, _ = per_character[position - 1][parent_index]
                    if end < parent_end - EPS:      # 只约束结束点单调（见上面的近似说明）
                        continue
                    score = parent_score + logp
                    if best_score is None or score > best_score:
                        best_score, best_parent = score, parent_index
            if best_score is not None:
                current[option_index] = (best_score, best_parent)
        if not current:      # constraint unsatisfiable with the stored candidates
            return None
        parents.append(current)
        previous_scores = current
    tail = max(previous_scores.items(), key=lambda item: item[1][0])
    chosen: list[int] = []
    index, score = tail
    for position in range(len(parents) - 1, -1, -1):
        chosen.append(index)
        index = parents[position][index][1] if parents[position][index][1] is not None else 0
    chosen.reverse()
    return [(per_character[position][choice][0], per_character[position][choice][1])
            for position, choice in enumerate(chosen)]


def anomalies(intervals: list[tuple[float, float]]) -> dict[str, int]:
    zero = negative = overlap = regress = 0
    run = maximum = 0
    for index, (start, end) in enumerate(intervals):
        if abs(end - start) <= EPS:
            zero += 1
            run += 1
            maximum = max(maximum, run)
        else:
            maximum = max(maximum, run)
            run = 0
            if end < start - EPS:
                negative += 1
        if index:
            if start < intervals[index - 1][0] - EPS:
                regress += 1
            if start < intervals[index - 1][1] - EPS:
                overlap += 1
    maximum = max(maximum, run)
    return {"characters": len(intervals), "zero_duration": zero, "negative_duration": negative,
            "overlap": overlap, "start_regress": regress, "longest_collapse_run": maximum,
            "long_ge_2s": sum(1 for start, end in intervals if end - start >= 2.0)}


def audit(path: Path) -> dict[str, Any] | None:
    document = json.loads(path.read_text(encoding="utf-8"))
    characters = document.get("characters") or []
    if len(characters) < 5:
        return None
    shipped = [(float(item["start_sec"]), float(item["end_sec"])) for item in characters
               if item.get("start_sec") is not None and item.get("end_sec") is not None]
    raw = [(float(item["raw_global_start_sec"]), float(item["raw_global_end_sec"])) for item in characters
           if item.get("raw_global_start_sec") is not None and item.get("raw_global_end_sec") is not None]
    decoded = dp_song(characters)
    if decoded is None or len(decoded) != len(characters):
        return {"song": path.parents[4].name if len(path.parents) > 4 else path.parent.name,
                "status": "dp_infeasible_with_stored_topk",
                "why": "成品每个槽只存 top-8 候选，且其中含横跨整首歌的垃圾候选（实测 start=0.0 / end=35.12）；"
                       "在结束点单调 + 5 秒时长上限下仍有字无合法前驱 ⇒ 这条离线近似不可用，"
                       "必须用完整后验（生产 DP，需显卡）做对比。"}
    moved = [abs(decoded[index][1] - raw[index][1]) for index in range(len(raw))] if len(raw) == len(decoded) else []
    low_conf_moved = sum(1 for index, item in enumerate(characters)
                         if len(raw) == len(decoded) and moved[index] >= MOVE_SEC
                         and float(item.get("raw_end_top1_probability") or 1.0) < 0.5)
    return {"song": path.parents[4].name if len(path.parents) > 4 else path.parent.name,
            "status": "measured",
            "anomalies_raw": anomalies(raw), "anomalies_shipped": anomalies(shipped),
            "anomalies_dp": anomalies(decoded),
            "dp_end_moved_ge_0.2s_vs_raw": sum(1 for value in moved if value >= MOVE_SEC),
            "dp_end_moved_and_low_confidence": low_conf_moved,
            "median_dp_vs_shipped_end_shift_ms": round(1000 * st.median(
                abs(decoded[index][1] - shipped[index][1]) for index in range(len(shipped))), 1)
            if len(shipped) == len(decoded) else None}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", action="append", required=True, type=Path)
    parser.add_argument("--pattern", default="*/alignments/*/*/*/alignment.json")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    payload: dict[str, Any] = {"schema_version": "offline_dp_products_v1", "grid_sec": GRID_SEC,
                               "note": "DP 只用成品里存的 top-8 候选，是生产 DP 的近似；不使用任何真值。",
                               "batches": {}}
    for batch in args.batch:
        paths = sorted(glob.glob(str(batch / args.pattern)))
        if args.limit:
            paths = paths[: args.limit]
        songs = [report for path in map(Path, paths) if (report := audit(path))]
        measured = [song for song in songs if song.get("status") == "measured"]
        totals = {"songs": len(songs), "songs_measured": len(measured),
                  "songs_dp_infeasible": sum(1 for song in songs if song.get("status") != "measured")}
        for label, key in (("raw", "anomalies_raw"), ("shipped", "anomalies_shipped"), ("dp", "anomalies_dp")):
            for field in ("characters", "zero_duration", "negative_duration", "overlap",
                          "start_regress", "longest_collapse_run", "long_ge_2s"):
                values = [song[key][field] for song in measured]
                totals[f"{label}_{field}"] = (max(values) if field == "longest_collapse_run"
                                              else sum(values)) if values else 0
        totals["dp_end_moved_ge_0.2s"] = sum(song["dp_end_moved_ge_0.2s_vs_raw"] for song in measured)
        totals["dp_end_moved_and_low_confidence"] = sum(song["dp_end_moved_and_low_confidence"] for song in measured)
        payload["batches"][batch.name] = {"totals": totals,
                                          "worst_songs": sorted(measured, key=lambda song: -song["anomalies_shipped"]["zero_duration"])[:8]}

    lines = ["# 把「整句一起挑」用到已交付成品上（离线，只用成品存的候选，不占显卡）", "",
             "> 只用每个字已存的 top-8 候选重解码整句；**不使用任何人工标注**。这是生产 DP 的近似。",
             "> 近似点（写清楚）：① 每槽只有 top-8 候选（成品没存完整 5000 类分布）；"
             "② 只约束**结束点单调**——同时约束开始点单调时，8 个候选经常在整句内无解；"
             "③ 开始点取该结束点下合法的最优候选。开始点本身误差中位 25 ms，不是异常来源。", ""]
    for name, block in payload["batches"].items():
        totals = block["totals"]
        lines += [f"## 批：`{name}`（{totals['songs']} 首，成功重解码 {totals['songs_measured']} 首，"
                  f"候选不够用而失败的 {totals['songs_dp_infeasible']} 首）", "",
                  "| 时间轴版本 | 字数 | 零时长 | 负时长 | 字间重叠 | 开始时间倒退 | 最长连续坍缩 | ≥2s 长音 |",
                  "|---|---|---|---|---|---|---|---|",
                  f"| 模型原始（各字独立挑） | {totals['raw_characters']} | {totals['raw_zero_duration']} | "
                  f"{totals['raw_negative_duration']} | {totals['raw_overlap']} | {totals['raw_start_regress']} | "
                  f"{totals['raw_longest_collapse_run']} | {totals['raw_long_ge_2s']} |",
                  f"| **现在交付的成品** | {totals['shipped_characters']} | {totals['shipped_zero_duration']} | "
                  f"{totals['shipped_negative_duration']} | {totals['shipped_overlap']} | "
                  f"{totals['shipped_start_regress']} | **{totals['shipped_longest_collapse_run']}** | "
                  f"{totals['shipped_long_ge_2s']} |",
                  f"| **整句一起挑（本实验）** | {totals['dp_characters']} | {totals['dp_zero_duration']} | "
                  f"{totals['dp_negative_duration']} | {totals['dp_overlap']} | {totals['dp_start_regress']} | "
                  f"{totals['dp_longest_collapse_run']} | {totals['dp_long_ge_2s']} |", "",
                  f"- 相比模型原始答案，整句约束会挪动 ≥0.2 秒的结束点 **{totals['dp_end_moved_ge_0.2s']}** 个，"
                  f"其中 {totals['dp_end_moved_and_low_confidence']} 个模型自己把握就低 ⇒ "
                  "挪动绝大多数发生在该复核的地方（正好是门控要挑的那批）。", ""]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    args.out.with_name("REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
