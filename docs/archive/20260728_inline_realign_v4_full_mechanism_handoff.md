# Inline Realign v4 全机制实现交接

## 1. 实现状态

本归档完成：

- 30/60 秒固定、静音吸附、严格静音边界和全静音压缩条件；
- Raw cursor control；
- Stable 音频—歌词同步裁剪 exact/−2/−4 与 anchor-only；
- 文本剂量 under/exact/over；
- Immediate/Deferred 的结构不升和零时长宽松 gate；
- 三上下文中位融合；
- Raw nonnegative/minimal monotonic 消融；
- canonical v3 tolerant 主指标；
- run/stage/item/render 严格 resume；
- 后置渲染与双完成状态；
- 中文字符化 timeline、完整 PMF、三子图 inconsistency 和固定比例行为视频；
- smoke/formal/render-only/cleanup/status 一条龙入口；
- bounded evidence 收集。

所有 realign 仍为 shadow-only，`actual_writeback` 应保持 0。

## 2. 主要入口

```text
scripts/demo/run_inline_realign_smoke.sh
scripts/demo/run_inline_realign_formal.sh
scripts/demo/run_inline_realign_render_only.sh
scripts/demo/watch_inline_realign_status.py
scripts/demo/cleanup_inline_realign_overwrite.sh
```

主 Python controller：

```text
scripts/demo/run_inline_realign_pipeline.py
```

## 3. 关键实现文件

```text
scripts/demo/build_inline_realign_manifest.py
scripts/demo/run_inline_realign_experiment.py
scripts/demo/align_qwen_fa_serial_demo.py
scripts/demo/analyze_inline_realign_visuals.py
scripts/demo/render_inline_realign_demo_batch.py
scripts/demo/summarize_inline_realign_followup.py
scripts/demo/collect_inline_realign_evidence.py
src/lyricalign/demo/window_planning.py
src/lyricalign/demo/run_state.py
src/lyricalign/demo/visual_diagnostics.py
src/lyricalign/demo/timeline_video.py
```

## 4. 旧实现中已确认的问题

1. stable trial 丢失 TTC SC index 的字体问题已在前一轮修复；本包不含字体文件；
2. 旧 stable 音频/歌词错位定义已废弃；
3. 旧 `stable_left_overlap_units` 未定义变量已修复，参数仅为兼容身份保留；
4. watcher 读取字段不匹配已修复；
5. 缺失静态图或视频会让对应 stage 明确失败；
6. 旧 `would_write` 已拆分；
7. 旧 matched-only MAE 不再作为主指标；
8. 旧缓存复用不再伪称 strict resume。

## 5. 运行迁移

源代码可直接解压覆盖 `/home/hyan/LyricAlignment`。

旧 v3 结果不可与 v4 共用身份。推荐使用 v4 默认新输出目录。必须复用旧目录时：

```bash
bash scripts/demo/cleanup_inline_realign_overwrite.sh OLD_OUT_ROOT all
```

正常中断恢复时绝对不要 cleanup：

```bash
OUT_ROOT=... RESUME=1 bash scripts/demo/run_inline_realign_formal.sh
```

## 6. 已知解释边界

- 严格静音边界由 vocal activity 决定，弱唱误判仍需通过 E1 结果检查；
- 全静音压缩会制造拼接点，只是诊断条件；
- Stable 同步裁剪依赖 baseline 时间作为裁剪边界，若 baseline 错误可能冻结错误锚点；
- 零时长宽松 gate 可能只改善结构而不改善真实时间，必须结合 GT 与视频；
- 中间层 timestamp 尚未实现，待 D0–D6 结果证明有必要后再做；
- 视频只对 Demo 生成，数据集主要使用静态图和数值结果。

## 7. 验证要求

应用后先运行：

```bash
PYTHONPATH=src pytest -q \
  tests/test_inline_realign_v4_full_mechanism.py \
  tests/test_inline_realign_pipeline.py \
  tests/test_inline_realign_v3_visual_config.py \
  tests/test_qwen_fa_serial_demo.py \
  tests/test_alignment_artifacts.py
```

随后运行 smoke。只有 `analysis_complete.json` 为 complete、失败计数为 0，并人工检查代表性图后，才启动 formal。

## 8. 本归档验证结果

```text
Python compileall: passed
All shell scripts bash -n: passed
Focused Inline Realign regression: 90 passed
Broad repository tests excluding three unavailable-pypinyin collection modules: 209 passed
```

完整未过滤 pytest 在当前归档环境中因缺少 `pypinyin` 停止于三个测试模块收集；这三个模块没有被声明为通过。详见：

```text
IMPLEMENTATION_VALIDATION_20260728.md
```

服务器应优先运行统一预检，而不是手工拼接测试命令：

```bash
bash scripts/demo/verify_inline_realign_v4.sh
```
