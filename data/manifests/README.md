# Manifests

保存轻量数据索引模板和后续冻结的 manifest。

- `manifest_alignment.template.csv`：字符级/词级 forced-alignment 样本模板。
- `manifest_asr_baseline.template.csv`：可选 audio-to-text 样本模板。

真实项目中建议分为：

```text
raw/
curated/
splits/
```

manifest 使用相对路径，并包含 `dataset_id`、稳定 `item_id`、annotation level、来源、hash、状态和版本。不得以 LRC 行作为主标注单位。
