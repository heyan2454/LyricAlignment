#!/usr/bin/env python3
"""Detector V2 M4→MIR 跨域：MIR-1K anomaly cohort manifest builder（18 §13 / 21 §1）。

MIR 资产复用评估（18 §13）：M4 anomaly builder 的 cohort/窗/severity/matched-baseline
合同可直接复用（同一 canonical 区、一窗一 baseline + 多 cohort 变体、view_id 区分视图、
baseline_request_identity 内容寻址）；不可复用的仅有两处：
  1. M4 timeline 行自带 duration_sec，MIR timeline 行（MIR_TIMELINE_MANIFEST.jsonl）
     没有 → 时长改由音频文件实测（soundfile）/ --duration-map 覆盖；
  2. _row 内硬编码 M4 元数据（m4singer_concat / m4singer_meta_v1 / split=unassigned）
     → 本 builder 用 MIR 元数据重写行构造，其余逻辑原样调用 M4 builder 的共享函数
     （load_timeline / 档位常量 / _replace_tail_third / _mutation_type）。

MIR 弱标签（validation_basis=null，非人工 GT，21 §1）单列：has_gt=true（弱轴评价）
但 gt_validation_basis=null + weak_label_source=mir1k_qwen_fa_labels_v1，不进入 M4
精确 GT 混合；split 统一标 "mir1k"，下游与 M4（train/validation/test）区分。

cohort（与 M4 anomaly builder 同档位）：
- baseline_legal（matched baseline，view_id=full|sparse|overlap）
- crop_late / crop_early（audio 平移，text 原窗；audio_w0<0 档跳过 C2）
- end_early（强制主条件；audio 提前截止）
- cursor_shift（audio 不变，text 起点偏移 du units）
- repeated_section（synthetic 尾部 1/3 替换；has_gt=false + gt_ambiguity=true）
- acoustic（--include-acoustic 时仅标记位置）

输入：--timeline-manifest（MIR_TIMELINE_MANIFEST.jsonl，build_mir1k_long_manifest
产物，canonical_units=逐字符弱标签时间轴）+ --audio-root（vocal_wavs/*.wav 原生
文件，非拼接）。输出：MIR_ANOMALY_MANIFEST.jsonl + MULTIVIEW_MANIFEST.jsonl +
FREEZE.json（含逐行 AlignmentRequest.validate 结果与 audio 边界核对）。纯 CPU。
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_detector_v2_anomaly_manifest as m4b  # noqa: E402
from lyricalign.research_v7.requests import AlignmentRequest  # noqa: E402

WINDOW_SEC = m4b.WINDOW_SEC
MIN_WINDOW_SEC = m4b.MIN_WINDOW_SEC
OVERLAP_PAD_SEC = m4b.OVERLAP_PAD_SEC
SCHEMA_VERSION = "research_v7_detector_v2_anomaly_mir_v1"
AUDIO_SOURCE = "mir1k_vocal_channel1_ood"
TEXT_SOURCE = "mir1k_qwen_fa_labels_v1"
ADAPTER_VERSION = "mir1k_weak_labels_v1"
DEFAULT_AUDIO_ROOT = "/home/hyan/Data/lyricalign/derived/20260722_mir1k_vocal_channel1_ood"


def _resolve_audio_path(audio_root: Path, song_id: str) -> Path:
    """vocal_wavs/*.wav 原生文件解析；song_id 可能已含 .wav 后缀。"""
    for cand in (audio_root / "vocal_wavs" / song_id,
                 audio_root / song_id,
                 audio_root / "vocal_wavs" / f"{song_id}.wav",
                 audio_root / f"{song_id}.wav"):
        if cand.is_file():
            return cand
    return audio_root / "vocal_wavs" / song_id


def _resolve_duration(song_id: str, audio: Path, duration_map: dict,
                      unit_end: float) -> float:
    """时长优先级：--duration-map > soundfile 实测 > 末单位 end 兜底。"""
    if song_id in duration_map:
        return float(duration_map[song_id])
    try:
        import soundfile as sf
        info = sf.info(str(audio))
        return float(info.frames) / float(info.samplerate)
    except Exception:
        return unit_end + 0.5


def _row_mir(tl: dict, duration: float, song: str, *, wi, text_w0, text_w1,
             audio_w0, audio_w1, view, family, severity, detail, base_row,
             text_start=None, text_end=None, gt_ambiguity=False):
    """构造一行请求；text 窗决定 canonical units，audio 窗决定取音区间（C1 分离）。

    行结构对齐 M4 anomaly builder 的 _row（同一 schema 族），仅 MIR 元数据不同：
    audio_source/text_source/dataset/split/gt_validation_basis/weak_label_source。
    """
    cap = duration
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
        "schema_version": SCHEMA_VERSION,
        "request_type": "detector_v2_anomaly",
        "item_id": f"{song}:{wi}:{family}:{view}",
        "request_id": f"{song}:{wi}:{family}:{severity}:{view}",
        "parent_request_id": base_row["request_id"] if base_row else None,
        "audio_path": base_row["audio_path"] if base_row else None,
        "audio_start_sec": round(audio_w0, 4), "audio_end_sec": round(audio_w1, 4),
        "duration_sec": round(audio_w1 - audio_w0, 4),
        "audio_source": AUDIO_SOURCE,
        "text_source": TEXT_SOURCE,
        "has_gt": not gt_ambiguity,
        "gt_ambiguity": gt_ambiguity,
        "gt_validation_basis": None,
        "weak_label_source": TEXT_SOURCE,
        "evaluation_role": "lyrics_aligned", "text_window_aligned": True,
        "text_units": texts, "text_start_index": 0, "text_end_index": len(texts),
        "timestamp_slot_indices": list(range(len(cids))),
        "workflow_mode": "detector_v2", "mutation_type": m4b._mutation_type(family),
        "mutation_parameters": {"position": "whole", "family": family, **detail},
        "language": "zh", "dataset": "mir1k", "split": "mir1k",
        "model_id": "Qwen3-ForcedAligner-0.6B-hf",
        "checkpoint_id": "r2-step-000750",
        "input_variant": "text_mutation",
        "canonical_text_start": cids[0], "canonical_text_end": cids[-1] + 1,
        "canonical_to_local": {str(k): v for k, v in local.items()},
        "canonical_ids": cids,
        "canonical_timeline_file_sha": tl["file_sha"],
        "canonical_timeline_row_sha": tl["row_sha"],
        "canonical_adapter_version": ADAPTER_VERSION,
        "source_window_start_sec": round(text_w0, 4),
        "source_window_end_sec": round(text_w1, 4),
        "condition": family, "pair_id": f"{song}:{wi}:{family}",
        "view_id": view, "hidden_schema": None,
        "family": family, "window_index": wi,
        "baseline_request_identity": base_row["baseline_request_identity"]
        if base_row else None,
        "split": "mir1k",
    }


def _to_alignment_request(row: dict) -> AlignmentRequest:
    """row → AlignmentRequest（字段映射与 M4 _request_identity 同口径）。"""
    return AlignmentRequest(
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


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--timeline-manifest", required=True,
                   help="MIR_TIMELINE_MANIFEST.jsonl（build_mir1k_long_manifest 产物）")
    p.add_argument("--audio-root", default=DEFAULT_AUDIO_ROOT,
                   help="vocal_wavs/*.wav 根目录（原生文件，非拼接）")
    p.add_argument("--out-root", required=True)
    p.add_argument("--songs", type=int, default=17)
    p.add_argument("--windows-per-song", type=int, default=3,
                   help="每歌窗数（默认 3：0/50%/100% 位置；剩余 <30s 的窗过滤）")
    p.add_argument("--duration-map", default=None,
                   help="可选 {song_id: duration_sec} json；缺省用 soundfile 实测，"
                        "实测失败时用末单位 end+0.5 兜底")
    p.add_argument("--include-acoustic", action="store_true")
    a = p.parse_args(argv)

    tl_path = Path(a.timeline_manifest)
    timelines = m4b.load_timeline(tl_path)
    duration_map = json.loads(Path(a.duration_map).read_text(encoding="utf-8")) \
        if a.duration_map else {}
    audio_root = Path(a.audio_root)
    out = Path(a.out_root)
    out.mkdir(parents=True, exist_ok=True)

    reqs: list[dict] = []
    multiview: list[dict] = []
    songs_processed: list[str] = []
    song_durations: dict[str, float] = {}
    n_skipped_no_audio = 0

    for song, tl in list(timelines.items())[: a.songs]:
        audio = _resolve_audio_path(audio_root, song)
        if not audio.is_file():
            n_skipped_no_audio += 1
            continue
        units = tl["row"]["canonical_units"]
        unit_end = max(float(u["end_sec"]) for u in units)
        duration = _resolve_duration(song, audio, duration_map, unit_end)
        song_durations[song] = duration
        n_win = max(1, a.windows_per_song)
        span = max(0.0, duration - WINDOW_SEC)
        starts = [span * i / max(1, n_win - 1) for i in range(n_win)] if n_win > 1 else [0.0]
        starts = [s for s in starts if s < duration - MIN_WINDOW_SEC]
        for wi, w0 in enumerate(starts):
            w1 = min(w0 + WINDOW_SEC, duration)
            if w1 - w0 < MIN_WINDOW_SEC:
                continue
            base = _row_mir(tl, duration, song, wi=wi, text_w0=w0, text_w1=w1,
                            audio_w0=w0, audio_w1=w1, view="full",
                            family="baseline_legal", severity="legal", detail={},
                            base_row=None)
            if base is None:
                continue
            base["audio_path"] = str(audio)
            base["baseline_request_identity"] = _to_alignment_request(base).request_identity()
            reqs.append(base)
            sparse = _row_mir(tl, duration, song, wi=wi, text_w0=w0, text_w1=w1,
                              audio_w0=w0, audio_w1=w1, view="sparse",
                              family="baseline_legal", severity="legal",
                              detail={"slot_density": "sparse"}, base_row=base)
            views = [base["request_id"]]
            if sparse:
                sparse["audio_path"] = str(audio)
                sparse["timestamp_slot_indices"] = list(range(0, len(sparse["text_units"]), 2))
                reqs.append(sparse)
                views.append(sparse["request_id"])
            aw0 = max(0.0, w0 - OVERLAP_PAD_SEC)
            aw1 = min(w1 + OVERLAP_PAD_SEC, duration)
            if aw1 - aw0 >= MIN_WINDOW_SEC:
                ov = _row_mir(tl, duration, song, wi=wi, text_w0=w0, text_w1=w1,
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
            for shift in m4b.DEFAULT_CROP_SHIFTS:
                aw0 = w0 + shift
                aw1 = min(w1 + shift, duration)
                if aw0 >= duration or aw1 - aw0 < MIN_WINDOW_SEC:
                    continue
                late = _row_mir(tl, duration, song, wi=wi, text_w0=w0, text_w1=w1,
                                audio_w0=aw0, audio_w1=aw1, view="full",
                                family="crop_late", severity=f"{shift:g}",
                                detail={"shift_sec": shift}, base_row=base)
                if late:
                    late["audio_path"] = str(audio)
                    reqs.append(late)
            for shift in m4b.DEFAULT_CROP_EARLY_SHIFTS:
                aw0 = w0 - shift
                if aw0 < 0:
                    continue
                aw1 = w1 - shift
                if aw1 - aw0 < MIN_WINDOW_SEC:
                    continue
                early = _row_mir(tl, duration, song, wi=wi, text_w0=w0, text_w1=w1,
                                 audio_w0=aw0, audio_w1=aw1, view="full",
                                 family="crop_early", severity=f"{shift:g}",
                                 detail={"shift_sec": -shift}, base_row=base)
                if early:
                    early["audio_path"] = str(audio)
                    reqs.append(early)
            for cut in m4b.DEFAULT_END_EARLY:
                aw1 = w1 - cut
                if aw1 - w0 < MIN_WINDOW_SEC:
                    continue
                ee = _row_mir(tl, duration, song, wi=wi, text_w0=w0, text_w1=w1,
                              audio_w0=w0, audio_w1=aw1, view="full",
                              family="end_early", severity=f"{cut:g}",
                              detail={"early_sec": cut}, base_row=base)
                if ee:
                    ee["audio_path"] = str(audio)
                    reqs.append(ee)
            for du in m4b.DEFAULT_CURSOR_UNITS:
                cs = _row_mir(tl, duration, song, wi=wi, text_w0=w0, text_w1=w1,
                              audio_w0=w0, audio_w1=w1, view="full",
                              family="cursor_shift", severity=f"{du}",
                              detail={"shift_units": du}, text_start=du, base_row=base)
                if cs:
                    cs["audio_path"] = str(audio)
                    reqs.append(cs)
            rp = _row_mir(tl, duration, song, wi=wi, text_w0=w0, text_w1=w1,
                          audio_w0=w0, audio_w1=w1, view="full",
                          family="repeated_section", severity="repeat",
                          detail={"note": "synthetic: window tail 1/3 text replaced by "
                                          "head 1/3 (no occurrence GT)"},
                          gt_ambiguity=True, base_row=base)
            if rp:
                rp["text_units"] = m4b._replace_tail_third(rp["text_units"])
                rp["audio_path"] = str(audio)
                reqs.append(rp)
            if a.include_acoustic:
                ac = _row_mir(tl, duration, song, wi=wi, text_w0=w0, text_w1=w1,
                              audio_w0=w0, audio_w1=w1, view="full",
                              family="acoustic_difficulty", severity="marker",
                              detail={"note": "location marker; transform applied by audio step"},
                              base_row=base)
                if ac:
                    ac["audio_path"] = str(audio)
                    reqs.append(ac)
        songs_processed.append(song)

    ids = [r["request_id"] for r in reqs]
    unique = len(set(ids)) == len(ids)
    # validate：逐行 AlignmentRequest.validate + audio 边界不超时长（纯 CPU）
    validate_ok = unique
    for r in reqs:
        song = r["request_id"].split(":")[0]
        dur = song_durations[song]
        try:
            _to_alignment_request(r).validate(
                total_units=len(timelines[song]["row"]["canonical_units"]),
                duration_sec=dur)
        except Exception:
            validate_ok = False
            break
        if r["audio_start_sec"] < -1e-6 or r["audio_end_sec"] > dur + 1e-6:
            validate_ok = False
            break

    req_sha = hashlib.sha256(b"\n".join(
        json.dumps(r, ensure_ascii=False, sort_keys=True).encode() for r in reqs)).hexdigest()
    (out / "MIR_ANOMALY_MANIFEST.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False, sort_keys=True) for r in reqs) + "\n")
    (out / "MULTIVIEW_MANIFEST.jsonl").write_text(
        "\n".join(json.dumps(m, ensure_ascii=False, sort_keys=True) for m in multiview) + "\n")
    freeze = {
        "schema": "research_v7_detector_v2_mir_anomaly_manifest_v1",
        "cli": {"timeline_manifest": str(tl_path), "audio_root": str(audio_root),
                "songs": a.songs, "windows_per_song": a.windows_per_song,
                "duration_map": a.duration_map, "include_acoustic": a.include_acoustic},
        "gears": {
            "window_sec": WINDOW_SEC, "min_window_sec": MIN_WINDOW_SEC,
            "overlap_pad_sec": OVERLAP_PAD_SEC,
            "crop_late_shifts_sec": list(m4b.DEFAULT_CROP_SHIFTS),
            "crop_early_shifts_sec": list(m4b.DEFAULT_CROP_EARLY_SHIFTS),
            "end_early_cuts_sec": list(m4b.DEFAULT_END_EARLY),
            "cursor_shift_units": list(m4b.DEFAULT_CURSOR_UNITS),
        },
        "weak_label_note": "MIR GT 为 qwen_fa 弱监督标签（validation_basis=null），"
                           "单列不进入 M4 精确 GT 混合（21 §1）",
        "n_requests": len(reqs), "n_multiview_groups": len(multiview),
        "n_songs_processed": len(songs_processed),
        "n_skipped_no_audio": n_skipped_no_audio,
        "songs_processed": sorted(songs_processed),
        "request_ids_unique": unique,
        "validate_ok": validate_ok,
        "split_counts": dict(collections.Counter(r["split"] for r in reqs)),
        "families": dict(collections.Counter(r["family"] for r in reqs)),
        "requests_sha256": req_sha,
    }
    (out / "FREEZE.json").write_text(json.dumps(freeze, ensure_ascii=False, indent=1))
    print(json.dumps({"ok": True, "requests": len(reqs), "multiview": len(multiview),
                      "songs_processed": len(songs_processed),
                      "families": freeze["families"],
                      "request_ids_unique": unique, "validate_ok": validate_ok,
                      "out": str(out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
