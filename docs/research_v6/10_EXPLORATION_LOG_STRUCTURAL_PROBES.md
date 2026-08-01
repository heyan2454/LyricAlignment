# Exploration Log — 结构性探针（长期探索记录）

> 目的：在正式实验（formal）并行期间，用**微型、纯 CPU、不占 GPU、不触碰 production** 的探针，
> 检验"框架主干"的隐藏假设，为结构性改造提供依据。
> 本文件是长期追加式探索日志；每个探针独立成节，记「假设 / 方法 / 结果 / 启示 / 下一步」。

---

## 探针 1：错误归因 —— 当前 detector 能否区分「全局边界错位」vs「局部 decoder 失效」

**日期**：2026-08-01
**代码**：`src/lyricalign/align_detect_designs/probes/error_type_discrimination.py`
**运行**：`PYTHONPATH=src python -m lyricalign.align_detect_designs.probes.error_type_discrimination`（纯 CPU，无模型）

### 假设
框架主干把窗口/歌词预分割当作"给定常量"，detector 只做局部风险评定。
据此怀疑：当前特征/`rule_risk_score`（`detector.py:129-242`，只测 raw 局部曲率：
负时长/重叠/回归/零时长、margin、entropy、movement、跨输入/窗 spread、音频支持、local_rate_z）
**无法感知"全局均匀偏移"**（整段边界整体平移，边际与曲率不变），却能定位"局部崩坏"。
若成立，则“边界错位型”错误在当前 detect 层漏网 —— 正是结构改造成照点。

### 方法（合成行，纯几何，非真实 logits）
构造 20 字符基线 → 派生 3 类行：
1. 正确基线；
2. 全局偏移 +1s（所有起止一起平移，模拟窗口/歌词错位）；
3. 局部失效（中段 3 字符 raw 零时长）。
对各派生行跑 `extract_features` + `rule_risk_score`，比较 risk 分布。

### 结果（risk_score: mean / max / high(>0.5) / spread）
| 行类型 | mean | max | high | spread |
|---|---|---|---|---|
| 正确基线 | 0.000 | 0.000 | 0 | 0.000 |
| 全局偏移 +1s | **0.000** | **0.000** | 0 | 0.000 |
| 局部失效(3字zero) | 0.443 | 2.950 | 3 | 2.950 |

判据：局部失效的峰值与 spread 明显高于全局偏移 → **可区分 = True**。

### 结论 / 启示
1. **分离成立，但方向暴露出空缺**：detector 对"全局均匀偏移"完全免疫（risk 全 0），因为
   特征全是局部的"曲率/边际"，没有"全局基线是否整体偏移"的维度。
2. 这正说明当前框架**检测不到由窗口/歌词预分割错位导致的整段平移** —— 与项目一直追的
   ~150s 跨长序列崩溃（`project_current.md:100-106`"尚未支持长稳健全曲对齐"）可能相关：
   长序列里窗口边界的累积错位表现为"整体段平移"，而现有 detect 无感。
3. detector 目前只能回答"哪里局部崩了"，回答不了"当前整体对齐是否整体偏了"。

### 下一步（候选结构性补强）
- 给特征层补一个「全局一致性」维度：跨整个 item 的 raw↔selected 整体偏移量、分段漂移趋势、
  起始/结束锚点偏移的一致方向，使"全局偏移型"也可被 detector 标出。
- 在 `align_detect_designs` 下实现该全局维度的纯函数探针（继续纯 CPU），验证能否让全局偏移
  也被检出，同时不误报局部正常变体。
- 评估它与 E9「跨窗 beam / 一致路径」的关系（一者是全局几何判据，一者是路径探测）。

---

（后续探针按此追加。）

---

## 探针 2：无 GT 全局一致性评分 —— 能否检出「输出整体漂移」

**日期**：2026-08-01
**代码**：`src/lyricalign/align_detect_designs/probes/global_shift_detector.py`
**运行**：`PYTHONPATH=src python -m lyricalign.align_detect_designs.probes.global_shift_detector`（纯 CPU）

### 背景 / 假设
探针1 表明当前 detector 特征全是局部曲率，对全局一致平移完全免疫。
本探针假设：**仅凭 raw 与 selected 的边界差异分布（无 GT、纯几何）**即可把「整体一致漂移」
从基线与局部异常中分开——这可为 detector 补一个全局一致性维度。

### 关键修正（合成口径）
先误用 `global_shift`（raw 与 selected **同步平移**）→ raw−selected 差恒为 0，探针失效。
改为 `selected_drift`：**只平移 final 输出侧**，raw 不动，制造真实“输出整体错位”。

### 结果（无 GT 几何信号）
| 行类型 | mean | spread | right% | flag |
|---|---|---|---|---|
| 正确基线 | 0.0 | 0.0 | 0.0 | ambiguous |
| selected 整体漂移 +1s | **-1.0** | 0.0 | 1.0 | **global_consistent_shift** |
| 局部失效(3字zero) | 0.0 | 0.0 | 0.0 | ambiguous |

### 结论 / 启示
1. **无 GT、纯几何**的全局一致性信号就能把「输出整体漂移」与基线/局部异常区分开：
   所有字符的 raw−selected 差同向且集中（mean 显著、spread 小、同向占比高）。
2. 这是一个成本极低、可离线重算的结构维度（对 03:31 "可离线重算" 友好），
   可作为 detector 新增「全局偏移/漂移」特征，补齐探针1 的盲区。
3. 局限：当前用合成几何验证了"信号可行性"；对真实 logits/窗口错位是否仍有区分度，需在真实数据上验证（占 GPU，留到 formal 结束后）。

### 下一步（候选）
- 把该全局维度做成纯函数并入 `align_detect_designs`（仍是纯 CPU 可测的契约扩展）；
- 真实数据验证前，先用现有 synthetic-long / 窗口错位样本在 CPU 上做一次端到端 smoke。

---

## 方向池（基于探针1/2，开放式、不收敛）

> 探针1/2 已确认一个结构性盲区：detector 只有局部曲率维度，缺「全局一致性/整体漂移」维度，
> 且该维度可被无 GT、纯几何信号补上。以下为**可随时切入、彼此平行**的方向池，不预设终点：

- **方向 A｜全局维度正式化**：把 global_offset/一致性评分做成纯函数并入 `align_detect_designs`
  契约（纯 CPU 可测），并继续探它与其他 detector 维度的交互（叠加/冲突）。
- **方向 B｜真实数据 CPU 端到端验证**：用现有 synthetic-long / 窗口错位样本，不占 GPU，
  验证全局维度对真实几何错位的区分度（探针2 仅合成几何；这是现实性检验）。
- **方向 C｜更多盲区探测**：像探针1/2 那样，继续枚举 detector 可能的结构盲区
  （时间尺度、静音段、重复副歌混淆、跨窗漂移累积）——"找盲区"本身是一条持续线。
- **方向 D｜设计线推进**：D1 反馈闭环细化、D4 状态机 hook 骨架（另一条与探测器盲区独立的线）。
- **方向 E｜契约性质化**：把 align_detect_designs 的契约变成可对 research_v6 真实逻辑单元
  做性质/一致性测试的桩。
- **方向 F｜formal 后真实对比**：formal 完成后，用真实数据/GPU 做全局维度对长序列崩溃的
  相关性验证（后台、届时再看）。

**当前取向**：先从 A 起步（它最直接、纯 CPU、紧扣探针2 结论），但 A–F 均为平行可切入，
依兴趣随时切换；不把任何一项作为"唯一/终结"目标。

---

## 方向 A（已起步）：globasl 一致性维度正式化

**代码**：`src/lyricalign/align_detect_designs/global_dims.py`（GlobalShiftConfig/GlobalShiftReport/global_shift_score/extend_features_with_global），已导出到 `__init__.py`。
**验证**：`probes/global_dims_check.py`（纯 CPU；exit=0）。
**结果**：
- 行为与探针2 一致：基线→ambiguous、selected 整体漂移→global_consistent_shift、局部失效→ambiguous。
- 叠加性成立：`extend_features_with_global` 可并入 `extract_features` 的 per-char 输出，不破坏原局部特征；
  漂移行的 `global_consistent_shift=1`、基线为 0，作为 item 级全局特征广播到每行。
**启示**：全局维度已从"探针验证"升级为"可复用纯函数 + 可并入特征层"。它是 detector 侧可加的
一项结构特征，纯 CPU 可测、可离线重算。后续可在 B（真实数据 CPU 验证）或 C（更多盲区）继续。

---

## 探针 3：分段漂移 vs 整首漂移 —— 全局维度该在什么粒度上算

**代码**：`src/lyricalign/align_detect_designs/probes/segmentation_granularity.py`（纯 CPU）

### 假设
全局一致性维度如果按“整首一个信号”计算，当长序列发生**分段差异漂移**（前段+1s、后段−1s，
或两段同向但幅度不同）时，会因 mean 相抵 / spread 增大而漏检。分段（per-window）计算应能
正确检出每段内部的一致偏移。

### 结果
| 场景 | 整首 global_shift_score | 分段(每段) |
|---|---|---|
| 两段相反(+1/−1) | ambiguous（漏检） | (consistent, consistent) |
| 两段同向(1.0/0.5) | ambiguous（spread 增大漏检） | (consistent, consistent) |

### 结论 / 启示
1. **全局一致性维度应按段/窗口计算，而非整首**：整首单个信号会系统性漏检分段漂移。
2. 这直接指向长序列（~150s、多窗）崩溃的机制假设：窗口边界的累积错位表现为分段式偏移，
   而整首尺度下 detector 无感；**粒度是结构问题，需要 per-window 的全局维度**。
3. 下一步：在 `global_dims` 增加 per-segment 计算（global_shift_score_by_segments），
   并用真实 synthetic-long/窗口错位（方向 B）验证。

---

## 方向 A→C 编码落地：per-segment 全局一致性 API

**代码**：`global_dims.global_shift_score_by_segments(rows, key_fn, ...)`；导出 `SegmentGlobalReport`。
**验证**：`probes/segmentation_granularity.py`（exit=0）。
**结论**：`by_segments` 按 key 分组后各算 global_shift_score，能正确检出两段相反漂移
（整首 ambiguous 漏检），char→segment 映射可用；这是全局维度"按窗粒度"的可复用实现。
**状态**：纯 CPU、不触碰 research_v6；py_compile 全包通过，formal 21392/21562 仍在并行。

---

## 方向 B（真实 long CPU 验证）—— 关键方法学负结果

**代码**：`probes/real_long_global_dims.py`（只读 v3 baseline，纯 CPU）
**结果**：扫 40 个 m4long baseline item → 整首全 ambiguous、按 window 分段平均每项 window=1.0、
无一致偏移段、no_data 健康（exit=0）。
**根因（重要）**：v3 baseline `alignment.json.characters` **并不是全曲对齐行的全集**——
`m4long_000`（名义合成120s、应多窗）实际 characters 仅 95 字符、`window_index` 全 0、
`window_trace` 仅 1 窗。即 `characters` 只含单窗口/被压平的内容，用它做整首或多窗分段
全局一致性会失真。
**教训**：真实多窗口对齐行需从 `window_trace`（或各窗实际 alignment）拼接，不能直接用
`baseline.characters`。这也说明：全局维度的“按窗粒度”验证（探针3 的编码落地）必须建立在
“真是多窗行”之上，而非单窗 flattened 行。
**处置**：方向 B 的“真实数据端到端验证”**归并到方向 F（formal 完成后，用正式 formal 的
多窗合成行做）**；当前不以拼数据管道为代价硬做。全局维度代码（global_dims）保持纯函数、
在合成几何上自洽，等待 F 的真实行再定最终阈值。

---

## 探针 5：时间尺度（节奏）盲区 —— detector 对“放慢”无感、仅对“过快/短时长”有感

**代码**：`probes/tempo_shift_blindspot.py`（合成几何，纯 CPU）

### 方法
24 字符，中段后节奏 [不变 / ×2 放慢 / ×0.25 变快]，均保持单调、无重叠/零时长/回归，
跑 rule_risk_score 看后段风险是否变化。

### 结果（后段相对基线 risk 差）
| 场景 | 均值差 | 后段max | 后段>0.5 数 |
|---|---|---|---|
| 基线 | 0.000 | 0.000 | 0 |
| 慢变 ×2 | 0.000 | 0.000 | 0 |
| 快变 ×0.25 | +0.700 | 0.700 | 12 |

### 结论 / 启示
- detector 对“整体放慢（拖沓）”**完全无感**（0.000）；对“过快”会因 `raw_short_duration`
  触发而有感（+0.70）。
- 即当前 detector 只有“局部曲率破坏”感知（过短/重叠/零时长），**没有“期望节奏/参照节奏”
  维度**，因此对“整体偏慢但仍一致”的节拍拖沓无反应。
- 这与探针1（全局平移）、探针3（分段漂移）同属一类结构缺口：detector 测量的是**内部一致性**
  （曲率/局部离群），而非 **对照期望参照**（期望节奏/期望位置）。这类“缺参照”可能是长歌
  对齐稳定问题的共性根因。

### 方向启示
一个真正的结构补强不是加“更多局部特征”，而是给 detector 引入**期望参照维度**：期望节奏
（节拍/语速先验）、期望位置（锚点/起始时间先验）。这与方向A的“全局一致性”互补：
A 测“输出是否整体自洽”，这里指向“输出是否匹配期望时序”。

---

## 中间总结：探针链的统一论断（里程碑）

**探针 1 / 2 / 3 / 5 + 方向 A / B 的串联判断**：

> 当前 detector 的核心局限**不是“特征太少”，而是“只测内部一致性，缺‘期望参照’维度”**。

| 探针 | 现象 | 归因 |
|---|---|---|
| 1 | 对“全局均匀平移”risk=0 无感 | 缺“期望位置/锚点”参照 |
| 2 / 方向A | raw↔selected 一致漂移可无GT检出 | 可补“输出自洽”信号（内部一致性） |
| 3 | 整首信号对“分段差异漂移”漏检 | 粒度要按窗（per-window） |
| 5 | 只对“过快/短时长”有感、对“放慢”无感 | 缺“期望节奏/参照语速” |
| B | baseline.characters 仅单窗；真实多窗需拼 window_trace | 真实验证要等多窗行 |

- 共通根因：detector 测量的是**内部一致性**（曲率/局部离群/跨输入 spread），
  而非**对照外部期望参照**（期望节奏、期望位置、歌词预期时序）。
- 预测：长歌（多窗、~150s）里，只要错误是“整体自洽但相对期望偏移”（整体偏慢、整段平移到
  错误副歌、分段异幅漂移），现有 detect 都难察觉——这与“尚未支持长稳健全曲对齐”
  （project_current:100-106）的长期未解问题吻合。
- 建议的**结构性补强方向**（与“多加点特征”的不同）：
  1. 给 detector 注入**期望参照维度**（节奏先验、锚点/起始时间先验、歌词预期时序）——
     从“内部是否乱”升级为“相对期望是否偏”。
  2. 全局一致性维度按 **per-window** 实现（global_dims.global_shift_score_by_segments，已就位）。
  3. 真实多窗验证需在 formal 完成后，用 window_trace 拼接的正式行进行（方向 F）。

---

## 探针 6 + 落地：期望节奏参照（外部先验）补上『放慢无感』盲区

**代码**：`expected_ref.py`（ExpectedTempoConfig/TempoRefReport/tempo_ref_score/extend_with_tempo_ref），已导出。
**验证**：`probes/expected_tempo_probe.py`（纯 CPU；exit=0）。

### 结果（期望速率固定为外部先验 = n/duration_sec）
| 行 | expected/s | measured/s | ratio | flag |
|---|---|---|---|---|
| 基线 | 2.034 | 2.000 | 0.98 | normal |
| 慢变×2 | 2.034 | 1.314 | 0.65 | **slow** ← 探针5 盲区已补 |
| 快变×0.25 | 2.034 | 3.286 | 1.62 | **fast** |

### 关键方法学教训（初版失败）
初版把 `duration_sec` 取为**被测行自己的末字符时间**，与实测速率同源 → 恒 normal（同义反复）。
修复：期望节奏必须来自**独立外部先验**（request/window 的计划 total_units/duration_sec），
不能从被测输出导出。这印证"期望参照维度"的正确实现约束。

### 意义
- 直接补上探针5 的"整体放慢无感"盲区，验证了'缺期望参照'这一统一论断可被编码实现。
- 提供 detector 可融合的新参照特征（tempo_* broadcast 到每行），且纯 CPU 可测。
- 局限：真实回跑仍需 formal 后的多窗行（方向 F）定阈值；当前在合成几何上自洽。

---

## 方向 F（CPU 版）：真实多窗 demo 上的全局一致性验证

**代码**：`probes/real_demo_global_dims.py`（只读 v3 baseline demo 多窗项；纯 CPU，exit=0）
**结果**：30/30 真实 demo 项均为多窗（≥2 windows，trace 3-5 窗）；整首与按 window 分段 global_shift_score
全部 ambiguous（未检测到一致偏移）、无 no_data 异常、多窗字段兼容。
**解读**：
- global_dims 对**真实多窗行**健壮可评估（补上方向 B 用单窗 characters 的盲区）。
- 对正常 formal baseline 输出**不误报**为“一致偏移”（阴性正确）—— 一致的 raw↔selected 且
  达幅度的偏移未出现属合理（正式输出大体自洽）。
**局限**：CPU 版只验证“可评估 + 不误报”；真正检验“能否检出真实错误偏移”需对比已知错位样本
（构造窗口错位 或 用 formal 中 E5/E7/E8/E9 的改值行），属 GPU/真实回跑范围，留后续。
**状态**：方向 F 的 CPU 真实验证已完成，转入 git 阶段。
