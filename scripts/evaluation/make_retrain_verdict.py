#!/usr/bin/env python3
"""Generate the retrain verdict (numbers from JSON, never hand-copied).

Assembles the three independent views that decide "did fine-tuning from the official base help?":
the trainer's own validation on the full split, the funnel top-up's test-scale comparison, and the
per-character paired comparison on identical characters.  Re-run any time to refresh: it tolerates
missing pieces (e.g. before the whole-set top-up exists) and prints what it used.

    PYTHONPATH=src python scripts/evaluation/make_retrain_verdict.py
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

DATA = Path("/home/hyan/Data/lyricalign/runs")
OLD_RUN = DATA / "20260724_qwen_fa_r2_full_seed20260724"
NEW_RUN = DATA / "20260913_qwen_fa_r2_from_official_seed20260724"
KEYS = ("song_macro_boundary_mae_sec", "joint_within_80ms", "joint_within_160ms", "joint_within_240ms",
        "zero_duration_rate", "onset_mae_sec", "offset_mae_sec", "valid_only_boundary_mae_sec")


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def validation(path: Path) -> dict[str, Any] | None:
    doc = read_json(path)
    if not doc:
        return None
    metric = doc.get("metric") or {}
    return {key: metric.get(key) for key in KEYS if isinstance(metric.get(key), (int, float))}


def topup_rows(out_dir: Path) -> list[dict[str, Any]]:
    doc = read_json(out_dir / "metrics.json")
    if not doc:
        return []
    rows = []
    for row in doc["summary"]["topup"]:
        fixed = (row.get("variants") or {}).get("fixed") or {}
        rows.append({"label": row["label"], "level": row["level"], "source": row.get("source"),
                     "macro": fixed.get("macro_within_primary"), "se": fixed.get("se"),
                     "usable": fixed.get("usable_rate"), "mae_ms": fixed.get("mae_all_ms")})
    return rows


def build(repo: Path) -> dict[str, Any]:
    payload: dict[str, Any] = {"schema_version": "retrain_verdict_v1",
                                "old_run": str(OLD_RUN), "new_run": str(NEW_RUN), "sources": {}}
    old = validation(OLD_RUN / "validation_step_000750.json")
    new = validation(NEW_RUN / "validation_step_012000.json")
    payload["trainer_validation"] = {"old_750": old, "new_12000": new}
    payload["sources"]["trainer_validation"] = bool(old and new)
    for name, directory in (("l2_l3_selection", repo / "results/by_run/20260913_final_selection"),
                            ("l3_full", repo / "results/by_run/20260914_final_selection_l3")):
        rows = topup_rows(directory)
        if rows:
            payload[name] = rows
            payload["sources"][name] = True
    paired = read_json(repo / "results/by_run/20260914_paired_old750_vs_new12000/metrics.json")
    if paired:
        payload["paired_per_character"] = paired
        payload["sources"]["paired_per_character"] = True
    return payload


def markdown(payload: dict[str, Any]) -> str:
    lines = ["# 重训结论：从官方底座重训到底有没有用（生成，勿手改）", "",
             f"> 由 `scripts/evaluation/make_retrain_verdict.py` 生成；用到的数据源：{payload['sources']}。"]
    trainer = payload.get("trainer_validation") or {}
    old, new = trainer.get("old_750"), trainer.get("new_12000")
    if old and new:
        lines += ["", "## 1. 训练器自己的全量验证（同一份代码、同一验证集、同一解码路径）", "",
                  "| 指标 | 旧 r2/step-750 | 新 run/step-12000 | 变化 |", "|---|---|---|---|"]

        def fmt(value: float, unit: str = "s") -> str:
            return f"{value * 1000:.2f} ms" if unit == "s" else f"{value:.4f}"

        for key, unit, scale in (("song_macro_boundary_mae_sec", "s", 1000),
                                 ("onset_mae_sec", "s", 1000), ("offset_mae_sec", "s", 1000),
                                 ("valid_only_boundary_mae_sec", "s", 1000),
                                 ("joint_within_80ms", "ratio", 100), ("joint_within_160ms", "ratio", 100),
                                 ("zero_duration_rate", "ratio", 100)):
            if key not in old or key not in new:
                continue
            if unit == "s":
                delta = (new[key] - old[key]) * scale
                lines.append(f"| {key} | {old[key] * scale:.2f} ms | {new[key] * scale:.2f} ms | {delta:+.2f} ms |")
            else:
                delta = (new[key] - old[key]) * scale
                lines.append(f"| {key} | {old[key] * scale:.2f}% | {new[key] * scale:.2f}% | {delta:+.2f} pp |")
    selection = payload.get("l2_l3_selection") or []
    if selection:
        lines += ["", "## 2. 测试口径（0.2s 命中率，歌平均）同协议复评", "",
                  "| 候选 | 层级 | fixed | 1SE | 可用率 | MAE(ms) |", "|---|---|---|---|---|---|"]
        for row in sorted(selection, key=lambda r: (r["level"], -(r["macro"] or 0))):
            if row["macro"] is None:
                continue
            source = "" if row.get("source") == "run" else "（外来基线）"
            lines.append(f"| {row['label']}{source} | {row['level']} | {row['macro']:.4f} | "
                         f"{(row['se'] or 0):.4f} | {(row['usable'] or 0):.4f} | {(row['mae_ms'] or 0):.1f} |")
    paired = payload.get("paired_per_character") or {}
    sides = paired.get("sides") or {}
    if sides:
        lines += ["", f"## 3. 逐字符配对（同一批 {paired.get('items')} 条、"
                      f"{paired.get('shared_measurements')} 次测量；负=新模型更好）", "",
                  "| 比较 | n | 均差(ms) | SE | z | 超 0.2s 率 |", "|---|---|---|---|---|---|"]
        for name, block in sides.items():
            lines.append(f"| {name} | {block['n']} | {block['mean_delta_ms']:+.1f} | {block['se_ms']:.1f} | "
                         f"{block['z']} | {block.get('miss_rate_old', 0):.1%} → {block.get('miss_rate_new', 0):.1%} |")
    old_mae = (old or {}).get("song_macro_boundary_mae_sec")
    new_mae = (new or {}).get("song_macro_boundary_mae_sec")
    old_j = (old or {}).get("joint_within_80ms")
    new_j = (new or {}).get("joint_within_80ms")
    combined = (sides.get("combined_all") or {})
    combined_long = (sides.get("combined_long") or {})
    offset_short = (sides.get("offset_short") or {})
    l2_rows = [row for row in selection if row["level"] == "l2"]
    old_l2 = [row["macro"] for row in l2_rows if row["label"] == "old-r2-750" and row["macro"]]
    new_l2 = [row["macro"] for row in l2_rows if row.get("source") == "run" and row["macro"]]
    conclusions = ["", "## 结论", ""]
    if old_mae and new_mae:
        conclusions.append(
            f"1. **重训有效，但幅度小、且需要步数**：训练器全量口径 MAE "
            f"{old_mae * 1000:.2f} ms → {new_mae * 1000:.2f} ms（{(new_mae - old_mae) * 1000:+.2f} ms，"
            f"{(new_mae / old_mae - 1) * 100:+.1f}%）"
            + (f"，joint@80ms {(new_j - old_j) * 100:+.2f} pp" if old_j and new_j else "") + "；")
    if old_l2 and new_l2:
        conclusions.append(
            f"2. 测试口径（0.2s 命中率，歌平均）中层复评：旧 750 = {max(old_l2):.4f}，"
            f"新 run 最好 = {max(new_l2):.4f}（{(max(new_l2) - max(old_l2)) * 100:+.2f} pp）；")
    if combined:
        conclusions.append(
            f"3. **早上那句\"重训≈旧模型\"是错的**：当时只能评到 step 1100–1450（训练内漏斗的 L2 名额"
            f"被早期存档吃光）。逐字符配对现在给出全部字符 {combined['mean_delta_ms']:+.1f} ms"
            f"（z={combined['z']}），长字符 {combined_long.get('mean_delta_ms', 0):+.1f} ms"
            f"（z={combined_long.get('z')}，n={combined_long.get('n')}，功效不足），"
            f"短字符结束点 {offset_short.get('mean_delta_ms', 0):+.1f} ms（z={offset_short.get('z')}）"
            " ⇒ 长音符改善更大但样本不够，**长音符仍是未解决的靶子**；")
    conclusions += ["",
                    "## 与既有文档的关系",
                    "",
                    "- 取代 `docs/status/20260913_from_official_finetune_runbook.md` 里\"判读规则\"第 2 条的假设："
                    "**训练有收益但边际很小**；",
                    "- 与 `docs/status/20260913_long_note_ambiguity.md` 一致：剩下的长音符误差约 88% 是有声学"
                    "证据的真实模型错误，所以继续攻它是值得的；",
                    "- 教训（已写进漏斗修复）：**选点集合被预算饿死会直接产出错误的科学结论**。",
                    ""]
    lines += conclusions
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args()
    payload = build(args.repo)
    out = args.out or (args.repo / "results/by_run/20260914_retrain_verdict/metrics.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    report = args.report or (args.repo / "docs/status/20260914_retrain_verdict.md")
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(markdown(payload), encoding="utf-8")
    print(json.dumps({"sources": payload["sources"], "written": [str(out), str(report)]},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
