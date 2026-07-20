# Project Current

**Snapshot date:** 2026-07-20  
**Stage:** smoke infrastructure repaired; server rerun and data cleaning pending

## 当前定位

```text
audio + known Mandarin lyrics
-> Chinese character-level timestamps
-> raw Qwen baseline
-> unified data cleaning and long-audio construction
-> staged adaptation
-> held-out evaluation
```

## 已确认资产

### Qwen Forced Aligner

- model ID：`Qwen/Qwen3-ForcedAligner-0.6B-hf`
- 2026-07-19 resolved revision：`c07281df297b9905d24a508279258cccf987a064`
- 历史服务器缓存：`/home/hyan/Data/lyricalign/models/hf_cache/.../c07281df297b9905d24a508279258cccf987a064`
- 一条 5.005 s M4Singer raw smoke 被报告成功，返回 12 项且无报告中的结构 warning；
- 原逐样本 JSON、命令、配置 hash 和 output hash 未随旧包归档，因此证据强度为 report-level；
- 旧 6.253 s 为未拆分 wall time，可能包含 lazy model load，不能解释为 warm runtime 或正式 RTF。

### M4Singer

- 共享路径：`/home/hyan/Data/datasets/m4singer`
- 已报告约 20 GB / 65,198 文件；
- WAV 和根 `meta.json` 的 `item_name`/中文 `txt` 映射可用于 raw smoke；
- 直接只读复用，不再传输第二份完整数据。

### MIR-1K

- 历史发现路径：`/home/hyan/Data/ast_data/mir1k/current -> prepared`
- vocal WAV 可读；
- 可靠歌词映射尚未审计；
- 当前仅作为未来 test-only/OOD 候选，不加入训练。

### OpenCpop

- 尚未获取；
- 官方流程需要授权/表单，当前保持 blocked；
- 下载脚本已修复 HTTP Range 和 HTML 响应检查，但不能替代授权。

## 本包已修复

- 只跳过同模型 ID、resolved revision、行为配置、音频和文本均一致的成功结果；
- 失败、损坏、旧 schema 或身份变化的结果会重新执行；
- 逐样本保存模型身份、输入 hash、配置 hash、结构诊断和 runtime；
- run 内保存轻量 command、环境摘要和外部 JSON hash；
- runtime 拆分为 model load、audio decode、input prepare、forward 和 alignment decode；
- start/end 倒退、负时长、overlap、gap 和越界分开记录；
- `verify_assets.py` 输出父目录 bug 已修复；
- OpenCpop 续传不会在服务器忽略 Range 时错误追加；
- 增加环境捕获工具和已知版本记录。

## 长音频判断

5 秒片段表现良好只证明短样本调用链可用，不能证明完整歌曲稳定。M4Singer raw 缺少自然长音频，OpenCpop 尚不可用，MIR-1K 不加入训练。

长音频准备统一纳入下一阶段数据清洗：

- `native_short`：原生短切片；
- `synthetic_concat`：同歌曲相邻片段顺序拼接并平移字符时间轴；
- `natural_long`：真实连续长歌声，主要用于 test-only 和最终验证。

虚拟长音频不能冒充真实连续歌声，报告和 split 必须保持类型字段。

## 环境状态

历史记录：Python 3.12.3、PyTorch 2.8.0+cu128、Transformers 5.15.0.dev0、huggingface_hub 1.24.0、soundfile 0.14.0、RTX 4080 SUPER 32 GB。

Transformers 源码 commit 尚未从旧证据恢复。服务器重新运行前必须执行 `scripts/environment/capture_environment.py` 并保存 `direct_url.json` 中的 commit（若可获得）。

## 尚未完成

- 本包在目标服务器合并后的 Git 状态和测试；
- schema-v2 official/M4Singer smoke；
- OpenCpop 获取；
- 数据清洗、字符 schema、长音频构造；
- metric、训练、LoRA 和 held-out evaluation。
