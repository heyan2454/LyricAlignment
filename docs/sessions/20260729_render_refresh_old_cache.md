# Inline realign 渲染修复与旧缓存安全重建（2026-07-29）

## 目的

本补丁只修复展示层：静态诊断图、视频页面和 MP4 编码。它不重新运行模型推理，不修改 alignment、实验分支、GT 指标或 local-realign scientific JSON/JSONL。

旧实验目录的冻结身份曾把可视化和渲染源码哈希纳入整条实验身份，因此直接重新执行 `run_inline_realign_pipeline.py` 会因源码变化拒绝复用旧缓存。本补丁新增独立入口：

```bash
scripts/demo/rerender_inline_realign_from_cache.py
```

该入口不初始化旧版 `RunState`，但会在重建前后计算 scientific artifact tree SHA-256；任何科学结果文件发生变化都会使命令失败。

## 修复内容

- timeline 标签由 `序号:字` 改为 `序号 字`。
- 标签按实际像素宽度自适应：过窄不画文字，中等只画字，足够宽才画序号和字。
- 限制异常长重叠造成的 lane 无限增长；静态图最多 12 lanes，视频页最多 3 lanes。该限制只影响画法，不修改时间戳。
- 跨页长区间在页面边缘显示延续箭头，减少“被剪断但不知道是否继续”的感觉。
- Inconsistency 图的 colorbar 使用独立列，三个 panel 的序号轴保持相同物理宽度。
- 视频指针改为黑色描边 + 橙色内线，按每页实际 timeline axis 匀速扫描，并在新页面重置。
- 只保留一套 CFR 帧率控制；输出后用 `ffprobe` 校验时长。
- 对缺失 mono/stereo channel-layout 元数据的输入显式声明布局，避免 FFmpeg 猜测提示。
- `render_mode=after` 的新 pipeline 顺序改为：静态图 → evidence collection → 视频页 → MP4；收集不再等待大量视频页。
- 新增 `--video-pages-only`，允许复用静态图，只重建视频页面。
- 新运行将 scientific implementation identity 与 presentation implementation identity 分离；以后只改渲染代码不应再使科学实验缓存失效。

## 应用补丁

建议先保存当前改动：

```bash
cd /home/hyan/LyricAlignment
git status --short
git diff > /root/autodl-tmp/LyricAlignment_before_render_refresh.patch
```

使用 unified patch：

```bash
cd /home/hyan/LyricAlignment
git apply --check /path/to/inline_realign_render_refresh_20260729.patch
git apply /path/to/inline_realign_render_refresh_20260729.patch
```

若目录不是 Git 仓库，可在仓库根目录解压 overlay 包：

```bash
cd /home/hyan/LyricAlignment
tar -xzf /path/to/inline_realign_render_refresh_overlay_20260729.tar.gz
```

## 更新后验证

```bash
cd /home/hyan/LyricAlignment
PYTHONPATH=src python -m compileall -q src scripts tests

PYTHONPATH=src pytest -q \
  --ignore=tests/test_audio_contract.py \
  --ignore=tests/test_m4singer_preparation.py \
  --ignore=tests/test_mir1k_partial_align.py
```

本补丁制作环境结果为 `227 passed`。三个被忽略测试在该环境中仅因未安装 `pypinyin` 而无法收集；你的 lyricalign-qwen 环境若已安装，可直接运行完整测试。

## 从旧缓存完整重建渲染

本轮正式实验目录为：

```text
/root/autodl-tmp/AST_storage/Data/lyricalign/demo_diagnostics/inline_realign_formal_v4_20260729
```

执行：

```bash
cd /home/hyan/LyricAlignment

PYTHONPATH=src /root/autodl-tmp/AST_storage/conda/envs/lyricalign-qwen/bin/python \
  scripts/demo/rerender_inline_realign_from_cache.py \
  --experiment-root /root/autodl-tmp/AST_storage/Data/lyricalign/demo_diagnostics/inline_realign_formal_v4_20260729 \
  --python-bin /root/autodl-tmp/AST_storage/conda/envs/lyricalign-qwen/bin/python \
  --font "Noto Sans CJK SC" \
  --profile review \
  --timeline-page-seconds 30
```

不要通过旧版 pipeline 的 `--resume --from-stage visualization` 入口重渲染；旧缓存会按旧冻结身份拒绝。上面的 cache-rerender 入口就是为此场景设计的。

默认顺序：

1. 强制重建静态 diagnostics；
2. 强制重建 video pages；
3. 强制重新编码 demo MP4；
4. 比较 scientific tree 的前后 SHA-256；
5. 写出 `rerender_complete.json`。

## 只更新部分展示层

只更新静态图，不生成页面和 MP4：

```bash
... rerender_inline_realign_from_cache.py \
  --experiment-root "$EXP_ROOT" \
  --skip-video-pages \
  --skip-encode
```

静态图已经更新，只重建视频页和 MP4：

```bash
... rerender_inline_realign_from_cache.py \
  --experiment-root "$EXP_ROOT" \
  --skip-static
```

只重新编码已有的新页面：

```bash
... rerender_inline_realign_from_cache.py \
  --experiment-root "$EXP_ROOT" \
  --skip-static \
  --skip-video-pages
```

默认仍跳过 automatic-incomplete demo。确实需要渲染时加：

```bash
--render-incomplete
```

正式高质量编码使用：

```bash
--profile final
```

建议先用 `review` 检查布局和指针，验收后再运行 `final`。

## 备份与日志

每次执行都会创建：

```text
$EXP_ROOT/render_refresh/<UTC timestamp>/
```

其中包含：

- `state_backup/`：旧 visualization/render summaries 与 stage/item states；
- `01_static_visuals.log`；
- `02_video_pages.log`；
- `03_encode.log`；
- `rerender_complete.json`。

根目录也会写入最新的：

```text
$EXP_ROOT/rerender_complete.json
```

成功时应满足：

```json
"status": "complete"
```

且：

```json
"scientific_identity_before": { ... }
"scientific_identity_after":  { ... }
```

两者完全相同。

## 失败恢复

渲染中断后可原样重跑该命令。该入口使用 `--force` 重建 presentation artifacts，不追加 scientific results；已有旧展示状态保存在最近一次 `render_refresh/.../state_backup/`。

若报告 `failed_scientific_cache_changed`：

1. 立即停止，不继续覆盖；
2. 查看对应 `render_refresh/<timestamp>/rerender_complete.json`；
3. 比较 scientific JSON/JSONL；
4. 从原实验备份恢复后再排查。

正常情况下分析器和渲染器不应写入这些 scientific artifacts。
