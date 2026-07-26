# 2026-07-26 Demo exploration and reusable batch entry archive

## 1. Scope

This session focused on the real-song demo path rather than formal M4Singer or
MIR-1K evaluation. It covered:

1. diagnosing invalid Spleeter outputs;
2. comparing full-song and cropped serial-window alignment behavior;
3. identifying a cross-window merge failure rather than a pure model failure;
4. replacing heuristic candidate competition with hard 60-second core ownership;
5. correcting an initial strict-core implementation that omitted overlap lyrics;
6. adding a reusable same-stem batch alignment and rendering entry.

Demo observations remain diagnostic-only. They do not select checkpoints and do
not replace the frozen test/OOD metrics.

---

## 2. Initial Spleeter failure

### Observation

The two Spleeter outputs sounded nearly identical. The first Spleeter launch had
attempted to download model weights but network access failed; a later launch no
longer displayed weight-download information and still produced files.

### Risk

The old demo path only checked that `vocals.wav` existed. It did not verify that:

- the official `2stems` model cache was complete;
- vocals differed from the original mix;
- vocals and accompaniment differed from each other;
- both stems were non-silent;
- the stems approximately reconstructed the mix.

A bad output could therefore be cached and reused through the mix identity even
though it was not a meaningful separation.

### Repair

The demo path now:

- uses an explicit `SPLEETER_MODEL_ROOT`;
- requires the model completion `.probe` marker;
- provides a resumable SHA-256-verified model download script;
- preserves both `vocals.wav` and `accompaniment.wav`;
- computes `separation_quality.json`;
- rejects silent or near-copy stems;
- includes the separation policy and model root in the cache identity.

### Result strength

The repair proves that later vocal-mode runs use a validated two-stem output.
It does not prove that Spleeter is the optimal separator or that leakage is low
enough for formal evaluation.

---

## 3. Full-song failure versus 03:05 cropped success

### Observation

In the earlier full-song serial-window R2 vocal result, the line
`即便明日将得过且过毫无期许` failed and several following lines collapsed.
Alignment recovered only several lines later. When the song was cropped from
03:05 and the corresponding lyrics were supplied, the same passage aligned
substantially better.

### Controlled comparison

Two R2 windowed vocal JSON outputs were compared:

- full song: 270.071 s, 44 lines, 435 characters, 5 windows;
- 03:05 tail: 85.071 s, 10 lines, 113 characters, 2 windows.

The old full result reported:

```text
cross_window_repaired_character_count = 80 / 435
cross_window_repaired_character_rate  = 18.39%
```

The 03:05 result reported:

```text
cross_window_repaired_character_count = 0 / 113
cross_window_repaired_character_rate  = 0%
```

### Key proof

For most characters from `即便明日...` through `如此选择`, the full-song
candidate times before cross-window repair were already close to the cropped
result after adding back the 185-second offset. The large visible failure was
created later:

1. a later window supplied a wrong candidate at approximately 225 s for the
   beginning of the passage;
2. selection operated independently per character;
3. the global monotonic repair forced subsequent otherwise-correct 193–223 s
   characters forward to 225 s;
4. alignment appeared to recover when raw candidate times naturally exceeded
   the incorrect 225 s anchor.

This supports the conclusion that the dominant failure was in window candidate
selection and cumulative repair, not simply that R2 could not hear the phrase.

### Alternative explanations retained

- local low-confidence character boundaries still existed in the cropped run;
- corrected Spleeter vocals also changed the acoustic input;
- the demo has no manual character-level ground truth;
- subjective video quality cannot quantify generalization.

---

## 4. Why the old window mechanism failed

The older implementation behaved as follows:

- each overlapping window independently aligned a broad lyric candidate range;
- the nominal commit cursor only guided the next lyric estimate;
- committed rows were not immutable;
- multiple window candidates remained eligible;
- a per-character rank preferred core placement and margin but did not enforce
  whole-line or whole-window consistency;
- a final global monotonic repair could move many later rows.

This was weaker than the intended rule:

```text
trusted core = final owner
extended region = context only
```

The broad candidate range could also include lyrics that did not occur inside a
window, especially around repeated sections. A bad boundary candidate could then
become a global time anchor.

---

## 5. Agreed strict serial design

### Time layout

Core regions are adjacent and non-overlapping:

```text
core 0:   0–60 s
core 1:  60–120 s
core 2: 120–180 s
...
```

Each model input adds 10 seconds of audio context on both sides when available:

```text
window 0 input:   0–70 s
window 1 input:  50–130 s
window 2 input: 110–190 s
```

### Ownership

- character ownership is determined by character start time;
- a character starting inside a core belongs wholly to that core even if its end
  crosses the right boundary;
- adjacent extended regions can never overwrite the owning core;
- committed results are immutable;
- no per-character cross-window winner competition remains;
- only a very small seam correction is permitted; large conflicts hard fail.

### Transcript passed to the next window

The next window must wait for the previous window. Its transcript start is
computed at the next window's **audio input boundary**, not only at the next core
boundary.

For example, window 1 starts acoustically at 50 s:

- if 50 s cuts through a character, that cut character is omitted;
- input starts with the following complete character;
- complete lyrics from 50–60 s are re-input as left-overlap context;
- those rows are already committed by core 0 and cannot be submitted again;
- new commits begin from the first uncommitted character in core 1.

This preserves acoustic/transcript consistency while maintaining hard ownership.

---

## 6. Negative result: strict-core v2

### Incorrect implementation

The first strict-core implementation gave window 1 the 50–130 s audio but began
its transcript only at the first uncommitted character after the 60 s core
boundary. It omitted the complete 50–60 s lyrics even though that audio remained
in the input.

### Server evidence

Window 0 completed with:

```json
{
  "core": [0.0, 60.0],
  "input": [0.0, 70.0],
  "characters": [0, 174],
  "committed": [0, 92],
  "next_window_character_start": 92,
  "boundary_character": {
    "global_character_index": 91,
    "character": "我",
    "start_sec": 59.84,
    "end_sec": 60.16,
    "crosses_core_end": true
  }
}
```

Window 1 then failed:

```text
RuntimeError: first uncommitted character aligned inside the left context:
start=50.000s core_start=60.000s tolerance=0.320s
```

### Interpretation

This was not evidence that 10-second left context was invalid. It proved that
forced alignment cannot be given 50–60 s audio while withholding the lyrics that
occur there. The model attached its first supplied character to the start of the
unmatched audio.

### Consequence

Strict-core v2 was rejected. The implementation was replaced by the current
`hard_core_overlap_transcript_v3` policy.

---

## 7. Current `hard_core_overlap_transcript_v3`

The current implementation distinguishes:

- `next_window_input_character_start`: first complete character supplied to the
  next acoustic window, which may be an already committed overlap character;
- `next_uncommitted_character_start`: first character not yet owned by any core;
- `input_boundary_cut_character`: character cut by the next acoustic input start
  and therefore excluded from that next transcript;
- `core_boundary_character`: character crossing a core end but owned wholly by
  the current core.

The implementation no longer uses:

- proportional whole-song lyric-start estimates as the controlling cursor;
- arbitrary character backtracking;
- independent cross-window candidate winners;
- large cumulative monotonic flattening.

### Current qualitative result

After re-running, the user observed that the new output looked substantially
more correct. This is useful demo evidence but remains confounded by:

- the corrected Spleeter stem;
- forced re-inference and changed request identities;
- the absence of manual GT for the song.

Therefore the archive records this as a qualitative success, not a formal model
or metric claim.

---

## 8. Reusable batch demo implementation

### Default behavior

The new entry is:

```text
scripts/demo/run_qwen_fa_batch.sh
```

It accepts a media file, TXT file, basename, or directory. Files are grouped by
exact stem:

```text
song.mp4 / song.wav / song.txt
```

Default output selection:

```text
R2 + separated vocal alignment + strict windowed inference
```

### Source resolution

- a same-stem video is used as the visual source when present;
- a same-stem audio sidecar is preferred for alignment/separation;
- otherwise audio is extracted from the video;
- every group requires `<stem>.txt` and at least one supported media file;
- incomplete groups are ignored during directory discovery.

### Rendering

For video input:

- the original video is placed above without subtitle overlap;
- the canvas is extended downward with a black subtitle band;
- two outlined ASS karaoke rows are rendered in that band;
- source program audio is used by default even when alignment used vocals.

For audio-only input:

- a pure black video background is generated;
- the same two-row outlined karaoke rendering is used.

`--render-audio aligned` is available for diagnostic mix/vocal audio tracks.

### Optional outputs

The entry supports:

- arbitrary individual `MODEL:AUDIO:MODE` selections;
- R0/R1/R2 three-panel comparisons for one audio/mode;
- four-panel mix/full, mix/windowed, vocal/full, vocal/windowed comparisons for
  one model;
- presets for default, all individuals, model comparison, input comparison and
  the historical full demo matrix.

### Reproducibility and failure recovery

- mix extraction, Spleeter separation, alignment and rendering each have request
  identities;
- unchanged outputs are reused;
- stages can be run separately;
- force flags are scoped by stage;
- batch manifests record source files, resolved plan, outputs and failures;
- selected models are loaded once and reused across all discovered jobs;
- batch mode continues to later jobs by default and returns nonzero if any job
  failed; `--fail-fast` is available.

---

## 9. Verification

Completed in the archive build environment:

- Python compileall for demo modules and scripts;
- shell syntax checks;
- same-stem discovery tests;
- default and composite plan-expansion tests;
- strict-window and separation-quality regressions;
- ASS bottom-band position checks;
- FFmpeg smoke proving a 320×180 video becomes 320×300 with a 120-pixel subtitle
  band rather than overlaid subtitles;
- 25 directly relevant tests passed in the focused suite after the multilingual extension.

Not executed in the archive build environment:

- actual R0/R1/R2 GPU inference;
- Spleeter model execution with server weights;
- a directory-scale real-media batch.

---

## 10. Current conclusions and remaining risks

Supported:

- invalid Spleeter stems can silently invalidate demo conclusions unless quality
  is checked;
- the observed 225 s collapse was substantially amplified by cross-window merge
  and monotonic repair;
- hard core ownership avoids later windows overwriting trusted results;
- left audio overlap requires matching overlap lyrics as context;
- the reusable batch path now implements the agreed default and output modes.

Not yet supported:

- a formal accuracy gain from v3 on a GT long-song benchmark;
- robustness to missing, extra or incorrect lyric lines;
- optimal 60/10/10 window sizes;
- reliable local recovery after a hard seam failure;
- equivalence between same-stem sidecar audio and the video's embedded audio.

Next formal work should build a labeled long-audio evaluation or controlled
MIR-1K/M4Singer concatenation protocol before tuning the window policy further.

---

## 11. Multilingual batch-input extension

### User requirement

The reusable batch entry needed an explicit language option and correct English
and Japanese text handling. The existing CLI already exposed `--language`, but
its lyric parser still treated every non-whitespace Unicode symbol as one
alignment item. That was valid for Mandarin character-level experiments but
incorrect for English and Japanese.

### Problem in the previous implementation

For an English line such as:

```text
Don't stop now.
```

the old parser produced one timestamp target per letter. Qwen's official Forced
Aligner processor instead produces word units. The expected units are:

```text
Don't | stop | now
```

The same mismatch existed for Japanese: the official processor uses Nagisa word
segmentation, while the project would have used individual Unicode symbols.
This caused three reproducibility risks:

1. timestamp slot count could differ from the local lyric-unit count;
2. window cursors would operate on incompatible units;
3. rendered punctuation and spaces could be lost or assigned to the wrong time.

### Implemented design

The lyric document now stores language-aware alignment units while retaining the
historic `characters` field names for compatibility.

- Chinese/Cantonese: CJK characters are individual units; contiguous Latin text
  is one word, so mixed lyrics such as `今晚 sing with me` become
  `今 | 晚 | sing | with | me`.
- English and other space-delimited supported languages: word units; embedded
  CJK remains character-level, matching the official processor behavior.
- Japanese: Nagisa word units. Punctuation is display-only and does not consume
  timestamp slots.

Each unit separates model and display forms:

```text
alignment_unit / character  model-facing clean token
display_prefix               leading punctuation
 display_text                exact visible token span
display_suffix               following punctuation and spaces
unit_type                    cjk_character / word / japanese_word
```

The window transcript is rebuilt with explicit separators between pre-tokenized
units. The processor-returned units are checked for exact equality before model
output is accepted. A mismatch now hard-fails with the language, expected units,
processor units and transcript instead of silently corrupting indexes.

### Cache and output identity

Language and unit mode are included in:

- batch plan;
- lyrics structure identity;
- alignment request hash;
- alignment summary;
- rendered video label.

Changing `--language` therefore invalidates incompatible alignment caches. The
cheap `lyrics_structure.json` is always rewritten so an old Chinese character
structure cannot remain beside a new English/Japanese word-level result.

### Rendering

ASS rendering now uses `display_prefix + display_text + display_suffix` rather
than assuming `character` is a single visible glyph. This preserves output such
as:

```text
Hello, world!
今日は、晴れです。
```

while highlighting each model alignment unit. Default fonts are selected by
language: Japanese uses `Noto Sans CJK JP`, Chinese/Cantonese use
`Noto Sans CJK SC`, and other languages use `Noto Sans` unless overridden.

### Japanese dependency

Japanese support intentionally requires `nagisa`, matching the official
processor. No heuristic character-level fallback is allowed. The project adds:

```bash
pip install -e '.[demo-multilingual]'
```

Korean is not enabled in this CLI revision because the official processor uses a
separate `soynlp` dictionary tokenizer and the required dictionary asset is not
part of this project. Rejecting it is safer than claiming incorrect support.

### Model fairness warning

The base R0 model is multilingual, but R2 was fine-tuned on Chinese singing.
Non-Chinese runs keep the requested default R2 behavior but emit
`r2_multilingual_not_validated`. R0 and R2 should be run together before making
cross-language model claims.

### Verification

The focused suite now covers:

- English word units and visible punctuation;
- Chinese-English mixed unitization;
- Japanese Nagisa-compatible units through a deterministic tokenizer stub;
- language alias canonicalization;
- multilingual ASS display reconstruction;
- existing hard-core overlap transcript behavior and media rendering.

No real English/Japanese GPU song inference or ground-truth metric was available
in the archive environment. The implementation claim is therefore interface and
mapping correctness, not multilingual singing-alignment accuracy.
