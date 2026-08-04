# 2026-08-04 长时间线 Slot/判别器会话归档 Patch（review 修订版）

## 基准工作目录

本 patch 面向：

```text
LyricAlignment_202608040823_alignbehavior.zip
```

它只更新文档、会话入口和 Agent 实施合同，不包含下一阶段实验代码或运行结果。

## 主要修订

- 明确 ≥180 秒是数据时间线，主模型请求继续使用 fixed 60s；
- 禁止人工静音凑长度，仅保留小型 0.5 秒 seam 对照；
- extra/missing/replace 同时保留 1/2/4/8 units 与百分比曲线；
- missing 增加 virtual gap，replace 增加 wrong-output + omitted-original 双向评价；
- 同时报告 unit recall、interval recall@75%、interval recall@100% 和 correct-unit FPR；
- slot density 使用 common units 和 stride phase 轮换；
- matched legal baseline 按完整 request identity 建立；
- S6 拆分为机制消融和系统配置比较；
- raw/official/hidden 分开诊断，暂不冻结生产 commit；
- 增加跨域 assessor 与严格 hidden extraction contract；
- 弱人声 calibration packet 作为第一批并行工作；
- formal 目标 10 小时、硬上限 12 小时；
- 修正 E5、P1 和人工 review 结果/标签的历史文档错误。

## 应用

在 `/home/hyan` 下覆盖解压：

```bash
cd /home/hyan
unzip -o LyricAlignment_20260804_long_slot_region_assessor_archive_patch_reviewed.zip
```

也可以在解压后的仓库根目录运行：

```bash
bash APPLY_LONG_SLOT_REGION_ASSESSOR_ARCHIVE_PATCH.sh
```

该脚本验证文件是否已正确覆盖，不执行实验。
