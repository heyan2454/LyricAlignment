# Annotation Schema

**Status:** planned; must be completed from real M4Singer and Opencpop files before training.

## Target record

Each Mandarin lyric character must be traceable to its source annotation:

```text
dataset_id
item_id
song_id
character_index
raw_character
normalized_character
start_sec
end_sec
source_phoneme_indices
source_syllable_or_note_indices
mapping_status
mapping_notes
schema_version
```

## Required invariants

- `start_sec < end_sec` for sung characters;
- character intervals are monotonic within an item;
- special silence/breath tokens are not silently converted to lyric characters;
- melisma/slur mappings preserve all source indices;
- any ambiguous mapping is marked `review_required` rather than guessed.

Dataset-specific field mappings remain to be filled after real-file audit.
