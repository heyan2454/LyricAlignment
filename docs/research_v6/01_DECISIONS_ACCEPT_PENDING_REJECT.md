# Alignment Research v6：想法决策表

## 目的

本文件记录从 decoder、detector、歌词输入、分窗、静音、串行传播到 realign 的设计取舍。它保留原始想法、用户评价和最终决定，避免后续再次扩张成不可归因的笛卡尔积。

## 接受

| 原始想法 | 用户评价 | 最终决定 |
|---|---|---|
| 充分使用 raw 时间戳与 logits，而非只看 official | raw 已很准，official 主要做合理性修正 | raw/top-K/margin/entropy/结构异常作为 Detector 与新 decoder 的主要证据 |
| local realign 同时保存 raw 与 official | 要知道改善来自输入还是 official | 每次 local inference 强制保存，不额外重复 Qwen 前向 |
| 同时研究直接替换 raw 与替换 official | 两条路线都可能有价值 | 实现 joint start/end、top-K sequence、weighted isotonic、Detector-local repair |
| Detector 检测危险区、安全边界、可修复区 | 当前 Detector 不可直接生产 | 同时输出 risk/safe/repairability 证据，正式阈值由 pilot 冻结 |
| 使用输入扰动与音频支持发现平滑偏移 | 结构合法也可能对错位置 | 实现歌词/音频错配腐化、跨输入差异、RMS/flux/activity 支持特征 |
| 大幅少给歌词并测试少量多次 | 现有只测少量减字 | 实现 -50%/-25%/+25%/+50%、32/48/64 与 96→3×32 |
| Stable 用于动态安全边界，但向前保留 2/4 字 | exact 容易过晚、漏字 | 实现 exact/-2/-4 连续动态窗口，音频与歌词同步 |
| Hard core + soft context | strict 缺少静音后约束 | core 不跨静音，input 可包含静音后 lookahead |
| 长静音 cap 4s/1.5s | 历史 0.4s 太激进 | 实现 full/cap4/cap1.5/历史0.4 对照 |
| 用状态注入与 GT reset 验证串行累计 | 现有只有现象无因果 | 实现 cursor/previous-end 注入与 reset 对照 |
| 研究阶段保存完整反事实，不急于写回 | 当前目的是排查 | 所有候选独立落盘、可视化，正式 baseline 不覆盖 |
| Cursor/window beam 与行级粗定位 | 有工程产品价值 | 实现 E9 pilot，不进入默认生产路径 |

## 待实验

| 原始想法 | 用户评价 | 最终决定 |
|---|---|---|
| local raw 或 local official 谁应作为最终结果 | official 可能再次过修复 | 按 raw好/official好四象限与 GT 改善分析 |
| Detector 用规则、Logistic、GBDT 或序列模型 | 要深入发掘 raw 信息 | 首轮实现规则、Logistic、boosted stumps；序列模型待信号成立后再做 |
| top-K 的 K、beam 与惩罚 | 应避免大网格 | pilot 小范围冻结，formal 不再调参 |
| dynamic boundary exact/-2/-4 | -4 当前较好但未全量 | 全量固定比较，并允许冻结选择器 |
| 32/48/64 如何自动选 | oracle best 不等于可部署 | 同时报告 oracle、规则/Detector 选择、顺序扩展 |
| 静音 lookahead 长度 | 需要静音后约束 | 先固定 8s，后续仅在 pilot 内调整 |
| 错歌词/重复副歌定位 | 结构 detector 无法解决 | E9 行级粗定位作为 pilot |

## 拒绝或暂停

| 原始想法 | 用户评价 | 最终决定 |
|---|---|---|
| D6 raw minimal monotonic | 只是简单前向合法化 | 拒绝；只保留历史结果 |
| 相同输入重新跑 raw 期待改善 | realign 应改变输入 | 拒绝 |
| 当前全局 residual TCN/Transformer 继续扩大 | 已无收益且 cummax 抹平差异 | 暂停 |
| 把 raw/official 当两个独立模型共识 | official 由 raw 派生 | 拒绝作为独立证据，但允许同层候选接口 |
| Official-only Detector | 会丢失 raw 的困难信息 | 拒绝 |
| 旧 raw-guarded 直接自动修改 | PRF 不足 | 只作 Detector 基线 |
| 手工 anomaly 加权作为最终 gate | 权重无 GT 依据 | 拒绝作为主判据，保留特征向量 |
| Stable exact 直接作为默认起点 | coverage 明显下降 | 只作对照 |
| 当前 strict silence 继续使用 | 多变量混杂且秒级恶化 | 拒绝当前实现，改为公平静音实验 |
| C0/C1 0.4s 拼接进入产品 | 过度压缩且不自然 | 仅作历史负面对照 |
| 大量未来歌词作为保险 | 已明显恶化 | 拒绝 |
| plus4/median/deferred/tail rollback 全部常规运行 | 联动与实验量过大 | 暂停，只有腐化诊断可使用 plus4 |
| 多语言完整矩阵作为当前主线 | 主攻中文 | 暂停；保留全量 test demo 执行与统计，不以语言做大网格 |
| 所有变量完整笛卡尔积 | 无法归因 | 拒绝，采用阶段漏斗 |
