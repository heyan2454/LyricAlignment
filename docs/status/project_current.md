# Project Current

**Snapshot date:** 2026-07-23
**Stage:** M4Singer rule mapping review and MIR-1K vocal-only OOD preparation

## 当前定位

```text
known Mandarin lyrics + vocal-only singing audio
-> rule-validated character-level timestamp candidates
-> explicit review/reject states
-> song-level split and derived data products
-> automatic raw baseline and evaluation
-> staged domain adaptation
```

## M4Singer current operational canonical

当前规则轮次的 operational canonical manifest：

```text
/home/hyan/Data/lyricalign/derived/
20260722_m4singer_pinyin_validated_v4/prepare/m4singer_manifest.jsonl
```

### 身份

| Item | Value |
|---|---|
| source `meta.json` SHA-256 | `50030a56d4529bb460f3088534655e27b75b4e538fcbe4f2ea2a4b968935d433` |
| manifest rows | 20,896 |
| manifest SHA-256 | `22828f809e60cfaeb44f0fec973d7ce5b026fd024d0740b9120725f012d6053a` |
| character annotation rows | 193,666 |
| character annotation SHA-256 | `ba28f0e0c5f5d6c850b47632808ccc60052f3be397f3316ee95bc95678ca613d` |

### 状态守恒

| Status | Count | Meaning |
|---|---:|---|
| accepted | 20,298 | `rule_validated` character-to-phoneme candidate mapping |
| review_required | 598 | 当前规则下未自动接受 |
| rejected / failed | 0 | 全量审计中没有 schema、timing 或 audio hard rejection |
| total | 20,896 | 与源记录数守恒 |

`accepted` 是规则验证候选，不等同于已经人工确认的高置信训练集。

### 598 条 review

Primary reason：

| Reason | Count |
|---|---:|
| complex/multiple slur cases | 487 |
| single-slur one-group deficits | 74 |
| Mandarin pinyin parse failures | 36 |
| Latin/digit | 1 |

Mapping status：

| Status | Count |
|---|---:|
| ambiguous allocations | 531 |
| no-match allocations | 67 |

当前 audit 是 primary reason breakdown 的事实来源；prepare manifest 是 canonical mapping artifact。

## MIR-1K vocal-only OOD

用户已于 2026-07-22 人工确认 `UndividedWavfile` 的第二个交错 PCM 声道，即 zero-based channel index 1，为人声。实现通过按声道步进抽取 PCM，不调用 `ffmpeg -ac 1`，也不平均两个声道。

| Item | Value |
|---|---|
| output root | `/home/hyan/Data/lyricalign/derived/20260722_mir1k_vocal_channel1_ood` |
| vocal-only songs | 17 |
| character annotations | 2,035 |
| split / use | `test` / `ood_test_only` |
| extraction manifest SHA-256 | `5ed24d2a616af5764ab036876ccba919595728a31586d3b593a39bdb4fb2a9da` |
| manifest SHA-256 | `bd8109d608247b78407c1d63e9f648b83f697a00c5c0b05b3fe93c87b42c884f` |
| character JSONL SHA-256 | `78d7054ada0a3fb5ec3cd916174d094d78ab5d96f67d0112408de30dc24469c9` |

该结果是显式 vocal-only 派生物，不代表原始 stereo mixture 本身是 vocal-only。

## Historical validity

| Version / count | Validity now | Reason |
|---|---|---|
| 6,051 accepted / 14,845 review | historical v2 only; not canonical | 早期固定 gate，早于当前 pinyin/held-vowel 规则 |
| 66-item result | invalid / superseded | 历史计数错误 |
| 18,057 / 2,839 | superseded intermediate | 早于独立字符 heteronym 处理和 `q+v` 等 M4Singer 转换修正 |
| 20,298 / 598 | current operational canonical | 与当前 manifest、audit 和总数守恒一致 |

历史 run 和报告可以保留用于追溯，但不得与当前 manifest 混合或继续作为当前状态源。

## Qwen Forced Aligner

- model ID：`Qwen/Qwen3-ForcedAligner-0.6B-hf`；
- resolved revision：`c07281df297b9905d24a508279258cccf987a064`；
- Transformers source commit：`7ea2320c76117e6742364808a666ef6f2fb40a67`；
- 已有短片段和旧版本数据的 raw inference 记录；
- 旧 inference 与旧 manifest 绑定，不能直接当作当前 canonical 数据的正式 baseline；
- raw smoke 只证明调用链，不构成准确率结论。

## 当前包与外部数据的关系

- 仓库保存代码、规则、命令/配置、轻量数量与 hash；
- 大型 M4Singer/MIR-1K manifest、音频和逐样本结果位于外部数据盘；
- 本归档没有重新执行外部全量数据处理；上述 canonical 数量和 hash 来自已提供的服务器 run 记录；
- 后续规则变化必须生成新目录和新 manifest，不得静默修改当前 canonical。

## 尚未形成的正式结论

- 20,298 条尚未被表述为人工确认高置信训练集；
- 剩余 598 条仍保持 review；
- 基于当前 canonical 的最终 song split、20/30/60/180 秒派生集和 raw baseline 尚未在本快照中固定；
- OpenCpop 仍受官方授权/获取流程阻塞；
- LoRA 或其他正式适配尚未开始。
