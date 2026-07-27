from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_script(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_limited_cache_selection_keeps_validation_items() -> None:
    cache = load_script("cache_gpu_decoder_features_test", "scripts/demo/cache_gpu_decoder_features.py")
    rows = [
        {"item_id": f"train-{index:03d}", "split": "train"}
        for index in range(100)
    ] + [
        {"item_id": f"validation-{index:03d}", "split": "validation"}
        for index in range(10)
    ]
    selected, audit = cache.select_records(
        rows,
        requested_splits=["train", "validation"],
        max_items=16,
        min_items_per_split=4,
    )
    counts = audit["selected_split_counts"]
    assert len(selected) == 16
    assert counts["train"] == 12
    assert counts["validation"] == 4
    assert {row["split"] for row in selected} == {"train", "validation"}


def test_song_holdout_is_disjoint_and_deterministic() -> None:
    train = load_script("train_gpu_decoder_test", "scripts/demo/train_gpu_decoder.py")
    items = [
        {"item_id": f"{song}-{index}", "song_id": song, "split": "train"}
        for song in ("s1", "s2", "s3", "s4")
        for index in range(3)
    ]
    first_train, first_validation, first_songs = train.derive_song_holdout(
        items,
        seed=123,
        percent=25.0,
    )
    second_train, second_validation, second_songs = train.derive_song_holdout(
        items,
        seed=123,
        percent=25.0,
    )
    assert first_songs == second_songs
    assert [row["item_id"] for row in first_validation] == [row["item_id"] for row in second_validation]
    assert {row["song_id"] for row in first_train}.isdisjoint(
        {row["song_id"] for row in first_validation}
    )
    assert first_train and first_validation
