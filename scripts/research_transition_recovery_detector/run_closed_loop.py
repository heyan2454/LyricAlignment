#!/usr/bin/env python3
"""P5：真正的 selected closed loop（09_CODEX_REVIEWED_IMPLEMENTATION_PLAN §3 P5）。

唯一数据流（执行阶段禁止读取 GT；GT 只进最终评估函数）：
    serial state + inference evidence
        -> detector 三态（冻结 FROZEN_WORKING_POINTS.json 阈值 + detector_mlp.pkl）
        -> build_route_plan(route_mode)          # 唯一决策点，不读分数
        -> RouteExecutor.execute(plan)           # 只验证/执行，不重新决策
        -> retry rows + explicit writeback
        -> next serial state/request

Gate C（09 §3 P5）：对每个已写回窗口，比较「写回后的 next request」与
「未写回（state_before 推导）的 next request」（request_id/parent_state_hash/
query_canonical_ids/model_bounds）；若 writeback 不改变后续 request/state，
该窗口 gate_c_ok=False，总结中 gate_c.passed=False。

L 与 W 行为不同（fixture 保证）：
- W：窗内存在 REJECT 即整窗 REJECT，commit_ids=()（零提交），retry 重跑整窗；
- L：提交连续 ACCEPT 前缀，第一个非 ACCEPT 起为 unresolved_gap（不越 gap 提交），
  retry 只覆盖 gap 区间 + 1 个左回看 id。

输出 <session-root>/07_closed_loop/CLOSED_LOOP_SUMMARY.json：
每窗 plan/route/commit/retry/cost + 最终评估（correct committed coverage、
unsafe commit、unresolved、恢复延迟、额外 forward/audio-sec/wall-time）+ gate_c。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

from lyricalign.research_transition_recovery_detector.contracts import (  # noqa: E402
    TRANSITION_T2_CORE,
    ROUTE_LOCAL,
    ROUTE_SHADOW,
    ROUTE_WHOLE,
    TransitionState,
    WindowRequest,
)
from lyricalign.research_transition_recovery_detector.identity import state_hash  # noqa: E402
from lyricalign.research_transition_recovery_detector.query_estimator import (  # noqa: E402
    QueryEstimator,
)
from lyricalign.research_transition_recovery_detector.route_executor import (  # noqa: E402
    RouteExecutor,
)
from lyricalign.research_transition_recovery_detector.runner import (  # noqa: E402
    TransitionRunner,
    build_query_ids,
)
from lyricalign.research_transition_recovery_detector.routes import build_route_plan  # noqa: E402
from lyricalign.research_transition_recovery_detector.thresholds import (  # noqa: E402
    tristate_labels,
)

DETECTOR_PKL_DEFAULT = (
    "/home/hyan/LyricAlignment/models/transition_recovery_detector_20260807/detector_mlp.pkl"
)
LOOKBACK_UNITS = 8
HEAD_STRATEGY = "H1"
SAMPLE_RATE = 16000
CORRECT_TOLERANCE_SEC = 0.25  # 09 §1 正式标签 250ms
UNSAFE_TOLERANCE_SEC = 1.0  # 09 §1 正式标签 1000ms（超出视为 unsafe commit）


class RecordingAlignerBackend:
    """包装 runner backend，兼容 RouteExecutor 的 state/gt_timeline kwargs。

    - executor 调 backend.forward(retry, audio=, document=, state=, gt_timeline=)；
      runner 的 Fake/Real backend 不接受这些 kwargs，由本包装吞掉。
    - 记录最近一次 forward 的 request/rows（executor 不返回 retry rows，P5 需要）。
    - 补 audit 成本字段：audio_seconds（model_bounds 跨度）、forward_seconds（墙钟）。
    - 记录 gt_timeline 是否泄漏进 backend（执行阶段必须恒为 None）。
    """

    def __init__(self, backend):
        self._backend = backend
        self.last_request: WindowRequest | None = None
        self.last_rows: list[dict] = []
        self.last_gt_seen = None
        self.forward_count = 0

    def forward(self, request, *, audio, document, state=None, gt_timeline=None, **kwargs):
        self.last_gt_seen = gt_timeline
        wall0 = time.monotonic()
        outcome = self._backend.forward(request, audio=audio, document=document, **kwargs)
        wall = time.monotonic() - wall0
        if isinstance(outcome, tuple) and len(outcome) == 2:
            rows, audit = outcome
        else:
            rows, audit = outcome, {}
        self.last_request = request
        self.last_rows = list(rows or [])
        audit = dict(audit or {})
        audit.setdefault("forward_seconds", float(wall))
        is_, _cs, _ce, ie = request.model_bounds
        audit.setdefault("audio_seconds", float(ie - is_))
        self.forward_count += 1
        return rows, audit


def _normalize_rows(rows: list[dict]) -> list[dict]:
    return TransitionRunner._normalize_rows(rows)


def _request_for(
    *,
    song_id: str,
    transition: str,
    state: TransitionState,
    win: dict,
    estimator: QueryEstimator,
    observations: dict[int, dict],
    window_index: int,
    lookback_units: int = LOOKBACK_UNITS,
    head_strategy: str = HEAD_STRATEGY,
) -> WindowRequest:
    """与 runner._request_for 等价（no-compress：model clock == original clock）。"""
    original_bounds = (
        float(win["input_start_sec"]),
        float(win["core_start_sec"]),
        float(win["core_end_sec"]),
        float(win["input_end_sec"]),
    )
    query_ids = build_query_ids(
        transition=transition,
        state=state,
        model_bounds=original_bounds,
        estimator=estimator,
        gt_timeline=None,  # 执行阶段禁止读取 GT（09 §3 P5）
        lookback_units=lookback_units,
        observations=observations,
        head_strategy=head_strategy,
    )
    if not query_ids:
        raise ValueError(f"no query ids for window {window_index} (T0 without GT?)")
    return WindowRequest(
        request_id=f"{song_id}__{transition}__w{window_index:03d}",
        parent_state_hash=state_hash(state),
        audio_identity=f"audio-{song_id}",
        original_bounds=original_bounds,
        model_bounds=original_bounds,
        query_canonical_ids=query_ids,
        slot_canonical_ids=(),
        decoder_evidence=("raw",),
        transition=transition,
        query_estimator_version=estimator.version,
        window_index=window_index,
    )


def _request_identity(request: WindowRequest) -> tuple:
    return (
        request.request_id,
        request.parent_state_hash,
        request.query_canonical_ids,
        request.model_bounds,
    )


def _unit_states_from_rows(
    *,
    rows: list[dict],
    p_bad_per_row: list[float],
    frozen_wp: dict,
    start_id: int,
) -> list[tuple[int, str]]:
    """rows -> 从 start_id 起的连续 (canonical_id, tristate)。缺失 id 保守标 UNCERTAIN。"""
    by_id: dict[int, str] = {}
    for row, p in zip(rows, p_bad_per_row, strict=True):
        cid = int(row["global_character_index"])
        by_id[cid] = tristate_labels(
            float(p), float(frozen_wp["t_accept"]), float(frozen_wp["t_reject"])
        )
    if not by_id:
        return []
    last = max(by_id)
    states: list[tuple[int, str]] = []
    for cid in range(start_id, last + 1):
        states.append((cid, by_id.get(cid, "UNCERTAIN")))
    return states


def run_closed_loop_song(
    *,
    song_id: str,
    audio,
    document,
    gt: dict[int, dict],
    window_plan: dict,
    estimator: QueryEstimator,
    backend,
    transition: str = TRANSITION_T2_CORE,
    frozen_wp: dict,
    route_mode: str = "L",
    detector_predict=None,
    lookback_units: int = LOOKBACK_UNITS,
    head_strategy: str = HEAD_STRATEGY,
    tolerance_sec: float = CORRECT_TOLERANCE_SEC,
    unsafe_tolerance_sec: float = UNSAFE_TOLERANCE_SEC,
) -> dict:
    """窗口串行闭环。detector_predict(rows) -> list[float]（每行一个 p_bad，与 rows 对齐）。

    detector_predict 是唯一 p_bad 注入点：p_bad 只在 build_route_plan 前消费，
    RouteExecutor 与 backend 均不可见（执行阶段不读分数）。
    """
    if detector_predict is None:
        raise ValueError("detector_predict must be provided (main 注入真实 detector，测试注入 p_bad 列表)")

    executor = RouteExecutor(transition_runner=None, backend=backend)
    state = TransitionState(
        song_id=song_id, transition=transition, window_index=0,
        next_input_cursor=0, committed_end_exclusive=0,
    )
    observations: dict[int, dict] = {}
    windows = list(window_plan["windows"])
    records: list[dict] = []
    totals = {"forward_seconds": 0.0, "audio_seconds": 0.0, "wall_seconds": 0.0,
              "extra_forward_count": 0, "extra_audio_seconds": 0.0,
              "extra_wall_seconds": 0.0}
    gate_c_failures: list[dict] = []
    first_gap_window: int | None = None
    last_gap_window: int | None = None
    committed_times: dict[int, float] = {}

    for win in windows:
        k = int(win["window_index"])
        state = state.derive(window_index=k)
        state_before = state
        request = _request_for(
            song_id=song_id, transition=transition, state=state, win=win,
            estimator=estimator, observations=observations, window_index=k,
            lookback_units=lookback_units, head_strategy=head_strategy,
        )
        wall0 = time.monotonic()
        rows, audit = backend.forward(request, audio=audio, document=document)
        rows = _normalize_rows(rows)
        serial_cost = {
            "forward_seconds": float(audit.get("forward_seconds", 0.0)),
            "audio_seconds": float(audit.get("audio_seconds", 0.0)),
        }
        wall = time.monotonic() - wall0
        p_bad = list(detector_predict(rows))
        if len(p_bad) != len(rows):
            raise ValueError(
                f"detector_predict must return one p_bad per row "
                f"(got {len(p_bad)} for {len(rows)} rows)"
            )
        unit_states = _unit_states_from_rows(
            rows=rows, p_bad_per_row=p_bad, frozen_wp=frozen_wp,
            start_id=state.committed_end_exclusive,
        )
        plan = build_route_plan(
            window_id=f"w{k:03d}",
            unit_states=unit_states,
            current_cursor=state.committed_end_exclusive,
            transition_state_hash=state_hash(state),
            retry_count=state.retry_count,
            route_mode=route_mode,
        )
        outcome = executor.execute(
            plan, request=request, audio=audio, document=document,
            state=state, gt_timeline=None,  # 执行阶段不读 GT
        )
        retry_rows: list[dict] = []
        retry_info = {"executed_forward_count": 0, "request_id": None, "n_rows": 0}
        if outcome["executed_forward_count"] > 0:
            retry_rows = _normalize_rows(list(backend.last_rows or []))
            retry_info = {
                "executed_forward_count": outcome["executed_forward_count"],
                "request_id": backend.last_request.request_id if backend.last_request else None,
                "n_rows": len(retry_rows),
                "query_ids": list(backend.last_request.query_canonical_ids) if backend.last_request else [],
                "slot_ids": list(backend.last_request.slot_canonical_ids) if backend.last_request else [],
            }
        new_state = outcome["new_state"]
        retry_cost = dict(outcome["cost"])
        if retry_rows:
            observations.update(
                {
                    int(r["global_character_index"]): {
                        "global_character_index": int(r["global_character_index"]),
                        "start_sec": float(r["start_sec"]),
                        "end_sec": float(r["end_sec"]),
                        "source": str(r.get("source", "raw")),
                    }
                    for r in retry_rows
                }
            )
        # 常规串行 forward 的行也进 observations（head/左上下文用），但不覆盖 retry 行。
        for r in rows:
            observations.setdefault(
                int(r["global_character_index"]),
                {
                    "global_character_index": int(r["global_character_index"]),
                    "start_sec": float(r["start_sec"]),
                    "end_sec": float(r["end_sec"]),
                    "source": str(r.get("source", "raw")),
                },
            )
        for cid in plan.commit_ids:
            if cid in observations:
                committed_times[cid] = float(observations[cid]["start_sec"])

        # ---- Gate C：writeback 必须改变后续 request/state ----
        gate_c_ok: bool | None = None
        next_unchanged = None
        last_window = k == len(windows) - 1
        state_hash_before = state_hash(state_before)
        # 写回后的实际续跑状态：shadow 不写回 → 仍是 state_before（executor 的 new_state 是
        # plan-applied 假状态）；L/W 写回 → new_state。
        resumed_state = new_state if outcome["actual_writeback"] else state_before
        state_hash_after = state_hash(resumed_state)
        if not last_window:
            next_win = windows[k + 1] if "window_index" in windows[k + 1] else win
            hypothetical = _request_for(
                song_id=song_id, transition=transition, state=state_before, win=next_win,
                estimator=estimator,
                observations={x: y for x, y in observations.items() if not any(
                    int(r["global_character_index"]) == x for r in retry_rows
                )},
                window_index=k + 1,
                lookback_units=lookback_units, head_strategy=head_strategy,
            )
            actual_next = _request_for(
                song_id=song_id, transition=transition, state=resumed_state, win=next_win,
                estimator=estimator, observations=observations, window_index=k + 1,
                lookback_units=lookback_units, head_strategy=head_strategy,
            )
            next_unchanged = _request_identity(hypothetical) == _request_identity(actual_next)
        state_unchanged = state_hash_before == state_hash_after
        gate_c_ok = not (state_unchanged or bool(next_unchanged))
        if not gate_c_ok:
            gate_c_failures.append({
                "window_index": k,
                "state_unchanged": state_unchanged,
                "next_request_unchanged": next_unchanged,
            })

        if new_state.unresolved_gap is not None:
            if first_gap_window is None:
                first_gap_window = k
            last_gap_window = k

        if outcome["actual_writeback"]:
            state = new_state
        else:
            state = state_before

        window_cost = {
            "forward_seconds": serial_cost["forward_seconds"] + retry_cost["forward_seconds"],
            "audio_seconds": serial_cost["audio_seconds"] + retry_cost["audio_seconds"],
            "wall_seconds": wall + float(retry_cost.get("forward_seconds", 0.0)),
        }
        totals["forward_seconds"] += window_cost["forward_seconds"]
        totals["audio_seconds"] += window_cost["audio_seconds"]
        totals["wall_seconds"] += window_cost["wall_seconds"]
        totals["extra_forward_count"] += retry_info["executed_forward_count"]
        totals["extra_audio_seconds"] += retry_cost["audio_seconds"]
        totals["extra_wall_seconds"] += retry_cost["forward_seconds"]

        records.append({
            "window_index": k,
            "request_id": request.request_id,
            "model_bounds": list(request.model_bounds),
            "query_ids": list(request.query_canonical_ids),
            "n_query_units": len(request.query_canonical_ids),
            "plan": {
                "route": plan.route,
                "commit_ids": list(plan.commit_ids),
                "provisional_ids": list(plan.provisional_ids),
                "unresolved_gap": list(plan.unresolved_gap) if plan.unresolved_gap else None,
                "retry_count": plan.retry_request.retry_count if plan.retry_request else None,
                "reason_codes": list(plan.reason_codes),
                "next_input_cursor": plan.next_input_cursor,
            },
            "retry": retry_info,
            "writeback": {
                "actual_writeback": outcome["actual_writeback"],
                "state_hash_before": state_hash_before,
                "state_hash_after": state_hash_after,
                "gate_c_ok": gate_c_ok,
                "next_request_unchanged": next_unchanged,
            },
            "committed_this_window": list(plan.commit_ids),
            "cost": window_cost,
            "window_state": {
                "committed_end_exclusive": state.committed_end_exclusive,
                "unresolved_gap": state.unresolved_gap,
            },
        })

    # ---- 最终评估（GT 只在这里进入） ----
    eval_ = evaluate_song_gt(
        song_id=song_id,
        n_units=len(gt),
        committed_ids=state.committed_ids,
        committed_times=committed_times,
        gt=gt,
        tolerance_sec=tolerance_sec,
        unsafe_tolerance_sec=unsafe_tolerance_sec,
    )
    recovery_delay_windows = None
    if first_gap_window is not None:
        recovery_delay_windows = (last_gap_window - first_gap_window + 1) if last_gap_window is not None else 1

    return {
        "song_id": song_id,
        "transition": transition,
        "route_mode": route_mode,
        "n_windows": len(records),
        "n_units_total": len(gt),
        "windows": records,
        "totals": totals,
        "evaluation": eval_,
        "recovery_delay_windows": recovery_delay_windows,
        "gate_c": {
            "passed": not gate_c_failures,
            "failures": gate_c_failures,
        },
    }


def evaluate_song_gt(
    *,
    song_id: str,
    n_units: int,
    committed_ids: tuple[int, ...],
    committed_times: dict[int, float],
    gt: dict[int, dict],
    tolerance_sec: float,
    unsafe_tolerance_sec: float,
) -> dict:
    """GT 只允许在这里进入闭环评估（09 §3 P5：执行阶段禁止读取 GT）。"""
    correct = 0
    unsafe = 0
    missing_gt = 0
    for cid in committed_ids:
        g = gt.get(cid)
        if g is None:
            missing_gt += 1
            continue
        diff = abs(committed_times.get(cid, float("inf")) - float(g["start_sec"]))
        if diff <= tolerance_sec:
            correct += 1
        if diff > unsafe_tolerance_sec:
            unsafe += 1
    n_committed = len(committed_ids)
    return {
        "committed": n_committed,
        "correct_committed": correct,
        "unsafe_commit": unsafe,
        "missing_gt": missing_gt,
        "committed_coverage": n_committed / max(n_units, 1),
        "correct_committed_rate": correct / max(n_committed, 1),
        "correct_committed_coverage": correct / max(n_units, 1),
        "unresolved_units": max(0, n_units - n_committed),
        "unresolved_rate": max(0, n_units - n_committed) / max(n_units, 1),
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--session-root", required=True)
    p.add_argument("--timeline-manifest", required=True)
    p.add_argument("--role", default="model_selection")
    p.add_argument("--transition", default=TRANSITION_T2_CORE)
    p.add_argument("--detector-pkl", default=DETECTOR_PKL_DEFAULT)
    p.add_argument("--working-point", default="SA60")
    p.add_argument("--route-mode", default="L", choices=["L", "W", "shadow"])
    p.add_argument("--song-ids", default="")
    p.add_argument("--device", default="cuda:0")
    args = p.parse_args()

    import pickle

    import numpy as np
    import soundfile as sf
    from scripts.demo.align_qwen_fa_serial_demo import (  # noqa: E402
        build_vocal_activity_profile,
        load_model,
    )
    from scripts.research_transition_recovery_detector.train_detector_helpers import (  # noqa: E402
        predict_p_bad,
    )
    from lyricalign.demo.karaoke import parse_lyrics_text  # noqa: E402
    from lyricalign.demo.window_planning import build_silence_aware_window_plan  # noqa: E402
    from lyricalign.research_transition_recovery_detector.detector_features import (  # noqa: E402
        FEATURE_NAMES,
        extract_unit_features,
    )
    from lyricalign.research_transition_recovery_detector.runner import RealAlignerBackend  # noqa: E402

    session_root = Path(args.session_root)
    split = json.loads((session_root / "00_meta" / "DATASET_SPLIT.json").read_text(encoding="utf-8"))
    song_ids = split["roles"][args.role]
    if args.song_ids:
        song_ids = [s for s in song_ids if s in {x.strip() for x in args.song_ids.split(",")}]
    by_song = {
        json.loads(line)["song_id"]: json.loads(line)
        for line in Path(args.timeline_manifest).read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    frozen = json.loads((session_root / "06_detector" / "FROZEN_WORKING_POINTS.json").read_text(encoding="utf-8"))
    if args.working_point not in frozen:
        raise ValueError(f"working point {args.working_point!r} not in FROZEN_WORKING_POINTS.json")
    wp = frozen[args.working_point]
    if not wp.get("feasible") or "t_accept" not in wp or "t_reject" not in wp:
        raise ValueError(f"working point {args.working_point!r} not frozen/feasible")
    with open(args.detector_pkl, "rb") as f:
        artifact = pickle.load(f)

    model_args = argparse.Namespace(
        model="Qwen/Qwen3-ForcedAligner-0.6B-hf",
        revision="c07281df297b9905d24a508279258cccf987a064",
        cache_dir="/home/hyan/Data/lyricalign/models/hf_cache",
        local_files_only=True,
        device=args.device,
    )
    processor, model = load_model(model_args, "raw", None)
    infer_args = argparse.Namespace(
        timestamp_segment_sec=0.08, decoder_kind="raw", decoder_top_k=8, decoder_beam_size=96,
        research_infer_cache_root=str(session_root / "cache" / "closed_loop"),
        research_model_identity={"kind": "raw"}, device=args.device,
    )

    detector_feature_names = tuple(artifact.get("feature_names") or FEATURE_NAMES)

    def detector_predict(rows):
        feats = [extract_unit_features(r) for r in rows]
        return predict_p_bad(artifact, feats, detector_feature_names)

    per_song = []
    for song_id in song_ids:
        row = by_song[song_id]
        audio, sr = sf.read(row["concat_audio_path"], dtype="float32")
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        duration = float(len(audio) / SAMPLE_RATE)
        document = parse_lyrics_text("".join(u["text"] for u in row["canonical_units"]), language="Chinese")
        gt = {int(u["canonical_unit_id"]): u for u in row["canonical_units"]}
        window_plan = build_silence_aware_window_plan(
            duration, build_vocal_activity_profile(audio, sample_rate=SAMPLE_RATE),
            target_core_sec=60.0, left_context_sec=10.0, right_context_sec=10.0,
        )
        estimator = QueryEstimator(
            n_units=len(document.characters), effective_audio_sec=duration,
        )
        backend = RecordingAlignerBackend(
            RealAlignerBackend(processor=processor, model=model, args=infer_args, sample_rate=SAMPLE_RATE)
        )
        summary = run_closed_loop_song(
            song_id=song_id, audio=audio, document=document, gt=gt,
            window_plan=window_plan, estimator=estimator, backend=backend,
            transition=args.transition, frozen_wp=wp, route_mode=args.route_mode,
            detector_predict=detector_predict,
        )
        if backend.last_gt_seen is not None:
            raise RuntimeError(f"GT leaked into backend execution for {song_id}")
        per_song.append(summary)
        print(json.dumps({
            "song_id": song_id,
            "windows": summary["n_windows"],
            "committed_coverage": round(summary["evaluation"]["committed_coverage"], 4),
            "correct_coverage": round(summary["evaluation"]["correct_committed_coverage"], 4),
            "unsafe_commit": summary["evaluation"]["unsafe_commit"],
            "extra_forward": summary["totals"]["extra_forward_count"],
            "gate_c_passed": summary["gate_c"]["passed"],
        }))

    out_dir = session_root / "07_closed_loop"
    out_dir.mkdir(parents=True, exist_ok=True)
    all_gate_c = [s["gate_c"]["passed"] for s in per_song]
    summary = {
        "schema_version": "closed_loop_v2_selected",
        "correction_plan_version": "20260808_correction_v1",
        "clock": "original",
        "scope": "no_gt_execution",
        "transition": args.transition,
        "route_mode": args.route_mode,
        "working_point": args.working_point,
        "detector_pkl": args.detector_pkl,
        "per_song": per_song,
        "gate_c": {
            "passed": bool(per_song) and all(all_gate_c),
            "n_songs": len(per_song),
            "n_songs_passed": sum(1 for ok in all_gate_c if ok),
            "n_songs_failed": sum(1 for ok in all_gate_c if not ok),
        },
    }
    (out_dir / "CLOSED_LOOP_SUMMARY.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), "utf-8"
    )
    print(json.dumps({"gate_c": summary["gate_c"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
