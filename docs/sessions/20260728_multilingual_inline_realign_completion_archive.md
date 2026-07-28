# 2026-07-28 多语言 Test Demo、Inline Realign 未完成实验与归档记录

## 1. 本阶段从什么问题开始

本阶段不是从一个已经稳定的 realign 系统继续调阈值，而是从三组已观察到的问题继续推进：

1. **当前 official 明显优于 raw，但新的 official/no-realign 仍可能弱于历史 `r2:vocal:windowed`。**
   - 早期四分支 Demo 使用 shared raw planner，不能代表 official 自己控制窗口推进时的最佳行为。
   - 后续 B0/B1/B2/B3 发现固定 30 秒与固定 60 秒可以接近，但 silence-aware B2 在夜苏打上因文本扩展和立即提交发生严重坍塌。
2. **早期 post-hoc realign 几乎没有变化。**
   - 第一轮 formal 中大量 `no_conservative_anchor_pair` 实际来自过窄的单字/16 字/12 秒/两窗口硬条件，以及错误地把整窗当作异常区。
   - 修正为稳定段和局部异常后，GT-oracle 已证明 local realign 对部分错误有修复能力。
3. **补充实验没有全部真正执行。**
   - `start_sec` schema 错误使稳定段主动重跑和强制文本扩展在 23 个长样本上中断。
   - Demo 发现曾只纳入一首，且全局语言参数会把英文、日文、粤语按中文处理。
   - 跨窗口 pending、自动检测召回/误报、clean harm、三上下文一致性、历史 r2 对照、真实自动 incomplete 和尾部两窗回退仍未进入统一流水线。

本阶段目标是：**修复未完成实验，支持发现多少 Test Demo 就运行多少，覆盖每条样本自己的语言，并将仍未验证的问题实现为明确的 shadow 实验；自动写回仍保持关闭。**

## 2. 当前 Test Demo 数据现状与数量纪律

用户当前说明：

- 中文当前有 17 首；
- 其他每种语言当前有 6 首；
- 这些只是当前输入规模，不是代码中的固定数量或未来上限。

因此实现遵循：

- formal 默认递归发现并纳入 **全部可用 Test Demo**；
- 不在代码、配置或通过条件中写死中文 17、其他语言 6；
- 输入审计记录本次实际发现的语言和歌曲数，作为运行快照；
- smoke 默认每个当前发现到的语言取 1 首，只为了快速验证语言、tokenizer、模型和渲染链；
- 可通过显式 `--demo-cap` 或 `--demo-per-language-cap` 做临时预算运行，但这些不是正式默认；
- formal 的 expensive B0–B3 矩阵仍只在语言均衡的小子集运行，其余歌曲运行 official 主分支和补充诊断，避免计算量随 Demo 数量四倍增长。

示例目录按语言分层，原始媒体和歌词位于歌曲目录，旧 `_qwen_fa` 目录可提供 vocal 与历史 r2 输出。发现器忽略生成目录中的媒体，只配对同一原始目录中的同名媒体和 `.txt`。

## 3. 已否定或降级的方案

### 3.1 固定字符数、歌词行数和固定秒数找 anchor

否定：16 字、12 秒、5–6 行都不能稳定描述一首歌中的困难范围。新规则只限定在当前窗口或相邻窗口范围中寻找连续稳定段。

### 3.2 稳定单位必须天然出现在两个窗口

否定为硬条件。未来 lookahead 在前窗出现并不代表有声音支持；单窗口高置信稳定段也可作为候选。更可靠的验证方式是主动使用不同上下文重跑。

### 3.3 强静音附近自动成为可靠 anchor

否定。静音裁剪后模型未必知道原静音长度，静音前坍塌仍可影响静音后。静音只保留为窗口规划变量，不绕过稳定性检查。

### 3.4 直接使用稳定段开头替换下一窗口 cursor

由现有 GT 结果明确否定。它常使下一窗额外输入约十个已完成单位，而基线 cursor 已接近 GT。该实验保留为 paired negative control，不进入生产推荐。

### 3.5 raw 作为默认成品或默认生产 planner

降级为内部诊断。夜苏打 B3 出现大量零时长，official 主路径明显更合理。B3 只在 raw/official 的提交或 cursor 真正发生分歧时追加运行。

### 3.6 “增加歌词后覆盖到边界”即接受

明确否定。夜苏打中扩大到全部剩余歌词后，已有区域大幅移动、120 字零时长、113 字同边界，但旧逻辑仍视为已覆盖核心边界。新的扩展实验必须同时看已有区域移动、坍塌、堆积和稳定前缀复现。

### 3.7 尾窗无条件吞完剩余歌词

明确否定。失败时允许输出 incomplete，不能用上百个零时长单位伪装完整。

## 4. 已获得的主要结果

### 4.1 稳定段本身可靠

在已有 MIR-1K/M4Singer GT 结果中，稳定段覆盖约四成单位，稳定段的边界 MAE 和 0.16 秒内双边界准确率明显优于全体。它适合做 anchor 和交接校验。

### 4.2 Local realign 有修复能力

上一轮 GT-oracle：29 个候选实际完成两种上下文局部重跑，14 个改善；当前保守规则下 11 个 would-write 全部改善，未观察到误写。结论是 realign 不是无效，而是此前触发、范围和时机没有让它发挥。

### 4.3 当前 automatic detector 召回仍不足

自动检测主要捕获极端连续坍塌，尚未正式计算对 GT 错误段的 case/unit precision 和 recall。该缺口在本阶段实现。

### 4.4 稳定前缀适合校验，不适合替代 cursor

捕获到的正常接缝中，稳定前缀大多能在下一窗复现；但直接将 cursor 回退到稳定段开头明显远离 GT 理想 cursor。新的用途是：

- 下一窗复现失败时阻止继续提交；
- 文本扩展后稳定前缀消失时拒绝扩展结果；
- 窗尾坍塌缺右 anchor 时，作为 pending 的左侧参照。

## 5. 本阶段实现内容

## 5.1 多语言 per-item 输入

每个 manifest item 保存独立的 `language`，并参与 request hash。支持目录语言别名归一化，当前 Test Demo 可覆盖 Chinese、Cantonese、English、Japanese；其他 Qwen 支持语言可继续递归发现。

- 中文/粤语：CJK 字符与 Latin word 混合单位；
- 英文：word 单位；
- 日文：Nagisa 分词单位；
- 指标按 `language + alignment_unit_mode` 分组，不能直接把四个中文字符与四个英文单词当作同等异常长度。

若选中 Japanese 而环境缺少 Nagisa，manifest 后、模型推理前明确失败。

## 5.2 Demo 数量动态化

- formal：未传 cap 时使用全部发现并且具备 prepared vocal 的 Demo；
- smoke：默认每种发现语言 1 首；
- 审计保存 discovered、prepared、selected 和各语言数量；
- 当前实际歌曲数量只出现在运行审计，不进入长期配置。

## 5.3 Demo 输出位置

canonical 输出始终位于单一 experiment root，保证恢复、证据收集和汇总一致。另提供三种视图：

1. `central`：只保留 `<OUT_ROOT>/items/<item_id>`；
2. `adjacent`：歌曲旁生成 `<stem>_inline_realign/`；
3. `directory`：发布到指定目录的 `<language>/<stem>/`。

后两种只创建相对符号链接和小型 `publish_manifest.json`，不会复制视频和 alignment，避免重复目录与体积翻倍。所有歌曲仍然先 align 完，再统一 render，最后才 publish。

## 5.4 修复此前未完成的 schema

局部 `infer_slice` 输出统一投影为：

```text
start_sec
end_sec
global_character_index
```

再进入 GT、结构和扩展比较。稳定段主动重跑与 forced expansion 独立捕获失败，其中一个失败不再终止另一个。

## 5.5 三上下文 2/3 一致性

local realign 运行：

```text
exact
+2 units
+4 units
```

任意一对满足时间一致即可形成 shadow consensus，并记录选择了哪条局部路径。这用于检查此前“GT 明显改善但 exact/+2 不一致”的案例能否被第三种上下文安全恢复。

## 5.6 Clean-control harm

从 GT 正确且连续的内部区域抽取 clean control，运行同一 local realign。记录：

- 局部 GT 是否恶化；
- 三上下文是否一致；
- 非 GT 生产门是否可能误接受。

clean control 永远不允许写回，仅用于估计误伤风险。

## 5.7 Automatic detector 对 GT 的召回与误报

分别计算：

- case-level precision/recall；
- unit-level precision/recall；
- 自动范围与 GT 错误范围的交集；
- 自动候选来源和拒绝原因。

GT-oracle 仍只评价 local-realign 能力，不与 automatic 生产效果混合。

## 5.8 跨窗口 pending confirmation shadow

当自动候选在当前窗口缺少右稳定段时：

1. 只形成 counterfactual safe commit cursor；
2. 不修改正式结果；
3. 使用下一音频窗口从左稳定段附近重新输入 pending 与后续歌词；
4. 检查下一窗是否恢复出 target 之后的右稳定段；
5. 若恢复，运行 exact/+2/+4 local realign；
6. 保存 GT/结构与是否 shadow-resolved。

这回答“等待下一窗是否能解决 no-right-anchor”，但尚不实现正式串行 pending 状态。

## 5.9 尾部两窗回退 shadow

仅在最后两个窗口出现严重诊断或至少 4 个零时长单位时触发，避免每首歌额外跑两窗。根据两窗核心时长给出保守歌词分配，分别重跑并形成 counterfactual 合并结果。

它只评价回退是否可能有价值，不是最终的串行合并实现。

## 5.10 Automatic incomplete shadow

除构造的格式验证外，对严重且未解决的自动候选生成：

```text
automatic_incomplete_shadow/alignment.json
```

其中保留候选前的已解决前缀，标记 `automatic_shadow_only=true`。它不替换 B2 成品，用于验证真实异常是否能进入 fail-closed 下游。

## 5.11 历史 r2 行为对照

Test Demo manifest 自动登记：

```text
<song>_qwen_fa/alignments/r2/vocal/windowed/alignment.json
```

若存在，输出旧 r2 与当前 B2 的：

- 零时长和结构摘要；
- 最后时间；
- 共同单位数；
- 若该样本有外部 GT，再比较 GT；
- Demo 无 GT 时只作为行为和听感参考。

它用于回答“为什么当前 official 仍感觉略弱”，而不是将旧输出当 GT。

## 5.12 M4Singer 多长度与人工接缝分层

synthetic-long 默认构造 60、120、180 秒目标桶，总 cap 在三个桶之间分配，而不是每个桶重复使用完整 cap。每条保存人工接缝时间，并分别统计接缝 ±1 秒与远离接缝的 GT。

这样可以区分：

- 自然长距离传播；
- 人工拼接接缝；
- 时长增长；
- 单首歌曲或歌手异常。

## 5.13 B1/B2 独立比较

汇总中显式区分：

- 没有文本扩展的 B1 vs B2；
- 发生文本扩展的 B2；
- B0 vs B1。

只有在扩展保护生效或排除危险扩展后，才能将 B1/B2 差异解释为固定边界与静音感知边界差异。

## 6. 实验设计、目的、预期与判读

### E1 多语言全量 Test Demo

**目的：**验证不同语言单位、歌词解析、窗口推进、渲染与结构异常。

**方法：**formal 纳入全部 discovered+prepared Demo；按语言和 unit mode 汇总。B0–B3 只做语言均衡子集，全部 Demo 运行 B2、自动诊断、扩展保护和历史 r2 对照。

**预期：**

- 若某语言稳定段覆盖率或坍塌率明显异常，先检查 tokenizer/单位口径，不直接调整全局阈值；
- 英文的“连续 4 单位”和中文的“连续 4 字”分开解释；
- 日文必须验证 Nagisa 和字体；
- Demo 无 GT 只形成结构与听感结论。

### E2 GT-oracle + 三上下文

**目的：**确认 local realign 的能力上限与上下文敏感性。

**方法：**MIR-1K/M4Singer GT 错误段运行 exact/+2/+4，任意两条一致形成 consensus；比较局部 GT 前后。

**预期：**

- would-write 仍稳定改善：进入单窗自动写回 shadow；
- +2/+4 一致而 exact 不一致：第三上下文可找回此前被拒绝的高收益案例；
- 三条都不一致：输入范围或模型局部推理不稳定，不应放宽写回。

### E3 Clean harm

**目的：**测量“本来正确却被 realign 改坏”的风险。

**方法：**抽取 GT 正确连续内部段，运行同样三上下文和 splice。

**预期：**

- GT 恶化但生产门不接受：门控有效；
- clean control 也可能 would-write：自动写回禁止开启，需加强非 GT 改善判定；
- clean control 普遍不稳定：local input 本身过敏感。

### E4 Automatic detector precision/recall

**目的：**区分“realign 无能力”与“检测器没找到”。

**方法：**自动局部异常与完整 GT 错误 span 对齐，报告 case/unit P/R。

**预期：**

- oracle 可修但 detector recall 低：主要改 detector；
- detector precision 低：检查未来歌词、正常高语速和 official 修补误报；
- detector 只覆盖大坍塌：可作为第一版高精度生产触发，不声称覆盖所有错误。

### E5 Forced future-text expansion + stable-prefix guard

**目的：**验证增加歌词是否破坏已有路径，并评估稳定前缀能否提前拒绝危险扩展。

**方法：**同一窗口 baseline、+25%、+50%，比较已有单位移动、零时长、堆积、GT 和稳定前缀复现。

**预期：**

- +25% 稳定、+50% 崩：建立软上限；
- 稳定前缀先失败再出现坍塌：可作为扩展保护；
- 前缀仍复现但后文坍塌：还需检查 tail stack，不能只靠前缀；
- rap 需要更多文本但保持稳定：不要使用固定字速硬限制。

### E6 Pending confirmation

**目的：**验证当前窗缺右 anchor 时等待下一窗是否能恢复。

**方法：**严重自动候选进入 pending shadow，下一窗 counterfactual 重跑，寻找右稳定段并做三上下文 realign。

**预期：**

- 多数能恢复：实现正式 pending state；
- 下一窗仍无右段：需要粗定位或多 cursor，不应无限扩大窗口；
- GT 改善但结构不稳：仍不自动写回。

### E7 Tail two-window rollback

**目的：**验证尾部歌词积压是否能通过回退两窗而非强制吞完解决。

**方法：**仅严重尾部样本，按两窗时长重分剩余歌词并独立重跑。

**预期：**

- GT/结构明显改善：实现正式串行回退；
- 仍失败：输出 automatic incomplete；
- 只有 synthetic-long 接缝改善：不要外推到自然歌。

### E8 历史 r2、B0/B1/B2/B3

**目的：**拆分旧 r2 感觉更强的来源。

**方法：**同歌比较历史 r2、60 秒固定、30 秒固定、30 秒静音感知、raw control；标记是否发生文本扩展和 planner 分歧。

**预期：**

- B0/B1 接近历史 r2，B2 仅在扩展样本退化：主因是扩展/提交；
- B1 也弱于历史 r2：检查实现细节而非窗口长度；
- B2 在无扩展时仍弱：再研究静音边界；
- B3 普遍更差：raw 继续仅作诊断。

### E9 M4Singer 60/120/180 秒

**目的：**验证错误随时长、窗口数和人工接缝的变化。

**方法：**分桶、按 song 汇总、接缝近/远分开。

**预期：**

- 只在接缝附近退化：synthetic artifact；
- 远离接缝也随时长增加：串行传播或长上下文问题；
- 单一歌曲主导：不能宣称普遍时长规律。

## 7. 执行与恢复

```bash
cd /home/hyan/LyricAlignment
bash scripts/demo/run_inline_realign_smoke.sh
bash scripts/demo/run_inline_realign_formal.sh
```

formal 默认使用全部发现到的 Test Demo。可选发布方式：

```bash
# canonical 单独输出目录，默认
DEMO_PUBLISH_LAYOUT=central bash scripts/demo/run_inline_realign_formal.sh

# 在每首歌曲旁发布轻量链接视图
DEMO_PUBLISH_LAYOUT=adjacent bash scripts/demo/run_inline_realign_formal.sh

# 发布到统一目录
DEMO_PUBLISH_LAYOUT=directory \
DEMO_PUBLISH_ROOT=/home/hyan/Data/lyricalign/test_inline_results \
  bash scripts/demo/run_inline_realign_formal.sh
```

阶段顺序：

```text
01_manifest
02_experiment：全部 align 与 shadow 诊断
03_render_demo_after_all_alignments
03b_publish_demo_outputs（可选）
04_summarize
05_collect
```

相同 request hash 的 branch 和辅助实验可复用。每次新运行清除旧 terminal failure/complete 标记，但不删除成功产物。

## 8. 通过条件

Smoke 至少要求：

- 每个当前发现到的语言至少 1 首；
- Japanese tokenizer 可用；
- GT-oracle、clean control、稳定段 paired rerun、+25/+50 至少各产生可解释结果或明确的无候选原因；
- 没有 `start_sec` schema 失败；
- 全部 align 后才 render；
- 发布视图不复制视频；
- evidence 不超过默认 8 MiB。

Formal 要求：

- 全部 discovered+prepared Demo 进入 manifest，没有写死数量；
- MIR-1K held-out 仍冻结；
- automatic/oracle/clean 分开；
- pending、rollback、incomplete 均标明 shadow；
- 按语言、unit mode、自然/合成、接缝近/远、时长桶分层；
- partial failure 不吞掉已完成结果，辅助实验彼此隔离。

## 9. 仍未开启的生产行为

本归档实现了验证所需 shadow，但仍明确没有：

- automatic local writeback；
- 正式串行 pending state；
- 正式两窗口 cursor 重分配；
- 正式尾部回退；
- automatic incomplete 替换成品；
- 多候选 cursor beam；
- 基于完整 logits 的全局最优 official+ 解码。

这些必须依据本轮 GPU 结果分别决策，不能因为代码已能运行 shadow 就宣称方案有效。

## 10. 归档原则

归档包含源码、配置、测试、过程记录、实验设计、执行入口、结果 schema 和验证记录；不包含音频、视频、模型权重、数据集、checkpoint、运行缓存或大日志。证据包继续限制大小，音视频通过服务器路径和 hash 追踪。
