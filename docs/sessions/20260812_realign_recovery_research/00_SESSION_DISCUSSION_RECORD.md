# 会话讨论记录：从 real-GT / detector 复盘到 Realign Recovery 主线

- 日期：2026-08-12
- 目的：忠实记录本次会话的讨论过程、用户的意见与疑问、结论修正和最终实验方向。
- 说明：这里不仅记录最终结论，也保留讨论中被纠正、降级或延期的判断，避免后续 Agent 只看到最后一句而丢失原因。

---

## 1. 用户要求 review 当前工作目录与实验记录

用户：

> review当前工作目录和实验记录，陈述实验结果。

审核覆盖了当时提供的工作目录包与 evidence 包。讨论首先确认：这一轮已经把一部分旧实验从 synthetic-uniform timeline 中隔离出来，Detector V2 的 real-GT label lineage 比旧 correctness 口径可信；同时发现 recovery 和 semantic/subwindow 探索里仍残留 synthetic timing 使用。

主要复盘结论：

- `light_merge` 的旧后处理会把夹在 ACCEPT 中的 REJECT 岛重新翻回 ACCEPT，违反 detector 的保护优先语义；
- 修复后 A retrospective evaluation 中，Raw protected recall 从约 0.904 提高到约 0.957，Official 从约 0.914 提高到约 0.963；
- 修复带来更保守的行为，Raw safe accept 约 0.832，Official 约 0.730；
- 旧 Phase 4.3 的约 14–16% oracle recovery 使用 synthetic-uniform timing，不可继续称为 real-GT recovery 上界；
- semantic/subwindow 的部分 `hit100` 实际是 start-only 1 s，且 correctness reference 仍来自 synthetic timeline；
- 但 window-gate 中的 `hit100` 后续复核确认是正式 real-GT reaggregate 的 start+end 双边界 100 ms，并非 start-only 1 s。

---

## 2. 用户希望先让 OpenCode 做快速、低风险更新

用户：

> 现在可以要求opencode进行简单快速的更新，包括文档内容和部分简单计算。有什么部分是需要的？我将交给codex审核后让opencode进行更新。

讨论决定先做：

- 文档结论纠正；
- Detector bug-fixed retrospective summary；
- synthetic-GT usage audit；
- metric schema audit；
- per-song failure concentration；
- window gate threshold sweep；
- semantic boundary clamp 与 provenance warning；
- archive integrity；
- 不启动新的大规模 GPU 实验。

用户随后要求形成可下载 Markdown，并明确最终更新资料打包到 `/home/hyan`。

---

## 3. quick correction 第一轮审核与补修

第一轮 correction 交付后，审核发现：

- metric schema audit 把 window-gate 的正式 100 ms `hit100` 错归为 start-only 1 s；
- `eval_rule_subwindow.py` / `eval_subwindow.py` 的 synthetic correctness 使用未被 audit 正确识别；
- patch 引用了 `gt_provenance.py` 和测试，但交接包里没有可恢复文件；
- `song_failure_concentration.csv` 不是实际 per-song 表。

用户要求再次给出 MD，交给 Codex/OpenCode 补修。

---

## 4. quick correction 第二轮审核

第二轮 correction 已基本修复上述核心问题：

- window-gate `hit100` 正确归类为 start+end <=100 ms；
- subwindow legacy `hit100` 正确归为 `start_hit_1s`；
- synthetic-GT audit 已覆盖关键 subwindow/recovery 脚本；
- `gt_provenance.py` / `test_gt_provenance.py` 进入可恢复 patch；
- CPU 全量测试 1056/1056 通过；
- per-song concentration 已真正按 song/family/target 产出。

仍有三个小问题：

1. `start_mae_sec` 在 audit 中仍被误归成 `start_hit_1s`；它应是连续误差 metric；
2. top-k“歌曲集中度”展示实际上按 song×family 排名，应另做 song 聚合；
3. `CODEX_REVIEW.md` 仍是第一轮 review，缺 followup final acceptance。

用户决定：

> 这些问题可以纪录，下一轮再修复。

因此这三项成为本 session 的延期事项，不阻塞 Realign 主实验。

---

## 5. 用户要求用更直白语言重新总结这一批实验

讨论将当前现象归纳为：

- 系统不是“所有地方都对不准”，而是多数正常情况可工作，少数窗口突然发生严重整体错位；
- 严重错误高度集中于少量歌曲/窗口；
- 重复元音、衬词、重复歌词、长窗口和错误 text/audio pairing 是当前已经观察到的重要困难条件；
- Raw 严重失败通常伴随 entropy 高、margin 低、timestamp pile-up、倒序和异常跳跃，因此错误并非完全不可见；
- 修复 `light_merge` 后，Raw detector 已表现出约 95–96% 的严重错误保护能力，同时保持更好的 safe accept 平衡；
- 短窗/重新配对明显缓解某些 collapse，但旧 semantic accuracy 仍受 synthetic timing 污染，暂时只能作为机制证据；
- recovery 旧 14–16% 不能解释成真实能力上限；真正的 real-GT/no-GT recovery 能力仍未知。

---

## 6. 用户明确下一阶段更倾向 Raw，并把研究重点转向修复

用户：

> 考虑到可能改变decoder，我更倾向于使用raw，而且raw的平衡做得也更好，safe ac更高。接下来我觉得应该主要研究如何修复错误。围绕realign设计实验。当中比较重要的实验有：如果对困难段给出准确的范围和词曲，能否正确对齐。realign能起到怎样的修复作用等。你觉得都有什么需要的实验？

用户的核心决定：

- Realign 主线优先使用 Raw；
- 原因之一是未来 decoder 可能改变；
- 当前 Raw detector 在错误保护与 safe accept 间的平衡更适合作为闭环控制信号；
- 下一阶段重点从“还能不能找到更多 detector 信号”转向“发现错误后能不能真正修回来”。

讨论提出第一关键问题：

> 如果给困难段准确的音频范围和准确歌词，不给字符时间戳，模型是否能自行重新对齐正确？

这被确定为必须优先进行的 oracle repairability 上限实验。

---

## 7. 用户强调生产环境无 GT，并允许挂机长实验

用户：

> 你是对的，正常生产情况下没有gt，所以在oracle以外，还要研究真实情况下：realign如何被提供歌词和曲段；detector能否正确分辨realign修复质量。另外我会挂机，所以可以安排一些长实验或者更多实验。

由此把实验主线扩展为四层：

1. Oracle：模型本身能不能修；
2. No-GT proposal：真实情况下怎样自动给 realign 音频范围和歌词范围；
3. Quality gate：Raw detector 能否判断新结果是真改善、无变化还是变坏；
4. Closed loop：安全写回后能否阻止错误继续传播。

用户允许挂机，因此计划可以扩大 candidate bank 和真实串行轨迹数量；但仍要求避免笛卡尔积，并继承既有 GPU 预算/缓存/恢复原则。

---

## 8. 用户进一步提出更真实的模拟错误方式

用户：

> 除了oracle和容错以外，可以做模拟无gt环境得到结果，然后detect、realign，再和gt对比计算。当然也可以模仿之前的扰动实验，通过扰动前面串行地影响后面，构造比单纯加减字数更自然的模拟错误。

这是下一轮设计中的重要转折。

用户不希望主要依赖：

> 当前窗口直接 +N / -N 个字，然后立刻评价 detector/recovery。

更希望：

> 在更前面的状态只扰动一次，让 cursor / window / text request 自然产生后续错误；后续窗口不再人工修改，然后观察 detector 和 realign 能否把系统恢复。

讨论中确定应重点构造：

- natural error propagation；
- 前窗真实错误强制 commit；
- lyric cursor ahead/behind；
- audio/time boundary/cursor 偏移；
- repeated occurrence / repeated chorus 跳转；
- silence-boundary 错误；
- 只在错误源头注入一次，后续按照正常 route 自然运行。

主要 recovery denominator 应只统计真正造成了后续错误传播的有效 episode；注入但无实际影响的 case 单独报告，不混入 recovery success denominator。

---

## 9. 用户要求验证对 baseline 的理解

用户：

> 这一块，模型的baseline，或者说基础行为你觉得是什么，列出来让我验证你的理解。

讨论中的 baseline 理解包括：

- 模型在给定 audio + text request 内做 forced alignment，不负责从整首歌词自动重新搜索当前 occurrence；
- 正常对应关系明确时多数窗口可以工作；主要问题是少量 catastrophic misalignment；
- 长窗仍是正常生产主线，不能因为困难 case 就把全部窗口缩短；
- 串行 state 会使前窗错误自然改变后窗 request；
- 正常产品假设是整首歌词文本正确，主要困难是“当前音频对应整首歌词中的哪一段”；
- 同一个错误 request 原样 rerun 不是有意义的 recovery，realign 必须改变 request；
- Raw 错误通常暴露异常，因此 detector 可在无 GT 条件下工作；
- recovery 价值不仅是修当前局部，更是把后续串行轨道拉回正常。

---

## 10. 用户确认：除 realign 与 Raw detector 外，全部继承此前 baseline

用户：

> 是的，除了我们要实验的realign部分和已经有成果的raw的detector，你应该沿用之前的决定好的baseline。

这是本 session 的强制冻结决定。

含义：

- 不重新打开 model / slot-vs-nonslot / transition / planner / silence / decoder 大消融；
- Raw 是本轮主输出；
- Raw detector 使用修复 `light_merge` 后的当前版本；
- realign 输入构造、realign 执行、realign 质量判断、writeback/retry 是本轮允许变化的核心变量；
- 任何 Agent 如果重新做旧 baseline 大矩阵，属于偏离用户指令。

---

## 11. 用户要求生成相对于当前实验目录的 patch 包

用户：

> 给我一个相对于当前实验目录的patch包，包括会话记录与实验结论、下一轮实验设计。会话记录需要记录完整会话过程，我的意见和疑问需要忠实记录。实验需要记录好实验原因、设计、目的、预期结果与结果能说明的结论。实验设计使用工作目录中一个新的session文件夹。告诉opencode在实验完成后如果没有主动打断应该进入自由探索环节，自由探索环节要求列好todo，最后一条todo应该是重新展开下一轮自由探索的todo与延续todo以保证一直自由探索。

据此本 patch：

- 新建独立 session 文件夹；
- 不继续追加旧 session 编号；
- 记录本会话过程、用户意见、当前结论和下一轮完整 realign 计划；
- 写明正式实验结束后若用户没有主动打断，OpenCode 必须进入自由探索；
- 自由探索必须维护 TODO；
- TODO 最后一项必须重新展开下一轮 TODO 并继承未完成项，避免“TODO 做完即停”。

---

# 用户最终方向摘要（不可被后续 Agent 改写）

1. **Raw 主线**：考虑 decoder 未来可改变，而且当前 Raw detector 的平衡更好、safe accept 更高。
2. **Detector 不再是主研究对象**：当前成果作为模块复用；重点是 recovery/realign。
3. **Oracle 必须做，但不能代表生产结果**：要测 exact audio/text 输入下模型本身是否可修。
4. **No-GT 是主线**：生产决策不能访问 GT；GT 只在实验后评分。
5. **要研究 realign 输入从哪里来**：尤其歌词范围和音频范围。
6. **要研究 detector 能否判断 repair quality**：避免把更坏的新结果写回。
7. **模拟错误要更自然**：优先前面单点扰动，然后让后续串行状态自然受影响，不以当前窗口直接 ±文字为主。
8. **其他 baseline 冻结**：除 realign 与 Raw detector 外沿用此前决定。
9. **允许挂机长实验**：可扩大真实轨迹与 candidate bank；仍需缓存、resume、避免笛卡尔积。
10. **正式实验后持续自由探索**：没有用户打断就继续，TODO 的最后一项必须自动展开下一轮 TODO 与 carry-over。
