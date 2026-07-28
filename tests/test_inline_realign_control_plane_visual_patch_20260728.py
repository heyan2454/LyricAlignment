from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest
import yaml

from lyricalign.demo.run_state import RunState
from lyricalign.demo.visual_diagnostics import ordered_rows


ROOT = Path(__file__).resolve().parents[1]


def load_script(name: str, relative: str):
    path = ROOT / "scripts" / "demo" / relative
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_visual_rows_project_stage_specific_global_timing() -> None:
    rows = ordered_rows([
        {
            "global_character_index": 0,
            "character": "日",
            "fixed_global_start_sec": 1.25,
            "fixed_global_end_sec": 1.50,
        }
    ])
    assert rows[0]["start_sec"] == pytest.approx(1.25)
    assert rows[0]["end_sec"] == pytest.approx(1.50)
    assert rows[0]["visual_timing_source"] == "fixed_global"


def test_visual_realign_spans_accept_context_rows_without_canonical_time(tmp_path: Path) -> None:
    module = load_script("inline_visual_context_schema_patch", "analyze_inline_realign_visuals.py")
    item_root = tmp_path / "item"
    item_root.mkdir()
    (item_root / "inline_realign_shadow.json").write_text(json.dumps({
        "decisions": [{
            "audio_start_sec": 0.0,
            "audio_end_sec": 2.0,
            "candidate_source": "automatic_precommit",
            "context_trials": {
                "exact": {
                    "decoded_rows": [{
                        "global_character_index": 0,
                        "character": "語",
                        "fixed_global_start_sec": 0.2,
                        "fixed_global_end_sec": 0.4,
                    }]
                }
            },
        }]
    }), encoding="utf-8")
    spans, cases = module.realign_spans(item_root)
    assert len(cases) == 1
    assert spans[0]["start_sec"] == pytest.approx(0.0)
    assert spans[0]["end_sec"] == pytest.approx(2.0)


def test_finish_item_refuses_complete_when_output_missing(tmp_path: Path) -> None:
    state = RunState(tmp_path)
    output = tmp_path / "missing.json"
    request_hash = state.begin_item("x", request={"item": "x"}, outputs=[output])
    with pytest.raises(FileNotFoundError, match="refusing to mark item"):
        state.finish_item("x", status="complete", request_hash=request_hash, outputs=[output])
    payload = json.loads(state.item_path("x").read_text(encoding="utf-8"))
    assert payload["status"] == "running"
    state.finish_item(
        "x", status="failed", request_hash=request_hash, outputs=[output], error="missing output"
    )
    payload = json.loads(state.item_path("x").read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    assert payload["outputs_present"] is False


def test_force_resume_never_skips_complete_item() -> None:
    module = load_script("inline_experiment_force_resume_patch", "run_inline_realign_experiment.py")
    assert module.can_resume_skip_item(
        resume=True, force=False, item_id="x", restart_items=set(), complete_and_valid=True
    )
    assert not module.can_resume_skip_item(
        resume=True, force=True, item_id="x", restart_items=set(), complete_and_valid=True
    )


def test_experiment_invalidation_requests_force() -> None:
    module = load_script("inline_pipeline_invalidate_patch", "run_inline_realign_pipeline.py")
    assert module.experiment_force_requested(force=False, invalidated_stages=["experiment"])
    assert module.experiment_force_requested(force=True, invalidated_stages=[])
    assert not module.experiment_force_requested(force=False, invalidated_stages=["visualization"])


def test_smoke_config_selects_one_demo_per_language() -> None:
    payload = yaml.safe_load(
        (ROOT / "configs/experiments/inline_realign_multilingual_smoke_20260728.yaml").read_text(
            encoding="utf-8"
        )
    )
    assert payload["selection"]["demo_policy"] == "one_per_discovered_language_when_available"
    assert payload["selection"]["demo_per_language_cap"] == 1


def test_missing_demo_root_fails_before_wrapper_launch(tmp_path: Path) -> None:
    repo = ROOT
    python_bin = tmp_path / "python"
    python_bin.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    python_bin.chmod(0o755)
    model = tmp_path / "model"
    model.mkdir()
    for name in ("model.safetensors", "config.json", "tokenizer_config.json", "processor_config.json"):
        (model / name).write_bytes(b"x")
    checkpoint = tmp_path / "checkpoint"
    (checkpoint / "adapter").mkdir(parents=True)
    for name in ("projector.pt", "adapter/adapter_model.safetensors", "adapter/adapter_config.json"):
        (checkpoint / name).write_bytes(b"x")
    m4_audio = tmp_path / "m4_audio"
    m4_audio.mkdir()
    m4_labels = tmp_path / "m4.jsonl"
    m4_labels.write_text("{}\n", encoding="utf-8")
    mir = tmp_path / "mir"
    mir.mkdir()
    (mir / "selection.jsonl").write_text("{}\n", encoding="utf-8")
    missing_demo = tmp_path / "missing_demo"
    command = f'''
set +e
export REPO_ROOT={repo!s}
export PYTHON_BIN={python_bin!s}
export MODEL_SOURCE={model!s}
export R2_CHECKPOINT={checkpoint!s}
export M4_AUDIO_ROOT={m4_audio!s}
export M4_LABELS={m4_labels!s}
export MIR1K_SUBSET_ROOT={mir!s}
export DEMO_ROOT={missing_demo!s}
source {repo / "scripts/demo/inline_realign_env.sh"}
validate_inline_realign_inputs
exit $?
'''
    result = subprocess.run(["bash", "-lc", command], text=True, capture_output=True)
    assert result.returncode == 2
    assert "smoke/formal wrappers require Demo input" in result.stderr


def test_collection_creates_nested_state_destination_parents(tmp_path: Path) -> None:
    module = load_script("inline_collection_nested_state_patch", "collect_inline_realign_evidence.py")
    root = tmp_path / "run"
    staging = tmp_path / "staging"
    (root / "state" / "items").mkdir(parents=True)
    staging.mkdir()
    (root / "experiment_summary.json").write_text("{}\n", encoding="utf-8")
    state_payload = {"status": "complete", "item_id": "demo_Cantonese_乙女解剖_0aca89e7"}
    source = root / "state" / "items" / "demo_Cantonese_乙女解剖_0aca89e7.json"
    source.write_text(json.dumps(state_payload, ensure_ascii=False), encoding="utf-8")

    metadata = module.collect(root, staging, mode="minimal", max_cases=1)

    copied = staging / "state" / "items" / source.name
    assert copied.is_file()
    assert json.loads(copied.read_text(encoding="utf-8")) == state_payload
    assert metadata["item_count"] == 0
