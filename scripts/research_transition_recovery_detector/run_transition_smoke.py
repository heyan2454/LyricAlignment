#!/usr/bin/env python3
"""Phase 1 transition smoke：合成 3+ 窗 trajectory（fake）与 development song（real）。

用法：
  # 合成（CPU，无模型）
  PYTHONPATH=src python scripts/research_transition_recovery_detector/run_transition_smoke.py \
      --mode fake --session-root <SESSION_ROOT>

  # real（GPU，需 R2 checkpoint；--song-ids 用 --manifest 行的 song_id）
  PYTHONPATH=src python scripts/research_transition_recovery_detector/run_transition_smoke.py \
      --mode real --session-root <SESSION_ROOT> --song-ids "Bass-2#DEAR JOHN" \
      --timeline-manifest <LONG_TIMELINE_MANIFEST.jsonl> --transition T2_core_boundary_serial

  # 3s/5s retained pilot（real 或 fake）
  ... --retained 3 --retained 5
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

import numpy as np  # noqa: E402

from lyricalign.research_transition_recovery_detector.contracts import (  # noqa: E402
    TRANSITION_T1_DIRECT,
    TRANSITION_T2_CORE,
    TRANSITION_T3_STABLE,
    TRANSITIONS,
    TransitionState,
)
from lyricalign.research_transition_recovery_detector.runner import (  # noqa: E402
    FakeAlignerBackend,
    RealAlignerBackend,
    TransitionRunner,
)
from lyricalign.research_transition_recovery_detector.transitions import first_divergence  # noqa: E402

R2_CHECKPOINT_DEFAULT = "/home/hyan/Data/lyricalign/runs/20260724_qwen_fa_r2_full_seed20260724/checkpoints/step-000750"
MODEL_REVISION_DEFAULT = "c07281df297b9905d24a508279258cccf987a064"
M4_AUDIO_ROOT_DEFAULT = "/home/hyan/Data/datasets/m4singer/raw/extracted/m4singer"


def make_fake_audio(duration_sec: float = 240.0, sample_rate: int = 16000) -> np.ndarray:
    rng = np.random.default_rng(7)
    audio = np.zeros(int(duration_sec * sample_rate), dtype=np.float32)
    # 活动段：正弦 + 噪声；静音段：全零（>=5s 才被压缩）
    silence = [(8.0, 16.0), (78.0, 88.0), (158.0, 168.0), (228.0, 238.0)]
    rng = np.random.default_rng(3)
    t = np.arange(len(audio)) / sample_rate
    activity = 0.35 * np.sin(2 * np.pi * 220 * t) + 0.1 * rng.standard_normal(len(audio))
    audio += activity.astype(np.float32)
    for s, e in silence:
        audio[int(s * sample_rate):int(e * sample_rate)] = 0.0
    return audio


def fake_window_plan(duration_sec: float, audio: np.ndarray, sample_rate: int) -> dict:
    from scripts.demo.align_qwen_fa_serial_demo import build_vocal_activity_profile
    from lyricalign.demo.window_planning import build_silence_aware_window_plan

    profile = build_vocal_activity_profile(audio, sample_rate=sample_rate)
    return build_silence_aware_window_plan(
        duration_sec, profile,
        target_core_sec=60.0, left_context_sec=10.0, right_context_sec=10.0,
    )


def fake_document() -> Any:
    from lyricalign.demo.karaoke import parse_lyrics_text

    lines = ["".join("啊" for _ in range(50)) for _ in range(5)]
    return parse_lyrics_text("\n".join(lines), language="Chinese")


def fake_gt_timeline(n_units: int, sec_per_unit: float) -> dict[int, dict]:
    return {
        i: {"start_sec": i * sec_per_unit, "end_sec": i * sec_per_unit + 0.08, "text": "啊"}
        for i in range(n_units)
    }


def load_song_from_timeline(timeline_row: dict) -> tuple[np.ndarray, Any, dict[int, dict]]:
    import soundfile as sf

    audio, sr = sf.read(timeline_row["concat_audio_path"], dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    assert sr == 16000, f"expected 16k mono, got {sr}"
    units = timeline_row["canonical_units"]
    text = "".join(u["text"] for u in units)
    document = fake_document.__wrapped__(text) if hasattr(fake_document, "__wrapped__") else None
    from lyricalign.demo.karaoke import parse_lyrics_text

    document = parse_lyrics_text(text, language="Chinese")
    gt_timeline = {
        int(u["canonical_unit_id"]): {"start_sec": u["start_sec"], "end_sec": u["end_sec"], "text": u["text"]}
        for u in units
    }
    return audio, document, gt_timeline


def run_fake(session_root: Path, args: argparse.Namespace) -> int:
    from lyricalign.research_transition_recovery_detector.session_state import SessionState

    sample_rate = 16000
    audio = make_fake_audio()
    duration_sec = float(len(audio) / sample_rate)
    plan = fake_window_plan(duration_sec, audio, sample_rate)
    document = fake_document()
    gt = fake_gt_timeline(int(duration_sec / SEC_PER_UNIT_FAKE), SEC_PER_UNIT_FAKE)
    config = {
        "lookback_units": 8,
        "audio_sha": "fake-v1",
        "model_identity": {"kind": "fake"},
        "env_identity": "cpu-smoke",
        "config_hash": "fake-smoke-v1",
        "sample_rate": sample_rate,
        "audio_profile_provider": lambda a: None,
    }
    backend = FakeAlignerBackend(sec_per_unit=SEC_PER_UNIT_FAKE)
    runner = TransitionRunner(config, session_root=session_root, backend=backend)
    states: dict[str, Any] = {}
    for transition in (TRANSITION_T1_DIRECT, TRANSITION_T2_CORE, TRANSITION_T3_STABLE):
        records = runner.run_song(
            song_id="fake-240s", audio=audio, document=document,
            window_plan=plan, transition=transition, gt_timeline=gt,
            compress=False,
        )
        final = TransitionState(**records[-1]["state_after"])
        states[transition] = final
        print(json.dumps({
            "song": "fake-240s", "transition": transition, "windows": len(records),
            "committed_end": final.committed_end_exclusive, "provisional": len(final.provisional_ids),
        }))
    div = first_divergence(
        states[TRANSITION_T1_DIRECT], states[TRANSITION_T2_CORE], states[TRANSITION_T3_STABLE],
    )
    print(json.dumps({"first_divergence_window": div}))
    ok = div >= 0
    if not ok:
        print("SMOKE FAIL: transitions did not diverge", file=sys.stderr)
        return 2
    n1, n2, n3 = (
        states[TRANSITION_T1_DIRECT].committed_end_exclusive,
        states[TRANSITION_T2_CORE].committed_end_exclusive,
        states[TRANSITION_T3_STABLE].committed_end_exclusive,
    )
    if not (n1 >= n2 >= n3):
        print(f"SMOKE FAIL: expected n1>=n2>=n3, got {n1},{n2},{n3}", file=sys.stderr)
        return 2
    (session_root / "02_transition" / "SMOKE_FAKE.json").write_text(
        json.dumps({"ok": True, "first_divergence_window": div, "committed_ends": [n1, n2, n3]}, indent=2)
    )
    print("SMOKE FAKE OK")
    return 0


def run_real(session_root: Path, args: argparse.Namespace) -> int:
    import argparse as _argparse
    import hashlib

    from scripts.demo.align_qwen_fa_serial_demo import load_model

    session_root = Path(session_root)
    timeline_manifest = Path(args.timeline_manifest)
    rows = [json.loads(line) for line in timeline_manifest.read_text(encoding="utf-8").splitlines() if line.strip()]
    by_song = {r["song_id"]: r for r in rows}
    song_ids = [s.strip() for s in args.song_ids.split(",") if s.strip()]
    missing = [s for s in song_ids if s not in by_song]
    if missing:
        print(f"ERROR: song_ids not in manifest: {missing}", file=sys.stderr)
        return 2
    from scripts.demo.align_qwen_fa_serial_demo import build_vocal_activity_profile

    model_args = _argparse.Namespace(
        model="Qwen/Qwen3-ForcedAligner-0.6B-hf",
        revision=args.model_revision,
        cache_dir=args.cache_dir,
        local_files_only=True,
        device=args.device,
        kind="lora" if args.checkpoint else "raw",
    )
    checkpoint = Path(args.checkpoint) if args.checkpoint else None
    processor, model = load_model(model_args, "lora" if checkpoint else "raw", checkpoint)
    import io

    model_bytes = io.BytesIO()
    model_identity = {
        "kind": "lora" if checkpoint else "raw",
        "checkpoint": str(checkpoint) if checkpoint else None,
        "revision": args.model_revision,
        "model_sha": "loaded",
    }
    cache_dir = session_root / "cache"
    infer_args = _argparse.Namespace(
        timestamp_segment_sec=0.08,
        decoder_kind="raw",
        decoder_top_k=8,
        decoder_beam_size=96,
        research_infer_cache_root=str(cache_dir / "serial_infer"),
        research_model_identity=model_identity,
        device=args.device,
    )
    config = {
        "lookback_units": 8,
        "model_identity": model_identity,
        "env_identity": "gpu-dev",
        "config_hash": "dev-song-smoke-v1",
        "sample_rate": 16000,
        "audio_profile_provider": lambda a: build_vocal_activity_profile(a, sample_rate=16000),
        "min_original_silence_sec": 5.0,
    }
    backend = RealAlignerBackend(processor=processor, model=model, args=infer_args)
    runner = TransitionRunner(config, session_root=session_root, backend=backend)
    for song_id in song_ids:
        row = by_song[song_id]
        audio, document, gt = load_song_from_timeline(row)
        transitions = [args.transition] if args.transition else list(TRANSITIONS)
        for transition in transitions:
            for retained in ([float(args.retained)] if args.retained else [None, 3.0, 5.0]):
                records = runner.run_song(
                    song_id=f"{song_id}:r{retained}" if retained else song_id,
                    audio=audio, document=document, window_plan=fake_window_plan(
                        float(len(audio) / 16000), audio, 16000,
                    ),
                    transition=transition, gt_timeline=gt,
                    compress=retained is not None, retained_total_sec=retained,
                )
                print(json.dumps({
                    "song": song_id, "transition": transition, "retained": retained,
                    "windows": len(records), "last_committed": records[-1]["state_after"]["committed_end_exclusive"],
                }))
    print("SMOKE REAL OK")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mode", choices=("fake", "real"), default="fake")
    p.add_argument("--session-root", required=True)
    p.add_argument("--transition", choices=list(TRANSITIONS))
    p.add_argument("--song-ids", default="")
    p.add_argument("--timeline-manifest", default="")
    p.add_argument("--retained", type=float, help="silence retained_total_sec pilot (default: real 跑 None,3,5)")
    p.add_argument("--checkpoint", default=R2_CHECKPOINT_DEFAULT)
    p.add_argument("--model-revision", default=MODEL_REVISION_DEFAULT)
    p.add_argument("--cache-dir", default="/home/hyan/Data/lyricalign/models/hf_cache")
    p.add_argument("--device", default="cuda:0")
    return p


def main() -> int:
    args = build_parser().parse_args()
    session_root = Path(args.session_root)
    session_root.mkdir(parents=True, exist_ok=True)
    (session_root / "02_transition").mkdir(parents=True, exist_ok=True)
    if args.mode == "fake":
        return run_fake(session_root, args)
    return run_real(session_root, args)


if __name__ == "__main__":
    sys.exit(main())
