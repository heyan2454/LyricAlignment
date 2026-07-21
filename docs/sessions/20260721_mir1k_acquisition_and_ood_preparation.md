# MIR-1K 原始数据获取与 OOD 准备记录

**Date:** 2026-07-21  
**Status:** completed and verified  
**Scope:** 原始 MIR-1K 外部资产获取、完整性验证、17 首字符级标注的 test-only/OOD 接入

## 目标

将原始 MIR-1K 放在仓库外的数据盘，验证完整目录和音频可读性，并把公开的 MIR-1K-partial-align 标注转换为项目的字符级 manifest。不得把 MIR-1K 用作训练或 validation。

## 来源与获取

- 原始归档镜像：Figshare `MIR-1K.rar`，文件大小 `797386646` bytes；下载完成后按发布的 MD5 校验。
- 原始归档外部路径：`/home/hyan/Data/datasets/mir1k/MIR-1K.rar`
- 解压根目录：`/home/hyan/Data/datasets/mir1k/raw/MIR-1K`
- 字符级标注来源：`navi0105/LyricAlignment` 的 `MIR1k_partial_align.json`。
- 标注外部路径：`/home/hyan/Data/lyricalign/annotations/mir1k_partial_align/MIR1k_partial_align.json`

下载过程遇到单连接与单响应限速；改为 16 个可恢复 HTTP Range 分段，合并后才校验并解压。该分段实现仅用于本次外部资产获取，不纳入仓库代码。

## 完整性结果

| 项目 | 结果 |
| --- | --- |
| 发布 MD5 | `1810d01457ccbb84a0b41c4da53eee74` |
| 实际 MD5 | `1810d01457ccbb84a0b41c4da53eee74` |
| 归档 SHA256 | `5bf7d2c32de6fd9246b90460effff06a99464dc019ded7ce0901b67fd2316451` |
| `UndividedWavfile` | 110 首整曲 WAV，全部可读，时长 22.610–126.730 s |
| `Wavfile` | 1,000 条短片段 WAV，全部可读，时长 3.078–12.032 s |
| `Lyrics` | 1,000 份 |
| `PitchLabel` | 1,000 份 |

## 字符级 OOD 数据

使用 `scripts/datasets/prepare_mir1k_partial_align.py` 处理公开标注，输出到：

```text
/home/hyan/Data/lyricalign/derived/mir1k_partial_align_v1/
```

结果：

- 17 首已人工字符级对齐的完整歌曲；
- 2,035 条字符时间戳；
- 每条标注的字符数、时间戳顺序、起止合法性、音频存在性与音频时长均已验证；
- manifest 固定为 `split: test` 和 `usage: ood_test_only`。

完整的机器可读证据见 `runs/data_preparation/20260721_mir1k_partial_align_v1/run_summary.json`。

## 决策与边界

- MIR-1K 的 17 首人工标注歌曲只用于 OOD character-level 测试；
- 不将 MIR-1K 用于训练、validation 或与 M4Singer 混合切分；
- 其余 93 首整曲虽有歌词来源，但不具有已验证的字符级时间戳，不进入正式 character-level metric；
- 1,000 条短片段可用于将来的 metric-free 推理诊断，但不能替代 17 首人工标注 OOD 测试。

## 复现入口

```bash
python scripts/datasets/prepare_mir1k_partial_align.py \
  --mir1k-root /home/hyan/Data/datasets/mir1k/raw/MIR-1K \
  --annotations /home/hyan/Data/lyricalign/annotations/mir1k_partial_align/MIR1k_partial_align.json \
  --out-dir /home/hyan/Data/lyricalign/derived/mir1k_partial_align_v1
```
