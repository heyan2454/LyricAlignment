"""04_test_demo: no-GT stress analysis of the production detector on Test Demo.

Module is named ``test_demo`` (means "test the Demo behavior", unrelated to
pytest); function names intentionally avoid a ``test_`` prefix so pytest does
not collect this module as tests.

Pipeline (pure CPU except the real-model detector adapter):
    discover_items -> detector_summary -> select_suspicious ->
    build_demo_requests -> run_stage (writes 04_test_demo outputs).

No accuracy/harm labels are produced anywhere: only displacement, candidate
agreement, detector delta and structural anomalies.  The old proposal-builder
code path is intentionally never imported or called.
"""
from __future__ import annotations

import json
import pickle
from datetime import datetime, timezone
from pathlib import Path

from lyricalign.demo.karaoke import parse_lyrics_text
from lyricalign.realign_gate import identity

AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".flac", ".mp4", ".mov", ".aac"}
LANG_KEYWORDS = ("Chinese", "English", "Japanese", "Cantonese")

COMPRESSED_SEC = 0.05
RAW_OFF_DIVERGE_SEC = 0.3

ANOMALY_WEIGHT = {
    "detector_reject": 3.0,
    "zero_duration": 2.5,
    "detector_uncertain": 2.0,
    "compressed_run": 2.0,
    "posterior_multimodal": 1.0,
    "raw_official_divergence": 0.5,
}

LANG_PARSE = {
    "japanese": "Japanese",
    "english": "English",
    "cantonese": "Cantonese",
    "chinese": "Chinese",
    "unknown": "Chinese",
}


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _envelope(schema: str, cfg: dict) -> dict:
    return {
        "schema": schema,
        "generated_at_utc": _utcnow(),
        "command": cfg.get("command"),
        "inputs": cfg.get("inputs", []),
        "result_status": "ok",
    }


def discover_items(demo_roots) -> list[dict]:
    """Recursively discover audio + same-name txt pairs (language from path)."""
    items: list[dict] = []
    for raw_root in demo_roots:
        root = Path(raw_root)
        if not root.is_dir():
            continue
        for audio in sorted(root.rglob("*")):
            if audio.suffix.lower() not in AUDIO_EXTS:
                continue
            txt = audio.with_suffix(".txt")
            if not txt.is_file():
                continue
            lang = "unknown"
            parts = audio.relative_to(root).parts
            for cand in LANG_KEYWORDS:
                if cand in parts:
                    lang = cand.lower()
                    break
            items.append({"audio": audio, "txt": txt, "lang": lang, "root": root})
    return items


def _tristate(p_bad: float) -> str:
    if p_bad < identity.RAW_T_ACCEPT:
        return "accept"
    if p_bad > identity.RAW_T_REJECT:
        return "reject"
    return "uncertain"


def _parse_document(text: str, lang: str):
    return parse_lyrics_text(text, language=LANG_PARSE.get(lang, "Chinese"))


def _merge_segments(unit_states: list[dict]) -> list[dict]:
    """Group sorted unit states into contiguous segments (light-merge semantics)."""
    segments: list[dict] = []
    for unit in unit_states:
        idx = unit["index"]
        if segments and segments[-1]["unit_end"] == idx and segments[-1]["state"] == unit["state"]:
            segments[-1]["unit_end"] = idx + 1
            segments[-1]["max_p_bad"] = max(segments[-1]["max_p_bad"], unit["p_bad"])
            continue
        segments.append({
            "unit_start": idx,
            "unit_end": idx + 1,
            "state": unit["state"],
            "max_p_bad": unit["p_bad"],
        })
    return segments


def _segments_with_light_merge(unit_states: list[dict]) -> list[dict]:
    """Prefer research_v7.light_merge; fall back to local merge on mismatch."""
    try:
        from lyricalign.research_v7.detector_v2_intervals import light_merge

        merged = light_merge({u["index"]: u["state"] for u in unit_states})
        units_by_idx = {u["index"]: u for u in unit_states}
        segments: list[dict] = []
        for idx in sorted(merged):
            state = merged[idx].value if hasattr(merged[idx], "value") else str(merged[idx])
            unit = units_by_idx[idx]
            if segments and segments[-1]["unit_end"] == idx and segments[-1]["state"] == state:
                segments[-1]["unit_end"] = idx + 1
                segments[-1]["max_p_bad"] = max(segments[-1]["max_p_bad"], unit["p_bad"])
                continue
            segments.append({
                "unit_start": idx,
                "unit_end": idx + 1,
                "state": state,
                "max_p_bad": unit["p_bad"],
            })
        return segments
    except Exception:  # noqa: BLE001 - fall back to local merge
        return _merge_segments(unit_states)


def _raw_rows_json(rows: list[dict]) -> list[dict]:
    out = []
    for i, r in enumerate(rows):
        topk = r.get("raw_start_topk_probabilities")
        row = {
            "index": i,
            "fixed_global_start_sec": float(r.get("fixed_global_start_sec", 0.0)),
            "fixed_global_end_sec": float(r.get("fixed_global_end_sec", 0.0)),
        }
        off = r.get("official_fixed_global_start_sec")
        if off is not None:
            row["official_fixed_global_start_sec"] = float(off)
        if topk:
            row["raw_start_topk_probabilities"] = [float(v) for v in topk]
        out.append(row)
    return out


def _assemble_record(item: dict, text: str, duration: float, rows: list[dict],
                     unit_states: list[dict], segments: list[dict]) -> dict:
    n = len(unit_states)
    starts = [u["start_sec"] for u in unit_states]
    zero_run = 0
    cur = 0
    raw_off_diff = 0.0
    n_official = 0
    anomalies: list[dict] = []
    i = 0
    while i < n:
        u = unit_states[i]
        if u["start_sec"] == u["end_sec"]:
            cur += 1
            zero_run = max(zero_run, cur)
            anomalies.append({"kind": "zero_duration", "unit_start": i, "unit_end": i + 1,
                              "detail": {"start_sec": round(u["start_sec"], 3)}})
            i += 1
            continue
        cur = 0
        j = i
        while j < n and 0 < (unit_states[j]["end_sec"] - unit_states[j]["start_sec"]) < COMPRESSED_SEC:
            j += 1
        if j - i >= 2:
            anomalies.append({"kind": "compressed_run", "unit_start": i, "unit_end": j,
                              "detail": {"n": j - i}})
            i = j
            continue
        i += 1
    for u, row in zip(unit_states, rows):
        topk = row.get("raw_start_topk_probabilities")
        if topk and len(topk) >= 2 and float(topk[1]) > 0.15:
            anomalies.append({"kind": "posterior_multimodal", "unit_start": u["index"],
                              "unit_end": u["index"] + 1, "detail": {}})
        off = row.get("official_fixed_global_start_sec")
        if off is not None:
            diff = abs(u["start_sec"] - float(off))
            raw_off_diff += diff
            n_official += 1
            if diff > RAW_OFF_DIVERGE_SEC:
                anomalies.append({"kind": "raw_official_divergence", "unit_start": u["index"],
                                  "unit_end": u["index"] + 1,
                                  "detail": {"diff_sec": round(diff, 3)}})
    tri = {"accept": 0, "uncertain": 0, "reject": 0}
    for u in unit_states:
        tri[u["state"]] = tri.get(u["state"], 0) + 1
    mono = len(starts) == len(set(round(s, 2) for s in starts))
    n_reject = tri.get("reject", 0)
    n_uncertain = tri.get("uncertain", 0)
    n_peak = sum(1 for a in anomalies if a["kind"] == "posterior_multimodal")
    suspicious = (n_reject + 0.5 * n_uncertain + n_peak * 0.1 + zero_run * 0.2) / max(n, 1)
    return {
        "item": str(item["audio"].relative_to(item["root"])),
        "lang": item["lang"],
        "audio_path": str(item["audio"]),
        "txt_path": str(item["txt"]),
        "text": text,
        "duration_sec": round(duration, 1),
        "n_units": n,
        "raw_official_mean_diff_sec": round(raw_off_diff / max(n_official, 1), 3),
        "zero_duration_max_run": zero_run,
        "top2_competing_peak_units": n_peak,
        "monotonic_starts": mono,
        "tristate": tri,
        "detector_segments": segments,
        "anomalies": anomalies,
        "unit_states": unit_states,
        "raw_rows": _raw_rows_json(rows),
        "suspicious_score": round(suspicious, 4),
    }


def detector_summary(items: list[dict], detector_adapter) -> dict:
    """Run the detector adapter over items and aggregate the contract summary."""
    per_song: list[dict] = []
    failed: list[dict] = []
    for item in items:
        try:
            record = detector_adapter(item)
            record.setdefault("item", str(item["audio"].relative_to(item["root"])))
            record.setdefault("lang", item["lang"])
            per_song.append(record)
        except Exception as exc:  # noqa: BLE001
            failed.append({"item": str(item["audio"]), "reason": str(exc)[:300]})
    per_song.sort(key=lambda r: -float(r.get("suspicious_score", 0.0)))
    return {
        "schema": "TEST_DEMO_DETECTOR_SUMMARY_v1",
        "no_gt": True,
        "n_items": len(per_song),
        "n_failed": len(failed),
        "detector": {"kind": "standardized_logistic", "combo": "R", "merge": "light_merge",
                     "T_accept": identity.RAW_T_ACCEPT, "T_reject": identity.RAW_T_REJECT},
        "per_song": per_song,
        "ranking": [r["item"] for r in per_song],
        "failed": failed,
        "note": "无 GT，不报告 MAE/accuracy；suspicious 为 REJECT/UNCERTAIN/竞争峰/零时长/压缩 run 启发式组合",
    }


def _windows_from_record(record: dict) -> list[dict]:
    windows: list[dict] = []
    song_score = float(record.get("suspicious_score", 0.0))
    item = record["item"]
    lang = record["lang"]
    for a in record.get("anomalies", []):
        kind = a["kind"]
        windows.append({
            "item": item, "lang": lang, "anomaly_kind": kind,
            "unit_start": a["unit_start"], "unit_end": a["unit_end"],
            "score": round(song_score + ANOMALY_WEIGHT.get(kind, 1.0), 4),
            "song_suspicious_score": song_score,
            "segment": None, "detail": a.get("detail"),
            "song_record": record,
        })
    for seg in record.get("detector_segments", []):
        if seg["state"] not in ("reject", "uncertain"):
            continue
        kind = "detector_reject" if seg["state"] == "reject" else "detector_uncertain"
        windows.append({
            "item": item, "lang": lang, "anomaly_kind": kind,
            "unit_start": seg["unit_start"], "unit_end": seg["unit_end"],
            "score": round(song_score + ANOMALY_WEIGHT[kind], 4),
            "song_suspicious_score": song_score,
            "segment": dict(seg), "detail": None,
            "song_record": record,
        })
    return windows


def _window_key(w: dict) -> tuple:
    return (w["item"], w["unit_start"], w["unit_end"], w["anomaly_kind"])


def select_suspicious(detector_summary_data: dict, *, top_k: int = 20,
                      min_per_lang: int = 2) -> list[dict]:
    """Rank suspicious windows across languages; per-language quota then global top_k."""
    windows = [w for rec in detector_summary_data["per_song"] for w in _windows_from_record(rec)]
    windows.sort(key=lambda w: -w["score"])
    selected: list[dict] = []
    seen: set[tuple] = set()
    per_lang: dict[str, int] = {}
    for w in windows:
        if len(selected) >= top_k:
            break
        key = _window_key(w)
        if key in seen:
            continue
        if per_lang.get(w["lang"], 0) < min_per_lang:
            per_lang[w["lang"]] = per_lang.get(w["lang"], 0) + 1
            seen.add(key)
            selected.append(w)
    for w in windows:
        if len(selected) >= top_k:
            break
        key = _window_key(w)
        if key in seen:
            continue
        seen.add(key)
        selected.append(w)
    return selected[:top_k]


def _segment_bounds(unit_states: list[dict], start: int, end: int) -> tuple:
    start = max(0, min(start, len(unit_states) - 1))
    end = max(start + 1, min(end, len(unit_states)))
    lo = unit_states[start]["start_sec"]
    hi = unit_states[end - 1]["end_sec"]
    return round(float(lo), 3), round(float(hi), 3)


def _anchor_segments(segments: list[dict], s0: int, e: int) -> list[dict]:
    anchors = [s for s in segments if s["state"] == "accept"
               and (s["unit_end"] <= s0 or s["unit_start"] >= e)]
    anchors.sort(key=lambda s: s["unit_start"])
    before = [s for s in anchors if s["unit_end"] <= s0]
    after = [s for s in anchors if s["unit_start"] >= e]
    return (before[-1:] if before else []) + (after[:1] if after else [])


def _neighbor_segment(segments: list[dict], s0: int, e: int, *, before: bool) -> str | None:
    if before:
        cands = [s for s in segments if s["unit_end"] <= s0]
        cands.sort(key=lambda s: -s["unit_start"])
    else:
        cands = [s for s in segments if s["unit_start"] >= e]
        cands.sort(key=lambda s: s["unit_start"])
    return cands[0]["state"] if cands else None


def _displacement(raw_rows: list[dict], s0: int, e: int) -> dict:
    diffs = []
    for r in raw_rows:
        if not (s0 <= r["index"] < e):
            continue
        off = r.get("official_fixed_global_start_sec")
        if off is not None:
            diffs.append(abs(r["fixed_global_start_sec"] - float(off)))
    return {
        "mean_abs_diff_sec": round(sum(diffs) / len(diffs), 3) if diffs else None,
        "max_abs_diff_sec": round(max(diffs), 3) if diffs else None,
        "n_official_rows": len(diffs),
    }


def _signals(w: dict, song: dict, unit_states: list[dict], segments: list[dict]) -> dict:
    s0, e = w["unit_start"], w["unit_end"]
    s0, e = max(0, s0), min(e, len(unit_states))
    span = unit_states[s0:e]
    denom = max(len(span), 1)
    reject = sum(1 for u in span if u["state"] == "reject")
    uncertain = sum(1 for u in span if u["state"] == "uncertain")
    peak = sum(1 for a in song.get("anomalies", [])
               if a["kind"] == "posterior_multimodal" and s0 <= a["unit_start"] < e)
    seg = w.get("segment") or {}
    return {
        "displacement": _displacement(song.get("raw_rows", []), s0, e),
        "candidate_agreement": {
            "reject_ratio": round(reject / denom, 3),
            "uncertain_ratio": round(uncertain / denom, 3),
            "competing_peak_units": peak,
        },
        "detector_delta": {
            "segment_state": seg.get("state"),
            "max_p_bad": seg.get("max_p_bad"),
            "n_reject": reject,
            "n_uncertain": uncertain,
            "neighbor_before": _neighbor_segment(segments, s0, e, before=True),
            "neighbor_after": _neighbor_segment(segments, s0, e, before=False),
        },
        "structure_anomaly": {
            "kind": w["anomaly_kind"],
            "detail": w.get("detail"),
            "unit_start": s0,
            "unit_end": e,
        },
    }


def build_demo_requests(suspicious: list[dict], items: list[dict], *, detector_state: dict) -> list[dict]:
    """Build narrow + context demo requests.  The old proposal-builder code path
    is deliberately not used here (demo requests carry their own schema)."""
    items_by_rel = {str(item["audio"].relative_to(item["root"])): item for item in items}
    requests: list[dict] = []
    for i, w in enumerate(suspicious):
        item = items_by_rel.get(w["item"])
        song = w.get("song_record")
        if item is None or song is None:
            continue
        text = song.get("text") or item["txt"].read_text(encoding="utf-8-sig")
        document = _parse_document(text, item["lang"])
        character_index = [
            {"global_index": c.global_index, "text": c.text, "line_index": c.line_index,
             "index_in_line": c.index_in_line, "unit_type": c.unit_type}
            for c in document.characters
        ]
        unit_states = song.get("unit_states", [])
        segments = song.get("detector_segments", [])
        s0 = max(0, min(w["unit_start"], len(unit_states) - 1))
        e = max(s0 + 1, min(w["unit_end"], len(unit_states)))
        core_start, core_end = _segment_bounds(unit_states, s0, e)
        anchors = _anchor_segments(segments, s0, e)
        signals = _signals(w, song, unit_states, segments)
        base = {
            "schema": "realign_gate_test_demo_request_v1",
            "no_gt": True,
            "item": w["item"],
            "lang": w["lang"],
            "audio_path": song.get("audio_path") or str(item["audio"]),
            "text_path": str(item["txt"]),
            "text": text,
            "character_index": character_index,
            "raw_rows": song.get("raw_rows", []),
            "detector_state": detector_state,
            "signals": signals,
        }
        narrow = dict(base)
        narrow.update({
            "request_id": f"test-demo-{i:03d}-narrow",
            "kind": "narrow",
            "span": {"unit_start": s0, "unit_end": e,
                     "core_start_sec": core_start, "core_end_sec": core_end},
            "anchor": [],
        })
        requests.append(narrow)
        ctx_lo = anchors[0]["unit_start"] if anchors else s0
        ctx_hi = anchors[-1]["unit_end"] if anchors else e
        ctx_start, ctx_end = _segment_bounds(unit_states, ctx_lo, ctx_hi)
        context = dict(base)
        context.update({
            "request_id": f"test-demo-{i:03d}-context",
            "kind": "context",
            "span": {"unit_start": s0, "unit_end": e,
                     "core_start_sec": core_start, "core_end_sec": core_end,
                     "context_start_sec": ctx_start, "context_end_sec": ctx_end},
            "anchor": [dict(a) for a in anchors],
        })
        requests.append(context)
    return requests


def _write_json(path: Path, obj: dict) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _mock_detector_adapter(cfg: dict):
    """Deterministic CPU adapter for tests / dry runs (no real audio inference)."""
    del cfg

    def adapter(item: dict) -> dict:
        text = item["txt"].read_text(encoding="utf-8-sig")
        try:
            document = _parse_document(text, item["lang"])
        except Exception:  # noqa: BLE001
            document = _parse_document(text, "Chinese")
        unit_states = []
        for i, ch in enumerate(document.characters):
            start = i * 0.4
            end = start + 0.4
            p_bad = 0.05
            state = "accept"
            if i == 3:
                end = start
                p_bad = 0.5
                state = "reject"
            elif i == 7:
                p_bad = 0.3
                state = "uncertain"
            unit_states.append({"index": i, "text": ch.text, "start_sec": start,
                                "end_sec": end, "state": state, "p_bad": p_bad})
        rows = []
        for u in unit_states:
            row = {"index": u["index"], "fixed_global_start_sec": u["start_sec"],
                   "fixed_global_end_sec": u["end_sec"]}
            if u["index"] % 5 == 0:
                row["official_fixed_global_start_sec"] = u["start_sec"] + 0.5
            if u["index"] == 7:
                row["raw_start_topk_probabilities"] = [0.6, 0.2]
            else:
                row["raw_start_topk_probabilities"] = [0.9]
            rows.append(row)
        segments = _segments_with_light_merge(unit_states)
        return _assemble_record(item, text, len(unit_states) * 0.4, rows, unit_states, segments)

    return adapter


def _load_pipeline(cfg: dict) -> dict:
    import argparse

    import numpy as np  # noqa: F401
    import soundfile as sf
    from scripts.demo.align_qwen_fa_serial_demo import infer_slice, load_model
    from lyricalign.research_transition_recovery_detector.detector_features import (  # noqa: E402
        FEATURE_NAMES,
        extract_unit_features,
    )
    from lyricalign.research_transition_recovery_detector.train_detector_helpers import (  # noqa: E402
        predict_p_bad,
    )

    model_revision = cfg.get("model_revision", identity.MODEL_REVISION)
    cache_dir = cfg.get("cache_dir", str(identity.DATA_ROOT / "models/hf_cache"))
    device = cfg.get("device", "cuda:0")
    checkpoint = Path(cfg["checkpoint_path"]) if cfg.get("checkpoint_path") else Path(identity.CHECKPOINT_PATH)
    detector_path = Path(cfg.get("detector_path") or str(
        identity.REPO_ROOT / "models/transition_recovery_detector_20260808_corrected/detector_mlp.pkl"))
    with open(detector_path, "rb") as f:
        detector = pickle.load(f)
    feature_names = tuple(detector.get("feature_names") or FEATURE_NAMES)

    model_args = argparse.Namespace(
        model="Qwen/Qwen3-ForcedAligner-0.6B-hf", revision=model_revision,
        cache_dir=cache_dir, local_files_only=True, device=device,
    )
    processor, model = load_model(model_args, "lora", checkpoint)
    infer_args = argparse.Namespace(
        timestamp_segment_sec=0.08, decoder_kind="raw", decoder_top_k=8, decoder_beam_size=96,
        research_infer_cache_root=cfg.get("infer_cache_root"),
        research_model_identity={"kind": "lora"}, device=device,
    )

    def read_audio(path: Path) -> np.ndarray:
        audio, sr = sf.read(str(path), dtype="float32")
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        if sr != 16000:
            import scipy.signal as sig

            audio = sig.resample_poly(audio, 16000, sr).astype(np.float32)
        return audio

    def run(document, audio: np.ndarray) -> list[dict]:
        rows, _ = infer_slice(
            processor=processor, model=model, audio=audio, document=document,
            character_start=0, character_end=len(document.characters),
            global_audio_offset_sec=0.0, args=infer_args,
        )
        return rows

    return {
        "read_audio": read_audio,
        "run": run,
        "detector": detector,
        "feature_names": feature_names,
        "extract_unit_features": extract_unit_features,
        "predict_p_bad": predict_p_bad,
    }


def _default_detector_adapter(cfg: dict):
    """Real detector adapter: infer_slice + frozen Raw thresholds + light_merge."""
    pipeline = _load_pipeline(cfg)

    def adapter(item: dict) -> dict:
        audio = pipeline["read_audio"](item["audio"])
        text = item["txt"].read_text(encoding="utf-8-sig")
        try:
            document = _parse_document(text, item["lang"])
        except Exception:  # noqa: BLE001
            document = _parse_document(text, "Chinese")
        duration = float(len(audio) / 16000)
        rows = pipeline["run"](document, audio)
        feats = [pipeline["extract_unit_features"](r) for r in rows]
        p_bad = pipeline["predict_p_bad"](pipeline["detector"], feats, pipeline["feature_names"])
        unit_states = []
        for i, (row, pp) in enumerate(zip(rows, p_bad)):
            unit_states.append({
                "index": i,
                "text": document.characters[i].text,
                "start_sec": float(row.get("fixed_global_start_sec", 0.0)),
                "end_sec": float(row.get("fixed_global_end_sec", 0.0)),
                "state": _tristate(float(pp)),
                "p_bad": float(pp),
            })
        segments = _segments_with_light_merge(unit_states)
        return _assemble_record(item, text, duration, rows, unit_states, segments)

    return adapter


def run_stage(run_root, cfg_path, *, top_k: int = 20, limit: int | None = None) -> dict:
    """Stage 04 end-to-end: summary -> suspicious windows -> no-GT behavior rows."""
    run_root = Path(run_root)
    cfg = json.loads(Path(cfg_path).read_text(encoding="utf-8"))
    if limit is None:
        limit = cfg.get("limit")
    adapter_mode = cfg.get("adapter", "default")
    if adapter_mode == "mock":
        adapter = _mock_detector_adapter(cfg)
    else:
        adapter = _default_detector_adapter(cfg)
    items = discover_items(list(cfg.get("demo_roots", [])) + list(cfg.get("extra_roots", [])))
    if limit:
        items = items[: int(limit)]
    summary = detector_summary(items, adapter)
    suspicious = select_suspicious(summary, top_k=top_k, min_per_lang=cfg.get("min_per_lang", 2))
    detector_state = cfg.get("detector_state") or {
        "kind": "standardized_logistic", "combo": "R", "merge": "light_merge",
    }
    requests = build_demo_requests(suspicious, items, detector_state=detector_state)
    out = run_root / "04_test_demo"
    out.mkdir(parents=True, exist_ok=True)
    env = _envelope("TEST_DEMO_DETECTOR_SUMMARY_v1", cfg)
    summary["generated_at_utc"] = env["generated_at_utc"]
    summary["result_status"] = "ok"
    summary["inputs"] = env["inputs"]
    summary["command"] = env["command"]
    summary.setdefault("n_windows", len(suspicious))
    summary.setdefault("n_requests", len(requests))
    _write_json(out / "TEST_DEMO_DETECTOR_SUMMARY.json", summary)
    rows_out = [{k: v for k, v in w.items() if k != "song_record"} for w in suspicious]
    _write_jsonl(out / "TEST_DEMO_SUSPICIOUS_WINDOWS.jsonl", rows_out)
    _write_jsonl(out / "TEST_DEMO_REALIGN_BEHAVIOR.jsonl", requests)
    return summary
