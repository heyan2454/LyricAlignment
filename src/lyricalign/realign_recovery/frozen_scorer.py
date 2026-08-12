"""E3 frozen detector shadow (no-GT) bridging for realign-recovery C5.

CPU-only generator: from real forward evidence rows it produces a per-window
shadow dict (``unsafe_intervals`` + decision) using the frozen Detector V2
operating point. Feature path is exactly the minimal research_v7 chain:

    unit_feature_row -> predict -> tristate_from_p_bad

No GT/label fields are consumed at scoring time (the label field is only
allowed on the *train* rows used to re-fit the frozen model, and is stripped
before feature extraction so the leak guard never sees it).

Thresholds: read ``frozen_op[target].operating_points.{T_accept,T_reject}``.
A missing file raises ``FileNotFoundError``; a missing target or missing
thresholds raises ``ValueError`` (fail-fast, never a silent fallback to the
baseline identity thresholds, which are far too narrow to be a sane default).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from lyricalign.research_v7.detector_v2_evidence import (
    EvidenceRow,
    HiddenView,
    OfficialView,
    RawView,
)
from lyricalign.research_v7.detector_v2_features import build_neighbors, unit_feature_row
from lyricalign.research_v7.detector_v2_intervals import tristate_from_p_bad
from lyricalign.research_v7.detector_v2_models import (
    MODEL_KINDS,
    _make_trainer,
    standardized_logistic,
)

_RAW_FIELDS = ("start_sec", "end_sec", "start_entropy", "end_entropy",
               "start_margin", "end_margin", "topk")
_OFFICIAL_FIELDS = ("start_sec", "end_sec",
                    "repair_start_shift_sec", "repair_end_shift_sec")


def _signal_indices(feat_keys: list[str], combo: str) -> list[int]:
    """信号列分组（与 train_detector_v2.run_train / detector_v2_serial 一致）。"""
    idx: list[int] = []
    for g in combo.split("+"):
        for i, k in enumerate(feat_keys):
            if (g == "R" and k.startswith("raw_")) \
                    or (g == "O" and k.startswith(("official_", "ro_", "repair_", "has_"))) \
                    or (g == "H" and k.startswith("hidden_")) \
                    or (g == "V" and k.startswith("cv_")):
                idx.append(i)
    return sorted(set(idx))


def _evidence_rows(rows):
    """evidence dict 列表 → (EvidenceRow 序列, 原始 label 列表)。

    label 只从 dict 里读出供训练使用，绝不进入 EvidenceRow（避免 feature 泄漏断言）。
    """
    ordered = sorted(rows, key=lambda r: int(r.get("canonical_unit_id", 0)))
    evs: list[EvidenceRow] = []
    labels: list = []
    for d in ordered:
        raw = d.get("raw") or {}
        official = d.get("official") or {}
        hidden = d.get("hidden") or {}
        evs.append(EvidenceRow(
            request_identity=str(d.get("request_identity") or "frozen_shadow"),
            view_id=str(d.get("view_id") or ""),
            canonical_unit_id=int(d.get("canonical_unit_id", 0)),
            raw=RawView(**{k: raw.get(k) for k in _RAW_FIELDS}),
            official=OfficialView(**{k: official.get(k) for k in _OFFICIAL_FIELDS}),
            hidden=HiddenView(available=bool(hidden.get("available")),
                              schema=hidden.get("schema"),
                              start=hidden.get("start") or {},
                              end=hidden.get("end") or {}),
            cross_view=d.get("cross_view") or {}))
        labels.append(d.get("label"))
    return evs, labels


def _feature_matrix(evs: list[EvidenceRow], feat_keys: list[str]) -> np.ndarray:
    feat_rows = [unit_feature_row(ev, build_neighbors(evs, i), ev.cross_view)
                 for i, ev in enumerate(evs)]
    return np.asarray(
        [[float(r.get(k) or 0.0) for k in feat_keys] for r in feat_rows],
        dtype=float)


def _unit_start_sec(ev: EvidenceRow) -> float:
    if ev.raw.start_sec is not None:
        return float(ev.raw.start_sec)
    return float(ev.canonical_unit_id)


def _unit_end_sec(ev: EvidenceRow) -> float:
    if ev.raw.end_sec is not None:
        return float(ev.raw.end_sec)
    return float(ev.canonical_unit_id) + 1.0


def build_frozen_scorer(frozen_op_path, train_evidence_rows, *,
                        model_kind: str = "standardized_logistic", seed: int = 0,
                        target: str = "official") -> "FrozenScorer":
    """frozen_op + 同 target 的 train evidence → 冻结打分器（predict_fn 在内部拟合）。

    train_evidence_rows：evidence 行 dict（可带 ``label``，仅用于拟合冻结模型；
    评分窗口的 evidence 行不允许带 label）。frozen_op 缺失 → FileNotFoundError。
    """
    path = Path(frozen_op_path)
    if not path.is_file():
        raise FileNotFoundError(f"frozen operating points file not found: {path}")
    frozen_op = json.loads(path.read_text(encoding="utf-8"))
    op = frozen_op.get(target) if isinstance(frozen_op, dict) else None
    if not isinstance(op, dict):
        raise ValueError(
            f"frozen operating points missing target {target!r}: {path}")

    combo = op.get("best_combo")
    if op.get("model_kind"):
        model_kind = op["model_kind"]
    if model_kind not in MODEL_KINDS:
        raise ValueError(f"model_kind {model_kind!r} not in {MODEL_KINDS}")

    op_points = op.get("operating_points") or {}
    t_accept = op_points.get("T_accept")
    t_reject = op_points.get("T_reject")
    if t_accept is None or t_reject is None:
        raise ValueError(
            f"frozen operating points missing T_accept/T_reject for "
            f"target {target!r} in {path}; refusing silent fallback to "
            f"baseline identity thresholds")
    t_accept = float(t_accept)
    t_reject = float(t_reject)
    if not 0.0 <= t_accept < t_reject <= 1.0:
        raise ValueError(
            f"require 0 <= T_accept < T_reject <= 1, got ({t_accept}, {t_reject})")

    if not train_evidence_rows:
        raise ValueError("train_evidence_rows must not be empty")
    evs, labels = _evidence_rows(train_evidence_rows)
    feat_keys = sorted({
        k
        for i, r in enumerate(evs)
        for k in unit_feature_row(r, build_neighbors(evs, i), r.cross_view)
    })
    if not feat_keys:
        raise ValueError("train evidence produced no feature keys")
    idx = _signal_indices(feat_keys, combo) if combo else list(range(len(feat_keys)))
    X = _feature_matrix(evs, feat_keys)
    Xtr = X[:, idx] if idx else np.zeros((len(X), 1))
    ytr = np.asarray([1.0 if lab == "unsafe" else 0.0 for lab in labels], dtype=float)

    if model_kind == "standardized_logistic":
        _, _, _, predict_fn = standardized_logistic(Xtr, ytr, seed=seed)
        trainer = None
    else:
        trainer = _make_trainer(model_kind, seed=seed)
        predict_fn = None

    return FrozenScorer(target=target, feat_keys=feat_keys, idx=idx,
                        trainer=trainer, x_train=Xtr, y_train=ytr,
                        predict_fn=predict_fn, t_accept=t_accept, t_reject=t_reject)


class FrozenScorer:
    """每窗 evidence → no-GT shadow（unsafe_intervals / n_units / decision）。"""

    def __init__(self, *, target, feat_keys, idx, trainer, x_train, y_train,
                 predict_fn, t_accept, t_reject):
        self.target = target
        self.feat_keys = feat_keys
        self.idx = idx
        self.trainer = trainer
        self.x_train = x_train
        self.y_train = y_train
        self.predict_fn = predict_fn
        self.t_accept = t_accept
        self.t_reject = t_reject

    def score(self, evidence_rows) -> dict:
        """窗内 evidence 行 → shadow dict（与 catastrophic_commit 兼容）。"""
        if not evidence_rows:
            return {"unsafe_intervals": [], "n_units": 0, "decision": "accept"}
        evs, _ = _evidence_rows(evidence_rows)
        X = _feature_matrix(evs, self.feat_keys)
        Xte = X[:, self.idx] if self.idx else np.zeros((len(X), 1))
        if self.predict_fn is not None:
            p_bad = np.asarray(self.predict_fn(Xte), dtype=float).ravel()
        else:
            p_bad = np.asarray(
                self.trainer(self.x_train, self.y_train, Xte), dtype=float).ravel()

        probs = {i: float(p) for i, p in enumerate(p_bad)}
        output = tristate_from_p_bad(
            probs, self.t_accept, self.t_reject,
            request_identity="frozen_shadow")

        decision = "accept"
        unsafe_intervals: list[list[float]] = []
        for iv in output.state_intervals:
            value = iv.state.value
            if value == "reject":
                i0, i1 = int(iv.interval.start), int(iv.interval.end)
                unsafe_intervals.append([
                    _unit_start_sec(evs[i0]), _unit_end_sec(evs[i1 - 1])])
                decision = "reject"
            elif value == "uncertain" and decision != "reject":
                decision = "uncertain"

        return {"unsafe_intervals": unsafe_intervals,
                "n_units": len(evs), "decision": decision}
