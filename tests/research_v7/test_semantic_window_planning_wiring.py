"""契约测试：semantic_window_planning 规则 v2 接线（EXPLORATION_NOTES §12 + backlog）。

覆盖：plan_request_windows 输出可直接填充 AlignmentRequest（canonical 字段自洽、
source_window_sec 与 unit 时间一致、validate 通过）；绒花 w1/w2 简化样例各出 4 子窗；
build_requests 双模式（fixed 冻结口径不变 / semantic 子窗 ≤30s 且带 window_mode）。
"""
from __future__ import annotations

import json

from lyricalign.research_v7.requests import AlignmentRequest
from lyricalign.research_v7.semantic_window_planning import plan_request_windows

_FILLER = "一路芬芳满山崖世上好花有朵英雄滴那是青春放光华载亲人们请记住当年解放军的队伍走向前方边关风雪永不忘这茫茫天地之间是谁写下壮丽篇章"


def _filler(n):
    """n 个互不相同的填充字符（避免被 len>=4 任意字符规则误判为 run）。"""
    return [_FILLER[i % len(_FILLER)] for i in range(n)]


def build_units(items):
    """items: list[(text, dur, gap_before)] -> canonical units dict（含 start/end）。"""
    units = []
    t = 0.0
    for text, dur, gap in items:
        t += gap
        units.append({
            "canonical_unit_id": len(units),
            "text": text,
            "start_sec": round(t, 6),
            "end_sec": round(t + dur, 6),
        })
        t += dur
    return units


def _ronghua_w1():
    # 4 个 啊-run 段（每段后 gap<0.5 不拆），窗口在下一 run 起点切开 -> 恰好 4 子窗
    items = []
    for _ in range(4):
        items += [("啊", 0.5, 0.0)] * 8
        items += [(t, 0.6, 0.2) for t in _filler(8)]
    return build_units(items)


def _ronghua_w2():
    # 3 个 run 段，第 3 个 run 后 gap=2.0>GAP_RUN_SPLIT -> run 单独成窗 -> 恰好 4 子窗
    items = [("啊", 0.5, 0.0)] * 7 + [(t, 0.6, 0.2) for t in _filler(7)]
    items += [("啊", 0.5, 0.0)] * 8 + [(t, 0.6, 0.2) for t in _filler(4)]
    items += [("啊", 0.5, 0.0)] * 8
    items += [(t, 0.6, 2.0 if j == 0 else 0.0) for j, t in enumerate(_filler(20))]
    return build_units(items)


def _make_request(sw: dict) -> AlignmentRequest:
    ids = sw["canonical_ids"]
    texts = [u["text"] for u in _UNITS if u["canonical_unit_id"] in set(ids)]
    req = AlignmentRequest(
        request_id="test:sw",
        item_id="test",
        parent_request_id=None,
        audio_source="test",
        audio_start_sec=sw["start_sec"],
        audio_end_sec=sw["end_sec"],
        text_source="test",
        text_start_index=0,
        text_end_index=len(texts),
        text_units=tuple(texts),
        timestamp_slot_indices=None,
        workflow_mode="long_slot_60s",
        mutation_type="baseline",
        mutation_parameters={},
        model_id="test-model",
        checkpoint_id="test-ckpt",
        input_variant="long_timeline_v1",
        canonical_text_start=sw["canonical_text_start"],
        canonical_text_end=sw["canonical_text_end"],
        canonical_to_local={cid: i for i, cid in enumerate(ids)},
        canonical_ids=ids,
        source_window_sec=tuple(sw["source_window_sec"]),
    )
    return req


_UNITS: list[dict] = []


def test_plan_request_windows_ronghua_w1_four_subwindows():
    units = _ronghua_w1()
    wins = plan_request_windows(units, (0, len(units)))
    assert len(wins) == 4                        # §12 规则窗数一致
    for w in wins:
        assert w["canonical_text_end"] - w["canonical_text_start"] >= 1
        # source_window_sec == 首 unit start / 末 unit end
        ids = w["canonical_ids"]
        first = next(u for u in units if u["canonical_unit_id"] == ids[0])
        last = next(u for u in units if u["canonical_unit_id"] == ids[-1])
        assert w["source_window_sec"] == (first["start_sec"], last["end_sec"])


def test_plan_request_windows_ronghua_w2_four_subwindows():
    units = _ronghua_w2()
    wins = plan_request_windows(units, (0, len(units)))
    assert len(wins) == 4                        # §12 规则窗数一致
    for w in wins:
        ids = w["canonical_ids"]
        first = next(u for u in units if u["canonical_unit_id"] == ids[0])
        last = next(u for u in units if u["canonical_unit_id"] == ids[-1])
        assert w["source_window_sec"] == (first["start_sec"], last["end_sec"])


def test_plan_request_windows_dict_accepts_canonical_text_start_end():
    units = _ronghua_w1()
    full = {"canonical_text_start": 0, "canonical_text_end": len(units)}
    wins = plan_request_windows(units, full)
    assert len(wins) == 4
    # 输出 round-trip：canonical_text_end 可喂回 _window_bounds 语义
    for w in wins:
        assert w["canonical_text_end"] == w["canonical_ids"][-1] + 1
        assert w["canonical_text_start"] == w["canonical_ids"][0]


def test_request_roundtrip_validate_and_identity():
    units = _ronghua_w1()
    global _UNITS
    _UNITS = units
    wins = plan_request_windows(units, (0, len(units)))
    assert len(wins) == 4
    reqs = [_make_request(w) for w in wins]
    for req in reqs:
        req.validate(total_units=len(units), duration_sec=units[-1]["end_sec"])
    # 内容寻址 identity：同窗口稳定、不同窗口不同
    ids = {r.request_identity(context={"test": "wiring"}) for r in reqs}
    assert len(ids) == len(reqs)
    # canonical 字段自洽：text 覆盖与 canonical_ids 一致
    for req, w in zip(reqs, wins):
        assert req.canonical_ids == w["canonical_ids"]
        assert req.canonical_text_start == w["canonical_text_start"]
        assert req.canonical_text_end == w["canonical_text_end"]
        assert tuple(req.source_window_sec) == tuple(w["source_window_sec"])


def test_build_requests_fixed_matches_frozen_semantics():
    from scripts.research_v7.build_long_timeline_manifest import build_requests

    units = build_units([(t, 0.6, 0.2) for t in _filler(120)])     # 72s
    timeline = _Timeline(units)
    tl = {"song_id": "test_song", "segs_audio": ["test.wav"], "manifest_sha": "sha:test",
          "source_split": "validation"}
    fixed = build_requests(tl, timeline, windows_per_song=1, row_sha="sha:row")
    sem = build_requests(tl, timeline, windows_per_song=1, row_sha="sha:row",
                         use_semantic_windows=True)
    # fixed：冻结口径，不携带 window_mode
    assert all("window_mode" not in r for r in fixed)
    # semantic：子窗 ≤30s 且带 window_mode
    assert sem
    assert all(r["window_mode"] == "semantic" for r in sem)
    for r in sem:
        assert r["duration_sec"] <= 30.0 + 1e-6
        assert r["audio_end_sec"] <= r["audio_start_sec"] + 30.0 + 1e-6
    # semantic 请求仍可序列化（request_id 唯一）
    assert len({r["request_id"] for r in sem}) == len(sem)


class _Timeline:
    """最小 timeline stub：仅暴露 build_requests 需要的属性。"""

    def __init__(self, units):
        self.canonical_units = units
        self.duration_sec = units[-1]["end_sec"]
