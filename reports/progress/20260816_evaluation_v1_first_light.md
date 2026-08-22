# 2026-08-16 Evaluation V1 First Light

## 目标
验证新获取的数据能否进入现有 Lyric Align 推理链，并产出可清理、可追溯的产品化研究基础。

## 已执行
- 生成 Evaluation V1 grouped split draft（MIR-MLPop/Jamendo/PJS/GTSinger）
- 生成 dataset readiness、baseline identity、vocal derivation plan、behavior registry
- 在 GTSinger Chinese mini 上跑通两个 8 秒 diagnostic 片段的 R0/R1/R2 serial demo

## GTSinger Smoke 结果
| Smoke | 片段 | 时长 | R0/R1/R2 产物 | 结构质量 | 零时长 |
|---|---|---|---|---|---|
| 1 | `倒带/Control_Group/0000` | 8.068s | 12/12 | passed_structural | 0 |
| 2 | `倒带/Glissando_Group/0000` | 8.076s | 12/12 | passed_structural | 0 |
| 3 | `倒带/Control_Group/0001` | 9.35s | 16/16 | R0/R1 passed; R2 warning (raw overlap, final clean) | 0 |

产物路径：
- `/home/hyan/Data/lyricalign/runs/20260816_evaluation_v1_gtsinger_smoke/`
- `/home/hyan/Data/lyricalign/runs/20260816_evaluation_v1_gtsinger_smoke2/`
- `/home/hyan/Data/lyricalign/runs/20260816_evaluation_v1_gtsinger_smoke3/`

## 结论强度
- 强：新数据集 GTSinger 的 WAV + JSON 可转换为现有 pipeline 输入，R0/R1/R2 均可运行。
- 强：已完成 75 段 GTSinger diagnostic 的 GT 数值评测（1226 字符），R2 both_100ms=90.1%、both_200ms=95.5%。
- 中：仍存在约 30–34/75 段 final zero-duration warning，产品化需处理后处理质量 gate。
- 弱：尚未覆盖自然流行混音（MIR/Jamendo）和日语音素评测。

## 下一步
1. 冻结 split manifest
2. 对 GTSinger diagnostic 子集做批量 baseline 和 GT 对比
3. Jamendo/MIR-MLPop vocal 派生后接入评测
4. 按 behavior registry 做单因素消融
