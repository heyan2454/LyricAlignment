# Detector V2 设计与硬验收补丁

本补丁面向下一阶段 detector 研究，不包含已训练模型或正式实验结果。

## 新增内容

- `docs/research_v7_align_behavior/18_DETECTOR_V2_EXPERIMENT_PLAN.md`
- `docs/research_v7_align_behavior/19_DETECTOR_V2_AGENT_CONTRACT.md`
- `docs/research_v7_align_behavior/20_DETECTOR_V2_IMPLEMENTATION_BLUEPRINT.md`
- `docs/research_v7_align_behavior/21_PREVIOUS_DETECTOR_RESULT_CORRECTIONS.md`
- `docs/sessions/20260805_detector_v2_experiment_design.md`
- `src/lyricalign/research_v7/detector_v2_contract.py`
- `src/lyricalign/research_v7/detector_v2_metrics.py`
- `src/lyricalign/research_v7/detector_v2_coverage.py`
- `scripts/research_v7/build_detector_v2_coverage_matrix.py`
- `configs/research_v7/detector_v2_required_coverage.json`
- 三个测试文件，共 10 个新增单测。

## 作用

1. 将产品主任务冻结为正确歌词下的实际错位检测；
2. 将 detector 输出冻结为 accept/reject/uncertain 的完整子区间 partition；
3. 提供 false-accept、reject/protected recall、interval@75/@100 等产品指标；
4. 禁止旧 `wrong_output_recall`、tail gap 等非 detector 指标进入新验收；
5. 使用 coverage matrix 强制检查 H/R/O/V、raw/official、跨 family、M4→MIR、1/2/4/8 stress 和 serial closed-loop。

## 应用后检查

```bash
PYTHONPATH=src pytest -q \
  tests/research_v7/test_detector_v2_contract.py \
  tests/research_v7/test_detector_v2_metrics.py \
  tests/research_v7/test_detector_v2_coverage.py

PYTHONPATH=src python scripts/research_v7/build_detector_v2_coverage_matrix.py \
  --init configs/research_v7/detector_v2_required_coverage.json \
  --out /tmp/DETECTOR_V2_COVERAGE_MATRIX.json
```

初始化模板的 `--validate` 应失败，因为所有正式实验格仍为 pending；只有 agent 真实生成有非零分母的 artifact 后才能通过。
