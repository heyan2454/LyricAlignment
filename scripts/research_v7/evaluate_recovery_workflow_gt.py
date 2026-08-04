#!/usr/bin/env python3
"""Score each recovery-chain segment and compare corrected tail to P0 tail."""
from __future__ import annotations

import argparse,json
from pathlib import Path


def score(payload: dict, window: tuple[int, int] | None = None) -> float | None:
    attempt, request = payload["attempt"], payload["attempt"]["request"]
    if attempt["status"] != "ok": return None
    gt=[json.loads(x) for x in Path(request["text_source"]).read_text().splitlines() if x]
    start,end = window or tuple(int(request["mutation_parameters"].get(k) or 0) for k in ("source_text_start_index","source_text_end_index"))
    errors=[]
    for row in attempt["decoder_outputs"]["official"]["rows"]:
        i=int(row["global_character_index"])
        if start <= i < end and i < len(gt): errors += [abs(float(row["fixed_global_start_sec"])-float(gt[i]["start_sec"])),abs(float(row["fixed_global_end_sec"])-float(gt[i]["end_sec"]))]
    return sum(errors)/len(errors) if errors else None


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--collection',required=True);p.add_argument('--out',required=True);a=p.parse_args(argv)
    c=json.loads(Path(a.collection).read_text());root=Path(c['out_root']); rows=[]
    for r in c['records']:
        x=json.loads((root/r['source']).read_text());q=x['attempt']['request']; rows.append({'item_id':q['item_id'],'mode':q['workflow_mode'],'request_id':q['request_id'],'mae_sec':score(x),'payload':x})
    by={};
    for row in rows: by.setdefault(row['item_id'],{})[row['mode']]=row
    recovery=[]
    for item,modes in by.items():
        p0=modes.get('production_full_once'); recovered=modes.get('recovery_corrected_prefix')
        window=tuple(int(recovered['payload']['attempt']['request']['mutation_parameters'].get(k) or 0) for k in ('source_text_start_index','source_text_end_index')) if recovered else None
        p0_tail=score(p0['payload'], window) if p0 and window else None; recovered_tail=recovered['mae_sec'] if recovered else None
        recovery.append({'item_id':item,'p0_tail_mae_sec':p0_tail,'recovered_tail_mae_sec':recovered_tail,'delta_from_p0_tail_mae_sec':(recovered_tail-p0_tail if recovered_tail is not None and p0_tail is not None else None)})
    d=[x['delta_from_p0_tail_mae_sec'] for x in recovery if x['delta_from_p0_tail_mae_sec'] is not None]
    safe_rows=[{k:v for k,v in row.items() if k!='payload'} for row in rows]
    out={'schema':'research_v7/recovery_workflow_gt_v1','attempts':safe_rows,'recovery':recovery,'summary':{'items':len(recovery),'mean_recovered_minus_p0_tail_mae_sec':sum(d)/len(d) if d else None}}
    Path(a.out).write_text(json.dumps(out,ensure_ascii=False,indent=1)+'\n');print(json.dumps({'ok':True,'items':len(recovery),'out':a.out},ensure_ascii=False));return 0
if __name__=='__main__':raise SystemExit(main())
