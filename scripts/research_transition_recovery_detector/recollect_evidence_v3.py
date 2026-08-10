#!/usr/bin/env python3
"""二次补充：按 records request 重新收集 H/P evidence（修复 window 污染 P0）。

根因：collect_evidence_v3 复用 runner.last_evidence（最后 window），导致每首歌 4 窗
H/P evidence 都指向同一 npy。本脚本对每个 record 的 request 独立 forward（用与 records
相同的音频 + query），收集 hidden(-4/-1) 与 full_posterior，写新的 evidence jsonl。

用法：
  python recollect_evidence_v3.py --session-root <session> --records-root <records> \
      --role model_selection --timeline-manifest <manifest> [--smoke]
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

import numpy as np  # noqa: E402

from lyricalign.research_transition_recovery_detector.contracts import (  # noqa: E402
    TRANSITION_T2_CORE,
    WindowRequest,
)
from lyricalign.research_transition_recovery_detector.runner import (  # noqa: E402
    RealAlignerBackend,
)

EVIDENCE_CONFIG = {"hidden_layers": [-4, -1], "save_full_posterior": True}
R2_CHECKPOINT_DEFAULT = "/home/hyan/Data/lyricalign/runs/20260724_qwen_fa_r2_full_seed20260724/checkpoints/step-000750"
MODEL_REVISION_DEFAULT = "c07281df297b9905d24a508279258cccf987a064"


def _load_backend(args: argparse.Namespace) -> RealAlignerBackend:
    import argparse as _argparse

    from scripts.demo.align_qwen_fa_serial_demo import load_model  # noqa: E402

    model_args = _argparse.Namespace(
        model="Qwen/Qwen3-ForcedAligner-0.6B-hf", revision=args.model_revision,
        cache_dir=args.cache_dir, local_files_only=True, device=args.device,
    )
    checkpoint = Path(args.checkpoint) if args.checkpoint else None
    processor, model = load_model(model_args, "lora" if checkpoint else "raw", checkpoint)
    infer_args = _argparse.Namespace(
        timestamp_segment_sec=0.08, decoder_kind="raw", decoder_top_k=8, decoder_beam_size=96,
        research_infer_cache_root=str(Path(args.session_root) / "cache" / "serial_infer_v3"),
        research_model_identity={"kind": "lora" if checkpoint else "raw"},
        research_evidence_config=EVIDENCE_CONFIG,
        device=args.device,
    )
    return RealAlignerBackend(processor=processor, model=model, args=infer_args)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--session-root", required=True)
    p.add_argument("--records-root", required=True)
    p.add_argument("--role", required=True, choices=("detector_train", "model_selection", "threshold_validation"))
    p.add_argument("--timeline-manifest", required=True)
    p.add_argument("--device", default="cuda:0")
    p.add_argument("--checkpoint", default=R2_CHECKPOINT_DEFAULT)
    p.add_argument("--model-revision", default=MODEL_REVISION_DEFAULT)
    p.add_argument("--cache-dir", default="/home/hyan/Data/lyricalign/models/hf_cache")
    p.add_argument("--smoke", action="store_true", help="只跑 1 首歌验证")
    args = p.parse_args()

    session_root = Path(args.session_root)
    records_root = Path(args.records_root)
    out_dir = session_root / "06_detector"
    out_dir.mkdir(parents=True, exist_ok=True)

    from scripts.research_transition_recovery_detector.run_transition_smoke import (  # noqa: E402
        load_song_from_timeline,
    )

    split = json.loads((records_root / "00_meta" / "DATASET_SPLIT.json").read_text(encoding="utf-8"))
    song_ids = split["roles"][args.role]
    by_song = {json.loads(l)["song_id"]: json.loads(l)
               for l in Path(args.timeline_manifest).read_text(encoding="utf-8").splitlines() if l.strip()}

    backend = _load_backend(args)

    hidden_rows: list[dict] = []
    posterior_rows: list[dict] = []
    p_rows: list[dict] = []
    n_ok = 0
    n_mismatch = 0
    for si, song_id in enumerate(song_ids):
        if args.smoke and si >= 1:
            break
        row = by_song.get(song_id)
        if row is None:
            continue
        audio, document, gt = load_song_from_timeline(row)
        cand = glob.glob(str(records_root / "02_transition" / f"{song_id}__T2_core_boundary_serial.jsonl"))
        if not cand:
            print(f"[skip] {song_id}: no T2 records")
            continue
        recs = [json.loads(l) for l in open(cand[0], encoding="utf-8")]
        recs = [r for r in recs if not r.get("skipped")]
        for rec in recs:
            req_dict = rec["request"]
            request = WindowRequest(**req_dict)
            rows, audit = backend.forward(request, audio, document, window_index=rec.get("window_index"))
            ev = audit.get("evidence_v3") or {}
            n_units = len(req_dict.get("query_canonical_ids") or [])
            n_slots_h = (ev.get("hidden") or {}).get("n_slots")
            n_slots_p = (ev.get("full_posterior") or {}).get("n_slots")
            if n_slots_h is not None and n_slots_h != 2 * n_units:
                n_mismatch += 1
                print(f"[MISMATCH] {song_id} w{rec.get('window_index')} n_units={n_units} hidden_slots={n_slots_h}")
            if ev.get("hidden"):
                hidden_rows.append({
                    "song_id": song_id, "window_index": rec.get("window_index"),
                    "request_id": req_dict["request_id"], "n_units": n_units,
                    "layers": ev["hidden"].get("layers"), "dim": ev["hidden"].get("dim"),
                    "n_slots": ev["hidden"].get("n_slots"),
                    "vector_paths": ev["hidden"].get("vector_paths"),
                    "schema": ev["hidden"].get("schema"),
                })
            if ev.get("full_posterior"):
                posterior_rows.append({
                    "song_id": song_id, "window_index": rec.get("window_index"),
                    "request_id": req_dict["request_id"], "n_units": n_units,
                    "n_slots": ev["full_posterior"].get("n_slots"),
                    "n_classes": ev["full_posterior"].get("n_classes"),
                    "path": ev["full_posterior"].get("path"),
                    "schema": ev["full_posterior"].get("schema"),
                })
            n_ok += 1
        print(f"[done] {song_id}: {len(recs)} windows")

    with open(out_dir / f"evidence_hidden_{args.role}.jsonl", "w", encoding="utf-8") as f:
        for r in hidden_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(out_dir / f"evidence_posterior_{args.role}.jsonl", "w", encoding="utf-8") as f:
        for r in posterior_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(json.dumps({
        "role": args.role, "requests_forwarded": n_ok,
        "hidden_rows": len(hidden_rows), "posterior_rows": len(posterior_rows),
        "n_slots_mismatch": n_mismatch,
    }, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
