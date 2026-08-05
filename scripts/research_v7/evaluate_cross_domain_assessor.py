#!/usr/bin/env python3
"""round04 T4 + round13：冻结 assessor 评价 CLI —— 任意域 v2 assessor 对 guarded collection 打分。

13 §10.3 评价口径：assessor 训练/验证冻结后跨数据集/域内测试；M4、MIR、demo 分开汇报、
不合并成一个准确率。本 CLI 是 assessor 打分评价：

- 输入任意域冻结 assessor（v2 格式 ASSESSOR.json：model.beta/mean/std/feature_keys，
  由 assessor_train_eval.py 产出）；旧格式（只有 operating_points、无 model 权重）→
  明确错误并非零退出。
- collection 输入必须走 collect_trainable_evidence 的 guarded collection（load_verified 校验）。
- 对每份 evidence 的 official rows 提取 unit_features，按 model.feature_keys 对齐
  （缺失/非数值填 0，与 assessor_train_eval.consume 同法）→ predict_proba。
- 阈值二值化 high_recall_95/99：operating_points 从 ASSESSOR.json 读，缺的键回退
  model 默认（0.5，logistic 默认决策边界）。
- 弱标签评价：unit 真值 = attempt.gt_eval.unsafe_unit_indices（弱监督，非人工 GT，
  gt_axis_note=weak_labeled_qwen_fa_timestamps）。无标签 evidence 的 unit 仍打分
  （计入 n_units/n_rows/pred/分布），但排除出 recall/FPR 的标签分母，并记录 n_label_errors。
- 特征提取审计沿用 features.BLOCKED 字段（feature_extractor_blocked），输出 leak_check。
- 输出 ASSESSOR_CROSS_DOMAIN_EVAL.json（schema research_v7_assessor_cross_domain_eval_v1）：
  assessor 域（m4_assessor 键，schema 固定名）/ collection 域（mir1k 键，schema 固定名）
  分开汇报，不合并分母；`--domain` 记录被打分 collection 的域（默认 mir1k）。

round13 用法扩展：CLI 参数名泛化为 `--assessor` / `--collection`（`--m4-assessor` /
`--mir1k-collection` 为兼容别名），支持 MIR 域内自评（MIR in-domain assessor 打分 MIR
collection，--domain mir1k）与跨域评价同口径对比。

用法：
  PYTHONPATH=src python scripts/research_v7/evaluate_cross_domain_assessor.py \
      --assessor <ASSESSOR.json> --collection <collection.json> --out <out_dir> [--domain mir1k]
  兼容旧名：
  PYTHONPATH=src python scripts/research_v7/evaluate_cross_domain_assessor.py \
      --m4-assessor <ASSESSOR.json> --mir1k-collection <collection.json> --out <out_dir>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[0]))

import numpy as np  # noqa: E402

from lyricalign.research_v7.features import feature_extractor_blocked, unit_features  # noqa: E402
from lyricalign.research_v7.region_assessor import LogisticAssessor  # noqa: E402
from collect_trainable_evidence import load_verified  # noqa: E402

SCHEMA = "research_v7_assessor_cross_domain_eval_v1"
GT_AXIS_NOTE = "weak_labeled_qwen_fa_timestamps (not human GT)"
DEFAULT_OPERATING_POINTS = {"high_recall_95": 0.5, "high_recall_99": 0.5}
OUTPUT_NAME = "ASSESSOR_CROSS_DOMAIN_EVAL.json"


def _atomic_write(path: Path, payload: dict) -> None:
    import os
    import tempfile

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def load_m4_assessor(path: Path) -> dict:
    """加载 T3 冻结 assessor（strict 契约）；不合法 → ValueError（可读错误）。

    与 assessor_train_eval._load_assessor（compat 契约：(None, reason) 返回）的差异：
    本函数先复用 _load_assessor 的 base 校验（文件缺失/JSON 损坏/无 model 字段/
    beta/mean/std 非 list → (None, reason)），若被拒则抛 ValueError(reason)；
    通过后再叠加 strict 校验（feature_keys 非空字符串列表、权重形状与 feature_keys
    一致、有限且 std > 0），保证返回的 model 可直接喂 LogisticAssessor。
    """
    sys.path.insert(0, str(Path(__file__).resolve().parents[0]))
    import assessor_train_eval
    data, reason = assessor_train_eval._load_assessor(path)
    if reason is not None:
        raise ValueError(reason)
    model = data["model"]
    feature_keys = model.get("feature_keys")
    if not isinstance(feature_keys, list) or not feature_keys:
        raise ValueError("assessor model feature_keys must be a non-empty list")
    if not all(isinstance(k, str) for k in feature_keys):
        raise ValueError("assessor model feature_keys must be strings")
    n = len(feature_keys)
    beta = np.asarray(model["beta"], dtype=float)
    mean = np.asarray(model["mean"], dtype=float)
    std = np.asarray(model["std"], dtype=float)
    if beta.shape != (n + 1,) or mean.shape != (n,) or std.shape != (n,):
        raise ValueError(
            f"assessor model weight shapes inconsistent with feature_keys (n={n}): "
            f"beta{beta.shape} mean{mean.shape} std{std.shape}; "
            "expected beta=(n+1,), mean/std=(n,)")
    if (np.any(~np.isfinite(beta)) or np.any(~np.isfinite(mean))
            or np.any(~np.isfinite(std)) or np.any(std <= 0)):
        raise ValueError("assessor model weights must be finite with std > 0")
    return {
        "model": {
            "beta": beta, "mean": mean, "std": std, "feature_keys": feature_keys,
        },
        "operating_points": data.get("operating_points"),
    }


def _resolve_operating_points(assessor_op) -> tuple[dict, str]:
    """operating_points 从 ASSESSOR.json 读；缺的键回退 model 默认（0.5）。

    返回 (thresholds, source)：source ∈ {assessor, assessor_partial_default, model_default}。
    """
    merged = dict(DEFAULT_OPERATING_POINTS)
    if not isinstance(assessor_op, dict):
        return merged, "model_default"
    from_file = 0
    for k, dflt in DEFAULT_OPERATING_POINTS.items():
        v = assessor_op.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and 0.0 < v <= 1.0:
            merged[k] = float(v)
            from_file += 1
    if from_file == 2:
        return merged, "assessor"
    if from_file == 0:
        return merged, "model_default"
    return merged, "assessor_partial_default"


def _unit_rows(evidence: dict) -> list[tuple[dict, int]]:
    """从 evidence 的 official decoder rows 提取 (row, row_index)。无 rows → 空。"""
    attempt = evidence.get("attempt") or {}
    rows = (attempt.get("decoder_outputs") or {}).get("official") or {}
    rows = rows.get("rows") or []
    return [(r, i) for i, r in enumerate(rows) if isinstance(r, dict)]


def _labels_from_gt_eval(attempt: dict) -> tuple[set[int] | None, str | None]:
    """读取弱标签：attempt.gt_eval.unsafe_unit_indices（unit 局部索引）。

    返回 (unsafe_set, error)；无标签/格式错误 → (None, reason)。
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


def _aligned_xvec(feats: dict, keys: list[str]) -> list[float]:
    """按 model.feature_keys 对齐；缺失/非数值填 0（与 assessor_train_eval.consume 同法）。"""
    x = []
    for k in keys:
        v = feats.get(k)
        try:
            x.append(float(v) if v is not None else 0.0)
        except (TypeError, ValueError):
            x.append(0.0)
    return x


def _recall(n_hit: int, n_gt: int, n_pred: int, n_units: int) -> float | None:
    """弱标签 recall（与 evaluate_long_slot_gt 空集约定一致，避免真空膨成 1.0）。"""
    if n_gt or n_pred:
        return round(n_hit / n_gt, 4) if n_gt else 0.0
    if n_units == 0:
        return None
    return 1.0


def evaluate(assessor_path: Path, collection_path: Path, *, domain: str = "mir1k") -> dict:
    """加载冻结 assessor + guarded collection，打分并返回 eval 结果 dict。

    domain：被打分 collection 的域标签（默认 "mir1k"），记录在 eval_domain 字段；
    不影响输出 schema 的固定键 m4_assessor/mir1k（report/quality analysis 兼容）。
    """
    assessor = load_m4_assessor(assessor_path)
    collection, collection_sha = load_verified(collection_path)
    if collection.get("schema") != "research_v7_trainable_evidence_collection_v1":
        raise ValueError(
            f"collection schema mismatch: {collection.get('schema')!r}; "
            "expected research_v7_trainable_evidence_collection_v1")

    model = assessor["model"]
    keys = model["feature_keys"]
    thresholds, op_source = _resolve_operating_points(assessor["operating_points"])
    th95, th99 = thresholds["high_recall_95"], thresholds["high_recall_99"]
    predictor = LogisticAssessor(beta=model["beta"], mean=model["mean"], std=model["std"])
    predictor.frozen = True

    scores: list[float] = []
    pred95 = pred99 = 0
    gt_unsafe = labeled_units = n_rows = n_evidence = 0
    hit95 = hit99 = fp95 = fp99 = 0
    leak_keys: set[str] = set()
    label_errors: list[str] = []
    for t in collection.get("trainable_evidence", []):
        n_evidence += 1
        ev = json.loads(Path(t["path"]).read_text(encoding="utf-8"))
        attempt = ev.get("attempt") or {}
        gt, lerr = _labels_from_gt_eval(attempt)
        if lerr:
            label_errors.append(f"{t.get('request_identity')}: {lerr}")
        for row, row_i in _unit_rows(ev):
            n_rows += 1
            feats = unit_features(row)
            leak_keys.update(feature_extractor_blocked(feats)["leak"])
            xvec = _aligned_xvec(feats, keys)
            proba = float(predictor.predict_proba(np.asarray([xvec], dtype=float))[0])
            scores.append(proba)
            p95 = proba >= th95
            p99 = proba >= th99
            if p95:
                pred95 += 1
            if p99:
                pred99 += 1
            if gt is None:
                continue
            labeled_units += 1
            if row_i in gt:
                gt_unsafe += 1
                if p95:
                    hit95 += 1
                if p99:
                    hit99 += 1
            else:
                if p95:
                    fp95 += 1
                if p99:
                    fp99 += 1

    n_units = len(scores)
    correct_units = labeled_units - gt_unsafe  # FPR 分母：正确保留 unit（region_metrics 口径）
    fpr95 = round(fp95 / correct_units, 4) if correct_units else 0.0
    fpr99 = round(fp99 / correct_units, 4) if correct_units else 0.0
    if scores:
        s = np.asarray(scores)
        dist = {
            "min": round(float(s.min()), 6),
            "p50": round(float(np.percentile(s, 50)), 6),
            "p90": round(float(np.percentile(s, 90)), 6),
            "max": round(float(s.max()), 6),
        }
    else:
        dist = {"min": None, "p50": None, "p90": None, "max": None}

    return {
        "schema": SCHEMA,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "eval_domain": domain,
        "m4_assessor": {
            "operating_points": thresholds,
            "operating_points_source": op_source,
            "model_feature_keys": keys,
            "n_features": len(keys),
        },
        "mir1k": {
            "n_evidence": n_evidence,
            "n_rows": n_rows,
            "n_units": n_units,
            "n_units_labeled": labeled_units,
            "n_label_errors": len(label_errors),
            "n_gt_unsafe_units": gt_unsafe,
            "n_unsafe_pred_95": pred95,
            "n_unsafe_pred_99": pred99,
            "unsafe_rate_95": round(pred95 / n_units, 4) if n_units else 0.0,
            "unsafe_rate_99": round(pred99 / n_units, 4) if n_units else 0.0,
            "unit_recall_95": _recall(hit95, gt_unsafe, pred95, n_units),
            "unit_recall_99": _recall(hit99, gt_unsafe, pred99, n_units),
            "correct_unit_fpr_95": fpr95,
            "correct_unit_fpr_99": fpr99,
            "score_distribution": dist,
            "leak_check": {
                "ok": not leak_keys,
                "leak_keys": sorted(leak_keys),
                "n_units_checked": n_units,
            },
        },
        "gt_axis_note": GT_AXIS_NOTE,
        "note": (
            "MIR labels are weak supervision from qwen_fa timestamps, not human GT; "
            "M4 and MIR are reported separately and never merged into a single accuracy (13 §10.3); "
            f"eval_domain={domain} records the scored collection domain (schema keys m4_assessor/mir1k "
            "are fixed names)."
        ),
        "inputs": {
            "assessor": str(assessor_path.resolve()),
            "collection": str(collection_path.resolve()),
            "collection_domain": domain,
            "collection_sha256": collection_sha,
        },
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    # round13：泛化为任意域；--m4-assessor / --mir1k-collection 为旧名兼容别名（同一 dest）。
    p.add_argument("--assessor", "--m4-assessor", dest="assessor", required=True,
                   help="冻结 op 输出 ASSESSOR.json（须含 model.beta/mean/std/feature_keys）")
    p.add_argument("--collection", "--mir1k-collection", dest="collection", required=True,
                   help="guarded trainable evidence collection（research_v7_trainable_evidence_collection_v1）")
    p.add_argument("--domain", default="mir1k",
                   help="被打分 collection 的域标签（记录在输出 eval_domain；默认 mir1k）")
    p.add_argument("--out", required=True, help="输出目录（写 ASSESSOR_CROSS_DOMAIN_EVAL.json）")
    a = p.parse_args(argv)
    out = Path(a.out)
    try:
        result = evaluate(Path(a.assessor), Path(a.collection), domain=a.domain)
    except (ValueError, FileNotFoundError, json.JSONDecodeError) as e:
        # 确定性失败：原因写 stderr、退出码非 0（无 traceback）。
        # load_m4_assessor 的 (None, reason) 已转成 ValueError；
        # FileNotFoundError/JSONDecodeError 来自 collection/evidence 文件读取。
        print(f"error: {e}", file=sys.stderr)
        return 1
    out_file = out / OUTPUT_NAME
    _atomic_write(out_file, result)
    m = result["mir1k"]
    print(json.dumps({
        "ok": True,
        "schema": result["schema"],
        "operating_points_source": result["m4_assessor"]["operating_points_source"],
        "n_units": m["n_units"],
        "n_evidence": m["n_evidence"],
        "unsafe_rate_95": m["unsafe_rate_95"],
        "unsafe_rate_99": m["unsafe_rate_99"],
        "unit_recall_95": m["unit_recall_95"],
        "unit_recall_99": m["unit_recall_99"],
        "out": str(out_file),
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
