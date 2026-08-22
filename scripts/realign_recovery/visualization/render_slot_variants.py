#!/usr/bin/env python3
"""Render the C group (strict/compress 2x2) comparison: per song

  images/C_variants_<song>.png           4-lane full-song timeline (C1/C2/C3/C4)
  videos/C_variants_<song>.mp4           4-lane timeline video (vocal audio)
  videos/C_variants_KTV_<song>.mp4       2x2 KTV panels (C1|C2 / C3|C4, vocal audio)

Each lane/panel shows its own window boundaries:
  C1 from the B4 alignment window_trace; C2/C3/C4 from the variant manifests
  (original-clock core/input; compressed variants project original_* fields).

Usage:
  PYTHONPATH=src python scripts/realign_recovery/visualization/render_slot_variants.py \
      --deliver /home/hyan/Data/lyricalign/runs/20260815_slot_v2_DELIVER \
      [--c1-root .../20260815_slot_vs_b4/align] [--start N] [--end N]
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts" / "realign_recovery" / "visualization"))

from batch_ktv_compare import LANG_LOOKUP, resolve_b4  # noqa: E402
from lyricalign.demo.media_render import render_alignment_comparison  # noqa: E402

C1_ROOT = "/home/hyan/Data/lyricalign/runs/20260815_slot_vs_b4/align"
V2_ROOT = "/home/hyan/Data/lyricalign/runs/20260815_slot_v2"
VARIANT_ORDER = ["strict", "compress", "strict_compress"]
LABELS = {
    "C1": "C1 Base · soft",
    "strict": "C2 strict",
    "compress": "C3 compress",
    "strict_compress": "C4 strict+compress",
}
PREP = "/home/hyan/Data/lyricalign/viz_fullsong_prep"
TEST = "/home/hyan/Data/lyricalign/test"


def resolve_vocal(song: str, lang: str) -> Path | None:
    for base in (PREP, TEST):
        p = Path(base) / lang / f"{song}_qwen_fa/work/audio/vocals.wav"
        if p.is_file():
            return p
    return None


def load_window_traces(variant_root: Path | str, manifest: Path | str | None,
                       b4_align: Path | None, song: str | None = None) -> list[dict]:
    """Window trace for one variant lane: C1 reuses the B4 trace; the C2/C3/C4
    traces come from the variant manifest (original-clock geometry), filtered
    to ONE song (the manifest spans all 33 songs)."""
    if manifest is None or not Path(manifest).is_file():
        if b4_align is not None:
            d = json.loads(Path(b4_align).read_text(encoding="utf-8"))
            return list(d.get("window_trace") or [])
        return []
    traces = []
    for line in Path(manifest).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if song is not None and r.get("song_id") != song:
            continue
        if r.get("status") not in ("ok", "ok_truncated_units"):
            continue
        core_s = r.get("original_core_start_sec", r.get("core_start_sec"))
        core_e = r.get("original_core_end_sec", r.get("core_end_sec"))
        inp_s = r.get("original_input_start_sec", r.get("audio_start_sec"))
        inp_e = r.get("original_input_end_sec", r.get("audio_end_sec"))
        if core_s is None or core_e is None:
            continue
        traces.append({
            "window_index": r.get("window_index"),
            "core_start_sec": float(core_s),
            "core_end_sec": float(core_e),
            "input_start_sec": float(inp_s or core_s),
            "input_end_sec": float(inp_e or core_e),
            "is_final_core": bool(r.get("is_final_core", False)),
            "window_plan_policy": r.get("window_plan_policy", "variant"),
        })
    traces.sort(key=lambda w: float(w.get("core_start_sec", 0)))
    for i, w in enumerate(traces):
        w["window_index"] = i
    if traces:
        traces[-1]["is_final_core"] = True
    return traces


def inject_window_trace(align_path: Path, traces: list[dict], out_path: Path) -> Path:
    d = json.loads(align_path.read_text(encoding="utf-8"))
    d["window_trace"] = traces
    out_path.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deliver", required=True, type=Path)
    ap.add_argument("--c1-root", type=Path, default=Path(C1_ROOT))
    ap.add_argument("--v2-root", type=Path, default=Path(V2_ROOT))
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--end", type=int, default=0)
    ap.add_argument("--page-seconds", type=float, default=15.0)
    args = ap.parse_args()

    videos = args.deliver / "videos"
    images = args.deliver / "images"
    videos.mkdir(parents=True, exist_ok=True)
    images.mkdir(parents=True, exist_ok=True)

    render_script = REPO / "scripts/realign_recovery/visualization/render_full_song.py"
    tmp = args.deliver / "_tmp"
    tmp.mkdir(parents=True, exist_ok=True)

    songs = sorted(p.name for p in args.c1_root.iterdir() if p.is_dir())
    if args.end:
        songs = songs[args.start:args.end]
    else:
        songs = songs[args.start:]

    done, failed = [], []
    for song in songs:
        lang = LANG_LOOKUP.get(song)
        if lang is None:
            continue
        c1 = args.c1_root / song / "alignments/r2/vocal/windowed/alignment.json"
        if not c1.is_file():
            print(f"{song}: no C1 alignment", flush=True)
            failed.append(song)
            continue
        b4 = resolve_b4(song)
        audio = resolve_vocal(song, lang)
        if b4 is None or audio is None:
            print(f"{song}: no B4/audio", flush=True)
            failed.append(song)
            continue
        slug = song.replace(" ", "_")

        # lane alignments with injected window traces
        specs = [("C1", c1, load_window_traces(None, None, b4))]
        lanes = [("C1", c1)]
        ok_all = True
        for variant in VARIANT_ORDER:
            va = args.v2_root / "align" / variant / song / "alignments/r2/vocal/windowed/alignment.json"
            if not va.is_file():
                print(f"{song}: no {variant} alignment", flush=True)
                ok_all = False
                continue
            lanes.append((variant, va))
        if not ok_all or len(lanes) < 4:
            print(f"{song}: PARTIAL lanes ({len(lanes)}/4), skip", flush=True)
            failed.append(song)
            continue
        prepared = []
        for key, path in lanes:
            traces = (load_window_traces(None, None, b4, song) if key == "C1" else
                      load_window_traces(
                          None, args.v2_root / f"manifest_{key}.jsonl", None, song))
            prepared.append((key, inject_window_trace(
                path, traces, tmp / f"{slug}_{key}.alignment.json")))

        # 1) 4-lane timeline (render_full_song, static PNG only — timeline video
        #    removed per user decision; KTV subtitle video kept below)
        out = tmp / f"{slug}_lanes"
        cmd = [sys.executable, str(render_script)]
        for key, path in prepared:
            cmd += ["--baseline-align", f"{LABELS[key]}={path}"]
        cmd += ["--item", f"{lang}/{song}.mp3", "--audio", str(audio),
                "--out", str(out), "--page-seconds", str(args.page_seconds),
                "--no-global-windows", "--no-video"]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=7200)
        ft = out / "visuals/current_full_song/full_timeline.png"
        if ft.is_file():
            shutil.copyfile(ft, images / f"C_variants_{slug}.png")

        # 2) KTV 2x2 (C1|C2 / C3|C4)
        ktv = videos / f"C_variants_KTV_{slug}.mp4"
        try:
            render_alignment_comparison(
                alignment_paths=[p for _, p in prepared],
                labels=[LABELS[k] for k, _ in prepared],
                visual_source=None, audio_track=audio,
                output_path=ktv, ass_root=args.deliver / "_ktv_ass" / slug,
                font="Noto Sans CJK SC", layout="four", profile="final", force=True)
        except Exception as e:  # noqa: BLE001
            print(f"{song}: KTV FAIL {e}", flush=True)
        ok = ft.is_file() and ktv.is_file()
        print(f"{song}: {'OK' if ok else 'PARTIAL'} (exit={r.returncode})", flush=True)
        (done if ok else failed).append(song)
    print(json.dumps({"RENDER_DONE": len(done), "failed": failed, "total": len(songs)},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
