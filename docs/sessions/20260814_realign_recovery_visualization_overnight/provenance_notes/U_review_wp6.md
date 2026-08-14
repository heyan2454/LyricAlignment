# U_review — WP6（commit b89654b，E4 R-U coarse->fine）代码正确性/契约 + 数据一致性/跨模块接线 review

审查人/时：WP6 独立 review 子任务。范围：`src/lyricalign/unit_realign/coarse_fine.py`、`scripts/unit_realign/run_coarse_fine.py`、`src/lyricalign/unit_realign/request_families.py`（+R-CF）、`scripts/realign_recovery/visualization/` 的 `evidence_payloads_for_family`/`load_evidence_index`（第四路接入）。
启动条件：只读代码 + 最小 CPU（--smoke + 合成 region），不跑 GPU/渲染。

实测环境：`conda ignite lyricalign-qwen`，`PYTHONPATH=src:.`。跑了：
- `run_coarse_fine.py --regions <合成REGION_POOL> --smoke`（10 units、0.5s 间隔；连续 target [3,4] + 非连续 target [2,5]），并在 `/tmp/cf_review/run_smoke/` 落盘验证 output + resume。
- 直接单测 `constructible()`（overlap / negative-duration / noncont / empty 冲突）。
- 直接单测 `evaluate_coarse_fine()` 构造 steps（A ok + B not_constructible）
- 用 `visualization_controller.load_evidence_index/evidence_payloads_for_family` 校验 family 隔离。
- `-p no:capture` 下 `pytest -q tests/unit_realign` → **91 passed**（默认 pytest 命令因坏 readline 崩溃，见 §6）。

结论：**存在 3 个 P1（1 个指标口径、1 个四路接线脆弱、1 个测试运行环境）；无 P0。**

---

## [P1] 指标口径 1 — `_final_rows` 在 Stage B not_constructible 时把 Stage A 有效 coarse 结果整段丢弃

- **现象/证据**：`evaluate_coarse_fine` → `_final_rows(steps)`（coarse_fine.py §518-526）。当 `A ok` 且 `B 存在但因 fail-closed 为 not_constructible` 时，循环既不返回 B（B 非 ok），也不返回 A（`not any(B in steps)` 为假），最终 `return None, None`。实测：构造 A 成功（target3→1.52/ref1.5≈+20ms、target4→2.03/ref2.0≈+30ms，均 <100ms）,B `proposal_invalidates_fixed_context:non_monotonic_candidate_timeline` → aggregate `coverage:0.0`、`target_recovered_100/500/1000:0.0`、per-unit `error_ms:None`。**Stage A 的 coarse 已达标恢复被整段清零**。
- **影响**：fail-closed 本意为"坏 proposal 不喂精修、停链"（安全机制），不应等于"该 region 无任何恢复"。凡 A 成功但 B 因几何冲突 not_constructible 的 region，会被系统性低估为 0% 恢复，污染 `coverage`/`target_recovered_*`/`forward_cost`(仍=1) 口径，可能改变 WP6 结论。
- **建议**：
  1）`_final_rows` 在 B not_constructible / B 未跑但 A ok 时回退用 A 的 `candidate_rows` 作为 final（把 `not any(B)` 分支改成 `not (b_step and b_step.status=="ok")` 语义，即"B 无有效精修时回退 A"）；
  2）或至少在 aggregate 中单独记录 `final_stage:"A"|"B"`，并只对"B 真正产出"的 region 用 refine 口径，A-fallback region 明确标注 `stage_b_not_constructible` 后仍计入 coarse 恢复；
  3）无论采用哪种，T_wp6 §2.5 的口径说明需冻结补充这一回退语义。

## [P1] 数据/接线 2 — 第四路可视化 `request_id` 与 plan 的 `request_id` 无自动对齐，R-CF 证据可能静默永不入图

- **现象/证据**：`run_coarse_fine.py` 把 R-CF evidence 写到 `{request_id}.json`，`request_id = f"{song}:{region}:R-CF"`（coarse_fine.py §102/§237；run_coarse_fine.py `_write_evidence`）。`evidence_payloads_for_family(idx, request_ids, family=...)`（visualization_controller.py §190-208）仅在 `request_ids`（来自外部 `--plan REALIGN_REQUEST_PLAN` 的 `item` 过滤）命中 `load_evidence_index` key（= `attempt.request.request_id`）后才按 `proposal_method` 过滤。**plan 的 request_id 与 R-CF 的 `song:region:R-CF` id 能否命中完全取决于上游计划文件是否含该 id**——plan 由 R-U/R-S realign 流水线生成，**没有任何机制保证包含 R-CF id**。若不含，`evidence_index.get(rid)` 全 None → `f4=[]` → renderer 走 `[warn] ... keeping 3 tracks`（render_current_4way.py §109-110），第四路**静默消失**（仅一行 warn）。
- **实测确认隔离正确**（非冒名）：`load_evidence_index` 后 `evidence_payloads_for_family(idx,["s1:r_conc:R-CF"],family="R-CF")`→1（proposal_method="R-CF"），`family="R-U"/"R-A"/"R-B"` 对同 id → **0**。因此逻辑本身 filter 是对的，问题在**上游 request_id 对接**这一脆弱环节，无断言/缺 track 的硬失败。
- **建议**：
  1）给第四路接入提供一个显式 producer：正式流程应把 `run_coarse_fine.py` 的 `01_requests/REQUESTS.jsonl`（含 R-CF id）与可视化 plan 对齐（可加 `render_current_4way.py --fourth-id source=...` 或要求 plan 必须来自 REQUESTS.jsonl 的 region 对应行）；
  2）第四路 `f4` 为 0 时，若 `args.fourth_family` 已显式传入且该 item 本应有 R-CF evidence（按 forward-root 下存在 `*:R-CF` evidence），应提升为 warning+nonzero exit 或强制报错，而非静默降级 3 track，避免"看似已接入实则没画出"。
  3）T_wp6 §4 接受标准里的"把含其 request_id 的 plan 传入"是人工约定，应固化为脚本级检查。

## [P1] 环境/可复现 3 — 文档化测试命令 `python -m pytest -q tests/unit_realign` 在本 conda env 直接段错误（坏 readline C 扩展），`.readline_stub` 未生效

- **现象/证据**：faulthandler 显示 crash 在 `_pytest/capture.py:95 _readline_workaround` 内 `import readline` → `create_module`（加载编译版 readline C 扩展）时段错误。无论 `PYTHONPATH=src` 还是 `src:.`，`pytest --version` / `--collect-only` / 跑任一模块全部 `Segmentation fault (rc139)`。`.readline_stub/readline.py` 提供纯 Python readline，但 pytest 在 `_readline_workaround` 里加载的是**标准库编译扩展**（stub 未真正抢先命中），故 stub 无效。
- **影响**：AGENTS 规定的 L1/L2 验收命令无法直接运行，会让 reviewers/CI 误判为"测试全崩"。
- **建议（非 WP6 代码问题，属环境修复）**：
  1）短期：文档化 pytest 需 `-p no:capture`（即 `python -m pytest -p no:capture -q tests/unit_realign`，实测 **91 passed**），或设 `PYTEST_ADDOPTS`；
  2）治本：修 conda env 的 libreadline（重装 readline / 换非 libedit 后端），或让 `_readline_workaround` 不触发（e.g. 在 sitecustomize/入口里预 `sys.modules['readline']=stub`，而非只靠 PYTHONPATH 同名模块）。
  3）`.readline_stub` 目前实际无效，README 需更新或移除。

---

## 通过项（重点核查点复述）

- **[P1候选① identity/chain_context] 通过**：smoke 出 A=`sha256:5e548e…`、B=`sha256:3947bc…`（互异）；B 的 `parent_request_identity`=A identity、`iteration=1`、`recrop_view_id="recenter_proposal"`、`split_slot_id="R-CF"`，chain_context 含完整 8 frozen + 4 family key（B 顶层也 merge）。`build_request_identity` 按 chain_context 全量 digest，chained 四 key 缺失才 fail-closed。`_rekey_request`（coarse_fine.py §93-110）保留 R-U 几何构造后改 `family/requested_family="R-CF"` 与 `request_id` 并重算 identity；因 digest 含 `family:"R-CF"`（≠ 真实 R-U 的 `R-U`）且 chain_context 含 split="R-CF"，**与真实 R-U 请求 digest 不可能错乱**。identity 稳定性 OK。
- **[P1候选② stageB sparse/fixed] 通过**：smoke 验证 recrop 窗口 `[2,3,4,5]`（target [3,4]+每侧 2 邻居），`active_slot_indices=[1,2]`=target 局部 idx、`fixed_slot_rows`=[ci d 2,5]、`slot_constraint_schema="realign_sparse_fixed_v1"`；fixed 行放 baseline 全局位置（几何正确），active target 精修；fixed 非单调有守护。re-crop 后 fixed context 几何保持正确。
- **[P1候选③ constructible] 通过**：`constructible(proposal, region)` 用 `validate_rows`（负时间/负时长/start 单调）拦;实测定 overlap-fixed→`non_monotonic_candidate_timeline`、negative-dur→`negative_duration`、empty→`empty_coarse_proposal`；proposal 与 fixed 冲突时 `run_coarse_fine` 标 B not_constructible 并停链，不静默喂坏 proposal。见 MINOR-4。
- **[P1候选⑤ 四路不冒名] 通过**：`load_evidence_index` 按 `attempt.request.request_id` 建 key；R-CF evidence `proposal_method="R-CF"`；R-CF/ R-U/ R-A/ R-B 对同 id 计数=1/0/0/0，无冒名（上游 request_id 对接问题见 P1-2）。
- **[P1候选⑥ GT firewall] 通过**：`coarse_fine.py` 无 GT/oracle/`baseline_gt` 读取，recovery 参考全为 frozen shadow baseline；`actual_writeback:0`（§688），`writeback_unit_ids=targets` 仅元数据。

## MINOR（进 backlog，不阻塞）

1. **`test_coarse_fine.py` 缺失**：07 plan（§…205-206）与 T_wp6 §1 均列了该测试，但 `tests/unit_realign/` 下无此文件 → R-CF 的 fail-closed/identity 互异/coarse_fine_v1 schema 缺回归测试。建议补：构造 A 冲突 / B 冲突 / smoke full-run 三用例。
2. **`constructible` 把纯 overlap 标为 `non_monotonic`**：`validate_rows` 无专门 overlap 检查，overlap 被归入 start 非单调（语义label 不精确）。fail-closed 正确，仅 reason 文案可再细分 `overlap_with_fixed_context`。
3. **fixed-context displacement 只测 recrop 窗口内**：`evaluate_coarse_fine` 的 `fixed_context_unit_ids` 只采 A(request)/B(request) 里的子集（B 仅 recrop 内 fixed），recrop 窗口外 context 的位移不计入（视为不变）。局部精修语义下可接受，但口径说明需注明"仅活跃窗口内 context"。T_wp6 §2.5 未写明。
4. **Stage A/B `request_id` 相同**：两阶段共享 `song:region:R-CF`，evidence 只写 winning stage，`load_evidence_index` dict 天然只留一份；无错乱但目前依赖"只写 winner"约定，若未来写多 stage 会互覆。建议加 `stage` 维度到 evidence 文件名或用独立 id 后缀。
5. **`step_budget_note` 等 summary 文案**：`FINAL_COARSE_FINE.json` 的 `ok_stage_a_only` 计数与 `_final_rows` 的回退不一致（当前 A-only 也计入，但 evaluate 不产出 A 的 final rows，除非 B 不存在——两处口径不同），建议统一。

## 验收/留档（本次 review 实测记录）

- smoke 运行：`/tmp/cf_review/run_smoke/`；region `r_conc` → A/B 均 ok、覆盖 7 项指标齐全（aggregate 全 key）、`actual_writeback=0`；region `r_noncont` → stageA `invalid_unit_target_span`，A/B 均 not_constructible，缺 identity → RUN_STATE 用 `r_noncont:R-CF:no_identity` marker。resume 幂等（T_wp6 已验）。
- 证据：`/tmp/cf_review/run_smoke/forward/evidence/s1:r_conc:R-CF.json`（`proposal_method=R-CF`，4 rows）。
- 测试：`python -m pytest -p no:capture -q tests/unit_realign` → **91 passed**（2.46s）。
