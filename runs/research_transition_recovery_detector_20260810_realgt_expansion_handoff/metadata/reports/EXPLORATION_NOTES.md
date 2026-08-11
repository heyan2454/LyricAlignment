# 自由探索报告（after Phase 4.2–4.4）

Run root: `runs/research_transition_recovery_detector_20260810_realgt_expansion_handoff/`
日期：2026-08-11。方向：绒花异常根因 / reagg 失败模式 / detector 先行信号 / B-A 歌集难度差异。

## 1. 绒花 w1/w2 块聚集根因（Agent A + 补充 repair 分析）

- **文本结构**：绒花 136 canonical units，重复「啊」长串 6 组（char 29-36/41-48/75-82/87-94/102-109/114-121）。w2（canon 88-135）几乎全为重复段：`啊×7 + 一路芬芳满山崖 + 啊×8 + 绒花绒花 + 啊×8 + 一路芬芳满山崖×2`。
- **块聚集集中于「啊」重复段**：w2 的「啊×8」串被 Qwen FA 整体压成同一时刻。实测：
  - canon 103-109（啊×7）全部 raw_start=121.35s（GT 应约 137-145s，提前 16-24s）；
  - canon 113-115（啊×3）也叠在 121.35s；
  - canon 117-120（啊×4）全部 161.67s（GT 应约 152-155s，延后 ~8s）；
  - canon 90/92-93（啊）聚在 124.07/128.23s。
  - **聚集行熵极高**：clustered n=14, mean entropy=6.09, mean margin=0.008 vs solo n=34, entropy=3.45, margin=0.240 → detector 能识别。
- **w0 对照**：w0 也有「啊」簇聚集（canon 32-36、40-42）但簇小（≤5）偏移 <2s，hit100≈0.80。**问题随窗位深入而恶化**，不是全曲散布。
- **repair 在 w2 恶化**（关键新增）：raw mean|err|=13.913s → official_fixed 15.188s；improved=7 vs worse=21；mean|repair_shift|=14.37s。w1 raw 1.954s → official 0.770s（repair 有效）；w0 几乎无变化。即 repair 试图摊开聚集簇却过度修正，把低置信区间的位移放大。
- **根因结论**：Qwen FA 对无语义重复元音（啊 hum）存在「时间戳扎堆 + 输出顺序错乱（raw start 差分 min=-48.4s）」，在长窗口的纯重复段上放大为整簇错位；repair 无法挽救反而恶化。这是模型的系统性缺陷，非 GT/管线问题。

## 2. reagg 失败模式 + detector p_bad 关联（Agent B + 修复脚本重跑）

- 分析脚本：`/tmp/opencode/explore_reagg_failure.py`（修复 3 处 bug 后运行）；明细：`/tmp/opencode/explore_reagg_failure.md`。
- **失败是 song×window 结构性，非 baseline/missing**：最差 request 全为绒花:w2（hit100 0.0-0.17，start_mae 13-20s）与绒花:w1（0.42-0.56）；月满西楼:w1 次差（0.55-0.70）。baseline vs missing 同窗 hit100 差 <0.11，无系统性偏差。
- **detector p_bad 是 reagg 失败的行级强先行信号**（A 上 in-sample 拟合 R-combo 6 特征 logistic）：
  - fail@>250ms：AUROC=0.964；fail rows 特征 delta：entropy +2.9/+3.1，top1 -0.43/-0.49，margin -0.35/-0.40；
  - 绒花:w2 rows mean_pb=0.806（fail_rate 95%）vs 全局良好 window mean_pb≈0.05-0.13；
  - 阈值 T_accept≈0.1655：fail@250ms 中 78% 被 reject，ok 中仅 2.7% 误拒。
  - 方向与 v1/冻结一致：高熵 + 低 top1 + 低 margin ⇒ 高 p_bad。
- **含义**：detector 的行级 p_bad 可当作 reagg 输出质量的先行质检（在 GT 不可得时筛选待人工复查的 window/行）。绒花 w2 这类整窗灾难（mean_pb 0.8）应先于 reagg 合并被拦截。

## 3. B/A 歌集难度差异与 detector 训练划分敏感性（Agent C）

- **B 低 unsafe 率 = 歌集难歌少，非预测系统性更好**：
  - B raw unsafe 187 中我爱你中国 1 首占 115（61%），且正是 B reagg 宏观 start_mae=1.305s 的元凶；其余 4 首 reagg 均优（hit100 0.87-0.96, start_mae 0.03-0.06s）；
  - A raw unsafe 323 中绒花 199（62%）+月满西楼 52（78% 集中 2 首）；其余 3 首质量与 B 易歌同档（hit100 0.93-0.98）。
  - 两 cohort 易歌水平相当 → 差异来自难歌/灾难歌分布。
- **validation 统计力不足**：val=真实 1 首仅 29 unsafe（raw）→ frozen protected_recall=0.655 置信区间宽（29 正例 ±18%），95/99 档位相同，阈值基本由 29 个正例钉死；constraint_violated=true 反映 val 正例太少而非模型差。
- **A 作 test 更可信**：672 unsafe（含大量 >250ms 大误差）验证了冻结 detector 的真实拒绝能力，pr=0.904 比 val 0.655 更有代表性。
- **划分偏差方向**：train/val 偏易（B）、test 偏难（A）→ val 低估、test 高估难度分布；当前结论「detector 泛化达标」成立，但 val 冻结点应视为弱锚。
- **建议**（backlog）：val 扩到含难歌（我爱你中国/月满西楼），使 unsafe ≥100 再冻结；或报告中声明 29 正例 CI。

## 4. 结论汇总

1. 绒花灾难根因 = Qwen FA 对「啊」重复段的时间戳扎堆 + 顺序错乱，长窗口纯重复段放大；repair 在 w2 反而恶化。
2. reagg 失败为 song×window 结构性；baseline/missing 无系统偏差。
3. detector 行级 p_bad 与 reagg 失败强相关（AUROC 0.96），可作 GT 不可得时的输出质检信号。
4. B/A 差异源于歌集难歌分布；val 弱锚（29 unsafe），test 强验（672 unsafe，pr=0.904）。

## 5. 补充实验（E1/E2，脚本 `/tmp/opencode/explore_detector_sensitivity.py`）

### E1: OOS window 级 reagg 质检门（fit B train → score A test，全 OOS）
- 用 B train 4 首拟合 R-combo standardized logistic（24 特征），对 A test 90 requests 打分聚合。
- **window 级 AUROC**：mean_pb=0.977、p90_pb=0.978、frac>T_accept=0.983（15 bad windows hit100<0.7 vs 75 good）。
- **gate mean_pb>0.3**：捕获全部 15 个 bad window；75 个 good 中误伤 12（16%）。
- 绒花:w2 六请求 mean_pb=0.76-0.99（灾难级）；绒花:w1 0.51-0.75；绒花:w0 0.25-0.37（false-flag，因该窗 hit100 0.75-0.87 本就平庸）；月满西楼:w1 mean_pb≈0.20-0.26（坏但温和，>0.3 门会漏，frac>Tacc 指标更好）。
- **结论**：detector 行级 p_bad 聚合为 window 级分数可在 GT 不可得时作为 formal 前质检门槛，推荐用 frac>T_accept 或 p90（AUROC 0.978-0.983）。

### E2: LOO B-song 冻结敏感性（min_safe_accept_rate=0.7）
| val 歌 | n_val unsafe | T_accept/T_reject | val pr | A test pr / sa |
|---|---|---|---|---|
| 全世界失眠 | 23 | 0.1424/0.1439 | 0.783 | 0.932 / 0.834 |
| 已是两条路上的人 | 8 | 0.1265/0.1266 | 0.750 | 0.950 / 0.748 |
| 我爱你中国 | 115 | 0.0000/0.0214 | 1.000 | 1.000 / 0.000 |
| 真实（现行） | 29 | 0.1655/0.1684 | 0.655 | 0.904 / 0.900 |
| 阴天快乐 | 12 | 0.1470/0.1480 | 0.833 | 0.932 / 0.837 |

- **关键发现**：所有 LOO 点 constraint_violated=true；val=我爱你中国（115 unsafe）时冻结**坍缩为 reject-all**（T_accept=0、sa=0）。R-combo 特征无法同时满足 pr≥95% 与 sa≥70% 于含大量难 unsafe 的 val。
- 现行「真实」val（29 unsafe）是唯一在 A test 上达到 pr=0.904/sa=0.900 平衡的锚点，但脆弱：val 难度上升即退化。
- **含义**：①冻结点对 val 组成高度敏感，val 须含难歌但其 unsafe 量又不至坍缩（需要比 R-combo 更强的特征，如 G1 hidden H 特征、neighborhood/cross_view 全量组合）；②min_safe_accept=0.7 双约束在 R-combo 上对难 val 不可达 → 要么增强特征，要么调低约束并显式声明 trade-off。

## 6. 绒花:w2 细分窗 GPU 实验（2026-08-11，RTX 3090，real executor）

**假设**：绒花:w2 灾难的根因是长窗口（60s）+ 大量纯重复「啊」段 → Qwen FA 将重复段整体扎堆/塌陷到窗口起点（raw 输出大量钉在 121.35s）。若窗口缩小、重复段被拆开，模型应能正确定位。

**实验**：把 w2（canon 88-135，audio 121.35-181.35s）按语义边界切成 4 个连续子窗（每窗 ≤14 字、≤18s），用同一模型（Qwen3-ForcedAligner-0.6B-hf @ c07281df + r2-step-000750）重新推理，对比 raw 输出与 GT timeline。

| 段 | 内容 | audio 区间 | n | mean_mae | hit100(≤1s) |
|---|---|---|---|---|---|
| seg1 | 啊×7+一路芬芳满山崖 | 121.35-139.0 | 14 | 1.84s | 0.21 |
| seg2 | 啊×8+绒花绒花 | 138.0-156.0 | 12 | 1.28s | 0.58 |
| seg3 | 啊×8 | 155.0-163.5 | 8 | 1.21s | 0.50 |
| seg4 | 一路芬芳满山崖×2 | 163.0-181.35 | 14 | 1.30s | 0.36 |
| **合并** | canon 88-135 | 121.35-181.35 | 48 | **1.44s** | **0.40** |

**对照**（原 60s 整窗 raw）：绒花:w2:full hit100=0.000、start_mae 13-20s；啊×8（canon103-109）整段塌到窗口起点 121.35s，一路芬芳被错推到 163-169s（GT 应在 128-138s），canon110-121 大量重复钉 121.35s。

**结论（决定性）**：
1. **细分窗彻底消除灾难性塌陷**：无任何单位再钉窗口起点；最大误差从 >15s 降到 4.4s，mean_mae 13-20s→1.44s。
2. 剩余误差为「啊」簇内抖动（1-4s），非结构错位——短窗口内每个重复段可被独立锚定。
3. **窗口规划策略有效**：对长窗 + 重复段内容，应按语义/时间把 60s 窗切成 ≤20s 子窗（尤其「啊×N」跑长段），raw 级 hit100 即从 0 到 0.40。
4. 该修复无需换模型/重训，纯 window-plan 层即可实施——backlog #1 有明确可行解。

实验产物：manifest `/tmp/opencode/rerun_w2_subwindow.jsonl`，运行输出 `/tmp/opencode/w2_subwindow_run/`（evidence 含 raw rows），评价脚本 `/tmp/opencode/eval_subwindow.py`。

## 8. Detector 特征增强无法修复 LOO 冻结坍缩（2026-08-11，CPU 消融）

**问题**：E2 发现 R-combo 在 LOO B-song 下 5/5 全部 constraint_violated（`我爱你中国`/`真实` 作 val 时 T_accept→0 坍缩 reject-all）。假设「特征不足」导致，做特征集消融。

**实验**：特征集 `R / R+repair / R+crossview / R+neigh / R+all`（53 特征全量），每个对 5 首 B 歌 LOO（train 4 → freeze on val, min_safe_accept_rate=0.7）。

| 特征集 | n_feat | constraint_satisfied |
|---|---|---|
| R（raw_*，E2 基线） | 24 | 0/5 |
| R+repair | 28 | 0/5 |
| R+crossview | 28 | 0/5 |
| R+neigh | 37 | 0/5 |
| R+all | 53 | 0/5 |

**关键观察**：任何特征集下，val=我爱你中国（unsafe=115）都迫使 T_accept=0.000（reject-all，sa=0.000）；val=真实（unsafe=29）在 R+all 下 pr=1.000 但 sa=0.068。R+all 在全世界失眠上 pr 升到 0.870（vs R 的 0.783）但仍 viol=True。

**结论（证伪特征假设）**：冻结坍缩不是特征表达问题——判别特征再多，`min_safe_accept_rate=0.7` 的冻结约束在 unsafe 占比极高/分布悬殊的歌作 val 时依然不可满足。结构性因素：① val 的 unsafe 绝对量/占比（我爱你中国 115 vs 其余 8-29）主导冻结点；② 现有 frozen-p 阈值对 pr/sa 双约束无可行解。缓解方向应转向冻结机制本身（如 val 内按歌分层冻结、放宽 sa 或用 ROC 平衡点替代硬约束），而非加特征。此 backlog 条目（"增强特征缓解 E2"）证伪关闭。

产物：`/tmp/opencode/explore_featuresets.py` + `/tmp/opencode/explore_featuresets.md`。

## 9. P0：light_merge island-fill 破坏保护优先召回（2026-08-11，CPU 核验 + 修复模拟）

**发现**：冻结机制子 agent 指出 `light_merge`（`src/lyricalign/research_v7/detector_v2_intervals.py:40-69`）的 island-fill 会把孤立单点 REJECT 夹在两侧 ACCEPT 时改写成 ACCEPT。独立核验确认这是**保护优先契约违反**：

| val 歌 | raw pr（无 merge） | merged pr（现行） | raw sa | merged sa | unsafe_accept raw→merged |
|---|---|---|---|---|---|
| 全世界失眠 | **1.000** | 0.783 | 0.825 | 0.844 | 0→5 |
| 已是两条路上的人 | **1.000** | 0.750 | 0.902 | 0.931 | 0→2 |
| 真实 | **1.000** | 0.655 | 0.906 | 0.869 | 0→10 |
| 阴天快乐 | **1.000** | 0.833 | 0.880 | 0.902 | 0→2 |
| 我爱你中国 | 0.991 | 1.000 | 0.000 | 0.000 | 1→0 |

即在**保护优先点**（min_safe_accept_rate=0，pr 应为 1.000）上，island-fill 把 unsafe 单点 REJECT 翻转成 ACCEPT，导致 pr 掉到 0.65-0.83。这解释了 E2「冻结坍缩」为何特征/机制都无解——freeze_thresholds 在 merge 后验证 pr 不达标，回退保护优先点仍不达标。

**修复模拟**：island-fill 只填 ACCEPT 岛、REJECT 岛永不翻转（REJECT 是保护信号），LOO（min_safe=0.7）结果：

| val 歌 | T_accept | T_reject | pr | sa | viol |
|---|---|---|---|---|---|
| 全世界失眠 | 0.1424 | 0.1439 | 1.000 | 0.556 | True |
| 已是两条路上的人 | 0.1265 | 0.1266 | 1.000 | 0.749 | **False** |
| 我爱你中国 | 0.0000 | 0.0214 | 1.000 | 0.000 | True |
| 真实 | 0.1655 | 0.1684 | 1.000 | 0.764 | **False** |
| 阴天快乐 | 0.1470 | 0.1480 | 1.000 | 0.683 | True |

约束满足 0/5 → **2/5**，且所有歌保护点 pr=1.000 恢复。剩余 viol（全世界失眠/阴天快乐 sa≈0.55-0.68、我爱你中国极端 115 unsafe）为**真实数据约束**（保护与 sa 不可兼得），非 merge 破坏。

**结论（P0）**：`light_merge` island-fill 对称翻转 REJECT 岛违反保护优先契约，是冻结 pr 不达标的真实 bug。修复方向=只填 ACCEPT 岛。已归档 backlog，需在 detector 主线下修复并重验（修复会提高冻结可行性，但不解决我爱你中国式极端 val 的真实约束）。

产物：`/tmp/opencode/lightmerge_check.py`（raw vs merged 对照）、`/tmp/opencode/lightmerge_fix_sim.py`（修复模拟）。

## 10. Window 级质检门槛全量落地（2026-08-11，CPU）

**问题**：E1 只验证了阈值在部分窗上的捕获能力；需在全部 90 请求上扫描并给出推荐落地参数。

**实验**：fit B train → score A test（3955→4150 行），按 request 聚合。bad=hit100<0.7（15 个），good=75。T_ACCEPT=0.1655 沿用。

| 门槛 | AUROC | capture bad | FP ratio |
|---|---|---|---|
| mean_pb>0.20 | 0.9769 | 15/15 | 10/75 (13%) |
| mean_pb>0.30（E1 建议） | — | **12/15** | 漏 3 |
| p90_pb>0.25 | 0.9778 | 15/15 | 13/75 (17%) |
| **frac>T_accept>0.45** | **0.9831** | **15/15** | **9/75 (12%)** |

**关键**：E1 的「mean_pb>0.3 全捕获」在 90 请求上不成立（漏 3）；推荐改为 **frac>T_accept>0.45**（全捕获 + 最低误伤）。15 个被标记请求全部为绒花（w0/w1/w2 含 missing 变体）；FN=0。FP 9 个为月满西楼:w1（hit100 0.71-0.73，刚过线）+ 绒花:w0（0.75-0.87，detector 强预警但 hit100 达标）——保守侧，需人工豁免决策。

**落地**：`/tmp/opencode/window_gate.py`（--run-root/--out，输出 REAGG_GATE.json 形态）+ `/tmp/opencode/window_gate_report.json`（扫描全表）。

## 11. 语义窗口规则形式化 + 90 请求回测（2026-08-11，CPU）

**问题**：§7 证明窗口边界须落在语义边界，但人工切分不可扩展；需形式化规则并回测覆盖。

**规则 v2**（`/tmp/opencode/semantic_window_backtest.py`）：
- 重复元音 run 检测：元音连续 run len≥3（如 啊×8）或任意字符 len≥4，视为「重复段」；
- run 区间**相交判定**（非仅起点）——修正 v1 漏判跨窗 run 的 bug；
- 约束：每窗 ≤1 个 run；含 run 窗 ≤20s（RUN_WIN_CAP）；无 run 窗 ≤30s；run 段后 gap>0.5s 强制切（GAP_RUN_SPLIT）；GT 间隙≥2s 作切分候选；贪心切窗。

**绒花:w2 规则切分**（对比 §6 人工 4 子窗）：

| 规则 seg | canon | n | dur | 文本 |
|---|---|---|---|---|
| seg1 | [88,101] | 14 | 17.7s | 啊×7+一路芬芳满山崖 |
| seg2 | [102,113] | 12 | 16.9s | 啊×8+绒花绒花 |
| seg3 | [114,131] | 18 | 19.8s | 啊×8+一路芬芳满山崖一 |
| seg4 | [132,135] | 4 | 6.5s | 芳满山崖 |

（规则 v2 的 seg 边界与人工版存在差异：人工把「啊×8」run 后 gap 处拆出 2 段，规则用 GAP_RUN_SPLIT 在多处追加切分；需 GPU 实测两者优劣。）

**回测汇总**（90 请求）：bad(hit100<0.7) 23 个（含 missing 变体口径），其中含重复 run 的 bad 18 个（全部绒花 w1/w2 系列）规则均可拆分；不含 run 的 bad 5 个（月满西楼:w1 的 s2/s4 变体）——**月满西楼坏因与「啊」重复段无关，需单独归因**。规则 recommend_split 覆盖面过广（149/180 变体），正式 GPU 验证应只选 bad 请求的子集。

产物：`/tmp/opencode/semantic_window_rules.md`、`/tmp/opencode/semantic_window_proposal.jsonl`（request_id→窗口列表，供 GPU 复用）、`/tmp/opencode/semantic_window_backtest.py`。

## 12. 语义窗口规则 GPU 验证：规则切分复现人工切分（2026-08-11，RTX 3090）

**问题**：§11 规则 v2 只在 CPU 回测；需 GPU 实测确认规则切窗效果与人工切分相当（可自动落地）。

**实验**：用规则窗 manifest（`/tmp/opencode/rerun_rule_subwindow.jsonl`，绒花 w1/w2 各 4 窗）真实 forward（R2 checkpoint），与 §6/§6.5 人工切分同口径对比（均 raw rows、GT 逐字符）：

| 方案 | n | mean_mae | hit100 | max |
|---|---|---|---|---|
| 60s 整窗基线（w2:full） | 48 | 13.91 | 0.10 | 40.6 |
| 人工切分 w1+w2 | 93 | 1.08 | **0.57** | 4.43 |
| **规则切分 w1+w2** | 93 | **1.21** | **0.53** | **4.44** |

逐窗明细（规则）：w1:rule2（无 run 歌词段）hit100=0.88 最佳；w1:rule3/w2:rule2（含 run）0.33-0.42；w2:rule3（啊×8+歌词）0.50。**规则切分 hit100 0.53 与人工 0.57 基本持平、mean_mae 1.21 vs 1.08**，max 4.44s 一致性消除窗口起点塌陷（整窗基线 max=40.6s）。

**结论（窗口规划落地）**：语义窗口规则 v2 可自动执行且 GPU 实测复现人工效果，可作为 formal window-plan 的自动切窗策略。注意：
1. `audio_end_sec` 不能 round（181.34975 音频上限，round 到 181.35 越界报错）——§7 已记录；
2. 规则对「无 run 的歌词段」窗口也适用（w1:rule2 0.88）；
3. 月满西楼:w1 是**句首衬词错位**（非重复 run），规则不适用，需独立处理（§13 归因）。

产物：`/tmp/opencode/rerun_rule_subwindow.jsonl`（8 窗 manifest）、`/tmp/opencode/rule_subwindow_run2/`（evidence）、`/tmp/opencode/eval_rule_subwindow.py`。

## 13. 月满西楼:w1 坏因归因：句首衬词错位（2026-08-11，CPU 分析）

**问题**：§11 回测发现月满西楼:w1 的 bad 变体不含重复 run（规则无法拆分），需单独归因。

**分析**：月满西楼:w1（canon 62-117, 56 字）逐字符 raw vs GT：14/56 字 |err|>1s，但**无「啊」重复段**。错误集中在两处：
1. **句首衬词序列 `头哦无哦偶却上心头红藕`**（canon 62-72）：`偶` pred=76.0s vs GT=68.72s（**+7.29s**），后续 `却上心头` 整体负偏 -1.5~-2.6s——衬词组被压缩/锚定错位，与绒花「啊」簇同源（无语义音节时间戳扎堆），但**是句首短衬词串而非长 run**，且偏移幅度小（+2~-2.6s 为主，偶单点 +7.3s）。
2. **段尾小偏移**：canon 99-102（`西楼花自`）|err| 1.0-2.1s。

**结论**：月满西楼:w1 坏因与绒花同根（Qwen FA 对无语义音节的时间戳错位），但触发形态不同——句首衬词序列 vs 长重复 run。窗口规则（run≥3）不覆盖此类；其 hit100≈0.70（刚过线）属轻中度，且窗口拆分未必有效（衬词串嵌在句内、无语义边界可切）。建议：此类句首衬词错位留给 repair/后处理，或在 detector 特征中识别句首衬词模式。

产物：逐字符对照表（见本段上方数字）。

## 14. 语义窗口规则 v2 接入 window-plan 管线 + review 收尾（2026-08-11）

**接线**（commit 6d6b0db）：`build_requests()` 加 `use_semantic_windows=False` 开关（默认保持 fixed-60s 冻结口径），`--window-mode fixed|semantic` CLI，FREEZE.json 记 window_mode；语义模式把每个 fixed 候选窗用 `plan_request_windows` 切成子窗（子窗音频区间=子窗首末 unit 时间，canonical 连续不相交），请求带 `:s{sub_idx}` 后缀区分。新增 `plan_request_windows` 纯函数（semantic_window_planning.py 末尾）+ 接线契约测试（test_semantic_window_planning_wiring.py，22 passed）。

**review 发现并修复 P1**（commit 7e39d5e）：`slot_plan_id`/`comparison_group_id` 由 `plan_group` 派生，semantic 模式初始不带子窗后缀 → 同一 fixed 窗切出的子窗共享同一 group（identity 绑定到内容不同的请求）。修复：`plan_group` 并入 `sw_sfx`，pair_id==comparison_group_id 恢复。补断言测试（baseline slot_plan_id 跨子窗唯一、comparison_group_id 按子窗一个、pair_id==comparison_group_id）。复查确认 fixed 口径逐字节不变、missing 继承 base slot_plan_id 属既有冻结口径、density phase 名唯一。

**验证**：全模块 tests/research_v7 511 passed。

## 下一步（backlog，不阻塞）

- **【DONE】语义窗口规则 v2 模块化 + 接线**（§12/§14）：模块化 commit ee72ba1、契约对齐 33f4e22、接线 6d6b0db、P1 修复 7e39d5e。**待办：semantic 模式跑一次真实 GPU 对比（vs fixed 基线），确认子窗请求的 real 执行与评价链路无缺口。**

- **【DONE】修复 `light_merge` island-fill 对称翻转 REJECT 岛**（§9）：island-fill 只填 ACCEPT 岛（commit cf20bb6）；修复后 LOO 约束满足 0/5→2/5、pr 恢复 1.000。契约测试已加（单点/级联 REJECT 岛不翻转），全模块 506 passed。**待办：用真实 formal 重验冻结行为（pr/sa 非退化）。**
- **【P1】window 级质检门槛接入 formal**（§10）：采用 `frac>T_accept>0.45`（AUROC 0.983，15/15 bad 全捕获，FP 12%）替代 E1 的 mean_pb>0.3（90 请求下漏 3）；脚本已可复用（REAGG_GATE.json 形态）。
- **【DONE】语义窗口规则 v2 模块化**（§12）：`src/lyricalign/research_v7/semantic_window_planning.py` + 契约测试（commit ee72ba1）；GPU 验证 hit100=0.53 ≈ 人工 0.57。review 已对齐 requests.py 契约（canonical_text_start/end 不含端点，commit 33f4e22）。接线见 §14。
- **【P2】月满西楼:w1 句首衬词错位**（§13）：非重复 run、规则不可拆；句首衬词序列 `头哦无哦偶` 时间戳错位（偶 +7.3s）。可留给 repair 或在 detector 识别句首衬词模式。
- 对「啊」重复段探索 window-plan 层去重/分片策略；绒花 w2 段需窗口边界调整或分句。
- 复训 detector 时 val 纳入难歌但控制 unsafe 量（避免 reject-all 坍缩），冻结前确认 unsafe ≥100 且 pr/sa 非退化。
- 将行级 p_bad 聚合为 window 级 reagg 质量分（推荐 frac>T_accept / p90），用作 formal 前质检门槛（E1 已验证 AUROC≈0.98）。
- ~~增强特征（G1 hidden H / 全信号组合）以缓解 E2 的 val 敏感性坍缩~~（**证伪**：§8 五种特征集 LOO 均 0/5 满足；应转向冻结机制本身——按歌分层冻结 / 放宽 sa / ROC 平衡点替代硬约束）。
