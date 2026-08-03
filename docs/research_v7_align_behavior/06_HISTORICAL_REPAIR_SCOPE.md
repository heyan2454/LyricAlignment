# 历史结果修复边界

## 必修

### E1 event

旧 formal event-level 因跨 item 索引碰撞无效。修复后报告 micro、macro、cluster bootstrap 和 event count。

### E5/E6

在完全相同 applicable subset 上 paired 重算。旧主表保留但标注不可直接横比。

### 条件分母

补 total/applicable/attempted/completed/non-null/success/failure/numerator/denominator。

## 不修成“正结果”

- E3：停止；
- E2：不再用旧 detector 评价；
- E5/E6：不继续调参数；
- E7：不沿用不完整 full reset；
- E9：不在旧 score 上扩 beam。

## 原始数据原则

优先重算，不重推理。若逐 item rows 缺失，应明确记录缺失及不得恢复的指标；不能从轻量摘要反推不存在的数据。

## 输出

- fixed JSON/CSV；
- old-vs-new comparison；
- provenance；
- test logs；
- status table；
- verify script。
