from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from lyricalign.datasets.split import freeze_m4singer_split, leakage_audit


def test_song_split_is_deterministic_and_never_splits_a_song() -> None:
    rows = [
        {"item_id": "a#song#0", "song_id": "song", "lyrics_normalized": "你好"},
        {"item_id": "a#song#1", "song_id": "song", "lyrics_normalized": "世界"},
        {"item_id": "a#other#0", "song_id": "other", "lyrics_normalized": "再见"},
    ]
    frozen = freeze_m4singer_split(rows, "fixed-seed")
    assert frozen[0]["split"] == frozen[1]["split"]
    assert leakage_audit(frozen)["passed"]


def test_leakage_audit_detects_song_cross_split() -> None:
    rows = [
        {"item_id": "one", "song_id": "same", "lyrics_normalized": "甲", "split": "train"},
        {"item_id": "two", "song_id": "same", "lyrics_normalized": "乙", "split": "validation"},
    ]
    assert leakage_audit(rows)["song_cross_split"] == ["same"]


def test_exact_lyrics_components_stay_on_one_side() -> None:
    rows = [{"item_id": "one", "song_id": "a", "lyrics_normalized": "重复"}, {"item_id": "two", "song_id": "b", "lyrics_normalized": "重复"}]
    frozen = freeze_m4singer_split(rows, "fixed-seed")
    assert frozen[0]["split"] == frozen[1]["split"]
    assert leakage_audit(frozen)["exact_lyrics_cross_split_hashes"] == []
