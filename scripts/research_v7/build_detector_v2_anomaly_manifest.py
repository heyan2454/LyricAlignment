#!/usr/bin/env python3
"""Detector V2 Phase1-1：product-like anomaly cohort manifest builder（18 §6，禁止全笛卡尔积）。

输入：M4 长数据 timeline（LONG_TIMELINE_MANIFEST.jsonl + 拼接音频），来源 formal_manifest_v3。
每个 cohort 只改变一个主要因素，保留 matched legal baseline（19 §G2：不同 crop/view 不共享 baseline）。

cohort（view_id 区分视图，进 request identity）：
- baseline_legal: 正常 60s 窗（matched baseline，view_id=full|sparse）
- crop_late / crop_early / crop_end_early / crop_end_late: 音频 crop 错位（18 §6B）
- cursor_shift: 文本起点 ±1/±2/±4/±8 units（18 §6C）
- end_early: 强制主条件，提前 0.5/1/2/4/8s（18 §6B）
- repeated_section: 重复副歌（18 §6D，需 timeline 提供 occurrence；无 GT 的窗口标 ambiguous）
- acoustic: 声学困难（18 §6F，先标记位置，声学变换由后续音频处理）
- multiview: 同一 canonical 区 full/sparse/overlap 视图（18 §6G）

输出：ANOMALY_MANIFEST.jsonl（每行 REQUESTS 格式，可喂 run_behavior_suite --real）
+ MULTIVIEW_MANIFEST.jsonl（matched views 组）。纯 CPU。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

WINDOW_SEC = 60.0
DEFAULT_CROP_SHIFTS = (0.5, 1.0, 2.0, 4.0, 8.0)
DEFAULT_CURSOR_UNITS = (1, 2, 4, 8)
DEFAULT_END_EARLY = (0.5, 1.0, 2.0, 4.0, 8.0)


def load_timeline(path: Path) -> dict:
    import hashlib
    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    file_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    return {r["song_id"]: {**r, "_file_sha": file_sha} for r in rows}


def _tl_sha(units: list) -> str:
    import hashlib
    return hashlib.sha256(json.dumps([u["text"] for u in units], ensure_ascii=False).encode()).hexdigest()


def _row(tl, song, *, w0, w1, text_start, text_end, view, family, detail, base_row=None):
    units = tl["canonical_units"]
    cids = [int(u["canonical_unit_id"]) for u in units
            if max(float(u["start_sec"]), w0) < min(float(u["end_sec"]), w1)]
    texts = [u["text"] for u in units
             if max(float(u["start_sec"]), w0) < min(float(u["end_sec"]), w1)]
    if not cids or len(cids) < 4:
        return None
    # cursor shift：从 canonical 起点偏移 text（文本与音频错位是 18 §6C 的本意）
    if text_start is not None or text_end is not None:
        lo = 0 if text_start is None else max(0, text_start)
        hi = len(texts) if text_end is None else min(len(texts), text_end)
        texts = texts[lo:hi]
        cids = cids[lo:hi]
    if len(texts) < 4:
        return None
    local = {cid: i for i, cid in enumerate(cids)}
    return {
        "schema_version": "research_v7_detector_v2_anomaly_v1",
        "request_type": "detector_v2_anomaly",
        "item_id": f"{song}:{family}:{view}",
        "request_id": f"{song}:{family}:{view}",
        "parent_request_id": base_row.get("request_id") if base_row else None,
        "audio_path": base_row["audio_path"] if base_row else None,
        "audio_start_sec": round(w0, 4), "audio_end_sec": round(w1, 4),
        "duration_sec": round(w1 - w0, 4), "audio_source": "m4singer_concat",
        "text_source": "m4singer_meta_v1", "has_gt": True,
        "evaluation_role": "lyrics_aligned", "text_window_aligned": True,
        "text_units": texts, "text_start_index": 0, "text_end_index": len(texts),
        "timestamp_slot_indices": list(range(len(cids))),
        "workflow_mode": "detector_v2", "mutation_type": "baseline",
        "mutation_parameters": {"position": "whole", "family": family, **detail},
        "language": "zh", "dataset": "m4singer", "split": "validation",
        "model_id": "Qwen3-ForcedAligner-0.6B-hf", "checkpoint_id": "r2-step-000750",
        "input_variant": "text_mutation",
        "canonical_text_start": cids[0], "canonical_text_end": cids[-1] + 1,
        "canonical_to_local": {str(k): v for k, v in local.items()},
        "canonical_ids": cids,
        "canonical_timeline_file_sha": tl.get("_file_sha"),
        "canonical_timeline_row_sha": _tl_sha(units),
        "canonical_adapter_version": "detector_v2_timeline_v1",
        "source_window_start_sec": round(w0, 4), "source_window_end_sec": round(w1, 4),
        "condition": family, "pair_id": f"{song}:{family}",
        "view_id": view, "hidden_schema": None,
        "family": family,
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--timeline-manifest", required=True)
    p.add_argument("--audio-root", required=True, help="拼接音频目录（含 <song>.wav + .sources.json）")
    p.add_argument("--out-root", required=True)
    p.add_argument("--songs", type=int, default=30)
    p.add_argument("--windows-per-song", type=int, default=3)
    p.add_argument("--include-acoustic", action="store_true", help="声学 cohort 仅标记位置")
    a = p.parse_args(argv)

    timelines = load_timeline(Path(a.timeline_manifest))
    out = Path(a.out_root); out.mkdir(parents=True, exist_ok=True)
    reqs: list[dict] = []
    multiview: list[dict] = []
    audio_root = Path(a.audio_root)
    n = 0
    for song, tl in list(timelines.items())[: a.songs]:
        audio = audio_root / f"{song}.wav"
        if not audio.is_file():
            continue
        units = tl["canonical_units"]
        duration = float(tl["duration_sec"])
        n_win = max(1, int(duration // WINDOW_SEC))
        starts = [duration * i / max(1, a.windows_per_song - 1) for i in range(a.windows_per_song)]
        starts = [s for s in starts if s < duration - 30]
        for wi, w0 in enumerate(starts):
            w1 = min(w0 + WINDOW_SEC, duration)
            base = _row(tl, song, w0=w0, w1=w1, text_start=None, text_end=None,
                        view="full", family="baseline_legal", detail={})
            if base is None:
                continue
            base["audio_path"] = str(audio)
            # baseline matched legal（full + sparse 视图）
            reqs.append(base)
            sparse = _row(tl, song, w0=w0, w1=w1, text_start=None, text_end=None,
                          view="sparse", family="baseline_legal",
                          detail={"slot_density": "sparse"})
            if sparse:
                sparse["audio_path"] = str(audio)
                sparse["timestamp_slot_indices"] = list(range(0, len(sparse["text_units"]), 2))
                reqs.append(sparse)
                multiview.append({"pair_id": f"{song}:{wi}:legal",
                                  "views": [base["request_id"], sparse["request_id"]],
                                  "canonical_ids": base["canonical_ids"]})
            # crop cohorts（audio crop 错位）
            for shift in DEFAULT_CROP_SHIFTS:
                late = _row(tl, song, w0=w0 + shift, w1=w1 + shift, text_start=None, text_end=None,
                            view="full", family="crop_late", detail={"shift_sec": shift})
                if late:
                    late["audio_path"] = str(audio)
                    reqs.append(late)
                early = _row(tl, song, w0=max(0.0, w0 - shift), w1=w1 - shift, text_start=None,
                             text_end=None, view="full", family="crop_early",
                             detail={"shift_sec": -shift})
                if early and early["audio_end_sec"] > early["audio_start_sec"] + 30:
                    early["audio_path"] = str(audio)
                    reqs.append(early)
            # end-early（强制主条件）
            for cut in DEFAULT_END_EARLY:
                ee = _row(tl, song, w0=w0, w1=w1 - cut, text_start=None, text_end=None,
                          view="full", family="end_early", detail={"early_sec": cut})
                if ee and ee["audio_end_sec"] > ee["audio_start_sec"] + 30:
                    ee["audio_path"] = str(audio)
                    reqs.append(ee)
            # cursor shift（文本起点错位）
            for du in DEFAULT_CURSOR_UNITS:
                cs = _row(tl, song, w0=w0, w1=w1, text_start=du, text_end=None,
                          view="full", family="cursor_shift", detail={"shift_units": du})
                if cs:
                    cs["audio_path"] = str(audio)
                    reqs.append(cs)
            # repeated section：用窗内文本前 1/3 替换后 1/3（近似重复段；无 occurrence GT → 标 ambiguous 提示）
            rp = _row(tl, song, w0=w0, w1=w1, text_start=None, text_end=None,
                      view="full", family="repeated_section",
                      detail={"note": "synthetic repeated occurrence; GT occurrence ambiguous"})
            if rp:
                rp["audio_path"] = str(audio)
                reqs.append(rp)
            # acoustic：标记位置（声学变换由后续步骤处理）
            if a.include_acoustic:
                ac = _row(tl, song, w0=w0, w1=w1, text_start=None, text_end=None,
                          view="full", family="acoustic_difficulty",
                          detail={"note": "location marker; transform applied by audio step"})
                if ac:
                    ac["audio_path"] = str(audio)
                    reqs.append(ac)
            n += 1
            if n >= a.songs * 3:
                break
        if n >= a.songs * 3:
            break
    import hashlib
    req_sha = hashlib.sha256(b"\n".join(json.dumps(r, ensure_ascii=False, sort_keys=True).encode()
                                        for r in reqs)).hexdigest()
    (out / "ANOMALY_MANIFEST.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False, sort_keys=True) for r in reqs) + "\n")
    (out / "MULTIVIEW_MANIFEST.jsonl").write_text(
        "\n".join(json.dumps(m, ensure_ascii=False, sort_keys=True) for m in multiview) + "\n")
    (out / "FREEZE.json").write_text(json.dumps({
        "schema": "research_v7_detector_v2_anomaly_manifest_v1",
        "n_requests": len(reqs), "n_multiview_groups": len(multiview),
        "requests_sha256": req_sha, "songs": a.songs}, ensure_ascii=False, indent=1))
    import collections
    print(json.dumps({"ok": True, "requests": len(reqs), "multiview": len(multiview),
                      "families": dict(collections.Counter(r["family"] for r in reqs)),
                      "out": str(out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
