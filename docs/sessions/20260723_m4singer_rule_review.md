# M4Singer rule review sheet

This sheet records executable rules only. It is intended for rule-by-rule review, not as a claim about any individual lyric or source file.

## Rule order

1. Normalize text with the existing reversible normalization rule.
2. Ignore `<AP>`, `<SP>`, and `<SIL>` as lyric phonemes; preserve their locations as attributes and boundaries.
3. Build preliminary groups at a new consonant/initial or at a changed vowel/final. Consecutive identical finals remain in the same held-vowel candidate.
4. Where groups are fewer than characters, split repeated identical finals only when the number of splittable repeats exactly equals the deficit.
5. Parse every normalized Chinese character independently with all available Mandarin readings. Do not let phrase-level disambiguation suppress a reading.
6. Convert every complete reading to one or more M4Singer token candidates, then find all monotonic full-sequence allocations.
7. Accept only exactly one full allocation. More than one allocation is ambiguous; no allocation is a no-match. Neither case is repaired by a ratio or guess.
8. A structurally exact mapping with slur markers only, no group-count defect, and valid timing is accepted as `accepted_rule_validated_held_vowel`.
9. A mapping must still have finite, non-negative, monotonic character intervals within audio. Accepted records are described as `rule_validated`, not high-confidence.

## Pinyin to M4Singer token conversion

The normal rule is `initial + final`. Orthographic `y` and `w` are zero-initial spellings and are converted before this split.

| Reading | M4Singer tokens |
| --- | --- |
| `yi` | `i` |
| `ya`, `yao`, `ye`, `you`, `yan`, `yin`, `yang`, `ying`, `yong` | `ia`, `iao`, `ie`, `iou`, `ian`, `in`, `iang`, `ing`, `iong` |
| `yu`, `yue`, `yuan`, `yun` | `v`, `ve`, `van`, `vn` |
| `wu`, `wo`, `wai`, `wei`, `wan`, `wen`, `wang` | `u`, `uo`, `uai`, `uei`, `uan`, `uen`, `uang` |
| ordinary `ui`, `iu`, `un`, `ue` finals | `uei`, `iou`, `uen`, `ve` |
| `j/q/x + u`, `j/q/x + un`, `j/q/x + uan` | `j/q/x + v`, `j/q/x + vn`, `j/q/x + van` |
| `wang` | `uang` (proposed corpus rule; see review evidence below) |

### `wang` / `van` review evidence

The current corpus scan found 781 `望`/`忘` characters with a `wang` reading.
Of these, 752 have a unique full mapping and **all 752** use an `uang` run:
545 use one `uang`, 172 use two, 32 use three, and 3 use four held `uang`
tokens (997 `uang` tokens in total).  No uniquely mapped occurrence uses `van`.
The remaining 29 cases are not unique mappings (21 ambiguous and 8 no-match),
including `Alto-1#空空#0019`.  This is strong evidence that `van` should not
remain a corpus conversion alternative.  The current parser still retains it
as a temporary compatibility candidate pending manual confirmation.  If the
review confirms a `wang -> van` source error, remove that candidate and correct
the individual record through an external, hash-anchored annotation overlay;
do not relax the global conversion rule.

## Explicit non-rules

- Do not make a repeated `i**`, `u**`, `an`, `a`, `ou`, or another final into a new character unless the exact-repeated-final rule or unique pinyin allocation proves it.
- Do not accept `multiple_or_complex_slur_with_missing_syllable_groups` with a simple heuristic.
- Do not use note pitch/duration to invent missing lyric phonemes. Note metadata is diagnostic only for this mapping decision.
- Do not require the final character to end at the WAV end.

## Session update — 2026-07-23

### Scope and starting state

- Repository start commit: `0ca273796b953ab48985c0b42436d151d7648e77`
  (`feat: refine vowel-boundary grouping and MIR-1K vocal OOD`).
- Source dataset (read-only):
  `/home/hyan/Data/datasets/m4singer/raw/extracted/m4singer`.
- This is a rule-validation and review-artifact pass.  It neither rewrites
  `meta.json` nor starts model training, and it is not the historical
  6,051/14,845 data-preparation baseline.  The rule set here supersedes the
  earlier working pinyin-grouping taxonomy for subsequent review.

### Changes made in this pass

| Path | Change | Compatibility / rationale |
| --- | --- | --- |
| `src/lyricalign/datasets/m4singer.py` | Added independent-character, heteronym-preserving pinyin parsing and unique monotonic phoneme allocation; converted M4Singer zero-initial spellings; retained held repeated-finals as candidates. | A record is accepted only on one complete allocation; ambiguity remains review. |
| `src/lyricalign/datasets/audit.py` | Zero-initial groups and `<AP>/<SP>/<SIL>` are now auxiliary attributes, not primary failures.  Pinyin no-match/ambiguity is `mandarin_syllable_parse_failure`. | Corrects the prior misleading `zero_initial_or_special_syllable_case` label. |
| `tests/test_m4singer_preparation.py` | Added regressions for zero-initial parsing, `q+v`, repeated-final ambiguity, special-token handling, and the corrected primary reason. | Covers behavior rather than a particular source row. |
| `scripts/datasets/render_b_tier_review.py` | Review rendering uses a shared time scale for phoneme and note timelines, with first non-special phoneme aligned to the first pitched note. | A visualization diagnostic only; it does not alter mappings. |
| `scripts/datasets/audit_note_phoneme_boundaries.py` | Added an experimental nearest-boundary offset diagnostic and box plot. | Not used to create or repair labels. |
| `pyproject.toml` | Declared `pypinyin>=0.55,<1`. | Required for heteronym-aware Mandarin parsing. |

### Incremental decision log

This section is deliberately chronological.  It distinguishes a tested rule
change from a hypothesis, so later review can reconstruct why the present
implementation differs from the initial grouping rule.

| Stage | Triggering observation | Rule/code change | Observed result and retained limitation |
| --- | --- | --- | --- |
| 1. Vowel-boundary grouping | The former “initial + all following vowels until next initial” grouping incorrectly absorbed a changed zero-initial vowel into the preceding character. | Begin a new group at a consonant/initial **or a changed final**; keep only immediately repeated identical finals in the same candidate. | Ordinary zero-initial syllables are representable.  Repeated finals alone still cannot tell hold from a new same-vowel character. |
| 2. Exact repeated-final split | Some character deficits can be resolved by exposing repeated identical vowels one-for-one. | Permit the split only when the number of extra repeated finals exactly equals the group deficit. | No guessed ratio is used.  Cases such as repeated `a`, `an`, `i`, `u`, or `ou` with more than one valid allocation remain review. |
| 3. Timeline review | The original plots placed phoneme and note rows on unrelated effective time origins/scales, and did not make note events readable. | Render phoneme labels and collapsed note-event labels on one scale; align first non-AP/SP phoneme start with first pitched-note start and preserve blank leading/trailing space. | Visual comparison is now meaningful, but timing is diagnostic only and does not authorize a label repair. |
| 4. Pinyin validation | Structural groups alone cannot distinguish a held vowel from a later character with the same final. | Parse each Chinese character with all pypinyin heteronyms and search monotonic full phoneme allocations.  Accept exactly one allocation. | Exact examples such as `题一啊: t i i a` can pass; `啊啊: a a a` stays ambiguous. |
| 5. Phrase-context and M4Singer conversion fixes | Phrase-level pinyin suppressed useful readings (for example `了 -> le`), and the initial conversion did not match corpus spellings such as `qu -> q v`. | Query characters independently; preserve heteronyms; add M4Singer conversion for `j/q/x + u -> v`, zero-initial y/w spellings, and their applicable finals. | Previously rejected valid sequences such as `走入无边人海里` and the examined `Tenor-6#盛夏#0002` pattern became uniquely parseable. |
| 6. Held-vowel structural fallback | A complete, timed structural mapping with slur evidence but no pinyin allocation should not be treated as an arbitrary guess. | Allow `accepted_rule_validated_held_vowel` only with equal group/character cardinality and a slur marker; leave any deficit/ambiguity in review. | This is a narrow validation rule; complex slur-plus-deficit records are still not accepted. |
| 7. `wang` exception review | A temporary `wang -> van` compatibility alternative was introduced for an observed problematic item. | Scan the corpus before accepting it as a general rule. | 752 unique mappings all used `uang`; zero used `van`.  The exception remains temporary pending manual confirmation, and is slated to become a record-level overlay rather than a global rule if confirmed. |
| 8. Zero-initial / special-token taxonomy review | The old label suggested zero-initial or AP/SP were errors, even though they are normal syntax/attributes. | Reclassify pinyin no-match/ambiguity as `mandarin_syllable_parse_failure`; retain zero-initial and special-token information only in secondary attributes. | The old zero/special and unclassified buckets both became zero in the current audit.  The 36 records are visible as actual parse failures for review. |
| 9. Human review tables | Raw tables separated `uo` from held `uo uo`, inflating distinctions; special-token detail was too large to inspect directly. | Normalize a run of identical observed tokens to its base token for summaries, retain held-length distribution, and add a reading-level character-merged table. | 33,801 raw zero-initial groups reduce to 410 base token/reading/character rows and 163 base token/reading rows; full detail remains available. |
| 10. Non-destructive repair design | Direct edits to source `meta.json` would obscure provenance and make re-audit unsafe. | Specify hash-anchored external overlays for token corrections and explicit repeated-vowel boundary decisions. | Templates exist, but no source correction or overlay application has been performed before human confirmation. |

### Rule-validation audit (rerun after zero-initial primary-reason fix)

Command:

```bash
PYTHONPATH=src python scripts/datasets/audit_m4singer.py \
  --m4singer-root /home/hyan/Data/datasets/m4singer/raw/extracted/m4singer \
  --out-dir /home/hyan/Data/lyricalign/derived/20260722_m4singer_pinyin_validated_v4/audit
```

Result: **20,896 total = 20,298 rule-validated + 598 review**; no failed
records.  Primary review reasons are 487
`multiple_or_complex_slur_with_missing_syllable_groups`, 74
`single_slur_with_one_missing_syllable_group`, 36
`mandarin_syllable_parse_failure`, and 1 `latin_or_digit`.  The obsolete
`zero_initial_or_special_syllable_case` and
`unclassified_mapping_failure` both have count 0.

The source audit and summary are:

- `/home/hyan/Data/lyricalign/derived/20260722_m4singer_pinyin_validated_v4/audit/m4singer_audit.jsonl`
- `/home/hyan/Data/lyricalign/derived/20260722_m4singer_pinyin_validated_v4/audit/m4singer_audit_summary.json`

### Zero-initial and special-token review findings

Zero-initial syllables are normal in this corpus, not a failure class.  The
full scan found 33,801 zero-initial candidate groups.  Consecutive identical
tokens are normalized as held versions of one base syllable in the aggregate
table: for `wo -> uo -> 我`, 6,677 occurrences are represented by 5,521
single-token, 1,079 two-token, 59 three-token, 14 four-token, and 4 longer
held runs.  The consolidated mapping table contains 410 base-token / reading /
character combinations; the further character-merged table contains 163
base-token / reading combinations.

Special tokens occur 55,197 times and are only `<AP>`, `<SP>`, or `<SIL>`
boundaries.  All 34 records formerly categorized
`zero_initial_or_special_syllable_case` do happen to contain a special token
(19 have both AP and SP, 13 AP only, 2 SP only), but this was correlation, not
the old classifier's condition: it had selected the class solely upon seeing a
zero-initial group.  Those records now correctly retain special-token and
zero-initial attributes and are classified by their pinyin parse result.

Artifacts:

- `/home/hyan/Data/lyricalign/derived/20260722_m4singer_pinyin_validated_v4/manual_review/zero_initial_mapping_summary.csv`
- `/home/hyan/Data/lyricalign/derived/20260722_m4singer_pinyin_validated_v4/manual_review/zero_initial_pinyin_reading_merged.csv`
- `/home/hyan/Data/lyricalign/derived/20260722_m4singer_pinyin_validated_v4/manual_review/zero_initial_review.csv`
- `/home/hyan/Data/lyricalign/derived/20260722_m4singer_pinyin_validated_v4/manual_review/special_token_context_summary.csv`
- `/home/hyan/Data/lyricalign/derived/20260722_m4singer_pinyin_validated_v4/manual_review/special_token_review_examples.csv`

### Manual source-correction policy (not yet applied)

Source metadata remains immutable.  A correction must be a hash-anchored,
external overlay with `item_id`, `source_row_sha256`, operation, target token
index, expected value, replacement value, reason, decision, and reviewer note.
The editable CSV and JSONL templates are in:

- `/home/hyan/Data/lyricalign/derived/20260722_m4singer_pinyin_validated_v4/manual_review/annotation_correction_overlay_template.csv`
- `/home/hyan/Data/lyricalign/derived/20260722_m4singer_pinyin_validated_v4/manual_review/annotation_correction_overlay_template.jsonl`

For ambiguous slur/repeated-vowel cases, the intended future overlay is a
boundary decision (`hold_with_previous`, `start_new_character`, or
`unresolved`) anchored after a phoneme index, rather than an edit to source
`is_slur` or source phoneme arrays.  No overlay loader or correction has been
activated yet; this is deliberately pending human review.

### Verification and pending decisions

```bash
PYTHONPATH=src pytest -q tests/test_m4singer_preparation.py
# 11 passed
```

Pending manual confirmation:

1. Confirm whether `Alto-1#空空#0019` has the proposed `wang -> van` source
   annotation error.  Evidence above supports removal of the parser's temporary
   global `wang -> van` candidate and a one-record overlay, but neither action
   has been performed yet.
2. Review the generated slur visualizations and decide explicit boundary
   actions for ambiguous repeated vowels.  Complex slur cases remain review;
   no heuristic has been used to force them into accepted data.
3. Refresh downstream prepared manifests/splits/long-audio artifacts only
   after the human-approved overlays and the final rule set are fixed.

### Current canonical inventory (2026-07-23)

The operational canonical M4Singer mapping manifest for this rule pass is
`/home/hyan/Data/lyricalign/derived/20260722_m4singer_pinyin_validated_v4/prepare/m4singer_manifest.jsonl`.
It has 20,896 JSONL rows and SHA-256
`22828f809e60cfaeb44f0fec973d7ce5b026fd024d0740b9120725f012d6053a`.
Its input `meta.json` SHA-256 is
`50030a56d4529bb460f3088534655e27b75b4e538fcbe4f2ea2a4b968935d433`.
The paired character annotation file has 193,666 rows and SHA-256
`ba28f0e0c5f5d6c850b47632808ccc60052f3be397f3316ee95bc95678ca613d`.

| Status | Count | Meaning |
| --- | ---: | --- |
| accepted | 20,298 | `rule_validated` character-to-phoneme candidate mapping |
| review_required | 598 | no automatic acceptance under the current rules |
| rejected / failed | 0 | no schema, timing, or audio hard rejection in the full audit |
| total | 20,896 | conserved source-record total |

The 598 review records are: 487 complex/multiple slur cases, 74
single-slur one-group deficits, 36 Mandarin pinyin parse failures, and 1
Latin/digit item.  The mapping-status split is 531 ambiguous allocations and
67 no-match allocations.  The current audit is the source for the primary
reason breakdown; the prepare manifest is the canonical mapping artifact.

### MIR-1K channel and processing state

The user manually confirmed on 2026-07-22 that the **second interleaved PCM
channel (zero-based index 1; “channel 1” in the review)** in MIR-1K
`UndividedWavfile` is vocal.  The implementation selects that channel by
striding interleaved PCM samples; it does not use `ffmpeg -ac 1` or average the
two channels.  It writes a temporary mono WAV and atomically replaces the
destination, recording source/output SHA-256 and the channel index.

Processed OOD test-only subset:

| Item | Value |
| --- | --- |
| output root | `/home/hyan/Data/lyricalign/derived/20260722_mir1k_vocal_channel1_ood` |
| vocal-only songs | 17 |
| character annotations | 2,035 |
| split / use | `test` / `ood_test_only` |
| extraction manifest SHA-256 | `5ed24d2a616af5764ab036876ccba919595728a31586d3b593a39bdb4fb2a9da` |
| manifest SHA-256 | `bd8109d608247b78407c1d63e9f648b83f697a00c5c0b05b3fe93c87b42c884f` |
| character JSONL SHA-256 | `78d7054ada0a3fb5ec3cd916174d094d78ab5d96f67d0112408de30dc24469c9` |

The run summary is
`/home/hyan/Data/lyricalign/derived/20260722_mir1k_vocal_channel1_ood/run_summary.json`;
the channel-level source/output evidence is in
`channel_extraction_manifest.json` beside it.  This is an explicit vocal-only
derivative, not a claim that the original stereo mixture itself is vocal-only.

### Historical-count validity

| Version / count | Validity now | Reason |
| --- | --- | --- |
| 6,051 accepted / 14,845 review | historical v2 result only; not canonical | Uses the earlier fixed gate and predates the present pinyin/held-vowel validation rules.  It must not be mixed with current manifests. |
| 66-item result | invalid / superseded | Previously identified historical counting error. |
| Interim 18,057 / 2,839 pinyin run | superseded intermediate | Produced before independent-character heteronym handling and M4Singer conversion fixes such as `q+v`; retain only as trace history. |
| 20,298 accepted / 598 review | current operational canonical | Matches the current manifest, current audit, and conserved total.  It remains subject to future explicitly approved source overlays, not silent mutation. |

### Current interpretation

- `accepted` means the current deterministic rules produced a complete, traceable mapping that passed the current audit conditions.
- It does not mean every mapping has been manually checked.
- `review_required` preserves ambiguity or no-match rather than forcing acceptance.
- Future source overlays or rule changes must create a new explicit version, compare against this manifest, and record the superseding relationship.

### Archive boundary

This archive records the current code/document snapshot and the supplied external-run identities.  Large external manifests and audio are not copied into the repository.  The archive does not claim to have rerun the 20,896-item server audit locally.

### Incremental overlay and slur-time pass

The parser now maps ordinary `wang` only to `uang`.  The confirmed exceptional
source row `Alto-1#空空#0019` is corrected non-destructively by the approved,
hash-anchored token overlay in
`configs/curation/m4singer_annotation_overlays_v1.jsonl`: source token index
11 is required to be `van` and is replaced by `uang` only when the source-row
SHA-256 is exactly `92c7c8a86912cf9f939a5640bcec9b3359d2da7fed0ef0e425d86cc0a5b90f1a`.

`m4singer_slur_time_allocation_v1` is strictly incremental.  It is evaluated
only after the legacy pinyin/held-vowel rules leave a slur record in review,
and it only partitions the legacy phoneme groups.  It requires complete,
independent character-time anchors and agreement with both phoneme and
collapsed MIDI boundaries within 30 ms; it does not infer lyrics from MIDI.
The initial full pass has no independent character-time-anchor JSONL, so it
promotes zero slur records.  Its purpose is to establish the 20,299 accepted /
597 review overlay baseline and retain the old result path for comparison.
