# 执行合同与挂机自由探索协议

## 1. 总体执行方式

本 session 先交 Codex 做实现方案/代码现状核实，再交 OpenCode/agent 实现和运行。实现 agent 不得因为某个方向 negative result 或 sample 不足就提前收尾。

---

## 2. 环境与路径

- repo：`/home/hyan/LyricAlignment`；
- conda：`lyricalign-qwen`；
- `PYTHONPATH=src`；
- 大型 run：`/home/hyan/Data/lyricalign/runs/`；
- 不把大型 cache/audio/video/evidence pack 放 git；
- session 文档、轻量 metrics/comparisons、配置可进 git。

正式运行前记录：

- resolved config；
- git commit/diff；
- model/revision/checkpoint；
- CUDA/torch/transformers；
- RNG seed（如涉及随机采样/bootstrap）；
- source manifests + hashes；
- output overwrite/resume policy。

---

## 3. GPU 预算

- target GPU：<=10h；
- hard cap：<=12h；
- 预算优先级：机制 screening > 对有效机制扩量 > 重复无效 family；
- 到 hard cap 后停止新增 GPU formal forward；
- 继续 CPU evaluator、统计、报告、hard-case mining、已有 cache 的 candidate selector、可视化 rerender 与自由探索计划生成。

若用户挂机且没有主动打断，agent 不能因为达到 GPU cap 就结束整个 session。

---

## 4. 不做笛卡尔积

禁止：

```text
iteration × split size × audio margin × context k × family × language × threshold
```

的全排列。

执行策略：

1. 40–60 独立 hard regions 做机制 screening；
2. 每个问题只比较 3–5 个差异明显的 branch；
3. 根据预注册主指标淘汰 no-op/high-harm route；
4. 只把 1–2 个有效方向扩到 >=200 regions；
5. heldout/test 不用于反向调参。

---

## 5. GT Firewall

no-GT controller/ranker/stop rule：

- 不接受 GT path；
- 不读取 evaluator artifact；
- 不使用 `delta_error_ms`/GT label；
- 不能用 GT 选择 best iteration / best view。

GT evaluator 在所有 candidate frozen 后 join：

- 100/200/500/1000ms；
- unit/region；
- all-hit / >=75%-hit；
- context harm；
- song-cluster bootstrap。

Oracle 实验放在独立 evaluator-only namespace，不能污染 production candidate selector。

---

## 6. Cache / Resume / Failure Recovery

- 完整 request identity 包含 iteration、parent candidate、audio crop、split、family、model/checkpoint、audio hash、code/schema；
- 相同 identity 必须复用 forward；
- 任何 identity field 变化禁止错误复用；
- per-request 结果原子写入；
- failed request 保留错误日志并可 resume；
- formal summary 不因少数 failed case 丢弃全部已完成结果；
- sample 不足先扩大 pool/放宽每歌 cap/从更多 M4 songs 寻找；仍不足才报告真实 denominator，不能用重复同一 region 伪造样本量。

---

## 7. 指标口径

必须分开：

### Target correctness

- boundary max error；
- 100/200/500/1000ms；
- improvement/regression；
- coarse vs strict recovery。

### Context safety

- fixed context displacement；
- safe preservation；
- collateral/catastrophic harm。

### Region/event

- all-target recovered；
- >=75% recovered；
- serial downstream recovery。

### No-GT

- detector/raw/official/hidden/posterior；
- stability/consensus；
- structural sanity。

不同 schema 不混成一个“accuracy”。

---

## 8. 可视化与 scientific pipeline 分离

- collection 在 visualization 前；
- presentation 依赖 scientific artifacts，scientific collection 不依赖图片；
- rerender 不能重复 model forward；
- renderer 修改后检查 scientific hash；
- Side by Side smoke 未通过前不得批量生成大量 MP4。

---

## 9. 阶段完成后自动自由探索

主计划完成或 GPU cap 到达后，若用户未主动打断，进入 free exploration。

### 第一轮自由探索 todo 建议

1. 汇总 recovery-basin atlas，寻找“只差一种机制未测”的 hard cases；
2. 自动 mine 新 catastrophic / multi-view disagreement / serial drift / repeated-lyrics cases；
3. 用已缓存 candidate 研究真实 no-GT selector/safety feature；
4. 检查是否存在 coarse localization/retrieval 的低成本替代实现；
5. 检查 current baseline vs B4 的客观回归，找到最值得看的 Demo；
6. 扩 detector hard-negative/realign-failure 数据；
7. 汇总 negative results 与替代解释；
8. **重新审阅当前所有结果、失败样本和未验证假设，生成下一轮自由探索 todo，并把“再次生成后续 todo”作为新 todo 的最后一项。**

最后一项必须保留，以便挂机时持续推进，而不是一次 todo 跑完后空闲。

---

## 10. 收尾要求

最终报告至少包含：

- 实际执行阶段与未执行项；
- GPU/CPU wall time、forward count、cache hit；
- 每个实验的 hypothesis / setup / observation / alternative explanation / conclusion strength；
- negative results；
- sample accounting；
- failed/not_constructible 原因；
- B4 vs Current 与四路可视化路径；
- 下一轮自由探索 todo 状态。
