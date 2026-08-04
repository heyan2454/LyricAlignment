#!/usr/bin/env python3
"""Assess request-level posterior entropy/margin separation in frozen evidence."""
from __future__ import annotations

import argparse,json
from collections import defaultdict
from pathlib import Path


def mean(x): return sum(x)/len(x) if x else None


def auc(positive, negative, higher_positive=True):
    """Tie-aware Mann--Whitney AUROC; samples are requests, not characters."""
    if not positive or not negative: return None
    wins=ties=0
    for a in positive:
        for b in negative:
            better=a>b if higher_positive else a<b
            wins += better; ties += a==b
    return (wins+.5*ties)/(len(positive)*len(negative))


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--collection',required=True);p.add_argument('--out',required=True);a=p.parse_args(argv)
    c=json.loads(Path(a.collection).read_text());root=Path(c['out_root']); grouped=defaultdict(lambda:defaultdict(list))
    for r in c['records']:
        x=json.loads((root/r['source']).read_text());q=x['attempt']['request'];typ=q['mutation_type']; rows=x['attempt']['decoder_outputs'].get('_posterior',{}).get('rows',[])
        values=defaultdict(list)
        for z in rows:
            for k in ('start_entropy','end_entropy','start_margin','end_margin'):
                if z.get(k) is not None: values[k].append(float(z[k]))
        for k,v in values.items(): grouped[typ][k].append(mean(v))
    summary={typ:{k:{'request_count':len(v),'mean':mean(v),'min':min(v) if v else None,'max':max(v) if v else None} for k,v in d.items()} for typ,d in sorted(grouped.items())}
    comparisons={}
    for target in ('extra','missing','replace','no_match'):
        if target not in grouped or 'baseline' not in grouped: continue
        comparisons[target]={
            'entropy_auc_vs_baseline': auc(grouped[target]['start_entropy'],grouped['baseline']['start_entropy'],True),
            'margin_auc_vs_baseline': auc(grouped[target]['start_margin'],grouped['baseline']['start_margin'],False),
            'positive_label':target,'sample_unit':'request'}
    out={'schema':'research_v7/internal_signal_separation_v1','by_mutation':summary,'comparisons_vs_baseline':comparisons,
         'note':'AUROC compares request-mean posterior values. It demonstrates separation in these frozen mutations; it is not a calibrated QualityAssessor.'}
    Path(a.out).write_text(json.dumps(out,ensure_ascii=False,indent=1)+'\n');print(json.dumps({'ok':True,'groups':len(summary),'out':a.out},ensure_ascii=False));return 0
if __name__=='__main__':raise SystemExit(main())
