from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from lyricalign.curation.quality import assign_quality_tier


def test_quality_tier_is_exclusive_and_model_independent() -> None:
    assert assign_quality_tier({"status": "accepted", "mapping_status": "accepted_rule_based", "audio": {"audio_status": "ok"}}) == ("A_high_confidence", [])
    assert assign_quality_tier({"status": "review_required", "mapping_status": "review_text_phoneme_mismatch", "audio": {"audio_status": "ok"}})[0] == "B_review_or_robustness"
    assert assign_quality_tier({"status": "accepted", "audio": {"audio_status": "decode_failure"}})[0] == "C_invalid"
