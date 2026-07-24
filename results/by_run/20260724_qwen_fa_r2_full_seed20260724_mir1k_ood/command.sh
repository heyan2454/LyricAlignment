cd "/home/hyan/LyricAlignment"
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONUNBUFFERED=1 \
"/root/autodl-tmp/AST_storage/conda/envs/lyricalign-qwen/bin/python" scripts/training/evaluate_qwen_fa_checkpoint.py \
  --model "/root/autodl-tmp/AST_storage/Data/lyricalign/models/hf_cache/models--Qwen--Qwen3-ForcedAligner-0.6B-hf/snapshots/c07281df297b9905d24a508279258cccf987a064" \
  --revision "c07281df297b9905d24a508279258cccf987a064" \
  --checkpoint-kind lora \
  --checkpoint "/home/hyan/Data/lyricalign/runs/20260724_qwen_fa_r2_full_seed20260724/checkpoints/step-000750" \
  --labels "/home/hyan/Data/lyricalign/derived/20260724_mir1k_qwen_fa_labels_v1/mir1k_qwen_fa_labels.jsonl" \
  --characters "/home/hyan/Data/lyricalign/derived/20260722_mir1k_vocal_channel1_ood/mir1k_vocal_ood_characters.jsonl" \
  --audio-root "/home/hyan/Data/lyricalign/derived/20260722_mir1k_vocal_channel1_ood" \
  --out-dir "/home/hyan/Data/lyricalign/runs/20260724_qwen_fa_r2_full_seed20260724_mir1k_ood.tmp.20260724_200123.813811" \
  --split "test" \
  --batch-size "4" \
  --device "cuda" \
  --local-files-only \
  --evaluation-role "full_r2_seed20260724_mir1k_ood"
