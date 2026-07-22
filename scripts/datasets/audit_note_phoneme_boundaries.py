#!/usr/bin/env python3
"""Quantify note-event boundaries against nearest phoneme boundaries."""
from __future__ import annotations
import argparse, json
from pathlib import Path
import matplotlib.pyplot as plt

def cumulative(values):
    cursor=0.; result=[0.]
    for value in values: cursor += float(value); result.append(cursor)
    return result

def main():
    p=argparse.ArgumentParser(); p.add_argument('--meta',type=Path,required=True); p.add_argument('--out-dir',type=Path,required=True); a=p.parse_args()
    signed=[]
    for row in json.loads(a.meta.read_text(encoding='utf-8')):
        ph=cumulative(row['ph_dur']); events=[]; previous=None; cursor=0.
        for note,duration in zip(row['notes'],row['notes_dur'],strict=True):
            key=(int(note),float(duration))
            if key != previous: events.extend((cursor,cursor+key[1])); cursor += key[1]; previous=key
        for boundary in events:
            nearest=min(ph,key=lambda value:abs(value-boundary)); signed.append(boundary-nearest)
    absolute=[abs(value) for value in signed]; a.out_dir.mkdir(parents=True,exist_ok=True)
    fig,axes=plt.subplots(1,2,figsize=(10,4),constrained_layout=True); axes[0].boxplot(signed,showfliers=False); axes[0].axhline(0,color='black',linewidth=.8); axes[0].set(title='Signed note boundary − nearest phoneme boundary',ylabel='seconds',xticks=[]); axes[1].boxplot(absolute,showfliers=False); axes[1].set(title='Absolute nearest-boundary difference',ylabel='seconds',xticks=[]); fig.savefig(a.out_dir/'note_phoneme_boundary_boxplot.png',dpi=180); plt.close(fig)
    summary={'record_count':len(json.loads(a.meta.read_text(encoding='utf-8'))),'boundary_count':len(signed),'signed_sec':{'min':min(signed),'median':sorted(signed)[len(signed)//2],'max':max(signed)},'absolute_sec':{'median':sorted(absolute)[len(absolute)//2],'p95':sorted(absolute)[int(.95*(len(absolute)-1))],'max':max(absolute)}}
    (a.out_dir/'note_phoneme_boundary_summary.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8'); print(json.dumps(summary))
if __name__=='__main__': main()
