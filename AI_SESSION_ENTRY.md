# AI Session Entry

本文件是 GPT / Codex / 其他 AI 的固定入口，只负责导航、当前事实和强约束。

## 必读顺序

1. `README.md`
2. `docs/status/project_current.md`
3. `docs/sessions/20260723_qwen_fa_lora_full_r2_archive.md`
4. `reports/progress/20260723_qwen_fa_lora_results.md`
5. `docs/status/next_execution_plan.md`
6. `docs/principles.md`
7. `docs/sessions/SESSION_INDEX.md`

## 当前阶段

```text
R2 full training complete
-> retain existing M4Singer sealed-test result
-> run missing full-R2 MIR-1K OOD with frozen validation-best checkpoint
-> verify evaluation identity
-> close report/session and push Git
```

## 已确认结果

- R0 raw validation song-macro boundary MAE：169.925 ms；
- R1 projector-only：90.823 ms @100，65.699 ms @200；
- R2 top-half audio LoRA + projector：55.247 ms @100；
- R3 all-layer audio LoRA + projector：61.078 ms @100；
- full R2：1,110 optimizer steps；final validation 46.634 ms；
- `best_checkpoint.json`：step 1000，46.734 ms；
- full R2 M4Singer sealed test：79.590 ms song-macro MAE；
- full R2 MIR-1K OOD：尚缺；现有 39.671 ms OOD 是 pilot 结果。

## 数据身份

- M4Singer accepted-only weak supervision：20,298；598 review 全部排除；
- M4Singer canonical manifest SHA-256：`22828f809e60cfaeb44f0fec973d7ce5b026fd024d0740b9120725f012d6053a`；
- MIR-1K OOD manifest SHA-256：`bd8109d608247b78407c1d63e9f648b83f697a00c5c0b05b3fe93c87b42c884f`；
- MIR-1K character SHA-256：`78d7054ada0a3fb5ec3cd916174d094d78ab5d96f67d0112408de30dc24469c9`。

## 强约束

- 不重复运行已有 M4Singer sealed test；
- sealed test/OOD 不得参与 checkpoint 反选；
- final OOD 必须使用 `best_checkpoint.json` 指向的 validation-best checkpoint，除非先以独立 validation-only 决策文件明确改变选择；
- 旧 `20260723_qwen_fa_r2_mir1k_ood` 是 pilot，不得改名或覆盖为 full；
- final OOD 使用新目录 `20260723_qwen_fa_r2_full_mir1k_ood`；
- 运行前校验 checkpoint、MIR-1K manifest 和 character JSONL hash；
- 输出必须记录 checkpoint adapter/projector/hash、数据 hash、split 与 usage；
- checkpoint、音频和 predictions 不进入 Git/archive；
- `rule_validated` 不等同于人工高置信 GT。

## 唯一手动入口

```bash
conda activate lyricalign-qwen
bash scripts/training/finalize_qwen_fa_r2_manual.sh inspect
bash scripts/training/finalize_qwen_fa_r2_manual.sh run-ood
bash scripts/training/finalize_qwen_fa_r2_manual.sh summarize
```
