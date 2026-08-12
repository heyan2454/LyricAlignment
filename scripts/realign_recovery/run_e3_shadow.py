#!/usr/bin/env python3
"""E3 frozen-baseline detector-shadow 离线发现（WP C2，纯 CPU，不发起 GPU forward）。

输入（均为 research_transition_recovery_detector 上游 stage3b 产物）：
- --evidence-v2-dir  evidence_v2/*.jsonl（每文件 = 一个 request 的 EvidenceRow 列表，
  文件名 sha256:<digest>.jsonl）
- --labels           LABELS.jsonl（每行 request_identity/canonical_unit_id/target/
  label/family/split/song_id；train 行用于拟合冻结模型，eval 行不参与打分输入）
- --frozen-op        FROZEN_OPERATING_POINTS.json
- --items-dir        items/ 目录（目录名 <song>:<wi>:<family>:<view>，内部 sha 文件，
  提供 sha256 -> (song, window_index, view) 的解析）

流程：
1. 解析 items 目录获得 (song, wi, view) -> sha256 映射；
2. 用 LABELS(train, 指定 target) 行的 label join 对应 evidence 文件行，拟合
   FrozenScorer（detector_v2_features 全链，CPU）；
3. 对每首歌每个窗口的 full 视图（view 名以 ":full" 结尾且不含 "missing"）evidence
   score() 得 detector_shadow，写 baseline.jsonl；
4. discover_catastrophic_commits 输出每首歌 first catastrophic window + 1/2/3/5
   continuation，写 E3_CATASTROPHIC_COMMITS.json。

shadow-only：不读 GT（label 仅训练时消费，评分离线）。--dry-run 只做步骤 1--2。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from lyricalign.realign_recovery.catastrophic_commit import (  # noqa: E402
    discover_catastrophic_commits,
)
from lyricalign.realign_recovery.frozen_scorer import (  # noqa: E402
    build_frozen_scorer,
)

_ITEM_RE = re.compile(r"^(?P<song>.+?):(?P<wi>w\d+):(?P<view>.+)$")


def _parse_items(items_dir: Path):
    """items/<song>:<wi>:<view>/sha256:<digest>.json -> (song, wi, view, digest)。"""
    mapping: list[dict] = []
    if not items_dir.is_dir():
        return mapping
    for d in sorted(items_dir.iterdir()):
        if not d.is_dir():
            continue
        m = _ITEM_RE.match(d.name)
        if not m:
            continue
        for f in sorted(d.iterdir()):
            if not f.name.endswith(".json"):
                continue
            digest = f.stem
            mapping.append({
                "song_id": m.group("song"),
                "window_index": int(m.group("wi")[1:]),
                "view": m.group("view"),
                "digest": digest,
            })
    return mapping


def _load_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        if isinstance(obj, list):
            rows.extend(obj)
        elif isinstance(obj, dict):
            rows.append(obj)
    return rows


def _join_train_evidence(labels_path: Path, evidence_dir: Path, target: str):
    """LABELS(train, target) -> (request_identity, canonical_unit_id) -> label。"""
    labels = {}
    for row in _load_jsonl(labels_path):
        if row.get("split") != "train":
            continue
        if row.get("target") != target:
            continue
        rid = row.get("request_identity")
        cid = row.get("canonical_unit_id")
        if rid is None or cid is None:
            continue
        labels[(rid, int(cid))] = row.get("label")
    return labels


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--evidence-v2-dir", required=True)
    p.add_argument("--labels", required=True)
    p.add_argument("--frozen-op", required=True)
    p.add_argument("--items-dirs", required=True, nargs="+", help="一个或多个 items/ 目录")
    p.add_argument("--out-root", required=True)
    p.add_argument("--target", default="raw", choices=("raw", "official"))
    p.add_argument("--model-kind", default="standardized_logistic")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)

    evidence_dir = Path(args.evidence_v2_dir)
    labels_path = Path(args.labels)
    frozen_op = Path(args.frozen_op)
    out_root = Path(args.out_root) / args.target
    out_root.mkdir(parents=True, exist_ok=True)

    items: list[dict] = []
    for it_dir in args.items_dirs:
        items.extend(_parse_items(Path(it_dir)))
    if not items:
        raise SystemExit(f"items 解析为空: {args.items_dirs}")
    print(f"items 解析: {len(items)} 条")

    train_labels = _join_train_evidence(labels_path, evidence_dir, args.target)
    if not train_labels:
        raise SystemExit(f"target={args.target} train 标签为空，检查 LABELS split/target 列")
    print(f"train 标签: {len(train_labels)}（target={args.target}）")

    # evidence 文件 -> 行 dict
    evidence_cache: dict[str, list[dict]] = {}
    for f in evidence_dir.glob("*.jsonl"):
        digest = f.stem
        rows = _load_jsonl(f)
        if rows:
            evidence_cache[digest] = rows
    print(f"evidence 文件: {len(evidence_cache)}")

    # 训练集：train label 行 join evidence 行
    train_rows = []
    for item in items:
        digest = item["digest"]
        if digest not in evidence_cache:
            continue
        for row in evidence_cache[digest]:
            cid = row.get("canonical_unit_id")
            key = (digest, int(cid)) if cid is not None else None
            if key in train_labels:
                merged = dict(row)
                merged["label"] = train_labels[key]
                train_rows.append(merged)
    if not train_rows:
        raise SystemExit("train rows 为空，检查 digest 与 evidence 文件名是否匹配")
    print(f"train rows: {len(train_rows)}")

    scorer = build_frozen_scorer(
        frozen_op, train_rows, model_kind=args.model_kind, target=args.target)
    print(f"FrozenScorer 就绪: target={args.target} model_kind={args.model_kind}")

    if args.dry_run:
        print("dry-run 结束（未写 baseline.jsonl / commits）")
        return 0

    # 每首歌每窗口：full 视图 evidence -> shadow
    by_key = defaultdict(list)
    for item in items:
        view = item["view"]
        if view != "full" or "missing" in view:
            continue
        digest = item["digest"]
        if digest not in evidence_cache:
            continue
        by_key[(item["song_id"], item["window_index"])].append((item, digest))

    baseline = []
    for (song, wi), pairs in sorted(by_key.items()):
        pairs.sort(key=lambda kv: kv[0]["view"])
        for item, digest in pairs:
            rows = evidence_cache[digest]
            unit_ids = sorted(
                int(r.get("canonical_unit_id", 0)) for r in rows)
            shadow = scorer.score(rows)
            baseline.append({
                "id": f"{song}:w{wi}:{item['view']}",
                "song_id": song,
                "window_index": wi,
                "view": item["view"],
                "request_identity": digest,
                "window": {"text_unit_ids": unit_ids},
                "detector_shadow": shadow,
                "n_units": shadow.get("n_units", 0),
                "decision": shadow.get("decision", "accept"),
            })

    baseline_path = out_root / "baseline.jsonl"
    with open(baseline_path, "w", encoding="utf-8") as fh:
        for row in baseline:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"baseline rows: {len(baseline)} -> {baseline_path}")

    commits = discover_catastrophic_commits(baseline_path)
    commits_path = out_root / "E3_CATASTROPHIC_COMMITS.json"
    with open(commits_path, "w", encoding="utf-8") as fh:
        json.dump({"target": args.target, "commits": commits},
                  fh, ensure_ascii=False, indent=1)
    print(f"catastrophic commits: {len(commits)} -> {commits_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
