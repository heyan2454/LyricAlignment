# 文本 Mutation 与 No-match 实现规范

## 1. 严重度

以合法 baseline 的 unit 数 `N_base` 为分母。

- extra：10/25/50/100/200%；
- missing：10/25/50/75/90%；
- replacement：10/25/50/75/100%。

保存 requested_ratio、actual_ratio、绝对 added/removed/replaced units。来源文本不足时必须 not_applicable，不能静默降低比例。

## 2. 尾部过量来源

- `future_present_in_audio`；
- `future_absent_from_audio`；
- `partially_present`；
- `far_future_same_song`；
- `cross_song_wrong_suffix`。

必须区分额外歌词是否真实存在于当前 audio request。

## 3. 头部与中间

头部 10/25/50/100%，中间在 25/50/75% 位置插入 10/25/50/100%。来源分重复 prefix、future、同歌错段和跨歌文本。

## 4. 文本不足

尾/头/中间连续和分散缺失，比例 10/25/50/75/90%。中间和分散缺失要保存冻结 seed/indices。

## 5. 完全不对应主实现

### Cross-song strict no-match

对 target audio，从另一首歌选同语言、同 unit mode、同长度连续歌词片段：

```text
donor_song != target_song
len(donor_segment) == N_base
```

过滤偶然相似：

- normalized LCS；
- longest contiguous match ratio；
- token/word n-gram overlap；
- 可用时 phonetic similarity。

阈值在 pilot 冻结；保存 donor ID、indices、指标、seed 和 manifest SHA256。

### 同歌错段

单独标记 `SAME_SONG_WRONG_SECTION`，模拟 cursor/段落索引错误。

### 重复副歌

单独标记 `AMBIGUOUS_REPEATED_SECTION`，它是多解，不是 strict no-match。

### 纯器乐区配真实歌词

模拟歌词正确但 audio range 错误，是 production 常见 no-match。

### 行序/句序打乱

模拟歌词版本或预处理排序错误。

### 随机文本

只作机制对照，不作为主要生产结论。

## 6. Paired control

No-match 与同 audio、同 unit 数、同 slots、同 workflow 的合法文本配对。除文本内容外其他条件相同。

## 7. No-match 评价

不计算 donor MAE。报告：

- 首尾吸附、时间覆盖和均匀铺开；
- 零时长、回归、重叠；
- official repair ratio、LIS 保留率、最长 repair run；
- posterior 熵、多峰和峰间距离；
- request/slot-mask stability；
- vocal/ASR/音素兼容；
- strict serial cursor 消费和恢复。
