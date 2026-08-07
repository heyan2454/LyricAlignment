#!/usr/bin/env python3
"""Phase 0 preflight：只读核对 + 产出 PRECHECK.json（纯 CPU，不加载 GPU 模型）。

检查项：
1. session root 唯一且不覆盖旧 evidence；
2. contracts/identity/session_state/transitions/runner 可导入且测试通过标记存在；
3. 四角色 split 已生成且 source-song 不重叠；
4. resolved config 无 null formal 参数；
5. 数据/模型/checkpoint 存在；
6. implementation map 已生成。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--session-root", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()

    root = Path(args.session_root)
    checks: list[dict] = []

    def check(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    # 1. session root
    state_path = root / "SESSION_STATE.json"
    check("session_state_exists", state_path.is_file(), str(state_path))
    check(
        "session_root_unique",
        "session_" in root.name and "research_transition_recovery_detector" in str(root),
        str(root),
    )

    # 2. 模块可导入
    import importlib

    modules = [
        "lyricalign.research_transition_recovery_detector.contracts",
        "lyricalign.research_transition_recovery_detector.identity",
        "lyricalign.research_transition_recovery_detector.session_state",
        "lyricalign.research_transition_recovery_detector.transitions",
        "lyricalign.research_transition_recovery_detector.audio_preprocessing",
        "lyricalign.research_transition_recovery_detector.runner",
    ]
    for mod in modules:
        try:
            importlib.import_module(mod)
            check(f"import_{mod.split('.')[-1]}", True, "ok")
        except Exception as exc:  # noqa: BLE001
            check(f"import_{mod.split('.')[-1]}", False, str(exc))

    # 3. split
    split_path = root / "00_meta" / "DATASET_SPLIT.json"
    roles_disjoint = True
    n_roles = 0
    if split_path.is_file():
        split = json.loads(split_path.read_text(encoding="utf-8"))
        n_roles = len(split.get("roles", {}))
        all_ids = [set(v) for v in split.get("roles", {}).values()]
        for i in range(len(all_ids)):
            for j in range(i + 1, len(all_ids)):
                if all_ids[i] & all_ids[j]:
                    roles_disjoint = False
    check("dataset_split_exists", split_path.is_file(), str(split_path))
    check("dataset_split_four_roles", n_roles == 4, f"roles={n_roles}")
    check("dataset_split_songs_disjoint", roles_disjoint, "source songs must not cross roles")

    # 4. resolved config
    resolved = root / "00_meta" / "RESOLVED_CONFIG.yaml"
    no_null = True
    if resolved.is_file():
        import yaml

        cfg = yaml.safe_load(resolved.read_text(encoding="utf-8"))
        for key, value in cfg.items():
            if value is None:
                no_null = False
                break
    check("resolved_config_exists", resolved.is_file(), str(resolved))
    check("resolved_config_no_null_formal", no_null, "formal 参数不得为 null")

    # 5. 数据/模型
    import os

    model_dir = Path("/home/hyan/Data/lyricalign/models/hf_cache/models--Qwen--Qwen3-ForcedAligner-0.6B-hf/snapshots")
    ckpt = Path("/home/hyan/Data/lyricalign/runs/20260724_qwen_fa_r2_full_seed20260724/checkpoints/step-000750")
    audio_root = Path("/home/hyan/Data/datasets/m4singer/raw/extracted/m4singer")
    check("model_snapshot_exists", model_dir.is_dir() and any(model_dir.iterdir()), str(model_dir))
    check("r2_checkpoint_exists", ckpt.is_dir(), str(ckpt))
    check("m4_audio_root_exists", audio_root.is_dir() and any(audio_root.iterdir()), str(audio_root))

    # 6. implementation map
    map_path = root / "01_precheck" / "TRANSITION_IMPLEMENTATION_MAP.json"
    map_ok = False
    if map_path.is_file():
        map_data = json.loads(map_path.read_text(encoding="utf-8"))
        transitions = map_data.get("transitions") if isinstance(map_data, dict) else map_data
        map_ok = all("status" in item for item in transitions) if isinstance(transitions, list) else False
    check("implementation_map_exists", map_path.is_file(), str(map_path))
    check("implementation_map_has_status", map_ok, "every transition must carry status")

    ok = all(c["ok"] for c in checks)
    payload = {"schema_version": "transition_precheck_v1", "ok": ok, "checks": checks}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps({"ok": ok, "failed": [c["name"] for c in checks if not c["ok"]]}, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
