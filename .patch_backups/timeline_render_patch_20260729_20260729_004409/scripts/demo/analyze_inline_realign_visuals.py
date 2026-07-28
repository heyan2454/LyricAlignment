#!/usr/bin/env python3
"""Generate Chinese, character-level static diagnostics and reusable video pages.

Static analysis is intentionally completed before slow video encoding.  Every
required figure is checked strictly.  Demo items additionally receive fixed-
scale PNG pages that the render stage can resume/encode without rebuilding any
model output.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from lyricalign.demo.media_render import atomic_json, detect_font
from lyricalign.demo.run_state import canonical_hash, file_identity, output_snapshots, snapshots_match
from lyricalign.demo.visual_diagnostics import (
    ordered_rows, render_duration_pmf, render_inconsistency, render_timeline_page,
    row_index, row_text, structural_counts,
)


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (OSError, json.JSONDecodeError):
        return {}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file(): return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def nested(payload: dict[str, Any], *keys: str, default: Any = None) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict) or key not in current: return default
        current = current[key]
    return current


def require_files(paths: list[Path], purpose: str) -> None:
    missing=[str(path) for path in paths if not path.is_file() or path.stat().st_size <= 0]
    if missing: raise FileNotFoundError(f"{purpose} 缺失或为空: {missing}")


BRANCH_LABELS = {
    "B0_60_fixed_official": "60秒固定窗",
    "B1_30_fixed_official": "30秒固定窗",
    "B2_30_silence_official": "30秒静音吸附",
    "B3_30_silence_raw_control": "30秒原始输出控制推进",
    "B4_60_silence_official": "60秒静音吸附",
    "B5_30_strict_silence_official": "30秒严格静音边界",
    "B6_60_strict_silence_official": "60秒严格静音边界",
    "C0_30_silence_compressed_diagnostic": "30秒全静音压缩（诊断）",
    "C1_60_silence_compressed_diagnostic": "60秒全静音压缩（诊断）",
}
STABLE_LABELS = {
    "S0_stable_anchor_only": "原窗口范围重跑，仅冻结稳定区",
    "S1_stable_sync_exact": "从稳定区同步开始",
    "S2_stable_sync_minus2": "稳定区前2字同步开始",
    "S3_stable_sync_minus4": "稳定区前4字同步开始",
}
REALIGN_LABELS = {
    "R1_immediate_inline": "立即局部重对齐",
    "R2_deferred": "等待后续右边界",
    "R3_inline_deferred": "立即+等待后续",
    "R4_context_median_fused": "三上下文边界中位融合",
}


DISPLAY_TEXT = {
    "gt_oracle_improved_shadow": "GT显示改善，仅影子接受",
    "automatic_zero_duration_relaxed_gate_accepted": "零时长减少且未引入新异常，影子接受",
    "automatic_structure_nonincrease_gate_accepted": "三种上下文一致且结构不恶化，影子接受",
    "three_context_disagreement": "三种上下文结果差异过大",
    "invalid_or_unsafe_splice": "替换后出现不安全的时间结构",
    "gt_not_improved": "GT未显示改善",
    "structure_not_improved_or_zero_not_reduced": "结构未改善且零时长未减少",
    "no_left_stable_segment": "未找到左侧稳定边界",
    "no_right_stable_segment": "未找到右侧稳定边界",
    "no_stable_segment_pair": "未找到成对稳定边界",
    "future_windows_did_not_recover_right_stable_segment": "后续窗口未恢复右侧稳定边界",
    "deferred_three_context_disagreement": "等待后仍存在三种上下文分歧",
    "deferred_trigger_not_reduced": "等待后异常触发未减少",
    "strict_decrease": "结构异常严格下降",
    "structure_nonincrease_consensus": "三种上下文一致且结构不恶化",
    "zero_duration_relaxed": "零时长专用宽松门",
    "gt_oracle_improved": "GT改善影子门",
    "none": "未接受",
    "exact": "精确目标范围",
    "plus2": "前后各加2字",
    "plus4": "前后各加4字",
}

def display_text(value: Any) -> str:
    text = str(value or "")
    return DISPLAY_TEXT.get(text, text.replace("_", " ") or "-")


def resolved_variant_settings(root: Path) -> tuple[str, list[str]]:
    resolved=read_json(root/"resolved_config.json")
    effective=resolved.get("effective") if isinstance(resolved.get("effective"),dict) else {}
    source=resolved.get("source_config") if isinstance(resolved.get("source_config"),dict) else {}
    primary=str(effective.get("primary_variant") or nested(source,"variants","primary",default="B2_30_silence_official"))
    raw_matrix=effective.get("baseline_matrix_variants")
    if isinstance(raw_matrix,str):
        matrix=[value.strip() for value in raw_matrix.split(",") if value.strip()]
    elif isinstance(raw_matrix,list):
        matrix=[str(value) for value in raw_matrix]
    else:
        matrix=[str(value) for value in (nested(source,"variants","window_matrix",default=[]) or [])]
        raw_control=nested(source,"variants","raw_control")
        if raw_control and str(raw_control) not in matrix: matrix.append(str(raw_control))
    if primary not in matrix: matrix.insert(0,primary)
    return primary,list(dict.fromkeys(matrix))



def validate_expected_experimental(item: dict[str, Any], root: Path, item_root: Path) -> None:
    resolved=read_json(root/"resolved_config.json")
    source=resolved.get("source_config") if isinstance(resolved.get("source_config"),dict) else {}
    primary,matrix=resolved_variant_settings(root)
    effective=resolved.get("effective") if isinstance(resolved.get("effective"),dict) else {}
    expected_variants=matrix if str(item.get("variant_set","official_primary"))=="baseline_matrix" else [primary]
    stable_enabled=bool(effective.get("stable_window_assistance",nested(source,"shadow","stable_anchor","enabled",default=True))) and item.get("profile")!="local_segment"
    deferred_enabled=bool(effective.get("pending_confirmation_shadow",nested(source,"shadow","deferred_realign","enabled",default=True)))
    inline_enabled=bool(effective.get("inline_shadow",True))
    immediate_enabled=inline_enabled and bool(nested(source,"shadow","deferred_realign","immediate_inline",default=True))
    deferred_enabled=deferred_enabled and inline_enabled
    expected=[]
    for variant in expected_variants:
        expected += [
            item_root/"branches"/variant/"alignment.json",
            item_root/"branches"/variant/"alignment.raw.json",
            item_root/"branches"/variant/"alignment.processor_decoded.json",
            item_root/"branches"/variant/"alignment.selected.json",
            item_root/"branches"/variant/"summary.json",
        ]
    if stable_enabled:
        expected += [item_root/"experimental_alignments"/name/"alignment.json" for name in STABLE_LABELS]
    if immediate_enabled:
        expected += [item_root/"experimental_alignments/R1_immediate_inline/alignment.json",item_root/"experimental_alignments/R4_context_median_fused/alignment.json"]
    if deferred_enabled:
        expected += [item_root/"experimental_alignments/R2_deferred/alignment.json",item_root/"experimental_alignments/R3_inline_deferred/alignment.json"]
    missing=[str(path) for path in expected if not path.is_file() or path.stat().st_size<=0]
    if missing: raise FileNotFoundError(f"expected stable/realign alignments missing or empty: {missing}")

def alignment(item_root: Path, relative: str) -> tuple[dict[str, Any], Path]:
    path=item_root/relative
    return read_json(path), path


def tracks_from_paths(specs: list[tuple[str, Path]], *, strict: bool = True) -> list[tuple[str,list[dict[str,Any]]]]:
    tracks=[]; missing=[]
    for label,path in specs:
        payload=read_json(path)
        if payload.get("characters"):
            tracks.append((label,ordered_rows(payload)))
        elif strict:
            missing.append(path)
    if missing: require_files(missing,"预期对齐产物")
    return tracks


def page_ranges(duration: float, page_seconds: float) -> list[tuple[float,float]]:
    duration=max(duration,0.01); step=max(page_seconds,5.0)
    return [(start,min(duration,start+step)) for start in [i*step for i in range(max(1,math.ceil(duration/step)))]]


def full_timeline_pixel_width(duration: float) -> int:
    return max(3600, min(9000, int(max(duration, 30.0) * 24.0)))


def stable_spans(item_root: Path, baseline: dict[str,Any]) -> list[dict[str,Any]]:
    """Return all stable candidates plus the selected input/commit anchors."""
    spans: list[dict[str,Any]] = []
    stable_payload = baseline.get("stable_segments") or {}
    for segment in stable_payload.get("segments",[]) if isinstance(stable_payload,dict) else []:
        if segment.get("start_sec") is not None and segment.get("end_sec") is not None:
            spans.append({
                "start_sec":float(segment["start_sec"]),"end_sec":float(segment["end_sec"]),
                "label":"稳定候选","kind":"stable_candidate",
                "character_start":segment.get("character_start"),"character_end":segment.get("character_end"),
            })
    assistance=read_json(item_root/"stable_window_assistance.json")
    for transition in assistance.get("transitions",[]):
        for key,label,kind in (
            ("prefix_segment","选中的输入稳定区","stable_selected_input"),
            ("safe_commit_segment","选中的安全提交区","stable_selected_commit"),
        ):
            segment=transition.get(key) or {}
            if segment.get("start_sec") is not None and segment.get("end_sec") is not None:
                spans.append({"start_sec":float(segment["start_sec"]),"end_sec":float(segment["end_sec"]),"label":label,"kind":kind,"from_window":transition.get("from_window_index"),"to_window":transition.get("to_window_index")})
    return spans

def realign_spans(item_root: Path) -> tuple[list[dict[str,Any]], list[dict[str,Any]]]:
    shadow=read_json(item_root/"inline_realign_shadow.json")
    pending=read_json(item_root/"pending_confirmation_shadow.json")
    spans=[]; cases=[]
    for decision in shadow.get("decisions",[]):
        left=decision.get("audio_start_sec")
        if left is None:
            left=nested(decision,"left_segment","start_sec")
        right=decision.get("audio_end_sec")
        if right is None:
            right=nested(decision,"right_segment","end_sec")
        if left is None or right is None:
            # Derive from replacement rows where available.
            rows=[]
            for trial in (decision.get("context_trials") or {}).values():
                rows.extend(ordered_rows(trial.get("decoded_rows") or []))
            if rows:
                left=min(float(r["start_sec"]) for r in rows); right=max(float(r["end_sec"]) for r in rows)
        source=str(decision.get("candidate_source") or "候选")
        accepted=bool(decision.get("automatic_gate_accepted_shadow") or decision.get("gt_oracle_improved_shadow") or decision.get("manual_gate_accepted_shadow"))
        if left is not None and right is not None:
            spans.append({"start_sec":float(left),"end_sec":float(right),"label":("接受" if accepted else "拒绝")+"："+source,"kind":"realign_accepted" if accepted else "realign_rejected"})
        cases.append({**decision,"case_kind":"立即重对齐"})
    for case in pending.get("cases",[]):
        rows=[]
        for trial in (case.get("context_trials") or {}).values():
            rows.extend(ordered_rows(trial.get("decoded_rows") or []))
        if rows:
            spans.append({"start_sec":min(float(r["start_sec"]) for r in rows),"end_sec":max(float(r["end_sec"]) for r in rows),"label":"等待后续窗口","kind":"realign_accepted" if case.get("status")=="resolved_shadow" else "realign_rejected"})
        cases.append({**case,"case_kind":"等待后续窗口"})
    return spans,cases


def realign_case_tracks(case: dict[str,Any], baseline_rows: list[dict[str,Any]]) -> list[tuple[str,list[dict[str,Any]]]]:
    start=int(case.get("target_start",case.get("character_start",0))); end=int(case.get("target_end",case.get("character_end",start)))
    pad=6
    base=[r for r in baseline_rows if start-pad <= row_index(r) <= end+pad]
    result=[("原结果",base)]
    labels={"exact":"严格目标区间","plus2":"前后各加2字","plus4":"前后各加4字"}
    trials=case.get("context_trials") or case.get("trials") or {}
    for key in ("exact","plus2","plus4"):
        rows=ordered_rows((trials.get(key) or {}).get("decoded_rows") or [])
        if rows: result.append((labels[key],rows))
    fused=ordered_rows(case.get("median_fused_rows") or case.get("fused_replacement_rows") or [])
    if fused: result.append(("三上下文中位融合",fused))
    return result


def realign_execution_tracks_for_page(
    cases: list[dict[str,Any]], baseline_rows: list[dict[str,Any]], *, page_start: float, page_end: float,
) -> tuple[list[tuple[str,list[dict[str,Any]]]], list[str]]:
    tracks: list[tuple[str,list[dict[str,Any]]]]=[("原始基线",baseline_rows)]
    annotations: list[str]=[]
    labels={"exact":"严格区间","plus2":"前后各加2字","plus4":"前后各加4字"}
    visible_case_count=0
    for case_index,case in enumerate(cases):
        trials=case.get("context_trials") or case.get("trials") or {}
        trial_rows={key:ordered_rows((trials.get(key) or {}).get("decoded_rows") or []) for key in ("exact","plus2","plus4")}
        fused=ordered_rows(case.get("median_fused_rows") or case.get("fused_replacement_rows") or [])
        all_rows=[row for rows in trial_rows.values() for row in rows]+fused
        if not all_rows: continue
        case_start=min(min(float(row["start_sec"]),float(row["end_sec"])) for row in all_rows)
        case_end=max(max(float(row["start_sec"]),float(row["end_sec"])) for row in all_rows)
        if case_end<page_start or case_start>page_end: continue
        visible_case_count+=1
        case_label=f"案例{case_index+1}"
        for key in ("exact","plus2","plus4"):
            if trial_rows[key]: tracks.append((f"{case_label}·{labels[key]}",trial_rows[key]))
        if fused: tracks.append((f"{case_label}·中位融合",fused))
        reason=display_text(case.get("reason") or case.get("gate_reason") or "待判断")
        gate=display_text(case.get("accepted_gate_kind") or case.get("gate_kind") or "未接受")
        annotations.append(f"{case_label}：{reason}；判定={gate}")
    if visible_case_count==0:
        annotations.append("本页没有执行局部重对齐")
    return tracks,annotations


def behavior_annotations(base: dict[str,Any], spans: list[dict[str,Any]], page_start: float, page_end: float) -> list[str]:
    windows=[w for w in base.get("window_trace",[]) if float(w.get("core_end_sec",0))>=page_start and float(w.get("core_start_sec",0))<=page_end]
    stable=sum(int(w.get("stable_segment_count",0)) for w in windows)
    realign=sum(float(s["end_sec"])>=page_start and float(s["start_sec"])<=page_end for s in spans)
    policy=str(nested(base,"identity","window_plan_policy",default="") or nested(base,"summary","window_policy",default=""))
    return [f"窗口数：{len(windows)}",f"稳定候选：{stable}",f"重对齐区间：{realign}",f"策略：{policy or '见窗口边界'}"]


def render_item(item: dict[str,Any], root: Path, *, font: str, timeline_page_seconds: float, behavior_page_seconds: float, comparison_tokens: list[str], generate_video_pages: bool) -> dict[str,Any]:
    item_id=str(item["item_id"]); item_root=root/"items"/item_id; visual_root=item_root/"visuals"
    visual_root.mkdir(parents=True,exist_ok=True)
    validate_expected_experimental(item,root,item_root)
    primary_token,_matrix=resolved_variant_settings(root)
    primary_root=item_root/"branches"/primary_token
    primary=read_json(primary_root/"alignment.json")
    if not primary: raise FileNotFoundError(primary_root/"alignment.json")
    primary_label=BRANCH_LABELS.get(primary_token,primary_token)
    duration=float(nested(primary,"summary","audio_duration_sec",default=0.0) or 0.0)
    windows=list(primary.get("window_trace") or [])
    raw=read_json(primary_root/"alignment.raw.json")
    processor=read_json(primary_root/"alignment.processor_decoded.json")
    selected=read_json(primary_root/"alignment.selected.json")
    decoder_tracks=[
        ("原始逐槽独立取最大值",ordered_rows(raw)),
        ("处理器单调解码",ordered_rows(processor)),
        ("窗口选中结果",ordered_rows(selected)),
        ("最终提交结果",ordered_rows(primary)),
    ]
    require_files([primary_root/"alignment.raw.json",primary_root/"alignment.processor_decoded.json",primary_root/"alignment.selected.json"],"解码层次")

    branch_specs=[]
    for token,label in BRANCH_LABELS.items():
        path=item_root/"branches"/token/"alignment.json"
        if path.is_file(): branch_specs.append((label,path))
    window_payload_map={token:read_json(item_root/"branches"/token/"alignment.json") for token in BRANCH_LABELS if (item_root/"branches"/token/"alignment.json").is_file()}
    window_track_map={token:(BRANCH_LABELS[token],ordered_rows(payload)) for token,payload in window_payload_map.items() if payload.get("characters")}
    window_timeline_map={token:(BRANCH_LABELS[token],ordered_rows(payload),list(payload.get("window_trace") or [])) for token,payload in window_payload_map.items() if payload.get("characters")}
    window_groups={
        "window_core":[window_track_map[token] for token in ("B0_60_fixed_official","B1_30_fixed_official","B2_30_silence_official","B4_60_silence_official") if token in window_track_map],
        "window_strict":[window_track_map[token] for token in ("B2_30_silence_official","B4_60_silence_official","B5_30_strict_silence_official","B6_60_strict_silence_official") if token in window_track_map],
        "window_compression":[window_track_map[token] for token in ("B2_30_silence_official","B4_60_silence_official","C0_30_silence_compressed_diagnostic","C1_60_silence_compressed_diagnostic") if token in window_track_map],
        "window_raw_control":[window_track_map[token] for token in ("B2_30_silence_official","B3_30_silence_raw_control") if token in window_track_map],
    }
    window_timeline_groups={
        "window_core":[window_timeline_map[token] for token in ("B0_60_fixed_official","B1_30_fixed_official","B2_30_silence_official","B4_60_silence_official") if token in window_timeline_map],
        "window_strict":[window_timeline_map[token] for token in ("B2_30_silence_official","B4_60_silence_official","B5_30_strict_silence_official","B6_60_strict_silence_official") if token in window_timeline_map],
        "window_compression":[window_timeline_map[token] for token in ("B2_30_silence_official","B4_60_silence_official","C0_30_silence_compressed_diagnostic","C1_60_silence_compressed_diagnostic") if token in window_timeline_map],
        "window_raw_control":[window_timeline_map[token] for token in ("B2_30_silence_official","B3_30_silence_raw_control") if token in window_timeline_map],
    }

    stable_specs=[(label,item_root/"experimental_alignments"/token/"alignment.json") for token,label in STABLE_LABELS.items()]
    stable_tracks=tracks_from_paths(stable_specs,strict=False)
    realign_specs=[(label,item_root/"experimental_alignments"/token/"alignment.json") for token,label in REALIGN_LABELS.items()]
    realign_tracks=tracks_from_paths(realign_specs,strict=False)
    spans,cases=realign_spans(item_root)
    stable_evidence_spans=stable_spans(item_root,primary)

    outputs=[]; pages={"decoder":[],"window_core":[],"window_strict":[],"window_compression":[],"window_raw_control":[],"stable":[],"realign":[],"behavior":[],"comparison_window":[],"comparison_realign":[],"comparison_realign_execution":[],"comparison_decoder":[]}
    timeline_groups=[
        ("decoder","解码与提交层次",decoder_tracks,None,windows),
        ("window_core","Core长度与静音吸附",window_timeline_groups["window_core"],None,[]),
        ("window_strict","静音吸附与严格静音边界",window_timeline_groups["window_strict"],None,[]),
        ("window_compression","连续音频与全静音压缩诊断",window_timeline_groups["window_compression"],None,[]),
        ("window_raw_control","处理器推进与原始输出推进",window_timeline_groups["window_raw_control"],None,[]),
        ("stable","稳定区同步裁剪消融",[(f"{primary_label}基线",ordered_rows(primary)),*stable_tracks],stable_evidence_spans,windows),
        ("realign","局部重对齐行为",[(f"{primary_label}基线",ordered_rows(primary)),*realign_tracks],spans,windows),
    ]
    full_width = full_timeline_pixel_width(duration)
    full_start, full_end = 0.0, max(duration, 0.1)
    for key,title,tracks,track_spans,page_windows in timeline_groups:
        if not tracks: continue
        out=visual_root/f"timeline_{key}"/"full_timeline.png"
        meta=render_timeline_page(output=out,tracks=tracks,windows=page_windows,start=full_start,end=full_end,title=f"{title}｜全曲时间轴",font=font,spans=track_spans,pixel_width=full_width)
        pages[key].append(meta); outputs.append(out)

    duration_outputs={}
    for key,title,tracks in [
        ("decoder","单字时长离散概率分布：解码层次",decoder_tracks),
        ("window_core","单字时长离散概率分布：Core与静音吸附",window_groups["window_core"]),
        ("window_strict","单字时长离散概率分布：严格静音边界",window_groups["window_strict"]),
        ("window_compression","单字时长离散概率分布：静音压缩诊断",window_groups["window_compression"]),
        ("window_raw_control","单字时长离散概率分布：原始输出推进控制",window_groups["window_raw_control"]),
        ("stable","单字时长离散概率分布：稳定区同步裁剪",[("基线",ordered_rows(primary)),*stable_tracks]),
        ("realign","单字时长离散概率分布：局部重对齐",[("基线",ordered_rows(primary)),*realign_tracks]),
    ]:
        if not tracks: continue
        out=visual_root/f"duration_{key}.png"; duration_outputs[key]=render_duration_pmf(output=out,tracks=tracks,title=title,font=font); outputs.append(out)

    inconsistency_outputs={}
    out=visual_root/"inconsistency_decoder.png"; inconsistency_outputs["decoder"]=render_inconsistency(output=out,tracks=[decoder_tracks[0],decoder_tracks[1],decoder_tracks[-1]],title="原始逐槽结果、处理器解码与最终提交的歌词序号—时间及最大差",font=font); outputs.append(out)
    out=visual_root/"inconsistency_commit.png"; inconsistency_outputs["commit"]=render_inconsistency(output=out,tracks=[decoder_tracks[1],decoder_tracks[2],decoder_tracks[3]],title="处理器解码、窗口选中与最终提交的差异",font=font); outputs.append(out)
    # Window inconsistency uses per-window shadow predictions when available.
    shadow_tracks=[]
    for window in windows:
        rows=ordered_rows(window.get("shadow_rows") or [])
        if rows: shadow_tracks.append((f"窗{window.get('window_index')}",rows))
    if shadow_tracks:
        out=visual_root/"inconsistency_windows.png"; inconsistency_outputs["windows"]=render_inconsistency(output=out,tracks=shadow_tracks,title="同一歌词单位在不同窗口中的时间分歧",font=font,heatmap_label="相对跨窗中位时间偏差（秒）"); outputs.append(out)

    case_outputs=[]
    baseline_rows=ordered_rows(primary)
    for position,case in enumerate(cases):
        tracks=realign_case_tracks(case,baseline_rows)
        if len(tracks)<2: continue
        all_rows=[row for _,rows in tracks for row in rows]
        start=min(float(r["start_sec"]) for r in all_rows)-0.5; end=max(float(r["end_sec"]) for r in all_rows)+0.5
        reason=display_text(case.get("reason") or case.get("gate_reason") or "待判断")
        out=visual_root/"realign_cases"/f"case_{position:03d}.png"
        render_timeline_page(output=out,tracks=tracks,windows=[],start=max(0,start),end=max(start+0.1,end),title=f"{case.get('case_kind','局部重对齐')}｜{reason}",font=font,pixel_width=3000,annotations=[f"目标字符：{case.get('target_start')}–{case.get('target_end')}",f"判定规则：{display_text(case.get('accepted_gate_kind') or case.get('gate_kind') or case.get('non_gt_gate') or '-')}"])
        case_outputs.append(str(out)); outputs.append(out)

    # Fixed-scale reusable pages for Demo videos.  They contain full glyph tracks,
    # while the render stage only adds a moving pointer and audio.
    if str(item.get("dataset"))=="demo" and generate_video_pages:
        comparison_window=[]
        for token in comparison_tokens:
            if token=="RAW_B2":
                comparison_window.append(("原始逐槽独立取最大值",ordered_rows(raw),windows))
            else:
                payload=read_json(item_root/"branches"/token/"alignment.json")
                if payload:
                    comparison_window.append((BRANCH_LABELS.get(token,token),ordered_rows(payload),list(payload.get("window_trace") or [])))
        comparison_realign=[("基线",ordered_rows(primary)),*realign_tracks]
        for page_no,(start,end) in enumerate(page_ranges(duration,behavior_page_seconds)):
            stable_exact=next((track for track in stable_tracks if track[0]==STABLE_LABELS["S1_stable_sync_exact"]),None)
            behavior_tracks=[("原始逐槽独立取最大值",ordered_rows(raw)),("处理器单调解码",ordered_rows(processor)),("最终提交结果",ordered_rows(primary))]
            if stable_exact is not None:
                behavior_tracks.append(stable_exact)
            behavior_tracks.extend(realign_tracks)
            out=visual_root/"video_pages"/"behavior"/f"page_{page_no:03d}.png"
            meta=render_timeline_page(output=out,tracks=behavior_tracks,windows=windows,start=start,end=end,title="模型行为：窗口、稳定区与局部重对齐",font=font,spans=[*stable_evidence_spans,*spans],annotations=behavior_annotations(primary,spans,start,end),pixel_width=1920,pixel_height=1080,video_layout=True)
            pages["behavior"].append(meta); outputs.append(out)
            execution_tracks,execution_annotations=realign_execution_tracks_for_page(
                cases,baseline_rows,page_start=start,page_end=end,
            )
            out=visual_root/"video_pages"/"comparison_realign_execution"/f"page_{page_no:03d}.png"
            meta=render_timeline_page(
                output=out,tracks=execution_tracks,windows=windows,start=start,end=end,
                title="局部重对齐执行：精确范围、前后各加2字、前后各加4字与中位融合",font=font,spans=spans,
                annotations=execution_annotations,pixel_width=1920,pixel_height=1080,video_layout=True,
            )
            pages["comparison_realign_execution"].append(meta); outputs.append(out)
            for key,title,tracks in [
                ("comparison_window","窗口策略机制对照",comparison_window),
                ("comparison_realign","局部重对齐最终方案对照",comparison_realign),
                ("comparison_decoder","底层输出到最终提交",decoder_tracks),
            ]:
                if not tracks:
                    continue
                out=visual_root/"video_pages"/key/f"page_{page_no:03d}.png"
                meta=render_timeline_page(output=out,tracks=tracks,windows=[] if key=="comparison_window" else windows,start=start,end=end,title=title,font=font,spans=spans if key=="comparison_realign" else None,pixel_width=1920,pixel_height=1080,video_layout=True)
                pages[key].append(meta); outputs.append(out)

    require_files(outputs,"静态可视化")
    analysis={
        "schema_version":"inline_realign_visual_analysis_v5_character_mechanism",
        "item_id":item_id,"duration_sec":duration,"font":font,"pages":pages,
        "duration_distributions":duration_outputs,"inconsistency":inconsistency_outputs,
        "realign_case_images":case_outputs,"structural":{
            "raw":structural_counts(ordered_rows(raw)),"processor":structural_counts(ordered_rows(processor)),
            "selected":structural_counts(ordered_rows(selected)),"final":structural_counts(ordered_rows(primary)),
        },
        "expected_outputs":[str(path) for path in outputs],
        "interpretation":"图表用于机制诊断；不替代GT指标或Demo听感判断。",
    }
    atomic_json(visual_root/"visual_analysis.json",analysis)
    return analysis



def visual_source_identity(root: Path, item_root: Path) -> list[dict[str, Any]]:
    """Hash every JSON/JSONL source consumed by the visual stage.

    Static figures are inexpensive compared with model inference, but a strict
    resume must still refuse to reuse pages after any branch, stable, realign
    or configuration payload changes.
    """
    resolved=read_json(root/"resolved_config.json")
    source=resolved.get("source_config") if isinstance(resolved.get("source_config"),dict) else {}
    effective=resolved.get("effective") if isinstance(resolved.get("effective"),dict) else {}
    semantic_config={
        "source_config":source,
        "effective":{key:effective.get(key) for key in (
            "primary_variant","baseline_matrix_variants","comparison_branches",
            "inline_shadow","stable_window_assistance","text_dosage_trials",
            "pending_confirmation_shadow","strict_silence_boundary_sec",
            "silence_compression_min_sec","silence_compression_padding_sec",
            "deferred_max_windows","deferred_max_seconds","deferred_max_units",
            "text_dosage_end_deltas","text_dosage_start_deltas",
        )},
    }
    identities=[{"semantic_config_hash":canonical_hash(semantic_config),"semantic_config":semantic_config}]
    paths=[]
    for path in sorted(item_root.rglob("*")):
        if not path.is_file() or path.suffix not in {".json", ".jsonl"}:
            continue
        relative=path.relative_to(item_root)
        if any(part in {"visuals", "renders", "render", "work"} for part in relative.parts):
            continue
        paths.append(path)
    identities.extend(file_identity(path) for path in paths)
    return identities


def visual_expected_outputs(item_root: Path) -> list[Path]:
    analysis_path=item_root/"visuals/visual_analysis.json"
    payload=read_json(analysis_path)
    outputs=[Path(str(value)).expanduser().resolve() for value in payload.get("expected_outputs",[]) if value]
    if analysis_path not in outputs: outputs.append(analysis_path)
    return outputs

def parser() -> argparse.ArgumentParser:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest",type=Path,required=True); p.add_argument("--experiment-root",type=Path,required=True)
    p.add_argument("--timeline-page-seconds",type=float,default=60.0); p.add_argument("--behavior-page-seconds",type=float,default=30.0)
    p.add_argument("--comparison-branches",default="B0_60_fixed_official,B2_30_silence_official,B4_60_silence_official,B5_30_strict_silence_official")
    p.add_argument("--font",default="Noto Sans CJK SC")
    p.add_argument("--video-pages-mode", choices=("on", "off"), default="on")
    p.add_argument("--resume",action="store_true")
    p.add_argument("--force",action="store_true")
    p.add_argument("--restart-item",action="append",default=[])
    return p


def main() -> int:
    args=parser().parse_args(); root=args.experiment_root.expanduser().resolve(); manifest=read_jsonl(args.manifest.expanduser().resolve())
    font=detect_font(args.font); tokens=[v.strip() for v in args.comparison_branches.split(",") if v.strip()]
    results=[]; failures=[]; skipped=0; restart={str(value) for value in args.restart_item}
    state_root=root/"state/visual_items"; state_root.mkdir(parents=True,exist_ok=True)
    for ordinal,item in enumerate(manifest,1):
        item_id=str(item["item_id"]); item_root=root/"items"/item_id; state_path=state_root/f"{item_id}.json"
        request={
            "schema_version":"inline_realign_visual_item_request_v1",
            "item_id":item_id,"font":font,"timeline_page_seconds":args.timeline_page_seconds,
            "behavior_page_seconds":args.behavior_page_seconds,"comparison_tokens":tokens,
            "video_pages_mode": args.video_pages_mode,
            "sources":visual_source_identity(root,item_root),
        }
        request_hash=canonical_hash(request); old=read_json(state_path); expected=visual_expected_outputs(item_root)
        if (args.resume and not args.force and item_id not in restart
                and old.get("status")=="complete" and old.get("request_hash")==request_hash
                and expected and all(path.is_file() and path.stat().st_size>0 for path in expected)
                and snapshots_match(old.get("output_snapshots"),expected)):
            skipped+=1; results.append({"item_id":item_id,"status":"resume_skipped","visual_analysis":str(item_root/"visuals/visual_analysis.json")})
            print(json.dumps({"stage":"visualization","item":f"{ordinal}/{len(manifest)}","item_id":item_id,"status":"resume_skipped_complete"},ensure_ascii=False),flush=True)
            continue
        atomic_json(state_path,{
            "schema_version":"inline_realign_visual_item_state_v1","item_id":item_id,"status":"running",
            "request":request,"request_hash":request_hash,"expected_outputs":[str(path) for path in expected],
        })
        try:
            result=render_item(item,root,font=font,timeline_page_seconds=args.timeline_page_seconds,behavior_page_seconds=args.behavior_page_seconds,comparison_tokens=tokens,generate_video_pages=args.video_pages_mode=="on")
            expected=[Path(str(value)).expanduser().resolve() for value in result.get("expected_outputs",[]) if value]
            analysis_path=item_root/"visuals/visual_analysis.json"
            if analysis_path not in expected: expected.append(analysis_path)
            require_files(expected,"静态可视化完整性")
            atomic_json(state_path,{
                "schema_version":"inline_realign_visual_item_state_v1","item_id":item_id,"status":"complete",
                "request_hash":request_hash,"expected_outputs":[str(path) for path in expected],
                "output_snapshots":output_snapshots(expected),
            })
            results.append({"item_id":item_id,"status":"complete","visual_analysis":str(analysis_path)})
            print(json.dumps({"stage":"visualization","item":f"{ordinal}/{len(manifest)}","item_id":item_id,"status":"complete"},ensure_ascii=False),flush=True)
        except Exception as exc:
            failure={"item_id":item_id,"reason":"visualization_failed","error":f"{type(exc).__name__}: {exc}"}; failures.append(failure)
            atomic_json(state_path,{
                "schema_version":"inline_realign_visual_item_state_v1","item_id":item_id,"status":"failed",
                "request_hash":request_hash,"error":failure["error"],
            })
            print(json.dumps({"stage":"visualization","item_id":item_id,"status":"failed","error":str(exc)},ensure_ascii=False),flush=True)
    payload={
        "schema_version":"inline_realign_visualization_summary_v6_character_mechanism_resumable",
        "item_count":len(manifest),"complete_count":len(results),
        "new_complete_count":sum(row.get("status")=="complete" for row in results),
        "resume_skipped_item_count":skipped,"failed_count":len(failures),
        "font":font,"results":results,"failures":failures,
    }
    atomic_json(root/"visualization_summary.json",payload)
    return 0 if not failures else 1


if __name__=="__main__": raise SystemExit(main())
