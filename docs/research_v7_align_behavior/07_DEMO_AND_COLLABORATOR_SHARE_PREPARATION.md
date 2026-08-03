# 阶段性 Demo 与合作者分享准备

## 当前暂定展示基线

- Qwen3-ForcedAligner-0.6B + R2；
- Demucs vocal 推理；
- fixed 60s；
- official decoder；
- 原始 mix/视频渲染；
- 不自动写回 realign；
- official/top-K/weighted 匿名对比作为附加材料。

该选择是“保守展示路线”，不是统一精度最优结论。

## 对外说明必须包含

1. 项目目标与当前定位；
2. 已完成 E0–E9 和主要正/负结果；
3. 当前限制：detector、dynamic boundary、silence、auto realign 未通过；
4. 旧 E4 是 localized upper bound；
5. 新主线：不合法输入行为、strict serial、sparse slots、posterior；
6. test demo 无 GT，人工观看不等于 accuracy。

## 环境包

最终需要：

- environment.yml；
- requirements lock；
- Python/CUDA/Torch/ffmpeg；
- Transformers 源码 commit；
- model/checkpoint SHA256；
- setup/verify 脚本；
- 单 case 一键命令；
- 可选 conda-pack。

## 无 GT Review Bundle

每首歌保存：

- request/window/cursor trace；
- 多路线 candidate；
- posterior/repair diagnostics；
- timeline/video；
- 人工 span review 表；
- dev/validation/heldout 身份。
