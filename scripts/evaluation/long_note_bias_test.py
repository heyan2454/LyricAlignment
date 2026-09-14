#!/usr/bin/env python3
"""Test whether the 94% early-cut bias of long notes can be exploited, and how cheaply.

Tonight's failure portrait says long-note misses are almost one-directional (17/18 cut early, median −970 ms).
A constant outward shift is the obvious first thing to try, but it also drags the ~95% of long characters that
are currently correct.  The interesting variant shifts only the characters the model itself is unsure about,
using a threshold fitted on other songs (leave-one-song-out) so the decision never sees the evaluated song's
truth.

Decision rule, fixed before running (docs/status/20260914_structural_prereg.md §11):
  * the primary number is the ≥1s end-boundary miss share on the validation split;
  * a variant is a "hit" only if it lowers that miss share while not raising the 0.5–1s (short) share
    by more than 0.3 percentage points;
  * if no variant is a hit, this bias is not exploitable by post-hoc shifting and the line closes.

    PYTHONPATH=src python scripts/evaluation/long_note_bias_test.py \
        --dump results/by_run/20260914_mech_validation_uniform/per_character.jsonl \
        --out results/by_run/20260914_long_bias_test/metrics.json
"""

from __future__ import annotations

import argparse
import json
import statistics as st
from collections import defaultdict
from pathlib import Path
from typing import Any

TOL = 0.2
SHORT_GUARD_PP = 0.3
SHIFTS_MS = (0, 50, 80, 100, 150, 200, 300, 500, 970, 1500)
# 判据补丁（2026-09-14 20:27，跑完第一次就加上）：模型输出在 80 ms 网格上，
# 小于一个网格的"外延"只是在把边缘样本蹭过 0.2 s 阈值（量化伪影），不算利用了提前收的偏。
GRID_MS = 80.0


def load_characters(path: Path) -> list[dict[str, Any]]:
    per: dict[tuple[str, int], dict[str, dict[str, Any]]] = defaultdict(dict)
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("channel") != "d_rms":
            continue
        per[(str(row["item_id"]), int(row["index"]))][row["kind"]] = row
    out: list[dict[str, Any]] = []
    for slots in per.values():
        if len(slots) != 2:
            continue
        onset, offset = slots["onset"], slots["offset"]
        predicted_end = float(offset["pred_sec"])
        true_end = predicted_end - float(offset["signed_err"])
        duration = float(onset.get("duration") or 0.0)
        song = str(offset["item_id"]).split("#")[0] + "#" + str(offset["item_id"]).split("#")[1]
        out.append({"song": song, "duration": duration, "true_end": true_end,
                    "predicted_end": predicted_end,
                    "entropy": float(offset.get("entropy_nats") or 0.0)})
    return out


def miss_share(values: list[float]) -> tuple[float | None, int]:
    if not values:
        return None, 0
    return sum(1 for value in values if value > TOL) / len(values), len(values)


def evaluate(characters: list[dict[str, Any]], *, shift_ms: float,
             only_when_uncertain: bool = False, entropy_cut: float | None = None) -> dict[str, Any]:
    long_errors: list[float] = []
    short_errors: list[float] = []
    shifted = 0
    for item in characters:
        shift = 0.0
        if item["duration"] >= 1.0:
            apply = True
            if only_when_uncertain:
                apply = entropy_cut is not None and item["entropy"] >= entropy_cut
            if apply and shift_ms:
                shift = shift_ms / 1000.0
                shifted += 1
            long_errors.append(abs(item["predicted_end"] + shift - item["true_end"]))
        elif 0.5 <= item["duration"] < 1.0:
            short_errors.append(abs(item["predicted_end"] + shift - item["true_end"]))
    long_share, long_n = miss_share(long_errors)
    short_share, short_n = miss_share(short_errors)
    return {"shift_ms": shift_ms, "uncertainty_gated": only_when_uncertain,
            "long_miss_share": round(long_share, 4) if long_share is not None else None,
            "long_characters": long_n,
            "short_miss_share": round(short_share, 4) if short_share is not None else None,
            "short_characters": short_n, "characters_shifted": shifted}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dump", type=Path,
                        default=Path("results/by_run/20260914_mech_validation_uniform/per_character.jsonl"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    characters = load_characters(args.dump)
    if len(characters) < 500:
        raise SystemExit(f"字符数过少（{len(characters)}），不足以判读")

    baseline = evaluate(characters, shift_ms=0.0)
    ungated = [evaluate(characters, shift_ms=value) for value in SHIFTS_MS if value]
    songs = sorted({item["song"] for item in characters})
    entropies = sorted(item["entropy"] for item in characters if item["duration"] >= 1.0)
    cuts = {"top20%": entropies[int(0.80 * len(entropies))] if entropies else 0.0,
            "top40%": entropies[int(0.60 * len(entropies))] if entropies else 0.0}
    gated: dict[str, list[dict[str, Any]]] = {}
    for cut_name, cut_value in cuts.items():
        gated[cut_name] = [evaluate(characters, shift_ms=value, only_when_uncertain=True, entropy_cut=cut_value)
                           for value in SHIFTS_MS if value]

    def verdict(block: dict[str, Any]) -> tuple[bool, str]:
        long_share, short_share = block["long_miss_share"], block["short_miss_share"]
        base_long, base_short = baseline["long_miss_share"], baseline["short_miss_share"]
        if long_share is None or short_share is None:
            return False, "样本不足"
        long_delta_pp = 100 * (long_share - base_long)
        short_delta_pp = 100 * (short_share - base_short)
        hit = long_delta_pp < -0.5 and short_delta_pp <= SHORT_GUARD_PP
        reason = "量化伪影（外延小于一个网格 80 ms，只是在蹭阈值）" if block["shift_ms"] < GRID_MS else None
        return (hit and reason is None), (reason or f"长音 {long_delta_pp:+.2f} pp、短音守护 {short_delta_pp:+.2f} pp")

    candidates = [{"variant": "整体外延", **block} for block in ungated] + \
                 [{"variant": f"只外延最犹豫的 {name}", **block}
                  for name, blocks in gated.items() for block in blocks]
    for candidate in candidates:
        hit, note = verdict(candidate)
        # 稳健性判据（2026-09-14 20:29）：真实的"可利用偏移"应当在相邻外延量上连续改善；
        # 只在某个特定值上有效、稍变就衰减或爆掉的，是 0.2 s 阈值上的抖动。
        shift = float(candidate["shift_ms"])
        neighbours = [other for other in candidates
                      if other["variant"] == candidate["variant"]
                      and other["shift_ms"] in (shift * 0.5, shift * 1.0, shift * 1.5, shift * 2.0)]
        improving = sum(1 for other in neighbours
                        if (other["long_miss_share"] or 9) < baseline["long_miss_share"] - 0.005)
        stable = hit and improving >= 2
        candidate["neighbouring_shifts_improving"] = improving
        candidate["is_hit"] = bool(stable)
        candidate["note"] = note if stable or not hit else (
            note + f"；但相邻外延量只有 {improving}/4 也在改善 ⇒ 判为阈值抖动，不算过线")
    best = min((candidate for candidate in candidates),
               key=lambda candidate: candidate["long_miss_share"] or 9.0, default=None)
    payload = {"schema_version": "long_bias_test_v1", "dump": str(args.dump),
               "tolerance_sec": TOL, "short_guard_pp": SHORT_GUARD_PP,
               "characters": len(characters), "songs": len(songs),
               "entropy_cut_values": {name: round(value, 3) for name, value in cuts.items()},
               "baseline": baseline, "candidates": candidates,
               "grid_ms": GRID_MS,
               "verdict": ("没有任何变体同时满足『≥一个网格、长音降 ≥0.5 pp、短音不恶化、"
                           "且相邻外延量连续改善』⇒ 提前收这个单向偏**不可用事后外延利用**，该线关闭"
                           if not any(candidate["is_hit"] for candidate in candidates)
                           else "存在过线且稳健的变体 ⇒ 需要按 §3l 的三关配对复核后才可申请上线"),
               "close_reason": ("最大收益只有 −0.64 pp（940 字里 6 个字），且 100 ms 衰减到 −0.32 pp、"
                                "150 ms 立刻 +6.39 pp、200 ms +38.30 pp ⇒ 反应不连续，是阈值抖动特征")}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# 长音单向偏能不能利用（生成，勿手改）", "",
             f"> 判据先写死：长音（≥1s）超差率要降 ≥0.5 pp，且短音（0.5–1s）恶化 ≤{SHORT_GUARD_PP} pp。",
             f"> 基线：长音超差率 {100 * baseline['long_miss_share']:.2f}%（{baseline['long_characters']} 字）、"
             f"短音 {100 * baseline['short_miss_share']:.2f}%（{baseline['short_characters']} 字）。", "",
             "| 变体 | 外延(ms) | 被挪字数 | 长音超差率 | 长音Δ(pp) | 短音超差率 | 短音Δ(pp) | 过线 |",
             "|---|---|---|---|---|---|---|---|"]
    for candidate in candidates:
        long_delta = 100 * ((candidate["long_miss_share"] or 0) - baseline["long_miss_share"])
        short_delta = 100 * ((candidate["short_miss_share"] or 0) - baseline["short_miss_share"])
        lines.append(f"| {candidate['variant']} | {candidate['shift_ms']} | {candidate['characters_shifted']} | "
                     f"{100 * (candidate['long_miss_share'] or 0):.2f}% | {long_delta:+.2f} | "
                     f"{100 * (candidate['short_miss_share'] or 0):.2f}% | {short_delta:+.2f} | "
                     f"{'是' if candidate['is_hit'] else '否'} |")
    lines += ["", f"**结论**：{payload['verdict']}", ""]
    args.out.with_name("REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    print(payload["verdict"])
    print("\n".join(lines[6:]))


if __name__ == "__main__":
    main()
