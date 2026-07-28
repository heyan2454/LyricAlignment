#!/usr/bin/env python3
"""Continuously display resumable inline-realign experiment and render status."""
from __future__ import annotations
import argparse, json, os, time
from datetime import datetime
from pathlib import Path
from typing import Any


def read_json(path:Path)->dict[str,Any]:
    try:return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (OSError,json.JSONDecodeError):return {}
def read_jsonl(path:Path)->list[dict[str,Any]]:
    try:return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()] if path.is_file() else []
    except (OSError,json.JSONDecodeError):return []
def directory_size(path:Path)->int:
    total=0
    if path.exists():
        for entry in path.rglob("*"):
            try:
                if entry.is_file():total+=entry.stat().st_size
            except OSError:pass
    return total
def human_bytes(value:int)->str:
    number=float(value)
    for unit in ("B","KiB","MiB","GiB","TiB"):
        if number<1024 or unit=="TiB":return f"{number:.1f} {unit}"
        number/=1024
    return f"{number:.1f} TiB"
def count_states(path:Path)->dict[str,int]:
    counts={}
    if path.is_dir():
        for file in path.glob("*.json"):
            status=str(read_json(file).get("status") or "unknown");counts[status]=counts.get(status,0)+1
    return counts
def fmt_counts(counts:dict[str,int])->str:
    return " / ".join(f"{k}:{v}" for k,v in sorted(counts.items())) or "—"


def render(root:Path)->str:
    manifest=read_jsonl(root/"experiment_manifest.jsonl"); live=read_json(root/"live_status.json")
    experiment_live=read_json(root/"experiment_live_status.json"); run=read_json(root/"state/run_state.json")
    experiment=read_json(root/"experiment_summary.json"); visuals=read_json(root/"visualization_summary.json")
    renders=read_json(root/"demo_render_summary.json"); analysis=read_json(root/"analysis_complete.json"); render_complete=read_json(root/"render_complete.json"); complete=read_json(root/"pipeline_complete.json")
    item_states=count_states(root/"state/items"); visual_states=count_states(root/"state/visual_items"); render_states=count_states(root/"state/render_items")
    current=experiment_live.get("item_ordinal") or "—"; total=experiment_live.get("manifest_item_count") or len(manifest) or "—"
    stage=live.get("stage") or "尚未开始"; stage_status=live.get("status") or "unknown"
    lines=[
        f"Inline Realign 进度｜{datetime.now().isoformat(timespec='seconds')}",f"目录：{root}",
        f"运行状态：{run.get('status','—')}｜流水线：{stage} / {stage_status}｜最终：{complete.get('status','—')}",
        f"当前实验项：{current}/{total}｜{experiment_live.get('item_id','—')}｜分支：{experiment_live.get('branch','—')}",
        f"实验项恢复状态：{fmt_counts(item_states)}",
        f"实验汇总：完成 {experiment.get('completed_item_count','—')}｜失败 {experiment.get('failed_item_count','—')}｜恢复跳过 {experiment.get('resume_skipped_item_count','—')}",
        f"静态图Item状态：{fmt_counts(visual_states)}",
        f"静态图汇总：合计完成 {visuals.get('complete_count','—')}｜本次新完成 {visuals.get('new_complete_count','—')}｜恢复跳过 {visuals.get('resume_skipped_item_count','—')}｜失败 {visuals.get('failed_count','—')}",
        f"分析完成：{analysis.get('status','—')}｜渲染完成：{render_complete.get('status',analysis.get('render_status','—'))}",
        f"视频Item状态：{fmt_counts(render_states)}",
        f"视频汇总：合计完成 {renders.get('complete_item_count', (renders.get('rendered_item_count',0) or 0)+(renders.get('resume_skipped_item_count',0) or 0))}｜本次新完成 {renders.get('rendered_item_count','—')}｜恢复跳过 {renders.get('resume_skipped_item_count','—')}｜失败 {renders.get('failed_item_count','—')}",
        f"输出体积：{human_bytes(directory_size(root))}",
    ]
    failure=live.get("error") or live.get("message") or experiment_live.get("error") or experiment_live.get("message")
    if failure:lines.append(f"消息：{failure}")
    log=root/"logs"/f"{stage}.log"
    if log.is_file():
        try:
            tail=log.read_text(encoding="utf-8",errors="replace").splitlines()[-8:]
            if tail:lines.extend(["",f"日志末尾：{log.name}",*tail])
        except OSError:pass
    return "\n".join(lines)


def main()->int:
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("experiment_root",type=Path);p.add_argument("--refresh-seconds",type=float,default=3.0);p.add_argument("--once",action="store_true");p.add_argument("--no-clear",action="store_true");args=p.parse_args()
    root=args.experiment_root.expanduser().resolve()
    while True:
        if not args.no_clear and not args.once:os.system("cls" if os.name=="nt" else "clear")
        print(render(root),flush=True)
        if args.once:return 0
        time.sleep(max(0.5,args.refresh_seconds))
if __name__=="__main__":raise SystemExit(main())
