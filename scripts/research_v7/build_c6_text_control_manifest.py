#!/usr/bin/env python3
"""Build C6 reordered, random-permutation, and wrong-language text controls."""
from __future__ import annotations

import argparse
import json
import random
import wave
from pathlib import Path


def gt_units(path: str) -> list[str]:
    return [json.loads(line)["normalized_character"] for line in Path(path).read_text(encoding="utf-8").splitlines() if line]


def duration(path: str) -> float:
    with wave.open(path, "rb") as f: return f.getnframes()/f.getframerate()


def main(argv=None) -> int:
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--manifest',required=True);p.add_argument('--out',required=True);p.add_argument('--unit-count',type=int,default=64);p.add_argument('--seed',type=int,default=3407);a=p.parse_args(argv)
    out=[]
    for line in Path(a.manifest).read_text(encoding='utf-8').splitlines():
        if not line: continue
        r=json.loads(line); base=gt_units(r['gt_path'])[:a.unit_count]
        if len(base)<2: continue
        total=duration(r['audio_path']); common={'item_id':r['item_id'],'song_id':r.get('song_id'),'source_song_id':r.get('source_song_id'),'dataset':r.get('dataset'),'split':r.get('split'),'language':r.get('language','Chinese'),'audio_path':r['audio_path'],'gt_path':r['gt_path'],'text_source':r['gt_path'],'audio_start_sec':0.,'audio_end_sec':total,'duration_sec':total,'baseline_unit_count':len(base),'n_base':len(base),'audio_relation':'full_source_audio','selection_seed':a.seed}
        rng=random.Random(f'{a.seed}:{r["item_id"]}'); shuffled=list(base);rng.shuffle(shuffled)
        reversed_sections=[]
        for i in range(0,len(base),max(1,len(base)//4)): reversed_sections.extend(reversed(base[i:i+max(1,len(base)//4)]))
        wrong_language=(['the','night','will','fall','and','we','will','sing']*((len(base)+6)//7))[:len(base)]
        variants=[('baseline','baseline',base,'exact'),('reordered_real_lyrics','replace',reversed_sections,'reordered_real_lyrics'),('random_permutation_control','replace',shuffled,'random_permutation'),('wrong_language_unit_mode','replace',wrong_language,'wrong_language_unit_mode')]
        for name,kind,text,relation in variants: out.append({**common,'request_id':f'{r["item_id"]}:C6:{name}','mutation_type':kind,'requested_ratio':0. if kind=='baseline' else 1.,'actual_ratio':0. if kind=='baseline' else 1.,'actual_replaced_units':0 if kind=='baseline' else len(base),'mutation_position':'whole','text_relation':relation,'text_units':text})
    target=Path(a.out);target.parent.mkdir(parents=True,exist_ok=True);target.write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in out),encoding='utf-8');print(json.dumps({'ok':True,'items':len({x['item_id'] for x in out}),'requests':len(out),'out':str(target)},ensure_ascii=False));return 0
if __name__=='__main__':raise SystemExit(main())
