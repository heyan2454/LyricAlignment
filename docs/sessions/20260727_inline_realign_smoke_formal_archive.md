# 2026-07-27 Inline Realign：归档、Shadow 实现与 Smoke/Formal 一条龙

## 1. 本次归档目的

前一轮真实 Demo 证据显示：official 成品时间优于 raw，但当前 realign 几乎没有产生写回；现有 O0 又受 shared raw planner 控制，不能视为旧 `r2:vocal:windowed` 的等价复现。本次工作不直接放宽 gate 并修改成品，而是先建立可验证、可恢复、数据量受控的实验入口。

本归档完成：

- 保存完整讨论、被否定设计、待验证假设和实验分支；
- 增加逐窗口提交前 shadow 诊断；
- 增加稳定段和稳定前缀复现证据；
- 增加候选歌词扩展前后的小规模对照；
- 增加 B0–B3 official 基线矩阵；
- 增加一个或两个相邻窗口内的 shadow local realign；
- 增加 Demo、M4Singer、MIR-1K 统一 manifest；
- 增加 smoke、formal、有限证据收集的一条龙入口；
- 优化 official comparison 渲染为一次编码；
- 增加单元测试、归档记录和执行说明。

## 2. 已否定内容

本次不再沿用：

- 固定 16 字、12 秒或 5～6 行寻找 anchor；
- 稳定字必须天然出现在两个窗口；
- 强静音附近字符绕过其他检查；
- raw 默认作为成品和生产 planner；
- 整首歌完成后才尝试修复串行错误；
- 尾窗无条件吞下全部剩余歌词；
- 使用严格固定语速作为普通歌曲硬门槛；
- 每次默认渲染四个完整分支并二次编码 comparison。

## 3. 本次实际实现

### 3.1 提交前 shadow 诊断

修改：

```text
scripts/demo/align_qwen_fa_serial_demo.py
src/lyricalign/demo/inline_realign.py
```

每个窗口在正式更新全局结果前，先在副本中执行原拼接规则并记录：

- 连续零时长或相同时间堆叠；
- 所有候选歌词在输入尾部的大量堆积；
- 有明显有效人声但本窗提交 0 字；
- 拼接压缩数量和最大幅度。

当前仅记录，不改变提交行为。这允许区分“模型窗口输出已坏”和“接到前文后才形成坍缩”。

### 3.2 候选歌词扩展证据

每次文本扩展只保留边界附近、输入尾部和首尾少量字符，默认每次最多 48 行，不保存完整重复输出。最终记录扩展前后的最大和中位边界移动。

### 3.3 稳定段

稳定段以连续字符为单位。当前主要条件：

- 段内多数边界达到本窗口置信度中位数以上；
- 非零时长、未被拼接压成零；
- raw 与 official 的最大移动不超过默认 160 ms；
- 若存在真正获得声音支持的重复上下文，则其时间差不超过默认 240 ms。

不要求必须出现于两个窗口。future lookahead 不再算作真正重复观察。

### 3.4 稳定前缀复现

上一窗口保存最靠后的稳定段；下一窗口若重新观察到它，记录最大和中位边界差。当前只做 shadow，不阻断提交。

### 3.5 B0–B3 基线

长音频运行：

```text
B0 60 s fixed, official self-control
B1 30 s fixed, official self-control
B2 30 s silence-aware, official self-control
B3 30 s silence-aware, raw control + official output
```

用途是拆分 60→30 秒、静音感知规划和 shared raw planner 三类变化。

### 3.6 Inline shadow realign

只从 B2 的提交前异常触发。搜索范围依次为：

1. 当前窗口；
2. 前一窗口 + 当前窗口；
3. 当前窗口 + 下一窗口。

找到左右稳定段后执行 exact 与 `+2` 两种上下文局部推理，比较结果一致性、bounded splice 的结构有效性、异常分数和 GT 前后变化。即使满足当前 shadow write 条件，也不会改写主对齐。

若未找到稳定段，不再只记录笼统的 `no_stable_segment_pair`，还会按搜索窗口范围保存：零时长、拼接压成零、置信度低于当前分位数、raw/official 移动过大、不同受声音支持上下文不一致，以及左右最近候选。局部替换预览最多保存 64 行，并在更长区域内均匀抽样。

### 3.7 数据集清单

Smoke 默认上限：

```text
Demo 1
MIR-1K development 2
M4Singer native 2
M4Singer synthetic-long 1
shadow cases / item 2
```

Formal 默认清单上限：

```text
Demo 6（其中 2 首运行 B0–B3，其余只运行 B2）
MIR-1K development 8（其中 4 首运行 B0–B3，其余只运行 B2）
M4Singer native 8（只运行 B2）
M4Singer synthetic-long 4（其中 2 首运行 B0–B3，其余只运行 B2）
shadow cases / item 8
```

M4Singer 默认只用 validation。MIR-1K held-out 只有显式 `--include-heldout` 才进入清单。

### 3.8 有限证据

默认上限 8 MiB。超限时自动从 full 缩减到 anomaly，再缩减到 severe。证据不包含音视频、模型权重和完整日志。若部分 item 失败但 `experiment_summary.json` 已生成，流水线仍继续收集已完成结果，最终写入 `partial_failure` 并返回非零状态。

### 3.9 渲染

默认 O0/O1 official review；同一输入视频只解码一次，两个字幕分支在一个 filter graph 中完成，一次编码输出。raw 四宫格改为显式 `--four-way`。入口视频不再强制复制。

## 4. 一条龙执行

```bash
bash scripts/demo/run_inline_realign_smoke.sh
bash scripts/demo/run_inline_realign_formal.sh
```

阶段：

```text
01_manifest → 02_experiment → 03_collect
```

每阶段有独立日志和状态。分支按 request hash 恢复。实际路径和覆盖方法见：

```text
docs/manual/inline_realign_smoke_formal.md
```

## 5. 预期结果与结论分支

### 基线矩阵

- B0≈B1，B2≈B1，B3 较差：shared raw planner 是主要退化来源；
- B0 明显优于 B1：30 秒输入或更频繁串行提交本身有风险；
- B1 优于 B2：静音感知边界移动或裁剪映射需要修正；
- selected 正常、final 变差：拼接压缩是主要二次坍缩来源；
- 所有 official 自控分支仍弱：需要研究 official 的整体解码和窗口文本输入，而不能只改 planner。

### 稳定段

- coverage 上升且 GT 准确率保持：旧 anchor 条件确实过严；
- coverage 上升但 GT 明显下降：需要主动上下文复验或提高段级置信度，不能继续无条件放宽；
- 单窗口稳定段准确、跨窗口不稳定：接缝定位是主要问题；
- raw/official 接近不能区分正确与错误：该项只能作为弱辅助，不能做门槛。

### 稳定前缀

- 失败早于后续明显坍缩：适合作为串行阻断信号；
- 正确样本中也大量失败：当前稳定段定义或上下文复现方法不可靠；
- 只在 future lookahead 情况下“成功”：必须继续排除无声支持观察。

### 文本扩展

- 边界覆盖增加且原区稳定：现有扩展策略可保留；
- 大量扩展导致原区堆积/坍缩：不能再以“看到边界”为唯一接受标准；
- 高语速样本只表现为需要更多文本，但不堆积：不应使用严格字速硬限制。

### Shadow realign

- local GT 提高、clean harm 低：进入单窗口正式写回实验；
- 单窗有效、跨窗无效：先实现单窗写回，接缝使用延迟确认；
- 结构改善但 GT 不改善：不能用结构分数作为唯一接受条件；
- local oracle 也不改善：问题不在 anchor gate，而在局部输入或模型能力。

## 6. 仍未实现

以下内容有意留到实验后：

- 自动写回主串行结果；
- 窗口尾部的 pending/延迟确认状态；
- 跨窗口联合重分歌词 cursor；
- 尾窗回退两窗或 incomplete 输出；
- 多候选 cursor/多路径；
- official logits 上的全局概率最优单调解码。

这些都会改变正式输出和后续窗口输入，必须在 shadow 证据支持后逐步进入。

## 7. 测试与验证

归档前完成：

- `python -m compileall -q src scripts tests`：通过；
- 所有 shell 脚本 `bash -n`：通过；
- 排除当前容器缺少 `pypinyin` 导致无法收集的 3 个既有测试文件后，`158 passed`；
- 新增 inline 流水线专项测试：`11 passed`；
- synthetic manifest smoke：MIR-1K development、M4Singer native 和 M4Singer synthetic-long 均能生成，held-out 默认排除；
- 1 MiB 有限证据 smoke：完成，证据约 4 KiB，并包含 pipeline 元数据；
- partial-failure smoke：实验已有部分结果时仍完成收集，写入 `partial_failure`，返回码为 1；
- 真实 ffmpeg review smoke：O0/O1 一次编码，入口视频通过 hardlink 复用，两个路径共用同一 inode。

完整 `pytest` 在当前归档容器的收集阶段被 `ModuleNotFoundError: pypinyin` 阻断，影响 `test_audio_contract.py`、`test_m4singer_preparation.py` 和 `test_mir1k_partial_align.py`；这不是本次改动的测试失败。

本地归档环境没有服务器模型快照、R2 权重和真实数据路径，因此没有声称完成真实 GPU inference smoke。服务器第一步应运行 smoke，并检查 `pipeline_complete.json`、`input_audit.json` 和 evidence 大小后再启动 formal。

## 8. Negative Results 与 AI 协作记录

本轮没有把此前几乎无写回的 realign 直接解释成“局部重对齐无效”。证据只支持：旧 anchor 条件与 post-hoc 插入时机没有形成有效干预。

实现过程中主动保留了以下限制：

- 不因讨论看起来合理就直接改写正式结果；
- 不把 Demo 结构指标当作准确率；
- 不将 M4Singer synthetic-long 与自然全曲混合汇总；
- 不提前使用 MIR-1K held-out；
- 不无限保存每次候选扩展的完整逐字输出；
- 不为追求“一条龙”吞掉 item 级错误，失败会留下明确记录并返回非零状态。

AI 的主要作用是将连续讨论转成可测试的模块、执行入口和归档证据。当前依赖状态仍包括：服务器本地 Qwen snapshot、R2 step-750、M4Singer labels/audio、MIR-1K subset 和已准备的 Demo vocal。
