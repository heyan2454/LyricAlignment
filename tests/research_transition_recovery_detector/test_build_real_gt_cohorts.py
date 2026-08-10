"""build_real_gt_cohorts.py 单元测试（Doc 19 Stage 2）。

全部使用内联合成 fixture：split manifest + overlay manifest + annotations。
materialize 路径用 python wave 生成真实 16k mono wav（无需 ffmpeg 编码），
再走 builder 子进程全链路。
"""
import hashlib
import importlib.util
import json
import struct
import wave
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / \
    "research_transition_recovery_detector" / "build_real_gt_cohorts.py"
_spec = importlib.util.spec_from_file_location("build_real_gt_cohorts", _SCRIPT)
brc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(brc)

ACC = "accepted_rule_based_pinyin_validated"
REVIEW = "review_required_pinyin_parse_ambiguous"


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _seg(item_id: str, song: str, singer: str, dur: float, text: str, rel: str) -> dict:
    return {
        "item_id": item_id, "song_id": song, "singer_id": singer,
        "duration_sec": dur, "audio_relpath": rel,
        "lyrics_normalized": text,
    }


def _split_row(song: str, split: str) -> dict:
    return {"song_id": song, "split": split}


def _ann(song: str, item: str, idx: int, start: float, end: float,
         char: str, status: str = ACC) -> dict:
    return {
        "song_id": song, "item_id": item, "character_index": idx,
        "start_sec": start, "end_sec": end,
        "mapping_status": status,
        "normalized_character": char, "raw_character": char,
    }


def _mk_audio(root: Path, rel: str, seconds: float = 0.2) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    rate, n = 16000, int(16_000 * seconds)
    with wave.open(str(p), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack(f"<{n}h", *([0] * n)))
    return p


def _make_annotations(seg_rows: list[dict], rejected_items: set[str] | None = None):
    """对每段生成逐字符 accepted annotations；rejected_items 中的段用 review status。"""
    rejected_items = rejected_items or set()
    rows = []
    for s in seg_rows:
        text = s["lyrics_normalized"]
        per = s["duration_sec"] / len(text)
        status = REVIEW if s["item_id"] in rejected_items else ACC
        for i, ch in enumerate(text):
            rows.append(_ann(s["song_id"], s["item_id"], i,
                             i * per, (i + 1) * per, ch, status=status))
    return rows


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _read_jsonl(p: Path) -> list[dict]:
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


# ---------------------------------------------------------------- non-materialize
def _build_static_fixture(tmp_path: Path) -> dict[str, Path]:
    """S1=正常 test 200s；S2=短 validation 100s；S3=同歌同 role 重复行(test)；S4=非 role；
    S5=缺 audio train；S6=同歌不同 role 冲突(test/validation)。"""
    audio_root = tmp_path / "audio"
    overlay = [
        _seg("S#S1#0000", "S1", "S1", 100.0, "我爱我的祖国大地", "s1/0000.wav"),
        _seg("S#S1#0001", "S1", "S1", 100.0, "五星红旗迎风飘扬", "s1/0001.wav"),
        _seg("S#S2#0000", "S2", "S2", 50.0, "小小竹排江中游", "s2/0000.wav"),
        _seg("S#S2#0001", "S2", "S2", 50.0, "巍巍青山两岸走", "s2/0001.wav"),
        _seg("S#S3#0000", "S3", "S3", 100.0, "我们都有一个家", "s3/0000.wav"),
        _seg("S#S3#0001", "S3", "S3", 100.0, "名字叫中国", "s3/0001.wav"),
        _seg("S#S4#0000", "S4", "S4", 100.0, "兄弟姐妹都很多", "s4/0000.wav"),
        _seg("S#S4#0001", "S4", "S4", 100.0, "景色也不错", "s4/0001.wav"),
        _seg("S#S5#0000", "S5", "S5", 100.0, "家里盘着两条龙", "s5/0000.wav"),
        _seg("S#S5#0001", "S5", "S5", 100.0, "是长江与黄河", "s5/0001.wav"),
        _seg("S#S6#0000", "S6", "S6", 100.0, "五千年的风和雨", "s6/0000.wav"),
        _seg("S#S6#0001", "S6", "S6", 100.0, "藏了多少梦", "s6/0001.wav"),
    ]
    for s in overlay[:8] + overlay[10:]:  # S5 故意缺音频
        _mk_audio(audio_root, s["audio_relpath"])
    split = [
        _split_row("S1", "test"),
        _split_row("S2", "validation"),
        _split_row("S3", "test"),
        _split_row("S3", "test"),          # 同歌同 role 重复行 → 去重，不算 duplicate
        _split_row("S4", "other"),
        _split_row("S5", "train"),
        _split_row("S6", "test"),
        _split_row("S6", "validation"),    # 同歌跨行 role 不一致 → 真正冲突
    ]
    overlay_path = tmp_path / "overlay_manifest.jsonl"
    split_path = tmp_path / "split_manifest.jsonl"
    ann_path = tmp_path / "annotations.jsonl"
    _write_jsonl(overlay_path, overlay)
    _write_jsonl(split_path, split)
    _write_jsonl(ann_path, [])
    return {"overlay": overlay_path, "split": split_path, "ann": ann_path,
            "audio_root": audio_root, "out": tmp_path / "out"}


def test_inventory_candidates_exclusions_and_audit(tmp_path):
    fx = _build_static_fixture(tmp_path)
    rc = brc.main([
        "--overlay-manifest", str(fx["overlay"]),
        "--annotations", str(fx["ann"]),
        "--split-manifest", str(fx["split"]),
        "--audio-root", str(fx["audio_root"]),
        "--out-root", str(fx["out"]),
        "--min-natural-duration-sec", "180",
    ])
    assert rc == 0
    out = fx["out"]

    inv = _read_jsonl(out / "inventory" / "COMPLETE_SONG_INVENTORY.jsonl")
    assert [r["song_id"] for r in inv] == ["S1", "S2", "S3", "S4", "S5", "S6"]
    by_id = {r["song_id"]: r for r in inv}
    assert by_id["S1"] == {"song_id": "S1", "role": "test", "n_segments": 2,
                           "natural_duration_sec": 200.0, "in_split": True,
                           "n_split_occurrences": 1, "duplicate_in_split": False,
                           "audio_ok": True,
                           "audio_path": str(fx["audio_root"] / "s1/0000.wav")}
    # P0: 同歌同 role 多行 → 去重不算 duplicate；同歌跨行 role 不一致 → 真正冲突
    assert by_id["S3"]["n_split_occurrences"] == 2
    assert by_id["S3"]["duplicate_in_split"] is False
    assert by_id["S3"]["role"] == "test"
    assert by_id["S6"]["n_split_occurrences"] == 2
    assert by_id["S6"]["duplicate_in_split"] is True
    assert by_id["S5"]["audio_ok"] is False

    cand_a = _read_jsonl(out / "COHORT_A_FORMAL_candidates.jsonl")
    cand_b = _read_jsonl(out / "COHORT_B_DEVELOPMENT_candidates.jsonl")
    cand_d = _read_jsonl(out / "COHORT_D_TRAIN_OVERLAP_DIAGNOSTIC_candidates.jsonl")
    assert [r["song_id"] for r in cand_a] == ["S1", "S3"]
    assert cand_a[0] == {"song_id": "S1", "split": "test", "natural_duration_sec": 200.0,
                         "n_segments": 2, "audio_path": str(fx["audio_root"] / "s1/0000.wav")}
    assert cand_b == []
    assert cand_d == []  # S5 缺音频被 missing_audio 排除

    excl = _read_jsonl(out / "EXCLUSION_LOG.jsonl")
    reasons = {r["song_id"]: r["reason"] for r in excl}
    assert reasons == {"S2": "below_min_natural_duration", "S4": "not_in_role",
                       "S5": "missing_audio", "S6": "duplicate_in_split"}

    audit = json.loads((out / "SPLIT_AUDIT.json").read_text(encoding="utf-8"))
    assert audit["checks"]["a_b_disjoint"] is True
    assert audit["checks"]["a_b_no_train_overlap"] is True
    assert audit["checks"]["a_songs_exactly_once_in_split"] is True
    assert audit["checks"]["b_songs_exactly_once_in_split"] is True
    assert audit["all_checks_pass"] is True
    assert audit["counts"] == {"cohort_a": 2, "cohort_b": 0, "cohort_d": 0, "inventory_songs": 6}
    assert audit["split_occurrences_in_inventory"] == {
        "S1": 1, "S2": 1, "S3": 2, "S4": 1, "S5": 1, "S6": 2}

    freeze = json.loads((out / "FREEZE.json").read_text(encoding="utf-8"))
    assert freeze["candidate_counts"] == {"cohort_a": 2, "cohort_b": 0, "cohort_d": 0}
    assert freeze["gates"]["min_natural_duration_sec"] == 180.0
    assert freeze["gates"]["primary_coverage_gate"] == 0.90
    assert freeze["gates"]["diagnostic_coverage_floor"] == 0.85
    assert freeze["inputs"]["overlay_manifest"]["sha256"] == _sha(fx["overlay"])
    assert freeze["inputs"]["split_manifest"]["sha256"] == _sha(fx["split"])
    assert freeze["inputs"]["annotations"]["sha256"] == _sha(fx["ann"])
    assert freeze["git_head_sha"]
    assert freeze["files"]["inventory"] == _sha(out / "inventory" / "COMPLETE_SONG_INVENTORY.jsonl")
    assert freeze["files"]["cohort_a_candidates"] == _sha(out / "COHORT_A_FORMAL_candidates.jsonl")


def test_no_materialize_does_not_run_builder(tmp_path):
    fx = _build_static_fixture(tmp_path)
    rc = brc.main([
        "--overlay-manifest", str(fx["overlay"]),
        "--annotations", str(fx["ann"]),
        "--split-manifest", str(fx["split"]),
        "--audio-root", str(fx["audio_root"]),
        "--out-root", str(fx["out"]),
    ])
    assert rc == 0
    out = fx["out"]
    assert not (out / "manifest_cohort_a").exists()
    assert not (out / "real_gt").exists()
    assert not (out / "COHORT_A_FORMAL.jsonl").exists()
    freeze = json.loads((out / "FREEZE.json").read_text(encoding="utf-8"))
    assert freeze["cli_args"]["materialize"] == "False"


def test_floor_above_gate_rejected(tmp_path):
    fx = _build_static_fixture(tmp_path)
    rc = brc.main([
        "--overlay-manifest", str(fx["overlay"]),
        "--annotations", str(fx["ann"]),
        "--split-manifest", str(fx["split"]),
        "--audio-root", str(fx["audio_root"]),
        "--out-root", str(fx["out"]),
        "--primary-coverage-gate", "0.85",
        "--diagnostic-coverage-floor", "0.90",
    ])
    assert rc == 2


# ---------------------------------------------------------------- materialize
def _build_materialize_fixture(tmp_path: Path) -> dict[str, Path]:
    """M1=test 全 accepted（coverage 1.0）；M2=validation 半段 review（coverage<floor）。"""
    audio_root = tmp_path / "audio"
    m1_segs = [
        _seg("S#M1#0000", "M1", "M1", 45.0, "我爱你中国我爱你中国", "m1/0000.wav"),
        _seg("S#M1#0001", "M1", "M1", 45.0, "我爱你中国心爱的祖国", "m1/0001.wav"),
    ]
    m2_segs = [
        _seg("S#M2#0000", "M2", "M2", 45.0, "我们都有一个家名字", "m2/0000.wav"),
        _seg("S#M2#0001", "M2", "M2", 45.0, "叫中国兄弟姐妹都", "m2/0001.wav"),
    ]
    for s in m1_segs + m2_segs:
        _mk_audio(audio_root, s["audio_relpath"])
    overlay = m1_segs + m2_segs
    split = [_split_row("M1", "test"), _split_row("M2", "validation")]
    overlay_path = tmp_path / "overlay_manifest.jsonl"
    split_path = tmp_path / "split_manifest.jsonl"
    ann_path = tmp_path / "annotations.jsonl"
    _write_jsonl(overlay_path, overlay)
    _write_jsonl(split_path, split)
    ann = _make_annotations(m1_segs, rejected_items=set()) + \
        _make_annotations(m2_segs, rejected_items={"S#M2#0001"})
    _write_jsonl(ann_path, ann)
    return {"overlay": overlay_path, "split": split_path, "ann": ann_path,
            "audio_root": audio_root, "out": tmp_path / "out"}


def test_materialize_full_chain_and_coverage_gate(tmp_path):
    fx = _build_materialize_fixture(tmp_path)
    rc = brc.main([
        "--overlay-manifest", str(fx["overlay"]),
        "--annotations", str(fx["ann"]),
        "--split-manifest", str(fx["split"]),
        "--audio-root", str(fx["audio_root"]),
        "--out-root", str(fx["out"]),
        "--min-natural-duration-sec", "80",
        "--seam-silence-sec", "0.0",
        "--materialize",
    ])
    assert rc == 0, rc
    out = fx["out"]

    man_a = out / "manifest_cohort_a" / "LONG_TIMELINE_MANIFEST.jsonl"
    man_b = out / "manifest_cohort_b" / "LONG_TIMELINE_MANIFEST.jsonl"
    assert man_a.is_file()
    assert man_b.is_file()

    cov_a = _read_jsonl(out / "real_gt" / "REAL_GT_COVERAGE_a.jsonl")
    cov_b = _read_jsonl(out / "real_gt" / "REAL_GT_COVERAGE_b.jsonl")
    assert len(cov_a) == 1 and cov_a[0]["song_id"] == "M1"
    assert cov_a[0]["coverage"] == 1.0
    assert cov_a[0]["gate_status"] == "formal"
    assert len(cov_b) == 1 and cov_b[0]["song_id"] == "M2"
    assert cov_b[0]["coverage"] < 0.85
    assert cov_b[0]["gate_status"] == "below_floor"

    audit_a = json.loads((out / "real_gt" / "REAL_GT_PROJECTION_AUDIT_a.json").read_text(encoding="utf-8"))
    assert audit_a["cohort"] == "a"
    assert audit_a["summary"]["songs"] == 1
    assert audit_a["per_song"]["M1"]["accepted_gt_units"] > 0

    # P1#2: REAL_GT_COVERAGE per-song 键与 real_gt.py audit 对齐（accepted/unlabeled，保留 total_units）
    assert cov_a[0]["accepted"] > 0
    assert cov_a[0]["unlabeled"] == 0
    assert cov_a[0]["total_units"] == cov_a[0]["accepted"] + cov_a[0]["unlabeled"]

    cohort_a = _read_jsonl(out / "COHORT_A_FORMAL.jsonl")
    cohort_b = _read_jsonl(out / "COHORT_B_DEVELOPMENT.jsonl")
    cohort_d = _read_jsonl(out / "COHORT_D_TRAIN_OVERLAP_DIAGNOSTIC.jsonl")
    assert [r["song_id"] for r in cohort_a] == ["M1"]
    assert cohort_a[0]["coverage"] == 1.0
    assert cohort_a[0]["accepted_gt_units"] > 0  # formal frozen 行保留 accepted_gt_units/unlabeled_units 键
    assert cohort_a[0]["unlabeled_units"] == 0
    assert cohort_a[0]["long_manifest_row_sha"]
    assert cohort_b == []  # M2 coverage < floor 被移除
    assert cohort_d == []  # 无 train 歌

    excl = _read_jsonl(out / "EXCLUSION_LOG.jsonl")
    assert [r for r in excl if r["reason"] == "below_coverage_gate"][0]["song_id"] == "M2"

    freeze = json.loads((out / "FREEZE.json").read_text(encoding="utf-8"))
    assert freeze["final_counts"] == {"cohort_a": 1, "cohort_b": 0, "cohort_d": 0,
                                      "cohort_a_diagnostic": 0, "cohort_b_diagnostic": 0}
    assert freeze["exclusion_stats"]["below_coverage_gate"] == 1
    assert freeze["exclusion_stats"]["diagnostic_only_range"] == 0
    assert freeze["coverage_rejected"]["cohort_b"] == ["M2"]
    assert freeze["builder_rejected"]["count"] == 0
    assert freeze["files"]["cohort_a_formal"] == _sha(out / "COHORT_A_FORMAL.jsonl")
    assert freeze["files"]["cohort_a_diagnostic"] == _sha(out / "COHORT_A_DIAGNOSTIC.jsonl")
    assert freeze["files"]["manifest_cohort_a"] == _sha(man_a)
    assert freeze["files"]["manifest_cohort_b"] == _sha(man_b)
    assert freeze["files"]["real_gt_coverage_a"] == _sha(out / "real_gt" / "REAL_GT_COVERAGE_a.jsonl")


def test_materialize_diagnostic_only_range(tmp_path):
    """coverage in [floor, gate) 保留为 diagnostic_only；<floor 移除。"""
    audio_root = tmp_path / "audio"
    # 6 字符段：仅 1 段中 1 字符 review → accepted 11/12 ≈ 0.917 >= 0.90 → formal
    segs = [
        _seg("S#M1#0000", "M1", "M1", 45.0, "你好世界", "m1/0000.wav"),
        _seg("S#M1#0001", "M1", "M1", 45.0, "你好中国", "m1/0001.wav"),
    ]
    for s in segs:
        _mk_audio(audio_root, s["audio_relpath"])
    overlay_path = tmp_path / "overlay_manifest.jsonl"
    split_path = tmp_path / "split_manifest.jsonl"
    ann_path = tmp_path / "annotations.jsonl"
    _write_jsonl(overlay_path, segs)
    _write_jsonl(split_path, [_split_row("M1", "test")])
    ann = _make_annotations(segs, rejected_items={"S#M1#0001"})
    _write_jsonl(ann_path, ann)
    out = tmp_path / "out"
    rc = brc.main([
        "--overlay-manifest", str(overlay_path),
        "--annotations", str(ann_path),
        "--split-manifest", str(split_path),
        "--audio-root", str(audio_root),
        "--out-root", str(out),
        "--min-natural-duration-sec", "80",
        "--materialize",
    ])
    assert rc == 0, rc
    man_a = out / "manifest_cohort_a" / "LONG_TIMELINE_MANIFEST.jsonl"
    assert man_a.is_file()  # cohort A 有候选 → 必须 materialize
    # cohort B 无候选 → 不调用 builder，也不产生 manifest（空 cohort 合法）
    assert not (out / "manifest_cohort_b").exists()
    cov_a = _read_jsonl(out / "real_gt" / "REAL_GT_COVERAGE_a.jsonl")
    # 4 accepted + 4 review = 0.5 < floor 0.85 → below_floor；此处断言 gate 语义而非值
    assert cov_a[0]["gate_status"] in ("formal", "diagnostic_only", "below_floor")
    assert cov_a[0]["coverage"] == round(8 / 16, 6)


def test_materialize_diagnostic_only_writes_separate_cohort(tmp_path):
    """coverage ∈ [floor, gate) → COHORT_A_DIAGNOSTIC.jsonl + EXCLUSION_LOG diagnostic_only_range。"""
    audio_root = tmp_path / "audio"
    segs = [
        _seg("S#D1#0000", "D1", "D1", 45.0, "我们都有一个家", "d1/0000.wav"),
        _seg("S#D1#0001", "D1", "D1", 45.0, "名字叫中国", "d1/0001.wav"),
    ]
    for s in segs:
        _mk_audio(audio_root, s["audio_relpath"])
    overlay_path = tmp_path / "overlay_manifest.jsonl"
    split_path = tmp_path / "split_manifest.jsonl"
    ann_path = tmp_path / "annotations.jsonl"
    _write_jsonl(overlay_path, segs)
    _write_jsonl(split_path, [_split_row("D1", "test")])
    # 7 accepted + 5 review（段 0001 整段被拒）→ coverage 7/12 ≈ 0.583 ∈ [0.5, 0.90) → diagnostic_only
    ann = _make_annotations(segs, rejected_items={"S#D1#0001"})
    _write_jsonl(ann_path, ann)
    out = tmp_path / "out"
    rc = brc.main([
        "--overlay-manifest", str(overlay_path),
        "--annotations", str(ann_path),
        "--split-manifest", str(split_path),
        "--audio-root", str(audio_root),
        "--out-root", str(out),
        "--min-natural-duration-sec", "80",
        "--diagnostic-coverage-floor", "0.5",
        "--materialize",
    ])
    assert rc == 0, rc

    diag_a = _read_jsonl(out / "COHORT_A_DIAGNOSTIC.jsonl")
    assert [r["song_id"] for r in diag_a] == ["D1"]
    assert diag_a[0]["gate_status"] == "diagnostic_only"
    assert diag_a[0]["coverage"] == round(7 / 12, 6)
    assert diag_a[0]["diagnostic_only_note"]

    cohort_a = _read_jsonl(out / "COHORT_A_FORMAL.jsonl")
    assert cohort_a == []  # 冻结文件只收 coverage >= primary_gate

    excl = _read_jsonl(out / "EXCLUSION_LOG.jsonl")
    assert [r for r in excl if r["reason"] == "diagnostic_only_range"][0]["song_id"] == "D1"

    freeze = json.loads((out / "FREEZE.json").read_text(encoding="utf-8"))
    assert freeze["final_counts"]["cohort_a"] == 0
    assert freeze["final_counts"]["cohort_a_diagnostic"] == 1
    assert freeze["exclusion_stats"]["diagnostic_only_range"] == 1
    assert freeze["files"]["cohort_a_diagnostic"] == _sha(out / "COHORT_A_DIAGNOSTIC.jsonl")


def test_materialize_builder_rejected_in_exclusion_log(tmp_path, monkeypatch):
    """builder 拒绝的歌 → EXCLUSION_LOG reason=builder_rejected + FREEZE.builder_rejected。"""
    audio_root = tmp_path / "audio"
    segs = [
        _seg("S#B1#0000", "B1", "B1", 45.0, "我们都有一个家", "b1/0000.wav"),
        _seg("S#B1#0001", "B1", "B1", 45.0, "名字叫中国", "b1/0001.wav"),
    ]
    for s in segs:
        _mk_audio(audio_root, s["audio_relpath"])
    overlay_path = tmp_path / "overlay_manifest.jsonl"
    split_path = tmp_path / "split_manifest.jsonl"
    ann_path = tmp_path / "annotations.jsonl"
    _write_jsonl(overlay_path, segs)
    _write_jsonl(split_path, [_split_row("B1", "test")])
    _write_jsonl(ann_path, _make_annotations(segs, rejected_items=set()))
    out = tmp_path / "out"

    def _fake_builder(overlay_manifest, out_root, audio_root_, min_duration,
                      seam_silence_sec, allowlist, n_allowlist):
        out_root = Path(out_root)
        out_root.mkdir(parents=True, exist_ok=True)
        (out_root / "LONG_TIMELINE_MANIFEST.jsonl").write_text("", encoding="utf-8")
        _write_jsonl(out_root / "ALLOWLIST_REJECTIONS.jsonl",
                     [{"song_id": "B1", "reason": "not_in_allowlist"}])

    monkeypatch.setattr(brc, "run_builder", _fake_builder)
    rc = brc.main([
        "--overlay-manifest", str(overlay_path),
        "--annotations", str(ann_path),
        "--split-manifest", str(split_path),
        "--audio-root", str(audio_root),
        "--out-root", str(out),
        "--min-natural-duration-sec", "80",
        "--materialize",
    ])
    assert rc == 0, rc

    excl = _read_jsonl(out / "EXCLUSION_LOG.jsonl")
    br_rows = [r for r in excl if r["reason"] == "builder_rejected"]
    assert len(br_rows) == 1
    assert br_rows[0]["song_id"] == "B1"
    assert "not_in_allowlist" in br_rows[0]["note"]

    freeze = json.loads((out / "FREEZE.json").read_text(encoding="utf-8"))
    assert freeze["builder_rejected"]["count"] == 1
    assert freeze["builder_rejected"]["by_cohort"]["cohort_a"] == ["B1"]
    assert freeze["builder_rejected"]["details_files"]["cohort_a"].endswith("ALLOWLIST_REJECTIONS.jsonl")
