#!/usr/bin/env python3
"""Detector V2 Phase1-1：product-like anomaly cohort manifest builder（18 §6，禁止全笛卡尔积）。

输入：M4 长数据 timeline（LONG_TIMELINE_MANIFEST.jsonl + 拼接音频），来源 formal_manifest_v3。
每个 cohort 只改变一个主要因素，保留 matched legal baseline（19 §G2：不同 crop/view 不共享 baseline）。

text/audio 分离契约（review C1）：_row 使用独立 text_w0/w1 与 audio_w0/w1 参数。
- crop_late：text 保持原窗 [w0,w1]，audio 平移为 [w0+s, w1+s]（歌词正确只改 crop）；
- crop_early：text 保持原窗 [w0,w1]，audio 平移为 [w0-s, w1-s]；audio_w0<0 物理不可能 → 跳过该档（C2）；
- end_early：text 全长 [w0,w1]，audio 提前截止 [w0, w1-cut]；
- end_late：text 原窗 [w0,w1]，audio 延长 [w0, min(w1+s, duration)]（M10 代表档）；
- cursor_shift：audio 不变 [w0,w1]，text 起点偏移 du units（18 §6C）；
- repeated_section：窗内文本后 1/3 替换为前 1/3（18 §6D synthetic 注入；无 occurrence GT →
  has_gt=false + gt_ambiguity=true，进 18 §5 独立 ambiguity cohort，不冒充有 GT）。

cohort（view_id 区分视图，进 request identity；severity 为档位量值）：
- baseline_legal: 正常 60s 窗（matched baseline，view_id=full|sparse|overlap）
- crop_late / crop_early: 音频 crop 错位（18 §6B）
- end_early（强制主条件）/ end_late: 音频截止错位（18 §6B）
- cursor_shift: 文本起点偏移（18 §6C）
- repeated_section: 重复副歌 synthetic 注入（18 §6D）
- acoustic: 声学困难（18 §6F，先标记位置，声学变换由后续音频处理）
- multiview: 同一 canonical 区 full/sparse/overlap 视图（18 §6G，窗 +2s 重叠切片）

多窗（C4）：--windows-per-song 默认 3，位置 0/50%/100%，剩余 <30s 的窗过滤。
split（C5）：--split-file 可选（SOURCE_SONG_SPLIT.json）；按歌写 train/validation/test，
无 split-file 时写 unassigned 并 warning。test 歌由 manifest 顶层 split 字段供消费者排除。

输出：ANOMALY_MANIFEST.jsonl（每行 REQUESTS 格式，可喂 run_behavior_suite --real）
+ MULTIVIEW_MANIFEST.jsonl（matched views 组）+ FREEZE.json（全部 CLI 参数与档位）。纯 CPU。
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from lyricalign.research_v7.requests import AlignmentRequest

WINDOW_SEC = 60.0
MIN_WINDOW_SEC = 30.0
DEFAULT_CROP_SHIFTS = (0.5, 1.0, 2.0, 4.0, 8.0)
DEFAULT_CROP_EARLY_SHIFTS = (0.5, 1.0, 2.0, 4.0)
DEFAULT_CURSOR_UNITS = (1, 2, 4, 8)
DEFAULT_END_EARLY = (0.5, 1.0, 2.0, 4.0, 8.0)
DEFAULT_END_LATE_SHIFTS = (0.5, 1.0, 2.0, 4.0)
OVERLAP_PAD_SEC = 1.0


def load_timeline(path: Path) -> dict:
    """返回 {song_id: {"row": 原行 dict, "file_sha": 文件级 sha, "row_sha": 本行序列化 sha}}。

    row_sha 口径（M9）：对 timeline 行 json.dumps(row, ensure_ascii=False, sort_keys=True)
    的 sha256——与 M4 builder（build_long_timeline_manifest / mir1k）一致，可逐行复验。
    """
    raw = path.read_bytes()
    rows = [json.loads(l) for l in raw.decode("utf-8").splitlines() if l.strip()]
    file_sha = hashlib.sha256(raw).hexdigest()
    out: dict = {}
    for r in rows:
        row_sha = hashlib.sha256(
            json.dumps(r, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
        out[r["song_id"]] = {"row": r, "file_sha": file_sha, "row_sha": row_sha}
    return out


def load_split(path: Path | None) -> dict:
    """SOURCE_SONG_SPLIT.json → {song: split}；返回空 dict 当无文件。"""
    if path is None:
        return {}
    sf = json.loads(path.read_text(encoding="utf-8"))
    return {song: sp for sp, songs in sf["songs"].items() for song in songs}


def _replace_tail_third(texts: list) -> list:
    """窗内文本后 1/3 替换为前 1/3（重复副歌 synthetic 注入；长度不变）。"""
    n = len(texts)
    third = max(1, n // 3)
    out = list(texts)
    out[-third:] = out[:third]
    return out


def _mutation_type(family: str) -> str:
    if family == "baseline_legal":
        return "baseline"
    if family in ("crop_late", "crop_early"):
        return "crop"
    return family


def _row(tl, song, *, wi, text_w0, text_w1, audio_w0, audio_w1, view, family,
         severity, detail, base_row, text_start=None, text_end=None,
         gt_ambiguity=False):
    """构造一行请求；text 窗决定 canonical units，audio 窗决定取音区间（C1 分离）。"""
    cap = float(tl["row"]["duration_sec"])
    if audio_w1 >= cap:
        audio_w1 = cap - 0.001
    units = tl["row"]["canonical_units"]
    cids: list[int] = []
    texts: list[str] = []
    for u in units:
        st, en = float(u["start_sec"]), float(u["end_sec"])
        if max(st, text_w0) < min(en, text_w1):
            cids.append(int(u["canonical_unit_id"]))
            texts.append(u["text"])
    if len(cids) < 4:
        return None
    if text_start is not None or text_end is not None:
        lo = 0 if text_start is None else max(0, text_start)
        hi = len(texts) if text_end is None else min(len(texts), text_end)
        texts = texts[lo:hi]
        cids = cids[lo:hi]
    if len(texts) < 4:
        return None
    local = {cid: i for i, cid in enumerate(cids)}
    return {
        "schema_version": "research_v7_detector_v2_anomaly_v2",
        "request_type": "detector_v2_anomaly",
        "item_id": f"{song}:{wi}:{family}:{view}",
        "request_id": f"{song}:{wi}:{family}:{severity}:{view}",
        "parent_request_id": base_row["request_id"] if base_row else None,
        "audio_path": base_row["audio_path"] if base_row else None,
        "audio_start_sec": round(audio_w0, 4), "audio_end_sec": round(audio_w1, 4),
        "duration_sec": round(audio_w1 - audio_w0, 4), "audio_source": "m4singer_concat",
        "text_source": "m4singer_meta_v1", "has_gt": not gt_ambiguity,
        "gt_ambiguity": gt_ambiguity,
        "evaluation_role": "lyrics_aligned", "text_window_aligned": True,
        "text_units": texts, "text_start_index": 0, "text_end_index": len(texts),
        "timestamp_slot_indices": list(range(len(cids))),
        "workflow_mode": "detector_v2", "mutation_type": _mutation_type(family),
        "mutation_parameters": {"position": "whole", "family": family, **detail},
        "language": "zh", "dataset": "m4singer",
        "model_id": "Qwen3-ForcedAligner-0.6B-hf", "checkpoint_id": "r2-step-000750",
        "input_variant": "text_mutation",
        "canonical_text_start": cids[0], "canonical_text_end": cids[-1] + 1,
        "canonical_to_local": {str(k): v for k, v in local.items()},
        "canonical_ids": cids,
        "canonical_timeline_file_sha": tl["file_sha"],
        "canonical_timeline_row_sha": tl["row_sha"],
        "canonical_adapter_version": "detector_v2_timeline_v1",
        "source_window_start_sec": round(text_w0, 4),
        "source_window_end_sec": round(text_w1, 4),
        "condition": family, "pair_id": f"{song}:{wi}:{family}",
        "view_id": view, "hidden_schema": None,
        "family": family, "window_index": wi,
        "baseline_request_identity": base_row["baseline_request_identity"]
        if base_row else None,
        "split": base_row["split"] if base_row else None,
    }


def _request_identity(row: dict) -> str:
    """AlignmentRequest 内容 identity（context=最小 ctx=None），用于 matched baseline 追踪（M3）。"""
    req = AlignmentRequest(
        request_id=row["request_id"], item_id=row["item_id"],
        parent_request_id=row.get("parent_request_id"),
        audio_source=row["audio_path"], audio_start_sec=row["audio_start_sec"],
        audio_end_sec=row["audio_end_sec"], text_source=row["text_source"],
        text_start_index=row["text_start_index"], text_end_index=row["text_end_index"],
        text_units=tuple(row["text_units"]),
        timestamp_slot_indices=tuple(row["timestamp_slot_indices"]),
        workflow_mode=row["workflow_mode"], mutation_type=row["mutation_type"],
        mutation_parameters=row["mutation_parameters"], model_id=row["model_id"],
        checkpoint_id=row["checkpoint_id"], input_variant=row["input_variant"],
        canonical_text_start=row["canonical_text_start"],
        canonical_text_end=row["canonical_text_end"],
        canonical_to_local={int(k): int(v) for k, v in (row["canonical_to_local"] or {}).items()},
        canonical_ids=list(row["canonical_ids"]),
        canonical_timeline_file_sha=row["canonical_timeline_file_sha"],
        canonical_timeline_row_sha=row["canonical_timeline_row_sha"],
        canonical_adapter_version=row["canonical_adapter_version"],
        source_window_sec=(row["source_window_start_sec"], row["source_window_end_sec"]),
        view_id=row.get("view_id"), hidden_schema=row.get("hidden_schema"),
        metadata={"evaluation_role": row["evaluation_role"]})
    return req.request_identity()


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--timeline-manifest", required=True)
    p.add_argument("--audio-root", required=True, help="拼接音频目录（含 <song>.wav + .sources.json）")
    p.add_argument("--out-root", required=True)
    p.add_argument("--songs", type=int, default=30)
    p.add_argument("--windows-per-song", type=int, default=3,
                   help="每歌窗数（默认 3：0/50%/100% 位置；剩余 <30s 的窗过滤）")
    p.add_argument("--split-file", default=None,
                   help="SOURCE_SONG_SPLIT.json（可选但推荐）；按歌写 train/validation/test，"
                        "无该文件时写 unassigned 并 warning")
    p.add_argument("--include-acoustic", action="store_true", help="声学 cohort 仅标记位置")
    p.add_argument("--replace-counts", default="",
                   help="逗号分隔的替换 unit 数（1,2,4,8）：窗尾 N 个 canonical units 的 text "
                        "换成同库其他歌 donor 文本（canonical 绑定保留，wrong-output 方向），"
                        "stress cohort 无 occurrence GT（gt_ambiguity=true）")
    p.add_argument("--missing-counts", default="",
                   help="逗号分隔的缺失 unit 数（1,2,4,8）：窗尾 N 个 canonical units 从 "
                        "canonical_ids/text_units 删除（virtual gap 评价方向），"
                        "stress cohort 无 occurrence GT（gt_ambiguity=true）")
    a = p.parse_args(argv)

    tl_path = Path(a.timeline_manifest)
    timelines = load_timeline(tl_path)
    split_map = load_split(Path(a.split_file) if a.split_file else None)
    if a.split_file is None:
        print("WARNING: --split-file not provided; per-song split=unassigned "
              "(test songs cannot be filtered downstream)", file=sys.stderr)

    out = Path(a.out_root)
    out.mkdir(parents=True, exist_ok=True)
    reqs: list[dict] = []
    multiview: list[dict] = []
    audio_root = Path(a.audio_root)
    songs_processed: list[str] = []

    replace_counts = tuple(int(x) for x in a.replace_counts.split(",") if x.strip())
    missing_counts = tuple(int(x) for x in a.missing_counts.split(",") if x.strip())
    # donor 池：同库其他歌的 canonical unit texts（排序后第一个 != 当前歌；池不足 2 首则跳过）
    donor_pool: dict[str, list[str]] = {
        s: [str(u.get("text") or "") for u in (tl["row"].get("canonical_units") or [])]
        for s, tl in list(timelines.items())[: a.songs]}
    donor_song_id: str | None = None
    donor_units: list[str] = []

    for song, tl in list(timelines.items())[: a.songs]:
        if donor_song_id is None:
            for other in sorted(donor_pool):
                if other != song:
                    donor_song_id = other
                    donor_units = donor_pool[other]
                    break
        audio = audio_root / f"{song}.wav"
        if not audio.is_file():
            continue
        split = split_map.get(song, "unassigned")
        duration = float(tl["row"]["duration_sec"])
        n_win = max(1, a.windows_per_song)
        # 窗起点 0/50%/100%（对可用跨度 duration-60，与 M4 builder 同口径）：
        # 保证 early/middle/late 覆盖；剩余 <30s 的窗过滤。
        span = max(0.0, duration - WINDOW_SEC)
        starts = [span * i / max(1, n_win - 1) for i in range(n_win)] if n_win > 1 else [0.0]
        starts = [s for s in starts if s < duration - MIN_WINDOW_SEC]
        for wi, w0 in enumerate(starts):
            w1 = min(w0 + WINDOW_SEC, duration)
            if w1 - w0 < MIN_WINDOW_SEC:
                continue
            base = _row(tl, song, wi=wi, text_w0=w0, text_w1=w1,
                        audio_w0=w0, audio_w1=w1, view="full", family="baseline_legal",
                        severity="legal", detail={}, base_row=None)
            if base is None:
                continue
            base["audio_path"] = str(audio)
            base["split"] = split
            base["baseline_request_identity"] = _request_identity(base)
            reqs.append(base)
            # matched legal baseline 视图（full/sparse/overlap，同一 canonical 区）
            sparse = _row(tl, song, wi=wi, text_w0=w0, text_w1=w1,
                          audio_w0=w0, audio_w1=w1, view="sparse", family="baseline_legal",
                          severity="legal", detail={"slot_density": "sparse"}, base_row=base)
            views = [base["request_id"]]
            if sparse:
                sparse["audio_path"] = str(audio)
                sparse["timestamp_slot_indices"] = list(range(0, len(sparse["text_units"]), 2))
                reqs.append(sparse)
                views.append(sparse["request_id"])
            aw0 = max(0.0, w0 - OVERLAP_PAD_SEC)
            aw1 = min(w1 + OVERLAP_PAD_SEC, duration)
            if aw1 - aw0 >= MIN_WINDOW_SEC:
                ov = _row(tl, song, wi=wi, text_w0=w0, text_w1=w1,
                          audio_w0=aw0, audio_w1=aw1, view="overlap",
                          family="baseline_legal", severity="legal",
                          detail={"overlap_pad_sec": OVERLAP_PAD_SEC}, base_row=base)
                if ov:
                    ov["audio_path"] = str(audio)
                    reqs.append(ov)
                    views.append(ov["request_id"])
            if len(views) >= 2:
                multiview.append({"pair_id": f"{song}:{wi}:baseline_legal",
                                  "window_index": wi, "views": views,
                                  "canonical_ids": base["canonical_ids"]})
            # crop_late：text 原窗，audio 平移后；audio 末端受 duration 封顶（M8），
            # 有效音窗 <30s 丢弃。
            for shift in DEFAULT_CROP_SHIFTS:
                aw0 = w0 + shift
                aw1 = min(w1 + shift, duration)
                if aw0 >= duration or aw1 - aw0 < MIN_WINDOW_SEC:
                    continue
                late = _row(tl, song, wi=wi, text_w0=w0, text_w1=w1,
                            audio_w0=aw0, audio_w1=aw1, view="full", family="crop_late",
                            severity=f"{shift:g}", detail={"shift_sec": shift}, base_row=base)
                if late:
                    late["audio_path"] = str(audio)
                    reqs.append(late)
            # crop_early：text 原窗，audio 平移前；audio_w0<0 物理不可能 → 跳过（C2）。
            for shift in DEFAULT_CROP_EARLY_SHIFTS:
                aw0 = w0 - shift
                if aw0 < 0:
                    continue
                aw1 = w1 - shift
                if aw1 - aw0 < MIN_WINDOW_SEC:
                    continue
                early = _row(tl, song, wi=wi, text_w0=w0, text_w1=w1,
                             audio_w0=aw0, audio_w1=aw1, view="full", family="crop_early",
                             severity=f"{shift:g}", detail={"shift_sec": -shift}, base_row=base)
                if early:
                    early["audio_path"] = str(audio)
                    reqs.append(early)
            # end_early（强制主条件）：text 全长，audio 提前截止。
            for cut in DEFAULT_END_EARLY:
                aw1 = w1 - cut
                if aw1 - w0 < MIN_WINDOW_SEC:
                    continue
                ee = _row(tl, song, wi=wi, text_w0=w0, text_w1=w1,
                          audio_w0=w0, audio_w1=aw1, view="full", family="end_early",
                          severity=f"{cut:g}", detail={"early_sec": cut}, base_row=base)
                if ee:
                    ee["audio_path"] = str(audio)
                    reqs.append(ee)
            # end_late（M10 代表档）：text 原窗，audio 延长。
            for shift in DEFAULT_END_LATE_SHIFTS:
                aw1 = min(w1 + shift, duration)
                if aw1 - w0 < MIN_WINDOW_SEC:
                    continue
                el = _row(tl, song, wi=wi, text_w0=w0, text_w1=w1,
                          audio_w0=w0, audio_w1=aw1, view="full", family="end_late",
                          severity=f"{shift:g}", detail={"late_sec": shift}, base_row=base)
                if el:
                    el["audio_path"] = str(audio)
                    reqs.append(el)
            # cursor_shift（18 §6C）：audio 不变，text 起点偏移 du units。
            for du in DEFAULT_CURSOR_UNITS:
                cs = _row(tl, song, wi=wi, text_w0=w0, text_w1=w1,
                          audio_w0=w0, audio_w1=w1, view="full", family="cursor_shift",
                          severity=f"{du}", detail={"shift_units": du},
                          text_start=du, base_row=base)
                if cs:
                    cs["audio_path"] = str(audio)
                    reqs.append(cs)
            # repeated_section（C3）：窗内文本后 1/3 替换为前 1/3（真实注入，
            # canonical_ids 与 baseline 相同、canonical_to_local 重映射）；
            # 无 occurrence GT → has_gt=false + gt_ambiguity=true，不冒充有 GT。
            rp = _row(tl, song, wi=wi, text_w0=w0, text_w1=w1,
                      audio_w0=w0, audio_w1=w1, view="full", family="repeated_section",
                      severity="repeat",
                      detail={"note": "synthetic: window tail 1/3 text replaced by "
                                      "head 1/3 (no occurrence GT)"},
                      gt_ambiguity=True, base_row=base)
            if rp:
                rp["text_units"] = _replace_tail_third(rp["text_units"])
                rp["audio_path"] = str(audio)
                reqs.append(rp)
            # acoustic：标记位置（声学变换由后续步骤处理）
            if a.include_acoustic:
                ac = _row(tl, song, wi=wi, text_w0=w0, text_w1=w1,
                          audio_w0=w0, audio_w1=w1, view="full", family="acoustic_difficulty",
                          severity="marker",
                          detail={"note": "location marker; transform applied by audio step"},
                          base_row=base)
                if ac:
                    ac["audio_path"] = str(audio)
                    reqs.append(ac)
            # replace stress（18 §13）：窗尾 N 个 units 的 text 换成 donor 文本。
            # canonical_ids/canonical_to_local 保留（wrong-output 方向），无 occurrence GT。
            for n in replace_counts:
                if n >= len(base["text_units"]):
                    continue
                donor_txt = donor_units[:n]
                if len(donor_txt) < n:
                    continue
                rp = _row(tl, song, wi=wi, text_w0=w0, text_w1=w1,
                          audio_w0=w0, audio_w1=w1, view="full", family=f"replace_{n}",
                          severity=str(n),
                          detail={"note": f"tail {n} canonical units text replaced by donor "
                                          "(wrong-output direction, no occurrence GT)",
                                  "replaced_canonical_ids": base["canonical_ids"][-n:]},
                          gt_ambiguity=True, base_row=base)
                if rp:
                    rp["text_units"] = rp["text_units"][:-n] + list(donor_txt)
                    rp["audio_path"] = str(audio)
                    reqs.append(rp)
            # missing stress（18 §13）：窗尾 N 个 units 从 canonical_ids/text_units 删除
            # （virtual gap 评价方向，omitted-original），无 occurrence GT。
            for n in missing_counts:
                if n >= len(base["text_units"]):
                    continue
                ms = _row(tl, song, wi=wi, text_w0=w0, text_w1=w1,
                          audio_w0=w0, audio_w1=w1, view="full", family=f"missing_{n}",
                          severity=str(n),
                          detail={"note": f"tail {n} canonical units omitted "
                                          "(virtual gap direction, no occurrence GT)",
                                  "missing_canonical_ids": base["canonical_ids"][-n:]},
                          gt_ambiguity=True, base_row=base)
                if ms:
                    ms["text_units"] = ms["text_units"][:-n]
                    ms["text_end_index"] = len(ms["text_units"])
                    ms["timestamp_slot_indices"] = list(range(len(ms["text_units"])))
                    if ms.get("canonical_to_local"):
                        ms["canonical_to_local"] = {
                            cid: i for cid, i in ms["canonical_to_local"].items()
                            if int(cid) < int(base["canonical_ids"][-n])}
                    if ms.get("canonical_ids"):
                        ms["canonical_ids"] = [
                            c for c in ms["canonical_ids"]
                            if int(c) < int(base["canonical_ids"][-n])]
                    ms["audio_path"] = str(audio)
                    reqs.append(ms)
        songs_processed.append(song)

    req_sha = hashlib.sha256(b"\n".join(
        json.dumps(r, ensure_ascii=False, sort_keys=True).encode() for r in reqs)).hexdigest()
    (out / "ANOMALY_MANIFEST.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False, sort_keys=True) for r in reqs) + "\n")
    (out / "MULTIVIEW_MANIFEST.jsonl").write_text(
        "\n".join(json.dumps(m, ensure_ascii=False, sort_keys=True) for m in multiview) + "\n")
    ids = [r["request_id"] for r in reqs]
    freeze = {
        "schema": "research_v7_detector_v2_anomaly_manifest_v2",
        "cli": {
            "timeline_manifest": str(tl_path),
            "audio_root": str(audio_root),
            "songs": a.songs,
            "windows_per_song": a.windows_per_song,
            "split_file": a.split_file,
            "include_acoustic": a.include_acoustic,
            "replace_counts": list(replace_counts),
            "missing_counts": list(missing_counts),
            "donor_song_id": donor_song_id,
        },
        "gears": {
            "window_sec": WINDOW_SEC,
            "min_window_sec": MIN_WINDOW_SEC,
            "overlap_pad_sec": OVERLAP_PAD_SEC,
            "crop_late_shifts_sec": list(DEFAULT_CROP_SHIFTS),
            "crop_early_shifts_sec": list(DEFAULT_CROP_EARLY_SHIFTS),
            "end_early_cuts_sec": list(DEFAULT_END_EARLY),
            "end_late_shifts_sec": list(DEFAULT_END_LATE_SHIFTS),
            "cursor_shift_units": list(DEFAULT_CURSOR_UNITS),
        },
        "n_requests": len(reqs),
        "n_multiview_groups": len(multiview),
        "n_songs_processed": len(songs_processed),
        "songs_processed": sorted(songs_processed),
        "request_ids_unique": len(set(ids)) == len(ids),
        "split_counts": dict(collections.Counter(r["split"] for r in reqs)),
        "requests_sha256": req_sha,
    }
    (out / "FREEZE.json").write_text(json.dumps(freeze, ensure_ascii=False, indent=1))
    print(json.dumps({"ok": True, "requests": len(reqs), "multiview": len(multiview),
                      "songs_processed": len(songs_processed),
                      "families": dict(collections.Counter(r["family"] for r in reqs)),
                      "split_counts": freeze["split_counts"],
                      "request_ids_unique": freeze["request_ids_unique"],
                      "out": str(out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
