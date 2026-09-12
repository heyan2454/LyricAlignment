from lyricalign.unit_realign.request_families import build_family_request, classify_intervention


def _units():
    return [{"canonical_unit_id": i, "text": str(i), "start_sec": i, "end_sec": i + .5}
            for i in range(5)]


def test_family_requests_have_real_sparse_and_anchor_contracts():
    r = build_family_request(family="R-S", song_id="s", region_id="r", audio_path="a.wav",
                             units=_units(), target_unit_ids=[2], left_anchor_id=1, right_anchor_id=3)
    assert r["family"] == "R-S"
    assert r["timestamp_slot_indices"] == [2]
    assert {x["local_index"] for x in r["fixed_slot_rows"]} == {0, 1, 3, 4}
    assert r["anchors"] == {"left": 1, "right": 3}
    assert r["intervention_identity"]["full_local_ids"] == [0, 1, 2, 3, 4]


def test_family_request_null_and_oracle_are_explicit():
    null = build_family_request(family="R-U", song_id="s", region_id="r", audio_path="a",
                                units=_units(), target_unit_ids=[99])
    assert null["family"] == "R-NULL"
    oracle = build_family_request(family="R-O", song_id="s", region_id="r", audio_path="a",
                                  units=_units(), target_unit_ids=[2], oracle=True)
    assert oracle["evaluation_only"] is True


def test_rb_missing_anchor_is_not_constructible_not_r_null():
    nc = build_family_request(family="R-B", song_id="s", region_id="r", audio_path="a",
                              units=_units(), target_unit_ids=[2])
    assert nc["family"] == "R-B"
    assert nc["status"] == "not_constructible"
    assert nc["reason"] == "missing_bilateral_anchor"
    assert nc["effective_intervention"] is False


def test_whole_item_coverage_is_pseudo_local_null():
    null = build_family_request(family="R-U", song_id="s", region_id="r", audio_path="a",
                                units=_units(), target_unit_ids=[0, 1, 2, 3, 4])
    assert null["family"] == "R-NULL"
    assert null["reason"] == "whole_item_pseudo_local"


def test_non_null_excludes_family_label_but_detects_actual_slot_change():
    base = build_family_request(family="R-A", song_id="s", region_id="r", audio_path="a", units=_units(), target_unit_ids=[2])
    same_other_family = dict(base, family="R-U")
    assert classify_intervention(same_other_family, base)["null_intervention"] is True
    changed = build_family_request(family="R-S", song_id="s", region_id="r", audio_path="a", units=_units(), target_unit_ids=[2])
    assert classify_intervention(changed, base)["effective_intervention"] is True


def test_rb_requires_nearest_accept_anchor_provenance():
    request = build_family_request(family="R-B", song_id="s", region_id="r", audio_path="a", units=_units(),
                                   target_unit_ids=[2], left_anchor_id=1, right_anchor_id=3,
                                   left_accept_anchor_candidates=[0, 1], right_accept_anchor_candidates=[3, 4])
    assert request["family"] == "R-B"
    non_nearest = build_family_request(family="R-B", song_id="s", region_id="r", audio_path="a", units=_units(),
                                       target_unit_ids=[2], left_anchor_id=0, right_anchor_id=4,
                                       left_accept_anchor_candidates=[0, 1], right_accept_anchor_candidates=[3, 4])
    assert non_nearest["reason"] == "non_nearest_bilateral_anchor"


def test_identity_changes_when_same_canonical_ids_have_different_text():
    context = {"audio_sha256": "a" * 64, "baseline_digest": "sha256:b", "model_identity": "m",
               "checkpoint_identity": "c", "decoder_identity": "d", "code_identity": "g", "text_adapter_identity": "t"}
    original = build_family_request(family="R-A", song_id="s", region_id="r", audio_path="a", units=_units(), target_unit_ids=[2], identity_context=context)
    edited = _units(); edited[2] = dict(edited[2], text="changed")
    changed = build_family_request(family="R-A", song_id="s", region_id="r", audio_path="a", units=edited, target_unit_ids=[2], identity_context=context)
    assert original["request_identity"] != changed["request_identity"]


def test_rs_non_monotonic_fixed_timeline_is_not_constructible():
    # Detector shadow alignment can overlap/regress between adjacent units
    # (P1-2 follow-up: real executor requires a globally monotonic merged
    # timeline; the smoke fake executor never checked this, masking it).
    overlapping = [{"canonical_unit_id": i, "text": str(i), "start_sec": i, "end_sec": i + 0.5}
                   for i in range(5)]
    overlapping[3] = dict(overlapping[3], start_sec=1.0, end_sec=1.2)
    nc = build_family_request(family="R-S", song_id="s", region_id="r", audio_path="a",
                              units=overlapping, target_unit_ids=[2])
    assert nc["family"] == "R-S"
    assert nc["status"] == "not_constructible"
    assert nc["reason"] == "non_monotonic_fixed_timeline"
    assert nc["effective_intervention"] is False


def test_local_context_is_family_specific():
    units = _units()
    ru = build_family_request(family="R-U", song_id="s", region_id="r", audio_path="a",
                              units=units, target_unit_ids=[2])
    ra = build_family_request(family="R-A", song_id="s", region_id="r", audio_path="a",
                              units=units, target_unit_ids=[2])
    rb = build_family_request(family="R-B", song_id="s", region_id="r", audio_path="a",
                              units=units, target_unit_ids=[2], left_anchor_id=1, right_anchor_id=3,
                              left_accept_anchor_candidates=[0, 1], right_accept_anchor_candidates=[3, 4])
    rs = build_family_request(family="R-S", song_id="s", region_id="r", audio_path="a",
                              units=units, target_unit_ids=[2])
    # R-U: target plus 1 neighbor on each side -> [1,2,3]
    assert ru["canonical_ids"] == [1, 2, 3]
    assert ru["fixed_context_unit_ids"] == [1, 3]
    assert ru["candidate_text_ids"] == [1, 2, 3]
    assert ru["text_units"] == ["1", "2", "3"]
    # R-A with default context 1: same span as R-U here.
    assert ra["canonical_ids"] == [1, 2, 3]
    # R-A with larger context: span + 2 on each side -> [0..4]
    ra2 = build_family_request(family="R-A", song_id="s", region_id="r", audio_path="a",
                               units=units, target_unit_ids=[2], ra_context_units=2)
    assert ra2["canonical_ids"] == [0, 1, 2, 3, 4]
    # R-B: bounded by nearest anchors inclusive -> [1,2,3]
    assert rb["canonical_ids"] == [1, 2, 3]
    # R-S: full local window, and audio is the full local span (not target span), padded by one
    # audio_margin_sec (default 0.5) so a collapsed/zero-duration local span cannot produce the
    # degenerate "invalid audio range: t,t" crop (see commit a6cdb8a); the start is clamped at 0.
    assert rs["canonical_ids"] == [0, 1, 2, 3, 4]
    assert rs["audio_start_sec"] == 0.0
    assert rs["audio_end_sec"] == 4.5 + 0.5
    # the crop still covers the whole local span rather than collapsing to the target
    assert rs["audio_start_sec"] <= 0.0 and rs["audio_end_sec"] >= 4.5


def test_ru_zero_neighbors_and_audio_margin():
    units = _units()
    r = build_family_request(family="R-U", song_id="s", region_id="r", audio_path="a",
                             units=units, target_unit_ids=[2], context_neighbors=0,
                             audio_margin_sec=0.5)
    assert r["canonical_ids"] == [2]
    assert r["fixed_context_unit_ids"] == []
    # target [2,2.5] plus 0.5 margin
    assert r["audio_start_sec"] == 1.5
    assert r["audio_end_sec"] == 3.0


def test_ra_context_and_audio_margin():
    units = _units()
    r = build_family_request(family="R-A", song_id="s", region_id="r", audio_path="a",
                             units=units, target_unit_ids=[2], ra_context_units=1,
                             audio_margin_sec=0.25)
    assert r["canonical_ids"] == [1, 2, 3]
    assert r["audio_start_sec"] == 1.75
    assert r["audio_end_sec"] == 2.75


def _id_context(**extra):
    return {"audio_sha256": "a" * 64, "baseline_digest": "sha256:b", "model_identity": "m",
            "checkpoint_identity": "c", "decoder_identity": "d", "code_identity": "g",
            "text_adapter_identity": "t", **extra}


def test_multi_realign_family_context_changes_identity():
    """parent/iteration/recrop/split must be part of cache identity (07 plan WP1)."""
    base = _id_context()
    r0 = build_family_request(family="R-U", song_id="s", region_id="r", audio_path="a",
                              units=_units(), target_unit_ids=[2], identity_context=base)
    # Same request, same identity (cache hit when nothing extra changed).
    r0b = build_family_request(family="R-U", song_id="s", region_id="r", audio_path="a",
                               units=_units(), target_unit_ids=[2], identity_context=base)
    assert r0["request_identity"] == r0b["request_identity"]

    # Each of the four family-context dimensions must change the identity.
    for key, val in (("iteration", 2), ("recrop_view_id", "left"), ("split_slot_id", "s1")):
        rv = build_family_request(family="R-U", song_id="s", region_id="r", audio_path="a",
                                  units=_units(), target_unit_ids=[2],
                                  identity_context=_id_context(**{key: val}))
        assert rv["request_identity"] != r0["request_identity"], key

    # parent_request_identity needs a valid sha256 string to pass the required check.
    parent = build_family_request(family="R-A", song_id="s", region_id="r", audio_path="a",
                                  units=_units(), target_unit_ids=[2], identity_context=base)
    parent_id = parent["request_identity"]
    r_child = build_family_request(family="R-U", song_id="s", region_id="r", audio_path="a",
                                   units=_units(), target_unit_ids=[2],
                                   identity_context=_id_context(parent_request_identity=parent_id))
    assert r_child["request_identity"] != r0["request_identity"]


def test_multi_realign_family_context_is_reproducible():
    """Identical parent/iteration context yields identical identity (cache reuse)."""
    ctx_a = _id_context(iteration=3, recrop_view_id="wider", split_slot_id="a0",
                        parent_request_identity="sha256:" + "d" * 64)
    ctx_b = _id_context(iteration=3, recrop_view_id="wider", split_slot_id="a0",
                        parent_request_identity="sha256:" + "d" * 64)
    ra = build_family_request(family="R-U", song_id="s", region_id="r", audio_path="a",
                              units=_units(), target_unit_ids=[2], identity_context=ctx_a)
    rb = build_family_request(family="R-U", song_id="s", region_id="r", audio_path="a",
                              units=_units(), target_unit_ids=[2], identity_context=ctx_b)
    assert ra["request_identity"] == rb["request_identity"]


def test_chained_request_with_parent_requires_all_family_keys():
    """A request that links to a parent must carry every family identity key (WP1)."""
    # parent present but iteration/recrop/split omitted -> identity is None (fail closed).
    partial = build_family_request(family="R-U", song_id="s", region_id="r", audio_path="a",
                                   units=_units(), target_unit_ids=[2],
                                   identity_context=_id_context(parent_request_identity="sha256:" + "d" * 64))
    assert partial["request_identity"] is None


def test_non_whitelisted_mechanism_key_changes_identity():
    """Future mechanism/direction keys folded via chain_context must change identity (P1-2)."""
    base = _id_context()
    with_dir = _id_context(direction="right_to_left")
    ra = build_family_request(family="R-U", song_id="s", region_id="r", audio_path="a",
                              units=_units(), target_unit_ids=[2], identity_context=base)
    rb = build_family_request(family="R-U", song_id="s", region_id="r", audio_path="a",
                              units=_units(), target_unit_ids=[2], identity_context=with_dir)
    assert ra["request_identity"] != rb["request_identity"]
