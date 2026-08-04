#!/usr/bin/env python3
"""Construct same-source-song wrong-section texts from other real M4 GT segments."""
from __future__ import annotations

import argparse
import json
import wave
from collections import defaultdict
from pathlib import Path


def units(path: str) -> list[str]:
    return [json.loads(line)["normalized_character"] for line in Path(path).read_text(encoding="utf-8").splitlines() if line]


def duration(path: str) -> float:
    with wave.open(path, "rb") as f: return f.getnframes()/f.getframerate()


def main(argv=None) -> int:
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--full-manifest',required=True);p.add_argument('--targets',required=True);p.add_argument('--out',required=True);p.add_argument('--unit-count',type=int,default=64);a=p.parse_args(argv)
    pool=defaultdict(list)
    for line in Path(a.full_manifest).read_text(encoding='utf-8').splitlines():
        if not line: continue
        r=json.loads(line)
        if r.get('dataset')=='m4singer' and r.get('split')=='test' and Path(r.get('gt_path','')).is_file(): pool[r.get('source_song_id')].append(r)
    out=[]
    for line in Path(a.targets).read_text(encoding='utf-8').splitlines():
        if not line: continue
        target=json.loads(line);base=units(target['gt_path'])[:a.unit_count];n=len(base); donor=[]; provenance=[]
        for candidate in sorted(pool[target['source_song_id']],key=lambda r:r['item_id']):
            if candidate['item_id']==target['item_id']: continue
            take=units(candidate['gt_path']); donor.extend(take);provenance.append({'item_id':candidate['item_id'],'gt_path':candidate['gt_path'],'units_taken':len(take)})
            if len(donor)>=n:break
        if len(donor)<n: raise RuntimeError(f"no same-song donor units for {target['item_id']}")
        donor=donor[:n];total=duration(target['audio_path']);common={'item_id':target['item_id'],'song_id':target.get('song_id'),'source_song_id':target.get('source_song_id'),'dataset':target.get('dataset'),'split':target.get('split'),'language':target.get('language','Chinese'),'audio_path':target['audio_path'],'gt_path':target['gt_path'],'text_source':target['gt_path'],'audio_start_sec':0.,'audio_end_sec':total,'duration_sec':total,'baseline_unit_count':n,'n_base':n,'audio_relation':'full_source_audio','donor_segments':provenance}
        out.append({**common,'request_id':f'{target["item_id"]}:C6:baseline','mutation_type':'baseline','text_relation':'exact','text_units':base})
        out.append({**common,'request_id':f'{target["item_id"]}:C6:same-song-wrong-section','mutation_type':'replace','requested_ratio':1.,'actual_ratio':1.,'actual_replaced_units':n,'mutation_position':'whole','text_relation':'same_song_wrong_section','text_units':donor})
    target=Path(a.out);target.parent.mkdir(parents=True,exist_ok=True);target.write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in out),encoding='utf-8');print(json.dumps({'ok':True,'items':len({x['item_id'] for x in out}),'requests':len(out),'out':str(target)},ensure_ascii=False));return 0
if __name__=='__main__':raise SystemExit(main())
