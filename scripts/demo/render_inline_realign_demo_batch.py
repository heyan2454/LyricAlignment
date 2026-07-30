#!/usr/bin/env python3
"""Encode post-analysis Demo behavior videos from reusable character PNG pages.

The model experiment and numeric analysis are already complete when this stage
starts.  Each Demo item has an independent render identity, so interruption only
requires re-running with ``--resume``; completed videos are skipped.
"""
from __future__ import annotations

import argparse
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"src"))

from lyricalign.demo.media_render import atomic_json, canonical_hash, detect_font, sha256
from lyricalign.demo.timeline_video import render_page_video
from lyricalign.demo.run_state import file_identity


def utc_now()->str: return datetime.now(timezone.utc).isoformat()

def read_json(path:Path)->dict[str,Any]:
    try: return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (OSError,json.JSONDecodeError): return {}

def read_jsonl(path:Path)->list[dict[str,Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

def file_ok(path:Path)->bool: return path.is_file() and path.stat().st_size>0


def resolved_primary_variant(root: Path) -> str:
    resolved=read_json(root/"resolved_config.json")
    effective=resolved.get("effective") if isinstance(resolved.get("effective"),dict) else {}
    source=resolved.get("source_config") if isinstance(resolved.get("source_config"),dict) else {}
    source_variants=source.get("variants") if isinstance(source.get("variants"),dict) else {}
    return str(effective.get("primary_variant") or source_variants.get("primary") or "B2_30_silence_official")


def render_output_snapshots(paths: list[Path]) -> list[dict[str, Any]]:
    """Validate videos without re-hashing every large MP4 on resume.

    The MP4 stat is paired with the small cryptographic request identity sidecar
    written by ``render_page_video``.  This preserves strict input identity while
    keeping a formal render resume cheap enough to use routinely.
    """
    snapshots=[]
    for path in paths:
        identity=path.with_suffix(path.suffix+".identity.json")
        snapshots.append({
            "video":file_identity(path,include_sha256=False),
            "identity":file_identity(identity,include_sha256=True),
        })
    return snapshots

def atomic_state(path:Path,payload:dict[str,Any])->None:
    path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile("w",encoding="utf-8",dir=path.parent,delete=False,suffix=".tmp") as handle:
        json.dump(payload,handle,ensure_ascii=False,indent=2); handle.write("\n"); temporary=Path(handle.name)
    temporary.replace(path)



def render_set(*, paths: list[Path], labels: list[str], visual: Path | None, audio: Path, output: Path, ass_root: Path, font: str, profile: str, force: bool) -> dict[str, Any]:
    """Legacy API retained for regression tests; new rendering uses PNG pages."""
    missing=[str(path) for path in paths if not path.is_file() or path.stat().st_size<=0]
    if missing: raise FileNotFoundError(f"comparison inputs missing or empty: {missing}")
    raise RuntimeError("legacy text comparison renderer is retired; use reusable timeline pages")

def parser()->argparse.ArgumentParser:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest",type=Path,required=True); p.add_argument("--experiment-root",type=Path,required=True)
    p.add_argument("--font",default="Noto Sans CJK SC"); p.add_argument("--profile",choices=("review","final"),default="review")
    p.add_argument("--comparison-branches",default="B0_60_fixed_official,B4_60_silence_official,C1_60_silence_compressed_diagnostic,B6_60_strict_silence_official")
    p.add_argument("--render-incomplete",action="store_true"); p.add_argument("--resume",action="store_true"); p.add_argument("--force",action="store_true")
    p.add_argument("--restart-item",action="append",default=[])
    return p


def main()->int:
    args=parser().parse_args(); root=args.experiment_root.expanduser().resolve(); manifest=read_jsonl(args.manifest.expanduser().resolve())
    demo_items=[row for row in manifest if str(row.get("dataset"))=="demo"]
    font=detect_font(args.font); primary_variant=resolved_primary_variant(root); results=[]; failures=[]; skipped=0; restart={str(value) for value in args.restart_item}
    for ordinal,item in enumerate(demo_items,1):
        item_id=str(item["item_id"]); item_root=root/"items"/item_id; visual_path=item_root/"visuals/visual_analysis.json"
        visual=read_json(visual_path); alignment_path=item_root/"branches"/primary_variant/"alignment.json"; alignment=read_json(alignment_path)
        render_root=item_root/"renders"; state_path=root/"state/render_items"/f"{item_id}.json"
        expected={
            "behavior":render_root/"behavior_current.mp4",
            "window":render_root/"comparison_window_mechanism.mp4",
            "realign":render_root/"comparison_realign_mechanism.mp4",
            "realign_execution":render_root/"comparison_realign_execution.mp4",
            "decoder":render_root/"comparison_decoder_stages.mp4",
        }
        try:
            if not visual or not alignment: raise FileNotFoundError(f"visual/alignment missing for {item_id}")
            audio=Path(str(item.get("mix_audio_path") or item["audio_path"])).expanduser().resolve()
            request={
                "schema_version":"inline_realign_render_item_request_v3_page_aware_pointer",
                "item_id":item_id,"primary_variant":primary_variant,"visual_sha256":sha256(visual_path),"alignment_sha256":sha256(alignment_path),
                "audio_sha256":sha256(audio),"font":font,"profile":args.profile,
                "renderer_implementation":[
                    file_identity(Path(__file__).resolve()),
                    file_identity(ROOT/"src/lyricalign/demo/timeline_video.py"),
                ],
                "page_groups":{key:[{"path":page["path"],"start":page["start_sec"],"end":page["end_sec"]} for page in visual.get("pages",{}).get(group,[])] for key,group in {"behavior":"behavior","window":"comparison_window","realign":"comparison_realign","realign_execution":"comparison_realign_execution","decoder":"comparison_decoder"}.items()},
            }
            request_hash=canonical_hash(request); old=read_json(state_path)
            if (
                args.resume and not args.force and item_id not in restart
                and old.get("status")=="complete" and old.get("request_hash")==request_hash
                and all(file_ok(path) for path in expected.values())
                and old.get("output_snapshots")==render_output_snapshots(list(expected.values()))
            ):
                skipped+=1; results.append({"item_id":item_id,"status":"resume_skipped","outputs":{k:str(v) for k,v in expected.items()}})
                print(json.dumps({"stage":"render","item":f"{ordinal}/{len(demo_items)}","item_id":item_id,"status":"resume_skipped_complete"},ensure_ascii=False),flush=True); continue
            atomic_state(state_path,{"schema_version":"inline_realign_render_item_state_v2","item_id":item_id,"status":"running","started_at":utc_now(),"request_hash":request_hash,"request":request,"expected_outputs":[str(v) for v in expected.values()]})
            page_groups=visual.get("pages") or {}
            specs=[
                ("behavior","behavior","模型行为：窗口、稳定区与局部重对齐"),
                ("window","comparison_window","窗口与静音策略机制对照"),
                ("realign","comparison_realign","局部重对齐最终方案对照"),
                ("realign_execution","comparison_realign_execution","局部重对齐：精确范围、前后各加2字、前后各加4字与融合"),
                ("decoder","comparison_decoder","原始逐槽结果到最终提交的解码层次对照"),
            ]
            rendered={}
            for key,group,title in specs:
                pages=list(page_groups.get(group) or [])
                if not pages: raise FileNotFoundError(f"{item_id} missing video page group {group}")
                rendered[key]=render_page_video(pages=pages,alignment=alignment,audio_track=audio,output_path=expected[key],work_root=render_root/"work",font=font,title=title,profile=args.profile,force=args.force or item_id in restart,include_karaoke=True)
            missing=[str(path) for path in expected.values() if not file_ok(path)]
            if missing: raise FileNotFoundError(f"rendered videos missing: {missing}")
            atomic_state(state_path,{"schema_version":"inline_realign_render_item_state_v3_strict_outputs","item_id":item_id,"status":"complete","finished_at":utc_now(),"request_hash":request_hash,"outputs":{k:str(v) for k,v in expected.items()},"output_snapshots":render_output_snapshots(list(expected.values()))})
            result={"item_id":item_id,"status":"complete","outputs":{k:str(v) for k,v in expected.items()},"details":rendered}; results.append(result)
            print(json.dumps({"stage":"render","item":f"{ordinal}/{len(demo_items)}","item_id":item_id,"status":"complete"},ensure_ascii=False),flush=True)
        except Exception as exc:
            failure={"item_id":item_id,"reason":"render_failed","error":f"{type(exc).__name__}: {exc}"}; failures.append(failure)
            atomic_state(state_path,{"schema_version":"inline_realign_render_item_state_v2","item_id":item_id,"status":"failed","finished_at":utc_now(),"error":failure["error"]})
            print(json.dumps({"stage":"render",**failure,"status":"failed"},ensure_ascii=False),flush=True)
    payload={
        "schema_version":"inline_realign_demo_render_batch_v6_page_aware_pointer","analysis_completed_before_render":True,
        "demo_item_count":len(demo_items),"rendered_item_count":sum(row.get("status")=="complete" for row in results),
        "resume_skipped_item_count":skipped,"complete_item_count":sum(row.get("status") in {"complete","resume_skipped"} for row in results),"failed_item_count":len(failures),"font":font,"profile":args.profile,"primary_variant":primary_variant,
        "videos_per_item":["behavior_current","comparison_window_mechanism","comparison_realign_mechanism","comparison_realign_execution","comparison_decoder_stages"],
        "results":results,"failures":failures,
    }
    atomic_json(root/"demo_render_summary.json",payload)
    print(json.dumps({"status":"complete" if not failures else "partial_failure","rendered_item_count":payload["rendered_item_count"],"resume_skipped_item_count":skipped,"complete_item_count":payload["complete_item_count"],"failed_item_count":len(failures)},ensure_ascii=False),flush=True)
    return 0 if not failures else 1


if __name__=="__main__": raise SystemExit(main())
