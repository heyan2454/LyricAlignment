# Next Actions（按优先级）

1. **PJS phoneme-level GT 评测**
   - 需要将 PJS lab phoneme 时间与日语 word-unit 对齐建立可复现映射
   - 目标：量化 raw decoder 在日语上的真实收益

2. **MIR-MLPop / JamendoLyrics vocal 派生**
   - 使用 demucs/现有分离环境生成 vocal-only
   - 记录 separator identity/config/hash
   - 然后跑自然流行混音评测

3. **R-U/R-S/R-CF recovery 机制消融**
   - 在 GTSinger hard-case 子清单上接入 unit_realign
   - 对比 raw decoder 与 recovery 机制是否互补

4. **Sealed milestone 正式评测**
   - 用 `guarded_run.py --allow-sealed` 包装
   - 仅 milestone 运行，结果单独报告

5. **产品化 gate 实现**
   - zero-duration / overlap / timestamp regression 自动门禁
   - speech-like input 单独阈值
