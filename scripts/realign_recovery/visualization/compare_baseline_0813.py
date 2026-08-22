#!/usr/bin/env python3
"""Compare the CURRENT-repo baseline implementation vs the 20260813 baseline
(0813) on the SAME M4Singer song / same windows / same checkpoint.

The 0813 baseline = research_v7 long_slot_60s with FIXED 60s grid windows
(e.g. 全世界失眠 w0=[0,60], w1=[67.64,127.64], w2=[135.28,195.28]), full-slot
query.  The current repo's independent runner uses silence-aware windows with
serial commit — a DIFFERENT window plan.

To separate "implementation drift" from "design difference", this script
re-runs the EXACT 0813 requests (fixed grid, full-slot, all window units) with
the CURRENT repo's infer_slice (Plan A, same R2 checkpoint) and compares
per-character outputs with the 0813 evidence rows.

Usage:
  PYTHONPATH=src python scripts/realign_recovery/visualization/compare_baseline_0813.py \
      --song-root <cohort_b dir> --evidence-dir <stage3b_cohort_b_dev/evidence> \
      --out <out.json> \
      --model-dir <snap> --revision <rev> --checkpoint-path <ckpt>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts" / "demo"))

import align_qwen_fa_serial_demo as SERIAL  # noqa: E402
from lyricalign.demo.karaoke import parse_lyrics_text  # noqa: E402
from lyricalign.training.qwen_fa_runtime import decode_audio  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--song-root", required=True, type=Path,
                    help="manifest_cohort_b dir (REQUESTS.jsonl + audio/)")
    ap.add_argument("--evidence-dir", required=True, type=Path,
                    help="stage3b_cohort_b_dev/evidence")
    ap.add_argument("--song", default="全世界失眠")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--model-dir", required=True)
    ap.add_argument("--revision", required=True)
    ap.add_argument("--checkpoint-path", required=True)
    args = ap.parse_args()

    # 1) 0813 requests (full, no missing) for this song
    reqs = [json.loads(l) for l in (args.song_root / "REQUESTS.jsonl").read_text(encoding="utf-8").splitlines()]
    full = [r for r in reqs
            if r.get("item_id", "").startswith(args.song) and "full" in r.get("request_id", "")
            and "missing" not in r.get("request_id", "")]
    full.sort(key=lambda r: r.get("audio_start_sec", 0))
    print(f"{args.song}: {len(full)} full windows", flush=True)

    # 2) canonical timeline (GT) for the document + unit texts
    tl_rows = [json.loads(l) for l in (args.song_root / "LONG_TIMELINE_MANIFEST.jsonl").read_text(encoding="utf-8").splitlines()]
    tl = next(r for r in tl_rows if r["song_id"] == args.song)
    canon = sorted(tl["canonical_units"], key=lambda u: int(u["canonical_unit_id"]))
    by_id = {int(u["canonical_unit_id"]): u for u in canon}
    texts = [u["text"] for u in canon]
    # document = line-joined text (each unit its own line keeps nagisa/char parse stable)
    line_text = "\n".join(texts)
    doc = parse_lyrics_text(line_text, language="chinese")
    print(f"  units={len(canon)} doc chars={len(doc.characters)}", flush=True)

    # 3) audio
    audio = decode_audio(str(args.song_root / "audio" / f"{args.song}.wav"))
    sr = 16000

    infer_args = SimpleNamespace(
        device="cuda", model=args.model_dir, revision=args.revision,
        local_files_only=True, cache_dir=None,
        timestamp_segment_sec=0.08, decoder_kind="official",
        decoder_top_k=8, decoder_beam_size=96,
    )
    processor, model = SERIAL.load_model(infer_args, kind="lora", checkpoint=Path(args.checkpoint_path))

    # 4) run each window, compare with 0813 evidence
    result = {"schema": "baseline_0813_comparison_v1", "song": args.song, "windows": []}
    for r in full:
        rid = r["request_id"]
        a_s = float(r["audio_start_sec"]); a_e = float(r["audio_end_sec"])
        cids = [int(x) for x in r["canonical_ids"]]
        wstart = min(cids); wend = max(cids) + 1
        start = int(round(a_s * sr)); stop = int(round(a_e * sr))
        stop = min(stop, len(audio))
        rows_out, audit = SERIAL.infer_slice(
            processor=processor, model=model,
            audio=audio[start:stop], document=doc,
            character_start=wstart, character_end=wend,
            global_audio_offset_sec=a_s, args=infer_args,
            timestamp_slot_indices=list(range(wend - wstart)),
        )
        cur = {int(x.get("global_character_index", -1)): x for x in rows_out}
        # 0813 evidence: find by request_id
        ev = None
        for f in (args.evidence_dir).glob("sha256:*.json"):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            rq = (d.get("attempt") or {}).get("request") or {}
            if rq.get("request_id") == rid:
                ev = d
                break
        ev_rows = {}
        if ev is not None:
            erows = ((ev["attempt"].get("decoder_outputs") or {}).get("official", {})).get("rows") or []
            # evidence rows carry WINDOW-LOCAL global_character_index; map via
            # the request's canonical_to_local back to song-global ids
            c2l = r.get("canonical_to_local") or {}
            local_to_c = {int(v): int(k) for k, v in c2l.items()}
            for x in erows:
                li = int(x.get("global_character_index", -1))
                g = local_to_c.get(li, li)
                ev_rows[g] = x
        # per-character comparison
        per = []
        for g in sorted(set(cids)):
            c = cur.get(g)
            e = ev_rows.get(g)
            gt_u = by_id.get(g)
            def s_of(row, key):
                v = row.get(key)
                return float(v) if isinstance(v, (int, float)) else None
            entry = {
                "g": g, "text": texts[g] if g < len(texts) else "?",
                "gt_start": round(float(gt_u["start_sec"]), 4) if gt_u else None,
                "cur_start": s_of(c, "official_fixed_global_start_sec") if c else None,
                "cur_end": s_of(c, "official_fixed_global_end_sec") if c else None,
                "e813_start": s_of(e, "official_fixed_global_start_sec") if e else None,
                "e813_end": s_of(e, "official_fixed_global_end_sec") if e else None,
            }
            per.append(entry)
        # aggregates
        def mae(pairs):
            ds = [abs(a - b) for a, b in pairs if a is not None and b is not None]
            return round(sum(ds) / len(ds), 4) if ds else None
        cur_gt = mae([(p["cur_start"], p["gt_start"]) for p in per])
        e813_gt = mae([(p["e813_start"], p["gt_start"]) for p in per])
        cur_e813 = mae([(p["cur_start"], p["e813_start"]) for p in per])
        n_cur = sum(1 for p in per if p["cur_start"] is not None)
        n_813 = sum(1 for p in per if p["e813_start"] is not None)
        n_both = sum(1 for p in per if p["cur_start"] is not None and p["e813_start"] is not None)
        big = sum(1 for p in per if p["cur_start"] is not None and p["e813_start"] is not None
                  and abs(p["cur_start"] - p["e813_start"]) > 0.5)
        result["windows"].append({
            "request_id": rid, "audio": [a_s, a_e],
            "n_units": len(cids),
            "mae_cur_vs_gt": cur_gt, "mae_0813_vs_gt": e813_gt,
            "mae_cur_vs_0813": cur_e813,
            "n_cur": n_cur, "n_813": n_813, "n_both": n_both,
            "n_diff_gt_0.5s": big,
        })
        print(json.dumps(result["windows"][-1], ensure_ascii=False), flush=True)
        # write per-char for first window
        if len(result["windows"]) == 1:
            (args.out.parent / f"{args.song}_per_char.json").write_text(
                json.dumps(per, ensure_ascii=False, indent=1), encoding="utf-8")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote", args.out, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
