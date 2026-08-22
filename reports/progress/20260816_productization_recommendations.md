# 2026-08-16 产品化建议（基于当前证据）

## 1. 模型配置
- 当前推荐：**R2**（LoRA + projector）
- 理由：GTSinger 75 段 diagnostic 上 R2 明显优于 R0，略优于 R1

## 2. Decoder
- 推荐：**默认继续使用 official，同时将 `--decoder-kind raw` 作为强候选**
- 证据：
  - GTSinger 全量：both_100ms 90.05% -> 91.84%，20 提升 / 2 回退
  - 18 hard cases：78.32% -> 84.47%
  - regression_selection 同集合：87.47% -> 89.49%，22 提升 / 1 回退
  - PJS：减少零时长，但增加 overlap warning
- 行动：raw decoder 已通过 diagnostic + regression 两轮验证，建议作为产品化默认 decoder 候选；对少量回退段做 hybrid/局部精修研究

## 3. Silence / Window 机制
- 当前证据不支持在短 hard case 上继续投入：
  - `compress-silence-audio`、`strict-silence-boundary-plan`、`skip-silent-windows` 均无变化
  - ⚠️ 口径：三个消融样本均为 7–9s 单窗口短片段，机制未被激活（inconclusive），
    **不能作为"机制无效"的证据**；仅支持"不在短片段上消耗资源"
- 建议：在 ≥60s 多窗口真实歌曲（如 GTSinger 原曲长版 / MIR·Jamendo vocal 派生整曲）再评估

## 4. 质量 Gate
- 必须增加：
  - zero-duration rate
  - raw/selected overlap
  - timestamp regression
- 对 speech-like input 单独报告和设阈值

## 5. 数据 readiness
- GTSinger：可正式评测，但需处理 speech-like 低分段
- PJS：可跑日语 smoke，phoneme GT 待做
- MIR/Jamendo：必须先 vocal 派生
- sealed：默认关闭，milestone 才开

## 6. 下一步优先
1. raw decoder regression_selection 验证
2. PJS phoneme-level GT
3. MIR/Jamendo vocal 派生
4. R-U/R-S/R-CF recovery 消融
