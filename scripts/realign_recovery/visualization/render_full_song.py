#!/usr/bin/env python3
"""V2.1 — full-song segmented B4-vs-Current + 机制 overlay renderer.

严格遵循 03 实验设计的 B4 vs Current 全曲双路可视化：
  * 「B4」lane = 真 pre-slot serial 逐字对齐 —— 由
    ``scripts/demo/align_qwen_fa_serial_demo.py`` 按 03 V1/02 B4 冻结配置产出
    (official, core/left/right=60/10/10, silence-aware, skip-silent)。
  * 「Current 全曲」lane = full-slot windowed 对齐。
  两者时间轴共用整歌时长，任意条 ``--baseline-align LABEL=path[,geom]`` 叠加。

修复可视化质量(用户 2026-08-14 反馈)：
  1. 全曲时长 —— timeline = 整歌逐字对齐，按真实时间分页(默认 15s/page, 更高 px/s)。
  2. 看得清 —— video page 233px/s(15s/页)字宽翻倍；full-timeline 160px/s
     (clamp 12k-64k 超宽长图)每个字有横向空间不再省略。
  3. 过去 baseline 对比 —— 真 B4(pre-slot serial) vs 当前(不 alias 成
     full-slot batch 的 raw 解码——上一版标注错误，本版用真 B4 语义)。

数据来源于冻结/串行对齐产物，不触发多余 forward；GT firewall(evaluator-only)。
所有 run 产物写数据盘，不进 git。

Usage:
  PYTHONPATH=src python scripts/realign_recovery/visualization/render_full_song.py \
      --baseline-align "B4 历史串行=<B4_r2/vocal/windowed/alignment.json>" \
      --baseline-align "Current 全曲=<full_slot_align.json>" \
      --item "Japanese/乙女解剖.mp3" --audio <mix.wav> --out <run>
      [--page-seconds 15] [--forward-root ...] ...
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from visualization_controller import (
    build_karaoke_alignment,
    build_track_from_evidence,
    evidence_payloads_for_family,
    load_evidence_index,
    load_plan,
    render_static_group,
    render_video,
    window_trace_from_request,
    write_analysis_complete,
    write_collection,
    write_render_manifest,
)
from lyricalign.demo import track_view as tv  # reuse projection contract


def load_fullsong_alignment(path: Path) -> dict:
    """Load a ``r2_vocal_windowed`` / ``r2_raw_guarded`` alignment.json."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or "characters" not in payload:
        raise ValueError(f"{path} is not a full-song alignment.json (no characters)")
    return payload


def characters_to_rows(alignment: dict, *, geom: str = "selected") -> list[dict]:
    """Project alignment.json ``characters`` to track_view visual rows.

    Each char -> one row with ``global_character_index``, ``display_text``,
    ``start_sec/end_sec`` from the requested geometry (default ``selected``;
    alternatives: ``raw`` -> raw_global_*, ``official`` -> official_global_*,
    ``fixed`` -> fixed_global_*).
    """
    def g(c, k):
        if geom == "selected":
            return c.get("selected_start_sec") or c.get("start_sec"), \
                   c.get("selected_end_sec") or c.get("end_sec")
        return c.get(f"{geom}_global_start_sec") or (c.get("start_sec") if k == 0 else c.get("end_sec")), \
               c.get(f"{geom}_global_end_sec") or (c.get("start_sec") if k == 0 else c.get("end_sec"))
    rows: list[dict] = []
    for c in alignment.get("characters", []):
        s, e = g(c, 0)
        if s is None or e is None:
            continue
        rows.append({
            "canonical_unit_id": c.get("global_character_index"),
            "global_character_index": c.get("global_character_index"),
            "display_text": str(c.get("display_text") or c.get("character") or "·"),
            "start_sec": float(s),
            "end_sec": float(e),
        })
    rows.sort(key=lambda r: (float(r["start_sec"]), r["global_character_index"] or 0))
    return rows


def build_fullsong_track(alignment: dict, label: str, geom: str = "selected") -> dict:
    """Full-song lane from a full-song alignment (one geometry)."""
    rows = characters_to_rows(alignment, geom=geom)
    return {
        "schema": "track_view_v1",
        "label": label,
        "rows": rows,
        "window_trace": list(alignment.get("window_trace") or []),
        "metadata": {"family": "full_song", "geometry": geom},
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="V2.1 full-song segmented render")
    ap.add_argument("--baseline-align", action="append", default=[],
                    help="LABEL=path[,geom] of a full-song alignment.json to use as a full-song "
                         "baseline lane (repeatable; geom defaults to 'selected').  "
                         "Equivalent single-lane shortcut also accepted as --fullsong-align")
    ap.add_argument("--fullsong-align", type=Path, default=None,
                    help="compat single-lane: same as --baseline-align 'Current (全曲)=<path>'")
    ap.add_argument("--fullsong-geom", default="selected",
                    help="geometry for the --fullsong-align lane (selected|raw|official|fixed)")
    ap.add_argument("--forward-root", required=False, type=Path, default=None)
    ap.add_argument("--plan", required=False, type=Path, default=None)
    ap.add_argument("--item", required=True,
                    help="item label, e.g. 'Japanese/乙女解剖.mp3'")
    ap.add_argument("--audio", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--page-seconds", type=float, default=15.0,
                    help="seconds per video page; smaller = 更高px-per-sec = 更清晰(默认15)")
    ap.add_argument("--font", default="Noto Sans CJK SC")
    ap.add_argument("--fourth-family", default=None)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    # ---- full-song baseline lanes ----
    baseline_specs: list[tuple[str, Path, str]] = []
    if args.fullsong_align is not None:
        baseline_specs.append(("Current (全曲)", args.fullsong_align, args.fullsong_geom))
    for spec in args.baseline_align:
        if "=" not in spec:
            raise SystemExit(f"--baseline-align needs LABEL=path[,geom], got {spec!r}")
        label, _, rest = spec.partition("=")
        path, _, geom = rest.partition(",")
        baseline_specs.append((label, Path(path), geom or "selected"))
    if not baseline_specs:
        raise SystemExit("need at least one full-song baseline lane (--baseline-align or --fullsong-align)")

    alignments = [load_fullsong_alignment(path) for _, path, _ in baseline_specs]
    audio_dur = float((alignments[0].get("summary") or {}).get("audio_duration_sec")
                      or max((c.get("selected_end_sec") or c.get("end_sec") or 0)
                             for c in alignments[0]["characters"]))
    start = 0.0
    end = max(audio_dur, start + 0.5)
    tracks = [build_fullsong_track(a, label, geom)
              for (label, _path, geom), a in zip(baseline_specs, alignments)]

    # ---- mechanism overlay tracks (窗口局部, 可选) ----
    if args.forward_root is not None:
        plan = load_plan(args.plan)
        item_reqs = [r for r in plan if r.get("item") == args.item]
        request_ids = [str(r["request_id"]) for r in item_reqs]
        evidence_index = load_evidence_index(args.forward_root / "evidence")
        for fam in ("R-U", "R-S"):
            # Robust match by item + proposal_method (plan request_ids often only
            # carry the executed R-U variant; R-S payloads live under item-scope).
            payloads = [
                p for p in evidence_index.values()
                if ((p.get("attempt") or {}).get("request") or {}).get("item_id") == args.item
                and ((p.get("attempt") or {}).get("request") or {}).get("mutation_parameters", {})
                .get("proposal_method") == fam
            ]
            if not payloads:
                continue
            traces = []
            for p in payloads:
                rq = (p.get("attempt") or {}).get("request") or {}
                traces.append(window_trace_from_request(rq))
            tracks.append(build_track_from_evidence(
                payloads, label=fam, decoder_kind="official",
                window_trace=traces, metadata={"family": fam},
            ))
        if args.fourth_family:
            f4 = [p for p in evidence_index.values()
                  if ((p.get("attempt") or {}).get("request") or {}).get("item_id") == args.item
                  and ((p.get("attempt") or {}).get("request") or {}).get("mutation_parameters", {})
                  .get("proposal_method") == args.fourth_family]
            if f4:
                f4_traces = []
                for p in f4:
                    rq = (p.get("attempt") or {}).get("request") or {}
                    f4_traces.append(window_trace_from_request(rq))
                tracks.append(build_track_from_evidence(
                    f4, label=args.fourth_family, decoder_kind="official",
                    window_trace=f4_traces, metadata={"family": args.fourth_family},
                ))
            else:
                raise SystemExit(f"--fourth-family {args.fourth_family!r} but no evidence has proposal_method==it")

    # windows for overlay (union across mechanism tracks)
    seen = set()
    windows = []
    for t in tracks:
        for w in (t.get("window_trace") or []):
            key = (w.get("core_start_sec"), w.get("core_end_sec"))
            if key in seen:
                continue
            seen.add(key)
            windows.append(w)

    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    if args.forward_root is not None:
        write_collection(out, plan, items=[args.item])
    n_reqs = len(item_reqs) if args.forward_root is not None else 0
    write_analysis_complete(out, n_items=1, n_requests=n_reqs,
                            resources={"item": args.item, "full_song_audio_sec": end})

    group_meta = render_static_group(
        out, group="current_full_song", tracks=tracks, windows=windows,
        start=start, end=end,
        title="全曲 Current vs 机制 — %s" % Path(args.item).name,
        font=args.font, video_layout=True, page_seconds=args.page_seconds,
    )
    rows = tracks[0].get("rows") or []
    alignment_ktv = build_karaoke_alignment(rows, duration_sec=end - start)
    video_meta = render_video(
        out, group="current_full_song", pages_meta=group_meta["pages"],
        alignment=alignment_ktv, audio_track=args.audio, title="全曲 Current vs 机制",
        font=args.font, force=args.force,
    )
    write_render_manifest(out, visual_groups=[group_meta], videos=[video_meta])
    summary = {
        "runner": "render_full_song.py",
        "item": args.item, "full_song_sec": [start, end],
        "n_characters": len(alignments[0].get("characters", [])),
        "tracks": [t["label"] for t in tracks],
        "pages": len(group_meta["pages"]),
        "video": video_meta,
        "full_timeline": group_meta["full_timeline"],
    }
    (out / "current_full_song_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "ok": True,
        "item": args.item,
        "full_song_sec": [start, round(end, 2)],
        "n_characters": len(alignments[0].get("characters", [])),
        "tracks": [t["label"] for t in tracks],
        "pages": len(group_meta["pages"]),
        "full_timeline": group_meta["full_timeline"],
        "video": video_meta.get("path"),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
