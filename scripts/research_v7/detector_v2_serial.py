#!/usr/bin/env python3
"""Detector V2 真实串行闭环仿真（18 §14）：SERIAL_CLOSED_LOOP.json。

输入：--run-root <run1>（evidence_v2/*.jsonl + LABELS.jsonl + FROZEN_OPERATING_POINTS.json +
items/<item_id>/<sha>.json）。选 n 首歌的连续窗序列（items 目录名 <song>:<wi>:<family>:<view>
提供 song/wi/family；sha 文件名 = 请求 content identity = evidence_v2 文件名），第 2 窗注入
end_early/cursor_shift 变体（无则克隆 baseline 窗并打 unsafe 标签）。

每窗：evidence+LABELS join → 特征（unit_feature_row + build_neighbors）→ 冻结模型打分 →
tristate_from_p_bad → 决策：accept 提交（cursor 推进）、reject 不提交、uncertain 用预算发
验证请求（同窗另一 target 再判），预算耗尽 unresolved。

对比 4 路线：all_commit / gt_oracle / single_view(official) / multi_view(official+raw 验证)。
输出每路线：错误正式提交率、首次错误提交窗、传播 windows/units、正确延迟提交、unresolved、
额外 request、耗时、困难区后重新入轨。核心仿真逻辑（simulate_route）无外部依赖，供测试复用。
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path


def _signal_indices(feat_keys: list[str], combo: str) -> list[int]:
    """信号列分组与 train_detector_v2.run_train / evaluate_detector_v2 一致（O 前缀组）。"""
    idx: list[int] = []
    for g in combo.split("+"):
        for i, k in enumerate(feat_keys):
            if (g == "R" and k.startswith("raw_")) \
                    or (g == "O" and k.startswith(("official_", "ro_", "repair_", "has_"))) \
                    or (g == "H" and k.startswith("hidden_")) \
                    or (g == "V" and k.startswith("cv_")):
                idx.append(i)
    return sorted(set(idx))


def tristate_states(p_bad, t_accept: float, t_reject: float) -> dict[int, str]:
    """冻结阈值三态；优先消费 DetectorOutput.state_intervals，无则阈值回退。

    值域与 contract.TriState 一致："accept"/"reject"/"uncertain"（高 p_bad=reject）。
    """
    from lyricalign.research_v7.detector_v2_intervals import tristate_from_p_bad

    out = tristate_from_p_bad({i: float(p) for i, p in enumerate(p_bad)}, t_accept, t_reject)
    states: dict[int, str] = {}
    for iv in getattr(out, "state_intervals", []) or []:
        val = getattr(getattr(iv, "state", None), "value", None) or str(iv.state)
        for i in range(int(iv.interval.start), int(iv.interval.end)):
            states[i] = val
    if not states:
        for i, p in enumerate(p_bad):
            states[i] = "reject" if p >= t_reject else ("accept" if p <= t_accept else "uncertain")
    return states


def window_decision(p_bad, t_accept: float, t_reject: float) -> tuple[str, dict[int, str]]:
    """窗级决策：任一 reject → reject；任一 uncertain → uncertain；否则 accept。"""
    states = tristate_states(p_bad, t_accept, t_reject)
    if any(v == "reject" for v in states.values()):
        return "reject", states
    if any(v == "uncertain" for v in states.values()):
        return "uncertain", states
    return "accept", states


def _atomic_write(path: Path, payload) -> None:
    import os
    import tempfile
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1, default=str)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def simulate_route(*, route: str, windows: list[dict], scorer, t_accept: float,
                   t_reject: float, budget_requests: int,
                   t_accept_alt: float, t_reject_alt: float) -> dict:
    """串行闭环单路线仿真。windows: 每窗 {"wi","rows":[feature dict+canonical_unit_id],
    "unsafe_flags":[bool]}；scorer(win, view)->list[p_bad]（按 rows 序）。
    windows 可带 "song" 键：歌曲变化时重置未提交集合（串行闭环按歌独立，避免伪传播）。"""
    commits: list[int] = []
    decisions: dict[int, str] = {}
    unresolved: list[int] = []
    delayed: list[int] = []
    extra_requests = 0
    error_commits = 0
    first_error_commit = None
    uncommitted_unsafe: set = set()
    propagated_windows: list[int] = []
    propagated_units: set = set()
    re_entries: list[int] = []
    scoring_calls = 0
    t0 = time.perf_counter()
    prev_committed = True
    prev_song = None

    for win in windows:
        wi = win["wi"]
        song = win.get("song")
        if song is not None and song != prev_song:
            uncommitted_unsafe = set()
            prev_committed = True
        prev_song = song
        unsafe_ids = {row.get("canonical_unit_id") for row, f in
                      zip(win["rows"], win["unsafe_flags"]) if f}
        if route == "all_commit":
            decision, verifies = "accept", 0
        elif route == "gt_oracle":
            decision, verifies = ("reject" if unsafe_ids else "accept"), 0
        else:
            p = scorer.score(win, "official")
            scoring_calls += 1
            decision, _ = window_decision(p, t_accept, t_reject)
            verifies = 0
            if decision == "uncertain" and route == "multi_view":
                budget_left = budget_requests
                while decision == "uncertain" and budget_left > 0:
                    budget_left -= 1
                    extra_requests += 1
                    verifies += 1
                    pv = scorer.score(win, "raw")
                    scoring_calls += 1
                    decision, _ = window_decision(pv, t_accept_alt, t_reject_alt)
                if decision == "uncertain":
                    decision = "unresolved"
            elif decision == "uncertain":
                decision = "unresolved"

        decisions[wi] = decision
        committed = decision == "accept"
        match = uncommitted_unsafe & unsafe_ids
        if match:
            propagated_windows.append(wi)
            propagated_units |= match
        if committed:
            commits.append(wi)
            if verifies:
                delayed.append(wi)
            if unsafe_ids:
                error_commits += 1
                if first_error_commit is None:
                    first_error_commit = wi
            uncommitted_unsafe -= unsafe_ids
            if not prev_committed:
                re_entries.append(wi)
        else:
            if decision == "unresolved":
                unresolved.append(wi)
            uncommitted_unsafe |= unsafe_ids
        prev_committed = committed

    wall_sec = time.perf_counter() - t0
    total = len(commits)
    return {
        "route": route,
        "error_commit_rate": (error_commits / total) if total else 0.0,
        "error_commits": error_commits,
        "total_commits": total,
        "first_error_commit_wi": first_error_commit,
        "propagated_windows": sorted(propagated_windows),
        "n_propagated_windows": len(propagated_windows),
        "propagated_units": sorted(propagated_units),
        "n_propagated_units": len(propagated_units),
        "delayed_commits": delayed,
        "n_delayed_commits": len(delayed),
        "unresolved_windows": sorted(unresolved),
        "n_unresolved": len(unresolved),
        "extra_requests": extra_requests,
        "scoring_calls": scoring_calls,
        "wall_sec": wall_sec,
        "re_entries": re_entries,
        "n_re_entries": len(re_entries),
        "decisions": {str(k): v for k, v in sorted(decisions.items())},
    }


class _FrozenScorer:
    """真实冻结打分器：train 拟合 standardized_logistic（seed=0）+ 冻结 combo 信号列。"""

    def __init__(self, by_target: dict, frozen_op: dict):
        import numpy as np
        from lyricalign.research_v7.detector_v2_models import _make_trainer

        self.np = np
        self.trainer: dict[str, callable] = {}
        self.feat_keys: dict[str, list] = {}
        self.idx: dict[str, list] = {}
        self.xtr: dict = {}
        self.ytr: dict = {}
        self.missing: dict[str, str] = {}
        for target in ("official", "raw"):
            tr = by_target.get(target, {}).get("train", [])
            op = frozen_op.get(target) or {}
            if not tr or not op.get("best_combo"):
                self.missing[target] = f"no_train({len(tr)})"
                continue
            fk = sorted({k for r in tr for k in r["features"]})
            idx = _signal_indices(fk, op["best_combo"])
            X = np.asarray([[float(r["features"].get(k) or 0.0) for k in fk]
                            for r in tr], dtype=float)
            y = np.asarray([1.0 if r["label"] == "unsafe" else 0.0 for r in tr])
            self.trainer[target] = _make_trainer("standardized_logistic", seed=0)
            self.xtr[target] = X[:, idx] if idx else np.zeros((len(X), 1))
            self.ytr[target] = y
            self.feat_keys[target] = fk
            self.idx[target] = idx

    def score(self, win: dict, target: str) -> list[float]:
        if target not in self.trainer:
            return [0.0] * len(win["rows"])
        fk, idx = self.feat_keys[target], self.idx[target]
        X = self.np.asarray([[float(r.get(k) or 0.0) for k in fk] for r in win["rows"]],
                            dtype=float)
        Xte = X[:, idx] if idx else self.np.zeros((len(X), 1))
        return [float(p) for p in self.trainer[target](self.xtr[target], self.ytr[target], Xte)]


def _load_labels(run_root: Path) -> tuple[dict, dict]:
    label_map: dict[tuple, str] = {}
    song_map: dict[str, str] = {}
    for line in (run_root / "LABELS.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        x = json.loads(line)
        key = (x["request_identity"], int(x["canonical_unit_id"]), x["target"])
        label_map[key] = x.get("label")
        song_map.setdefault(x["request_identity"], x.get("song_id"))
    return label_map, song_map


def _load_frozen_op(run_root: Path) -> dict:
    raw = json.loads((run_root / "FROZEN_OPERATING_POINTS.json").read_text(encoding="utf-8"))
    if isinstance(raw, dict) and {"raw", "official"} <= set(raw):
        return raw
    return {"raw": raw, "official": raw}


def _window_feature_rows(ev_dir: Path, rid: str, label_map: dict,
                         unsafe_override: bool = False) -> list[dict] | None:
    """evidence rows（canonical 序）→ 特征 dict 列表 + unsafe_flags。"""
    from lyricalign.research_v7.detector_v2_evidence import (
        EvidenceRow, HiddenView, OfficialView, RawView)
    from lyricalign.research_v7.detector_v2_features import build_neighbors, unit_feature_row

    path = ev_dir / f"{rid}.jsonl"
    if not path.exists():
        return None
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        x = json.loads(line)
        if isinstance(x, list):
            rows.extend(x)
    if not rows:
        return None
    rows_sorted = sorted(rows, key=lambda r: int(r["canonical_unit_id"]))
    evs = []
    for d in rows_sorted:
        h = d.get("hidden") or {}
        evs.append(EvidenceRow(
            request_identity=d["request_identity"], view_id=d.get("view_id"),
            canonical_unit_id=int(d["canonical_unit_id"]),
            raw=RawView(**(d.get("raw") or {})),
            official=OfficialView(**(d.get("official") or {})),
            hidden=HiddenView(available=bool(h.get("available")), schema=h.get("schema"),
                              start=h.get("start") or {}, end=h.get("end") or {}),
            cross_view=d.get("cross_view") or {}))
    out = []
    flags = []
    for i, ev in enumerate(evs):
        feats = unit_feature_row(ev, build_neighbors(evs, i), ev.cross_view)
        out.append({"canonical_unit_id": ev.canonical_unit_id, **feats})
        if unsafe_override:
            flags.append(True)
        else:
            flags.append(label_map.get((rid, ev.canonical_unit_id, "official")) == "unsafe")
    return [{"rows": out, "unsafe_flags": flags, "rid": rid}]


def _build_series(run_root: Path, *, n_songs: int, max_windows: int) -> list[dict]:
    """基于 items/ 目录（item_id=<song>:<wi>:<family>:<view>，内部 <sha>.json）构建连续窗序列。

    manifest 的 baseline_request_identity 是 builder 阶段的音频身份而非请求 content
    identity；sha 映射在 items/<item_id>/<content_identity>.json 文件名中。
    """
    label_map, song_map = _load_labels(run_root)
    ev_dir = run_root / "evidence_v2"
    items_root = run_root / "items"

    songs: dict[str, dict] = {}
    for item_dir in sorted(items_root.iterdir()):
        if not item_dir.is_dir():
            continue
        parts = item_dir.name.split(":")
        if len(parts) < 3:
            continue
        song, wi_s, family = parts[0], parts[1], parts[2]
        view = parts[3] if len(parts) > 3 else "full"
        if view != "full":
            continue
        shas = [p.stem for p in item_dir.glob("*.json")]
        if not shas:
            continue
        s = songs.setdefault(song, {"base": {}, "variants": {}})
        if family == "baseline_legal":
            s["base"].setdefault(wi_s, {"rid": shas[0]})
        else:
            s["variants"].setdefault(wi_s, {})[family] = {"rid": shas[0]}

    ranked = sorted(songs.items(), key=lambda kv: len(kv[1]["base"]), reverse=True)
    series_out: list[dict] = []
    for song, s in ranked[:n_songs]:
        base_wis = sorted(s["base"], key=int)
        if not base_wis:
            continue
        wis = base_wis[:max_windows]
        windows = []
        for idx, wi_s in enumerate(wis):
            rid = s["base"][wi_s]["rid"]
            variant = None
            if idx == 1:
                for mtype in ("end_early", "cursor_shift"):
                    if mtype in s["variants"].get(wi_s, {}):
                        variant = s["variants"][wi_s][mtype]
                        break
            clone_unsafe = False
            if variant is not None:
                rid = variant["rid"]
            elif idx == 1:
                clone_unsafe = True
            fr = _window_feature_rows(ev_dir, rid, label_map, unsafe_override=clone_unsafe)
            if fr is None and not clone_unsafe:
                fr = _window_feature_rows(ev_dir, s["base"][wi_s]["rid"], label_map,
                                          unsafe_override=True)
                clone_unsafe = True
            if fr is None:
                continue
            fr[0].update({"wi": int(wi_s), "song": song,
                          "mutation_type": "baseline" if not clone_unsafe
                          else (variant["mtype"] if variant is not None else "injected"),
                          "injected": variant is not None or clone_unsafe})
            windows.append(fr[0])
        if windows:
            series_out.append({"song": song, "windows": windows})
    return series_out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run-root", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--max-windows", type=int, default=4)
    p.add_argument("--budget-requests", type=int, default=2)
    p.add_argument("--n-songs", type=int, default=3)
    a = p.parse_args(argv)

    run_root = Path(a.run_root)
    frozen = _load_frozen_op(run_root)
    from train_detector_v2 import build_matrix

    by_target = build_matrix(run_root / "evidence_v2", run_root / "LABELS.jsonl")
    scorer = _FrozenScorer(by_target, frozen)
    series = _build_series(run_root, n_songs=a.n_songs, max_windows=a.max_windows)
    if not series:
        raise SystemExit("no usable song series")

    op_o = frozen["official"]["operating_points"]
    op_r = frozen["raw"]["operating_points"]
    routes = {}
    for route in ("all_commit", "gt_oracle", "single_view", "multi_view"):
        windows = [w for s in series for w in s["windows"]]
        routes[route] = simulate_route(
            route=route, windows=windows, scorer=scorer,
            t_accept=float(op_o["T_accept"]), t_reject=float(op_o["T_reject"]),
            t_accept_alt=float(op_r["T_accept"]), t_reject_alt=float(op_r["T_reject"]),
            budget_requests=a.budget_requests)

    payload = {"schema": "research_v7_serial_closed_loop_v1",
               "args": vars(a), "frozen_op": frozen,
               "songs": [{"song": s["song"], "n_windows": len(s["windows"]),
                          "windows": [{"wi": w["wi"], "mutation_type": w["mutation_type"],
                                       "injected": w["injected"], "n_units": len(w["rows"]),
                                       "n_unsafe": sum(w["unsafe_flags"])} for w in s["windows"]]}
                         for s in series],
               "routes": routes}
    out_path = Path(a.out) / "SERIAL_CLOSED_LOOP.json"
    _atomic_write(out_path, payload)
    brief = {r: {k: routes[r][k] for k in
                 ("error_commit_rate", "error_commits", "total_commits",
                  "first_error_commit_wi", "n_propagated_windows",
                  "n_propagated_units", "n_delayed_commits", "n_unresolved",
                  "extra_requests", "n_re_entries", "wall_sec")} for r in routes}
    print(json.dumps({"ok": True, "n_songs": len(series), "out": str(out_path),
                      "routes": brief}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
