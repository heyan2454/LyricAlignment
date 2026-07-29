"""Character-level diagnostic plotting for inline-realign experiments.

The module deliberately renders alignment units as glyphs instead of long text
lists.  It supports zero/negative durations, overlap lane packing, window/core
boundaries, realign context trials and fixed-scale pages for later video reuse.
"""
from __future__ import annotations

import colorsys
import math
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable


def row_index(row: dict[str, Any]) -> int:
    return int(row.get("global_character_index", row.get("character_index", -1)))


def row_text(row: dict[str, Any]) -> str:
    return str(row.get("display_text") or row.get("alignment_unit") or row.get("character") or "")


_VISUAL_TIME_FIELD_PAIRS = (
    ("start_sec", "end_sec", "canonical"),
    ("selected_start_sec", "selected_end_sec", "selected"),
    ("fixed_global_start_sec", "fixed_global_end_sec", "fixed_global"),
    ("official_fixed_global_start_sec", "official_fixed_global_end_sec", "official_fixed_global"),
    ("raw_global_start_sec", "raw_global_end_sec", "raw_global"),
)


def canonical_visual_row(row: dict[str, Any]) -> dict[str, Any]:
    """Project any supported alignment-stage row to ``start_sec/end_sec``.

    Local realign/context-trial payloads may retain stage-specific timing fields
    even though normal alignment artifacts already expose canonical timing.
    Visualization must accept both schemas, while still failing loudly when no
    complete global timing pair exists.
    """
    result = dict(row)
    for start_key, end_key, source in _VISUAL_TIME_FIELD_PAIRS:
        start = result.get(start_key)
        end = result.get(end_key)
        if start is None or end is None:
            continue
        result["start_sec"] = float(start)
        result["end_sec"] = float(end)
        if source != "canonical":
            result.setdefault("visual_timing_source", source)
        return result
    index = result.get("global_character_index", result.get("character_index"))
    available = sorted(key for key, value in result.items() if value is not None and key.endswith("_sec"))
    raise KeyError(
        f"visual row {index!r} lacks a complete supported global timing pair; "
        f"available timing fields={available}"
    )


def ordered_rows(payload_or_rows: dict[str, Any] | Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = payload_or_rows.get("characters", []) if isinstance(payload_or_rows, dict) else payload_or_rows
    return sorted((canonical_visual_row(dict(row)) for row in rows), key=row_index)


def character_color(index: int, alpha: float = 1.0) -> tuple[float, float, float, float]:
    # Golden-ratio stepping avoids near-identical adjacent hues while remaining
    # deterministic across every model/figure for the same lyric index.
    hue = (max(index, 0) * 0.6180339887498949) % 1.0
    red, green, blue = colorsys.hsv_to_rgb(hue, 0.72, 0.92)
    return red, green, blue, alpha


def duration_bin_labels() -> list[str]:
    return ["<0", "=0", "(0,20]", "(20,40]", "(40,80]", "(80,120]", "(120,200]", "(200,400]", "(400,800]", ">800"]


def duration_pmf(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    labels = duration_bin_labels()
    counts = [0 for _ in labels]
    durations_ms: list[float] = []
    for row in rows:
        value = (float(row["end_sec"]) - float(row["start_sec"])) * 1000.0
        durations_ms.append(value)
        if value < -1e-9: position = 0
        elif abs(value) <= 1e-9: position = 1
        elif value <= 20: position = 2
        elif value <= 40: position = 3
        elif value <= 80: position = 4
        elif value <= 120: position = 5
        elif value <= 200: position = 6
        elif value <= 400: position = 7
        elif value <= 800: position = 8
        else: position = 9
        counts[position] += 1
    total = len(durations_ms)
    return {
        "labels": labels,
        "counts": counts,
        "probabilities": [value / total if total else 0.0 for value in counts],
        "unit_count": total,
        "negative_count": counts[0],
        "zero_count": counts[1],
    }


def structural_counts(rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    rows = ordered_rows(rows)
    negative = zero = start_regression = end_regression = overlap = 0
    previous_start = previous_end = None
    for row in rows:
        start = float(row["start_sec"]); end = float(row["end_sec"])
        negative += end < start - 1e-9
        zero += end <= start + 1e-9
        if previous_start is not None:
            start_regression += start < previous_start - 1e-9
        if previous_end is not None:
            end_regression += end < previous_end - 1e-9
            overlap += start < previous_end - 1e-9
        previous_start, previous_end = start, end
    return {
        "negative_duration_count": int(negative), "zero_duration_count": int(zero),
        "start_regression_count": int(start_regression), "end_regression_count": int(end_regression),
        "inter_unit_overlap_count": int(overlap),
    }


DEFAULT_PLOT_FONT = "Noto Sans CJK SC"


@lru_cache(maxsize=16)
def _resolve_plot_font(font: str | None) -> str:
    """Resolve and register the exact font face used by every plotting API.

    Static rendering helpers are called both from the production visualizer and
    directly from tests or one-off diagnostics.  Font correctness must therefore
    be a contract of the low-level plotting API, rather than depending on an
    outer entry point having already registered the indexed TTC face.
    """
    from .media_render import detect_font

    return detect_font(font or DEFAULT_PLOT_FONT)


def import_plotting(font: str | None = None):
    import matplotlib
    matplotlib.use("Agg")
    resolved_font = _resolve_plot_font(font)
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyArrowPatch, Rectangle
    matplotlib.rcParams["font.family"] = [resolved_font]
    matplotlib.rcParams["font.sans-serif"] = [resolved_font]
    matplotlib.rcParams["axes.unicode_minus"] = False
    return plt, Rectangle, FancyArrowPatch


def _visible_rows(rows: Iterable[dict[str, Any]], start: float, end: float) -> list[dict[str, Any]]:
    result = []
    for row in rows:
        left = min(float(row["start_sec"]), float(row["end_sec"]))
        right = max(float(row["start_sec"]), float(row["end_sec"]))
        if right >= start and left <= end:
            result.append(dict(row))
    return sorted(result, key=lambda row: (min(float(row["start_sec"]), float(row["end_sec"])), row_index(row)))


def assign_lanes(rows: Iterable[dict[str, Any]], *, minimum_width: float = 0.08) -> tuple[list[tuple[dict[str, Any], int]], int]:
    lane_ends: list[float] = []
    assigned: list[tuple[dict[str, Any], int]] = []
    for row in rows:
        left = min(float(row["start_sec"]), float(row["end_sec"]))
        right = max(float(row["start_sec"]), float(row["end_sec"]))
        visual_right = max(right, left + minimum_width)
        lane = next((i for i, lane_end in enumerate(lane_ends) if left >= lane_end + 0.015), None)
        if lane is None:
            lane = len(lane_ends); lane_ends.append(visual_right)
        else:
            lane_ends[lane] = visual_right
        assigned.append((row, lane))
    return assigned, max(1, len(lane_ends))


def draw_windows(ax: Any, windows: list[dict[str, Any]], *, start: float, end: float, y_min: float, y_max: float) -> None:
    for position, window in enumerate(windows):
        core_start = float(window.get("core_start_sec", 0.0)); core_end = float(window.get("core_end_sec", core_start))
        input_start = float(window.get("effective_input_start_sec", window.get("input_start_sec", core_start)))
        input_end = float(window.get("input_end_sec", window.get("effective_input_end_sec", core_end)))
        if core_end < start or core_start > end:
            continue
        ax.axvspan(max(start, core_start), min(end, core_end), alpha=0.055 if position % 2 == 0 else 0.10, zorder=0)
        for boundary in (input_start, input_end):
            if start <= boundary <= end:
                ax.axvline(boundary, linestyle=":", linewidth=0.8, alpha=0.55, zorder=1)
        if start <= core_start <= end:
            ax.axvline(core_start, linewidth=1.6, alpha=0.75, zorder=1)
            ax.text(core_start + 0.02, y_max - 0.12, f"窗{window.get('window_index')}", fontsize=7, va="top", clip_on=True)
        policy = str(window.get("window_plan_policy") or "")
        if "strict" in policy:
            for boundary in (window.get("strict_region_start_sec"), window.get("strict_region_end_sec")):
                if boundary is not None and start <= float(boundary) <= end:
                    ax.axvline(float(boundary), linewidth=3.0, alpha=0.75, zorder=1)


def _unpack_track(track: tuple[Any, ...]) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]] | None]:
    if len(track) == 2:
        label, rows = track
        return str(label), list(rows), None
    if len(track) == 3:
        label, rows, windows = track
        return str(label), list(rows), list(windows or [])
    raise ValueError(f"timeline track must have 2 or 3 values, got {len(track)}")


def draw_track_windows(
    ax: Any, windows: list[dict[str, Any]], *, start: float, end: float,
    y_bottom: float, y_top: float,
) -> None:
    """Draw one branch's input/core boundaries only inside its own row."""
    for position, window in enumerate(windows):
        core_start=float(window.get("core_start_sec",0.0));core_end=float(window.get("core_end_sec",core_start))
        input_start=float(window.get("effective_input_start_sec",window.get("input_start_sec",core_start)))
        input_end=float(window.get("input_end_sec",window.get("effective_input_end_sec",core_end)))
        if core_end < start or core_start > end: continue
        left=max(start,core_start);right=min(end,core_end)
        if right>left:
            ax.fill_between([left,right],y_bottom,y_top,alpha=0.055 if position%2==0 else 0.10,zorder=0)
        for boundary in (input_start,input_end):
            if start<=boundary<=end:
                ax.vlines(boundary,y_bottom,y_top,linestyle=":",linewidth=0.75,alpha=0.60,zorder=1)
        for boundary in (core_start,core_end):
            if start<=boundary<=end:
                ax.vlines(boundary,y_bottom,y_top,linewidth=1.4,alpha=0.78,zorder=1)
        if start<=core_start<=end:
            ax.text(core_start+0.015,y_top-0.02,f"窗{window.get('window_index')}",fontsize=6,va="top",clip_on=True)
        if "strict" in str(window.get("window_plan_policy") or ""):
            for boundary in (window.get("strict_region_start_sec"),window.get("strict_region_end_sec")):
                if boundary is not None and start<=float(boundary)<=end:
                    ax.vlines(float(boundary),y_bottom,y_top,linewidth=2.8,alpha=0.90,zorder=1)


def _row_display_label(row: dict[str, Any]) -> str:
    return f"{row_index(row)}:{row_text(row)}"


class _CollapsedGroup(dict):
    pass


def _collapsed_group_label(group: dict[str, Any]) -> str:
    start_index = int(group["start_index"])
    end_index = int(group["end_index"])
    start_text = str(group["start_text"] or "")
    end_text = str(group["end_text"] or start_text)
    prefix = "坍缩" if group["kind"] == "negative" else "零时长"
    return f"{prefix}[{start_index}-{end_index}] {start_text}-{end_text}" if end_index != start_index else f"{prefix}[{start_index}] {start_text}"


def _group_collapsed_rows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    positive: list[dict[str, Any]] = []
    collapsed: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for row in rows:
        start_sec = float(row["start_sec"])
        end_sec = float(row["end_sec"])
        kind = "negative" if end_sec < start_sec - 1e-9 else "zero" if end_sec <= start_sec + 1e-9 else None
        if kind is None:
            if current is not None:
                collapsed.append(current)
                current = None
            positive.append(row)
            continue
        idx = row_index(row)
        if current is None or current["kind"] != kind or idx != int(current["end_index"]) + 1:
            if current is not None:
                collapsed.append(current)
            current = {
                "kind": kind,
                "start_index": idx,
                "end_index": idx,
                "start_text": row_text(row),
                "end_text": row_text(row),
                "times": [start_sec, end_sec],
            }
        else:
            current["end_index"] = idx
            current["end_text"] = row_text(row)
            current["times"].extend([start_sec, end_sec])
    if current is not None:
        collapsed.append(current)
    for group in collapsed:
        times = [float(value) for value in group.pop("times")]
        center = sum(times) / max(1, len(times))
        group["start_sec"] = center
        group["end_sec"] = center
    return positive, collapsed


def draw_track(
    ax: Any, *, rows: list[dict[str, Any]], label: str, y_top: float,
    start: float, end: float, font_size: float = 8.0,
) -> float:
    _, Rectangle, FancyArrowPatch = import_plotting(None)
    visible = _visible_rows(rows, start, end)
    normal_rows, collapsed_groups = _group_collapsed_rows(visible)
    assigned, lane_count = assign_lanes(normal_rows)
    collapsed_assigned, collapsed_lane_count = assign_lanes(collapsed_groups, minimum_width=0.02)
    lane_height = 0.32
    for row, lane in assigned:
        x0 = float(row["start_sec"]); x1 = float(row["end_sec"])
        y = y_top - lane * lane_height
        color = character_color(row_index(row), 0.80)
        text = _row_display_label(row)
        width = x1 - x0
        ax.add_patch(Rectangle((x0, y-0.095), width, 0.19, facecolor=color, edgecolor=color,
                               linewidth=0.55, alpha=0.43, zorder=3))
        ax.text((x0+x1)/2, y, text, ha="center", va="center", fontsize=font_size,
                color="black", clip_on=True, zorder=5)
    collapsed_top = y_top - max(0.45, lane_count * lane_height) - 0.10 if collapsed_assigned else y_top
    for group, lane in collapsed_assigned:
        x = float(group["start_sec"])
        y = collapsed_top - lane * lane_height
        text = _collapsed_group_label(group)
        color = "#b22222" if group["kind"] == "negative" else "#8b4513"
        ax.vlines(x, y-0.11, y+0.11, linewidth=2.2, color=color, zorder=4)
        ax.text(x, y+0.13, text, ha="center", va="bottom", fontsize=max(font_size - 0.2, 6.8),
                color=color, clip_on=True, zorder=5)
    block_height = max(0.45, lane_count * lane_height)
    if collapsed_assigned:
        block_height += 0.12 + max(0.45, collapsed_lane_count * lane_height)
    ax.text(start - max(0.18, (end-start)*0.008), y_top - (block_height-0.22)/2, label,
            ha="right", va="center", fontsize=9, fontweight="bold")
    ax.hlines(y_top - block_height - 0.05, start, end, linewidth=0.3, alpha=0.25)
    return block_height + 0.18


def render_timeline_page(
    *, output: Path, tracks: list[tuple[Any, ...]], windows: list[dict[str, Any]],
    start: float, end: float, title: str, font: str | None = None,
    spans: list[dict[str, Any]] | None = None, annotations: list[str] | None = None,
    pixel_width: int = 2800, pixel_height: int | None = None,
    video_layout: bool = False,
) -> dict[str, Any]:
    plt, _, _ = import_plotting(font)
    lane_heights = []
    unpacked_tracks=[_unpack_track(track) for track in tracks]
    for _, rows, _ in unpacked_tracks:
        _, count = assign_lanes(_visible_rows(rows, start, end))
        lane_heights.append(max(0.45, count*0.32)+0.18)
    total_height = sum(lane_heights) + 1.15
    if pixel_height is None:
        pixel_height = max(520, int(total_height * 145))
    fig = plt.figure(figsize=(pixel_width/100, pixel_height/100), dpi=100)
    # Video pages reserve a real subtitle band instead of drawing the model
    # mechanism behind the karaoke overlay.  The timeline remains the visual
    # center while subtitles occupy the lower, intentionally flattened band.
    ax = fig.add_axes([0.07, 0.23, 0.91, 0.66] if video_layout else [0.07, 0.10, 0.91, 0.82])
    y_top = total_height - 0.35
    draw_windows(ax, windows, start=start, end=end, y_min=0, y_max=total_height)
    if spans:
        for span in spans:
            left = span.get("start_sec"); right = span.get("end_sec")
            if left is None or right is None: continue
            left=float(left); right=float(right)
            if right >= start and left <= end:
                kind=str(span.get("kind") or "realign")
                style={
                    "stable_candidate":("#6aa84f",0.045,0.4),
                    "stable_selected_input":("#38761d",0.16,2.0),
                    "stable_selected_commit":("#274e13",0.16,2.0),
                    "realign_accepted":("#3d85c6",0.15,1.8),
                    "realign_rejected":("#cc0000",0.08,1.0),
                }.get(kind,("#674ea7",0.10,1.0))
                color,alpha,linewidth=style
                ax.axvspan(max(start,left),min(end,right),facecolor=color,edgecolor=color,linewidth=linewidth,alpha=alpha,zorder=1)
                # All candidates remain visible as bands; text is reserved for
                # selected anchors and realign decisions to avoid unreadable overlap.
                if kind != "stable_candidate":
                    label = str(span.get("label") or span.get("reason") or "重对齐")
                    ax.text(max(start,left)+0.02,0.08,label,fontsize=7,rotation=90,va="bottom",color=color)
    for label, rows, track_windows in unpacked_tracks:
        _, lane_count=assign_lanes(_visible_rows(rows,start,end))
        block_height=max(0.45,lane_count*0.32)
        if track_windows is not None:
            draw_track_windows(ax,track_windows,start=start,end=end,y_bottom=y_top-block_height-0.04,y_top=y_top+0.12)
        consumed = draw_track(ax, rows=rows, label=label, y_top=y_top, start=start, end=end)
        y_top -= consumed
    ax.set_xlim(start, end); ax.set_ylim(0, total_height)
    ax.set_yticks([]); ax.set_xlabel("全局时间（秒）")
    ax.set_title(title, fontsize=14, fontweight="bold")
    if annotations:
        fig.text(0.075, 0.965, "　|　".join(annotations), ha="left", va="top", fontsize=9)
    ax.grid(axis="x", linewidth=0.35, alpha=0.25)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=100)
    plt.close(fig)
    return {"path": str(output), "start_sec": start, "end_sec": end, "width": pixel_width, "height": pixel_height}


def render_duration_pmf(
    *, output: Path, tracks: list[tuple[str, list[dict[str, Any]]]], title: str, font: str | None = None,
) -> dict[str, Any]:
    plt, _, _ = import_plotting(font)
    labels = duration_bin_labels(); x = list(range(len(labels)))
    width = min(0.78/max(len(tracks),1), 0.22)
    fig, ax = plt.subplots(figsize=(18, 6.5))
    summaries = {}
    for position, (name, rows) in enumerate(tracks):
        summary = duration_pmf(rows); summaries[name] = summary
        offset = (position - (len(tracks)-1)/2)*width
        bars = ax.bar([value+offset for value in x], summary["probabilities"], width=width,
                      label=f"{name}（n={summary['unit_count']}）", alpha=0.80)
        for bin_index in (0,1):
            value=summary["probabilities"][bin_index]
            if value > 0:
                ax.text(x[bin_index]+offset, value+0.003, f"{value:.1%}", ha="center", va="bottom", fontsize=7, rotation=90)
    ax.set_xticks(x, labels); ax.set_ylabel("占全部歌词单位的比例")
    ax.set_xlabel("单字时长区间（毫秒）"); ax.set_title(title, fontweight="bold")
    ax.legend(ncol=min(4,len(tracks)), fontsize=8); ax.grid(axis="y", alpha=0.25)
    fig.tight_layout(); output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=150); plt.close(fig)
    return {"path": str(output), "tracks": summaries}


def _stage_matrix(tracks: list[tuple[str, list[dict[str, Any]]]]) -> tuple[list[int], list[list[float]], list[list[float]], list[str]]:
    maps = [(name, {row_index(row): row for row in rows}) for name, rows in tracks]
    indices = sorted(set().union(*(set(mapping) for _, mapping in maps))) if maps else []
    starts=[]; ends=[]; names=[]
    for name, mapping in maps:
        names.append(name)
        starts.append([float(mapping[i]["start_sec"]) if i in mapping else math.nan for i in indices])
        ends.append([float(mapping[i]["end_sec"]) if i in mapping else math.nan for i in indices])
    return indices, starts, ends, names


def render_inconsistency(
    *, output: Path, tracks: list[tuple[str, list[dict[str, Any]]]], title: str,
    font: str | None = None, heatmap_label: str = "相对跨层中位时间偏差（秒）",
) -> dict[str, Any]:
    plt, _, _ = import_plotting(font)
    import numpy as np
    indices, starts, ends, names = _stage_matrix(tracks)
    fig = plt.figure(figsize=(24, 13))
    grid = fig.add_gridspec(3, 1, height_ratios=[2.2, 1.1, 1.5], hspace=0.18)
    ax1 = fig.add_subplot(grid[0])
    ax2 = fig.add_subplot(grid[1], sharex=ax1)
    ax3 = fig.add_subplot(grid[2], sharex=ax1)
    for name, start_values, end_values in zip(names, starts, ends):
        ax1.plot(indices, start_values, linewidth=1.0, label=f"{name} 起点")
        ax1.plot(indices, end_values, linewidth=1.0, linestyle="--", label=f"{name} 终点")
    ax1.set_ylabel("全局时间（秒）")
    ax1.set_title("歌词序号—起止时间")
    ax1.legend(ncol=min(3, len(names)), fontsize=8)
    ax1.grid(alpha=0.25)
    start_array = np.array(starts, dtype=float)
    end_array = np.array(ends, dtype=float)
    with np.errstate(all="ignore"):
        start_spread = np.nanmax(start_array, axis=0) - np.nanmin(start_array, axis=0)
        end_spread = np.nanmax(end_array, axis=0) - np.nanmin(end_array, axis=0)
    ax2.plot(indices, start_spread, label="起点最大差", linewidth=1.0)
    ax2.plot(indices, end_spread, label="终点最大差", linewidth=1.0, linestyle="--")
    for threshold in (0.16, 0.24, 0.50):
        ax2.axhline(threshold, linewidth=0.8, linestyle=":", label=f"{threshold:.2f}s")
    ax2.set_ylabel("最大差（秒）")
    ax2.set_title("同一歌词单位在不同层次/窗口中的最大差")
    ax2.legend(ncol=5, fontsize=8)
    ax2.grid(alpha=0.25)
    mid = (start_array + end_array) / 2
    median = np.nanmedian(mid, axis=0)
    delta = mid - median[None, :]
    finite = np.abs(delta[np.isfinite(delta)])
    limit = max(0.24, float(np.quantile(finite, 0.95))) if finite.size else 0.24
    left = indices[0] - 0.5 if indices else -0.5
    right = indices[-1] + 0.5 if indices else 0.5
    image = ax3.imshow(
        delta,
        aspect="auto",
        interpolation="nearest",
        cmap="coolwarm",
        vmin=-limit,
        vmax=limit,
        extent=[left, right, len(names) - 0.5, -0.5],
    )
    ax3.set_xlim(left, right)
    ax3.set_yticks(range(len(names)), names)
    ax3.set_xlabel("全局歌词序号")
    ax3.set_title("偏差热力图（灰色为空缺）")
    image.cmap.set_bad("lightgray")
    fig.colorbar(image, ax=ax3, label=heatmap_label, pad=0.01)
    for axis in (ax1, ax2):
        axis.tick_params(labelbottom=False)
        axis.set_xlim(left, right)
    fig.suptitle(title, fontsize=15, fontweight="bold")
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=145, bbox_inches="tight")
    plt.close(fig)
    return {
        "path": str(output),
        "track_count": len(tracks),
        "unit_count": len(indices),
        "max_start_spread_sec": float(np.nanmax(start_spread)) if len(indices) else None,
        "max_end_spread_sec": float(np.nanmax(end_spread)) if len(indices) else None,
    }
