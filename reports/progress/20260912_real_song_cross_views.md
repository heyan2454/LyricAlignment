# 真实长歌跨视图一致度普查（25 首 · 无真值 · 2026-09-12 第 5 轮）

> 数字由 `runs/20260912_real_song_views/{VIEWS_PANEL_SUMMARY,VIEWS_ANALYSIS}.json` 生成。
> 纯 CPU 复用 2026-08-14/15 的真实歌曲对齐产物；零新增前向；无真值 ⇒ 只测分歧，不判对错。

## 0. 结论先说：这批真实长歌证据**不能**支撑任何"机制对比"结论

- 三个视图里只有一对可按索引比较：**B4 vs current_silence**（100.0% 位置文本一致）；而 `full_slot` 有 23.6% 的位置落在**不同字符**上（该 run 会跳过/重复单元导致索引漂移），且其音频 sha 未记录（b4↔slot 同 sha 占比 0.0%）⇒ 不能做逐单元比较。
- 而那唯一可比的一对，输出几乎完全相同：>100ms 分歧占比仅 0.08%（9 个单元）。**它们根本不是两种规划**：窗口计划逐字段相同（同 policy、同 60s core、同 10s 左上下文、同 committed 区间）。
- ⇒ 因此 2026-08-14 交付的 `B4 vs Current` 四路诊断视频/KTV 对照，**在留存证据里不构成已识别的因子对比**；真实长歌上目前**没有任何可用的多视图证据**。

## 1. 视图身份溯源（问题定位）

| 视图 | 产出 runner（identity.schema_version） | 记录 silence 标志的歌曲数 |
|---|---|---:|
| `b4_60s_windowed` | `qwen_fa_serial_demo_v7_silence_aware_windows`×25 | 25/25 |
| `current_silence_aware` | `qwen_fa_batch_alignment_v4_forward_overlap_compression`×25 | 0/33 |
| `full_slot` | ``×25 | 0/33 |

- 批处理视图（`qwen_fa_batch_alignment_v4_*`）的 `identity.window` **完全不记录** `skip_silent_windows / silence_aware_window_plan / strong_silence_anchor_sec / leading_silence_min_sec / tail_min_core_sec` 等标志（全部 None）⇒ 即使标志生效，产物里也无法核对；这是 request-identity 的**记录缺口**，正是 AGENTS 里"缓存身份必须并入代码/配置"要求在长歌 demo 链路上的破口。
- 两个视图的音频路径不同（一份在 `test/<Lang>/<song>_qwen_fa/work/audio/vocals.wav`，一份在 `runs/20260814_ktv_current_silence/<song>/work/…`），但内容 sha 一致率 92.6%（按单元计）⇒ 同一段分离人声被复制两份，后续若要真正做"分离 vs 混音"因子，必须先消除这种同内容双路径。

## 2. 可比对的分歧量级（唯一有效的一对）

| 配对 | 可比单元 | 中位分歧 | p90 | p99 | >100ms | >250ms |
|---|---:|---:|---:|---:|---:|---:|
| `b4_vs_cur` | 10,909 | 0.0ms | 0.0ms | 0.0ms | 0.08% | 0.06% |
| `b4_vs_slot`（**不可用于结论**：索引错位） | 8,331 | 0.0ms | 700.0ms | 65.04s | 15.58% | 12.82% |

## 3. 各语言的退化单元比例（这是本面板**唯一可靠**的跨视图信息，来自 single-view 统计）

| 语言 | 单元 | 歌曲 | B4 零时长率 | full_slot 零时长率 |
|---|---:|---:|---:|---:|
| Cantonese | 1,564 | 3 | 15.2% | 17.8% |
| Chinese | 5,980 | 13 | 7.2% | 5.8% |
| English | 1,946 | 5 | 23.2% | 22.1% |
| Japanese | 1,419 | 4 | 52.8% | 45.0% |

- 真实伴奏流行歌上的零时长单元比例高得离谱（中文 7.2%、英文约 23%、日文 45-53%），与 GTSinger 干净录音上的 2-4% 完全不同量级：**产品化必须把零时长/退化区间当作首要结构 gate**，而不是把它当成可忽略的边角。

## 4. 与前三轮结论的接续

- 第 1 轮：GTSinger 上 12 配置矩阵是假因子 ⇒ 本轮在真实长歌上又发现一个假因子（B4 vs current_silence 计划相同）。**"配置写了不同标签"不等于"跑了不同配置"**，这条已经两次被证实，必须进流程。
- 第 5 轮共识模拟：自然录音上共识只关 7.4% 上界差距 ⇒ 真实长歌这边连可用的多视图证据都没有，所以`multi-view / recrop` 线要推进，缺的不是算法而是**一次带完整身份记录的多视图采集**。
- 建议（不花 GPU 就能做）：把本模块的"可比性检查"（文本逐位一致 + 音频 sha 相同 + 窗口计划不同）作为任何跨视图实验的**前置门**，三条不满足就直接拒绝出对比结论。

## 5. 复现

```bash
source /root/miniconda3/etc/profile.d/conda.sh && conda activate lyricalign-qwen
cd /home/hyan/LyricAlignment
PYTHONPATH=src python -c "from pathlib import Path;
from lyricalign.analysis import real_song_views as R;
d=Path('/home/hyan/Data/lyricalign/runs/20260912_real_song_views'); st=R.build_panel(d)
df=R.load_frame(Path(st['out'])); a=R.analyse(df)
(d/'VIEWS_ANALYSIS.json').write_text(__import__('json').dumps(a,ensure_ascii=False,indent=2))"
PYTHONPATH=src python scripts/evaluation/report_real_song_views.py
PYTHONPATH=src python -m pytest -q tests/evaluation/test_real_song_views.py
```

