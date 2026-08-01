# Alignment Research v6 formal decoder route completion

## 背景

实现级 review 确认：上一版虽然冻结并报告 `selected_decoder`，但 formal 没有加载它，串行提交仍固定使用 official；pilot 还会纳入 M4Singer test；E8 continuation 失败后的 static splice 零变化会进入 downstream effect mean。

## 最终修复

1. formal 加载、校验 `selected_decoder`；
2. raw/official/joint/top-K/isotonic 均可作为实际窗口 decoder；
3. research decoder 在 core ownership、commit 和 cursor 更新前投影到 `fixed_*`；
4. 非 official formal 按冻结 B4 window plan 进行 model-backed baseline rerun，其 rows/trace 作为 E1、E5–E9 operational baseline；
5. local request、E7、E8 continuation、E9 beam branch 使用同一冻结 decoder；
6. pilot 排除 test/heldout 和 test-derived synthetic-long，显式 test item 也不能绕过；
7. 修复 pilot 可用样本少于 cap 时的重复位置抽样；
8. E8 项目级 downstream effect 仅统计 continuation complete 候选，失败保留为 negative result 和 static diagnostic。

## 保留决定

- decoder 选择仍采用当前 pilot `all.macro` 口径，训练样本组成影响暂不调整；
- resume/cache 的跨版本强身份验证仍不新增，算法变更后依赖全新 `OUT_ROOT`；
- 未声称完成真实 GPU 集成验证。

## 验证

- 相关回归 39 项通过；
- 排除缺失 `pypinyin` 的 3 个既有测试模块后，其余 266 项通过；
- Python 编译与 shell 语法检查通过。
