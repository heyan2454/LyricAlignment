#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Inventory the checkpoints the product and the analyses actually depend on.

Training may only be re-run safely if the currently referenced adapter/projector pair stays
byte-identical and available, so record its path, per-file SHA256, the validation numbers it was
selected on, and every place that points at it.  Read-only: nothing here moves or deletes anything.

    PYTHONPATH=src python scripts/evaluation/make_pinned_checkpoint_inventory.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
RUNS = Path("/home/hyan/Data/lyricalign/runs")
DEFAULT_CKPT = RUNS / "20260724_qwen_fa_r2_full_seed20260724/checkpoints/step-000750"
OUT_MD = REPO / "docs/status/20260913_pinned_checkpoint_inventory.md"
OUT_JSON = REPO / "results/by_run/20260913_pinned_checkpoints/metrics.json"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def referenced_by(pattern_dirs: list[Path], needle: str) -> list[dict]:
    hits = []
    for base in pattern_dirs:
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.suffix not in {".sh", ".py", ".yaml", ".yml", ".json"}:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if needle in text:
                hits.append({"path": str(path), "count": text.count(needle)})
    return hits


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", type=Path, default=DEFAULT_CKPT)
    ap.add_argument("--out-md", type=Path, default=OUT_MD)
    ap.add_argument("--out-json", type=Path, default=OUT_JSON)
    args = ap.parse_args()
    ckpt = args.checkpoint
    run_dir = ckpt.parent.parent
    files = []
    for path in sorted(p for p in ckpt.rglob("*") if p.is_file()):
        files.append({"path": str(path.relative_to(ckpt)), "bytes": path.stat().st_size,
                      "sha256": sha256(path)})
    total = sum(f["bytes"] for f in files)
    val: dict[str, Any] = {}
    for vpath in sorted(run_dir.glob("validation_step_*.json")):
        step = re.search(r"(\d+)", vpath.name).group(1)
        payload = json.loads(vpath.read_text(encoding="utf-8"))
        metric = payload.get("metric") or {}
        val[f"step_{int(step):,}"] = {
            "song_macro_boundary_mae_sec": metric.get("song_macro_boundary_mae_sec"),
            "train_loss": payload.get("loss")}
    best = json.loads((run_dir / "best_checkpoint.json").read_text(encoding="utf-8")) if (
        run_dir / "best_checkpoint.json").exists() else {}
    cfg_path = run_dir / "config.yaml"
    stage_cfg: dict = {}
    if cfg_path.exists():
        cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        stage_cfg = {"stages": cfg.get("stages", {}),
                    "training": {k: v for k, v in (cfg.get("training") or {}).items()
                                 if k in ("eval_steps", "save_steps", "lora_lr", "projector_lr",
                                          "gradient_accumulation", "micro_batch_size", "seed",
                                          "warmup_ratio", "weight_decay")}}
    needle = str(ckpt)
    refs = referenced_by([REPO / "configs", REPO / "scripts", REPO / "src"], needle)
    # also count how many batch identities pin it (via the recorded projector sha)
    projector = next((f for f in files if f["path"].endswith("projector.pt")), None)
    batches_using = []
    if projector:
        for align in sorted(RUNS.glob("*/**/alignments/*/*/*/alignment.json"))[:400]:
            try:
                text = align.read_text(encoding="utf-8")
            except OSError:
                continue
            if projector["sha256"][:16] in text:
                batches_using.append(str(align.parent.relative_to(RUNS)))
        # collapse to batch/song counts
        batches_summary = sorted({p.split("/")[0] for p in batches_using})
    else:
        batches_summary = []

    res = {"schema_version": "pinned_checkpoint_inventory_v1",
           "checkpoint": str(ckpt), "run_dir": str(run_dir),
           "total_bytes": total, "files": files,
           "validation_curve": val, "best_from_run_record": best,
           "stage_config": stage_cfg,
           "references_in_repo": refs,
           "batches_referencing_projector_sha": batches_summary,
           "policy": "training reruns must keep this checkpoint byte-identical; "
                     "if it changes, every batch pinned to it is no longer reproducible"}
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(res, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    L: list[str] = []
    w = L.append
    w("# 常用检查点固定清单（生成，勿手改）")
    w("")
    w("> 由 `scripts/evaluation/make_pinned_checkpoint_inventory.py` 生成；"
      "逐文件完整 SHA256 与验证曲线见 `results/by_run/20260913_pinned_checkpoints/metrics.json`。"
      "**只读生成**：不移动、不删除任何检查点。")
    w("")
    w("## 为什么记这个")
    w("")
    w("- 产品默认路径、批次产物身份与多个分析都指向同一个检查点；一旦它被覆盖或漂移，"
      "**历史批次与结论就无法复现**；")
    w("- 因此把逐文件指纹固定下来，作为重训前的对照基线。")
    w("")
    w("## 检查点")
    w("")
    w(f"- 路径：`{ckpt}`")
    w(f"- 大小：{total / 1e6:.2f} MB（{len(files)} 个文件）")
    w("")
    w("| 文件 | 字节 | SHA256 |")
    w("|---|---:|---|")
    for f in files:
        w(f"| `{f['path']}` | {f['bytes']:,} | `{f['sha256'][:16]}…`（全长见 JSON） |")
    w("")
    w("## 它的验证曲线（选择依据，全部来自验证集）")
    w("")
    w("| 检查点 | 验证 song_macro_boundary_mae_sec | 训练损失 |")
    w("|---|---:|---:|")
    for step, v in val.items():
        mae = v["song_macro_boundary_mae_sec"]
        mark = "（被选中）" if str(best.get("step", "")).strip() and (
            f"step_{best['step']:,}" == step) else ""
        w(f"| {step.replace('step_', '')} | {mae if mae is None else round(mae, 5)}{mark} | "
          f"{round(v['train_loss'], 4) if v['train_loss'] is not None else '—'} |")
    w("")
    stages = stage_cfg.get("stages", {}) if stage_cfg else {}
    w(f"- 该阶段训练预算：**max_steps = {stages.get('r2', {}).get('max_steps')}**"
      "（保存/评估每 250 步；无早停），所以停止原因是**步数预算用尽**，不是收敛判据；")
    w(f"- 记录的最优：step {best.get('step')}，"
      f"mae {best.get('song_macro_boundary_mae_sec')}；"
      "**1000 步起验证指标变差**（见上表）⇒ 单纯加步数无收益。")
    w("")
    w("## 谁在引用它")
    w("")
    w("| 引用处 | 次数 |")
    w("|---|---:|")
    for r in refs:
        w(f"| `{Path(r['path']).relative_to(REPO)}` | {r['count']} |")
    w("")
    if batches_summary:
        w(f"- 以 projector 指纹自检时，**{len(batches_summary)} 个批次的对齐产物**引用了这份投影权重："
          + "、".join(f"`{b}`" for b in batches_summary[:6])
          + ("…" if len(batches_summary) > 6 else ""))
    w("")
    w("## 重训前的硬要求")
    w("")
    w("1. **保留原件**：新训练写到新的 run 目录，禁止复用/覆盖上面这个路径；")
    w("2. **重训后先比指纹**：若 `projector.pt` 或 adapter 权重变了，本清单里"
      "引用它的批次必须重新验证，不能继续沿用旧结论；")
    w("3. 检查点选择只允许用验证集（本例即 `M4Singer_validation` 的 song 宏平均边界 MAE），"
      "test/OOD 不参与选择——这条已由 run 内的 `final_checkpoint_selection.json` 记录。")
    w("")
    args.out_md.parent.mkdir(parents=True, exist_ok=True)
    args.out_md.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(json.dumps({"out_md": str(args.out_md), "out_json": str(args.out_json),
                      "files": len(files), "total_mb": round(total / 1e6, 2),
                      "repo_refs": len(refs), "batches": len(batches_summary)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    from typing import Any
    raise SystemExit(main())
