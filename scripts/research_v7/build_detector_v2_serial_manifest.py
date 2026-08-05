#!/usr/bin/env python3
"""Detector V2 Phase D serial manifest builder（22 §5.2 冻结闭环设计）。

每条 trajectory：一首歌的 4-5 个连续 60s 窗口，stride=30s（窗口间 50% canonical
overlap）；窗 1 正常启动（baseline_legal）；窗 2 注入一次错误（end_early/cursor_shift
变体）；窗 3-5 正常（请求范围由串行 commit 状态推进，simulate 层处理 cursor 传播）。

输出：SERIAL_MANIFEST.jsonl（REQUESTS 行，view=full）+ FREEZE.json。纯 CPU。
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

WINDOW_SEC = 60.0
STRIDE_SEC = 30.0
MIN_WINDOW_SEC = 30.0
INJECT_FAMILIES = ("end_early", "cursor_shift")


def load_timelines(path: Path) -> tuple[dict[str, dict], str]:
    """返回 ({song_id: row}, timeline 文件 sha256)。"""
    file_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        r["_file_sha"] = file_sha
        r["_row_sha"] = hashlib.sha256(
            json.dumps(r, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
        out[r["song_id"]] = r
    return out, file_sha


def _units_in_window(units, w0, w1):
    return [u for u in units if max(float(u["start_sec"]), w0) < min(float(u["end_sec"]), w1)]


def _row(song, tl, *, wi, w0, w1, family, severity, text_units, cids,
         canonical_to_local, detail):
    row = {
        "schema_version": "research_v7_detector_v2_serial_v1",
        "request_type": "detector_v2_serial",
        "item_id": f"{song}:{wi}:{family}:{severity}:full",
        "request_id": f"{song}:{wi}:{family}:{severity}:full",
        "parent_request_id": None,
        "audio_path": f"/serial/{song}.wav",
        "audio_start_sec": round(w0, 4), "audio_end_sec": round(w1, 4),
        "duration_sec": round(w1 - w0, 4), "audio_source": "m4singer_concat",
        "text_source": "m4singer_meta_v1", "has_gt": True, "gt_ambiguity": False,
        "evaluation_role": "lyrics_aligned", "text_window_aligned": True,
        "text_units": list(text_units), "text_start_index": 0,
        "text_end_index": len(text_units),
        "timestamp_slot_indices": list(range(len(text_units))),
        "workflow_mode": "detector_v2_serial", "mutation_type": family,
        "mutation_parameters": {"position": f"window{wi}", "family": family, **detail},
        "language": "zh", "dataset": "m4singer",
        "model_id": "Qwen3-ForcedAligner-0.6B-hf", "checkpoint_id": "r2-step-000750",
        "input_variant": "text_mutation",
        "canonical_text_start": cids[0], "canonical_text_end": cids[-1] + 1,
        "canonical_to_local": {str(c): i for i, c in enumerate(cids)},
        "canonical_ids": cids,
        "canonical_timeline_file_sha": tl.get("canonical_timeline_file_sha") or tl.get("_file_sha"),
        "canonical_timeline_row_sha": tl.get("canonical_timeline_row_sha") or tl.get("_row_sha"),
        "canonical_adapter_version": tl.get("canonical_adapter_version",
                                            "detector_v2_timeline_v1"),
        "source_window_start_sec": round(w0, 4),
        "source_window_end_sec": round(w1, 4),
        "condition": family, "pair_id": f"{song}:{wi}:{family}",
        "view_id": "full", "hidden_schema": None,
        "family": family, "window_index": wi,
        "baseline_request_identity": None, "split": "serial",
    }
    return row


def build_serial_manifest(*, timelines: dict, songs: list[str],
                          n_windows: int = 5, inject: str = "end_early",
                          audio_root: Path | None = None) -> list[dict]:
    reqs: list[dict] = []
    for song in songs:
        tl = timelines.get(song)
        if tl is None:
            continue
        units = tl["canonical_units"]
        duration = float(tl["duration_sec"])
        if n_windows * STRIDE_SEC + WINDOW_SEC - STRIDE_SEC > duration:
            continue
        for wi in range(n_windows):
            w0 = wi * STRIDE_SEC
            w1 = w0 + WINDOW_SEC
            in_win = _units_in_window(units, w0, w1)
            if len(in_win) < 4:
                continue
            cids = [int(u["canonical_unit_id"]) for u in in_win]
            texts = [str(u["text"]) for u in in_win]
            if wi == 1 and inject == "end_early":
                cut = 4.0
                aw1 = w1 - cut
                if aw1 - w0 >= MIN_WINDOW_SEC:
                    r = _row(song, tl, wi=wi, w0=w0, w1=aw1, family="end_early",
                             severity="inject", text_units=texts, cids=cids,
                             canonical_to_local=None,
                             detail={"early_sec": cut, "serial_inject": True})
                    r["audio_path"] = str(audio_root / f"{song}.wav") if audio_root else r["audio_path"]
                    reqs.append(r)
                    continue
            elif wi == 1 and inject == "cursor_shift":
                shift = 2
                r = _row(song, tl, wi=wi, w0=w0, w1=w1, family="cursor_shift",
                         severity="inject", text_units=texts[shift:], cids=cids[shift:],
                         canonical_to_local=None,
                         detail={"shift_units": shift, "serial_inject": True})
                r["audio_path"] = str(audio_root / f"{song}.wav") if audio_root else r["audio_path"]
                reqs.append(r)
                continue
            r = _row(song, tl, wi=wi, w0=w0, w1=w1, family="serial_baseline",
                     severity="legal", text_units=texts, cids=cids,
                     canonical_to_local=None, detail={})
            r["audio_path"] = str(audio_root / f"{song}.wav") if audio_root else r["audio_path"]
            reqs.append(r)
    return reqs


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--timeline-manifest", required=True)
    p.add_argument("--audio-root", required=True)
    p.add_argument("--out-root", required=True)
    p.add_argument("--songs", default=None,
                   help="逗号分隔歌名（缺省：timeline 前 3 首）")
    p.add_argument("--n-windows", type=int, default=5)
    p.add_argument("--inject", default="end_early", choices=INJECT_FAMILIES)
    a = p.parse_args(argv)

    timelines, file_sha = load_timelines(Path(a.timeline_manifest))
    songs = [s.strip() for s in a.songs.split(",")] if a.songs \
        else sorted(timelines)[:3]
    audio_root = Path(a.audio_root)
    reqs = build_serial_manifest(timelines=timelines, songs=songs,
                                 n_windows=a.n_windows, inject=a.inject,
                                 audio_root=audio_root)
    out = Path(a.out_root)
    out.mkdir(parents=True, exist_ok=True)
    (out / "SERIAL_MANIFEST.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False, sort_keys=True) for r in reqs) + "\n")
    freeze = {
        "schema": "research_v7_detector_v2_serial_manifest_v1",
        "cli": {"timeline_manifest": str(a.timeline_manifest), "audio_root": str(a.audio_root),
                "songs": songs, "n_windows": a.n_windows, "inject": a.inject,
                "stride_sec": STRIDE_SEC, "window_sec": WINDOW_SEC},
        "n_requests": len(reqs),
        "request_ids_unique": len({r["request_id"] for r in reqs}) == len(reqs),
        "families": dict(collections.Counter(r["family"] for r in reqs)),
        "songs_processed": sorted({r["item_id"].split(":")[0] for r in reqs}),
        "requests_sha256": hashlib.sha256(b"\n".join(
            json.dumps(r, ensure_ascii=False, sort_keys=True).encode() for r in reqs)).hexdigest(),
    }
    (out / "FREEZE.json").write_text(json.dumps(freeze, ensure_ascii=False, indent=1))
    print(json.dumps({"ok": True, "requests": len(reqs), "songs": songs,
                      "families": freeze["families"],
                      "request_ids_unique": freeze["request_ids_unique"],
                      "out": str(out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
