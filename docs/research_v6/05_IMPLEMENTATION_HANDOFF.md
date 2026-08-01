# 实现交接、过程与限制

## 当前实现

1. 保留 B4 串行链作为统一 baseline，不在 Detector 未验证前改写 production commit。
2. Baseline 保存 raw/official/local/global/top-K evidence；top-K class 的全局时间只由已有 local/global 字段恢复，不新增偏移字段。
3. `src/lyricalign/research_v6` 实现 request/corruption、decoder、Detector、window/silence/state injection、audio support、统一 metrics 和专项分析。
4. E0–E9 共用执行器；冻结 Detector 真正生成 formal risk spans/safe boundaries，并进入 E5/E8；E5 使用风险门控后的边界分数。
5. Pilot 按 source song 分 train/calibration；held-out 只在冻结后进入 formal。pilot 不完整时按 best-effort/default 继续冻结并显式降低效力，不硬阻断 formal。
6. E2–E9 phase 级 resume、local inference cache、失败落盘、项目级汇总、正式 Markdown 报告、可视化与 full/light3m 收集均已接入。

## 重要口径

- Formal 消费 manifest 的每个 item；重复 local/chunk/realign case 有独立可配置上限，不等同于数据集 item cap。
- M4Singer 保留 train/validation/test 与 training exposure；synthetic-long 不跨 split 拼接。
- MIR-1K development/extra/spare/heldout 独立汇报。
- 局部实验报告 local GT 与 spliced-full 两套指标，不把局部输出直接与整首 GT 比较。
- Frame/unit、event、歌曲 macro、reference-weighted micro、source-song cluster 和 seam-near/far 不混用。
- 无 GT demo 不声称 accuracy 改善。

## 已知限制

- 本归档环境没有真实模型权重和完整数据，因此没有伪造 GPU 或 formal 数值；必须先运行单 Demo smoke。
- 当前 local inference cache 是逐 request 前向复用，并未声称已验证模型级 batch inference；真实 wall time以 pilot 日志为准。
- E9 的 cursor/window/text-budget 路线已是真实跨窗 beam；其中行级粗定位仍是独立于字符 alignment 的能量跨度/歌词长度 baseline，不等同于最终 ASR/embedding 粗定位器。
- 即时 precommit realign 尚未写回 production commit；E8 是研究路径中的真实串行 continuation：局部候选成为 immutable prefix，再重跑同窗尾部及后续窗口。
- Resume/cache 身份语义本轮按用户决定不继续加固；修改算法、歌词、checkpoint 或实现后仍必须换新 `OUT_ROOT`。
- 完整 pytest 在本打包解释器中因缺少 `pypinyin` 无法收集 3 个数据模块；其余 261 个测试通过。

## 下一执行顺序

```bash
# 1. 安装依赖并验证 snapshot
$PYTHON_BIN -m pip install -e ".[test,qwen-smoke,demo-multilingual]"

# 2. 单 Demo smoke
scripts/research/run_research_v6_smoke.sh --item-id <demo_item_id>

# 3. 检查 smoke 的 E0-E9、failure、formal_report 与视频/图

# 4. 新 OUT_ROOT 启动 formal
scripts/research/start_research_v6_detached.sh formal --resume
```
