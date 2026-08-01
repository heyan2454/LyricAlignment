from __future__ import annotations

from lyricalign.research_v6.decoders import DecoderConfig, decode_rows
from lyricalign.research_v6.detector import LogisticRiskModel, StumpBoostRiskModel, inspect_alignment


def sample_rows():
    return [
        {
            "global_character_index": 0, "character": "你",
            "raw_global_start_sec": 0.0, "raw_global_end_sec": 0.16,
            "official_fixed_global_start_sec": 0.0, "official_fixed_global_end_sec": 0.16,
            "start_sec": 0.0, "end_sec": 0.16,
            "raw_start_topk_classes": [0,1], "raw_start_topk_probabilities": [0.7,0.3],
            "raw_end_topk_classes": [2,1], "raw_end_topk_probabilities": [0.7,0.3],
            "raw_start_margin": .4, "raw_end_margin": .4,
        },
        {
            "global_character_index": 1, "character": "好",
            "raw_global_start_sec": 0.08, "raw_global_end_sec": 0.0,
            "official_fixed_global_start_sec": 0.16, "official_fixed_global_end_sec": 0.24,
            "start_sec": 0.16, "end_sec": 0.24,
            "raw_start_topk_classes": [1,2,3], "raw_start_topk_probabilities": [0.45,0.4,0.15],
            "raw_end_topk_classes": [0,3,4], "raw_end_topk_probabilities": [0.45,0.4,0.15],
            "raw_start_margin": .05, "raw_end_margin": .05,
        },
    ]


def test_decoders_produce_legal_candidates():
    rows = sample_rows()
    joint = decode_rows(rows, DecoderConfig(name="joint_start_end", top_k=3))
    sequence = decode_rows(rows, DecoderConfig(name="topk_sequence", top_k=3, beam_size=16))
    isotonic = decode_rows(rows, DecoderConfig(name="weighted_isotonic"))
    assert all(r["end_sec"] >= r["start_sec"] for r in joint)
    assert all(r["end_sec"] >= r["start_sec"] for r in sequence)
    assert sequence[1]["start_sec"] >= sequence[0]["end_sec"]
    flat = [v for r in isotonic for v in (r["start_sec"], r["end_sec"])]
    assert flat == sorted(flat)


def test_detector_and_learned_models():
    report = inspect_alignment(sample_rows())
    assert report["feature_count"] == 2
    assert report["features"][1]["raw_negative_duration"] == 1.0
    labelled = []
    for i in range(30):
        labelled.append({**report["features"][i % 2], "gt_error": bool(i % 2)})
    logistic = LogisticRiskModel.fit(labelled, epochs=50)
    stump = StumpBoostRiskModel.fit(labelled, rounds=3)
    assert 0.0 <= logistic.predict_score(labelled[0]) <= 1.0
    assert 0.0 <= stump.predict_score(labelled[0]) <= 1.0
    restored = LogisticRiskModel.from_dict(logistic.to_dict())
    assert abs(restored.predict_score(labelled[0]) - logistic.predict_score(labelled[0])) < 1e-12
