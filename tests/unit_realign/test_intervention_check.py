from lyricalign.unit_realign.intervention_check import validate_request
from lyricalign.unit_realign.request_families import build_family_request


def _units():
    return [{"canonical_unit_id": i, "text": str(i), "start_sec": float(i), "end_sec": float(i) + .5}
            for i in range(3)]


def _context():
    return {"audio_sha256": "a" * 64, "baseline_digest": "sha256:base", "model_identity": "model@1",
            "checkpoint_identity": "checkpoint@1", "decoder_identity": "decoder@1", "code_identity": "git:abc",
            "text_adapter_identity": "adapter@1", "audio_preprocess_identity": "pre@1",
            "determinism_identity": "seed:0"}


def test_v2_request_requires_exact_identity_and_rejects_gt_fields():
    request = build_family_request(family="R-S", song_id="s", region_id="r", audio_path="a.wav",
                                   units=_units(), target_unit_ids=[1], identity_context=_context())
    assert validate_request(request)["status"] == "ready"
    leaky = dict(request, gt_label="bad")
    assert validate_request(leaky)["reason"].startswith("forbidden_request_field")
    stale = dict(request, request_identity="sha256:wrong")
    assert validate_request(stale)["reason"] == "request_identity_mismatch"
