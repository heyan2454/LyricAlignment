# 自由探索记录（2026-08-09 晚）

探索阶段：二次补充实验完成后，主 agent 管控，多个 explore/review 子 agent 从不同角度自由探索。
目的：寻找值得深挖的研究问题、潜在缺陷、仓库可清理项。

## 探索 1：对齐大主题 / Forced Aligner 能力边界（explore agent）

### 发现
1. **三种 decoder 语义差异**（align_qwen_fa_serial_demo.py:382-401）：raw=80ms 网格 argmax、official=processor 连续值、gpu=网格。行内天然带三套对照。
2. **80ms 网格 vs 100/250ms 阈值耦合**：raw 一次 1 格错误(80ms)即掉出 Safe(100ms)。full-song raw 0.1s→12.3%、0.2s→25.6%，跃升≈1-2格，提示大量"量化误差"。
3. **sparse_slots 雏形已存在**（research_v7/sparse_slots.py retain_timestamp_slots），slot_planning.py 完整但未接线。
4. **margin/entropy 特征在类别空间而非时间空间**计算，top-2 恒差 80ms，对 detector 信息量有限。
5. **"我们都太倔强"整段全错根因线索**：query 头部含未演唱歌词（extra_left_units=4/19），模型被迫对齐未唱字 → 系统性偏移 + amplifying 级联。
6. **长静音压缩映射脆弱**（_remap_compressed_alignment 硬编码 key 名单）。
7. 小死代码：timeline.py:120 三元两分支相同。

## 探索 2：当前实验衍生（explore agent）

### 发现
1. **P 特征构建缺陷**：detector_features.py 的 `_P_NAMES`（top2_gap_sec 等）与 train_detector_v3.py 的 `P_NAMES`（11个）两套体系并存，前者未接线——P 族没吃到 unit topk 结构。
2. **P 单信号只消费 11 维稀疏特征**，full posterior 的分布/直方图未进特征。
3. **recovery retry 覆盖极大**（查 41 unit）但 writeback commit 空 → retry request 构造问题。
4. **interval**：SA60/R95 均不实用，只有 UNCERTAIN 中间态有召回。

## 探索 3：仓库健康（explore agent）

### 可清理清单（分级）
- **A 级（安全）**：long_manifest_60/audio/(419M 音频)、out/formal_run_copy/(186M)、models/qwen_fa_*(safetensors/pt 误跟踪)、ARCHIVE_MANIFEST.generated.json(误跟踪)、evidence_P_*_old.jsonl(3个)、__pycache__/pyc/pytest_cache
- **B 级（需确认）**：supersede 脚本（report_final.py 等）、test_posterior_paths.py vs v2、PATCH_README_*.md 归档
- **C 级（保留）**：runs 四套 session、当前主线脚本、docs 深度上下文

## 探索 4：H/P evidence 数据污染（explore agent）—— 高优先级

### 根因（已确认）
- collect_evidence_v3.py:111 `ev = runner.last_evidence`：run_song 结束后 last_evidence = **最后一个 window** 的 evidence，循环内 4 个 rec 全写同一份。
- 结果：**每首歌 4 个 window 的 evidence_P/evidence_hidden 都指向同一个 posterior/hidden npy**。9/9 首 model_selection 歌曲全部受影响。
- 已用数据证实：newboy 4 窗 n_units=129/152/159/124 但 n_slots 全 248（指向 w3 的 npy）。

### 影响边界
- **受影响**：H/P evidence（evidence_hidden_*/evidence_P_*/evidence_posterior_*）、SIGNAL_COVERAGE_AUDIT 的 H/P 覆盖。
- **不受影响**：R/O/S/label（来自 records 正确）、trajectory、二次补充核心结论（R=0.632、binding、interval、PR、recovery）。

### 修复方案
1. **必改代码**：runner.py 按 request_id 存 evidence（evidence_by_request map）；collect_evidence_v3.py 删除 last_evidence 读取，按 request_id 取；加 n_slots==2*n_units 校验。
2. **恢复路径**：先离线从 cache/forward（464 json，180 含 evidence_v3）恢复正确 H/P；缺失 window 再 GPU 补 forward（~200 次，1-2h）。

## 探索 5：80ms 量化与阈值耦合（explore agent）

### 发现
- raw decoder 确实 80ms 网格（argmax 无二次精化）。
- **后验呈双峰/扩散形态**（如 top1=class27 p=0.70、top2=class0 p=0.13），class 0 特殊桶占显著质量。
- 全窗口期望时间被远端扩散质量拉偏（mean 0.54s），不能直接做亚网格解码。
- **正确口径**：argmax 局部窗口（±2-3 类）重归一化期望 → 位移上界 ±0.16s；需区分"后验集中度"（量化误差≈半格 0.04s）vs "后验扩散"（亚网格解码不可靠）。
- 结论倾向双因子：量化本身小，后验扩散/双峰才是 R=0.632 未达 Safe 的主因。class 0 桶语义需查证。

## 待深挖问题（backlog）
1. **H/P evidence 污染修复**（P0，缓存已齐只需重排索引，无需 GPU）
2. **P 特征接线**（_P_NAMES 死代码 + unit topk 结构利用）
3. **后验 class 0 桶语义**（timestamp tokenizer 特殊桶）
4. **亚网格解码低配实验**（后验集中度 + 局部位移 vs 阈值）
5. **query 头部污染**（extra_left_units → head 修正）
6. **retry request 构造**（query 长度 vs writeback 空率）

## 探索 6：多语言处理细节（explore agent）

### 发现
1. 日文按 nagisa 词为 unit（非字符），中文按字符——250ms 指标对三语言不等价（日文词内误差被内部化）。
2. `don't` 撇号保留，但官方 processor 行为只靠手动脚本验证，无 pytest。
3. `unit_type` 字段（cjk_character/japanese_word/word）在 research_v7 canonical 管道中**未被消费**——多语言粒度信息丢失。
4. `check_qwen_fa_processor_equivalence.py` 是脚本非测试，覆盖单语言单条，无混排 case。
5. 可清理：`.patch_backups/` 下两份旧 align_qwen_fa_serial_demo.py 副本。

## 探索 7：上游数据管线 + 训练（explore agent）

### 发现
1. **M4Singer GT 是规则推导**（ph_dur 累计 + pinyin 映射），标记 rule_validated 非人工。MIR-1K 人工 GT 仅 OOD test。
2. **训练纯中文**（M4Singer zh），日/英多语言是零样本迁移。
3. R2 checkpoint step-000750：seed 20260724、train 17748 条、LoRA 只注入 audio_tower 后 4 投影、best checkpoint 由 validation 选（song_macro_boundary_mae 0.0472）。
4. `m4singer.py:251-257` 有不可达死代码（return 之后的 legacy 分支）。
5. 可清理：路径硬编码分散（/root/autodl-tmp vs /home/hyan/Data 双写）。

## 探索 8：GT 质量影响评估（explore agent）

### 发现
1. **GT 内部自洽**：60 首歌 21715 units 无 zero-duration/负时长/非单调；段级 duration 与 audio offset 完全一致；字符时长中位 0.53s、min 0.266s。
2. **风险在系统性 ph_dur 偏置**（非随机噪声）：若整体缩放偏置，GT 边界误差沿时间轴累积，60s 窗口末尾可达数百 ms——此时 Unsafe 可能反映 GT 偏置而非模型错误。
3. **建议**：用 MIR-1K 人工 GT 作为模型噪声底对照；人工听标抽查 2-3 首 M4Singer。
4. 549/804/2021 的精确出处需定位（grep docs 为空，应在 report JSON）。

## 探索 9：H/P 污染影响复查（review agent）

### 结论
- **污染影响**：H/P 单信号（H 0.521/P 0.465）+ 含 H/P combo → 不可信。
- **不受影响**：R+sel(0.641)、R/O/RO/S 单信号、interval、PR、recovery、binding 549/804/2021。
- **缓存已齐**：555 npy = 185 req × (2 hidden + 1 posterior)，每 window 正确 npy 都在，**只需重排 jsonl 索引，无需 GPU forward**。
- selected=S 稳定性需修复后复核（P 远低，S 应稳定）。

## 探索 10-16（后续批次）

### 探索 10：posterior class 0 桶
- class 0 = 合法最小时间桶 [0,0.04)s（round-half-up），非 sentinel。
- 但低置信时是"不确定汇聚点"：argmax=0 比例 0.3-1.2%，class0∈top3 占 12-22%。
- 高置信 argmax0（p=0.76）是"模型真认为边界在 0 秒"；低置信是"质量扩散到 0 桶"。
- 影响：每 100-300 边界 1 个 raw=0.0s，对 250ms 指标是局部风险；对依赖 topk/entropy 的特征是噪声源。

### 探索 11：亚网格解码实验
- 后验集中度：argmax±3 内质量占比中位 98.8%（≥90% 占 84.9%），后验扩散非主因。
- K=3 亚网格期望 vs argmax：量化位移 p50≈14ms、p90≈36ms、97.6% slot ≤50ms。
- **结论：值得做正式低配实验**（纯 CPU，无需重 forward），预计 Safe 率 +5~15pp。
- 建议 K=3 + 集中度<70% 的 slot 标 unreliable（约 10.6%）。

### 探索 12：retry 失败机制
- 36 windows：83.3%（30/36）是 detector 拒绝（gap 起点 retry 后仍非 ACCEPT），16.7% 对齐无解。
- retry query 覆盖大（中位 30 ids）是成本浪费，非决策原因（build_retry_writeback_plan 只消费 base_cursor 起连续 ACCEPT）。
- 改进：聚焦 gap 的窄 query；retry 失败 fallback（commit=[] 时不覆盖 serial 状态）。

### 探索 13：class 0 与亚网格（补充）
- 训练侧 class 0 合法；official decoder 也是 argmax×80ms + _fix_timestamps（LIS 单调修复），无真插值。

### 探索 14：raw vs official
- 两者同源（都是 argmax×80ms）；official 的连续时间来自 _fix_timestamps 的 LIS 插值/吸附（伪连续）。
- 250ms 层面几乎等价（差 0.1pp）；official 长尾 MAE 略优。
- 建议评测以 official（fixed_global_start_sec）为主目标。

### 探索 15：detector 特征画像（主 agent 计算）
- 8 个 R 特征单特征 AUC 全部 ≤0.58（entropy 0.58 最强、margin 0.45-0.47、top1 0.44-0.47）。
- unsafe 组熵更高（0.86-1.0 vs safe 0.8）、top1 略低 → "unsafe=模型不确定"但区分度弱。
- R=0.632 来自组合，单特征无强判别力 → interval 无实用工作点的根因。

### 探索 16：PR 候选特征（主 agent 计算）
- 首窗 err mean/median/max/std + gap 异常对 high vs non-high 的 AUC 全 ≈0.5（0.48-0.53）。
- **支持"问题本身难"**：决策时首窗信息不足以预测传播风险。PR negative 结论有更强证据。

### 探索 17：H/P 修复 GPU 成本
- 基础 records：185 次 forward（三 role）/247（四 role）→ GPU 0.5-2.7h，远低于 10h 预算。
- 含 76 变体最坏 792 次 → 逼近 8.8h（需确认变体是否也污染）。
- 建议一次性重跑，先实测单次 forward 秒数。

### 探索 18：serial head 策略（H0 vs H1）
- H0（时间驱动）用 input_start 估算头部 → 28 窗口 extra_left>0、总 628 unit 头部污染（9/9 歌）。
- H1（index 驱动：start_row=committed_end-lookback）纯函数、已实现、零成本，根治头部污染。
- **建议优先切 H1**（消除系统性偏移与级联），对 250ms 指标正面。
- t_accept 调整是零和搬移（AUC 0.632 弱信号），不建议动。

## 探索期间的可执行改进（已完成）
1. ✅ RUN_META.json 补全（命令/输入/GPU/已知问题）
2. ✅ SESSION_INDEX 覆盖 08-08/08-09 三 session
3. ✅ A 级清理（_old.jsonl 备份、__pycache__、根目录 md 归档 docs/archive/）
4. ✅ B 级 git 误跟踪（models 权重 17.6M + ARCHIVE_MANIFEST 移出，git 40M→23M）
5. ✅ recovery before/after 同集合对比（worsened 7→3，消除 population mismatch 伪退化）
6. ✅ detector 模型持久化（detector_mlp_v3_R+sel.pkl）+ 保留 THRESHOLD_VALIDATION_PBAD.json（可追溯性）

## 待执行改进（backlog）
- H1 head 策略切换（零成本，需验证后启用）
- 亚网格解码低配实验（纯 CPU，K=3 + 集中度 gate）
- H/P evidence 污染修复（185-247 forward，GPU 0.5-2.7h）
- retry 窄 query + fallback 语义

## ⚠️ 关键科学边界发现：GT 口径

### LONG_TIMELINE_MANIFEST 是 synthetic-uniform，非真实 GT
- `timeline.py:106-107`：段内字符均匀分配（per = dur/len(units)），所有 interval 恒等于段时长/字数。
- 验证：newboy 前 10 字符 interval 全 0.4171s；segment_offsets.duration 与字符均匀分配完全一致。
- 真实 GT 在 `/home/hyan/Data/lyricalign/derived/m4singer_character_v2/`（ph_dur 累计推导，rule_validated）。

### 真实 GT 覆盖不足
- 193666 字符中仅 38967（20%）有可用时间边界（accepted_rule_based），80% review_required（end_sec=null）。
- model_selection 9 首歌：真实 GT 覆盖 43-260 字/歌，总计 ~718/3374（21%）。
- "我们都太倔强"仅 46 真实字，"歌颂者"仅 3 字。

### 对二次补充结论的影响
- **549/804/2021、R=0.632、interval 等全部基于 synthetic-uniform GT**（唯一可复现全量 GT）。
- uniform 轴对**相对比较**（serial vs full-song、raw vs official、binding 修复前后）有效。
- 但**绝对 Safe/Grey/Unsafe 划分**有 uniform 假设误差（真实演唱时间非均匀）。
- 探索 agent 指出代码注释 "synthetic-uniform axes never generate correctness labels"，但当前因真实 GT 覆盖不足而用 uniform 替代。

### 建议
- 报告标注 GT 口径为 "synthetic-uniform (segment-uniform) 轴"，明确绝对标签的口径边界。
- 未来可用 21% 真实 GT 作为校验锚，评估 uniform 假设误差。
- MIR-1K 人工 GT（OOD）是唯一全人工参照。

## 探索 19-21（GT 边界与 seam）

### 探索 19：真实 GT 校验锚可行性
- uniform GT 误差 = 段内累积型锯齿波（段首≈0、段中达数百 ms、段尾归零），非全局系统偏差。
- 真实 GT 仅覆盖 718/3374（21%），歌颂者 3 字、newboy 43 字，统计弱。
- 标签翻转估算：718 字符中约 1/3-1/2 会因 GT 选择翻转（Safe↔Grey、Grey↔Unsafe 边界）。
- **主结论稳健**：AUC≈0.5、Pareto gap 是分布性质，uniform 误差只轻微扰动，不翻转结论。

### 探索 20：CNN1D 失败归因
- **主因 = 训练不足**：CNN1D 实际只有 40 次优化步（26 歌聚合每 epoch 一步）vs MLP 数百步。
- pad 浪费次因；S 特征弱（0.541）但非序列问题。
- 结论：序列建模当前不值得继续（S 弱 + 数据小 + 训练预算不对等）；若重试需 opt.step 每歌 + dynamic pad + 对齐 MLP 训练量。

### 探索 21：seam 拼接与对齐
- M4Singer seam 是 0.5s 人工静音；窗口默认不吸附（min_silence=0.8 > 0.5）。
- seam 是 uniform GT 假设最差处（0.5s 跳变），seam 邻域字符边界误差系统性偏大。
- 建议：报告标注 GT 口径 + 跨/不跨 seam 窗口分层；不建议默认吸附（打乱均匀窗口）。

### 探索 22：serial route/head 策略
- 四 route：none/L/W/shadow；L=安全前缀+gap，W=整窗 REJECT，shadow=L 不写回。
- R=0.632 是信号可分性非提交阈值；调 t_accept 是零和搬移（弱信号）。
- **H1（index 驱动 head）零成本根治头部污染**：28 窗口 extra_left>0、总 628 unit 头部污染（9/9 歌）。
- 建议优先切 H1；t_accept 不动。

## 探索 23-25（验证批次，主 agent 计算）

### 探索 23：H1 头部策略量化（主 agent）
- H0 头部污染 638 unit（28 窗）→ H1 降至 220 unit，**消除 418 unit（65%）**。
- H1 仍保留 220 因 committed_end 本身偏移。9/9 歌都受益（每歌消除 18-59 unit）。
- **确认 H1 是零成本高收益改进**，登记为建议启用项。

### 探索 24：亚网格全量评估（主 agent）
- 5 个 posterior：亚网格位移 p50≈10-15ms、p90≈34-39ms、>50ms 仅 1.3-3.8%、>100ms 几乎 0。
- **确认亚网格解码值得做正式低配实验**（可消除大部分 80ms 量化误差）。

### 探索 25：posterior 集中度特征（主 agent）
- 集中度中位 0.988（84.9%>0.9）、7.6% 严重扩散（<0.5）。
- **集中度与 top1 强相关**（<0.5 时 top1=0.10，>0.9 时 top1=0.76）→ 可能非独立增量特征。
- 次峰/主峰中位 0.009，11%>0.1。
- 结论：posterior 集中度相对现有 top1/entropy 的增量可能有限。

### 探索 26：unsafe 失败形态细分（主 agent）
- 2183 unsafe units：**local_shift 53%**（err 中位 0.59s）、gap_anomaly 18%、large_jump 16%、window_edge 12%、inversion 0.4%。
- **多数是 0.25-1s 局部偏移，非大跳变** → detector 应细化局部偏移修复，而非 head/cursor 大修。

# 🔴 重大发现：评估 GT 选择根本性错误（探索最高优先）

## 核心事实
- **LONG_TIMELINE_MANIFEST（synthetic-uniform）是错误评估 GT**：段内均匀分配（timeline.py:106-107），不是真实演唱时间。
- **真实 GT（20260723_m4singer_overlay_slur_time_v1）覆盖 97.2%**（accepted 228905，review 仅 2.8%），模型对齐与真实 GT 误差中位 **20-30ms**。
- 真实 GT 的 start_sec 是**段局部时间**，需 + segment_offsets.global_start_sec 才与全局时间对齐。

## 决定性数据（主 agent 计算）
### synthetic-uniform GT（当前实验用）
- model_selection: n=3374, labels={safe:549, grey:804, unsafe:2021}, err_med=0.322s, unsafe250=59.9%

### 真实 GT（pinyin overlay, 段偏移修正）
- model_selection: n=3228, labels={safe:3093, grey:97, unsafe:38}, err_med=0.025s, unsafe250=1.2%
- 抽查：newboy 前 12 unit er≤70ms；圣诞结 err_med 0.020s unsafe 1.7%；宿敌 0.030s unsafe 1.6%

## 含义
1. **模型对齐质量实际极好**（95.8% unit <100ms），被 uniform GT 严重低估（60% 被误判 unsafe）。
2. **二次补充及之前的 549/804/2021、R=0.632、detector 消融、interval、retry 全部基于错误 GT**。
3. uniform GT 的"40% 250ms correct"是均匀假设误差，不是模型真实表现。

## 为什么之前用 uniform GT
- 之前误认为真实 GT 覆盖不足（读了过时的 m4singer_character_v2，只有 20% accepted）。
- 实际现行 overlay（20260723）已覆盖 97%，完全可用。

## 后续动作（最高优先）
1. 用真实 GT 重新评估 model_selection 的 250ms 正确率、三态标签、detector AUC。
2. 检查 LONG_TIMELINE_MANIFEST 为何被选为评估 GT（代码/文档溯源）。
3. 所有下游结论需在真实 GT 下重算。

## 重大发现复核结果（review agent + 主 agent 反证）

### 反证点已闭合
- `original_global_start_sec` 是**模型预测**（非从真实 GT 复制）：与真实 GT 有差异（如 cid=1: 0.08 vs 0.10、cid=5: 1.84 vs 1.81），差异 <40ms（80ms 网格半格量级）。
- 模型预测与真实 GT 极接近 → **模型对齐质量确实好**，发现成立。
- 代码已内建声明 uniform 轴非 GT（evaluate_long_slot_gt.py:19-20 gt_axis_note="synthetic_uniform_timeline_axis (not human GT)"）。

### 真实 GT 下 detector 重新评估
- 真实 GT 下冻结 detector(R+sel) AUC = **0.569**（vs uniform GT 0.641），但仅 38 unsafe 样本（正负 81:1 不平衡）。
- 单特征：raw_start_entropy AUC=0.986（38 unsafe vs 3093 safe），top1 AUC=0.036——真实 unsafe 特征区分度强，但样本极少。

### 核心结论转变（可能推翻当前主线）
- uniform GT 下：60% unsafe、"对齐差"、需要 detector/retry 修复。
- 真实 GT 下：**1.2% unsafe、模型对齐极好（95.8% Safe）**，detector/retry 针对的是被 uniform GT 误标的假错误。
- **整个 research_transition_recovery_detector 主线可能基于"对齐质量差"的错误前提**。

### 待办（最高优先）
1. 溯源 uniform GT 为何被引入评估链（LONG_TIMELINE_MANIFEST 的来源决策）。
2. 用真实 GT 重算全部下游（549/804/2021、detector AUC、interval、recovery、PR）。
3. 评估是否推翻当前主线结论。

## 溯源最终结论（explore agent）

- **uniform GT 是历史接线错误**，非有意评估基准。
  - research_v7 18/19 号合同明确："M4 detector 训练只能用真实可追溯 unit GT。均匀合成时间轴仅可做行为/跨视图研究，不得生成 100/250ms correctness 标签"。
  - `audit_detector_v2_gt_split.py:15` 声明性排除 synthetic-uniform 轴。
  - 但 transition-recovery-detector 主线误用 LONG_TIMELINE_MANIFEST 作为评估 GT（549/804/2021、R=0.632 等）。
- **真实 GT 早两周就绪**：20260723_overlay_slur_time_v1（97.1% accepted）于 07-23 完成；LONG_TIMELINE_MANIFEST 08-05 冻结。真实 GT 全程可用且与 R2 训练同源。
- 原因：误读 m4singer_character_v2（过时，20% accepted）以为覆盖不足，实际 overlay 已 97%。
- 替换成本：中低（GT 投影/段偏移加载器 + 3 处接线），但下游全部需重算。
