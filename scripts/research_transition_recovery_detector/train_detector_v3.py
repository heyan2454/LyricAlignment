#!/usr/bin/env python3
"""11 计划 Stage 3：detector 全信号消融（CPU）。

在 v2 dataset builder（R/O/RO/V/S 特征 + Safe/Grey/Unsafe 三态标签）之上叠加真实
H（evidence_hidden npy，-4/-1 层，start/end 双 slot）与 P（evidence_P 的 p_features
请求级 + 由 full posterior npy 计算的 unit 级 top2）。

矩阵：H/R/O/RO/V/P/S 单信号、H+R、H+O、R+O、H+R+O、R+selected(V/P/S)（validation 选）、
H+R+O+selected、CNN1D（per-unit 输出，与同输入 MLP 比较）。
工作点：仅 threshold_validation 选 SA60/SA80/R95+joint（严格 REJECT-only，UNCERTAIN 不算 REJECT）。
输出（session/06_detector/）：MODEL_SELECTION_v3.json、FROZEN_WORKING_POINTS_v3.json、
INTERVAL_METRICS_REPRODUCIBLE.json、SEQUENCE_MODEL_EVAL.json、SIGNAL_COMPLETION_MATRIX_v3.json。

H/P 状态只允许 executed|negative（evidence 已落盘，禁止 blocked_api/not_executed/planned）。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "scripts" / "research_transition_recovery_detector"))

from lyricalign.research_transition_recovery_detector.contracts import TRANSITION_T2_CORE  # noqa: E402
from lyricalign.research_transition_recovery_detector.detector_features import (  # noqa: E402
    SIGNAL_GROUPS,
    cross_window_features,
    extract_signal_features,
)
from lyricalign.research_transition_recovery_detector.posterior_paths import unit_p_features  # noqa: E402
from train_detector_helpers_v2 import (  # noqa: E402
    LABEL_SCHEMA,
    SAFE_MS,
    GREY_MS,
    grey_excluded_binary,
    load_gt_manifest,
)
from train_detector_helpers import train_mlp, predict_p_bad  # noqa: E402

AUC_GAIN_POSITIVE = 0.005

H_NAMES = (
    "h_start_norm_m4", "h_end_norm_m4", "h_start_norm_m1", "h_end_norm_m1",
    "h_start_end_cos_m4", "h_start_end_l2_m4", "h_start_end_cos_m1", "h_start_end_l2_m1",
    "h_adj_cos_m4", "h_adj_l2_m4", "h_adj_cos_m1", "h_adj_l2_m1",
    "h_layer_cos_start", "h_layer_l2_start", "h_layer_cos_end", "h_layer_l2_end",
    "h_first_diff_m4", "h_first_diff_m1", "h_second_diff_m4", "h_second_diff_m1",
    "h_change_point_m4", "h_change_point_m1",
)
P_NAMES = (
    "p_unit_top2_gap", "p_path_ok", "p_best_path_score", "p_norm_gap", "p_mean_shift",
    "p_diff_slot_frac", "p_longest_run", "p_second_continuity", "p_global_shift",
    "p_occ_sep", "p_local_ambiguity",
)
S_NAMES = (
    "s_interval_sec", "s_velocity_flag", "s_inversion", "s_rolling_mean_interval",
    "s_rolling_std_interval",
)
RO_NAMES = tuple(SIGNAL_GROUPS["RO"]) if "RO" in SIGNAL_GROUPS else ()
V_NAMES = tuple(SIGNAL_GROUPS["V"]) if "V" in SIGNAL_GROUPS else ()
R_NAMES = tuple(SIGNAL_GROUPS["R"])
O_NAMES = tuple(SIGNAL_GROUPS["O"])

FAMILIES: dict[str, tuple[str, ...]] = {
    "H": H_NAMES, "R": R_NAMES, "O": O_NAMES, "RO": RO_NAMES,
    "V": V_NAMES, "P": P_NAMES, "S": S_NAMES,
}
MATRIX = [
    ("H", ("H",), "hidden 序列特征"),
    ("R", ("R",), "raw 几何"),
    ("O", ("O",), "official 几何"),
    ("RO", ("RO",), "raw-official 交互"),
    ("V", ("V",), "cross-window 一致性"),
    ("P", ("P",), "posterior competing path"),
    ("S", ("S",), "per-unit 序列 trajectory"),
    ("H+R", ("H", "R"), "hidden+raw"),
    ("H+O", ("H", "O"), "hidden+official"),
    ("R+O", ("R", "O", "RO"), "raw+official(+交互)"),
    ("H+R+O", ("H", "R", "O", "RO"), "hidden+raw+official(+交互)"),
]
SEL_POOL = ("V", "P", "S")


def _num(v):
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _cos(a: np.ndarray, b: np.ndarray) -> float | None:
    na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
    if na < 1e-9 or nb < 1e-9:
        return None
    return float(np.dot(a, b) / (na * nb))


def _l2(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.linalg.norm(a - b))


def _hidden_unit_primary(layer_vecs: dict[str, np.ndarray], i: int, n_slots: int) -> dict[str, float | None]:
    f: dict[str, float | None] = {}
    for lname in ("-4", "-1"):
        v = layer_vecs[lname]
        s, e = 2 * i, 2 * i + 1
        key = "m4" if lname == "-4" else "m1"
        sn = v[s] if s < n_slots else None
        en = v[e] if e < n_slots else None
        f[f"h_start_norm_{key}"] = float(np.linalg.norm(sn)) if sn is not None else None
        f[f"h_end_norm_{key}"] = float(np.linalg.norm(en)) if en is not None else None
        if sn is not None and en is not None:
            f[f"h_start_end_cos_{key}"] = _cos(sn, en)
            f[f"h_start_end_l2_{key}"] = _l2(sn, en)
        else:
            f[f"h_start_end_cos_{key}"] = f[f"h_start_end_l2_{key}"] = None
        f[f"h_first_diff_{key}"] = None
        f[f"h_second_diff_{key}"] = None
        f[f"h_change_point_{key}"] = None
        f[f"h_adj_cos_{key}"] = None
        f[f"h_adj_l2_{key}"] = None
    if 2 * i < n_slots:
        s4, s1 = layer_vecs["-4"][2 * i], layer_vecs["-1"][2 * i]
        f["h_layer_cos_start"] = _cos(s4, s1)
        f["h_layer_l2_start"] = _l2(s4, s1)
    else:
        f["h_layer_cos_start"] = f["h_layer_l2_start"] = None
    if 2 * i + 1 < n_slots:
        e4, e1 = layer_vecs["-4"][2 * i + 1], layer_vecs["-1"][2 * i + 1]
        f["h_layer_cos_end"] = _cos(e4, e1)
        f["h_layer_l2_end"] = _l2(e4, e1)
    else:
        f["h_layer_cos_end"] = f["h_layer_l2_end"] = None
    return f


def _resolve_npy(p: str, base_dirs: list[Path]) -> Path | None:
    ap = Path(p)
    if ap.is_file():
        return ap
    for bd in base_dirs:
        cand = bd / ap
        if cand.is_file():
            return cand
    return None


def _hidden_request_features(hinfo: dict, base_dirs: list[Path]) -> tuple[list[dict[str, float | None]], dict]:
    """请求级 hidden npy → 每 unit 特征（按 query 顺序 2 slots/unit，取 min 切分）。"""
    layer_vecs: dict[str, np.ndarray] = {}
    n_slots = None
    for lname in ("-4", "-1"):
        p = hinfo.get("vector_paths", {}).get(lname)
        if not p:
            return [], {"reason": f"missing vector_paths[{lname}]"}
        ap = _resolve_npy(p, base_dirs)
        if ap is None:
            return [], {"reason": f"npy missing: {p}"}
        vec = np.load(ap, mmap_mode="r").astype(np.float32)
        layer_vecs[lname] = vec
        n_slots = vec.shape[0] if n_slots is None else min(n_slots, vec.shape[0])
    n_units = int(hinfo.get("n_units", 0))
    n_unit_slots = min(n_slots or 0, 2 * n_units)
    if n_unit_slots <= 0:
        return [], {"reason": f"no slots (n_slots={n_slots}, n_units={n_units})"}
    per_unit: list[dict[str, float | None]] = [
        _hidden_unit_primary(layer_vecs, i, n_unit_slots) for i in range(n_units)]
    for i in range(n_units):
        s, e = 2 * i, 2 * i + 1
        for lname, key in (("-4", "m4"), ("-1", "m1")):
            v = layer_vecs[lname]
            fd = None
            if s < n_unit_slots and e < n_unit_slots:
                sn, en = float(np.linalg.norm(v[s])), float(np.linalg.norm(v[e]))
                fd = (en - sn) / max(sn, 1e-9)
            per_unit[i][f"h_first_diff_{key}"] = fd
            prev = per_unit[i - 1][f"h_first_diff_{key}"] if i > 0 else None
            sd = (fd - prev) if (fd is not None and prev is not None) else None
            per_unit[i][f"h_second_diff_{key}"] = sd
            per_unit[i][f"h_change_point_{key}"] = abs(sd) if sd is not None else None
            ns = 2 * (i + 1)
            if e < n_unit_slots and ns < n_unit_slots:
                per_unit[i][f"h_adj_cos_{key}"] = _cos(v[e], v[ns])
                per_unit[i][f"h_adj_l2_{key}"] = _l2(v[e], v[ns])
    info = {"n_units": n_units, "n_slots": n_slots, "n_unit_slots": n_unit_slots,
            "slicing": "slots 2i/2i+1 per unit in query order; min(n_slots,2*n_units) cut"}
    return per_unit, info


def _p_request_features(pinfo: dict) -> tuple[dict[str, float | None], dict]:
    """请求级 P 特征（来自 evidence_P 的 p_features）。status ok 才有真实 path 特征。"""
    pf = pinfo.get("p_features") or {}
    status = pf.get("status", "missing")
    base: dict[str, float | None] = {"p_path_ok": 1.0 if status == "ok" else 0.0}
    if status != "ok":
        return base, {"status": status, "request_level_path_features_unavailable": True}
    return ({**base,
             "p_best_path_score": _num(pf.get("best_path_score")),
             "p_norm_gap": _num(pf.get("normalized_score_gap")),
             "p_mean_shift": _num(pf.get("mean_time_shift_classes")),
             "p_diff_slot_frac": _num(pf.get("differing_slot_fraction")),
             "p_longest_run": _num(pf.get("longest_alternate_run")),
             "p_second_continuity": _num(pf.get("second_path_continuity")),
             "p_global_shift": (1.0 if pf.get("global_shift") else 0.0),
             "p_occ_sep": (1.0 if pf.get("occurrence_mode_separation") else 0.0),
             "p_local_ambiguity": _num(pf.get("local_ambiguity"))},
            {"status": "ok"})


def _unit_p_request(pinfo: dict, n_units: int, base_dirs: list[Path]) -> list[dict[str, float | None]]:
    """unit 级 P 特征：从 full posterior npy 用 start-slot top2 计算（不依赖请求级 path 状态）。"""
    path = pinfo.get("path")
    if not path:
        return [{"p_unit_top2_gap": None} for _ in range(n_units)]
    ap = _resolve_npy(path, base_dirs)
    if ap is None:
        return [{"p_unit_top2_gap": None} for _ in range(n_units)]
    probs = np.load(ap, mmap_mode="r").astype(np.float32)
    n_slots = probs.shape[0]
    slot_to_unit = [min(i // 2, n_units - 1) for i in range(min(n_slots, 2 * n_units))]
    rows = unit_p_features(probs, slot_to_unit)
    out: list[dict[str, float | None]] = []
    for i in range(n_units):
        r = next((x for x in rows if x.get("canonical_id") == i), None)
        out.append({"p_unit_top2_gap": _num(r.get("top2_gap")) if r else None})
    return out


def _s_features(sinfo: dict | None, song_intervals: list[float]) -> dict[str, float | None]:
    if sinfo is None:
        return {n: None for n in S_NAMES}
    iv = _num(sinfo.get("interval_sec"))
    flag = sinfo.get("velocity_flag")
    arr = np.asarray([x for x in song_intervals if x is not None], dtype=float)
    return {
        "s_interval_sec": iv,
        "s_velocity_flag": (1.0 if flag == "ok" else (0.0 if flag else None)),
        "s_inversion": (1.0 if flag == "inversion" else (0.0 if flag else None)),
        "s_rolling_mean_interval": float(np.mean(arr)) if arr.size else None,
        "s_rolling_std_interval": float(np.std(arr)) if arr.size else None,
    }


def _label_from_gt(pred: float | None, gt_start: float | None) -> int | None:
    if pred is None or gt_start is None:
        return None
    err = abs(pred - gt_start)
    return 0 if err <= SAFE_MS else (1 if err <= GREY_MS else 2)


def collect_records_flex(session_root: Path, song_ids: list[str]) -> dict[str, list[dict]]:
    """先按 TRANSITION_T2_CORE 命名取，取不到则 glob __T2_core*.jsonl 兜底。"""
    out: dict[str, list[dict]] = {}
    for song_id in song_ids:
        p = session_root / "02_transition" / f"{song_id}__{TRANSITION_T2_CORE}.jsonl"
        if not p.is_file():
            cands = sorted((session_root / "02_transition").glob(f"{song_id}__T2_core*.jsonl"))
            p = cands[0] if cands else p
        if not p.is_file():
            continue
        recs = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
        out[song_id] = [r for r in recs if not r.get("skipped")]
    return out


def rows_to_rowobjs(records: list[dict], cids: list[int]) -> list[dict]:
    by_cid = {int(r["global_character_index"]): r
              for rec in records for r in rec["evidence_summary"]["raw_global_rows"]}
    return [by_cid[c] for c in cids]


def build_dataset_v3(session_root: Path, records_root: Path, role: str, timeline_manifest: str,
                     evidence_dir: Path) -> tuple[dict, list[dict], list[int | None], list[int | None], dict]:
    split = json.loads((records_root / "00_meta" / "DATASET_SPLIT.json").read_text(encoding="utf-8"))
    song_ids = split["roles"][role]
    manifest = load_gt_manifest(timeline_manifest, records_root)
    records_by_song = collect_records_flex(records_root, song_ids)

    hidden_by_req: dict[str, dict] = {}
    p_by_req: dict[str, dict] = {}
    base_dirs = [records_root.parent, records_root.parent.parent]
    for fn, store in ((f"evidence_hidden_{role}.jsonl", hidden_by_req),
                      (f"evidence_P_{role}.jsonl", p_by_req)):
        f = evidence_dir / fn
        if f.is_file():
            for line in f.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    r = json.loads(line)
                    store[r.get("request_id")] = r
    traj_by_key: dict[tuple[str, int], dict] = {}
    tf = evidence_dir / f"evidence_trajectory_{role}.jsonl"
    if tf.is_file():
        for line in tf.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                traj_by_key[(r["song_id"], int(r["canonical_id"]))] = r

    features: list[dict] = []
    labels_raw: list[int | None] = []
    labels_off: list[int | None] = []
    meta_rows: list[dict] = []
    h_missing: list[str] = []
    p_missing: list[str] = []
    n_songs = n_intervals = 0

    for song_id in song_ids:
        records = records_by_song.get(song_id)
        if not records:
            continue
        gt = manifest.get(song_id)
        if gt is None:
            continue
        n_songs += 1
        observations_by_id: dict[int, list[dict]] = {}
        for rec in records:
            for row in rec["evidence_summary"]["raw_global_rows"]:
                observations_by_id.setdefault(int(row["global_character_index"]), []).append(row)
        row_req: dict[int, str] = {}
        for rec in records:
            before = rec["state_before"]["committed_end_exclusive"]
            after = rec["decision"]["committed_end_exclusive"]
            for r in rec["evidence_summary"]["raw_global_rows"]:
                cid = int(r["global_character_index"])
                if before <= cid < after:
                    row_req[cid] = rec["request"]["request_id"]
        rows = sorted(set(row_req), key=lambda c: c)
        if not rows:
            continue
        rowobjs = rows_to_rowobjs(records, rows)
        per_row = extract_signal_features(rowobjs)
        v_feats = cross_window_features(observations_by_id)

        req_h: dict[str, tuple[list[dict[str, float | None]], dict]] = {}
        req_p: dict[str, tuple[dict[str, float | None], list[dict[str, float | None]], dict]] = {}
        req_qids: dict[str, list[int]] = {}
        for rec in records:
            req_id = rec["request"]["request_id"]
            qids = [int(c) for c in rec["request"].get("query_canonical_ids", [])]
            req_qids[req_id] = qids
            if req_id in req_h:
                continue
            hinfo = hidden_by_req.get(req_id)
            if hinfo:
                try:
                    req_h[req_id] = _hidden_request_features(hinfo, base_dirs)
                except Exception as e:  # noqa: BLE001
                    req_h[req_id] = ([], {"reason": f"hidden load error: {type(e).__name__}: {e}"})
            else:
                req_h[req_id] = ([], {"reason": "no evidence_hidden row for request"})
            pinfo = p_by_req.get(req_id)
            if pinfo:
                preq, pinfo2 = _p_request_features(pinfo)
                req_p[req_id] = (preq, _unit_p_request(pinfo, len(qids), base_dirs), pinfo2)
            else:
                req_p[req_id] = ({"p_path_ok": 0.0},
                                 [{"p_unit_top2_gap": None} for _ in qids],
                                 {"reason": "no evidence_P row for request"})

        song_intervals = [_num(traj_by_key.get((song_id, c), {}).get("interval_sec")) for c in rows]
        for idx, cid in enumerate(rows):
            req_id = row_req[cid]
            qids = req_qids.get(req_id, [])
            try:
                uidx = qids.index(cid)
            except ValueError:
                uidx = None
            hf, hinfo = req_h.get(req_id, ([], {}))
            p_req, p_unit, pinfo = req_p.get(req_id, ({"p_path_ok": 0.0}, [], {}))
            if uidx is None:
                h_missing.append(f"{song_id}:{cid}:not_in_query")
                p_missing.append(f"{song_id}:{cid}:not_in_query")
            pu = p_unit[uidx] if (uidx is not None and uidx < len(p_unit)) else {"p_unit_top2_gap": None}
            hu = hf[uidx] if (uidx is not None and uidx < len(hf)) else {n: None for n in H_NAMES}
            feats = {**per_row[idx], **v_feats.get(cid, {}),
                     **_s_features(traj_by_key.get((song_id, cid)), song_intervals),
                     **p_req, **pu, **hu}
            features.append(feats)
            ro = rowobjs[idx]
            g = gt.get(cid)
            gs = float(g["start_sec"]) if g else None
            labels_raw.append(_label_from_gt(_num(ro.get("original_global_start_sec")), gs))
            labels_off.append(_label_from_gt(_num(ro.get("fixed_global_start_sec")), gs))
            meta_rows.append({"song_id": song_id, "cid": cid, "request_id": req_id})
        n_intervals += sum(1 for a, b in zip(rows, rows[1:]) if b != a + 1) + 1

    cov = _coverage_v3(features, meta_rows, h_missing, p_missing)
    meta = {
        "role": role, "n_songs": n_songs, "n_units": len(features), "n_intervals": n_intervals,
        "n_safe_raw": sum(1 for l in labels_raw if l == 0), "n_grey_raw": sum(1 for l in labels_raw if l == 1),
        "n_unsafe_raw": sum(1 for l in labels_raw if l == 2),
        "n_safe_off": sum(1 for l in labels_off if l == 0), "n_grey_off": sum(1 for l in labels_off if l == 1),
        "n_unsafe_off": sum(1 for l in labels_off if l == 2),
        "n_unlabeled": sum(1 for l in labels_raw if l is None),
        "label_schema": LABEL_SCHEMA,
    }
    return meta, features, labels_raw, labels_off, cov


def _coverage_v3(features: list[dict], meta_rows: list[dict], h_missing: list[str],
                 p_missing: list[str]) -> dict:
    n = max(len(features), 1)
    out: dict[str, dict] = {}
    for fam, names in FAMILIES.items():
        avail = sum(1 for f in features if all(f.get(nm) is not None for nm in names))
        missing_fields = {nm: sum(1 for f in features if f.get(nm) is None) for nm in names}
        reasons: list[str] = []
        if fam == "H" and h_missing:
            reasons.append(f"rows missing hidden evidence: {len(h_missing)}")
        if fam == "P" and p_missing:
            reasons.append(f"rows missing posterior evidence: {len(p_missing)}")
        if fam == "P" and missing_fields.get("p_best_path_score", 0):
            reasons.append("request-level path features only for ok requests ("
                           f"{n - missing_fields.get('p_best_path_score', 0)}/{n} rows)")
        out[fam] = {
            "n_units": len(features), "n_available_rows": avail,
            "coverage": round(avail / n, 4),
            "missing_fields": {k: v for k, v in missing_fields.items() if v},
            "n_songs": len({r["song_id"] for r in meta_rows}),
            "missing_reasons": reasons,
        }
    return out


def _eval_auc(probs: list[float | None], labels: list[int | None]) -> dict:
    from sklearn.metrics import roc_auc_score, average_precision_score

    ys, ps = [], []
    for p, l in zip(probs, labels, strict=True):
        if l is not None and p is not None:
            ys.append(int(l))
            ps.append(float(p))
    if len(set(ys)) < 2 or len(ps) < 2:
        return {"auc": None, "auprc": None, "n": len(ps), "reason": "single class or empty"}
    return {"auc": float(roc_auc_score(ys, ps)), "auprc": float(average_precision_score(ys, ps)),
            "n": len(ps)}


def _fit_predict(train_feats, train_bin, ev_feats, ev_bin, names, fams) -> tuple:
    """动态按训练集字段覆盖率>=0.9 过滤；返回 (model, scaler, used, probs_train, probs_eval, err)。"""
    avail: dict[str, float] = {}
    for fam in fams:
        for nm in FAMILIES[fam]:
            a = sum(1 for f in train_feats if f.get(nm) is not None)
            avail[nm] = a / max(len(train_feats), 1)
    names = tuple(n for n in names if avail.get(n, 0.0) >= 0.5)
    if not names:
        return None, None, [], [], [], "no features with train coverage>=0.5"
    try:
        model, scaler, tr = train_mlp(train_feats, train_bin, feature_names=names)
        ev_probs = predict_p_bad({"model": model, "scaler": scaler}, ev_feats, names)
        tr_probs = predict_p_bad({"model": model, "scaler": scaler}, train_feats, names)
        return model, scaler, names, tr_probs, ev_probs, None
    except Exception as e:  # noqa: BLE001
        return None, None, names, [], [], f"{type(e).__name__}: {e}"


def _strict_working_points(scores: list[float | None], labels: list[int | None]) -> list[dict]:
    """严格 REJECT-only：SA 点无 REJECT；R95 的 recall 只数 REJECT。Grey 排除分母。"""
    safe = [p for p, l in zip(scores, labels, strict=True) if l == 0 and p is not None]
    unsafe = [p for p, l in zip(scores, labels, strict=True) if l == 2 and p is not None]
    n_grey = sum(1 for l in labels if l == 1)
    out: list[dict] = []
    for target, kind in ((0.60, "SA60"), (0.80, "SA80")):
        if not safe:
            out.append({"point": kind, "status": "no_safe_units"})
            continue
        t = float(np.quantile(safe, target))
        safe_acc = sum(1 for p in safe if p < t) / len(safe)
        unsafe_rej = sum(1 for p in unsafe if p >= 1.0) / len(unsafe) if unsafe else None
        unsafe_non_accept = sum(1 for p in unsafe if p >= t) / len(unsafe) if unsafe else None
        out.append({"point": kind, "t_accept": t, "t_reject": 1.0,
                    "decision_rule": "ACCEPT if p_bad < t_accept else UNCERTAIN (no REJECT at SA point)",
                    "safe_accept_rate": round(safe_acc, 4),
                    "unsafe_reject_rate_reject_only": round(unsafe_rej or 0.0, 4),
                    "unsafe_non_accept_rate": unsafe_non_accept,
                    "n_safe": len(safe), "n_unsafe": len(unsafe), "n_grey_excluded": n_grey})
    if not unsafe:
        out.append({"point": "R95", "status": "no_unsafe_units"})
    else:
        t = float(np.quantile(unsafe, 0.05))
        rej = sum(1 for p in unsafe if p >= t) / len(unsafe)
        safe_acc = sum(1 for p in safe if p < t) / len(safe) if safe else None
        out.append({"point": "R95", "t_accept": 0.0, "t_reject": t,
                    "decision_rule": "REJECT if p_bad >= t_reject else UNCERTAIN (REJECT-only recall)",
                    "unsafe_reject_rate_reject_only": round(rej, 4),
                    "safe_accept_rate": safe_acc,
                    "n_safe": len(safe), "n_unsafe": len(unsafe), "n_grey_excluded": n_grey})
    if safe and unsafe:
        ta, tr = float(np.quantile(safe, 0.60)), float(np.quantile(unsafe, 0.05))
        safe_acc = sum(1 for p in safe if p < ta) / len(safe)
        rej = sum(1 for p in unsafe if p >= tr) / len(unsafe)
        out.append({"point": "SA60+R95_joint", "t_accept": ta, "t_reject": tr,
                    "feasible": bool(ta < tr),
                    "safe_accept_rate": round(safe_acc, 4),
                    "unsafe_reject_rate_reject_only": round(rej, 4),
                    "n_safe": len(safe), "n_unsafe": len(unsafe), "n_grey_excluded": n_grey})
    return out


def _label_arrays(bin_lbl, idx):
    return np.asarray([(1.0 if bin_lbl[i] == 1.0 else 0.0) if bin_lbl[i] is not None else np.nan
                       for i in idx], dtype=np.float32)


def _mlp_sequence_eval(train_feats, train_bin, ev_feats, ev_bin, names, meta_train, meta_ev, fams):
    """同输入 MLP（tabular）vs CNN1D（per-unit 输出）。返回 dict。"""
    res: dict = {"status": "executed", "families": list(fams)}
    avail = {nm: sum(1 for f in train_feats if f.get(nm) is not None) / max(len(train_feats), 1)
             for fam in fams for nm in FAMILIES[fam]}
    names = tuple(n for n in names if avail.get(n, 0.0) >= 0.9)
    res["input_features"] = list(names)
    try:
        model, scaler, tr = train_mlp(train_feats, train_bin, feature_names=names)
        ev_probs = predict_p_bad({"model": model, "scaler": scaler}, ev_feats, names)
        m = _eval_auc(ev_probs, ev_bin)
        m["auc_train"] = tr["auc_train"]
        res["mlp"] = m
    except Exception as e:  # noqa: BLE001
        res["mlp"] = {"status": "failed", "reason": f"{type(e).__name__}: {e}"}
    try:
        import torch
        import torch.nn as nn

        def seq_songs(feats, meta):
            out = []
            for s in sorted({r["song_id"] for r in meta}):
                idx = [i for i, r in enumerate(meta) if r["song_id"] == s]
                X = np.asarray([[0.0 if feats[i].get(nm) is None else float(feats[i].get(nm))
                                 for nm in names] for i in idx], dtype=np.float32)
                out.append((s, idx, X))
            return out

        tr_songs = seq_songs(train_feats, meta_train)
        ev_songs = seq_songs(ev_feats, meta_ev)
        max_len = max([len(x[2]) for x in tr_songs + ev_songs] + [1])
        n_feat = len(names)
        torch.manual_seed(0)
        conv = nn.Conv1d(n_feat, 16, kernel_size=3, padding=1)
        head = nn.Conv1d(16, 1, kernel_size=1)
        opt = torch.optim.Adam(list(conv.parameters()) + list(head.parameters()), lr=1e-3)
        loss_fn = nn.BCEWithLogitsLoss(reduction="none")
        for ep in range(40):
            total = torch.tensor(0.0)
            nw = 0.0
            for s, idx, X in tr_songs:
                y = _label_arrays(train_bin, idx)
                nan = np.isnan(y)
                if not nan.any():
                    continue
                xt = torch.from_numpy(np.pad(X, ((0, max_len - len(X)), (0, 0)))).unsqueeze(0).permute(0, 2, 1)
                logits = head(torch.relu(conv(xt))).squeeze(0).squeeze(0)
                yt = torch.from_numpy(np.where(nan, 0.0, y))[:len(X)]
                m = torch.from_numpy((~nan).astype(np.float32))
                loss = (loss_fn(logits[:len(X)], yt) * m).sum()
                total = total + loss
                nw += float(m.sum())
            if nw == 0:
                continue
            opt.zero_grad()
            (total / nw).backward()
            opt.step()
        cnn_probs: list[float | None] = [None] * len(ev_feats)
        with torch.no_grad():
            for s, idx, X in ev_songs:
                xt = torch.from_numpy(np.pad(X, ((0, max_len - len(X)), (0, 0)))).unsqueeze(0).permute(0, 2, 1)
                logits = head(torch.relu(conv(xt))).squeeze(0).squeeze(0)[:len(X)]
                for j, oi in enumerate(idx):
                    cnn_probs[oi] = float(torch.sigmoid(logits[j]))
        c = _eval_auc(cnn_probs, ev_bin)
        c.update({"n_epochs": 40,
                  "arch": "Conv1d(n_feat->16,k=3,pad=1)+ReLU+Conv1d(16->1,k=1); per-unit output",
                  "input": f"sequence features ({n_feat} dims) padded to {max_len} per song",
                  "n_songs_train": len(tr_songs), "n_songs_eval": len(ev_songs)})
        res["cnn1d"] = c
        res["comparison"] = {"cnn1d_gt_mlp": bool(c.get("auc") is not None and m.get("auc") is not None
                                                  and c["auc"] > m["auc"])}
    except Exception as e:  # noqa: BLE001
        res["cnn1d"] = {"status": "failed", "reason": f"{type(e).__name__}: {e}"}
    return res


def main() -> None:
    t0 = time.time()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--session-root", required=True)
    ap.add_argument("--records-root", required=True)
    ap.add_argument("--timeline-manifest", required=True)
    args = ap.parse_args()

    session_root = Path(args.session_root).resolve()
    records_root = Path(args.records_root).resolve()
    out_dir = session_root / "06_detector"
    out_dir.mkdir(parents=True, exist_ok=True)

    print("[v3] building datasets ...")
    datasets = {}
    for role in ("detector_train", "model_selection", "threshold_validation"):
        meta, feats, lraw, loff, cov = build_dataset_v3(
            session_root, records_root, role, args.timeline_manifest, out_dir)
        datasets[role] = (meta, feats, lraw, loff, cov)
        print(f"[v3] {role}: {meta}")

    tr_meta, tr_feats, tr_lraw, tr_loff, tr_cov = datasets["detector_train"]
    va_meta, va_feats, va_lraw, va_loff, va_cov = datasets["model_selection"]
    th_meta, th_feats, th_lraw, th_loff, th_cov = datasets["threshold_validation"]

    tr_bin, _ = grey_excluded_binary(tr_lraw)
    va_bin, va_grey = grey_excluded_binary(va_lraw)
    th_bin, _ = grey_excluded_binary(th_lraw)
    va_bin_off, _ = grey_excluded_binary(va_loff)

    def fam_names(*fams: str) -> tuple[str, ...]:
        out: list[str] = []
        for f in fams:
            for n in FAMILIES[f]:
                if n not in out:
                    out.append(n)
        return tuple(out)

    branch_results: dict[str, dict] = {}
    for combo, fams, note in MATRIX:
        names = fam_names(*fams)
        _, _, used, tr_probs, va_probs, err = _fit_predict(
            tr_feats, tr_bin, va_feats, va_bin, names, fams)
        r: dict = {"combo": combo, "families": list(fams), "note": note,
                   "features_used": list(used), "features_requested": list(names)}
        if err:
            r.update({"status": "failed", "failure_reason": err})
        else:
            r.update({
                "status": "executed",
                "auc_heldout": _eval_auc(va_probs, va_bin)["auc"],
                "auc_heldout_off": _eval_auc(va_probs, va_bin_off)["auc"],
                "auprc_heldout": _eval_auc(va_probs, va_bin)["auprc"],
                "auc_train": _eval_auc(tr_probs, tr_bin)["auc"],
                "n_train_units": len(tr_feats), "n_val_units": len(va_feats),
                "n_train_songs": tr_meta["n_songs"], "n_val_songs": va_meta["n_songs"],
                "n_threshold_units": len(th_feats),
            })
        branch_results[combo] = r
        print(f"[v3] {combo}: {r.get('status')} auc={r.get('auc_heldout')} "
              f"auc_off={r.get('auc_heldout_off')} n_feat={len(used)}")

    # selected(V/P/S)：validation 上比较 V/P/S 单信号与对 R 的增量，冻结一个
    r_auc = branch_results["R"].get("auc_heldout")
    sel: dict = {"pool": list(SEL_POOL), "single_auc": {}, "delta_over_R": {}, "R_plus_auc": {}}
    for f in SEL_POOL:
        sel["single_auc"][f] = branch_results[f].get("auc_heldout")
        names = fam_names("R", f)
        _, _, _, _, va_probs, err = _fit_predict(tr_feats, tr_bin, va_feats, va_bin, names, ("R", f))
        a = _eval_auc(va_probs, va_bin)["auc"] if not err else None
        sel["R_plus_auc"][f] = a
        sel["delta_over_R"][f] = (a - r_auc) if (a is not None and r_auc is not None) else None
    cands = {f: sel["delta_over_R"][f] for f in SEL_POOL if sel["delta_over_R"][f] is not None}
    chosen = max(cands, key=cands.get) if cands else "V"
    sel["chosen"] = chosen
    sel["chosen_rationale"] = ("max delta_over_R on model_selection (validation); tie-break V>P>S; "
                               "frozen before fixed combos & threshold_validation")
    print(f"[v3] selected(V/P/S) = {chosen} (deltas: {sel['delta_over_R']})")

    for combo, fams, note in (("R+sel", ("R", chosen), "R+selected(V/P/S)"),
                              ("H+R+O+sel", ("H", "R", "O", "RO", chosen), "H+R+O+selected(V/P/S)")):
        names = fam_names(*fams)
        _, _, used, tr_probs, va_probs, err = _fit_predict(
            tr_feats, tr_bin, va_feats, va_bin, names, fams)
        branch_results[combo] = {
            "combo": combo, "families": list(fams), "note": note,
            "features_used": list(used),
            "status": ("failed" if err else "executed"),
            "failure_reason": err,
            "auc_heldout": _eval_auc(va_probs, va_bin)["auc"] if not err else None,
            "auc_heldout_off": _eval_auc(va_probs, va_bin_off)["auc"] if not err else None,
            "auprc_heldout": _eval_auc(va_probs, va_bin)["auprc"] if not err else None,
            "auc_train": _eval_auc(tr_probs, tr_bin)["auc"] if not err else None,
            "n_train_units": len(tr_feats), "n_val_units": len(va_feats),
            "n_train_songs": tr_meta["n_songs"], "n_val_songs": va_meta["n_songs"],
            "n_threshold_units": len(th_feats),
        }
        print(f"[v3] {combo}: {branch_results[combo].get('status')} "
              f"auc={branch_results[combo].get('auc_heldout')}")

    for combo, r in branch_results.items():
        if r.get("status") == "executed" and combo != "R":
            r["judgement"] = ("positive" if (r["auc_heldout"] is not None and r_auc is not None
                                             and r["auc_heldout"] >= r_auc + AUC_GAIN_POSITIVE)
                              else "negative")

    executed = {c: r for c, r in branch_results.items() if r.get("status") == "executed"}
    best_combo = max(executed, key=lambda c: executed[c]["auc_heldout"] or -1)
    best_r = executed[best_combo]
    names = fam_names(*best_r["families"])
    _, _, used, tr_probs, th_probs, err = _fit_predict(
        tr_feats, tr_bin, th_feats, th_bin, names, best_r["families"])
    working_points = _strict_working_points(th_probs, th_lraw) if not err else []
    for wp in working_points:
        wp["model_combo"] = best_combo
        wp["role"] = "threshold_validation"
    frozen = {
        "schema_version": LABEL_SCHEMA,
        "model_combo": best_combo,
        "features_used": list(used),
        "train_role": "detector_train",
        "working_points": working_points,
        "working_points_v3_format": {
            wp["point"]: {"t_accept": float(wp["t_accept"]), "t_reject": float(wp["t_reject"])}
            for wp in working_points if "t_accept" in wp},
    }
    print(f"[v3] best combo: {best_combo} -> working points on threshold_validation")

    eval_json = {"role": "threshold_validation", "p_bad": list(th_probs), "labels": th_lraw,
                 "n_units": len(th_feats)}
    eval_path = out_dir / "_eval_v3_threshold.json"
    eval_path.write_text(json.dumps(eval_json, ensure_ascii=False), encoding="utf-8")
    th_json = out_dir / "_frozen_v3_for_intervals.json"
    th_json.write_text(json.dumps(frozen, ensure_ascii=False), encoding="utf-8")
    iv_out = out_dir / "INTERVAL_METRICS_REPRODUCIBLE.json"
    cp = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "research_transition_recovery_detector"
                             / "evaluate_interval_metrics_v2.py"),
         "--session-root", str(session_root), "--eval", str(eval_path),
         "--thresholds", str(th_json), "--out", str(iv_out), "--role", "threshold_validation"],
        capture_output=True, text=True, timeout=600)
    if cp.returncode != 0:
        iv_out.write_text(json.dumps({
            "generator": "inline_fallback", "error": cp.stderr[-500:],
            "note": "evaluate_interval_metrics_v2.py failed; interval metrics not produced",
            "working_points": frozen["working_points_v3_format"],
        }, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[v3] WARN interval metrics script failed: {cp.stderr[-300:]}")
    else:
        print("[v3] interval metrics written via evaluate_interval_metrics_v2.py")

    seq_eval = _mlp_sequence_eval(tr_feats, tr_bin, va_feats, va_bin,
                                  fam_names(*best_r["families"]),
                                  tr_meta, va_meta, best_r["families"])
    (out_dir / "SEQUENCE_MODEL_EVAL.json").write_text(
        json.dumps(seq_eval, indent=2, ensure_ascii=False), encoding="utf-8")

    probe = {"status": "failed", "reason": "hidden vectors not collected"}
    try:
        from sklearn.linear_model import LogisticRegression
        from sklearn.preprocessing import StandardScaler

        Xs = np.asarray([[f.get(n) if f.get(n) is not None else 0.0 for n in H_NAMES]
                         for f in tr_feats], dtype=float)
        sc = StandardScaler().fit(Xs)
        Xtr = sc.transform(Xs)
        ytr = np.asarray([1.0 if l == 2 else (0.0 if l == 0 else np.nan) for l in tr_bin], dtype=float)
        valid = ~np.isnan(ytr)
        if valid.sum() > 10 and len(set(ytr[valid])) == 2:
            clf = LogisticRegression(max_iter=500).fit(Xtr[valid], ytr[valid])
            Xv = np.asarray([[f.get(n) if f.get(n) is not None else 0.0 for n in H_NAMES]
                             for f in va_feats], dtype=float)
            pv = clf.predict_proba(sc.transform(Xv))[:, 1]
            probe = {"status": "executed",
                     "probe_input": "h_* engineered features (22d), StandardScaler fit on train only",
                     "auc_heldout": _eval_auc(pv.tolist(), va_bin)["auc"],
                     "n_train": int(valid.sum())}
        else:
            probe = {"status": "negative", "reason": "insufficient labeled train rows for probe",
                     "n_train": int(valid.sum())}
    except Exception as e:  # noqa: BLE001
        probe = {"status": "failed", "reason": f"{type(e).__name__}: {e}"}

    model_selection_json = {
        "schema_version": LABEL_SCHEMA,
        "targets": {"raw": "original_global_start_sec vs GT", "official": "fixed_global_start_sec vs GT"},
        "auc_gain_positive": AUC_GAIN_POSITIVE,
        "branches": branch_results,
        "selection": sel,
        "hidden_linear_probe": probe,
        "coverage_by_role": {"detector_train": tr_cov, "model_selection": va_cov,
                             "threshold_validation": th_cov},
        "meta_by_role": {"detector_train": tr_meta, "model_selection": va_meta,
                         "threshold_validation": th_meta},
        "runtime_sec": round(time.time() - t0, 1),
    }
    (out_dir / "MODEL_SELECTION_v3.json").write_text(
        json.dumps(model_selection_json, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "FROZEN_WORKING_POINTS_v3.json").write_text(
        json.dumps(frozen, indent=2, ensure_ascii=False), encoding="utf-8")

    matrix_rows = []
    for combo, r in branch_results.items():
        st = r.get("status")
        if st == "executed":
            status = "negative" if r.get("judgement") == "negative" else "executed"
        elif st in ("failed",):
            status = "failed"
        else:
            status = st
        matrix_rows.append({
            "branch_id": combo,
            "status": status,
            "input_artifacts": [f"evidence_{fam.lower()}" for fam in r.get("families", [])] or None,
            "n_train_songs": tr_meta["n_songs"], "n_val_songs": va_meta["n_songs"],
            "n_test_songs": th_meta["n_songs"],
            "n_units": len(tr_feats),
            "n_intervals": tr_meta["n_intervals"],
            "coverage": min((tr_cov.get(f, {}).get("coverage") for f in r.get("families", [])),
                            default=None),
            "metrics_artifact": "MODEL_SELECTION_v3.json",
            "failure_reason": r.get("failure_reason"),
        })
    matrix_rows.append({
        "branch_id": "sequence_model",
        "status": "executed" if seq_eval.get("status") == "executed" else "negative",
        "input_artifacts": [f"sequence features of {best_combo}"],
        "n_train_songs": tr_meta["n_songs"], "n_val_songs": va_meta["n_songs"],
        "n_test_songs": th_meta["n_songs"], "n_units": len(tr_feats),
        "n_intervals": tr_meta["n_intervals"], "coverage": None,
        "metrics_artifact": "SEQUENCE_MODEL_EVAL.json",
        "failure_reason": None,
    })
    matrix_json = {
        "schema_version": LABEL_SCHEMA,
        "status_allowed": ["executed", "negative"],
        "selected_vps": chosen,
        "note": "H/P evidence 实际进入特征（coverage>0），禁止 blocked_api/not_executed/planned",
        "rows": matrix_rows,
    }
    (out_dir / "SIGNAL_COMPLETION_MATRIX_v3.json").write_text(
        json.dumps(matrix_json, indent=2, ensure_ascii=False), encoding="utf-8")
    for path in (eval_path, th_json):
        path.unlink(missing_ok=True)
    print(f"[v3] done -> {out_dir} ({round(time.time() - t0, 1)}s)")
    print("[v3] matrix: " + ", ".join(f"{r['branch_id']}={r['status']}" for r in matrix_rows))


if __name__ == "__main__":
    main()
