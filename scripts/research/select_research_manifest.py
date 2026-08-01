#!/usr/bin/env python3
"""Create an active manifest without changing the immutable full manifest."""
from __future__ import annotations
import argparse, json
from pathlib import Path


def main():
    p=argparse.ArgumentParser(); p.add_argument('--input',type=Path,required=True); p.add_argument('--output',type=Path,required=True); p.add_argument('--mode',choices=('formal','smoke'),required=True); p.add_argument('--item-id'); a=p.parse_args()
    rows=[json.loads(x) for x in a.input.read_text(encoding='utf-8').splitlines() if x.strip()]
    if a.mode=='formal': selected=rows
    elif a.item_id:
        selected=[r for r in rows if str(r['item_id'])==a.item_id]
        if not selected: raise ValueError(f'item not found: {a.item_id}')
    else:
        selected=[next((r for r in rows if r.get('dataset')=='demo'), rows[0])]
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(''.join(json.dumps(r,ensure_ascii=False,sort_keys=True)+'\n' for r in selected),encoding='utf-8')
    audit={'mode':a.mode,'full_item_count':len(rows),'active_item_count':len(selected),'item_ids':[r['item_id'] for r in selected], 'formal_full_population': a.mode=='formal' and len(selected)==len(rows)}
    a.output.with_suffix('.audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(audit,ensure_ascii=False))
    return 0
if __name__=='__main__': raise SystemExit(main())
