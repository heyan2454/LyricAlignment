# 数据、指标、公平性、缓存与预算

## 1. 数据角色

### M4

主 GT formal。要求 source-song split 严格分离：

- development/train；
- threshold/calibration validation；
- test。

不得在 test 结果出来后回调 threshold。

### MIR-1K

固定 M4 detector/scaler/threshold 后迁移。若标签 schema 与 M4 不同，必须分别报告，不得把数值直接拼总表。

### Synthetic / constructed

仅用于机制：

- repeated occurrence；
- canonical state corruption；
- model-native forced commit；
- seam control。

构造来源必须继承 source split，避免同歌不同构造跨 train/test。

### Test demo

无 GT；自动扫描现有与新增 demo，不固定数量。用于：

- trajectory；
- cross-window consistency；
- repeated occurrence mining；
- detector/recovery intervention statistics；
- runtime；
- suspicious-case ranking。

不得声称 GT MAE/accuracy。

---

## 2. 自动利用 Test demo

每首自动输出：

- language / duration / silence structure；
- number of windows；
- skipped silent windows；
- raw/official disagreement；
- cross-window timestamp jump；
- posterior multimodality；
- occurrence ambiguity candidates；
- abnormal compression / zero-duration run；
- Transition route disagreement；
- detector intervention；
- L/W retry cost；
- top suspicious episodes。

人工只检查：

- top-ranked 异常；
- route 显著改善/恶化；
- 少量随机 controls。

---

## 3. 指标层级不得混淆

### Frame/timestamp-level

如 MAE/onset/offset/timestamp deviation，仅在 GT 可用时。

### Unit-level

每 canonical unit correctness、accept/reject、cursor/occurrence identity。

### Interval/event-level

错误区间是否完整/≥75% 命中，必须明确容忍度和 interval merge 规则。

### Serial/episode-level

- propagation probability；
- propagation depth；
- cursor/time amplification；
- corrupted committed units；
- recovery latency；
- occurrence jump；
- final trajectory success。

### Demo listening/visual

仅辅助 qualitative，不可替代主指标。

---

## 4. 公平性要求

比较两方案时至少核对：

- source split；
- audio identity / preprocessing；
- actual window plan；
- left/core/right context；
- text/query span；
- slot mapping；
- decoder；
- postprocessing；
- threshold；
- GT tolerance；
- duration crop；
- model forward count；
- wall time。

如果多个变量同时变化，结论必须降级为“system-level comparison”，不能声称单因素因果。

---

## 5. 缓存

优先共享：

- 同一 audio/request 的 encoder/model forward；
- raw/official 从同一 forward 派生；
- 相同 query/slot/window 的 evidence；
- detector feature conversion。

Cache key 至少包含：

- audio content identity + preprocessing version；
- exact actual window boundaries；
- query text/span；
- slot topology/full-slot identity；
- model/checkpoint；
- generation config；
- hidden hook config（若启用）。

不得仅按文件名或 OUT_ROOT 复用。

Mutation 改变 query/state 并需要真实重新 forward 时，不能错误复用 baseline evidence。

---

## 6. 12h 预算建议

GPU 预算目标约 10h，硬上限 12h。建议：

| 阶段 | 目标预算 |
|---|---:|
| baseline/cache + transition formal | 3.0 h |
| propagation harvesting + controlled episodes | 2.5 h |
| oracle recovery + transition stability | 1.0 h |
| legacy gap targeted re-forward | 1.0 h |
| detector SA60/SA80/R95 + main signals | 2.0 h |
| selected closed-loop + MIR/demo | 2.0 h |
| 合计目标 | 11.5 h |

CPU 审计、报告和从已有 evidence 重算不计 GPU 预算，但 Agent 仍应优化 wall time。

### 超预算处理

接近预算时按优先级砍：

1. 更多 hidden layers；
2. 更多 context/strict-silence 变体；
3. 更多 non-slot 组合；
4. 更多 classifier；
5. 更多 decoder。

不得砍：

- T0–T3 主 comparison；
- propagation corpus；
- SA60/SA80/R95；
- oracle recovery；
- selected L/W closed-loop；
- authoritative final report。

---

## 7. 失败恢复与写盘

所有阶段：

- append-only event log；
- per-item atomic write；
- manifest/state 定期 flush；
- resume 跳过已完成且 cache identity 一致的 item；
- failed item 单独记录，不删除已有结果；
- summary 从 authoritative JSON/JSONL 生成，不手工抄关键数字。
