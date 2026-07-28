#!/usr/bin/env python3
"""Summarize the full inline-realign mechanism suite without mixing evidence roles."""
from __future__ import annotations
import argparse, collections, json, math, statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from lyricalign.metrics.character import evaluate_tolerant


def utc_now()->str:return datetime.now(timezone.utc).isoformat()
def read_json(path:Path)->dict[str,Any]:
    try:return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (OSError,json.JSONDecodeError):return {}
def read_jsonl(path:Path)->list[dict[str,Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.is_file() else []
def write_json(path:Path,payload:Any)->None:
    path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix(path.suffix+".tmp");tmp.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8");tmp.replace(path)
def finite(value:Any)->float|None:
    try:x=float(value)
    except (TypeError,ValueError):return None
    return x if math.isfinite(x) else None
def mean(values:Iterable[Any])->float|None:
    values=[x for v in values if (x:=finite(v)) is not None];return statistics.fmean(values) if values else None
def median(values:Iterable[Any])->float|None:
    values=[x for v in values if (x:=finite(v)) is not None];return statistics.median(values) if values else None
def percentile(values:Iterable[Any],q:float)->float|None:
    values=sorted(x for v in values if (x:=finite(v)) is not None)
    if not values:return None
    if len(values)==1:return values[0]
    p=(len(values)-1)*q;lo=math.floor(p);hi=math.ceil(p);return values[lo] if lo==hi else values[lo]*(hi-p)+values[hi]*(p-lo)
def cdict(counter:collections.Counter)->dict[str,int]:return dict(sorted(counter.items(),key=lambda x:(-x[1],str(x[0]))))




def resolved_primary_variant(root: Path) -> str:
    resolved=read_json(root/"resolved_config.json")
    effective=resolved.get("effective") if isinstance(resolved.get("effective"),dict) else {}
    source=resolved.get("source_config") if isinstance(resolved.get("source_config"),dict) else {}
    variants=source.get("variants") if isinstance(source.get("variants"),dict) else {}
    return str(effective.get("primary_variant") or variants.get("primary") or "B2_30_silence_official")

def _row_index(row:dict[str,Any])->int:
    return int(row.get("global_character_index",row.get("character_index")))

def _structural_rows(rows:list[dict[str,Any]])->dict[str,int]:
    ordered=sorted(rows,key=_row_index);zero=negative=overlap=start_reg=end_reg=0;previous_start=previous_end=None
    for row in ordered:
        start=float(row["start_sec"]);end=float(row["end_sec"])
        negative+=end<start-1e-9;zero+=end<=start+1e-9
        if previous_start is not None:start_reg+=start<previous_start-1e-9
        if previous_end is not None:
            end_reg+=end<previous_end-1e-9;overlap+=start<previous_end-1e-9
        previous_start=start;previous_end=end
    return {"unit_count":len(ordered),"zero_duration_count":zero,"negative_duration_count":negative,"inter_unit_overlap_count":overlap,"start_regression_count":start_reg,"end_regression_count":end_reg}

def _canonical_gt(rows:list[dict[str,Any]],gt_rows:list[dict[str,Any]])->dict[str,Any]|None:
    if not gt_rows:return None
    gt_by={_row_index(row):row for row in gt_rows}
    reference=[]
    for index,row in sorted(gt_by.items()):
        reference.append({"item_id":"item","song_id":"item","character_index":index,"normalized_character":row.get("normalized_character") or row.get("character") or str(index),"start_sec":float(row["start_sec"]),"end_sec":float(row["end_sec"])})
    prediction=[]
    for row in rows:
        index=_row_index(row);g=gt_by.get(index,{})
        prediction.append({"item_id":"item","song_id":"item","character_index":index,"normalized_character":g.get("normalized_character") or g.get("character") or row.get("normalized_character") or row.get("character") or str(index),"start_sec":float(row["start_sec"]),"end_sec":float(row["end_sec"])})
    return evaluate_tolerant(reference,prediction)

def decoder_stage_aggregates(root:Path,manifest:list[dict[str,Any]])->dict[str,Any]:
    """Aggregate raw->processor->selected->final and lightweight raw repairs."""
    stage_files={
        "D0_raw_argmax":"alignment.raw.json",
        "D1_processor_decoded":"alignment.processor_decoded.json",
        "D2_window_selected":"alignment.selected.json",
        "D4_final_committed":"alignment.json",
    }
    acc:dict[str,dict[str,Any]]={}
    adjustment_acc:dict[str,list[dict[str,Any]]]=collections.defaultdict(list)
    primary_variant=resolved_primary_variant(root)
    for item in manifest:
        item_root=root/"items"/str(item["item_id"]);branch=item_root/"branches"/primary_variant
        gt_rows=read_jsonl(Path(str(item["gt_path"]))) if item.get("gt_path") else []
        quality=read_json(branch/"alignment.quality.json")
        for name,value in (quality.get("stage_adjustments") or {}).items():adjustment_acc[name].append(value)
        candidates={name:branch/file for name,file in stage_files.items()}
        candidates.update({
            "D5_raw_nonnegative_only":item_root/"experimental_alignments"/"D5_raw_nonnegative_only"/"alignment.json",
            "D6_raw_minimal_monotonic":item_root/"experimental_alignments"/"D6_raw_minimal_monotonic"/"alignment.json",
        })
        for stage,path in candidates.items():
            payload=read_json(path);rows=list(payload.get("characters") or [])
            if not rows:continue
            structural=_structural_rows(rows);gt=_canonical_gt(rows,gt_rows)
            state=acc.setdefault(stage,{"item_count":0,"unit_count":0,"zero":0,"negative":0,"overlap":0,"start_reg":0,"end_reg":0,"gt_characters":0,"gt_penalized_sum":0.0,"gt_valid_sum":0.0,"gt_valid_count":0,"gt_coverage_weighted":0.0})
            state["item_count"]+=1;state["unit_count"]+=structural["unit_count"];state["zero"]+=structural["zero_duration_count"];state["negative"]+=structural["negative_duration_count"];state["overlap"]+=structural["inter_unit_overlap_count"];state["start_reg"]+=structural["start_regression_count"];state["end_reg"]+=structural["end_regression_count"]
            if gt:
                n=int(gt["character_count"]);valid=int(gt["valid_prediction_count"]);state["gt_characters"]+=n;state["gt_penalized_sum"]+=float(gt["all_item_penalized_boundary_mae_sec"])*n;state["gt_valid_sum"]+=float(gt["valid_only_boundary_mae_sec"])*valid;state["gt_valid_count"]+=valid;state["gt_coverage_weighted"]+=float(gt["character_coverage"])*n
    rows=[]
    for stage,state in sorted(acc.items()):
        units=state["unit_count"];n=state["gt_characters"]
        rows.append({"stage":stage,"item_count":state["item_count"],"unit_count":units,"zero_duration_count":state["zero"],"zero_duration_rate":state["zero"]/units if units else None,"negative_duration_count":state["negative"],"negative_duration_rate":state["negative"]/units if units else None,"inter_unit_overlap_count":state["overlap"],"start_regression_count":state["start_reg"],"end_regression_count":state["end_reg"],"gt_character_count":n,"gt_all_item_penalized_boundary_mae_sec":state["gt_penalized_sum"]/n if n else None,"gt_valid_only_boundary_mae_sec":state["gt_valid_sum"]/state["gt_valid_count"] if state["gt_valid_count"] else None,"gt_character_coverage":state["gt_coverage_weighted"]/n if n else None,"metric_schema_version":"character_interval_metrics_v3_tolerant"})
    adjustments=[]
    for transition,values in sorted(adjustment_acc.items()):
        adjustments.append({"transition":transition,"item_count":len(values),"changed_unit_rate_macro":mean((value.get("changed_unit_rate") for value in values)),"boundary_change_mean_sec_macro":mean(((value.get("absolute_boundary_change_sec") or {}).get("mean") for value in values)),"boundary_change_p90_sec_macro":mean(((value.get("absolute_boundary_change_sec") or {}).get("p90") for value in values)),"boundary_change_max_sec_max":max((finite((value.get("absolute_boundary_change_sec") or {}).get("max")) or 0.0 for value in values),default=None)})
    return {"primary_variant":primary_variant,"stage_results":rows,"stage_adjustments":adjustments,"interpretation":f"D0-D4 share {primary_variant} window/cursor ownership; D5-D6 are lightweight raw repairs. Raw-controlled serial behavior remains a separate branch and must be interpreted separately."}

def branch_aggregates(root:Path,manifest:list[dict[str,Any]])->list[dict[str,Any]]:
    acc:dict[tuple[str,str,str],dict[str,Any]]={}
    for item in manifest:
        item_root=root/"items"/str(item["item_id"])
        for summary_path in item_root.glob("branches/*/summary.json"):
            summary=read_json(summary_path);variant=str(summary.get("variant") or summary_path.parent.name)
            alignment_payload=read_json(summary_path.parent/"alignment.json")
            for dataset in (str(item.get("dataset","unknown")),"__TOTAL__"):
                key=(dataset,str(item.get("language","unknown")) if dataset!="__TOTAL__" else "__TOTAL__",variant)
                state=acc.setdefault(key,{"item_count":0,"unit_count":0,"zero":0,"negative":0,"overlap":0,"wall":[],"windows":[],"gt_units":0,"gt_abs_sum":0.0,"gt_macro":[]})
                state["item_count"]+=1;state["unit_count"]+=int(summary.get("character_count",0) or 0)
                structural=summary.get("structural") or {}
                if not structural:
                    rows=alignment_payload.get("characters") or []
                    structural={"zero_duration_count":sum(float(r.get("end_sec",0))-float(r.get("start_sec",0))<=1e-9 for r in rows),"negative_duration_count":sum(float(r.get("end_sec",0))<float(r.get("start_sec",0))-1e-9 for r in rows),"inter_unit_overlap_count":sum(float(rows[i].get("start_sec",0))<float(rows[i-1].get("end_sec",0))-1e-9 for i in range(1,len(rows)))}
                state["zero"]+=int(structural.get("zero_duration_count",0) or 0);state["negative"]+=int(structural.get("negative_duration_count",0) or 0);state["overlap"]+=int(structural.get("inter_unit_overlap_count",0) or 0)
                state["wall"].append(summary.get("wall_sec"));state["windows"].append(summary.get("window_count"))
                gt=summary.get("gt") or {}
                # Canonical v3 is defined over every reference character, including
                # invalid/missing predictions.  Weight the micro score by the full
                # reference character count; never fall back to the matched subset.
                reference_count=int(gt.get("character_count",gt.get("requested_unit_count",0)) or 0)
                mae=finite(gt.get("all_item_penalized_boundary_mae_sec",gt.get("boundary_mae_sec")))
                if reference_count and mae is not None:
                    state["gt_units"]+=reference_count
                    state["gt_abs_sum"]+=mae*reference_count
                    state["gt_macro"].append(mae)
    output=[]
    for (dataset,language,variant),state in sorted(acc.items()):
        units=state["unit_count"];gt_units=state["gt_units"]
        output.append({"dataset":dataset,"language":language,"variant":variant,"item_count":state["item_count"],"unit_count":units,"zero_duration_count":state["zero"],"zero_duration_rate":state["zero"]/units if units else None,"negative_duration_count":state["negative"],"negative_duration_rate":state["negative"]/units if units else None,"inter_unit_overlap_count":state["overlap"],"wall_sec_mean":mean(state["wall"]),"window_count_mean":mean(state["windows"]),"gt_character_count":gt_units,"gt_common_unit_count":gt_units,"gt_all_item_penalized_boundary_mae_micro_sec":state["gt_abs_sum"]/gt_units if gt_units else None,"gt_boundary_mae_micro_sec":state["gt_abs_sum"]/gt_units if gt_units else None,"gt_boundary_mae_macro_sec":mean(state["gt_macro"]),"metric_schema_version":"character_interval_metrics_v3_tolerant"})
    return output


def summarize(root:Path)->dict[str,Any]:
    experiment=read_json(root/"experiment_summary.json");manifest=read_jsonl(root/"experiment_manifest.jsonl")
    datasets=collections.Counter(str(x.get("dataset","unknown")) for x in manifest);languages=collections.Counter(str(x.get("language","unknown")) for x in manifest)
    gate_sources=collections.Counter();gate_reasons=collections.Counter();gate_kinds=collections.Counter();deferred_reasons=collections.Counter()
    stable_status=collections.Counter();stable_candidates=collections.Counter();dosage_groups:dict[tuple[str,str],dict[str,Any]]={}
    detector={"automatic_case_count":0,"gt_error_case_count":0,"cooccurring_evaluable_item_count":0}
    counts=collections.Counter();item_rows=[]
    automatic_reason_counts=collections.Counter();oracle_reason_counts=collections.Counter()
    legacy_automatic_candidate_count=legacy_oracle_candidate_count=legacy_local_attempted_count=0
    for item in manifest:
        item_id=str(item["item_id"]);item_root=root/"items"/item_id
        shadow=read_json(item_root/"inline_realign_shadow.json");stable=read_json(item_root/"stable_window_assistance_trials.json")
        dosage=read_json(item_root/"text_dosage_trials.json") or read_json(item_root/"forced_expansion_trials.json")
        deferred=read_json(item_root/"pending_confirmation_shadow.json")
        overlap=shadow.get("detector_gt_overlap") or {}
        detector["automatic_case_count"]+=int(overlap.get("automatic_case_count",0) or 0);detector["gt_error_case_count"]+=int(overlap.get("gt_error_case_count",0) or 0)
        if overlap.get("automatic_case_count") and overlap.get("gt_error_case_count"):detector["cooccurring_evaluable_item_count"]+=1
        legacy_automatic_candidate_count += int(shadow.get("automatic_candidate_count",0) or 0)
        legacy_oracle_candidate_count += int(shadow.get("gt_oracle_candidate_count",0) or 0)
        legacy_local_attempted_count += int(shadow.get("local_inference_attempted_count",0) or 0)
        for decision in shadow.get("decisions",[]):
            source=str(decision.get("candidate_source") or (decision.get("trigger") or {}).get("candidate_source") or "unknown");reason=str(decision.get("reason","unknown"));gate_sources[source]+=1;gate_reasons[reason]+=1
            if source=="automatic_precommit": automatic_reason_counts[reason]+=1
            if source=="gt_oracle": oracle_reason_counts[reason]+=1
            counts["gt_oracle_improved_shadow"]+=bool(decision.get("gt_oracle_improved_shadow") or decision.get("gt_improved"));counts["automatic_gate_accepted_shadow"]+=bool(decision.get("automatic_gate_accepted_shadow"));counts["manual_gate_accepted_shadow"]+=bool(decision.get("manual_gate_accepted_shadow"));counts["actual_writeback"]+=bool(decision.get("actual_writeback"));counts["three_context_supported"]+=bool((decision.get("context_consensus") or {}).get("supported"));counts["zero_duration_relaxed_gate"]+=bool(decision.get("zero_duration_relaxed_gate"));counts["context_median_fused_gate"]+=bool(decision.get("fused_would_pass_non_gt_gate"))
            gate_kinds[str(decision.get("accepted_gate_kind") or decision.get("gate_kind") or "none")]+=1
        for trial in stable.get("trials",[]):
            stable_status[str(trial.get("status","unknown"))]+=1
            for name,candidate in (trial.get("candidates") or {}).items():
                stable_candidates[f"{name}:{candidate.get('status','unknown')}"]+=1
                comparison=candidate.get("gt_comparison") or {}
                if comparison.get("better"):counts[f"stable_{name}_gt_better"]+=1
                if comparison.get("worse"):counts[f"stable_{name}_gt_worse"]+=1
        for window in dosage.get("windows",dosage.get("results",[])):
            for variant in window.get("variants",[]):
                key=(str(variant.get("kind","unknown")),str(variant.get("delta_units",variant.get("ratio","unknown"))))
                state=dosage_groups.setdefault(key,{"run_count":0,"complete_count":0,"movement":[],"negative":0,"zero":0,"gt_mae":[]})
                state["run_count"]+=1
                if variant.get("status")=="complete":
                    state["complete_count"]+=1;movement=variant.get("movement") or {};state["movement"].append(movement.get("max_boundary_movement_sec"));state["negative"]+=int(variant.get("negative_duration_count",0) or 0);state["zero"]+=int(variant.get("zero_duration_count",0) or 0);state["gt_mae"].append((variant.get("gt") or {}).get("boundary_mae_sec"))
        for case in deferred.get("cases",[]):
            deferred_reasons[str(case.get("reason","unknown"))]+=1;counts["deferred_case_count"]+=1;counts["deferred_resolved_shadow"]+=case.get("status")=="resolved_shadow";counts["deferred_zero_relaxed"]+=bool(case.get("zero_duration_relaxed_gate"));counts["deferred_actual_writeback"]+=bool(case.get("actual_writeback"))
        item_rows.append({"item_id":item_id,"dataset":item.get("dataset"),"language":item.get("language"),"shadow_decision_count":len(shadow.get("decisions",[])),"stable_trial_count":len(stable.get("trials",[])),"text_dosage_window_count":len(dosage.get("windows",dosage.get("results",[]))),"deferred_case_count":len(deferred.get("cases",[]))})
    dosage_rows=[]
    for (kind,delta),state in sorted(dosage_groups.items()):
        dosage_rows.append({"kind":kind,"delta_or_ratio":delta,"run_count":state["run_count"],"complete_count":state["complete_count"],"max_boundary_movement_median_sec":median(state["movement"]),"max_boundary_movement_p90_sec":percentile(state["movement"],0.9),"negative_duration_count_total":state["negative"],"zero_duration_count_total":state["zero"],"gt_boundary_mae_macro_sec":mean(state["gt_mae"])})
    render=read_json(root/"demo_render_summary.json");visual=read_json(root/"visualization_summary.json")
    return {
        "schema_version":"inline_realign_followup_summary_v5_full_mechanism","created_at":utc_now(),
        "experiment_status":{"status":experiment.get("status"),"manifest_item_count":len(manifest),"summarized_item_count":len(item_rows),"stale_item_directory_count":len([path for path in (root/"items").glob("*") if path.is_dir() and path.name not in {str(row.get("item_id")) for row in manifest}]),"completed_item_count":experiment.get("completed_item_count",0),"failed_item_count":experiment.get("failed_item_count",0),"resume_skipped_item_count":experiment.get("resume_skipped_item_count",0),"dataset_counts":cdict(datasets),"language_counts":cdict(languages)},
        "branch_results":branch_aggregates(root,manifest),
        "grouped_results":branch_aggregates(root,manifest),
        "decoder_stages":decoder_stage_aggregates(root,manifest),
        "automatic_and_oracle_realign":{"automatic_candidate_count":legacy_automatic_candidate_count,"gt_oracle_candidate_count":legacy_oracle_candidate_count,"local_inference_attempted_count":legacy_local_attempted_count,"gt_improved_count":counts["gt_oracle_improved_shadow"],"automatic_reason_counts":cdict(automatic_reason_counts),"gt_oracle_reason_counts":cdict(oracle_reason_counts)},
        "realign_gate":{"candidate_source_counts":cdict(gate_sources),"decision_reason_counts":cdict(gate_reasons),"accepted_gate_kind_counts":cdict(gate_kinds),"gt_oracle_improved_shadow_count":counts["gt_oracle_improved_shadow"],"automatic_gate_accepted_shadow_count":counts["automatic_gate_accepted_shadow"],"manual_gate_accepted_shadow_count":counts["manual_gate_accepted_shadow"],"zero_duration_relaxed_gate_count":counts["zero_duration_relaxed_gate"],"context_median_fused_gate_count":counts["context_median_fused_gate"],"three_context_supported_count":counts["three_context_supported"],"actual_writeback_count":counts["actual_writeback"]},
        "detector":{"role":"辅助候选生成，不作为当前主指标","automatic_case_count":detector["automatic_case_count"],"gt_error_case_count":detector["gt_error_case_count"],"cooccurring_evaluable_item_count":detector["cooccurring_evaluable_item_count"],"precision_recall_status":"not_evaluable" if detector["cooccurring_evaluable_item_count"]==0 else "see_item_level"},
        "stable_synchronized":{"trial_status_counts":cdict(stable_status),"candidate_status_counts":cdict(stable_candidates),"audio_text_synchronized":True,"sync_exact_gt_better_count":counts["stable_S1_stable_sync_exact_gt_better"],"sync_exact_gt_worse_count":counts["stable_S1_stable_sync_exact_gt_worse"],"sync_minus2_gt_better_count":counts["stable_S2_stable_sync_minus2_gt_better"],"sync_minus4_gt_better_count":counts["stable_S3_stable_sync_minus4_gt_better"]},
        "text_dosage":{"grouped_results":dosage_rows,"interpretation":"固定声学窗口，分别改变歌词起点和终点；负end delta可能删掉窗口内真实歌词，正delta增加未来歌词。"},
        "deferred":{"case_count":counts["deferred_case_count"],"resolved_shadow_count":counts["deferred_resolved_shadow"],"zero_duration_relaxed_count":counts["deferred_zero_relaxed"],"actual_writeback_count":counts["deferred_actual_writeback"],"reason_counts":cdict(deferred_reasons)},
        "visualization":{"complete_count":visual.get("complete_count",0),"failed_count":visual.get("failed_count",0),"design":"字符彩虹、完整离散PMF、三子图不一致性、可复用视频页面"},
        "render":{"rendered_item_count":render.get("rendered_item_count",0),"resume_skipped_item_count":render.get("resume_skipped_item_count",0),"failed_item_count":render.get("failed_item_count",0),"post_analysis":True},
        "items":item_rows,
        "interpretation_limits":["GT oracle改善、自动门控接受、人工候选接受和实际写回严格分开。","自动detector目前只作Demo导航和候选生成。","全静音压缩是诊断条件，不默认作为生产方案。","Demo无GT，仅支持结构和听感结论。","M4Singer synthetic-long与自然数据分开解释。","所有realign保持shadow-only，actual_writeback应为0。"],
    }


def fmt(x:Any,d:int=4)->str:return "—" if x is None else f"{x:.{d}f}" if isinstance(x,float) else str(x)
def render_markdown(p:dict[str,Any])->str:
    status=p["experiment_status"];gate=p["realign_gate"];stable=p["stable_synchronized"];deferred=p["deferred"]
    lines=[
        "# Inline Realign 全机制实验汇总","",f"生成时间：`{p['created_at']}`","",
        "## 运行覆盖","",
        f"- manifest：{status['manifest_item_count']}",
        f"- 完成 / 失败 / resume跳过：{status['completed_item_count']} / {status['failed_item_count']} / {status['resume_skipped_item_count']}",
        f"- 数据集：`{json.dumps(status['dataset_counts'],ensure_ascii=False)}`",
        f"- 语言：`{json.dumps(status['language_counts'],ensure_ascii=False)}`","",
        "## 局部重对齐门控（影子实验）","",
        f"- GT oracle改善：{gate['gt_oracle_improved_shadow_count']}",
        f"- 自动候选门控接受：{gate['automatic_gate_accepted_shadow_count']}",
        f"- 人工候选门控接受：{gate['manual_gate_accepted_shadow_count']}",
        f"- 零时长宽松门接受：{gate['zero_duration_relaxed_gate_count']}",
        f"- 三上下文中位融合门接受：{gate['context_median_fused_gate_count']}",
        f"- 实际写回：{gate['actual_writeback_count']}",
        f"- 拒绝/接受原因：`{json.dumps(gate['decision_reason_counts'],ensure_ascii=False)}`","",
        "## Raw → Official 分阶段","",
    ]
    for row in p.get("decoder_stages",{}).get("stage_results",[]):
        lines.append(
            f"- {row['stage']}：负时长 {row['negative_duration_count']}，"
            f"零时长 {row['zero_duration_count']}，canonical MAE "
            f"{fmt(row['gt_all_item_penalized_boundary_mae_sec'])}"
        )
    lines.extend([
        "","## Stable 同步裁剪","",
        f"- trial状态：`{json.dumps(stable['trial_status_counts'],ensure_ascii=False)}`",
        f"- 候选状态：`{json.dumps(stable['candidate_status_counts'],ensure_ascii=False)}`","",
        "## Deferred","",
        f"- case / resolved shadow：{deferred['case_count']} / {deferred['resolved_shadow_count']}",
        f"- 零时长宽松门：{deferred['zero_duration_relaxed_count']}",
        f"- 原因：`{json.dumps(deferred['reason_counts'],ensure_ascii=False)}`","",
        "## 静态图与视频","",
        f"- 静态图完成 / 失败：{p['visualization']['complete_count']} / {p['visualization']['failed_count']}",
        f"- 视频新完成 / resume跳过 / 失败：{p['render']['rendered_item_count']} / {p['render']['resume_skipped_item_count']} / {p['render']['failed_item_count']}",
        "","## 解释边界","",
    ])
    lines.extend(f"- {x}" for x in p["interpretation_limits"]);lines.append("")
    return "\n".join(lines)

def parser()->argparse.ArgumentParser:
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("input_root",type=Path);p.add_argument("--output",type=Path);p.add_argument("--markdown-output",type=Path);return p
def main()->int:
    args=parser().parse_args();root=args.input_root.expanduser().resolve()
    if not (root/"experiment_summary.json").is_file():raise FileNotFoundError(root/"experiment_summary.json")
    payload=summarize(root);out=(args.output or root/"followup_analysis_summary.json").resolve();md=(args.markdown_output or root/"followup_analysis_summary.md").resolve();write_json(out,payload);md.parent.mkdir(parents=True,exist_ok=True);md.write_text(render_markdown(payload),encoding="utf-8")
    print(json.dumps({"status":"complete","output":str(out),"markdown_output":str(md),"completed_item_count":payload["experiment_status"]["completed_item_count"],"failed_item_count":payload["experiment_status"]["failed_item_count"]},ensure_ascii=False),flush=True);return 0
if __name__=="__main__":raise SystemExit(main())
