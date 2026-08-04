#!/usr/bin/env python3
"""Build real accompaniment-only + lyrics C6 controls from demo prepared assets."""
from __future__ import annotations
import argparse,json,wave
from pathlib import Path

PUNCT=set("，。！？、,.!?;:：；()（）[]【】\"'“”‘’—-…")
def units(path,limit):return [c for c in Path(path).read_text(encoding='utf-8') if not c.isspace() and c not in PUNCT][:limit]
def duration(path):
 with wave.open(path,'rb') as f:return f.getnframes()/f.getframerate()
def main(argv=None):
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--manifest',required=True);p.add_argument('--out',required=True);p.add_argument('--unit-count',type=int,default=32);a=p.parse_args(argv);out=[]
 for line in Path(a.manifest).read_text(encoding='utf-8').splitlines():
  if not line:continue
  r=json.loads(line)
  if r.get('dataset')!='demo' or r.get('gt_path') is not None:continue
  audio=Path(r['audio_path']).with_name('accompaniment.wav');text=units(r['lyrics_path'],a.unit_count)
  if not audio.is_file() or len(text)<2:continue
  total=duration(str(audio));out.append({'item_id':r['item_id'],'song_id':r.get('source_song_id'),'source_song_id':r.get('source_song_id'),'dataset':'demo','split':'demo_challenge','language':r.get('language'),'gt_available':False,'audio_path':str(audio),'text_source':r['lyrics_path'],'audio_start_sec':0.,'audio_end_sec':total,'duration_sec':total,'baseline_unit_count':len(text),'n_base':len(text),'request_id':f'{r["item_id"]}:C6:accompaniment-only','mutation_type':'replace','requested_ratio':1.,'actual_ratio':1.,'actual_replaced_units':len(text),'mutation_position':'whole','text_relation':'instrumental_audio_with_real_lyrics','audio_relation':'verified_accompaniment_only','text_units':text,'provenance':{'prepared_from':r['audio_path'],'accompaniment_path':str(audio)}})
 target=Path(a.out);target.parent.mkdir(parents=True,exist_ok=True);target.write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in out),encoding='utf-8');print(json.dumps({'ok':True,'items':len(out),'out':str(target)},ensure_ascii=False));return 0
if __name__=='__main__':raise SystemExit(main())
