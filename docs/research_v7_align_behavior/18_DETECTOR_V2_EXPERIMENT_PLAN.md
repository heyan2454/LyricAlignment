# Detector V2 冻结实验计划：无 GT 的区间级错位检测

日期：2026-08-05  
状态：下一阶段冻结计划；本文件取代 `13_LONG_SLOT_REGION_ASSESSOR_EXPERIMENT_PLAN.md` 作为 detector 主线入口。旧计划仍保留用于追溯，但不得继续把 mutation family 当作产品输出类别。

## 1. 目标

输入是一个已完成对齐的检测区间，以及该区间对应的一次或多次 align evidence。推理时不得使用 GT。输出必须将输入区间完整划分为：

- `accept`：允许提交；
- `reject`：不允许提交；
- `uncertain`：证据不足或冲突，需要保留、复查或生成一个有限验证请求。

输出是连续、互斥、无遗漏的 canonical-unit 子区间，而不是整条 request 的一个分数，也不是 `missing/replace/extra` 分类。

```json
{
  "queried_intervals": [[120, 180]],
  "accept_intervals": [[120, 143]],
  "reject_intervals": [[151, 166]],
  "uncertain_intervals": [[143, 151], [166, 180]]
}
```

本阶段只研究 detector，不要求自动修改 alignment。最终必须增加真实串行闭环，验证三态输出能否减少错误提交和传播。

## 2. 产品假设与主任务

产品默认用户歌词文本及顺序正确。主问题是：

- 正确文字被对齐到错误时间；
- 对齐到另一遍副歌或相似段；
- crop、cursor、commit 或前窗状态错误造成整体/局部错位；
- 弱人声、伴唱、高语速、长音等导致时间选择错误；
- sparse/full、相邻窗口或不同请求视图下结果不稳定；
- 局部坍缩、挤压、重叠、拉长或整体平移。

因此正式标签是 `alignment correctness`，不是 mutation family。`replace/missing/extra` 只作为压力与迁移测试。

## 3. 上一轮结果的强制修正

以下指标不得继续作为 detector 结果：

1. `wrong_output_recall`：旧实现等于被替换 unit 的 slot/query coverage；full=1 是设计必然，无检测意义；
2. 尾部 `gap_recall=1`：旧实现只检查最后输出是否早于窗口结尾 1 ms，且全部 missing 位于尾部；
3. baseline/extra 的空正例 `recall=1`；
4. `formal_approved=true`：只代表执行/文件 gate，不代表设计、指标与解释完成。

允许保留的旧结果：

- 未查询的 tail-extra context 基本不改变已有 slot；
- tail replace 主要破坏替换区，前缀较稳定；
- slot mask 会改变少量共同 unit，错误文本下更明显；
- 两轮 seam 对照均无明确影响，seam 降为低优先级审计项；
-旧 LogisticAssessor 只说明相同 tail-25%-replace 构造中存在易学的坍缩信号，不能代表产品错位 detector。

## 4. Raw-target 与 Official-target

必须建立两套独立任务：

- `raw_target`：判断模型原始时间选择能否接受；
- `official_target`：判断最终 official 时间轴能否接受。

两套任务使用相同 evidence 与 source-song split，但分别根据 raw/official 与 GT 的误差生成标签。不得再只评 official，也不得将二者标签混合。

## 5. GT 三态训练口径

主口径：

- 明确安全：onset 与 offset 都 `<=100 ms`，时间有效，未选错 occurrence；
- 明确错误：任一边界 `>250 ms`，或输出缺失、严重逆序/越界、选错重复段、连续整体错位；
- GT 灰区：100–250 ms，训练第一版忽略，测试单列。

同时报告 100/250/500 ms 敏感性。GT ambiguity（无法确定重复段目标）不得强行标安全/错误，应进入独立 ambiguity cohort。

## 6. 实际异常 Cohort

禁止全笛卡尔积。每个 cohort 只改变一个主要因素，并保留 matched legal baseline。

### A. 正常合法输入

覆盖 early/middle/late、低/中/高语速、长音、短字、静音边界、伴唱较多、full/sparse 和重叠窗口。用途是正确接受率与误拒/存疑代价。

### B. 音频 crop 错位

歌词正确，只改变 crop：

- start-late：+0.5/+1/+2/+4/+8 s；
- start-early：-0.5/-1/-2/-4 s；
- end-early：提前 0.5/1/2/4/8 s；
- end-late：延长代表档。

`end-early` 为强制主条件，因为它会把尚未唱到的尾部错误提交并污染下一窗。

### C. 文本 cursor/区间选择错误

歌词文件正确，但当前请求从错误 canonical 位置开始：±1/±2/±4/±8 units。要求区分错误起点、重新重合区与持续错位区。

### D. 重复副歌与相似段

构造目标 occurrence 明确的请求：第一次/第二次、crop 同时覆盖两个 occurrence、前文充分/不足、full/sparse/review slot。重点检测内部规整但整体选错 occurrence 的结果。

### E. 串行传播

至少连续 4 个 60 s 窗。第 2 窗注入一次 cursor/time/end-early/错误 commit，第 3–5 窗不得用 GT reset。记录 detector 首次报警、错误提交前是否阻断、传播 units/windows、恢复与 unresolved。

### F. 声学困难

文本和位置正确，只改变声学证据：局部人声缺失/削弱、伴唱/和声覆盖、轻/明显混响或分离残留、自然高语速/长音/高误差区。先验证 processor 归一化不会抵消扰动。

### G. Slot/窗口多视图

同一 canonical unit 生成 matched views：full、selected sparse、连续 sparse、当前区+历史复查区、相邻窗口重叠、单独请求/联合请求、0 或固定 future context。跨视图差是核心无 GT 信号。

### H. 文本扰动压力测试

不作为产品主训练来源。必须补齐上一轮遗漏：

- 随机 1/2/4/8 units；
- 分散、短连续块、头/中/尾；
- 同歌其他位置、跨歌真实文本、同音/近音；
- 10/25/50% 比例对照。

Missing/extra 只作迁移与反例，不得再用 slot coverage 或尾部空白冒充 detector。

## 7. 无 GT Evidence

### H：Hidden

先完成 token→output-row→canonical-unit 映射及 hook 数值等价审计。至少提取最后一层与倒数四层的 start/end boundary hidden，保存原始投影或可重建摘要。

单 unit/邻域特征：norm、variance、start-end cosine/L2、层间变化、相邻一/二阶差、局部突变、train-only PCA/Mahalanobis/kNN 距离。跨视图比较 hidden cosine/L2 与层间演化一致性。

必须保留直接 hidden linear probe，避免只依赖手工统计。

### R：Raw/posterior

- entropy、top1-top2 margin、top-k span/variance、多峰性、头尾概率质量；
- raw onset/offset/duration、零时长、逆序、gap/overlap、局部 unit/s 与一/二阶变化；
- 跨视图 onset/offset、posterior 距离、top1 改变、共同 top-k 候选。

### O：Official/repair

- official 时间与局部几何；
- raw→official start/end shift；
- repair 连续长度、局部 repair 比例、同点压缩；
- official 跨视图差。

### 结合信号

必须显式研究，而不是只拼接：raw 确定但 official 大改、raw 不确定但 official 平滑、hidden 异常+raw 不确定、H/R 稳定但 O 不稳定、H/R 不稳定但 O 稳定、start/end 证据冲突等。

## 8. 单视图与有限多视图

分别报告：

1. 单视图 detector：一次 align 后直接判断；
2. 多视图验证：单视图存疑区最多增加一个冻结的验证 request，再输出三态。

多视图必须报告额外 forward、耗时、存疑转 accept/reject 的比例。若只有多视图能发现整体错位，应将 detector 定义为有限验证协议，而不是单次分类器。

## 9. 模型阶梯与消融

旧 E1 detector 不得导入，旧 risk score 不得作为特征。硬接口错误（缺行、NaN、严重越界）可独立 fail-closed。

同一 evidence、同一 split 上比较：

1. 单信号图谱与 rule baseline；
2. 标准化 Logistic；
3. 受限 GBDT；
4. 小型 MLP/hidden probe；
5. 一个冻结的小型区间序列模型（1D CNN、双向序列或小 Transformer pilot 后三选一）。

强制 H/R/O 消融：H、R、O、H+R、H+O、R+O、H+R+O、H+R+O+V（V=跨视图）。raw-target 与 official-target 全部重复，但复用 evidence。

## 10. 三态阈值

模型输出 `p_bad(unit)`，validation 冻结：

- `p_bad <= T_accept` → accept；
- `p_bad >= T_reject` → reject；
- 中间 → uncertain。

`T_reject` 主要约束错误捕捉；`T_accept` 主要约束错误被错误接受。OOD、证据缺失、视图冲突、模型冲突强制 uncertain。只允许“填 1 unit 小孔、reject 两侧最多扩 1 unit 为 uncertain”的轻度合并，不得大范围扩张刷召回。

## 11. 主指标

禁止只报 AUROC/F1。必须报告：

- unsafe false-accept rate：真实错误 unit 被判 accept 的比例；
- reject recall；
- protected recall：真实错误 unit 被 reject 或 uncertain；
- 正确 unit accept/reject/uncertain 比例；
- 错误保护率—正确接受率曲线；
- reject/protected interval recall@75/@100；
- 长度>=3 的错误区间完全接受率；
- 最长连续漏检长度；
- 预测区间起止与 GT 错误区边界距离；
- source-song micro/macro、family、early/middle/late、full/sparse、raw/official 分表。

Validation 冻结 `protected_recall_95` 与 `protected_recall_99` 两个工作点，同时公开正确接受率与 reject-only recall。禁止通过全部 uncertain 获得高 protected recall。

## 12. 数据与切分

M4 detector 训练只能使用真实可追溯 unit GT。均匀合成字时间轴仅可做行为/跨视图研究，不得生成 100/250 ms correctness 标签。

所有同一 source song 的窗口、mutation、view、声学退化与串行轨迹必须在同一 split。建议 18/6/6 或约 60/20/20。demo 永不参与训练/阈值。

MIR 用于 M4→MIR 与小型域内阈值重校准，必须分 family 报告。弱标签来源单列，不与 M4 精确 GT 混合。

## 13. 跨 family 与跨域

强制 leave-one-family-out：crop、cursor、repeat、acoustic、replace 分别留出。必须分别运行：

- M4 song-heldout；
- M4 family-LOO；
- M4→MIR：baseline、crop/cursor、end-early、repeat、acoustic、replace 1/2/4/8、missing/extra stress；
- MIR 小型 validation 仅重校阈值、不重训模型。

任何一格缺失，detector formal 不得标完成。

## 14. 串行闭环

比较：全部提交、GT oracle、Detector V2 单视图、Detector V2 多视图。accept 才提交，reject 不提交，uncertain provisional；达到有限预算后 unresolved，不无限重跑。

主要指标：错误正式提交率、首次错误提交窗口、传播 units/windows、正确延迟提交、unresolved、额外 request、耗时、困难区后重新入轨。

## 15. 阶段与预算

- Phase 0：契约、GT、hidden、split、coverage、预算审计；
- Phase 1：H/R/O 单信号图谱；
- Phase 2：小型 pilot，冻结模型/特征/视图/阈值/区间合并；
- Phase 3：M4 song-heldout formal；
- Phase 4：family-LOO、M4→MIR、stress、demo 人工复核；
- Phase 5：真实串行闭环。

formal 目标 <=10h，硬上限 12h。H/R/O 消融必须复用同一 forward evidence；多视图只对冻结 cohort 或 uncertain 区运行。超预算先删除极端文本扰动、重复 seed 和次要声学强度，不得删除 hidden audit、实际错位、repeat、source-song split、跨域或串行闭环。
