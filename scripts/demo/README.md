# Demo scripts

- `run_yessoda_serial_demo.sh`: 夜苏打完整 demo 入口。
- `align_qwen_fa_serial_demo.py`: R0/R1/R2 full 与严格串行核心分窗推理。
- `run_yessoda_tail_windowed.sh`: 03:05 / 03:12 后分离人声尾段实验入口。
- `align_qwen_fa_tail_windowed.py`: 尾段 R0/R1/R2 严格串行核心分窗推理。
- `render_qwen_fa_karaoke.py`: 完整 demo 的 ASS/KTV 视频渲染。
- `render_qwen_fa_tail_windowed.py`: 尾段单模型与三模型比较视频渲染。

## Windowed policy

`windowed` 当前使用 `hard_core_overlap_transcript_v3`：

- 60 秒核心区完全相邻；
- 左右各 10 秒为音频上下文；
- 下一窗口的歌词起点由上一窗口在“下一窗口音频起点”处的对齐计算；
- 若该音频切点落在某个字内部，下一窗口排除这个被切开的字，从后一个完整字开始；
- 左侧 10 秒中的已提交歌词会重新输入给 forced aligner 作为定位上下文，但不会再次提交；
- 字符按起点归属核心，跨核心右边界字符完整归前窗；
- 已提交歌词不可被后窗覆盖；
- 不再执行跨窗候选竞争或大范围累计单调修复。

输出的 `window_trace` 同时记录：

- `next_window_input_character_start`：下一窗口实际输入歌词起点；
- `next_uncommitted_character_start`：尚未由任何核心提交的第一个字符；
- `input_boundary_cut_character`：被下一窗口音频起点切开、因此从下一输入排除的字符；
- `core_boundary_character`：跨核心右边界但完整归当前核心的字符。

Demo 不含正式 metric，不能用于选择检查点。输出仍保存在输入歌曲目录下，不进入 tracked project results。
