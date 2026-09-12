# 重训盘点：上一次是怎么停的 + 现在有什么数据可用（生成）

> 由 `scripts/evaluation/make_retrain_data_inventory.py` 生成；数字取自 run 内文件与磁盘实测，许可/角色条目转写自 `data/datasets_registry.md` 与采集会话快照（政策声明，不是测量）。

## 1. 上一次的停止方式与选择粒度

- 预算 **max_steps = 1110**，micro_batch × grad_accum = **32** ⇒ 折算 **约 2.0 个 epoch**；`eval_steps = 250`、`save_steps = 250`、**无早停**；⇒ 停止原因是**步数预算用尽**。
- 候选检查点 **5 个**（[250, 500, 750, 1000, 1110]），其中最后一个是 terminal_validation；**每个都做过验证**（此前我说过『1110 未验证』，是错的，已更正）。
- 验证集只有 **29 首歌**上的宏平均（selection_metric = `song_macro_boundary_mae_sec`，tie_break = `lower_checkpoint_step`），**且只存聚合值、没存逐歌数据** ⇒ 无法给出误差棒。

| 检查点 | 验证 MAE（秒） | 与最优差 |
|---:|---:|---:|
| 250 | 0.05098 | +3.83ms |
| 500 | 0.04751 | +0.35ms |
| 750 | 0.04716 | +0.00ms |
| 1000 | 0.04837 | +1.21ms |
| 1110 | 0.04841 | +1.25ms |

- 最好与次好只差 **0.35ms**；与最后一步差 **1.25ms**；五个候选总跨度 **3.83ms**，而系统的**时间分辨率是 80ms**、且指标本身要 0.2s 才稳（第 31/32 轮）。
- ⇒ 更正措辞：不能说『再练会更差』，准确说法是**『500 步以后就平了，彼此差异远小于测量分辨率，因此选择哪一个是随机的』**。

## 2. 重训前该改的协议（不是数据，是流程）

1. **验证间隔加密**（如每 50–100 步）并**保存逐歌/逐条指标**，否则任何 checkpoint 选择都不可判定；
2. 选择指标换成**分辨率足够**的口径（≥0.2s 的 within-rate，或 MAE 但配合误差棒），并把「两个 checkpoint 谁更好」与「格点余量界」一起报（第 32 轮的规则）；
3. 若继续用 M4Singer，验证集偏小（29 首歌）⇒ 建议扩充验证集（人工标注或 GTSinger 内部研究用）而不是只加训练量；
4. **保留现有 ckpt**：`r2/step-000750` 的逐文件指纹已固定（见 `docs/status/20260913_pinned_checkpoint_inventory.md`），新训练必须写到新 run 目录。

## 3. 数据盘点：磁盘上有 11 个目录，能进训练的其实还是只有 1 个

| 数据集 | 在盘 | 体量(GB) | 登记角色 | 能否进训练（依登记表） |
|---|---|---:|---|---|
| `amll_ttml_db` | 是 | 0.2 | community silver pool | 无音频，不可训练；底层歌词权利未解决 |
| `audio_works_202604` | 是 | 100.6 | real-song pool | 无标注；只能作评测/伪标签来源 |
| `gtsinger_chinese` | 是 | 0.3 | phoneme-boundary + technique stress test | CC BY-NC-SA + 附加协议未澄清；登记表限定内部非商业研究；未定前不进训练 |
| `ikala` | 是 | 0.0 | benchmark candidate | blocked_pending_access：未获授权，禁止训练 |
| `ismir2014_singing` | 是 | 0.2 | 未登记 | 同上 |
| `jamendolyrics_en` | 是 | 0.1 | English evaluation candidate | 登记表明文『不混入训练』；逐曲许可 |
| `m4singer` | 是 | 18.8 | primary train + custom validation | 可用于训练（现行唯一训练语料） |
| `mir1k` | 是 | 2.6 | OOD test-only | 禁止：不训练、不验证、不调参（登记表明文） |
| `mir_mlpop` | 是 | 1.2 | natural-mixture evaluation candidate | 仅学术非商业；普通话音频 20/30，规模不足作训练 |
| `mirst500` | 是 | 2.6 | 未登记 | 只有 raw/，无 acquisition.json/checksums ⇒ 不可依赖 |
| `pjs` | 是 | 0.6 | Japanese phoneme/boundary calibration | CC BY-SA 4.0；单男声短句，只做边界单测，域不匹配 |
| `tonas` | 是 | 0.2 | 未登记 | 同上 |

- 现行训练语料规模：标签 **20,298** 条，划分 test 839、train 17,748、validation 1,711（登记表记 20,896 items / 193,666 字符记录，且注明 `rule_validated` 属弱监督，不等同人工确认）

## 4. 结论：想加数据，路径只有三条

- **A. 走授权拿真正的普通话训练集**：登记表里 `OpenCpop`（官方 train/test）长期是 `pending official authorization/download`，而主项目定位就是普通话 character-level；**这是最对症的一条，但被外部授权卡住**；
- **B. 英文侧**：`DALI` 被登记为『English training candidate』但状态是 `deferred`（未推进）；`JamendoLyrics` 明文『不混入训练』；所以英文要练就得先推进 DALI；
- **C. 自监督/伪标签**：`audio_works_202604`（实测约 101 GB）无标注，但可以用『raw 解码 + 定向修复 + 置信度筛选』造标签。**注意与本次发现耦合**：若用现行上游修补的输出去造标签，会把 16% 的塌陷当真理学进去 ⇒ 伪标签必须走 raw + 定向修复，并用结构非法率与置信度双重过滤。

另外三个目录（`mirst500`、`ismir2014_singing`、`tonas`）只有 `raw/`、没有 `acquisition.json`/`checksums.sha256`，**属于未登记资产，不应作为训练依据**。

## 5. 复现

```bash
source /root/miniconda3/etc/profile.d/conda.sh && conda activate lyricalign-qwen
cd /home/hyan/LyricAlignment
PYTHONPATH=src python scripts/evaluation/make_retrain_data_inventory.py
```

