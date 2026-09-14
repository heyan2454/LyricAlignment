#!/usr/bin/env python3
"""Apply the pre-registered warm-start A/B decision rule mechanically.

The rules were frozen in `docs/status/20260914_concat_arm_prereg.md` before the arms ran, so they
belong in code rather than in a morning reading of tables.  Every criterion comes back with an
explicit status — `pass`, `fail`, `insufficient_data`, `not_run` — because "we did not measure it"
must never be reported as "it did not work" or as silence.

Inputs are the JSONs the existing tools already produce:
* `--view label=path`       : long-context view files (`eval_long_context_view.py`), which carry
  `variants.<decoder>.per_song`, so the endpoint is compared song against song;
* `--duration label=path`   : `duration_ratio_profile.py` output, for the mechanism check
  (does the failing subset's duration ratio move toward 1?);
* `--short label=path`      : optional funnel top-up summary, for the "do not wreck the short-item
  view" guard.

    PYTHONPATH=src python scripts/evaluation/warmstart_ab_verdict.py \
        --view uniform-12000=results/by_run/20260914_long_context_view/baseline_aligned.summary.json \
        --view warmstart-control=... --view warmstart-oversample=... \
        --control warmstart-control --treatment warmstart-oversample \
        --baseline old-r2-750 --out results/by_run/20260914_warmstart_ab
"""

from __future__ import annotations

import argparse
import json
import math
import statistics as st
from pathlib import Path
from typing import Any

PRIMARY_DECODER = "fixed"


def paired_by_song(left: dict[str, float], right: dict[str, float], *, minimum_songs: int = 5) -> dict[str, Any]:
    shared = sorted(set(left) & set(right))
    if len(shared) < minimum_songs:
        return {"status": "insufficient_data", "songs": len(shared)}
    diffs = [right[song] - left[song] for song in shared]
    mean = st.mean(diffs)
    se = st.stdev(diffs) / math.sqrt(len(diffs)) if len(diffs) > 1 else 0.0
    z = mean / se if se > 1e-12 else None
    return {"status": "measured", "songs": len(diffs), "mean_delta_pp": round(100 * mean, 3),
            "se_pp": round(100 * se, 3), "z": round(z, 2) if z is not None else None,
            "better": sum(1 for value in diffs if value > 0), "worse": sum(1 for value in diffs if value < 0)}


def song_scores(view_documents: list[dict[str, Any]], *, decoder: str = PRIMARY_DECODER) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for document in view_documents:
        for label, block in document.get("checkpoints", {}).items():
            variants = block.get("variants") or {}
            per_song = (variants.get(decoder) or {}).get("per_song") or {}
            scores = {song: float(values["within_200ms"]) for song, values in per_song.items()
                      if isinstance(values, dict) and values.get("within_200ms") is not None}
            if scores:
                out[label] = scores
    return out


def duration_ratio(duration_documents: list[dict[str, Any]], label: str) -> dict[str, Any]:
    for document in duration_documents:
        if document.get("label") == label:
            buckets = document.get("buckets") or {}
            for name in ("2-+s", "2.0+s", "1-2.0s", "1-2s"):
                block = buckets.get(name)
                if block:
                    return {"bucket": name,
                            "miss_median_duration_ratio": block.get("miss_median_duration_ratio"),
                            "miss_share": block.get("miss_share"), "characters": block.get("characters")}
    return {"status": "not_run"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--view", action="append", default=[],
                        help="长上下文视图 JSON（可 label=path，也可直接给路径；标签取文件内 checkpoints 的键）")
    parser.add_argument("--duration", action="append", default=[],
                        help="label=path，duration_ratio_profile.py 的输出，label 须与 --control/--treatment 一致")
    parser.add_argument("--control", default="warmstart-control")
    parser.add_argument("--treatment", default="warmstart-oversample")
    parser.add_argument("--baseline", default="old-r2-750")
    parser.add_argument("--reference", default="uniform-12000", help="两臂共同的热启动来源")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--decoder", default=PRIMARY_DECODER,
                        help="用哪个判据做配对；换 dp 属于**另一份预注册**，两者都报才诚实")
    args = parser.parse_args()
    views: list[dict[str, Any]] = []
    unreadable: list[dict[str, str]] = []
    for spec in args.view:
        location = spec.split("=", 1)[-1] if "=" in spec else spec
        path = Path(location)
        if not path.exists():
            # A missing input is a result in itself: report it as not_run instead of crashing,
            # so the morning verdict still prints the comparisons that *can* be made.
            unreadable.append({"requested": location, "status": "not_run", "reason": "文件不存在"})
            print(f"[warn] 视图文件不存在，记为未跑：{location}", flush=True)
            continue
        views.append(json.loads(path.read_text(encoding="utf-8")))
    durations: list[dict[str, Any]] = []
    for spec in args.duration:
        label, _, location = spec.partition("=")
        block = json.loads(Path(location or label).read_text(encoding="utf-8"))
        block["label"] = label
        durations.append(block)
    scores = song_scores(views, decoder=args.decoder)
    missing = [name for name in (args.baseline, args.control, args.treatment, args.reference) if name not in scores]
    reference = scores.get(args.reference, {})
    baseline = scores.get(args.baseline, {})
    control = scores.get(args.control, {})
    treatment = scores.get(args.treatment, {})
    payload: dict[str, Any] = {"schema_version": "warmstart_ab_verdict_v2",
                               "missing_view_files": unreadable,
                               "available_checkpoints": sorted(scores), "missing": missing,
                               "primary_decoder": args.decoder, "tolerance": "within_200ms",
                               "comparisons": {
                                   "treatment_vs_baseline": paired_by_song(baseline, treatment),
                                   "control_vs_baseline": paired_by_song(baseline, control),
                                   "treatment_vs_control": paired_by_song(control, treatment),
                                   "treatment_vs_reference": paired_by_song(reference, treatment),
                                   "control_vs_reference": paired_by_song(reference, control)},
                               "mechanism": {
                                   "control": duration_ratio(durations, args.control),
                                   "treatment": duration_ratio(durations, args.treatment)}}
    pairwise = payload["comparisons"]["treatment_vs_control"]
    direct = paired_by_song(control, treatment)
    payload["verdict"] = {
        "main_vs_online_baseline": "pass" if (payload["comparisons"]["treatment_vs_baseline"].get("z") or 0) >= 2
        and (payload["comparisons"]["treatment_vs_baseline"].get("mean_delta_pp") or 0) > 0
        else payload["comparisons"]["treatment_vs_baseline"].get("status", "not_run"),
        "net_effect_vs_control": "pass" if (direct.get("z") or 0) >= 2 and (direct.get("mean_delta_pp") or 0) > 0
        else direct.get("status", "not_run"),
        "control_drift": payload["comparisons"]["control_vs_baseline"].get("status"),
        "treatment_vs_control_paired": direct,
        "note": "净效应以**逐歌配对 B vs A** 为准（treatment_vs_control_paired），"
                "两臂各自对基线的差仅作参考。机制项不参与判决。"}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "metrics.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                                           encoding="utf-8")
    lines = ["# 热启动 A/B 判决（生成，勿手改）", "",
             f"> 主判据 = 长上下文视图 `{PRIMARY_DECODER}` 的 0.2s 命中率，逐歌配对；"
             f"预注册规则见 `docs/status/20260914_concat_arm_prereg.md`。可用存档：{sorted(scores)}；缺失：{missing}。", ""]
    labels = {"treatment_vs_baseline": "B（上采样）vs 线上旧 750 — 主指标",
              "control_vs_baseline": "A（对照）vs 线上旧 750 — 续训漂移",
              "treatment_vs_control_paired": "B vs A — 上采样的**净效应**（判定用这一行）",
              "treatment_vs_reference": "B vs 热启动来源（均匀终点）",
              "control_vs_reference": "A vs 热启动来源（均匀终点）"}
    lines += ["| 比较 | 歌数 | 差(pp) | SE | z | 更好/更差 |", "|---|---|---|---|---|---|"]
    for key, label in labels.items():
        block = payload["comparisons"].get(key) if key != "treatment_vs_control_paired" else direct
        if not block or block.get("status") != "measured":
            lines.append(f"| {label} | — | — | — | — | 未测到（{(block or {}).get('status', 'not_run')}） |")
            continue
        lines.append(f"| {label} | {block['songs']} | {block['mean_delta_pp']:+.2f} | {block['se_pp']:.2f} | "
                     f"{block['z']} | {block['better']}/{block['worse']} |")
    mechanism = payload["mechanism"]
    lines += ["", "## 机制检查（不参与判决，只解释成因）", ""]
    for arm in ("control", "treatment"):
        block = mechanism[arm]
        if block.get("status") == "not_run" or "miss_median_duration_ratio" not in block:
            lines.append(f"- {arm}：未测（跑 `duration_ratio_profile.py` 后重跑本工具）")
        else:
            lines.append(f"- {arm}：{block.get('bucket')} 桶失败子集时长比 "
                         f"{block['miss_median_duration_ratio']}（该桶超差率 "
                         f"{block.get('miss_share')}，n={block.get('characters')}）")
    lines += ["", f"**判决**：主指标 `{payload['verdict']['main_vs_online_baseline']}`；"
             f"净效应 `{payload['verdict']['net_effect_vs_control']}`。", ""]
    (args.out / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
