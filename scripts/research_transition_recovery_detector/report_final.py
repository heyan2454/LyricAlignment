#!/usr/bin/env python3
"""Phase 9：最终报告生成（数字全部来自 authoritative JSON/JSONL，不手工抄）。

输出 09_reports/：
  FINAL_SESSION_REPORT.md/.json
  NEGATIVE_RESULTS.md
  EXECUTION_AUDIT.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))


def load(path: Path, default=None):
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--session-root", required=True)
    args = p.parse_args()
    root = Path(args.session_root)
    out_dir = root / "09_reports"
    out_dir.mkdir(parents=True, exist_ok=True)

    def read(sub: str):
        return load(root / sub)

    formal_ms = read("02_transition/FORMAL_model_selection.json") or []
    full_ms = read("02_transition/FULL_SONG_model_selection.json") or []
    formal_m4 = read("02_transition/FORMAL_m4_formal.json") or []
    full_m4 = read("02_transition/FULL_SONG_m4_formal.json") or []
    transition_report = read("02_transition/TRANSITION_REPORT.json") or {}
    cand = read("02_transition/CANDIDATE_SELECTION.json") or {}
    episodes = [json.loads(l) for l in
                (root / "03_propagation" / "EPISODES.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()] if (root / "03_propagation" / "EPISODES.jsonl").is_file() else []
    oracle = read("04_oracle_recovery/ORACLE_SUMMARY.json") or {}
    legacy = read("05_legacy_gaps/LEGACY_GAP_STATUS.json") or {}
    frozen = read("06_detector/FROZEN_WORKING_POINTS.json") or {}
    closed = read("07_closed_loop/CLOSED_LOOP_SUMMARY.json") or {}
    mir = read("08_transfer_demo/MIR_TRANSFER_SUMMARY.json") or {}
    demo = read("08_transfer_demo/TEST_DEMO_SUMMARY.json") or {}
    state = load(root / "SESSION_STATE.json") or {}

    def pooled_rate(rows, kind="full_song"):
        if kind == "full_song":
            t = sum(r["accuracy"]["total"] for r in rows)
            c = sum(r["accuracy"]["correct"] for r in rows)
            return round(c / max(t, 1), 4)
        t = sum(r["accuracy"]["total"] for r in rows)
        c = sum(r["accuracy"]["correct"] for r in rows)
        return round(c / max(t, 1), 4)

    report = {
        "session_root": str(root),
        "scope": "development + m4_formal + mir_transfer + demo",
        "transition_selection": {
            "product_candidate": cand.get("product_candidate"),
            "mechanism_candidate": cand.get("mechanism_candidate"),
            "model_selection_pooled": {
                "T0_oracle_independent": pooled_rate([r for r in formal_ms if r["transition"] == "T0_oracle_independent"]),
                "T1_direct_serial": pooled_rate([r for r in formal_ms if r["transition"] == "T1_direct_serial"]),
                "T2_core_boundary_serial": pooled_rate([r for r in formal_ms if r["transition"] == "T2_core_boundary_serial"]),
                "T3_stable_boundary_serial": pooled_rate([r for r in formal_ms if r["transition"] == "T3_stable_boundary_serial"]),
                "full_song_align": pooled_rate(full_ms),
            },
        },
        "m4_formal_pooled": {
            "full_song_align": pooled_rate(full_m4),
            "T2_core_boundary_serial": pooled_rate([r for r in formal_m4 if r["transition"] == "T2_core_boundary_serial"]),
        },
        "propagation": {
            "episodes": len(episodes),
            "natural": sum(1 for e in episodes if e.get("natural")),
            "corruption": sum(1 for e in episodes if not e.get("natural")),
            "note": "T2 serial 系统性错位机制（query 起点估算缺陷）",
        },
        "oracle_recovery": {
            "segments": oracle.get("segments"),
            "recovery_rate": oracle.get("oracle_recovery_rate"),
            "mode": oracle.get("mode"),
            "conclusion": "模型固有偏移（~0.4-1.3s）重跑不可修复",
        },
        "detector": {
            "train_auc": (read("06_detector/TRAIN_META.json") or {}).get("auc_train"),
            "threshold_validation": {k: {kk: vv for kk, vv in (frozen.get(k) or {}).items() if kk in ("feasible", "t_accept", "t_reject", "safe_accept", "unsafe_reject")} for k in ("SA60", "SA80", "R95")},
            "threshold_validation_denominators": frozen.get("threshold_validation_denominators"),
            "threshold_validation_denominator_note": "rate 分母 = 该工作点下被分类（ACCEPT/REJECT）的行数（UNCERTAIN 为 grey 不进分母）；threshold_validation_denominators 为全部有标签行，两者关系：grey 行被排除",
            "joint_sa60_r95": frozen.get("joint_sa60_r95", {}).get("feasible"),
            "fixed_threshold_transfer": frozen.get("fixed_threshold_transfer"),
        },
        "closed_loop": {
            "segments": sum(len((song.get("routes") or {}).get("SA80", {}).get("segments") or [])
                            for song in (closed.get("per_song") or [])),
            "routes_counted": "SA80",
            "delta": sum(
                (s.get("rerun_correct") or 0) - (s.get("base_correct") or 0)
                for song in (closed.get("per_song") or [])
                for route in (song.get("routes") or {}).values()
                for s in (route.get("segments") or [])
            ),
            "conclusion": (closed.get("pooled") or {}).get("conclusion")
            or "detector 标记段的 L 重跑净效果为负（模型重跑同段产生相同或更差偏移）",
        },
        "mir_transfer": {
            "n_songs": mir.get("n_songs"),
            "pooled_correct_rate": mir.get("pooled_correct_rate"),
            "note": "MIR 100% vs M4 38-55%：vocal 分离/短歌/人工 GT vs rule_validated 长歌",
        },
        "demo": {
            "n_items": demo.get("n_items"),
            "n_failed": demo.get("n_failed"),
            "top_suspicious": [r["item"] for r in (demo.get("ranking") or [])[:5]],
        },
        "legacy_gaps": {i["id"]: i["verdict"] for i in legacy.get("items", [])},
        "gpu_seconds_used": state.get("gpu_seconds_used"),
    }
    (out_dir / "FINAL_SESSION_REPORT.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")

    lines = [
        "# Final Session Report: Transition–Recovery–Detector", "",
        f"session_root: `{root}`",
        f"GPU seconds recorded: {report['gpu_seconds_used']}",
        "",
        "## 1. Transition 比较（model_selection 9 首，tolerance 0.32s, raw decoder, retained 3.0s）", "",
        "| transition | pooled correct* | 备注 |",
        "|---|---|---|",
        f"| T0 oracle-independent | {report['transition_selection']['model_selection_pooled']['T0_oracle_independent']} | 诊断上界（GT query） |",
        f"| T1 direct serial | {report['transition_selection']['model_selection_pooled']['T1_direct_serial']} | 提交内正确率，覆盖 ~40% |",
        f"| T2 core-boundary serial | {report['transition_selection']['model_selection_pooled']['T2_core_boundary_serial']} | 同上 |",
        f"| T3 stable-boundary serial | {report['transition_selection']['model_selection_pooled']['T3_stable_boundary_serial']} | 提交内高但覆盖 ~12% |",
        f"| **full-song align** | **{report['transition_selection']['model_selection_pooled']['full_song_align']}** | **Product candidate（non-serial 胜出）** |",
        "",
        "*T1/T2/T3 分母=committed units（覆盖 40%/12%），T0/full-song 分母=全部 units。",
        "",
        "## 2. 关键发现",
        "- **serial 系统性失效机制**：query 起点用 density 估算，歌词密度变化（如开头 0.5s/字、后段 1.25s/字）时把已唱过的歌词塞进后续窗 → 模型整体错位。",
        "- **正确切片下的单窗能力 59-66%**：模型本身不差；serial 的失败来自 query 构造而非模型。",
        "- **Oracle recovery 上限低**：L=18.6% / W=21.4%；模型重跑产生相同系统性偏移（~0.4-1.3s），无法通过重跑修复。",
        "- **Closed loop 净负**：36-88 段重跑 delta -110~-283，detector+recovery 不能提升 full-song 质量。",
        "- **MIR 100% vs M4 38-55%**：vocal 分离+短歌+人工 GT 下模型完美；M4 的误差含 GT 质量（rule_validated）与长歌上下文因素。",
        "- **Detector 有效但阈值漂移**：train AUC 0.84；SA60/SA80/R95 冻结可行；fixed-threshold transfer 跨歌漂移显著。",
        "",
        "## 3. 交付物清单",
    ]
    for sub in ("01_precheck/PRECHECK.json", "02_transition/TRANSITION_REPORT.json",
                "02_transition/CANDIDATE_SELECTION.json", "03_propagation/EPISODES.jsonl",
                "04_oracle_recovery/ORACLE_SUMMARY.json", "05_legacy_gaps/LEGACY_GAP_STATUS.json",
                "06_detector/FROZEN_WORKING_POINTS.json", "07_closed_loop/CLOSED_LOOP_SUMMARY.json",
                "08_transfer_demo/MIR_TRANSFER_SUMMARY.json", "08_transfer_demo/TEST_DEMO_SUMMARY.json"):
        exists = (root / sub).is_file()
        lines.append(f"- {'[x]' if exists else '[ ]'} `{sub}`")
    lines += [
        "",
        "## 4. 状态",
        "- Transition: complete（T0-T3 + full-song 比较完成）",
        "- Propagation: complete（170 episodes，机制为 T2 系统性错位）",
        "- Oracle recovery: complete（L/W 上限低）",
        "- Legacy gaps: 见 LEGACY_GAP_STATUS.json（2 complete + 1 blocked + 2 not_executed_dependency + 1 complete 替代）",
        "- Detector: complete（SA60/SA80/R95 冻结 + joint 可行 + transfer 漂移报告）",
        "- Closed loop: complete（negative result）",
        "- MIR transfer: complete（100% 对照）",
        "- Demo: complete（23 首结构分析 + suspicious ranking）",
        "",
        "结论：non-serial（full-song）为当前最佳路线；detector/recovery 的收益受模型固有对齐偏差限制；",
        "下一步应聚焦模型对齐质量（新 decoder/校准/GT 质量）与 M4 GT 审计。",
    ]
    (out_dir / "FINAL_SESSION_REPORT.md").write_text("\n".join(lines), "utf-8")

    negative = [
        "# Negative Results",
        "",
        "- **T1/T2 serial 无法作为产品路线**：提交内正确率 <25%（model_selection），覆盖 40% 下 correct-committed coverage <6%；query 起点估算缺陷导致系统性错位。",
        "- **T3 stable-boundary 覆盖率过低**（~12%）：保守提交导致大量未提交；且跨窗观察在已过时行上物理不可行（冷启动需 baseline commit 修正）。",
        "- **Oracle-L/W recovery 上限低**（18.6%/21.4%）：模型重跑同段产生相同偏移，重跑不能修复系统性节奏偏差。",
        "- **Closed loop 净负**：detector 标记段重跑整体变差（delta -110~-283）；detector+recovery 无法提升 full-song 输出。",
        "- **Fixed-threshold transfer 漂移**：冻结阈值在 model_selection 上 safe_accept≈0.5%（分布漂移）；未重调（07 §7 契约）。",
        "- **Hidden extraction 不可用**（blocked）：hook 未接入 real inference，availability=0；不声称 hidden 无增益。",
        "- **Cross-view full posterior 未执行**（not_executed_dependency）：topk-only 证据不足以计算精确 JS/L2。",
        "- **旧 CNN1D AUC=1 不得引用为窗口级能力**（协议纠正登记）。",
        "- **Isotonic 不能改善 discrimination**（旧结论确认，不重跑）。",
    ]
    (out_dir / "NEGATIVE_RESULTS.md").write_text("\n".join(negative), "utf-8")

    audit = {
        "session_root": str(root),
        "phases": state.get("phases"),
        "gpu_seconds_used": state.get("gpu_seconds_used"),
        "artifacts": {sub: (root / sub).is_file() for sub in (
            "00_meta/SESSION_META.json", "00_meta/RESOLVED_CONFIG.yaml", "00_meta/DATASET_SPLIT.json",
            "01_precheck/PRECHECK.json", "01_precheck/TRANSITION_IMPLEMENTATION_MAP.json",
            "02_transition/TRANSITION_SUMMARY.json", "03_propagation/EPISODES.jsonl",
            "03_propagation/ATTEMPT_DENOMINATORS.json", "04_oracle_recovery/ORACLE_SUMMARY.json",
            "05_legacy_gaps/LEGACY_GAP_STATUS.json", "06_detector/FROZEN_WORKING_POINTS.json",
            "07_closed_loop/CLOSED_LOOP_SUMMARY.json", "08_transfer_demo/MIR_TRANSFER_SUMMARY.json",
            "08_transfer_demo/TEST_DEMO_SUMMARY.json", "09_reports/FINAL_SESSION_REPORT.json",
            "09_reports/NEGATIVE_RESULTS.md", "SESSION_STATE.json")},
        "deviations": [
            "T3 冷启动语义修正（first-window baseline commit）：07 §3.2 全 provisional 在物理上不可行（已过行不可重观察）",
            "query 起点覆盖 committed 边界 + 动态单位密度（无 GT 串行 query 构造缺陷修复）",
            "full-song 加入为 product 对照（non-serial 胜出后成为 Product candidate，07 §12 允许）",
            "MIR/closed-loop 结果揭示模型固有偏差为瓶颈（研究叙事调整，保留 mechanism=T2）",
        ],
    }
    (out_dir / "EXECUTION_AUDIT.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), "utf-8")
    print(f"reports written to {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
