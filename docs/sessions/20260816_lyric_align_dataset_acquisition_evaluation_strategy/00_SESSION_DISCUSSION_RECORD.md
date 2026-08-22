# 会话记录：Lyric Align 机制困惑 → 数据集补充 → 无训练评测策略

- 日期：2026-08-15～2026-08-16（UTC）
- 记录原则：用户意见尽量保留原话；Assistant 的判断、执行结果和后续建议单独标明，不把建议反向写成用户已经确认的事实。

---

## 1. 用户指出当前问题：模式很多，但不知道为什么好或坏

用户原话：

> “我对当前项目有点迷茫，我可以调很多模式很多行为，但是我不知道它们为什么好为什么坏。”

用户随后限定讨论对象：

> “我说的是lyric align”

继续指出证据和复杂度问题：

> “我们目前的数据感觉不够支持这个。而且我们现有的机制组合很复杂。”

本轮对问题的理解由此冻结为：当前困难不是缺少更多开关，而是缺少能够解释各机制适用条件、收益和副作用的分层证据。后续工作应服务于“为什么好/为什么坏”，而不是继续扩大组合空间。

## 2. 用户询问资料、数据规模和替代数据集

用户原话：

> “阅读资料，数据集是有的，但是我觉得规模也一般。”

> “有什么其他可取的数据集？”

讨论形成的数据角色拆分：

- 真实流行混音对齐评测：MIR-MLPop、JamendoLyrics；
- 中文清唱、音素边界和技巧唱法压力测试：GTSinger；
- 日语音素/假名转换与边界单测：PJS；
- 社区逐词时间标注候选池：AMLL TTML DB；
- 人声/伴奏 benchmark 候选：iKala，但访问受限；
- 不因为数据存在就混入训练；每个数据集必须先定义角色、许可和输入域。

## 3. 用户询问空间规划，随后明确要求直接尝试获取

用户先问：

> “空间还有120G，可以怎么规划”

随后明确授权本轮获取，并把空间优化降为次要：

> “先不用管现有空间，按照你说的尝试帮我获取数据集。注意参考其他数据集的存储方式和md文件的说明妥善适当地存储。可以再获取少量的英、日、粤语。”

据此执行的存储规则：

```text
/home/hyan/Data/datasets/<dataset_id>/
  README.md
  SOURCE.md
  TERMS.md
  acquisition.json
  checksums.sha256
  acquisition/
  raw/downloads/
  raw/extracted/
```

大型外部数据没有进入 Git 仓库；仓库只更新轻量的 `data/datasets_registry.md` 和 `reports/assets/asset_inventory.md`。

## 4. 实际获取结果

### 4.1 MIR-MLPop

- 官方仓库和 240223 版 cmn/nan/yue 标注已取得；
- 普通话请求 30 首，最终取得 20 首 WAV，约 5,515.646 秒；
- 粤语取官方 Test split 前 5 首（song_id 21–25），最终取得 22、23、24 三首，约 735.670 秒；
- 普通话缺失 ID：7、8、9、10、12、14、26、27、28、30；
- 粤语缺失 ID：21、25；
- 先运行未修改的官方 downloader，再用 Node JavaScript runtime 和新版 yt-dlp 重试；剩余失败来自视频下架、地区限制或 HTTP 403；
- 官方条款为学术非商业用途，不允许把本地副本视为可自由再分发音频。

### 4.2 AMLL TTML DB

- 固定 revision 的浅层 partial/sparse snapshot 已取得；
- 保存 `raw-lyrics/`、`metadata/` 和 `instructions/`；
- 共 3,160 个 TTML，全部通过 XML parse；没有下载对应商业歌曲音频；
- 上游对仓库贡献声明 CC0，但这不能清除底层歌词、翻译、出版方等第三方权利；当前只作 internal research-only silver pool。

### 4.3 PJS v1.1

- 官方归档完整取得并通过 `unzip -t`；
- 100 段歌唱、100 段朗读，另有 MIDI、MusicXML、文本和原始音素标签；
- 歌唱约 1,611.444 秒，朗读约 542.620 秒；音频均为 48 kHz、mono、24-bit PCM；
- 另存 100 份人工重标音素标签及独立 Git revision；
- 许可为 CC BY-SA 4.0；定位为日语校准/单测，而不是真实流行混音最终评测。

### 4.4 JamendoLyrics MultiLang English

- 完整取得新版 `en/test` config：20 首 MP3、5,693 个 word interval、868 个 line interval；
- 总时长约 4,333.845 秒，全部音频可解码，所有时间区间顺序合法；
- 保存了 Hugging Face dataset API 原始响应作为 revision 证据，并纳入 checksum；payload 目录不是独立 Git checkout；
- 六种逐曲许可同时存在，必须保留每首的 `license_type` 和原 Jamendo URL；
- 当前只有 raw mixture。项目要求 vocal-only，在生成 separator identity/config/input-output hash 完整的派生资产前，不能称为可直接运行的正式 benchmark。

### 4.5 GTSinger Chinese mini

- 定向选取 5 个歌曲根，覆盖两位歌手和 Breathy、Mixed Voice/Falsetto、Pharyngeal、Glissando、Vibrato；
- 完整取得 850/850 文件：231 WAV、231 TextGrid、231 JSON、157 MusicXML；
- 231 段音频约 1,578.503 秒，均为 48 kHz、mono、24-bit PCM；JSON/XML/音频检查全部通过，无残留 `.part`；
- 上游在 CC BY-NC-SA 4.0 后附加 indemnity、代表雇主接受等协议，且文本异常提到 “authors of M4Singer”；适用范围未澄清前，仅限内部非商业研究，不代表用户或雇主接受附加协议。

### 4.6 iKala

- Zenodo 主文件为 Restricted；
- 没有代表用户填写需要姓名、机构和用途承诺的访问申请；
- 本地只记录 `blocked_pending_access`、来源和未解决的 custom license，没有主音频。

### 4.7 完整性结果

- 本轮新增外部资产约 2.3 GB；
- 5 个实际取得 payload 的数据集共保存 4,186 条 SHA-256；
- checksum、音频解码、JSON/XML 解析和已检查时间区间均通过；
- 两路独立只读复核提出的 Jamendo revision evidence、GTSinger 附加协议、AMLL 第三方歌词权利和 Jamendo vocal-only 输入契约问题均已修正，最终无 P0/P1。

## 5. 用户提出 2:5:3，并明确暂不训练

用户原话：

> “按照你之前的分析，我们可以怎么做？我的想法是这些数据使用2:5:3的比例分成训练、测试、封存，甚至不分训练。我暂时不想训新的，可以先在旧的上面继续研究。接下来可以做什么？”

这里用户明确了两个方向：

1. 希望有较大比例用于测试，并保留真正封存的数据；
2. 当前不训练新模型，继续研究旧模型和现有推理机制。

## 6. Assistant 对 2:5:3 的解释与建议

Assistant 建议在无训练阶段把比例重命名为：

```text
20% diagnostic_visible
50% regression_selection
30% sealed_final
```

理由：

- `diagnostic_visible` 允许听音、看可视化、逐条检查和调机制；
- `regression_selection` 用于批量比较和选择方案，只要根据其结果选过配置，它就不再是真正 test；
- `sealed_final` 平时不运行、不看逐条结果，只在阶段性版本开启，才承担最终无偏测试角色；
- 因此用户原称的“训练集”在本阶段实际是工作/诊断集，不用于更新模型权重。

## 7. Assistant 建议的分数据集策略

- MIR-MLPop 普通话现有 20 首可自然映射为 4/10/6：4+10 只从官方 Train 可用项中分，官方 Test 现有 6 首全部封存；
- JamendoLyrics 20 首可按歌曲做 4/10/6，并按长度、重叠人声、非词汇演唱和复调属性分层；
- PJS 100 首可做 20/50/30；同编号 song/speech/原标签/人工重标必须在同组；
- GTSinger 不能把 231 个片段随机散开，应以 5 个歌曲根为单位；可考虑 1/2/2，但每个技巧只有一个歌曲根，因此只能逐歌曲报告，不能把 technique 差异解释成 split 差异；
- 粤语只有 3 首，建议 1/1/1 或全部标记 exploratory probe，不给出强统计结论；
- AMLL 没有绑定可用音频，不进入数值 split；
- iKala 在授权前排除。

这些数字是本轮建议，尚未生成或冻结具体 item manifest。

## 8. 暂不训练时的研究主线

当前优先任务应是固定旧模型，研究推理机制行为，而不是扩大模式组合：

1. 冻结当前稳定 baseline 的模型 revision、代码 revision、配置和输入 manifest；
2. 把现有机制拆成输入/文本规范化、窗口与候选、对齐选择、silence/recovery、后处理五层；
3. 第一轮只做单因素消融；
4. 只有独立有收益的机制进入少量两两交互；
5. 每个机制记录目标故障、触发条件、可能副作用和数据证据；
6. 先过 diagnostic，再过 regression；sealed 只在里程碑运行；
7. 不把不同数据集、语言和 word/character/phoneme 粒度压成一个总分。

建议至少报告：onset/offset 绝对误差中位数与 P90、100/200/500 ms 命中率、严重失败率、漏字/重复/跨行/长间奏/短词/拖音分类、运行时间和 fallback 触发率。

## 9. 本轮最终状态与边界

已完成：

- 新数据的获取尝试、规范落盘、来源/条款/采集记录和 checksum；
- 项目数据登记和资产清单更新；
- 无训练阶段的 2:5:3 暴露策略讨论；
- 两轮风险修正后的独立只读复核。

尚未完成：

- `evaluation_v1` 的具体 item 分配和 manifest hash；
- vocal-only 派生与 separator provenance；
- 旧模型跨新数据 baseline；
- 行为 registry 与单因素消融报告；
- sealed runner 和 milestone 开启协议。

后续执行不得把“已下载 raw 数据”“已建议 split”和“已完成 operational evaluation”混为同一状态。
