#!/usr/bin/env python3
"""Generate compact, per-item visual diagnostics for inline-realign experiments.

The plots intentionally omit waveforms.  They focus on GT (when available), raw,
baseline/current alignments, experimental realign outputs, decoder/detector
markers, signed timing errors, duration distributions and cross-scale
inconsistency.  Every image is derived from the frozen manifest and is written
under ``items/<item_id>/visuals``.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from lyricalign.demo.media_render import atomic_json, detect_font

PLOT_FONT: str | None = None


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def nested(payload: dict[str, Any], *keys: str, default: Any = None) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


def expected_experimental_alignments(root: Path, item_root: Path) -> list[tuple[str, Path]]:
    resolved = read_json(root / "resolved_config.json")
    source = resolved.get("source_config") if isinstance(resolved.get("source_config"), dict) else {}
    stable_enabled = bool(nested(source, "shadow", "stable_anchor", "enabled", default=True))
    deferred_enabled = bool(nested(source, "shadow", "deferred_realign", "enabled", default=True))
    immediate_enabled = bool(nested(source, "shadow", "deferred_realign", "immediate_inline", default=True))
    expected: list[tuple[str, Path]] = []
    if stable_enabled:
        expected.extend([
            ("Stable inclusive", item_root / "experimental_alignments" / "S1_stable_inclusive" / "alignment.json"),
            ("Stable overlap", item_root / "experimental_alignments" / "S2_stable_left_overlap" / "alignment.json"),
            ("Stable frozen", item_root / "experimental_alignments" / "S3_stable_frozen_overlap" / "alignment.json"),
        ])
    if immediate_enabled:
        expected.append(("Immediate realign", item_root / "experimental_alignments" / "R1_immediate_inline" / "alignment.json"))
    if deferred_enabled:
        expected.extend([
            ("Deferred realign", item_root / "experimental_alignments" / "R2_deferred" / "alignment.json"),
            ("Inline+deferred", item_root / "experimental_alignments" / "R3_inline_deferred" / "alignment.json"),
        ])
    return expected


def require_files(paths: Iterable[Path], *, purpose: str) -> None:
    missing = [str(path) for path in paths if not path.is_file() or path.stat().st_size <= 0]
    if missing:
        raise FileNotFoundError(f"{purpose} missing or empty: {missing}")


def row_index(row: dict[str, Any]) -> int:
    return int(row.get("global_character_index", row.get("character_index", -1)))


def canonical_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return sorted((dict(row) for row in payload.get("characters", [])), key=row_index)


def q(values: Iterable[float], probability: float) -> float | None:
    values = sorted(float(value) for value in values if math.isfinite(float(value)))
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    position = probability * (len(values) - 1)
    lower = math.floor(position); upper = math.ceil(position)
    if lower == upper:
        return values[lower]
    fraction = position - lower
    return values[lower] * (1 - fraction) + values[upper] * fraction


def timing_metrics(predicted: list[dict[str, Any]], gt: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not gt:
        return None
    pred = {row_index(row): row for row in predicted}
    truth = {row_index(row): row for row in gt}
    common = sorted(set(pred) & set(truth))
    if not common:
        return None
    onset_signed = [float(pred[i]["start_sec"]) - float(truth[i]["start_sec"]) for i in common]
    offset_signed = [float(pred[i]["end_sec"]) - float(truth[i]["end_sec"]) for i in common]
    onset_abs = [abs(value) for value in onset_signed]
    offset_abs = [abs(value) for value in offset_signed]
    boundary_abs = onset_abs + offset_abs
    result: dict[str, Any] = {
        "common_unit_count": len(common),
        "onset_mae_sec": statistics.fmean(onset_abs),
        "offset_mae_sec": statistics.fmean(offset_abs),
        "boundary_mae_sec": statistics.fmean(boundary_abs),
        "onset_signed_bias_sec": statistics.fmean(onset_signed),
        "offset_signed_bias_sec": statistics.fmean(offset_signed),
        "onset_median_abs_sec": q(onset_abs, 0.5),
        "offset_median_abs_sec": q(offset_abs, 0.5),
        "boundary_p90_abs_sec": q(boundary_abs, 0.9),
    }
    for tolerance in (0.04, 0.08, 0.16, 0.24):
        key = f"joint_within_{int(tolerance * 1000)}ms_rate"
        result[key] = sum(
            onset_abs[pos] <= tolerance and offset_abs[pos] <= tolerance
            for pos in range(len(common))
        ) / len(common)
    return result


def duration_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    durations = [max(0.0, float(row["end_sec"]) - float(row["start_sec"])) for row in rows]
    positive = [value for value in durations if value > 1e-9]
    local_ratios: list[float] = []
    for index, duration in enumerate(durations):
        neighborhood = [
            value for value in durations[max(0, index - 5): index + 6]
            if value > 1e-9
        ]
        median = q(neighborhood, 0.5)
        if duration > 1e-9 and median and median > 1e-9:
            local_ratios.append(duration / median)
    zero_runs: list[int] = []
    run = 0
    for duration in durations:
        if duration <= 1e-9:
            run += 1
        elif run:
            zero_runs.append(run); run = 0
    if run:
        zero_runs.append(run)
    probabilities = (0.001, 0.005, 0.01, 0.025, 0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 0.99)
    return {
        "unit_count": len(rows),
        "zero_duration_count": len(durations) - len(positive),
        "zero_duration_rate": (len(durations) - len(positive)) / len(durations) if durations else 0.0,
        "positive_duration_quantiles_sec": {f"p{probability * 100:g}": q(positive, probability) for probability in probabilities},
        "local_duration_ratio_quantiles": {f"p{probability * 100:g}": q(local_ratios, probability) for probability in probabilities},
        "max_zero_run": max(zero_runs, default=0),
        "zero_run_count": len(zero_runs),
    }


def _import_plotting():
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import Rectangle
        if PLOT_FONT:
            matplotlib.rcParams["font.family"] = [PLOT_FONT]
            matplotlib.rcParams["axes.unicode_minus"] = False
    except ImportError as exc:
        raise RuntimeError("visualization requires matplotlib; install it in the experiment environment") from exc
    return plt, Rectangle


def _text(row: dict[str, Any]) -> str:
    return str(row.get("display_text") or row.get("alignment_unit") or row.get("character") or "")


def plot_timeline(
    *, output: Path, tracks: list[tuple[str, list[dict[str, Any]]]], gt: list[dict[str, Any]],
    windows: list[dict[str, Any]], stable: list[dict[str, Any]], detector: list[dict[str, Any]],
    start: float, end: float,
) -> None:
    plt, Rectangle = _import_plotting()
    figure_height = max(3.6, 0.85 * (len(tracks) + 1))
    fig, ax = plt.subplots(figsize=(16, figure_height))
    track_height = 0.58
    for track_index, (name, rows) in enumerate(tracks):
        y = len(tracks) - 1 - track_index
        for row in rows:
            row_start = float(row["start_sec"]); row_end = float(row["end_sec"])
            if row_end < start or row_start > end:
                continue
            width = max(0.006, row_end - row_start)
            hatch = "////" if row_end <= row_start + 1e-9 else None
            ax.add_patch(Rectangle((row_start, y - track_height / 2), width, track_height, fill=True, alpha=0.50, hatch=hatch))
            if name == "GT" and width >= 0.06:
                ax.text((row_start + row_end) / 2, y, _text(row), ha="center", va="center", fontsize=7, clip_on=True)
        ax.text(start - max(0.25, (end - start) * 0.012), y, name, ha="right", va="center", fontsize=9, fontweight="bold")
    for row in gt:
        for boundary in (float(row["start_sec"]), float(row["end_sec"])):
            if start <= boundary <= end:
                ax.axvline(boundary, linestyle="--", linewidth=0.45, alpha=0.28)
    marker_y = -0.75
    for window in windows:
        core_start = float(window.get("core_start_sec", 0.0)); core_end = float(window.get("core_end_sec", 0.0))
        if core_end >= start and core_start <= end:
            ax.axvline(core_start, linewidth=0.7, alpha=0.30)
            ax.text(core_start, marker_y, f"W{window.get('window_index')}", rotation=90, va="bottom", fontsize=6)
    for segment in stable:
        segment_start = segment.get("start_sec"); segment_end = segment.get("end_sec")
        if segment_start is not None and segment_end is not None and float(segment_end) >= start and float(segment_start) <= end:
            ax.add_patch(Rectangle((float(segment_start), marker_y - 0.18), max(0.01, float(segment_end)-float(segment_start)), 0.16, alpha=0.5))
    for span in detector:
        left = span.get("start_sec"); right = span.get("end_sec")
        if left is None or right is None:
            continue
        if float(right) >= start and float(left) <= end:
            ax.axvspan(float(left), float(right), alpha=0.10)
    ax.set_xlim(start, end)
    ax.set_ylim(-1.05, len(tracks) - 0.25)
    ax.set_yticks([])
    ax.set_xlabel("Time (s)")
    ax.set_title(f"Alignment timeline {start:.1f}–{end:.1f} s | GT boundaries are dashed")
    fig.tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=145)
    plt.close(fig)


def plot_errors(output: Path, gt: list[dict[str, Any]], tracks: list[tuple[str, list[dict[str, Any]]]]) -> None:
    plt, _ = _import_plotting()
    truth = {row_index(row): row for row in gt}
    fig, ax = plt.subplots(figsize=(16, 5.2))
    plotted = 0
    for name, rows in tracks:
        pred = {row_index(row): row for row in rows}
        common = sorted(set(pred) & set(truth))
        if not common:
            continue
        times = [float(truth[i]["start_sec"]) for i in common]
        onset = [float(pred[i]["start_sec"]) - float(truth[i]["start_sec"]) for i in common]
        offset = [float(pred[i]["end_sec"]) - float(truth[i]["end_sec"]) for i in common]
        ax.plot(times, onset, linewidth=0.8, alpha=0.75, label=f"{name} onset")
        ax.plot(times, offset, linewidth=0.8, alpha=0.75, linestyle="--", label=f"{name} offset")
        plotted += 1
    ax.axhline(0.0, linewidth=0.8)
    ax.set_xlabel("GT time (s)"); ax.set_ylabel("Prediction - GT (s)")
    ax.set_title("Signed onset/offset error")
    if plotted:
        ax.legend(ncol=2, fontsize=7)
    ax.grid(True, linewidth=0.3, alpha=0.35)
    fig.tight_layout(); output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=145); plt.close(fig)


def plot_durations(output: Path, tracks: list[tuple[str, list[dict[str, Any]]]], bin_ms: float, max_ms: float) -> None:
    plt, _ = _import_plotting()
    fig, axes = plt.subplots(1, 2, figsize=(16, 5.0))
    bins = max(10, int(max_ms / max(bin_ms, 0.5)))
    for name, rows in tracks:
        durations_ms = [max(0.0, (float(row["end_sec"]) - float(row["start_sec"])) * 1000.0) for row in rows]
        positive = [value for value in durations_ms if value > 1e-6]
        zero_rate = (len(durations_ms) - len(positive)) / len(durations_ms) if durations_ms else 0.0
        if positive:
            axes[0].hist([min(value, max_ms) for value in positive], bins=bins, range=(0, max_ms), histtype="step", density=True, label=f"{name} zero={zero_rate:.1%}")
            ordered = sorted(positive)
            axes[1].plot(ordered, [(index + 1) / len(ordered) for index in range(len(ordered))], label=f"{name} zero={zero_rate:.1%}")
    axes[0].set_title("Positive unit-duration density"); axes[0].set_xlabel("Duration (ms; clipped)")
    axes[1].set_title("Positive unit-duration ECDF"); axes[1].set_xlabel("Duration (ms)"); axes[1].set_ylabel("Cumulative proportion")
    for ax in axes:
        ax.grid(True, linewidth=0.3, alpha=0.35); ax.legend(fontsize=7)
    fig.tight_layout(); output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=145); plt.close(fig)


def plot_inconsistency(output: Path, reference: list[dict[str, Any]], comparisons: list[tuple[str, list[dict[str, Any]]]]) -> dict[str, Any]:
    plt, _ = _import_plotting()
    ref = {row_index(row): row for row in reference}
    fig, ax = plt.subplots(figsize=(16, 4.8))
    summary: dict[str, Any] = {}
    for name, rows in comparisons:
        other = {row_index(row): row for row in rows}
        common = sorted(set(ref) & set(other))
        times = [float(ref[index]["start_sec"]) for index in common]
        values = [max(abs(float(ref[index]["start_sec"]) - float(other[index]["start_sec"])), abs(float(ref[index]["end_sec"]) - float(other[index]["end_sec"]))) for index in common]
        if values:
            ax.plot(times, values, linewidth=0.9, label=name)
        summary[name] = {
            "common_unit_count": len(common),
            "mean_max_boundary_difference_sec": statistics.fmean(values) if values else None,
            "median_max_boundary_difference_sec": q(values, 0.5),
            "p90_max_boundary_difference_sec": q(values, 0.9),
            "over_160ms_rate": sum(value > 0.16 for value in values) / len(values) if values else None,
            "over_240ms_rate": sum(value > 0.24 for value in values) / len(values) if values else None,
        }
    ax.axhline(0.16, linestyle="--", linewidth=0.7); ax.axhline(0.24, linestyle=":", linewidth=0.7)
    ax.set_xlabel("Reference time (s)"); ax.set_ylabel("Max boundary difference (s)")
    ax.set_title("Cross-stage / cross-scale inconsistency")
    ax.grid(True, linewidth=0.3, alpha=0.35); ax.legend(fontsize=8)
    fig.tight_layout(); output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=145); plt.close(fig)
    return summary


def detector_spans(payload: dict[str, Any], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_index = {row_index(row): row for row in rows}
    spans: list[dict[str, Any]] = []
    for window in payload.get("window_trace", []):
        diagnostic = window.get("precommit_diagnostic") or {}
        for span in diagnostic.get("anomaly_spans", []) or []:
            start_index = int(span.get("character_start", -1)); end_index = int(span.get("character_end", -1))
            selected = [by_index[index] for index in range(start_index, end_index + 1) if index in by_index]
            if selected:
                spans.append({**span, "start_sec": min(float(row["start_sec"]) for row in selected), "end_sec": max(float(row["end_sec"]) for row in selected)})
    return spans


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--experiment-root", type=Path, required=True)
    p.add_argument("--comparison-branches", default="RAW_B2,B0_60_fixed_official,B1_30_fixed_official,B2_30_silence_official")
    p.add_argument("--timeline-page-seconds", type=float, default=60.0)
    p.add_argument("--duration-bin-ms", type=float, default=5.0)
    p.add_argument("--duration-max-ms", type=float, default=500.0)
    p.add_argument("--font", default="Noto Sans CJK SC")
    return p


def main() -> int:
    global PLOT_FONT
    args = parser().parse_args()
    PLOT_FONT = detect_font(args.font)
    manifest = read_jsonl(args.manifest.expanduser().resolve())
    root = args.experiment_root.expanduser().resolve()
    requested = [value.strip() for value in args.comparison_branches.split(",") if value.strip()]
    results: list[dict[str, Any]] = []; failures: list[dict[str, Any]] = []
    for ordinal, item in enumerate(manifest, 1):
        item_id = str(item["item_id"]); item_root = root / "items" / item_id; output_root = item_root / "visuals"
        try:
            b2_path = item_root / "branches" / "B2_30_silence_official" / "alignment.json"
            require_files([b2_path], purpose="B2 alignment")
            b2 = read_json(b2_path); b2_rows = canonical_rows(b2)
            tracks: list[tuple[str, list[dict[str, Any]]]] = []
            gt = read_jsonl(Path(str(item["gt_path"])).resolve()) if item.get("gt_path") else []
            if gt:
                tracks.append(("GT", gt))
            seen: set[str] = set()
            baseline_matrix = str(item.get("variant_set", "official_primary")) == "baseline_matrix"
            for token in requested:
                if token == "RAW_B2":
                    path = item_root / "branches" / "B2_30_silence_official" / "alignment.raw.json"
                    name = "Raw"
                else:
                    path = item_root / "branches" / token / "alignment.json"
                    name = token
                required = token in {"RAW_B2", "B2_30_silence_official"} or baseline_matrix
                if required:
                    require_files([path], purpose=f"requested comparison branch {token}")
                if not path.is_file():
                    continue
                payload = read_json(path)
                if payload and name not in seen:
                    tracks.append((name, canonical_rows(payload))); seen.add(name)
            experimental = expected_experimental_alignments(root, item_root)
            require_files([path for _, path in experimental], purpose="expected stable/realign alignments")
            for name, path in experimental:
                tracks.append((name, canonical_rows(read_json(path))))
            duration = float(b2.get("summary", {}).get("audio_duration_sec", 0.0))
            stable = list((b2.get("stable_segments") or {}).get("segments") or [])
            detector = detector_spans(b2, b2_rows)
            windows = list(b2.get("window_trace") or [])
            page_sec = max(10.0, args.timeline_page_seconds)
            page_paths: list[str] = []
            page_count = max(1, math.ceil(duration / page_sec))
            for page in range(page_count):
                page_start = page * page_sec; page_end = min(duration, (page + 1) * page_sec)
                path = output_root / "timeline" / f"page_{page:03d}_{page_start:.0f}_{page_end:.0f}s.png"
                plot_timeline(output=path, tracks=tracks, gt=gt, windows=windows, stable=stable, detector=detector, start=page_start, end=page_end)
                page_paths.append(str(path))
            duration_path = output_root / "duration_distribution.png"
            plot_durations(duration_path, tracks, args.duration_bin_ms, args.duration_max_ms)
            metrics = {name: {"timing": timing_metrics(rows, gt), "duration": duration_summary(rows)} for name, rows in tracks}
            error_path = None
            if gt:
                error_path = output_root / "signed_error.png"; plot_errors(error_path, gt, [(name, rows) for name, rows in tracks if name != "GT"])
            comparison_rows = [(name, rows) for name, rows in tracks if name not in {"GT", "B2_30_silence_official"}]
            inconsistency_path = output_root / "inconsistency.png"
            inconsistency = plot_inconsistency(inconsistency_path, b2_rows, comparison_rows)
            payload = {
                "schema_version": "inline_realign_visual_analysis_v1",
                "item_id": item_id, "manifest_order": item.get("manifest_order"),
                "tracks": [name for name, _ in tracks], "timeline_pages": page_paths,
                "duration_plot": str(duration_path), "signed_error_plot": None if error_path is None else str(error_path),
                "inconsistency_plot": str(inconsistency_path), "metrics": metrics,
                "inconsistency": inconsistency, "detector_span_count": len(detector),
                "human_review_entry": str(output_root / "HUMAN_REVIEW.md"),
            }
            review = output_root / "HUMAN_REVIEW.md"
            if not review.exists():
                review.parent.mkdir(parents=True, exist_ok=True)
                review.write_text("# Human / AI review entry\n\nThis file is intentionally left open for direct notes or later AI-assisted review.\n", encoding="utf-8")
            analysis_path = output_root / "visual_analysis.json"
            expected_outputs = [
                *(Path(value) for value in page_paths), duration_path, inconsistency_path,
                review,
            ]
            if error_path is not None:
                expected_outputs.append(error_path)
            require_files(expected_outputs, purpose="visualization outputs")
            payload["expected_output_count"] = len(expected_outputs) + 1
            atomic_json(analysis_path, payload)
            require_files([analysis_path], purpose="visual analysis JSON")
            results.append(payload)
            print(json.dumps({"stage": "visualize", "item": f"{ordinal}/{len(manifest)}", "item_id": item_id, "status": "complete"}, ensure_ascii=False), flush=True)
        except Exception as exc:
            failure = {"item_id": item_id, "error": f"{type(exc).__name__}: {exc}"}; failures.append(failure)
            print(json.dumps({"stage": "visualize", **failure, "status": "failed"}, ensure_ascii=False), flush=True)
    summary = {
        "schema_version": "inline_realign_visual_batch_v2_strict_expected_artifacts", "item_count": len(manifest),
        "complete_count": len(results), "failed_count": len(failures),
        "results": results, "failures": failures,
    }
    atomic_json(root / "visualization_summary.json", summary)
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
