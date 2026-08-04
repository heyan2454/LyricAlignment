#!/usr/bin/env python3
"""阶段 B：run_behavior_suite —— 从 behavior_manifest 批量跑 alignment 行为用例。

对 manifest 每条（baseline/extra/missing/replace/no_match）构造 v7 AlignmentRequest，
支持 sparse-slot 骨架（slot mask），用可注入 executor 产出 EvidencePack 到 <out-root>/items。

用法：
  PYTHONPATH=src python scripts/research_v7/run_behavior_suite.py \
      --manifest <behavior_manifest.jsonl> --out-root runs/research_v7_align_behavior/run \
      --smoke                      # fake executor，纯 CPU 验证
  # 真模型：manifest 的 audio_path 必须指向存在的 vocal 文件。

每条 evidence identity 含 audio/text hash + mutation + mutation params，供 lineage/重放。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from lyricalign.research_v7.attempt import run_request
from lyricalign.research_v7.requests import AlignmentRequest


def _fake_executor(_req: object):
    import random

    rnd = random.Random(0)

    def ex(request: AlignmentRequest):
        from lyricalign.research_v7.attempt import AlignmentAttempt

        n = len(request.text_units)
        rows = [{"global_character_index": i,
                 "raw_global_start_sec": i * 0.5, "raw_global_end_sec": i * 0.5 + 0.4,
                 "fixed_global_start_sec": i * 0.5 - 0.02, "fixed_global_end_sec": i * 0.5 + 0.42,
                 "start_sec": i * 0.5, "end_sec": i * 0.5 + 0.4} for i in range(n)]
        fa = []
        if request.mutation_type == "no_match":
            fa = ["WRONG_REPEATED_SECTION"]
        elif request.mutation_type == "extra":
            fa = ["TAIL_COLLAPSE"]
        elif request.mutation_type == "missing":
            fa = ["GLOBAL_SHIFT"]
        return AlignmentAttempt(
            request=request, attempt_id=f"B-{request.item_id}-{request.mutation_type}",
            decoder_outputs={"official": {"rows": rows}, "raw": {"rows": rows}},
            cursor_after=float(n) * 0.5, committed=True, status="ok", fa_taxonomy=tuple(fa),
        )

    return ex


def hash_text(units):
    return hashlib.sha256("|".join(units).encode()).hexdigest()[:16]


def audio_range(duration_sec):
    return (0.0, float(duration_sec or 60.0))


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest", required=True)
    p.add_argument("--out-root", required=True)
    p.add_argument("--smoke", action="store_true")
    p.add_argument("--real", action="store_true", help="run frozen Qwen executor; requires manifest audio_path")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--model", default="Qwen3-ForcedAligner-0.6B-hf")
    p.add_argument("--checkpoint", default="r2-step-000750")
    p.add_argument("--checkpoint-path", help="local LoRA checkpoint directory; required with --real")
    p.add_argument("--model-dir")
    p.add_argument("--revision", default="main")
    p.add_argument("--resume", action="store_true", help="reuse only identity-identical evidence; reject mismatches")
    args = p.parse_args(argv)

    rows = [json.loads(l) for l in Path(args.manifest).read_text().splitlines() if l.strip()]
    if args.limit:
        rows = rows[: args.limit]

    if args.smoke == args.real:
        p.error("choose exactly one of --smoke or --real")
    if args.real:
        if not args.model_dir or not args.checkpoint_path:
            p.error("--real requires --model-dir and --checkpoint-path")
        from lyricalign.research_v7.real_executor import RealAligner, make_real_executor
        executor = make_real_executor(RealAligner(args.model_dir, args.revision, args.checkpoint_path))
    else:
        executor = _fake_executor(None)
    out_root = Path(args.out_root)
    written = 0
    cache_hit = 0
    forward = 0
    failures: list[dict] = []  # review5-4：实际错误聚合
    identities: list[dict] = []
    cursor_after_by_request: dict[str, float | None] = {}
    rows_after_by_request: dict[str, list[dict]] = {}
    import time as _time
    t_start = _time.time()
    for i, r in enumerate(rows):
        units = tuple(r.get("text_units", []))
        parent = r.get("parent_request_id")
        cursor_prev = cursor_after_by_request.get(parent) if parent else None
        # review3-1：若为 C3 生成的 WAV（提供 files），用 generated wav 作为 audio 源并重算窗口
        if r.get("files"):
            a0, a1 = 0.0, (r.get("duration_sec") or 0.0) if r.get("duration_sec") else (r.get("audio_end_sec", 60.0) - r.get("audio_start_sec", 0.0))
        else:
            a0, a1 = r.get("audio_start_sec", 0.0), r.get("audio_end_sec", r.get("duration_sec", 0.0) or 60.0)
        if r.get("workflow_mode") == "strict_serial_progressive_crop" and parent:
            if cursor_prev is None:
                # review7-1：serial 依赖失败的子请求 → 记 blocked_by_parent failure，批次继续，不中止
                failures.append({"item_id": r.get("item_id"), "request_id": r.get("request_id"),
                                 "status": "blocked_by_parent",
                                 "error": f"P2 requires completed parent cursor {parent}", "kind": "blocked_by_parent"})
                continue
            a0 = max(float(a0), float(cursor_prev) - float(r.get("left_context_sec", 10.0)))
        slot = tuple(r["timestamp_slot_indices"]) if r.get("timestamp_slot_indices") is not None else None
        # review7-1：构造 + validate（malformed row：非法 range/slot/text）也做 per-item 隔离
        try:
            if r.get("provisional_policy") == "last_predicted_seconds" and parent:
                previous_rows = rows_after_by_request.get(parent, [])
                cutoff = float(cursor_prev or 0.0) - float(r.get("provisional_last_sec", 0.0))
                recent = [int(row["global_character_index"]) for row in previous_rows if float(row.get("fixed_global_end_sec", 0.0)) > cutoff]
                source_start = int(r.get("source_text_start_index", 0))
                slot_start = min(recent) if recent else source_start
                slot = tuple(range(max(0, slot_start), len(units)))
            mutation = r.get("mutation_type", "baseline")
            req = AlignmentRequest(
                request_id=r.get("request_id") or f"{r['item_id']}:{mutation}:{r.get('ratio', 1.0)}:{r.get('position', 'whole')}:{i}",
                item_id=r.get("item_id", f"r{i}"),
                parent_request_id=r.get("parent_request_id"),
                audio_source=r.get("files")[0] if r.get("files") else (r.get("audio_path", "demucs_vocal")),
                audio_start_sec=a0,
                audio_end_sec=a1,
                text_source=r.get("text_source") or r.get("gt_path") or "labels",
                text_start_index=int(r.get("text_start_index", 0)),
                text_end_index=int(r.get("text_end_index", len(units))),
                text_units=units,
                timestamp_slot_indices=slot,
                workflow_mode=r.get("workflow_mode", "behavior_suite") or "behavior_suite",
                mutation_type=mutation or "baseline",
                mutation_parameters={key: r.get(key) for key in (
                    "ratio", "requested_ratio", "actual_ratio", "position", "mutation_position", "source", "text_relation",
                    "audio_relation", "source_text_start_index", "source_text_end_index", "baseline_unit_count", "n_base",
                    "actual_added_units", "actual_removed_units", "actual_replaced_units", "donor_song_id", "donor_start_index",
                    "donor_end_index", "donor_similarity", "selection_seed", "cursor_offset_units", "provisional_policy",
                    "provisional_tail_units", "provisional_last_sec", "c10_case", "repeat_gt_starts", "repeat_unit_count")},
                model_id=args.model,
                checkpoint_id=args.checkpoint,
                input_variant=r.get("input_variant", "text_mutation"),
                metadata={"dataset": r.get("dataset"), "split": r.get("split"),
                          "source_song_id": r.get("source_song_id") or r.get("song_id"),
                          "language": r.get("language") or "Chinese", "provenance": r.get("provenance", {}),
                          # review5-3：显式 condition/pair/target_ratio(供 evaluator 按 control/weak pairing 分层)
                          "condition": r.get("condition"), "pair_id": r.get("pair_id"),
                          "target_ratio": r.get("target_ratio"),
                          "evaluation_role": r.get("evaluation_role"),
                          "text_window_aligned": r.get("text_window_aligned", "unknown"),
                          "canonical_mapping": r.get("canonical_mapping", {})},
            )
            req.validate()
        except Exception as _ce:  # noqa
            # review7-1：构造/validate 失败 → malformed_row failure，跳过该 item 继续
            failures.append({"item_id": r.get("item_id"), "request_id": r.get("request_id"),
                             "status": "malformed_row", "error": str(_ce), "kind": "malformed_row"})
            continue
        item_dir = out_root / "items" / str(req.item_id)
        import hashlib as _hl
        try:
            audio_sha = _hl.sha256(Path(req.audio_source).read_bytes()).hexdigest() if (req.audio_source and Path(req.audio_source).is_file()) else "none"
            man_sha = next(iter(r.get("files_sha256") or []), None)
            if man_sha and man_sha != audio_sha:
                raise RuntimeError(f"audio drift: manifest files_sha256 {man_sha[:12]} != actual {audio_sha[:12]}")
            ctx = {
                "audio_content_sha256": audio_sha,
                "manifest_files_sha256": man_sha or audio_sha,
                "model": args.model, "checkpoint": args.checkpoint, "revision": args.revision,
                "decoder": r.get("decoder", "official"),
                "code_identity": _git_dirty(), "env_schema": "research_v7_long_slot_v1",
                "mapping_schema": "research_v7_canonical_mapping_v2",
                "source_request_identity": r.get("request_identity") or "",
            }
            content_idn = req.request_identity(context=ctx)
            cache_f = out_root / "cached" / f"{content_idn}.json"
            if cache_f.exists():
                if not args.resume:
                    raise FileExistsError(f"refusing to overwrite existing evidence: {cache_f}; use --resume")
                cached = json.loads(cache_f.read_text(encoding="utf-8"))
                if cached.get("content_identity") != content_idn:
                    raise RuntimeError(f"content identity mismatch under cache path for {content_idn[:16]}")
                prior_attempt = cached["attempt"]
                cursor_after_by_request[req.request_id] = prior_attempt.get("cursor_after")
                rows_after_by_request[req.request_id] = list(prior_attempt.get("decoder_outputs", {}).get("official", {}).get("rows", []))
                cache_hit += 1
                # review6-5：cache hit 若 status 非 ok → 也进 failures（保持 inventory/failed 一致）
                if prior_attempt.get("status") != "ok":
                    failures.append({"item_id": req.item_id, "request_id": req.request_id,
                                     "request_identity": content_idn, "status": prior_attempt.get("status"),
                                     "evidence_path": str(cache_f), "cache": "hit", "kind": "cached_error"})
                identities.append({"item_id": req.item_id, "request_id": req.request_id, "request_identity": content_idn,
                                   "cache": "hit", "status": prior_attempt.get("status"),
                                   "evaluation_role": r.get("evaluation_role"),
                                   "text_window_aligned": r.get("text_window_aligned")})
                continue
            ev = run_request(req, executor, cursor_prev=cursor_prev)
            payload = ev.to_dict()
            payload["content_identity"] = content_idn
            payload["audio_content_sha256"] = audio_sha
            # review6-3：evidence 唯一路径 = evidence/<attempt_identity>.json（人读 view 见 items/<item>/<idn>.json），不覆盖历史
            item_dir.mkdir(parents=True, exist_ok=True)
            f_author = out_root / "evidence" / f"{content_idn}.json"
            _atomic_write_text(f_author, payload)
            _atomic_write_text(item_dir / f"{content_idn}.json", payload)
            _atomic_write_text(cache_f, payload)
            cursor_after_by_request[req.request_id] = ev.attempt.cursor_after
            rows_after_by_request[req.request_id] = list(ev.attempt.decoder_outputs.get("official", {}).get("rows", []))
            written += 1
            forward += 1
            if ev.attempt.status != "ok":
                failures.append({"item_id": req.item_id, "request_id": req.request_id,
                                 "request_identity": content_idn, "status": ev.attempt.status,
                                 "evidence_path": str(f_author), "cache": "miss", "kind": "exec_error"})
            identities.append({"item_id": req.item_id, "request_id": req.request_id, "request_identity": content_idn,
                               "cache": "miss", "status": ev.attempt.status,
                               "evaluation_role": r.get("evaluation_role"),
                               "text_window_aligned": r.get("text_window_aligned")})
        except Exception as e:  # noqa
            # review6-4：per-item 失败不中止批次；记录 structured failure，继续其它独立 item
            failures.append({"item_id": req.item_id, "request_id": r.get("request_id") or req.request_id,
                             "request_identity": locals().get("content_idn") or None,
                             "status": "run_error", "error": str(e), "kind": "item_aborted"})

    # review3/4/6：真实运行产物 RUN_MANIFEST + FAILURES.jsonl（原子写）
    import hashlib as _hl2
    manifest_sha = _hl2.sha256(Path(args.manifest).read_bytes()).hexdigest()
    cached_dir = out_root / "cached"
    evidence_inv = []
    if cached_dir.exists():
        for c in sorted(cached_dir.glob("*.json")):
            try:
                cd = json.loads(c.read_text(encoding="utf-8"))
                evidence_inv.append({"path": str(c), "sha256": _hl2.sha256(c.read_bytes()).hexdigest(),
                                     "status": (cd.get("attempt") or {}).get("status")})
            except Exception:
                evidence_inv.append({"path": str(c), "sha256": None, "status": "unreadable"})
    # review6-2：按 evaluation_role 计数
    from collections import Counter as _C
    role_counts = _C(i.get("evaluation_role", "unknown") or "unknown" for i in identities) or {}
    # review7-3：训练/阈值/正式评价入口硬过滤（实际调用 guard，记拒绝清单与分母）
    try:
        from lyricalign.research_v7.evaluation_guard import require_trainable
        _tr = require_trainable([{**i, "text_window_aligned": i.get("text_window_aligned")} for i in identities])
        train_filter = {"trainable_identity_count": len(_tr["trainable"]), "rejected": _tr["rejected_count"]}
    except Exception as _ge:  # noqa
        train_filter = {"error": str(_ge)}
    run_manifest = {
        "schema": "research_v7_long_slot_v1",
        "run_id": f"rl-{_time.strftime('%Y%m%d_%H%M%S')}",
        "code_identity": {"git_commit": _git_head(), "source_tree": _git_dirty(),
                          # review6-6：实际 import 的 research_v7 模块文件 SHA（run 代码快照，含 untracked）。
                          "imports_sha256": _imports_hash()},
        "manifest": {"path": str(Path(args.manifest).resolve()), "sha256": manifest_sha},
        "untracked_inputs": [{"path": str(Path(args.manifest).resolve()), "sha256": manifest_sha}],
        "environment": {"model": args.model, "revision": args.revision, "checkpoint": args.checkpoint,
                        "device": getattr(args, "device", "cuda" if args.real else "cpu"),
                        "executor": "real" if args.real else "fake-smoke"},
        "runtime_budget": {"elapsed_sec": round(_time.time() - t_start, 3), "forward_count": forward,
                           "cache_hit": cache_hit, "cache_miss": forward, "cache_total": cache_hit + forward},
        "item_count": {"requests": len(rows), "written": written, "cache_hit": cache_hit, "forward": forward,
                       "failed": len(failures), "role": dict(role_counts)},
        "train_filter": train_filter,
        "cache_keys": [i["request_identity"] for i in identities],
        "evidence_inventory": evidence_inv,
        "failures": failures,
        "requests_identity": identities,
    }
    # review6-4：原子写 RUN_MANIFEST + FAILURES.jsonl（临时文件+replace）；失败不结束仍产出
    _atomic_write_text(out_root / "RUN_MANIFEST.json", run_manifest)
    import json as _jf
    fd, tmp = _mkstemp(out_root)
    import os as _os2
    with _os2.fdopen(fd, "w") as _f:  # 关闭 fd
        for fa in failures:
            _f.write(_jf.dumps(fa, ensure_ascii=False) + "\n")
        _f.flush(); _os2.fsync(_f.fileno())
    _os2.replace(tmp, out_root / "FAILURES.jsonl")
    print(json.dumps({"ok": True, "rows": len(rows), "written": written,
                      "cache_hit": cache_hit, "forward": forward, "failed": len(failures),
                      "out_root": str(out_root), "executor": "real" if args.real else "fake-smoke",
                      "schema_version": "research_v7_long_slot_v1"}, ensure_ascii=False))
    return 0


def _mkstemp(out_root):
    import tempfile
    out_root.mkdir(parents=True, exist_ok=True)
    fd, path = tempfile.mkstemp(dir=str(out_root), suffix=".tmp")
    return fd, path


def _atomic_write_text(target, payload) -> None:
    """review7-6：fsync + 原子替换写入 JSON；返回前关闭 fd。"""
    import json as _j
    import os as _o
    import tempfile as _tf
    from pathlib import Path as _P
    t = _P(target); t.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = _tf.mkstemp(dir=str(t.parent), suffix=".tmp")
    try:
        with _o.fdopen(fd, "w") as fh:  # os.fdopen 关闭 fd
            _j.dump(payload, fh, ensure_ascii=False, indent=1)
            fh.flush(); _o.fsync(fh.fileno())
        _o.replace(tmp, t)
    finally:
        try:
            if _o.path.exists(tmp): _o.unlink(tmp)
        except Exception:
            pass



def _git_head() -> str:
    import subprocess
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    except Exception:  # noqa
        return ""


def _git_dirty() -> str:
    """source-tree identity：HEAD commit + staged diff + unstaged 工作树 diff 的内容 hash。

    review4/5：git write-tree 只代表 index，不覆盖未暂存工作树改动 → 需三条分别哈希。
    """
    import hashlib
    import subprocess

    def _h(*parts):
        return hashlib.sha256(b":".join((p if isinstance(p, bytes) else p.encode()) for p in parts)).hexdigest()

    def _diff_tree(_base="_git_dirty"):
        # staged diff: index vs HEAD (write-tree vs HEAD^tree)，即 git diff --cached 的内容
        return subprocess.run(["git", "diff", "--cached"], capture_output=True, text=True).stdout or ""
    def _diff_work():
        return subprocess.run(["git", "diff"], capture_output=True, text=True).stdout or ""
    try:
        head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        staged = _diff_tree()
        unstaged = _diff_work()
    except Exception:  # noqa
        return hashlib.sha256(b"unknown").hexdigest()
    return _h(head, staged, unstaged)


def _imports_hash() -> str:
    """实际参与本次运行的 research_v7 代码文件 SHA 摘要（含 untracked；供 RUN_MANIFEST。）。"""
    import hashlib
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    files = sorted((root / "src" / "lyricalign" / "research_v7").glob("*.py"))
    files.append(Path(__file__).resolve())
    parts = []
    for f in files:
        try:
            parts.append(f"{f.name}:{hashlib.sha256(f.read_bytes()).hexdigest()}")
        except Exception:
            continue
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
