# 2026-07-28 长范围歌词对齐：可视化、Detector、Stable 与 Deferred Realign 实现归档

## 1. 会话背景

上一轮 formal 证明了两个同时存在的事实：

- Qwen 在已知局部错误区和合适上下文下具有真实修复能力；
- 当前 automatic detector、stable cursor 实验和结果汇总尚不足以形成可靠生产路线。

本轮没有把问题继续泛化为“更换模型”，而是冻结项目主叙事：Qwen 是一个短范围内能力良好的工具，研究目标是通过长范围规划和局部执行，使它在完整歌曲上稳定工作。

## 2. 用户评价与最终分类

### 采用

- Formal 动态使用全部已准备 Demo；当前 17+6+6+6 仅是数据状态。
- 所有 Demo 从 E1 到 E7 全程参与，而不是 GT 选完方案后才展示。
- 每首 Demo 生成多路 K 歌方案对比视频，不生成无对比的普通 individual 视频。
- 同时生成当前主方案的行为解释视频。
- 每个样本生成多轨时间轴、偏差、时长分布和不一致图。
- GT 两端延长虚线作为其他轨的视觉参考；不使用 waveform/energy 主轨。
- Silence-aware 保留。
- Stable 实验纠正为 stable-inclusive、stable+left-overlap 和 stable frozen overlap。
- Immediate inline realign 与 anchor-recovered deferred realign 同时作为研究对象。
- 零时长作为强异常，极短时长使用细分布、分位数、相对局部时长和 burst 分析。
- 多尺度一致性只利用同一 Qwen 在不同窗口/上下文下的自一致性，不急于引入外部信号。
- Demo 不要求内置人工标签，只留文档入口。
- 实时状态必须可观察；证据包适度、默认小型。

### 待实验

- S2 与 S3 是否真正优于 baseline；硬冻结是否产生 seam。
- 30/60 秒、exact/+2/+4、raw/official 和跨窗重叠的不一致是否能预测 GT error。
- 极短非零时长是否在 zero collapse 之前出现。
- R1、R2、R3 各自贡献以及 non-GT gate 的误接纳风险。
- Deferred 区间最多跨几窗、多少秒、多少歌词 unit。

### 推迟

- 显式速度/时长先验；先理解真实分布。
- phoneme/VAD/beat 等外部信号。
- 从尾向前或双向解码；除非能形成一般性的右锚点方法。
- 产品式多级 fail-closed 修饰。

### 否定或降级

- 首个自动异常处终止整首输出。
- immediate pending confirmation 作为唯一确认机制。
- 不包含 stable 本身的“stable cursor”负控制代表合理 stable-anchor。
- 单纯最后两窗 rollback 作为主路线。
- raw cursor 作为默认正式控制。
- 20/40 ms 被直接写成普适异常阈值。
- 只渲染 B2 或只渲染单路 raw/baseline 的普通 Demo 视频。

## 3. 最新 realign 设计的准确表述

目标算法是：

1. 串行过程中，当前困难区已经有充分左右约束时，立即 local realign；
2. 没有右锚点时先记录 deferred interval，继续串行；
3. 未来 1–3 个窗口重新出现 stable anchor 后，对两锚点之间的有限区间 realign；
4. 歌曲结束后只扫描仍未解决的 bounded interval，不整首重新推理。

原则是“全局规划，局部执行”。

本轮工程实现为了不污染 B2 和保证公平视频比较，R1/R2/R3 仍是基于完整串行 trace 的 shadow 全曲产物。它模拟相应时机和选择逻辑，但尚未写回在线串行 cursor。这个差异必须在报告中保持透明。

## 4. 本轮实现

### 数据身份与配置

- Demo item ID 增加相对源 identity 的 8 位短哈希。
- long-serial item 全部进入 B0–B3，不再只取前 4 条矩阵样本。
- YAML 成为 wrapper 的规范配置源；显式 CLI 可覆盖。
- `resolved_config.json` 保存 source YAML 与实际 effective request。
- baseline inference cache identity 包含完整 serial 行为参数、歌词/音频 hash、model/revision/checkpoint 和 schema version；GT hash 与 metric schema 独立进入 evaluation identity，只改 GT 不重跑模型。

### Stable 与 realign

- S1/S2/S3 生成完整 shadow alignment，供 GT metric、图和全曲视频使用。
- clean-control 增加 `would_pass_non_gt_gate` 和 counterfactual false accept。
- R1/R2/R3 生成完整 shadow alignment；正式 B2 不修改。
- Deferred 区间限制为最多 3 窗、120 秒、320 units，可由 YAML/CLI 修改。

### 可视化

所有 manifest item：

- 分页多轨时间轴；
- signed onset/offset error；
- 正时长细直方图和 ECDF；
- 零时长比例、分位数、局部时长比与 zero burst；
- B2 相对其他阶段的不一致图；
- `HUMAN_REVIEW.md` 空入口。

### Demo 视频

所有 Demo：

- RAW/B0/B1/B2 四路 K 歌主对比；
- B2/S1/S2/S3 stable 对比；
- R0/R1/R2/R3 realign 对比；
- B2 行为视频，显示窗口、cursor、raw/official、detector、stable、零时长与播放进度。

不生成 unpaired individual videos。

### 汇总与证据

- summary/collector 只处理当前 manifest。
- stale item 只报告，不参与统计。
- clean-control reason 与 automatic reason 分离。
- `gt_available` 与 `gt_error_case_count` 分离。
- 输出 total 以及 dataset/profile/language/unit-mode/duration-bucket/variant 分组结果。
- compact evidence 保存 visual/render 索引和实验摘要，不打包视频图片本体。
- fallback 扩展为 `full → anomaly → severe → minimal`。

### 运行状态

- pipeline 子进程 stdout 实时 tee 到终端和 stage log。
- `live_status.json` 跟踪阶段。
- `experiment_live_status.json` 跟踪 item 与 branch。
- `watch_inline_realign_status.py` 提供持续状态页。

## 5. 一条龙与恢复

```bash
bash scripts/demo/run_inline_realign_smoke.sh
bash scripts/demo/run_inline_realign_formal.sh
```

状态：

```bash
python scripts/demo/watch_inline_realign_status.py <OUT_ROOT>
```

覆盖代码后保留 baseline cache、清理派生产物：

```bash
bash scripts/demo/cleanup_inline_realign_overwrite.sh <OUT_ROOT> derived
```

若需要彻底重跑：

```bash
bash scripts/demo/cleanup_inline_realign_overwrite.sh <OUT_ROOT> all
```

## 6. 实验问题与预期判读

### E1 Raw/Baseline/Current

问题：错误来自 Qwen raw、official decoder、窗口，还是串行累计？

预期：图和视频能把首次漂移、zero burst、raw/official 分歧和恢复位置分开。

结论：raw 正确而 official 坏则优先修 decoder；两者同偏则优先检查窗口和文本范围。

### E2 Zero/Short Duration

问题：错误是否直接 zero collapse，还是先出现低时长尾部堆积？

预期：GT error 区在 ECDF、低分位数、局部时长比或 burst 上与 clean 区分离。

结论：决定 detector 使用 zero 硬信号、short early warning，或只使用相对/burst 特征。

### E3 Detector Audit

问题：当前 detector 能发现什么，为什么漏掉结构正常但时间偏移的错误？

预期：现有特征偏向明显坍塌；多尺度分歧可能补召回。

结论：确定 detector 是否是当前主要瓶颈，并拆分每类特征的贡献。

### E4 Multi-scale Consistency

问题：30/60、exact/+2/+4、raw/official、跨窗重叠的分歧是否与 GT error 相关？

预期：错误区具有更高 boundary dispersion，并可能早于 zero burst。

结论：决定哪些对比值得成为 detector 特征，避免无意义地运行所有组合。

### E5 Stable Anchor

问题：包含 stable 本身并保留左上下文后，能否改善下一窗定位？

预期：S2/S3 优于旧负控制；S1 可能因左上下文不足而弱；S3 可能引入 seam。

结论：stable 应作为输入上下文、软锚点还是硬冻结。

### E6 Immediate / Deferred Realign

问题：哪些错误可立即修，哪些必须等待未来右锚点？

预期：R1 修短区，R2 修跨窗困难区，R3 总体最好；最终 sweep 只处理少量残余。

结论：确定 delayed inline 和结束后 bounded sweep 的实际价值与范围上限。

### E7 Candidate / Gate

问题：无 GT 时能否选择真正改善的 candidate，是否误接纳 clean hard negative？

预期：non-GT gate 接纳多数 GT-improved，拒绝多数 GT-worsened，并保持低 false accept。

结论：决定 realign 能否从 oracle shadow 进入 automatic shadow，再讨论正式写回。

## 7. 未完成和风险

- 本归档未在服务器加载真实 Qwen 权重运行新 smoke/formal。
- R1/R2/R3 是完整 trace 上的 shadow 模拟，不等于已完成在线 writeback decoder。
- Demo 无 GT，视频对比不能替代严格 metric。
- Matplotlib 需要可用 CJK 字体；wrapper 默认 `Noto Sans CJK SC`。
- FFmpeg/FFprobe 是视频必需的系统依赖。
- 多路全量 Demo 视频会占用较大磁盘，但不会进入 compact evidence。
- 新 Demo hash ID 会让旧无 hash item 变成 stale；不会混入统计，但需要按需清理空间。

## 8. AI 协作与理解状态

本轮 AI 主要承担：旧归档审计、实验口径澄清、实现整合、测试与归档记录。用户明确否定了“先用 GT 选方案、最后只在少数 Demo 展示”的流程，并要求 Demo 贯穿 detector、stable 和 realign 研究。实现据此把视频从最终展示升级为实验产物。

当前理解依赖：Qwen 短范围能力良好；长范围问题主要是约束、decoder、detector 和误差传播。这个判断已有 Demo 与 GT 实验支持，但仍需要本轮新增全量可视化和 formal 结果验证。
