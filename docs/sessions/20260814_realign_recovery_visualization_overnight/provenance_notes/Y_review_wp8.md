# Y_review — WP8 P6 adaptive expansion 审查（代码正确性/契约 + 数据/接线）

审查对象：`src/lyricalign/unit_realign/adaptive_expansion.py` + `scripts/unit_realign/run_adaptive_expansion.py`
commit `5f17160`（WP8 P6 adaptive expansion orchestration）。只报 P0/P1；MINOR 进 backlog。
审查方式：只读代码 + 最小 CPU（`py_compile`、直接函数调用验证、合成 smoke、git diff --check）。未跑 GPU forward。

---

## P0 — schema-tolerant 字段别名与真实 WP3/4/6 FINAL 字段名不匹配 → 真实运行会**静默不扩任何机制**

**问题**：`adaptive_expansion.region_recovery` 的恢复率字段别名表（`fields_100`/`fields_200`）是
`region_strict_100 / strict_100 / best_strict_100 / best_100 / hit_100 / r100 / strict_100_ratio / region_recovery_100`
（及 200 变体）。但三个真实 runner 产出的 FINAL aggregate 行字段名**完全不同**，全部落在这张表之外：

| 机制 | 真实 runner / 文件 | 真实恢复率字段 | 是否被本实现读到 |
|---|---|---|---|
| E2 split | `split_variants.py` L562-563 | `strict_100_recovery` / `strict_200_recovery` + `region_all_hit` | 否（别名表无 `*_recovery` 后缀） |
| E4 coarse→fine | `coarse_fine.py` L678-679 | `target_recovered_100` / `target_recovered_200` | 否（别名表无 `target_recovered_*`） |
| E1 direct chain | `multi_iteration.py` L663-667 | `all_target_recovered`(bool) / `case_pct_recovered` | 否（且 region 级无 strict 100/200 **比率**字段） |

**证据**（`PYTHONPATH=src` 直接调用验证）：
- 用真实 E2/E4/E1 字段行跑 `region_recovery(...)` → `{'strict_100': None, 'strict_200': None, ...}`，恢复率为 `None`。
- 用真实字段行跑 `mechanism_metrics([...])` → `mean_strict_100/200=None`、`recovery_score=0.0`（每机制）。
- 用真实字段行跑 `rank_mechanisms({E2,E4,E1}, top_k=2)` → **返回 `[]`（空）**（eligible 需要 `recovery_score>0`）。
- 连 E4 的 `forward_cost`（`coarse_fine.py` L695）也不在 `mechanism_metrics` L146 的
  `forward_attempts/n_forward/forward_count` 读取表中 → E4 `mean_forward_attempts=None`、`fwd_penalty=0`。

**影响**：真实 WP3/4/6 FINAL 输入下所有机制 `recovery_score=0` → 无一进入 eligible → `rank_mechanisms` 返回空 →
`run_adaptive_expansion.__main__` 的 `chosen_ids` 为空 → 兜底 `ranking[:top_k]` 也为空 → **零机制扩量**，
且**不报错**（fail-open）。这正是测试条目 #5 警告的"字段缺省→静默 recovery_score=0→误排/漏扩"。
X-note §8 也确实标注"需要确认真实 screening FINAL schema"，但未对真实字段名核对就交付。

**建议（P0 修复）**：把 `region_recovery` 别名表补上真实字段，且**在进入扩量前做 fail-closed 校验**：
任一被扫描的 FINAL 其 region 行在恢复率别名表中**全部 `None`** 时，`_load_screening`/`rank_mechanisms`
应显式报错（如 `ValueError: mechanism <id> 无任何可识别 strict recovery 字段（rows[0] keys=…）`），
而不是静默给 0。建议字段表至少补：
- E2：`strict_100_recovery`、`strict_200_recovery`；
- E4：`target_recovered_100`、`target_recovered_200`；
- E1：区域行如无严格 100/200 比率，则用 `case_pct_recovered`/`all_target_recovered` 作为 200ms 级门，或要求 E1 runner 在 region aggregate 明确输出 `strict_*_recovery`（跨模块接线一致性修改）。
- fwd：补读 E4 的 `forward_cost`。

---

## P1 — `_load_screening` 机制 id 推断对真实 FINAL 失效，`FILENAME_MECHANISM` 映射成死代码，且 E1/E2 在 `family` key 下**合并/碰撞**

**问题**：`run_adaptive_expansion._load_screening`（L92-96）推断机制 id 的顺序是
`mechanism_id` > `family` > `FILENAME_MECHANISM`。真实三个 runner 的 FINAL 摘要**都没有顶层 `mechanism_id`**，
但**都有顶层 `family`**（`run_multi_realign.py` L292 `family=R-U`、`run_split_realign.py` L334 `family=R-U`、
`run_coarse_fine.py` L291/155 `family=R-CF`，`FOURTH_FAMILY="R-CF"`）。因此第三条文件名映射
（`E1_direct_i5/E2_adaptive/E4_coarse_fine`）**永不到达**（死代码）。

**证据**：对三个"长得像真实 FINAL"（带顶层 `family`、无 mechanism_id）的文件跑 `_load_screening` →
返回 key 为 `['R-U','R-CF']`。E1(`FINAL_TRAJECTORY`) 与 E2(`FINAL_SPLIT`) 都被 key 成 `"R-U"`，
**dict 后者覆盖/与前混合** → 两个不同机制（direct vs split）的 aggregate 行**被合并到同一个机制桶**下，
排序/扩量把它们当同一机制，`MECHANISM_RANKING` 里机制 id 语义错乱。
（注：X-note 的 smoke 用了显式 `mechanism_id` 才绕过；真实 runner 不产该字段。）

**建议（P1）**：`.get("family")` 分支会吞掉文件名映射。改为：仅当无法从文件名 stem 匹配已知映射时
才回退到 `family`；或要求各 runner 在 FINAL 摘要明确写 `mechanism_id`。二者任选，但必须让
`FILENAME_MECHANISM` 在实际路径下生效，并阻止 E1/E2 在 `"R-U"` 下碰撞。

---

## P1 — `FINAL_EXPANSION.json` "不覆盖" 契约未实现（无条件写，无存在性守卫）

**问题**：X-note §8 声称"`FINAL_EXPANSION.json` 只在无旧文件时写入；重跑需手动清掉旧输出或换 `--out-root`，
避免静默覆盖原始聚合"。但 `run_adaptive_expansion.py` L241 `_write_json(root/"FINAL_EXPANSION.json", result)`
是**无条件写入**，从头到尾无 `exists()` 守卫，也无任何路径存在性检查。

**证据**：对同一 `--out-root` 非 resume 重跑两次，文件被重新覆盖写（本次因输入确定、内容重算相同，
md5 碰巧一致；但**一旦输入/schema/out-root 复用且内容变化，旧结果即被静默覆盖**，无任何告警）。

**影响**：违反 AGENTS 项"不静默覆盖原始 aggregate JSON"，破坏审计可追溯；重跑撞同一 out-root 会丢旧结果。

**建议（P1）**：写前 `if (root/"FINAL_EXPANSION.json").exists(): raise FileExistsError(...)` 或按 X-note
语义加 `--force`。RUN_STATE/RANKING 等同样建议确认覆盖语义（至少 FINAL_* 必须守卫）。

---

## 实测通过项（无 P0/P1）

1. **#1 disjoint / song-held-out 严格性：PASS**。用合成 population（10 歌×30 region）+ screening ids 验证：
   `main∩screening=∅`、`confirmation∩screening=∅`、`song_sets_disjoint=true`；`reserve_songs` 从 main_pool 排除，
   确认不会"reserve 后进 main"。main/confirmation 与 screening region、main 与 confirmation song 集均严格不相交。
2. **#2 ranking 机制排序：PASS**（在 schema 字段匹配的前提下）：composite=`0.55*recovery+0.35*safety-fwd_penalty`
   覆盖 strict recovery + safety；只扩 top-k（默认 2）；`recovery_score<=0` 的机制被 eligible 过滤排除。合成金
   （E4 r200=0.90 / E1=0.82 / E2=0.55）→ 排序 `E4(0.8055) > E1(0.7571)`，E2 不入 top2，符合预期。
3. **#3 规模：PASS**（合成 50 songs×30）→ main=200、confirmation=40 均 `complete`；per_song_cap 分层多歌分散。
   （保守：若 region pool 歌数不足，audit 会把 `main_status` 标为 `exhausted`，是显式回退而非静默——见 MINOR。）
4. **#4 纯 CPU / 账本记账：PASS**。runner 全流程仅 CPU；无任何 model forward/GPU 调用；预算仅 `estimate` 投影
   （main=400=200×2 mech、conf=80、×6 fwd/region → 2880 forwards，并注明"estimation only"）。`FINAL_EXPANSION.json`
   `budget_projection` 只写 estimate，不覆盖真实 forward（本 WP 不跑 forward）。
5. **#6 resume 幂等 / 内容寻址：PASS**。`screening_digest` 是筛选取向的 sha256（按机制排序后对 region 行
   `sort_keys` 序列化），输入变→digest 变→重算；digest 不变+`--resume`→`"resumed":true` 复用旧输出。实测改 E4
   一个 `strict_200` 后 digest 变化、全量重算，正确。
6. **语法/卫生**：`py_compile` 两文件 PASS；`git diff --check` 无输出。

---

## 环境阻塞（非代码缺陷，须上报）

任务要求"`tests/unit_realign` 需全绿"，但 **`lyricalign-qwen` 环境里 pytest 二进制级 segfault（exit 139）**：
- 即使是 `python -m pytest --version`、或在 `/tmp` 放一个 min 测试、`PYTHONPATH=` 空环境、`-p no:cacheprovider`，
  全部 `Segmentation fault` 且**零 stdout**（pytest 启动即崩，与项目/测试代码无关）。
- `python -c "import pytest"` 与 `import torch` 均正常；崩溃发生在 pytest 主程序启动阶段。
- 已尝试 `OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1`，无用。

**影响**：无法按任务要求对本提交执行 `tests/unit_realign` 全绿验证；该环境为环境回归（疑似 pytest 8.4.2 /
该 python 构建不兼容），需在修复 env（重装 pytest 或换 python）后补跑。本 review 的 WP8 结论不依赖该测试，
已用直接函数调用 + 合成 smoke 覆盖关键路径。

---

## MINOR（backlog，不阻塞）

- 确认歌曲数预留**无 slack**：`select_regions_for_expansion` 先按 `confirmation_target` 预留最少的歌，再做 main
  `target_n`；若 population 歌数不足（如 10 歌时预留 7、main 池仅 3 歌×cap6=18<200），main 会 `exhausted`。
  audit 已显式报 `main_status=exhausted`（非静默），但正式池歌数需在跑扩量前核对 ≥ 约 `ceil(target/6)+ceil(conf/6)`。
- E2 的 `region_all_hit` 能被读到（`all_targets_hit` 别名命中），但其作为 200ms 级"全中"门，若 strict 字段缺失时
  不被当作 recovery，未接进 `recovery_score`。建议在字段缺失时把 `all_targets_hit` 折算进恢复率。
- `safety` 用 `region_safety` 的 `fixed_context_displacement_ms`（max），若 E4 同时有 `mean_fixed_context_displacement_ms`
  会优先取 `fixed_context_displacement_ms`（max），口径需在报告中明确。
- X-note §8 已有项（fwd_penalty=0.10@16 权重、strict_250ms 扩展、real-schema 核对）继续保留。

---

## 结论

2 个 P0/P1 级别 bug 需在 G7/正式扩量前修：
- [P0] 恢复率字段别名与真实 WP3/4/6 FINAL 字段不匹配 → 真实运行静默零扩量；缺 fail-closed。
- [P1] `_load_screening` 机制 id 推断被顶层 `family` 短路 → 文件名映射死代码、E1/E2 合并进 `"R-U"`。
- [P1] `FINAL_EXPANSION.json`"不覆盖"契约未实现（无条件覆盖写）。
disjoint/song-held-out、top-K 排序、规模、纯 CPU 账本、resume 内容寻址 均验证通过（在字段匹配前提下）。
pytest 因环境 segfault 无法运行，已单独上报。
