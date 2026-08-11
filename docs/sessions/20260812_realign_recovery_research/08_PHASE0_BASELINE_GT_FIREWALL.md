# WP-A：Phase 0 Baseline Mapping 与 GT Firewall

**前置：** 阅读 00--07。**性质：** CPU-only；未完成不得启动 E1 或任何 GPU batch。

## A1. 生成不可变的 session 元数据

在新 `SESSION_ROOT/00_meta/` 生成下列文件。每个文件必须含 UTC、repo HEAD、完整 dirty status、命令和所有输入 SHA-256。

```text
BASELINE_IMPLEMENTATION_MAP.md + .json
RESOLVED_SESSION_CONFIG.yaml + .json
GT_ACCESS_CONTRACT.md + .json
CACHE_IDENTITY_SPEC.md
SPLIT_AND_GT_PROVENANCE.json
```

mapping 至少锁定：模型/checkpoint/processor；full-slot request path；实际 60/10/10 silence-aware serial 配置；Raw output/decoder；修复后的 `light_merge` detector artifact/threshold；accepted real-GT loader；source-song roles；audio preprocessing clock。

若 02 的预期名称与实现不一致，只记录真实映射与最小 adapter，不重新运行选择实验。若 frozen detector 没有可验证 artifact identity，标为 `blocked_missing_detector_identity`，不得把模糊的当前工作树当冻结 detector。

## A2. GT firewall 的代码规则

新增 no-GT control API 必须不接受 `gt`, `gt_path`, `timeline_gt` 或等价参数。执行记录只含 request、Raw 输出、detector/proposal/judge/writeback state 和可复现 identity。另建 evaluator CLI，以 `(control_artifact, real_gt_binding)` 做只读 join。

Oracle API 可接受一个 **oracle request specification**，但传给 aligner 的只能是音频范围、文本 unit/text 与非 GT 的配置；不得传字符时间戳、GT decoder correction 或根据即时 GT 的隐藏 retry。

禁止以 import 黑名单替代实际测试：测试 fake backend 必须证明 no-GT run 中未看到 GT 对象/路径；同时验证 evaluator 可以在运行后独立产生指标。

## A3. real-GT 与 split 核验

复用现有 `gt_provenance`、real-GT projection/audit 和 cohort evidence，重新核对本 session 实际 song list：accepted statuses、双边界、global unit identity、unlabeled 分母、source-song role、R2 training overlap。结果中不得把 historical cached aggregate 当 heldout formal。

任何自然轨迹或受控 episode 入库前都写 `song_id`、source role、language、failure family、GT binding hash；不满足 accepted real-GT correctness 的 unit 可保留 no-GT mechanism evidence，但必须在正式 correctness 指标外。

## A4. Phase-0 验收

```bash
PYTHONPATH=src python -m pytest -q \
  tests/research_transition_recovery_detector/test_gt_provenance.py \
  tests/research_transition_recovery_detector/test_closed_loop.py \
  tests/research_transition_recovery_detector/test_closed_loop_v3.py
python -m compileall -q src scripts
git diff --check
```

再新增 `tests/realign_recovery/test_gt_firewall.py` 与 `test_baseline_identity.py`：分别覆盖 control 无 GT、oracle 无 timestamp、identity 漏字段拒绝、split/accepted-status 审计。所有通过后在 `PHASE_A.md` 标记 `ready_for_core_implementation=true`。
