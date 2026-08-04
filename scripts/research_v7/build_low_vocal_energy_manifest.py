#!/usr/bin/env python3
"""Build review-only low-vocal-energy audio controls from local demo vocal WAVs."""
from __future__ import annotations

import argparse
import json
import wave
from pathlib import Path

import numpy as np

PUNCT = set("，。！？、,.!?;:：；()（）[]【】\"'“”‘’—-…")


def lyric_units(path: str, limit: int) -> list[str]:
    return [c for c in Path(path).read_text(encoding="utf-8") if not c.isspace() and c not in PUNCT][:limit]


def quietest_window(path: str, window_sec: float) -> tuple[float, float, float]:
    with wave.open(path, "rb") as f:
        rate=f.getframerate(); channels=f.getnchannels(); width=f.getsampwidth(); raw=f.readframes(f.getnframes())
    if width != 2: raise ValueError(f"unsupported sample width {width}: {path}")
    x=np.frombuffer(raw,dtype='<i2').astype(np.float32)
    if channels>1:x=x.reshape(-1,channels).mean(axis=1)
    window=max(1,int(window_sec*rate)); hop=max(1,window//4)
    if len(x)<=window:return 0.,len(x)/rate,float(np.sqrt(np.mean(x*x)+1e-12))
    power=np.concatenate(([0.],np.cumsum(x*x,dtype=np.float64)))
    starts=np.arange(0,len(x)-window+1,hop); rms=np.sqrt((power[starts+window]-power[starts])/window+1e-12)
    index=int(np.argmin(rms));return float(starts[index]/rate),float((starts[index]+window)/rate),float(rms[index])


def main(argv=None)->int:
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--manifest',required=True);p.add_argument('--out',required=True);p.add_argument('--window-sec',type=float,default=8.0);p.add_argument('--unit-count',type=int,default=32);a=p.parse_args(argv)
    out=[]
    for line in Path(a.manifest).read_text(encoding='utf-8').splitlines():
        if not line:continue
        r=json.loads(line)
        if r.get('dataset')!='demo' or r.get('gt_path') is not None:continue
        audio=Path(r['audio_path']);lyrics=Path(r['lyrics_path'])
        if not audio.is_file() or not lyrics.is_file():continue
        text=lyric_units(str(lyrics),a.unit_count)
        if len(text)<2:continue
        start,end,rms=quietest_window(str(audio),a.window_sec)
        out.append({'item_id':r['item_id'],'song_id':r.get('source_song_id'),'source_song_id':r.get('source_song_id'),'dataset':'demo','split':'demo_challenge','language':r.get('language'),'gt_available':False,'audio_path':r['audio_path'],'text_source':r['lyrics_path'],'audio_start_sec':start,'audio_end_sec':end,'baseline_unit_count':len(text),'n_base':len(text),'request_id':f'{r["item_id"]}:C6:low-vocal-energy','mutation_type':'replace','requested_ratio':1.,'actual_ratio':1.,'actual_replaced_units':len(text),'mutation_position':'whole','text_relation':'instrumental_audio_with_real_lyrics','audio_relation':'low_vocal_energy_candidate','text_units':text,'provenance':{'selection':'minimum_rms_sliding_window','window_sec':a.window_sec,'rms':rms}})
    target=Path(a.out);target.parent.mkdir(parents=True,exist_ok=True);target.write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in out),encoding='utf-8');print(json.dumps({'ok':True,'items':len(out),'out':str(target)},ensure_ascii=False));return 0
if __name__=='__main__':raise SystemExit(main())
