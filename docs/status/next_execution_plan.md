# Next Execution Plan

## 阶段 1：合并并验证本归档

在服务器项目根 `LyricAlignment/` 中：

1. 合并本包，确认根目录名没有日期或阶段后缀；
2. 核对 Git branch、remote 和 dirty 状态；
3. 运行：

```bash
python -m compileall -q src scripts tests
python -m pytest -q
```

4. 执行环境捕获：

```bash
python scripts/environment/capture_environment.py \
  --out runs/smoke/<run_id>/environment_full.json
```

5. 若 Transformers 来自源码，确认 `direct_url.vcs_info.commit_id`；无法获取时明确记录未锁定。

## 阶段 2：schema-v2 raw smoke

使用 gitignored local config，从 `configs/assets/smoke_samples.example.yaml` 生成实际配置。

至少执行：

- 官方 speech 示例 1 条；
- M4Singer 原生短片段 3–5 条，覆盖不同歌手/歌曲及拖音、停顿等可观察情况；
- 暂不使用没有可靠歌词映射的 MIR-1K；
- OpenCpop 仍阻塞时不绕过授权。

验证：

- 失败样本可重试；
- 同 revision/config/input 的成功结果可跳过；
- 改 revision、config、音频或文本后会重新执行；
- 每条 JSON 有模型身份和 hash；
- `runs/smoke/<run_id>/` 有 command、environment 和 run summary；
- runtime 字段口径明确；
- overlap/gap 不再误报为 start/end 逆序。

本阶段仍无 GT metric，不据此冻结模型或筛数据。

## 阶段 3：统一数据清洗与数据集构建

本阶段同时设计字符边界和长音频，不另建临时长音频管线。

### 3.1 音频与文本规范化

- 统一未来模型输入格式并记录原始/转换文件 hash；
- 保留原歌词和规范化歌词；
- 建立 phoneme/syllable/note 到中文字符的显式映射；
- 记录 mapping status、异常原因和人工复核。

### 3.2 长度类型

manifest 必须包含：

```text
length_source = native_short | synthetic_concat | natural_long
```

- `native_short`：M4Singer/OpenCpop 原生切片；
- `synthetic_concat`：只允许同歌曲、正确相邻顺序的片段；
- `natural_long`：真实连续歌声，优先 test-only。

### 3.3 synthetic concat

构造 20/30/60/120 秒等长度 bucket，并记录：

- source item IDs 与顺序；
- 拼接点和是否插入静音；
- 每段字符时间戳平移；
- 接缝标记；
- 输出音频/manifest hash；
- 与原生样本的 split 继承关系。

不得让同曲短片段和拼接版本跨越 train/validation/test，避免切片包含泄漏。

### 3.4 natural long

- MIR-1K 仅在歌词严格对应时作为 test-only/OOD；
- 未来补充少量 60–180 秒真实连续歌声；
- 覆盖间奏、长音、重复歌词、漏唱/加词等；
- synthetic 与 natural 结果分别报告。

## 阶段 4：schema/metric smoke

数据清洗后再实现：

- perfect、shifted、missing、extra 等人工 fixture；
- character-level metric 单元测试；
- 少量人工核验；
- 冻结 split 和 raw baseline。

## 阶段 5：适配训练

上述流程稳定后再比较：

- projector 全量训练；
- audio tower LoRA；
- 短/长样本混合或 curriculum；
- language model 是否有必要调整。

## 当前禁止

- 在 schema-v2 server smoke 前直接启动 LoRA；
- 把 legacy 6.253 s 当正式 runtime；
- 把 synthetic concat 当 natural long；
- 在数据清洗前临时实现另一套不可追溯的长音频拼接；
- 使用 MIR-1K 训练；
- 绕过 OpenCpop 官方授权。
