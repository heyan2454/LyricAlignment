#!/usr/bin/env python3
"""D3: closed-loop route decision builder（shadow-only，纯 CPU，不加载 GT）。

重建 E3 frozen raw scorer（与 evaluate_e8 同一套 stage3b artifacts），读入
D2 route plan、E5 REQUESTS 与 candidate bank，对每个 (route x episode) 的
每个窗口：
- trigger_state 取该 (episode, variant) 候选的 ``score_units()["decision"]``；
- score_delta 仅 C3 有意义：候选与 ``original_full`` 在 unit 交集上
  ``mean(old_p_bad - new_p_bad)``；
- 调 ``closed_loop.route_decision`` 得 action/writeback，窗口标记：
  ``error`` 当 detector 判定出错（state != accept）且未被 C3 selective
  writeback 修复（C3 写回成功窗口视为已恢复标记 ``clean``；C2 盲写回
  不消除错误标记，error 仍按 detector 判定）；否则 ``clean``；
- 按 window_index 排序整段序列调 ``classify_serial_recovery``。

始终 shadow-only：``actual_writeback`` 恒为 0。
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from lyricalign.realign_recovery.candidate_scores import (  # noqa: E402
    build_frozen_scorer_from_artifacts,
    candidate_evidence_rows,
    load_bank,
    load_requests,
    score_units,
)
from lyricalign.realign_recovery.closed_loop import (  # noqa: E402
    classify_serial_recovery,
    route_decision,
)

_DEFAULT_RUN = "/home/hyan/Data/lyricalign/runs/realign_recovery_20260812_20260811T202813Z"
_ROUTES = ("C0", "C0S", "C1", "C2", "C3")
_FORWARD_MANIFEST = "closed_loop/forward/RUN_MANIFEST.json"
_ROUTE_PLAN = "closed_loop/routes/ROUTE_PLAN.json"
_WINDOW_RE = re.compile(r":w(\d+):")

# C3 的候选必须是 no-GT 修补变体（03 实验计划 §C3：no-GT audio/text proposal）。
# 优先级：safe-anchor bounded 主候选在前，缩窗/unsafe 变体次之。
_NO_GT_VARIANTS = (
    "R-B_safe_anchor_bounded",
    "R-C_subdiv_0.5",
    "R-C_subdiv_0.5_hi",
    "R-A_unsafe_old_range",
)


def _load_evaluate_e8_constants():
    e8_path = Path(__file__).resolve().parent / "evaluate_e8.py"
    spec = importlib.util.spec_from_file_location("_eval_e8_consts", e8_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod._STAGE3B, mod._ITEMS_DIRS


def _window_index_of(proposal_id) -> int:
    m = _WINDOW_RE.search(str(proposal_id))
    if m:
        return int(m.group(1))
    m2 = re.search(r"w(\d+)", str(proposal_id))
    return int(m2.group(1)) if m2 else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-root", default=_DEFAULT_RUN,
                    help=f"run root（默认 {_DEFAULT_RUN}）")
    ap.add_argument("--out-root", default=None,
                    help="输出目录（默认 <run-root>/closed_loop/decision）")
    args = ap.parse_args(argv)

    run = Path(args.run_root)
    out_root = Path(args.out_root) if args.out_root else run / "closed_loop" / "decision"
    out_root.mkdir(parents=True, exist_ok=True)

    plan_path = run / _ROUTE_PLAN
    if not plan_path.exists():
        print(f"[error] ROUTE_PLAN not found: {plan_path}; run "
              f"scripts/realign_recovery/build_closed_loop_routes.py first",
              file=sys.stderr)
        return 2
    plan = json.loads(plan_path.read_text(encoding="utf-8"))

    fwd_manifest = run / _FORWARD_MANIFEST
    needs_forward_routes = sorted({
        rid for entry in plan["per_episode"].values()
        for rid, spec in entry.items() if spec.get("needs_forward")
    })
    if not fwd_manifest.exists() and needs_forward_routes:
        print(f"[error] forward manifest missing: {fwd_manifest}; run the "
              f"forward pipeline for routes {needs_forward_routes} first "
              f"(need forwarded continuation evidence for closed-loop decisions)",
              file=sys.stderr)
        return 2
    if not fwd_manifest.exists():
        print(f"[warn] no forward manifest found; no route needs forward, "
              f"continuing with existing E5 evidence", file=sys.stderr)

    stage3b, items_dirs = _load_evaluate_e8_constants()
    scorer = build_frozen_scorer_from_artifacts(
        f"{stage3b}/FROZEN_OPERATING_POINTS.json",
        f"{stage3b}/LABELS.jsonl",
        f"{stage3b}/evidence_v2",
        items_dirs,
        target="raw",
    )
    print(f"scorer ready: target={scorer.target} t=({scorer.t_accept:.4f},"
          f"{scorer.t_reject:.4f}) n_feat={len(scorer.feat_keys)}")

    requests = load_requests(run / "e5_proposals" / "raw" / "REQUESTS.jsonl")
    bank = load_bank(run / "e5_proposals" / "candidate_bank" / "candidate_bank.jsonl")

    scored: dict[tuple[str, int, str], dict] = {}
    for cand in bank:
        if cand.get("ownership") != "e5_proposal":
            continue
        req_row, rows = candidate_evidence_rows(cand, requests)
        if req_row is None:
            continue
        prov = req_row.get("provenance") or {}
        ep = prov.get("episode_id")
        variant = req_row.get("input_variant")
        if not ep or not variant:
            continue
        wi = _window_index_of(cand.get("proposal_id"))
        scored[(str(ep), wi, variant)] = score_units(scorer, rows)
    print(f"scored (episode, window, variant) groups: {len(scored)}")

    per_ep_windows: dict[str, list[int]] = {}
    for (ep, wi, _v) in scored:
        per_ep_windows.setdefault(ep, []).append(wi)
    for ep in per_ep_windows:
        per_ep_windows[ep] = sorted(set(per_ep_windows[ep]))

    decisions: list[dict] = []
    per_route_summary: dict[str, dict] = {}
    for route in _ROUTES:
        serial_dist: dict[str, int] = {}
        n_windows = 0
        n_trigger = 0
        n_writeback = 0
        for ep in sorted(per_ep_windows):
            window_seq: list[str] = []
            ep_rows: list[dict] = []
            for wi in per_ep_windows[ep]:
                # C0/C0S/C1：detector 判定取自 original_full（不 realign）。
                # C2/C3：候选必须是 no-GT 修补变体（优先 R-B），detector 判定与
                # score_delta 均基于该候选。
                if route in ("C0", "C0S", "C1"):
                    variant = "original_full"
                else:
                    variant = next(
                        (v for v in _NO_GT_VARIANTS if (ep, wi, v) in scored),
                        "original_full",
                    )
                su = scored.get((ep, wi, variant))
                if su is None:
                    continue
                decision_state = su["decision"]
                score_delta = None
                if route == "C3":
                    old_units = scored.get((ep, wi, "original_full"), {}).get("units") or []
                    new_units = su.get("units") or []
                    old_p = {int(u["canonical_unit_id"]): u["p_bad"]
                             for u in old_units}
                    deltas = [old_p[int(nu["canonical_unit_id"])] - nu["p_bad"]
                              for nu in new_units
                              if int(nu["canonical_unit_id"]) in old_p]
                    if deltas:
                        score_delta = sum(deltas) / len(deltas)
                dec = route_decision(route, decision_state, score_delta)
                trigger = bool(dec.get("trigger", decision_state != "accept"))
                writeback = bool(dec.get("writeback", False))
                is_error = decision_state != "accept" and not (route == "C3" and writeback)
                window_seq.append("error" if is_error else "clean")
                n_windows += 1
                n_trigger += 1 if trigger else 0
                n_writeback += 1 if writeback else 0
                ep_rows.append({
                    "route": route,
                    "episode_id": ep,
                    "window_index": wi,
                    "trigger": trigger,
                    "action": dec["action"],
                    "writeback": writeback,
                    "score_delta": score_delta,
                    "actual_writeback": 0,
                    "needs_forward": bool(
                        plan["per_episode"].get(ep, {}).get(route, {}).get("needs_forward", False)),
                })
            serial = classify_serial_recovery(window_seq)
            serial_dist[serial] = serial_dist.get(serial, 0) + 1
            for r in ep_rows:
                r["serial_recovery"] = serial
                decisions.append(r)
        per_route_summary[route] = {
            "n_windows": n_windows,
            "n_trigger": n_trigger,
            "n_writeback": n_writeback,
            "serial_recovery": serial_dist,
        }

    decisions_path = out_root / "RUN_DECISIONS.jsonl"
    with open(decisions_path, "w", encoding="utf-8") as fh:
        for row in decisions:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    summary = {
        "schema_version": "realign_recovery_closed_loop_decision_v1",
        "run_root": str(run),
        "n_decisions": len(decisions),
        "per_route": per_route_summary,
    }
    summary_path = out_root / "DECISION_SUMMARY.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8")

    print(json.dumps({
        "ok": True,
        "n_decisions": len(decisions),
        "per_route": {
            k: {kk: vv for kk, vv in v.items() if kk != "serial_recovery"}
            for k, v in per_route_summary.items()
        },
        "outputs": {
            "decisions": str(decisions_path),
            "summary": str(summary_path),
        },
    }, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
