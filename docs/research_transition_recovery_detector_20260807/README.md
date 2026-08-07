# 2026-08-07 Transition–Recovery–Detector 新阶段

本目录是独立于 `research_v7_align_behavior` 和 `research_fullslot_serial_detector` 的新 session 设计目录。它吸收 2026-08-07 最新讨论后重新分层：**先比较 Align / Transition 本身，再研究传播与 Recovery；旧实验缺陷单独补齐；Detector 作为并行研究线，最终只在少数代表 Transition 上闭环。**

旧 `docs/research_fullslot_serial_detector/` 保留为历史设计，不直接覆盖；其中仍有效的 B4、Detector V2 证据、W/L route 想法可以引用，但若与本目录冲突，以本目录为准。

## 阅读顺序

1. `00_FACTOR_MODEL_AND_FREEZE.md`：系统分层、冻结 baseline、哪些是主轴/次轴；
2. `01_MASTER_EXPERIMENT_PLAN.md`：三条研究线及总执行顺序；
3. `02_TRANSITION_RECOVERY_MAINLINE.md`：主线 A，Transition → propagation → Recovery；
4. `03_LEGACY_GAP_COMPLETION.md`：基础线 B，补齐先前实验缺陷；
5. `04_DETECTOR_RESEARCH_PLAN.md`：研究线 C，SA60/SA80/R95 与新信号；
6. `05_DATA_METRICS_BUDGET.md`：数据角色、指标、缓存、公平性与 12h 预算；
7. `06_AGENT_EXECUTION_CONTRACT.md`：Agent 强制执行合同、新 session 目录、不中途停止、resume/失败处理；
8. `../sessions/20260807_transition_recovery_detector_discussion_record.md`：本轮讨论过程、用户观点、疑问、修正与所有提出想法。

## 当前最高层研究结构

```text
Audio preprocessing
    original
    long-silence compressed (main; retain 3–5 s)
          ↓
Window planning / handling
    silence snap (main)
    fixed window (small control)
    skip silent windows
    leading-silence handling
    short-tail redistribution / merge
          ↓
Window input
    left 10 s + core 60 s + right 10 s
          ↓
Align query
    full-slot (main)
    non-slot (small control)
          ↓
Decoder
    raw (research main)
    official (secondary / reference / needed output)
          ↓
Transition
    T0 independent / non-serial
    T1 direct serial
    T2 core+boundary serial
    T3 stable-boundary serial
          ↓
Detector operating point
    SA60 / SA80 / R95
          ↓
Recovery / control
    none
    shadow
    L local recovery
    W whole-window recovery
```

这不是 `2 × 4 × 2 × 4` 的笛卡尔积。正式执行必须按阶段筛选：先用统一 full-slot baseline 比较四种 Transition；之后只选一个 product candidate 和一个 mechanism candidate 进入传播、Detector 与 Recovery 主实验。

## 新 session 运行要求

Agent 不得继续写入旧 research-v7、旧 detector 或旧 fullslot session 的 OUT_ROOT。所有新结果必须创建在新的 session root 下，格式见 `06_AGENT_EXECUTION_CONTRACT.md`。旧 evidence 只读复用。

## 重要非目标

- 不继续穷举更多普通 Logistic/MLP/GBDT；
- 不继续细调 isotonic calibration 以试图解决 safe-accept；
- 不做 slot density / sparse-slot 大矩阵；full-slot 为主；
- 不做 decoder × transition × threshold × recovery × mutation 全排列；
- 不把简单“尾部加几个零时长”当作主要传播异常；
- 不预设串行一定是最终产品路线；非串行若明显更稳且成本可接受，允许成为最终候选。
