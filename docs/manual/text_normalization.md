# Text Normalization

**Status:** planned; rules must be frozen before split generation and model evaluation.

## Required properties

- preserve raw lyrics unchanged;
- produce normalized lyrics as a new field;
- record a reversible raw-to-normalized character map where possible;
- handle Unicode normalization, full/half width, punctuation, spaces, digits, Latin text, brackets and non-lexical vocalizations explicitly;
- never change official test text based on model errors.

Concrete rules and version identifiers remain to be determined from M4Singer, Opencpop and MIR-1K examples.
