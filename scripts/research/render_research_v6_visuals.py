#!/usr/bin/env python3
"""Create compact research-v6 comparison plots and a navigable Markdown index."""
from __future__ import annotations
import argparse, json
from pathlib import Path
import sys
import matplotlib.pyplot as plt


def load(path: Path): return json.loads(path.read_text(encoding="utf-8"))

def rows(payload): return payload.get("characters", [])

def draw(item_id: str, candidates: list[tuple[str,list[dict]]], output: Path, max_units: int=240):
    fig, ax = plt.subplots(figsize=(16, max(3, 0.55*len(candidates)+1.5)))
    for y,(name,data) in enumerate(candidates):
        for r in data[:max_units]:
            s=float(r.get("start_sec",r.get("official_fixed_global_start_sec",0))); e=float(r.get("end_sec",r.get("official_fixed_global_end_sec",s)))
            ax.plot([s,e],[y,y],linewidth=2)
        ax.text(ax.get_xlim()[0] if ax.get_xlim()[1]>ax.get_xlim()[0] else 0, y+0.12, name, fontsize=8)
    ax.set_yticks(range(len(candidates)), [n for n,_ in candidates]); ax.set_xlabel("time (s)"); ax.set_title(item_id); ax.grid(True,axis="x",alpha=.25)
    fig.tight_layout(); output.parent.mkdir(parents=True,exist_ok=True); fig.savefig(output,dpi=120); plt.close(fig)

def main():
    p=argparse.ArgumentParser(); p.add_argument("--formal-root",type=Path,required=True); p.add_argument("--baseline-root",type=Path,required=True); p.add_argument("--out-root",type=Path,required=True); p.add_argument("--max-items",type=int,default=0); a=p.parse_args()
    a.out_root.mkdir(parents=True,exist_ok=True); lines=["# Research v6 visual index",""]
    items=sorted((a.formal_root/"items").glob("*/item_summary.json")); items=items if a.max_items<=0 else items[:a.max_items]
    count=0
    for summary_path in items:
        item_id=summary_path.parent.name; base_path=a.baseline_root/"items"/item_id/"branches"/"B4_60_silence_official"/"alignment.json"
        if not base_path.is_file(): continue
        candidates=[("B4 official",rows(load(base_path)))]
        exp=summary_path.parent/"experimental_alignments"
        for name in ("decoder_raw","decoder_official","decoder_joint_start_end","decoder_topk_sequence","decoder_weighted_isotonic","E8_local_raw","E8_local_official","E8_local_topk_sequence"):
            f=exp/name/"alignment.json"
            if f.is_file(): candidates.append((name,rows(load(f))))
        png=a.out_root/"items"/item_id/"alignment_candidates.png"; draw(item_id,candidates,png)
        lines += [f"## {item_id}",f"![{item_id}](items/{item_id}/alignment_candidates.png)",f"- Summary: `{summary_path}`"]
        case_root=summary_path.parent/"realign_cases"
        for case_dir in sorted(case_root.glob("case_*")) if case_root.is_dir() else []:
            case_candidates=[("baseline",rows(load(base_path)))]
            for decoder_dir in sorted(case_dir.iterdir()):
                f=decoder_dir/"alignment.json"
                if f.is_file(): case_candidates.append((decoder_dir.name,rows(load(f))))
            case_png=a.out_root/"items"/item_id/f"{case_dir.name}.png"
            draw(f"{item_id} {case_dir.name}",case_candidates,case_png)
            lines.append(f"![{case_dir.name}](items/{item_id}/{case_dir.name}.png)")
        lines.append("")
        count+=1
    (a.out_root/"visual_index.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    (a.out_root/"complete.json").write_text(json.dumps({"status":"complete","item_count":count},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return 0
if __name__=="__main__": raise SystemExit(main())
