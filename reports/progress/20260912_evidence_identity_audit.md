# 真实歌批次证据同一性审计（第 11 轮续，2026-09-12）

> 数字由 `runs/20260912_evidence_identity_audit/IDENTITY_AUDIT.json` 生成；检查器 `src/lyricalign/analysis/evidence_identity_audit.py` 可指向任意批次对复用。

## 0. 裁定

| 比较对 | 裁定 | 依据 |
|---|---|---|
| `ktv_B4__vs__current_silence` | **同一配置的重复运行**（不可用于机制结论） | 23/25 songs byte-identical, identical window plan on all songs, and every output difference occurs on a song whose audio content also changed (2 songs) => the batches are the same configuration re-run, not two mechanisms |
| `current_silence__vs__slot_align` | **不可比**（行不对齐） | 0 songs differ in unit count, 33 have the same count but different characters at the same index (index drift) |
| `ktv_B4__vs__slot_align` | **不可比**（行不对齐） | 0 songs differ in unit count, 25 have the same count but different characters at the same index (index drift) |
| `current_silence__vs__textmode3` | **不可比**（行不对齐） | 33 songs differ in unit count, 0 have the same count but different characters at the same index (index drift) |

- **B4 vs current_silence 收紧结论**：25/25 首歌窗口计划完全相同，92% 输出逐位相同；余下 2 首不同的歌**恰好就是音频 sha 不同的那 2 首**（差异完全由输入不同解释）⇒ 这不是两种机制的对比，而是**同一配置跑了两次**（其中 2 首换了分离音频）。比第 5 轮的表述更硬，也说明 2026-08-14 那批 KTV/四路诊断视频的 B4-vs-Current 对比不成立。
- **slot 两个批次根本没有身份**：`identity.schema_version`、`audio_sha256`、`request_hash` **100% 缺失**（见下表）⇒ 无法证明用的是哪份音频；再加上与 B4/current 逐索引文本 100% 不匹配（单元被跳过/重复导致漂移），这三批之间**不存在任何可支持的对比**。
- `textmode3` 与其余批次单元数不同（word vs char 单元化）⇒ 索引级比较先天不成立。

## 1. 身份卫生（每个批次能不能支撑结论）

| 批次 | 歌曲 | 缺 schema | 缺音频 sha | 缺 request_hash | 记录 silence 标志 | 窗口标志数(中位) | 退化单元 | 重叠 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `ktv_B4` | 25 | 0% | 0% | 0% | 100% | 22 | 18.6% | 0.10% |
| `ktv_current_silence` | 33 | 0% | 0% | 0% | 0% | 12 | 17.8% | 0.11% |
| `slot_vs_b4_align` | 33 | 100% | 100% | 100% | 0% | 0 | 16.7% | 4.66% |
| `slot_v2_textmode3` | 33 | 100% | 100% | 100% | 0% | 0 | 19.7% | 0.47% |

- 顺带复核第 6 轮的结构结论：真实伴奏歌退化单元比例在各批次 16.7%–19.7%（与第 6 轮 17.1% 一致），且**不依赖后处理选择**——这是数据/解码侧的既有事实。

## 2. 把教训变成流程

- 任何批次对比在出结论前必须通过 `audit_pair()`：输出 `not_identified` / `not_comparable` 就直接拒绝出对比表（本轮实现即第 2 轮提议的最小门）。
- `collect()` 对缺失 `schema_version` / `audio_sha256` / `request_hash` 的批次要显式标记为 **unattributable**；后续 batch runner 应把这三项写全（小改动、可纯 CPU 验证）。
- 与第 10 轮的 `factor_content_audit()` 合起来构成两类检查：**批内因子是否真的变了**、**批间是否可比**。

## 3. 复现

```bash
source /root/miniconda3/etc/profile.d/conda.sh && conda activate lyricalign-qwen
cd /home/hyan/LyricAlignment
PYTHONPATH=src python scripts/evaluation/audit_evidence_identity.py
PYTHONPATH=src python scripts/evaluation/report_evidence_identity_audit.py
PYTHONPATH=src python -m pytest -q tests/evaluation/test_evidence_identity_audit.py
```

