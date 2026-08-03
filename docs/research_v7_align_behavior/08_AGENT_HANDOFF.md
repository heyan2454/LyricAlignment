# Agent 执行交接

## 执行顺序

1. 读取本目录 README、00、01、05、06；
2. 审计原 formal 输出和逐 item 数据；
3. 只实现历史修复并验证；
4. 建立最小 Request/Attempt/Evidence；
5. 实现百分比 mutation 和 frozen donor manifest；
6. 单 case smoke；
7. controlled pilot；
8. 冻结 `pilot_freeze.json`；
9. formal GT behaviour；
10. demo_dev review bundle；
11. validation/heldout；
12. 综合归档。

## 必须优先完成

- E1 event 修复；
- E5/E6 paired；
- 条件分母；
- strict serial P1；
- sparse-slot S 可行性；
- extra/missing/replacement 百分比；
- cross-song strict no-match；
- posterior top-K 和 official repair trace。

## 不能擅自决定

- 不能继续调 E5/E6；
- 不能复活 E3；
- 不能把 detector 直接接入 writeback；
- 不能根据 formal test 结果改 mutation；
- 不能把无 GT 指标称为准确率；
- 不能将多解副歌算作 strict no-match；
- 不能因为计算量大就静默缩减比例或样本；
- 若需减量，应保留主曲线并在报告中明确 sampling。

## 进度记录

`08_AGENT_EXECUTION_LOG.md` 应逐项记录：

- 做了什么；
- 输入/输出路径；
- 命令和环境；
- 是否使用缓存；
- 失败和恢复；
- 与计划偏差；
- 未知或缺失数据；
- 当前结论强度。

## 最终验收

代码、测试、manifests、pilot freeze、raw attempts、compact evidence、报告、negative results、review bundle、checksums 和运行说明齐全。
