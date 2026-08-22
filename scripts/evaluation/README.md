# Evaluation V1 Scripts

No-training productization research helpers. All scripts are CPU-only by default
and write small JSON/JSONL/Markdown outputs under `/home/hyan/Data/lyricalign/runs/...`.

| Script | Purpose |
|---|---|
| `build_evaluation_v1_split_manifest.py` | Build grouped song-level `diagnostic_visible/regression_selection/sealed_final` draft manifest from newly acquired datasets. |
| `check_split_access.py` | Gate runner access to a manifest; refuses `sealed_final` unless `--allow-sealed`. |
| `audit_new_datasets.py` | Read-only readiness audit of new dataset payloads (audio counts, metadata completeness, vocal-only status). |
| `freeze_baseline_identity.py` | Record repo commit, model/checkpoint defaults, and Python environment as a CPU-only baseline identity. |
| `summarize_evaluation_v1_manifest.py` | Render a human-readable summary of an Evaluation V1 split manifest. |
| `filter_manifest.py` | Filter a manifest to runnable tiers; refuses sealed unless `--allow-sealed`. |
| `build_vocal_derivation_plan.py` | Plan raw-mixture -> vocal derivation outputs without running separation. |
| `build_behavior_registry.py` | Generate a machine-readable single-factor behavior registry for productization research. |
| `build_dataset_compatibility.py` | Generate a dataset compatibility matrix from a split manifest. |
| `build_gtsinger_lyrics.py` | Generate plain-text lyrics from GTSinger JSON for the existing demo pipeline. |
| `summarize_alignment_smoke.py` | Summarize serial-demo alignment smoke runs (zero durations, intervals, structural status). |
| `evaluate_gtsinger_alignment.py` | Evaluate a single GTSinger alignment against JSON word-level GT. |
| `evaluate_gtsinger_batch.py` | Evaluate a batch of GTSinger smoke subdirs against a GT map. |
| `build_gtsinger_diagnostic_manifest.py` | Build a runnable GTSinger diagnostic manifest (audio/GT/lyrics mapping). |
| `run_gtsinger_diagnostic_batch.py` | Run the GTSinger diagnostic manifest through the serial demo, resumable. |
| `aggregate_gtsinger_batch_results.py` | Combine r0/r1/r2 batch evaluation JSONs into one summary. |
| `build_operational_input_manifest.py` | Build raw-mixture operational input manifest for MIR/Jamendo. |
| `build_mir_mlpop_lyrics.py` | Extract a lyric slice from MIR-MLPop JSON for short raw-mixture smokes. |
| `build_pjs_manifest.py` | Build PJS manifest with phoneme counts, durations, and Evaluation V1 tier. |
| `build_pjs_lyrics.py` | Extract Japanese lyric text from PJS MusicXML for alignment smoke. |
| `guarded_run.py` | Run a command only if the manifest access policy allows it (sealed gate). |
| `run_quality_checks.sh` | Run tests, compile, diff check, and cleanup-report audit. |
| `compare_gtsinger_official_vs_rawdec.py` | Compare two GTSinger batch evaluation JSONs (e.g., official vs raw decoder). |
| `run_regression_rawdec_compare.sh` | Reproduce GTSinger regression raw decoder run and evaluation. |
| `summarize_quality_warnings.py` | Summarize alignment quality status/warnings for a batch root. |
| `run_productization_alignment.sh` | Productization alignment entry: R2 + raw decoder by default. |
| `check_alignment_quality_gate.py` | Check alignment JSON against zero-duration/overlap/regression gates. |

`run_gtsinger_diagnostic_batch.py` supports `--extra=--flag` to pass extra serial-demo flags for mechanism ablation.

## Example commands

```bash
# Build draft split (external data dir)
python scripts/evaluation/build_evaluation_v1_split_manifest.py \
  --out-root /home/hyan/Data/lyricalign/runs/20260816_evaluation_v1_split_draft \
  --datasets-root /home/hyan/Data/datasets

# Gate a run against sealed access
python scripts/evaluation/check_split_access.py \
  --manifest /home/hyan/Data/lyricalign/runs/20260816_evaluation_v1_split_draft/evaluation_v1_split_manifest.jsonl
# -> exits 2 unless --allow-sealed is passed

# Audit new dataset readiness
python scripts/evaluation/audit_new_datasets.py \
  --out-root /home/hyan/Data/lyricalign/runs/20260816_evaluation_v1_datasets_audit

# Freeze baseline identity
python scripts/evaluation/freeze_baseline_identity.py \
  --out-root /home/hyan/Data/lyricalign/runs/20260816_evaluation_v1_baseline_identity
```

All outputs include a `cleanup_report.md` so each batch can be removed safely.

## GTSinger smoke example

```bash
# Generate lyrics from a GTSinger JSON
python scripts/evaluation/build_gtsinger_lyrics.py \
  --json /home/hyan/Data/datasets/gtsinger_chinese/raw/extracted/selected_data/Chinese/ZH-Tenor-1/Glissando/倒带/Control_Group/0000.json \
  --out /home/hyan/Data/lyricalign/runs/20260816_evaluation_v1_gtsinger_smoke/lyrics.txt \
  --join-lines

# Run existing serial demo (R0/R1/R2) on the vocal WAV
PYTHONPATH=src python scripts/demo/align_qwen_fa_serial_demo.py \
  --lyrics /home/hyan/Data/lyricalign/runs/20260816_evaluation_v1_gtsinger_smoke/lyrics.txt \
  --mix-audio /home/hyan/Data/datasets/gtsinger_chinese/raw/extracted/selected_data/Chinese/ZH-Tenor-1/Glissando/倒带/Control_Group/0000.wav \
  --vocal-audio /home/hyan/Data/datasets/gtsinger_chinese/raw/extracted/selected_data/Chinese/ZH-Tenor-1/Glissando/倒带/Control_Group/0000.wav \
  --out-root /home/hyan/Data/lyricalign/runs/20260816_evaluation_v1_gtsinger_smoke \
  --model /root/autodl-tmp/AST_storage/Data/lyricalign/models/hf_cache/models--Qwen--Qwen3-ForcedAligner-0.6B-hf/snapshots/c07281df297b9905d24a508279258cccf987a064 \
  --revision c07281df297b9905d24a508279258cccf987a064 \
  --r1-checkpoint /home/hyan/Data/lyricalign/runs/20260724_qwen_fa_r1_full_seed3407/checkpoints/step-000750 \
  --r2-checkpoint /home/hyan/Data/lyricalign/runs/20260724_qwen_fa_r2_full_seed20260724/checkpoints/step-000750 \
  --device cuda --language Chinese \
  --core-sec 20 --left-context-sec 0 --right-context-sec 0 \
  --minimum-forward-characters 1 --startup-minimum-forward-characters 1 \
  --future-line-padding 0 --future-character-ratio 1.0 --max-candidate-expansions 0
```
