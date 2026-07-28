# 2026-07-28 Inline Realign v4 全机制实验设计

## 1. 研究目标

目标不是只找到一个工程上可用的窗口参数，而是回答：

1. 模型对窗口长度、静音边界和文本剂量的敏感性来自哪里；
2. Raw logits、official decoder 和串行 commit 分别带来哪些改善与损害；
3. Stable 是否可以作为同步裁剪边界和冻结约束；
4. 局部 realign 在什么证据下可安全采用；
5. Deferred 是否只缺未来右锚点，还是模型本身不存在稳定局部解。

## 2. 假设与替代解释

### H1：严格静音边界可减少跨静音路径波动

预期：静音两侧 cursor 跳动、重复提交和边界最大差下降。

替代解释：严格裁剪减少了有用声学上下文，导致静音后首字更差；或 vocal activity 错把弱唱识别为静音。

### H2：减少冗余未来歌词可降低路径分叉

预期：在不删掉真实演唱歌词时，减少未来文本会降低最大边界移动。

替代解释：模型需要较长文本确定全局路径，少给反而导致尾部膨胀或提前消耗歌词。

### H3：同步 stable 裁剪优于旧错位输入

预期：stable exact/−2/−4 不再系统性跳过 stable 前真实歌词，cursor 与 GT ideal 更接近。

替代解释：stable 时间本身来自错误 baseline，即使同步也会锁定错误路径。

### H4：结构不升 gate 可提高召回而不显著增加误改

预期：相对严格下降 gate 接受更多 GT-improved case；clean control false accept 仍较低。

替代解释：异常数量相同但时间位置更错，结构分数不升不足以保证正确。

### H5：零时长专用 gate 可恢复困难 Demo

预期：即使 Exact/±2/±4 完整路径不一致，只要一个候选减少零时长且不引入负时长/回退/重叠，听感和 GT 更可能改善。

替代解释：只是把错误堆叠摊开，结构更好但时间更错。

### H6：Raw 的局部时间质量好，但串行控制不稳定

预期：D0 在固定 B2 cursor 下 GT 不差；B3 raw-control 更容易传播 cursor 错误。

替代解释：Official 的优势只在特定语言/长度出现，Raw 优势来自样本或 metric 口径。

## 3. 实验矩阵

### E0：运行和可视化基础设施

目的：确保所有后续结论可恢复、可审计、可观察。

实现：严格 run/stage/item identity；`analysis_complete` 与 `render_complete` 分离；静态图和视频按 item resume。

预期：中断后不重复完整 item；视频失败不导致推理重跑。

### E1：Core × Silence

条件：B0/B1/B2/B4/B5/B6/C0/C1，外加 B3 raw-control。

主指标：canonical v3 tolerant、coverage、零/负时长、回退、重叠、窗口数、wall time。

局部指标：静音前后 ±2 秒、静音前最后字、静音后第一字、跨静音 cursor 跳变量。

公平性：同模型、同 checkpoint、同语言解析和同 GT；全静音压缩只作为诊断，不与生产条件直接排名。

### E2：Text dosage

固定声学窗口，改变文本起止：

```text
end: -8,-4,-2,0,+2,+4,+8,+16,1.25x,1.5x
start: -4,-2,0,+2,+4
```

观察：core/边缘 MAE、coverage、尾部膨胀、零/负时长、下一窗 cursor 和相对 exact 的最大移动。

公平性：必须明确负 end delta 是否删掉音频内真实歌词，不能把“减少冗余”与“文本不足”混在一起。

### E3：Stable synchronized crop

条件：原窗口范围重跑且只冻结 stable、sync exact、sync −2、sync −4。

观察：稳定段复现、cursor 距离、stable 附近 MAE、是否漏词、是否被后续覆盖。

公平性：音频起点和歌词起点来自同一 baseline 单位；任何声学 padding 都必须有对应歌词或处于静音中。

### E4：Immediate / Deferred realign

候选来源：GT oracle、人工 Demo、零时长结构候选；automatic detector 只作辅助。

Gate：strict decrease control、structural nonincrease、zero-duration relaxed、context median fusion。

Deferred 等待 1–3 个窗口恢复右 anchor，再运行相同 gate；它不等价于放宽三上下文一致性。

观察：GT improved/worsened、clean control false accept、零时长修复、unresolved 长度、等待窗口数。

### E5：Decoder stages

阶段：D0、D1、D2、D4、D5、D6；B3 单独表示 raw cursor control。

观察：每一步修改多少字符、首次引入零时长的阶段、负时长修复、边界移动分布和 canonical GT。

中间层 timestamp 只在 D0–D6 分析完成后进行，避免同时引入模型结构变量。

## 4. 数据规模

Formal 可大量使用当前所有 Demo、MIR-1K、M4Singer native 和 synthetic-long。推理不是主要瓶颈，因此不人为压缩模型实验数量。

渲染成本单独处理：

- 静态图对所有 item 生成；
- Demo 视频在分析之后统一生成或单独 resume；
- 默认 evidence 只收集适量代表 case，不复制完整视频和全 alignment。

## 5. 结论强度规则

- Demo：结构与听感观察，不声称 GT 精度；
- MIR-1K：自然 GT；
- M4Singer native：局部短段参考；
- synthetic-long：长序列与窗口传播压力测试，与自然长歌分开；
- matched-only metric：辅助诊断；
- canonical tolerant：主指标；
- oracle improvement：算法能力上限，不等于生产性能；
- shadow accepted：候选门控判断，不等于 actual writeback。
