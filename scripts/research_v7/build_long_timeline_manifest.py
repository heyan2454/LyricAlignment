#!/usr/bin/env python3
"""review12 C3/A1：formal long-timeline manifest builder（真实长数据 + fixed-60s 请求）。

formal 契约（13/14）：主体 ≥180s（同歌同歌手按元数据顺序拼接，禁人工静音凑长数据）、
主模型请求 fixed 60s、baseline 按完整 request identity 配对、每窗携带 canonical lineage
（canonical_ids/canonical_to_local/canonical range/timeline SHA/source window）、
role=lyrics_aligned + text_window_aligned=true——保证 guard/collect/assessor 链路不空转。

slot 密度（13 §S2）：--density-strides 控制档位（full=连续全量、strided2/4=等距取样），
stride 档按窗位轮换 phase 起点（offset=window_index % step），每档独立 slot plan
（slot_planning.build_density_plans 求全档 common anchors），request_id 后缀=档位名
（:full/:s2/:s4）——汇总/评价只对共同 queried 单位公平比较。

用法：
  PYTHONPATH=src python scripts/research_v7/build_long_timeline_manifest.py \
      --m4-manifest <m4singer_meta_v1/m4singer_manifest.jsonl> \
      --out-root <run>/formal_manifest \
      --min-duration 180 --windows-per-song 3 --window-sec 60 [--limit 5] \
      [--seam-silence-sec 0.5] \
      [--density-strides full,strided2,strided4] \
      [--missing-ratios 0.10,0.25,0.50] [--replace-ratios 0.10,0.25,0.50] \
      [--extra-ratios 0.10,0.25,0.50]

--limit 支持 ≥20（13 §3.3 formal gate 每条件 ≥12 首独立 song；默认 10 仅为快速验证，
正式重建请传 --limit 20，FREEZE 记录 songs）。

--seam-silence-sec 控制段间 seam：默认 0.5（13 §3.4 对照版，timeline 与 concat 音频
同用该静音，GT 随 seam 平移）；传 0.0 生成主版本（无静音直接拼接，timeline 时长 =
段时长之和，seams 记录零时长标记）。FREEZE 记录该值。

输出（均冻结 SHA 记录到 FREEZE.json）：
  LONG_TIMELINE_MANIFEST.jsonl  —— 每行：时间线拼接记录（segments/seams/canonical_units）
  WINDOW_PLAN.jsonl             —— 每行：{timeline, window [w0,w1), text_units, canonical_ids,
                                  canonical_to_local, canonical range, slot_plan, request row}
  REQUESTS.jsonl                —— 直接可喂 run_behavior_suite --real 的请求行
  纯 CPU，不启动模型。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from lyricalign.research_v7.canonical_mapping import build_mapping  # noqa: E402
from lyricalign.research_v7.mutations import (  # noqa: E402
    DonorSpec,
    extra_ratio,
    replace_ratio,
)
from lyricalign.research_v7.slot_planning import (  # noqa: E402
    build_density_plans,
    id_at_stride,
    plan_slots,
)
from lyricalign.research_v7.timeline import build_timeline  # noqa: E402

WINDOW_SEC = 60.0
DEFAULT_DENSITY_TIERS: tuple[tuple[str, int], ...] = (
    ("full", 1), ("s2", 2), ("s4", 4),
)


def parse_density_strides(raw: str) -> list[tuple[str, int]]:
    """'full,strided2,strided4' -> [('full', 1), ('s2', 2), ('s4', 4)]。

    full=连续全量；strided<N>=从 phase offset 起等距取样（N≥2）。phase 名=档位名
    （request_id 后缀 :full/:s2/:s4）。拒绝空档位/重复档位/非法 step。
    """
    out: list[tuple[str, int]] = []
    for tok in raw.split(","):
        tok = tok.strip()
        if not tok:
            continue
        if tok == "full":
            phase, step = "full", 1
        else:
            mm = re.fullmatch(r"strided(\d+)", tok)
            if mm is None or int(mm.group(1)) < 2:
                raise ValueError(f"bad token {tok!r} (expect 'full' or 'stridedN' with N>=2)")
            step = int(mm.group(1))
            phase = f"s{step}"
        if any(p == phase for p, _ in out):
            raise ValueError(f"duplicate density stride {tok!r}")
        out.append((phase, step))
    if not out:
        raise ValueError("empty list")
    return out


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _sha_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _atomic_jsonl(path: Path, rows) -> None:
    import os
    import tempfile

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
        f.flush(); os.fsync(f.fileno())
    os.replace(tmp, path)


def _atomic_json(path: Path, payload) -> None:
    import os
    import tempfile

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.flush(); os.fsync(f.fileno())
    os.replace(tmp, path)


def load_m4(path: Path, min_duration: float, max_songs: int, audio_root: Path | None = None) -> list[dict]:
    """按 song 聚合段，返回 ≥min_duration 的同歌时间线（段按 item_id 数字序）。"""
    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    by_song: dict[str, list] = {}
    for r in rows:
        song = r.get("song_id")
        if not song:
            continue
        audio_path = Path(r.get("audio_relpath", ""))
        if audio_root is not None:
            audio_path = audio_root / audio_path
        if not audio_path.is_file():
            continue  # 音频缺失的段不参与拼接
        by_song.setdefault(song, []).append(r)
    timelines = []
    for song, segs in sorted(by_song.items()):
        if not segs:
            continue
        total = sum(float(s.get("duration_sec", 0) or 0) for s in segs)
        if total < min_duration:
            continue
        # 同歌手校验：同歌段必须同一 singer（M4Singer 约定）
        singers = {s.get("singer_id") for s in segs}
        if len(singers) > 1:
            continue
        # 按 item_id 的段序号排序（0000,0001,...），显式排序拒绝文件名乱序
        def _num(s):
            try:
                return int(str(s.get("item_id", "")).split("#")[-1])
            except ValueError:
                return -1
        segs_sorted = sorted(segs, key=_num)
        if any(_num(s) < 0 for s in segs_sorted):
            continue
        timelines.append({
            "song_id": song, "singer_id": next(iter(singers)), "segments": segs_sorted,
            "total_duration_sec": round(total, 3), "n_segments": len(segs_sorted),
            "audio_root": str(audio_root) if audio_root else "",
        })
        if len(timelines) >= max_songs:
            break
    return timelines


def _canonical_units_for_window(canonical_units, w0: float, w1: float) -> list[dict]:
    """窗 [w0,w1) 内 overlap 的 canonical 单位（与 c3 adapter 同语义：严格 overlap）。"""
    out = []
    for u in canonical_units:
        start, end = float(u["start_sec"]), float(u["end_sec"])
        if max(start, w0) < min(end, w1):
            out.append(u)
    out.sort(key=lambda u: int(u["canonical_unit_id"]))
    return out


def build_requests(tl: dict, timeline: object, *, windows_per_song: int,
                   row_sha: str, language: str = "Chinese",
                   density_tiers: Sequence[tuple[str, int]] = DEFAULT_DENSITY_TIERS,
                   missing_ratios: tuple[float, ...] = (0.25,),
                   replace_ratios: tuple[float, ...] = (),
                   extra_ratios: tuple[float, ...] = (),
                   donor_pool: dict[str, list[str]] | None = None) -> list[dict]:
    """从一条时间线生成 fixed-60s 窗请求（baseline + missing/replace/extra mutation 多档配对）。

    slot 密度（13 §S2）：density_tiers 每档生成独立 slot plan（phase 名=档位名，
    request_id 后缀 :full/:s2/:s4）；stride 档等距取样且起点按窗位轮换
    （offset=window_index % step，不同窗错开取样位置）；档间 common anchors 由
    build_density_plans 求交集（汇总/评价只评共同 queried 单位）。

    每个 missing/replace/extra ratio 档生成一个独立变体（request_id 后缀
    :missing{r}/:replace{r}/:extra{r}，如 :missing0.25），避免多档 identity 冲突；
    mutation_parameters 记录 requested/actual ratio 与绝对 unit 数（13 §C1 百分比核心档）。
    默认 (0.25,) 保持原单档语义（canonical 截断逻辑不变）；replace/extra 默认关闭。

    replace（双向评价）：donor 从同库其他歌取（同语言），替换尾部 N 个 canonical 单位。
    关键语义：被替换 canonical id 仍保留在 canonical_ids/canonical_to_local 里
    （与 missing 的截断不同——替换单位只是 text 变成 donor 文本，canonical 绑定不删除），
    wrong-output 方向由 replaced_canonical_ids 标识。

    extra：尾部追加 donor 文本 N 个单位；extra 单位无 canonical id
    （canonical_ids 保持 baseline，text_units 更长），identity-error 语义。

    donor_pool：{song_id: [canonical unit texts]}，donor 取同库其他歌（本 builder 加载的
    时间线集合内、排序后第一个 song_id != 当前歌者）；池不足 2 首时 replace/extra 跳过。

    row_sha：LONG_TIMELINE_MANIFEST.jsonl 中本歌实际行的序列化 sha256
    （调用方在 main 中对该行 dict 以 json.dumps(ensure_ascii=False, sort_keys=True)
    求值，保证可从文件复验）。
    """
    units = list(timeline.canonical_units)
    n = len(units)
    duration = float(timeline.duration_sec)
    # 窗起点：early/middle/late 各 60s（窗不超时长）
    n_win = max(1, int(duration // WINDOW_SEC))
    if windows_per_song <= 1:
        starts = [0.0]
    else:
        span = max(0.0, duration - WINDOW_SEC)
        starts = [span * i / (windows_per_song - 1) for i in range(windows_per_song)]
    # donor：同库其他歌（同语言——M4Singer 全库 zh，按排序取第一个 song_id != 当前歌）
    donor_song_id = None
    donor_units: tuple[str, ...] = ()
    if (replace_ratios or extra_ratios) and donor_pool:
        for other in sorted(donor_pool):
            if other != tl["song_id"]:
                donor_song_id = other
                donor_units = tuple(donor_pool[other])
                break
    reqs = []
    for wi, w0 in enumerate(starts):
        w1 = min(w0 + WINDOW_SEC, duration)
        if w1 - w0 < 30.0:
            continue  # 尾窗太短不算正式请求
        in_win = _canonical_units_for_window(units, w0, w1)
        if len(in_win) < 4:
            continue  # 窗内歌词太少（可能是长间奏）→ 跳过，避免空对齐
        cids = [int(u["canonical_unit_id"]) for u in in_win]
        texts = [u["text"] for u in in_win]
        canonical_to_local = {cid: i for i, cid in enumerate(cids)}
        c0, c1 = cids[0], cids[-1] + 1
        # slot：按 density 档位生成（13 §S2）。full=连续全量；strided<N>=从
        # phase offset 等距取样，offset=window_index % step 实现 phase 轮换
        # （不同窗错开取样位置，不固定只取一种位置）。每档独立 slot plan，
        # phase 名=档位名（request_id 后缀 :full/:s2/:s4）；common anchors 由
        # build_density_plans 求全档交集（汇总只评共同 queried 单位）。
        selected_by_stride_phase: dict[str, dict[str, list[int]]] = {}
        for phase_name, step in density_tiers:
            if step == 1:
                selected = list(cids)
            else:
                selected = [cids[i] for i in id_at_stride(len(cids), step, wi % step)]
            selected_by_stride_phase[str(step)] = {phase_name: selected}
        plans, _common_anchors = build_density_plans(
            plan_group=f"{tl['song_id']}:w{wi}", canonical_unit_count=n,
            selected_by_stride_phase=selected_by_stride_phase,
            canonical_to_local=canonical_to_local, request_local_count=len(texts))
        # canonical lineage（review12：guard/collect/assessor 消费）
        # canonical_timeline_row_sha 由 main 对实际写入行求值后传入（可从文件复验）
        tl_sha = tl.get("manifest_sha")
        for plan in plans:
            base = {
                "schema_version": "research_v7_long_slot_v1",
                "request_type": "long_timeline_60s",
                "item_id": f"{tl['song_id']}:w{wi}:{plan.phase_name}",
                "request_id": f"{tl['song_id']}:w{wi}:{plan.phase_name}",
                "parent_request_id": None,
                "audio_path": (tl.get("segs_audio") or [None])[0],
                "audio_start_sec": round(w0, 4), "audio_end_sec": round(w1, 4),
                "duration_sec": round(w1 - w0, 4), "audio_source": "m4singer_segment_concat",
                "text_source": "m4singer_meta_v1", "has_gt": True,
                "evaluation_role": "lyrics_aligned", "text_window_aligned": True,
                "text_units": texts, "text_start_index": 0, "text_end_index": len(texts),
                "timestamp_slot_indices": list(plan.local_indices),
                "workflow_mode": "long_slot_60s", "mutation_type": "baseline",
                "mutation_parameters": {"position": "whole", "requested_ratio": 0.0},
                "language": language, "dataset": "m4singer", "split": "validation",
                "model_id": "Qwen3-ForcedAligner-0.6B-hf", "checkpoint_id": "r2-step-000750",
                "input_variant": "text_mutation",
                # canonical lineage（review12：guard/collect/assessor 消费）
                "canonical_text_start": c0, "canonical_text_end": c1,
                "canonical_to_local": {str(k): v for k, v in canonical_to_local.items()},
                "canonical_ids": cids,
                "canonical_timeline_file_sha": tl_sha,
                "canonical_timeline_row_sha": row_sha,
                "canonical_adapter_version": "long_timeline_v1",
                "source_window_start_sec": round(w0, 4), "source_window_end_sec": round(w1, 4),
                "condition": "baseline", "pair_id": f"{tl['song_id']}:w{wi}",
                "slot_plan_id": plan.plan_id, "comparison_group_id": plan.comparison_group_id,
                "phase": plan.phase_name,
            }
            # missing：virtual gap（移除尾部 requested_ratio 比例单位，评价
            # omitted-original）。契约：text_units 截断后，canonical_ids/mapping/
            # range/slot 全部同步到保留单位（缺失单位不得留在请求 canonical 字段里）。
            # 每个 ratio 一档独立请求（13 §C1 核心档 10/25/50%）；mutation_parameters
            # 记录 requested_ratio/actual_ratio/actual_removed_units/absolute_count。
            for ratio in missing_ratios:
                n_miss = max(1, round(len(texts) * ratio))
                tag = f"missing{ratio:.2f}"
                miss = dict(base)
                miss["request_id"] = f"{base['request_id']}:{tag}"
                miss["item_id"] = f"{base['item_id']}:{tag}"
                miss["mutation_type"] = "missing"
                miss["condition"] = "missing"
                kept = texts[:-n_miss]
                kept_ids = cids[:-n_miss]
                kept_to_local = {cid: i for i, cid in enumerate(kept_ids)}
                # missing 的 slot：用保留 canonical ids 在【新 local 映射】上的本地索引重算
                kept_slots = plan_slots(
                    plan_id=f"{base['slot_plan_id']}:{tag}", canonical_unit_count=n,
                    queried_canonical_ids=[c for c in plan.requested_canonical_ids if c in kept_to_local],
                    canonical_to_local=kept_to_local, request_local_count=len(kept),
                    comparison_group_id=plan.comparison_group_id, phase=plan.phase_name)
                miss["text_units"] = kept
                miss["text_end_index"] = len(kept)
                miss["canonical_ids"] = kept_ids
                miss["canonical_to_local"] = {str(k): v for k, v in kept_to_local.items()}
                miss["canonical_text_end"] = kept_ids[-1] + 1 if kept_ids else c0
                miss["timestamp_slot_indices"] = list(kept_slots.local_indices)
                miss["mutation_parameters"] = {
                    "position": "tail", "requested_ratio": ratio,
                    "actual_ratio": round(n_miss / len(texts), 6) if texts else 0.0,
                    "actual_removed_units": n_miss, "absolute_count": n_miss,
                    "baseline_unit_count": len(texts)}
                reqs.append(miss)
            # replace：尾部 N 个 canonical 单位 text 换成 donor 文本（双向评价 wrong-output 方向，
            # 13 §A3）。关键语义：被替换 canonical id 保留在 canonical_ids/canonical_to_local/
            # range 里（与 missing 截断不同——替换单位只是 text 变 donor 文本，canonical 绑定不删），
            # wrong-output 区间由 mutation_parameters.replaced_canonical_ids 标识。
            # donor 从同库其他歌取（同语言，M4Singer 全 zh）；无 donor 池时整档跳过。
            for ratio in replace_ratios:
                if donor_song_id is None:
                    break  # 池不足 2 首 → replace/extra 均无法产出，整档跳过
                tag = f"replace{ratio:.2f}"
                mut = replace_ratio(texts, ratio, donor=DonorSpec(
                    donor_song_id=donor_song_id, donor_start_index=0,
                    donor_units=donor_units, language="zh", unit_mode="character"),
                    position="tail", seed=0)
                n_rep = sum(1 for a, b in zip(texts, mut.mutated_units) if a != b)
                rep = dict(base)
                rep["request_id"] = f"{base['request_id']}:{tag}"
                rep["item_id"] = f"{base['item_id']}:{tag}"
                rep["mutation_type"] = "replace"
                rep["condition"] = "replace"
                rep["slot_plan_id"] = f"{base['slot_plan_id']}:{tag}"
                rep["text_units"] = list(mut.mutated_units)
                rep["mutation_parameters"] = {
                    "position": "tail", "requested_ratio": ratio,
                    "actual_ratio": round(mut.actual_ratio, 6),
                    "actual_replaced_units": n_rep,
                    "replaced_canonical_ids": cids[-n_rep:] if n_rep else [],
                    "donor_song_id": donor_song_id, "donor_start_index": 0,
                    "baseline_unit_count": len(texts)}
                reqs.append(rep)
            # extra：尾部追加 donor 文本 N 个单位（identity-error 语义，13 §A1/§5）。
            # extra 单位无 canonical id：canonical_ids/canonical_to_local/range 保持 baseline，
            # text_units 更长；extra_start_index 标识无 canonical 的文本区间起点。
            for ratio in extra_ratios:
                if donor_song_id is None:
                    break
                tag = f"extra{ratio:.2f}"
                mut = extra_ratio(texts, ratio, source="cross_song",
                                  extra_units=donor_units, position="tail")
                n_add = len(mut.mutated_units) - len(texts)
                ext = dict(base)
                ext["request_id"] = f"{base['request_id']}:{tag}"
                ext["item_id"] = f"{base['item_id']}:{tag}"
                ext["mutation_type"] = "extra"
                ext["condition"] = "extra"
                ext["slot_plan_id"] = f"{base['slot_plan_id']}:{tag}"
                ext["text_units"] = list(mut.mutated_units)
                ext["text_end_index"] = len(ext["text_units"])
                ext["mutation_parameters"] = {
                    "position": "tail", "requested_ratio": ratio,
                    "actual_ratio": round(mut.actual_ratio, 6),
                    "actual_added_units": n_add,
                    "donor_song_id": donor_song_id, "donor_start_index": 0,
                    "baseline_unit_count": len(texts),
                    "extra_start_index": len(cids)}
                reqs.append(ext)
            # baseline 本体
            reqs.append(base)
    return reqs


def concat_timeline_audio(segs: list[dict], output: Path, *, rate: int = 16000,
                          seam_silence_sec: float = 0.5) -> None:
    """按时间线顺序拼接段音频（16k mono int16，段间插 seam_silence_sec 静音，
    与 timeline.build_timeline 的 artificial_silence 一致），输出到 output。

    返回 None；失败抛错（调用方记录并跳过该歌）。音频是正式运行输入，
    用 sha256 记录 source 文件清单到 .sources.json（重放/审计）。
    """
    import shutil
    import struct
    import subprocess
    import wave as _wave
    import numpy as np

    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg required to concat timeline audio")
    tmp = output.with_suffix(".tmp.wav")
    output.parent.mkdir(parents=True, exist_ok=True)
    parts = []
    sil = np.zeros(int(rate * seam_silence_sec), dtype=np.float32)
    for si, s in enumerate(segs):
        src = Path(s["audio_path"])
        if not src.is_file():
            raise FileNotFoundError(f"segment audio missing: {src}")
        # 统一 16k mono s16le
        seg_out = output.with_suffix(f".seg{si}.wav")
        subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error",
                        "-i", str(src), "-ar", str(rate), "-ac", "1",
                        "-c:a", "pcm_s16le", str(seg_out)], check=True)
        with _wave.open(str(seg_out), "rb") as f:
            data = np.frombuffer(f.readframes(f.getnframes()), dtype="<i2").astype(np.float32) / 32768.0
        seg_out.unlink()
        if si > 0:
            parts.append(sil)
        parts.append(data)
    out_audio = np.concatenate(parts) if parts else sil
    out_audio = np.clip(out_audio, -1.0, 1.0)
    with _wave.open(str(tmp), "wb") as f:
        f.setnchannels(1); f.setsampwidth(2); f.setframerate(rate)
        f.writeframes(struct.pack(f"<{len(out_audio)}h",
                                  *(out_audio * 32767).astype(np.int16)))
    tmp.replace(output)
    sources = [{"path": str(Path(s["audio_path"]).resolve()), "sha256": _sha(Path(s["audio_path"]))}
               for s in segs]
    output.with_suffix(".sources.json").write_text(
        json.dumps(sources, ensure_ascii=False, indent=1), encoding="utf-8")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--m4-manifest", required=True)
    p.add_argument("--out-root", required=True)
    p.add_argument("--audio-root", default="/home/hyan/Data/datasets/m4singer/raw/extracted/m4singer",
                   help="audio_relpath 的根目录（音频实际位置）")
    p.add_argument("--min-duration", type=float, default=180.0)
    p.add_argument("--seam-silence-sec", type=float, default=0.5,
                   help="段间 seam 静音秒数：默认 0.5（对照版，GT 随 seam 平移）；"
                        "传 0.0 生成主版本（无静音直接拼接，13 §3.4）")
    p.add_argument("--windows-per-song", type=int, default=3)
    p.add_argument("--limit", type=int, default=10,
                   help="最多取几首歌曲构造时间线（13 §3.3 每条件 ≥12 首 gate："
                        "正式重建请传 20；默认 10 仅快速验证）")
    p.add_argument("--density-strides", type=str, default="full,strided2,strided4",
                   help="slot 密度档位（逗号分隔；full=连续全量，strided2=stride2，"
                        "strided4=stride4；stride 档按窗位轮换起点 offset=window_index % step，"
                        "request_id 后缀=档位名 :full/:s2/:s4）")
    p.add_argument("--missing-ratios", type=str, default="0.25",
                   help="missing 尾部缺失核心档（逗号分隔 float，如 0.10,0.25,0.50）")
    p.add_argument("--replace-ratios", type=str, default="",
                   help="replace 尾部替换核心档（逗号分隔 float，如 0.10,0.25,0.50；"
                        "默认空=不生成 replace 变体）")
    p.add_argument("--extra-ratios", type=str, default="",
                   help="extra 尾部追加核心档（逗号分隔 float，如 0.10,0.25,0.50；"
                        "默认空=不生成 extra 变体）")
    args = p.parse_args(argv)

    if args.seam_silence_sec < 0.0:
        print(json.dumps({"ok": False, "reason": "seam_silence_sec must be >= 0.0"},
                         ensure_ascii=False))
        return 1

    try:
        density_tiers = parse_density_strides(args.density_strides)
    except ValueError as e:
        print(json.dumps({"ok": False, "reason": f"bad --density-strides: {e}"},
                         ensure_ascii=False))
        return 1

    try:
        raw_ratios = [float(x) for x in args.missing_ratios.split(",") if x.strip() != ""]
    except ValueError:
        print(json.dumps({"ok": False, "reason": f"bad --missing-ratios: {args.missing_ratios!r}"},
                         ensure_ascii=False))
        return 1
    missing_ratios = tuple(dict.fromkeys(sorted(raw_ratios)))  # 去重保确定性，避免重复档 identity 冲突
    if not missing_ratios or any(r <= 0.0 or r > 1.0 for r in missing_ratios):
        print(json.dumps({"ok": False, "reason": "missing_ratios must be non-empty in (0, 1]"},
                         ensure_ascii=False))
        return 1

    def _parse_ratios(raw: str, name: str) -> tuple[float, ...] | None:
        try:
            vals = [float(x) for x in raw.split(",") if x.strip() != ""]
        except ValueError:
            print(json.dumps({"ok": False, "reason": f"bad --{name}: {raw!r}"},
                             ensure_ascii=False))
            return None
        out = tuple(dict.fromkeys(sorted(vals)))
        if any(r <= 0.0 or r > 1.0 for r in out):
            print(json.dumps({"ok": False, "reason": f"{name} must be in (0, 1]"},
                             ensure_ascii=False))
            return None
        return out

    if args.replace_ratios.strip():
        replace_ratios = _parse_ratios(args.replace_ratios, "replace-ratios")
        if replace_ratios is None:
            return 1
    else:
        replace_ratios = ()
    if args.extra_ratios.strip():
        extra_ratios = _parse_ratios(args.extra_ratios, "extra-ratios")
        if extra_ratios is None:
            return 1
    else:
        extra_ratios = ()

    m4 = Path(args.m4_manifest)
    out = Path(args.out_root); out.mkdir(parents=True, exist_ok=True)
    manifest_sha = _sha(m4)
    audio_root = Path(args.audio_root) if args.audio_root else None
    timelines = load_m4(m4, args.min_duration, args.limit, audio_root=audio_root)
    if not timelines:
        print(json.dumps({"ok": False, "reason": "no song >= min_duration",
                          "m4_manifest_sha": manifest_sha}, ensure_ascii=False))
        return 1

    tl_rows, timelines_built, win_rows, reqs = [], [], [], []
    for tl in timelines:
        # 决策记录（round06）：canonical_timeline_file_sha 语义 = 源 m4 manifest sha
        # （非 timeline 文件自身 sha，与 MIR builder 语义不同）；不改 identity，
        # 改会作废 120 req formal evidence 需重跑——见 FREEZE.canonical_timeline_file_sha_note。
        tl["manifest_sha"] = manifest_sha
        audio_root = Path(tl["audio_root"]) if tl.get("audio_root") else None
        segs = []
        for s in tl["segments"]:
            audio_path = Path(s["audio_relpath"])
            if audio_root is not None:
                audio_path = audio_root / audio_path
            segs.append({
                "item_id": s["item_id"], "song_id": s["song_id"], "singer_id": s["singer_id"],
                "text": s.get("lyrics_normalized") or s.get("lyrics_raw", ""),
                "duration_sec": float(s.get("duration_sec", 0) or 0),
                "audio_path": str(audio_path), "order": int(str(s["item_id"]).split("#")[-1]),
                "source_unit_index": 0,
            })
        try:
            timeline = build_timeline(
                timeline_id=f"m4:{tl['song_id']}:v1", source_song_id=tl["song_id"],
                dataset="m4singer", language="zh", segments=segs, order_field="order",
                artificial_silence_sec=args.seam_silence_sec)
        except Exception as e:  # noqa
            print(json.dumps({"ok": False, "song": tl["song_id"], "error": str(e)}), ensure_ascii=False)
            return 2
        # 拼接整歌音频（16k mono，段间 seam_silence_sec 静音与 timeline seam 一致）——
        # 请求的 audio_start/end 是整歌坐标系，真实 executor 需要可解码的完整音频。
        concat_wav = out / "audio" / f"{tl['song_id']}.wav"
        try:
            concat_timeline_audio(segs, concat_wav, seam_silence_sec=args.seam_silence_sec)
        except Exception as e:  # noqa
            print(json.dumps({"ok": False, "song": tl["song_id"], "error": f"concat failed: {e}"},
                             ensure_ascii=False))
            return 3
        tl["segs_audio"] = [str(concat_wav)] * len(segs)
        tl_row = {
            "timeline_id": timeline.timeline_id, "song_id": tl["song_id"],
            "singer_id": tl["singer_id"], "n_segments": tl["n_segments"],
            "duration_sec": round(timeline.duration_sec, 3),
            "canonical_units": [{"canonical_unit_id": u["canonical_unit_id"], "text": u["text"],
                                 "start_sec": u["start_sec"], "end_sec": u["end_sec"]}
                                for u in timeline.canonical_units],
            "seams": list(timeline.seams),
            "source_audio_paths": [s["audio_path"] for s in segs],
            "concat_audio_path": str(concat_wav),
        }
        tl_rows.append(tl_row)
        timelines_built.append((tl, timeline))
    # 第二遍：request 生成（donor 池必须含全部时间线，replace/extra 的 donor 才能
    # 从同库其他歌取；第一遍只做 timeline/音频装配）。
    donor_pool = {r["song_id"]: [u["text"] for u in r["canonical_units"]] for r in tl_rows}
    for tl, timeline in timelines_built:
        # row_sha：对【实际写入 LONG_TIMELINE_MANIFEST.jsonl 的序列化】求值
        # （与 _atomic_jsonl 的 json.dumps(r, ensure_ascii=False, sort_keys=True) 一致），
        # 保证可从文件逐行复验；texts-only hash 口径废弃。
        tl_row = next(r for r in tl_rows if r["song_id"] == tl["song_id"])
        row_sha = _sha_bytes(
            json.dumps(tl_row, ensure_ascii=False, sort_keys=True).encode("utf-8"))
        song_reqs = build_requests(tl, timeline, windows_per_song=args.windows_per_song,
                                   row_sha=row_sha, density_tiers=density_tiers,
                                   missing_ratios=missing_ratios,
                                   replace_ratios=replace_ratios, extra_ratios=extra_ratios,
                                   donor_pool=donor_pool)
        reqs.extend(song_reqs)
        for r in song_reqs:
            win_rows.append({"song_id": tl["song_id"], "request_id": r["request_id"],
                             "window": [r["audio_start_sec"], r["audio_end_sec"]],
                             "canonical_ids": r["canonical_ids"],
                             "text_units": r["text_units"],
                             "slot_plan_id": r.get("slot_plan_id")})
    _atomic_jsonl(out / "LONG_TIMELINE_MANIFEST.jsonl", tl_rows)
    _atomic_jsonl(out / "WINDOW_PLAN.jsonl", win_rows)
    _atomic_jsonl(out / "REQUESTS.jsonl", reqs)
    freeze = {
        "schema": "research_v7_long_timeline_manifest_v1",
        "m4_manifest": {"path": str(m4), "sha256": manifest_sha},
        # 决策记录（round06）：M4 builder 的 canonical_timeline_file_sha 为源 m4
        # manifest sha（与 MIR builder 的 timeline 文件 sha 语义不同）；此为决策记录，
        # 不改 identity（改会作废 formal evidence 需重跑）。
        "canonical_timeline_file_sha_note": (
            "M4 builder 的 canonical_timeline_file_sha 为源 m4 manifest sha"
            "（与 MIR builder 的 timeline 文件 sha 语义不同）；此为决策记录，"
            "不改 identity（改会作废 formal evidence 需重跑）。"
        ),
        "built_at_utc": "2026-08-05T00:00:00Z",
        "min_duration_sec": args.min_duration, "windows_per_song": args.windows_per_song,
        "seam_silence_sec": args.seam_silence_sec,
        "density_strides": [p if s == 1 else f"strided{s}" for p, s in density_tiers],
        "missing_ratios": list(missing_ratios),
        "replace_ratios": list(replace_ratios),
        "extra_ratios": list(extra_ratios),
        "songs": len(tl_rows), "requests": len(reqs),
        "files": {
            "LONG_TIMELINE_MANIFEST.jsonl": _sha(out / "LONG_TIMELINE_MANIFEST.jsonl"),
            "WINDOW_PLAN.jsonl": _sha(out / "WINDOW_PLAN.jsonl"),
            "REQUESTS.jsonl": _sha(out / "REQUESTS.jsonl"),
        },
    }
    _atomic_json(out / "FREEZE.json", freeze)
    print(json.dumps({"ok": True, "songs": len(tl_rows), "requests": len(reqs),
                      "out_root": str(out), "freeze": freeze["files"]["REQUESTS.jsonl"][:16]},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
