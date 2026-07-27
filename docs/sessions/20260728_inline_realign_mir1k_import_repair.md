# Inline realign MIR-1K 导入修复 — 2026-07-28

## 问题

Formal 扩大 MIR-1K 设计样本后报错：

```text
FileNotFoundError: .../mir1k_subset_v1/items/leon_1/lyrics.txt
```

## 根因

`prepare_mir1k_demo_subset.py` 的历史约定是：

- development：物化到 `items/`；
- heldout：物化但默认不使用；
- quick_v2_extra：被显式提升后物化；
- spare：只保留 `selection.jsonl` 元数据，不物化歌词、GT 和音频。

上一版 follow-up formal 为扩大数据量，将默认角色改为 `development,spare`，但 `build_inline_realign_manifest.py` 仍直接假设每行已经存在：

```text
items/<item_id>/lyrics.txt
items/<item_id>/ground_truth.characters.jsonl
items/<item_id>/audio/official_vocal.wav
items/<item_id>/audio/mix.wav
```

因此 `leon_1` 并非导入路径拼错，也不是服务器文件意外丢失，而是 metadata-only spare 被错误当成已物化样本。

## 修复

1. `prepare_mir1k_demo_subset.materialize()` 新增可选 `materialize_roles`，默认仍保持旧行为，显式调用时可以物化 spare。
2. manifest 构建器在选择 MIR-1K 行后先做完整资源审计。
3. 发现缺失时，从 `selection.json` 读取 `source_characters`、`mir1k_root` 和 `units_per_line`，只补齐本轮实际选中的缺失样本。
4. 补齐后再次验证歌词、GT、所选 vocal 和 mix；仍缺失则在模型推理前失败。
5. Formal 默认角色修正为 `development,quick_v2_extra,spare`，即全部非 held-out 设计样本；held-out 仍只由 `--include-heldout` 开启。
6. 修复过程写入 `input_audit.json.mir1k_asset_repair`。

## 恢复

使用修复包覆盖项目后，重新运行相同 formal 命令即可。失败发生在 manifest/首样本阶段时，已有输出目录可以直接复用；不需要删除数据集目录，也不需要手动创建空 `lyrics.txt`。

## 验证

- 针对性单测：25 passed；
- 除当前环境缺少 `pypinyin` 的 3 个既有测试外：170 passed；
- 真实 FFmpeg 物化演练：development 已存在、spare 仅有 metadata，构建器成功补齐 spare 的歌词、GT、official vocal 和 mix，并将两首写入 manifest。
