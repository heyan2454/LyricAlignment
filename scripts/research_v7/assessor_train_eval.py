#!/usr/bin/env python3
"""review11-4：region assessor train/freeze consumer —— 只消费 guarded evidence collection。

现有 analysis/evaluate 脚本仍读旧 `{out_root,records}` collection；本 CLI 是接入新
`research_v7_trainable_evidence_collection_v1` schema 的实际 consumer：

- 入口唯一：`--collection` 必须经 `load_verified()` 校验（guard present=True +
  collection_sha256 + 每份 evidence 文件存在），否则拒绝；
- 对每个 trainable evidence 提取 unit 特征（features.unit_features，R/O/H）；
- 标签只允许来自 evidence 的 `attempt.gt_eval["unsafe_unit_indices"]`（评审：GT 不进输入特征，
  标签不参与 request identity）；无标签时明确记录 labels_available=false 并拒绝训练/冻结，
  不假装产 operating points；
- 按 item_id 划分 train/val（train_frac），fit_and_freeze 只从 train 拟合、val 选 operating point；
- 输出 ASSESSOR_RUN_MANIFEST.json：collection SHA、实际 train/eval 分母、输出路径；
- round04/op-persist：ASSESSOR.json 额外持久化冻结权重（assessor.model.beta/mean/std/
  feature_keys），供 T4 对 MIR 打分；旧 v1 文件（无 model）经 _load_assessor() 加载
  返回 (None, reason) 兼容。

用法：
  PYTHONPATH=src python scripts/research_v7/assessor_train_eval.py \
      --collection <collection.json> --out <run_dir> [--train-frac 0.7] [--include-hidden]
      [--allow-zero-hidden] [--split-by item|song] [--family missing,replace] [--family-loo]

hidden 特征当前为声明停用（features.HIDDEN_FEATURES_ENABLED=False）：real_executor 不产 hidden，
`--include-hidden` 喂给模型的是全零占位。因此 `--include-hidden` 无 `--allow-zero-hidden` 时
确定性失败（非零退出并说明原因）；`--allow-zero-hidden` 是显式逃逸，仅供兼容旧 smoke。

round18（family 分层 + per-song LOO，13 §10.3/§10.2）：collection 转存 mutation_type 后，
本 CLI 增加：
  - `--split-by item|song`：train/val 切分维度；song 按 item_id.split(':')[0]（source song）
    切分，保证歌隔离（同歌 request 不跨折）；
  - `--family <f1,f2,...>`：只训练/评价指定 mutation family（baseline/missing/replace/extra）；
  - `--family-loo`：对每个 family 留出重训 + 对留出 family 打分（输出 FAMILY_LOO.json）；
  - manifest 增加 split_by / families / split（train/val 组 key）与 assessor.val_metrics
    （frozen op 下 val 的弱标签 unit_recall / correct_unit_fpr）。
mutation family 只用于分层，不进特征（13 §10.1）；family_loo / group_loo 可被
assessor_family_eval.py 复用（汇总驱动）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from lyricalign.research_v7.features import HIDDEN_FEATURES_ENABLED, unit_features  # noqa: E402
from lyricalign.research_v7.region_assessor import fit_and_freeze  # noqa: E402

COLLECTION_SCHEMA = "research_v7_trainable_evidence_collection_v1"

# round04/op-persist：v2 起 ASSESSOR.json 携带冻结模型权重（beta/mean/std）；
# v1 旧文件无 model 字段，加载方必须走 _load_assessor() 兼容（返回 None + reason）。
ASSESSOR_MANIFEST_SCHEMA = "research_v7_assessor_consumer_run_v2"
ASSESSOR_V1_COMPAT_NOTE = (
    "v2: assessor.model 持久化冻结 logistic 权重 {beta,mean,std,feature_keys}; "
    "v1 ASSESSOR.json 无 model 字段, 经 _load_assessor() 加载返回 (None, reason)"
)


def _load_assessor(path: Path | str) -> tuple[dict | None, str | None]:
    """加载 ASSESSOR.json（compat 契约）；旧文件（无 model 字段）/损坏/缺失 → (None, reason)。

    round04/op-persist：consumers 一律经此函数取冻结权重，不得直接读 ASSESSOR.json
    假设 model 存在。加载方需处理 (None, reason)：例如
    evaluate_cross_domain_assessor.load_m4_assessor 先复用本函数 base 校验，
    被拒时把 reason 转成 ValueError，再叠加 strict 校验（形状/有限值/feature_keys 非空）。
    """
    p = Path(path)
    if not p.is_file():
        return None, f"no assessor file at {p}"
    try:
        a = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return None, f"assessor file unreadable: {e}"
    m = a.get("model")
    if not isinstance(m, dict):
        return None, "assessor lacks model weights (v1 legacy or untrained)"
    missing = [k for k in ("beta", "mean", "std") if not isinstance(m.get(k), list)]
    if missing:
        return None, f"assessor model incomplete, missing {missing}"
    return a, None


def _atomic_write(path: Path, payload: dict) -> None:
    import os
    import tempfile

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
        f.flush(); os.fsync(f.fileno())
    os.replace(tmp, path)


def _load_verified_collection(path: Path):
    """唯一入口：校验 guard/collection_sha256/evidence 存在；返回 (collection, sha)。"""
    sys.path.insert(0, str(Path(__file__).resolve().parents[0]))
    from collect_trainable_evidence import load_verified
    return load_verified(path)


def _unit_rows(evidence: dict) -> list[tuple[dict, int]]:
    """从 evidence 的 official decoder rows 提取 (row, row_index)。无 rows → 空。"""
    attempt = evidence.get("attempt") or {}
    rows = (attempt.get("decoder_outputs") or {}).get("official") or {}
    rows = rows.get("rows") or []
    return [(r, i) for i, r in enumerate(rows) if isinstance(r, dict)]


def _labels_from_gt_eval(attempt: dict) -> tuple[set[int] | None, str | None]:
    """读取 GT 标签：attempt.gt_eval.unsafe_unit_indices（unit 局部索引）。

    返回 (unsafe_set, error)；无标签/格式错误 → (None, reason)，不训练。
    """
    gt = attempt.get("gt_eval")
    if not isinstance(gt, dict):
        return None, "no gt_eval in evidence"
    raw = gt.get("unsafe_unit_indices")
    if raw is None:
        return None, "gt_eval lacks unsafe_unit_indices"
    try:
        idx = [int(i) for i in raw]
    except (TypeError, ValueError) as e:
        return None, f"gt_eval unsafe_unit_indices malformed: {e}"
    return set(idx), None


# ---- round18：family 分层 / per-song 切分辅助（mutation family 只用于分层，不进特征）----

def _family_of(t: dict, request: dict) -> str | None:
    """evidence 的 mutation family：优先 collection 转存字段，缺失回退 evidence.request。"""
    f = t.get("mutation_type")
    if f is None:
        f = request.get("mutation_type")
    return f


def _song_of(item_id: str) -> str:
    """source song：item_id 首段（song:win:slot:family 约定，review12 formal 口径）。"""
    return item_id.split(":")[0]


def _extract_rows(c: dict, *, families: set[str] | None = None,
                  include_hidden: bool = False) -> dict:
    """从 guarded collection 提取 unit 特征行 + 弱标签。

    families 非 None 时只消费该 family 子集（denominator 随子集计；mutation family
    只进分层字段 fr.family，绝不进 fr.features）。返回 feature_rows（含
    request_identity/item_id/song/family/unit_index/features）、labels、denominator、
    label_errors。
    """
    feature_rows: list[dict] = []
    labels: dict[str, set[int]] = {}
    denominator = {"trainable_evidence": 0, "units": 0, "items": 0}
    label_errors: list[str] = []
    for t in c.get("trainable_evidence", []):
        idn = t.get("request_identity")
        ev_path = Path(t.get("path"))
        if not ev_path.is_file():
            raise ValueError(f"collection lists missing evidence file: {ev_path}")
        ev = json.loads(ev_path.read_text(encoding="utf-8"))
        attempt = ev.get("attempt") or {}
        request = attempt.get("request") or {}
        family = _family_of(t, request)
        if families is not None and family not in families:
            continue
        item_id = request.get("item_id") or t.get("item_id") or "?"
        rows = _unit_rows(ev)
        denominator["trainable_evidence"] += 1
        denominator["items"] += 1
        unsafe, lerr = _labels_from_gt_eval(attempt)
        if lerr:
            label_errors.append(f"{idn}: {lerr}")
        else:
            labels[idn] = unsafe
        for row, row_i in rows:
            feats = unit_features(row, include_hidden=include_hidden)
            fr = {
                "request_identity": idn,
                "item_id": item_id,
                "song": _song_of(item_id),
                "family": family,
                "unit_index": row_i,
                "features": feats,
            }
            feature_rows.append(fr)
            denominator["units"] += 1
    denominator["items"] = len({fr["item_id"] for fr in feature_rows})
    return {"feature_rows": feature_rows, "labels": labels, "denominator": denominator,
            "label_errors": label_errors}


def _feature_keys(feature_rows: list[dict]) -> list[str]:
    """统一特征键集合：跨行对齐（缺失键构造 xvec 时填 0.0，防列形状不一致崩溃）。"""
    return sorted({k for fr in feature_rows for k in fr["features"]
                   if isinstance(fr["features"][k], (int, float)) and fr["features"][k] is not None})


def _xvec(fr: dict, keys: list[str]) -> list[float]:
    return [float(fr["features"].get(k) or 0.0) for k in keys]


def _row_y(fr: dict, labels: dict[str, set[int]]) -> float:
    return 1.0 if fr["unit_index"] in labels.get(fr["request_identity"], set()) else 0.0


def _split_keys(keys: list[str], split_by: str, train_frac: float) -> tuple[list[str], list[str], str]:
    """按 item（默认）或 song（item_id.split(':')[0]）切分 train/val key 列表。

    返回 (train_keys, val_keys, mode)；mode ∈ by_item/by_song。调用方负责在任一折为空时
    回退 by_unit（单 item/song 场景）。
    """
    if split_by == "song":
        song_ids = sorted({_song_of(k) for k in keys})
        k = max(1, int(len(song_ids) * train_frac))
        train_songs, val_songs = set(song_ids[:k]), set(song_ids[k:])
        return ([kk for kk in keys if _song_of(kk) in train_songs],
                [kk for kk in keys if _song_of(kk) in val_songs], "by_song")
    ordered = sorted(keys)
    k = max(1, int(len(ordered) * train_frac))
    return (ordered[:k], ordered[k:], "by_item")


def _fit_val_partition(rows: list[dict], train_frac: float, split_by: str) -> tuple[list[dict], list[dict], str]:
    """把一组行按 item/song 切 fit/val；任一折为空 → unit 级固定 seed 划分回退。"""
    per_item: dict[str, list] = {}
    for fr in rows:
        per_item.setdefault(fr["item_id"], []).append(fr)
    train_keys, val_keys, mode = _split_keys(sorted(per_item), split_by, train_frac)
    train_set, val_set = set(train_keys), set(val_keys)
    train_rows = [fr for fr in rows if fr["item_id"] in train_set]
    val_rows = [fr for fr in rows if fr["item_id"] in val_set]
    if not val_rows:
        # 单 item/song → unit 级固定 seed 划分：保证两折非空（不用逐 unit random）。
        mode = "by_unit_fallback"
        import random as _r
        rng = _r.Random(0)
        order = list(range(len(rows)))
        rng.shuffle(order)
        k = max(1, int(len(order) * train_frac))
        train_set = set(order[:k])
        train_rows = [rows[i] for i in range(len(rows)) if i in train_set]
        val_rows = [rows[i] for i in range(len(rows)) if i not in train_set]
    return train_rows, val_rows, mode


def _binary_scores(y: np.ndarray, proba: np.ndarray, th95: float, th99: float) -> dict:
    """在 frozen 阈值下对一组带标签 unit 打分（弱标签口径，同 evaluate_cross_domain_assessor：
    空 GT 且无 pred 记 1.0（vacuous），有 pred 无 GT 记 0.0；FPR 分母 = 正确保留 unit）。"""
    n = int(len(y))
    out = {"n_units": n, "n_gt_unsafe_units": int(np.sum(y > 0.5)),
           "n_safe_units": int(np.sum(y <= 0.5))}
    for tag, th in (("95", th95), ("99", th99)):
        pred = proba >= th
        n_pred = int(np.sum(pred))
        gt = y > 0.5
        hit = int(np.sum(pred & gt))
        n_gt = int(np.sum(gt))
        fp = int(np.sum(pred & ~gt))
        n_safe = n - n_gt
        if n_gt or n_pred:
            recall = (hit / n_gt) if n_gt else 0.0
        elif n == 0:
            recall = None
        else:
            recall = 1.0
        out[f"n_pred_{tag}"] = n_pred
        out[f"n_hit_{tag}"] = hit
        out[f"n_fp_{tag}"] = fp
        out[f"unit_recall_{tag}"] = round(recall, 4) if recall is not None else None
        out[f"correct_unit_fpr_{tag}"] = round(fp / n_safe, 4) if n_safe else 0.0
        out[f"unsafe_rate_{tag}"] = round(n_pred / n, 4) if n else 0.0
    return out


def _fit_freeze_eval(fit_rows: list[dict], test_rows: list[dict], labels: dict,
                     keys: list[str], train_frac: float, split_by: str) -> dict:
    """fit_rows 内按 split_by/train_frac 切 fit/val → fit_and_freeze（val 冻结 op）；
    再对 test_rows（held-out group，训练完全不可见）打分。返回 frozen op / val 指标 /
    test 指标；两折不足时 reason 且各指标为 None。"""
    tr, vr, mode = _fit_val_partition(fit_rows, train_frac, split_by)
    if not tr or not vr:
        return {"operating_points": None, "split_mode": mode, "fit_units": len(tr),
                "val_units": len(vr), "val_metrics": None, "test": None,
                "reason": "not enough units for fit/val split"}
    Xt = np.asarray([_xvec(fr, keys) for fr in tr], dtype=float)
    yt = np.asarray([_row_y(fr, labels) for fr in tr], dtype=float)
    Xv = np.asarray([_xvec(fr, keys) for fr in vr], dtype=float)
    yv = np.asarray([_row_y(fr, labels) for fr in vr], dtype=float)
    res = fit_and_freeze(Xt, yt, Xv, yv)
    op = res["operating_points"]
    proba_v = res["model"].predict_proba(Xv)
    val_metrics = _binary_scores(yv, proba_v, op["high_recall_95"], op["high_recall_99"])
    test = None
    if test_rows:
        Xte = np.asarray([_xvec(fr, keys) for fr in test_rows], dtype=float)
        yte = np.asarray([_row_y(fr, labels) for fr in test_rows], dtype=float)
        test = _binary_scores(yte, res["model"].predict_proba(Xte),
                              op["high_recall_95"], op["high_recall_99"])
    return {"operating_points": op, "split_mode": mode, "fit_units": len(tr),
            "val_units": len(vr), "val_metrics": val_metrics, "test": test}


def group_loo(rows: list[dict], labels: dict, keys: list[str], group_names: list[str],
              group_of, train_frac: float, split_by: str) -> list[dict]:
    """对每个 group 留出重训（group 完全不可见，不参与拟合也不参与冻结）并打分。

    group_of(fr) -> group 名；rows 为全量特征行（keys 由调用方在全量上统一构造，
    保证各折列对齐一致）。返回 per-group 结果列表（_fit_freeze_eval 结构 + group）。
    """
    results = []
    for g in group_names:
        fit_rows = [fr for fr in rows if group_of(fr) != g]
        test_rows = [fr for fr in rows if group_of(fr) == g]
        res = _fit_freeze_eval(fit_rows, test_rows, labels, keys, train_frac, split_by)
        results.append({"group": g, **res})
    return results


def consume(collection_path: Path, out: Path, *, train_frac: float = 0.7,
            include_hidden: bool = False, allow_zero_hidden: bool = False,
            split_by: str = "item", families: list[str] | None = None) -> dict:
    """消费 collection：特征提取 + 标签 + assessor train/freeze；返回 run manifest dict。

    round18：split_by（item 默认 / song 歌隔离）与 families（mutation family 分层，
    只用于分层不进特征）筛选；manifest 记录 split_by/families/split 与 val_metrics
    （frozen op 下 val 弱标签 unit_recall / correct_unit_fpr）。
    """
    if include_hidden and not HIDDEN_FEATURES_ENABLED and not allow_zero_hidden:
        # review17 #4：hidden 未启用时拒绝把全零占位当真实特征训练（确定性失败）
        raise ValueError(
            "hidden extraction not enabled; refusing to train on zero-placeholder hidden features "
            "(pass --allow-zero-hidden to explicitly accept the zero-placeholder)")
    if not (0.0 < train_frac < 1.0):
        raise ValueError(f"train_frac must be in (0,1), got {train_frac}")
    if split_by not in ("item", "song"):
        raise ValueError(f"split_by must be 'item' or 'song', got {split_by!r}")
    fam_set = {f.strip() for f in families} if families else None
    if fam_set == set():
        raise ValueError("families must be a non-empty list of mutation family names")
    c, collection_sha = _load_verified_collection(collection_path)
    if c.get("schema") != COLLECTION_SCHEMA:
        raise ValueError(f"collection schema mismatch: {c.get('schema')!r}")
    ex = _extract_rows(c, families=fam_set, include_hidden=include_hidden)
    feature_rows = ex["feature_rows"]
    labels = ex["labels"]
    denominator = ex["denominator"]
    label_errors = ex["label_errors"]
    feature_keys = _feature_keys(feature_rows)
    from collections import Counter as _Counter
    family_counts = dict(sorted(_Counter(fr["family"] for fr in feature_rows).items(),
                                key=lambda kv: (kv[0] is None, kv[0] or "")))
    # 标签可用性：任何 evidence 无 gt_eval → 整体拒绝训练（不假装 operating points）
    labels_available = (not label_errors) and bool(labels) and denominator["units"] > 0
    assessor = {"labels_available": labels_available, "operating_points": None,
                "reason": None, "train_units": None, "val_units": None,
                "split_mode": None, "val_metrics": None, "model": None}
    split = {"mode": None}
    if labels_available:
        # 按 split_by 维度划分 train/val（同 item/同歌不跨集合），只从 train 拟合；
        # 任一折为空时回退 unit 级固定 seed 随机划分，并在 manifest 记录。
        tr, vr, mode = _fit_val_partition(feature_rows, train_frac, split_by)
        assessor["split_mode"] = mode
        split = {"mode": mode}
        if mode != "by_unit_fallback":
            split["train_keys"] = sorted({fr["item_id"] for fr in tr})
            split["val_keys"] = sorted({fr["item_id"] for fr in vr})
        if not tr or not vr:
            assessor["reason"] = "not enough units for train/val split"
            assessor["labels_available"] = False
        else:
            Xt = np.asarray([_xvec(fr, feature_keys) for fr in tr], dtype=float)
            yt = np.asarray([_row_y(fr, labels) for fr in tr], dtype=float)
            Xv = np.asarray([_xvec(fr, feature_keys) for fr in vr], dtype=float)
            yv = np.asarray([_row_y(fr, labels) for fr in vr], dtype=float)
            res = fit_and_freeze(Xt, yt, Xv, yv)
            assessor["operating_points"] = res["operating_points"]
            assessor["train_units"] = len(Xt)
            assessor["val_units"] = len(Xv)
            assessor["val_metrics"] = _binary_scores(
                yv, res["model"].predict_proba(Xv),
                res["operating_points"]["high_recall_95"],
                res["operating_points"]["high_recall_99"])
            # round04/op-persist：持久化冻结权重（numpy → list of float），
            # 供 T4 对 MIR 打分；beta 含截距（len = d+1），mean/std 长度 = d。
            m = res["model"]
            assessor["model"] = {
                "beta": [float(v) for v in np.asarray(m.beta, dtype=float).ravel()],
                "mean": [float(v) for v in np.asarray(m.mean, dtype=float).ravel()],
                "std": [float(v) for v in np.asarray(m.std, dtype=float).ravel()],
                "feature_keys": list(feature_keys),
            }
    else:
        assessor["reason"] = "; ".join(label_errors[:5]) if label_errors else "no labels in collection"
    # 输出：特征行 + assessor + run manifest（记录 collection SHA、实际分母、输出路径）
    features_file = out / "UNIT_FEATURES.jsonl"
    features_file.parent.mkdir(parents=True, exist_ok=True)
    with open(features_file, "w", encoding="utf-8") as f:
        for fr in feature_rows:
            f.write(json.dumps(fr, ensure_ascii=False, sort_keys=True, default=str) + "\n")
    assessor_file = out / "ASSESSOR.json"
    _atomic_write(assessor_file, assessor)
    manifest = {
        "schema": ASSESSOR_MANIFEST_SCHEMA,
        "schema_note": ASSESSOR_V1_COMPAT_NOTE,
        "collection_sha256": collection_sha,
        "input_collection": str(collection_path.resolve()),
        "code": {"script": "assessor_train_eval.py",
                 "features_module": "lyricalign.research_v7.features",
                 "assessor_module": "lyricalign.research_v7.region_assessor"},
        "split_by": split_by,
        "families": sorted(fam_set) if fam_set is not None else None,
        "family_counts": family_counts,
        "split": split,
        "denominator": denominator,
        "feature_keys": feature_keys,
        "labels": {"available": labels_available, "evidence_with_labels": len(labels),
                   "error_count": len(label_errors)},
        "hidden": {"enabled": bool(HIDDEN_FEATURES_ENABLED),
                   "note": "zero-placeholder rejected unless --allow-zero-hidden"},
        "assessor": {k: v for k, v in assessor.items()},
        "outputs": {"features": str(features_file), "assessor": str(assessor_file),
                    "manifest": str(out / "ASSESSOR_RUN_MANIFEST.json")},
    }
    _atomic_write(out / "ASSESSOR_RUN_MANIFEST.json", manifest)
    return manifest


def family_loo(collection_path: Path, out: Path, *, train_frac: float = 0.7,
               include_hidden: bool = False, allow_zero_hidden: bool = False,
               split_by: str = "item", families: list[str] | None = None) -> dict:
    """mutation family leave-one-out（13 §10.3）：对每个 family 留出重训 + 打分。

    对留出 family f：用其余 family 全部 evidence 拟合并冻结 op（其内按 split_by/
    train_frac 切 fit/val），再对 f 打分（f 完全不可见——不参与拟合也不参与冻结）。
    输出 FAMILY_LOO.json（schema research_v7_assessor_family_loo_v1），返回 summary。
    """
    if include_hidden and not HIDDEN_FEATURES_ENABLED and not allow_zero_hidden:
        raise ValueError(
            "hidden extraction not enabled; refusing to train on zero-placeholder hidden features "
            "(pass --allow-zero-hidden to explicitly accept the zero-placeholder)")
    if not (0.0 < train_frac < 1.0):
        raise ValueError(f"train_frac must be in (0,1), got {train_frac}")
    if split_by not in ("item", "song"):
        raise ValueError(f"split_by must be 'item' or 'song', got {split_by!r}")
    c, collection_sha = _load_verified_collection(collection_path)
    if c.get("schema") != COLLECTION_SCHEMA:
        raise ValueError(f"collection schema mismatch: {c.get('schema')!r}")
    ex = _extract_rows(c, include_hidden=include_hidden)
    feature_rows = ex["feature_rows"]
    labels = ex["labels"]
    label_errors = ex["label_errors"]
    keys = _feature_keys(feature_rows)
    present = sorted({fr["family"] for fr in feature_rows if fr["family"] is not None})
    loo_families = sorted(set(families)) if families else present
    if not loo_families:
        raise ValueError("no mutation families present in collection for family-LOO")
    labels_available = (not label_errors) and bool(labels) and len(feature_rows) > 0
    summary = {
        "schema": "research_v7_assessor_family_loo_v1",
        "collection_sha256": collection_sha,
        "train_frac": train_frac,
        "split_by": split_by,
        "families": loo_families,
        "labels_available": labels_available,
        "reason": None if labels_available else (
            "; ".join(label_errors[:5]) if label_errors else "no labels in collection"),
        "loo": [],
        "pooled_test": None,
    }
    if labels_available:
        for f in loo_families:
            test_rows = [fr for fr in feature_rows if fr["family"] == f]
            fit_rows = [fr for fr in feature_rows if fr["family"] != f]
            res = _fit_freeze_eval(fit_rows, test_rows, labels, keys, train_frac, split_by)
            if not test_rows:
                res["reason"] = "held-out family has no units in collection"
            summary["loo"].append({"family": f, **res})
        # pooled：每 family 由各自 LOO 模型打分，跨 family 汇总（只合并测试口径，不合并训练）
        tot = {"n_units": 0, "n_gt": 0, "n_safe": 0}
        acc = {t: {"hit": 0, "pred": 0, "fp": 0} for t in ("95", "99")}
        for row in summary["loo"]:
            te = row.get("test")
            if not te:
                continue
            tot["n_units"] += te["n_units"]
            tot["n_gt"] += te["n_gt_unsafe_units"]
            tot["n_safe"] += te["n_safe_units"]
            for t in ("95", "99"):
                acc[t]["hit"] += te[f"n_hit_{t}"]
                acc[t]["pred"] += te[f"n_pred_{t}"]
                acc[t]["fp"] += te[f"n_fp_{t}"]
        pooled = {"n_units": tot["n_units"], "n_gt_unsafe_units": tot["n_gt"]}
        for t in ("95", "99"):
            gt, pred = tot["n_gt"], acc[t]["pred"]
            if gt or pred:
                recall = acc[t]["hit"] / gt if gt else 0.0
            elif tot["n_units"] == 0:
                recall = None
            else:
                recall = 1.0
            pooled[f"unit_recall_{t}"] = round(recall, 4) if recall is not None else None
            pooled[f"correct_unit_fpr_{t}"] = (
                round(acc[t]["fp"] / tot["n_safe"], 4) if tot["n_safe"] else 0.0)
        summary["pooled_test"] = pooled
    _atomic_write(out / "FAMILY_LOO.json", summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--collection", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--train-frac", type=float, default=0.7)
    p.add_argument("--include-hidden", action="store_true")
    p.add_argument("--allow-zero-hidden", action="store_true",
                   help="显式接受全零占位 hidden 特征（hidden 未启用时 --include-hidden 的逃逸口）")
    p.add_argument("--split-by", choices=("item", "song"), default="item",
                   help="train/val 切分维度：item（默认，现行为）或 song（item_id.split(':')[0]"
                        " 歌隔离，同歌 request 不跨折）")
    p.add_argument("--family", default=None,
                   help="只训练/评价指定 mutation family（逗号分隔，如 missing,baseline；"
                        "family 只用于分层，不进特征）")
    p.add_argument("--family-loo", action="store_true",
                   help="mutation family leave-one-out：每 family 留出重训 + 对留出 family 打分"
                        "（输出 FAMILY_LOO.json）")
    a = p.parse_args(argv)
    families = [f.strip() for f in a.family.split(",")] if a.family else None
    try:
        if a.family_loo:
            s = family_loo(Path(a.collection), Path(a.out), train_frac=a.train_frac,
                           include_hidden=a.include_hidden, allow_zero_hidden=a.allow_zero_hidden,
                           split_by=a.split_by, families=families)
            out_summary = Path(a.out) / "FAMILY_LOO.json"
            print(json.dumps({"ok": True, "mode": "family_loo",
                              "labels_available": s["labels_available"],
                              "families": s["families"], "split_by": s["split_by"],
                              "loo_folds": len(s["loo"]),
                              "out": str(out_summary)}, ensure_ascii=False, indent=2))
            # C3（review12）：无标签时输出已写（含 reason），但退出码非 0
            return 0 if s["labels_available"] else 2
        m = consume(Path(a.collection), Path(a.out), train_frac=a.train_frac,
                    include_hidden=a.include_hidden, allow_zero_hidden=a.allow_zero_hidden,
                    split_by=a.split_by, families=families)
    except ValueError as e:
        # 确定性失败：原因写 stderr、退出码非 0（如 hidden 未启用却 --include-hidden）
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, "collection_sha256": m["collection_sha256"][:16],
                      "trainable_evidence": m["denominator"]["trainable_evidence"],
                      "units": m["denominator"]["units"],
                      "labels_available": m["labels"]["available"],
                      "split_by": m["split_by"],
                      "families": m["families"],
                      "split_mode": m["assessor"].get("split_mode"),
                      "operating_points": m["assessor"]["operating_points"],
                      "val_metrics": m["assessor"].get("val_metrics"),
                      "model_dims": {k: len(v) for k, v in (m["assessor"].get("model") or {}).items()
                                     if isinstance(v, list)} or None,
                      "out": str(Path(a.out))}, ensure_ascii=False))
    # C3（review12）：无标签时输出已写（含 reason），但退出码非 0，
    # 防止 formal 管线把"无标签的 assessor"误当训练成功继续推进。
    if not m["labels"]["available"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
