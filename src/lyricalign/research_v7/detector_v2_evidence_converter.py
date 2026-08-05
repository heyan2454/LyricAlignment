"""Detector V2 evidence converter —— 真实 runner evidence → EvidenceRow v2（20 §3, Dev-F）。

run_behavior_suite --real / real_executor 的 attempt.decoder_outputs 旧 schema：
  official.rows          逐字符 rows（含 raw_global_* / official_fixed_global_* / fixed_global_*）
  raw.rows               raw 几何副本（fixed_global_* 已改写为 raw 值）
  _posterior.rows        每边界 entropy/margin/topk（按 global_character_index）
  _repair_trace.boundary_moves  official 修复位移（按 global_character_index）

转换（每 official row → 一个 EvidenceRow）：
  - canonical_unit_id：global_character_index（request-local）经 canonical_to_local 逆映射；
    缺 canonical_to_local / row 缺 global_character_index / 索引不在映射内 → raise（完整性失败）。
  - raw view：raw_global_start/end_sec，缺失时回退 raw.rows 的 fixed_global_*；
    entropy/margin/topk 由 _posterior 按 index 对齐。topk 编码为
    (start_pairs, end_pairs)，每对 (class, prob)。
  - official view：official_fixed_global_start/end_sec（缺失回退 fixed_global_*）；
    repair shift 由 boundary_moves 匹配 global_character_index；trace 存在但无该 row 的 move
    → shift 0.0；trace 整体缺失 → shift None（不虚构 0）。
  - hidden：按 request_row.hidden_schema；decoder_outputs._hidden.rows 存在且按 index 对齐
    → available=True（start/end dict 透传）；否则 available=False（R/O 继续，不虚构 hidden）。
  - cross_view：由 MULTIVIEW_MANIFEST 组注入（view_group/n_views/view_ids/unit_covered_by）。
  - 防泄漏：每 row 输出前递归 assert_no_label_leak（顶层 + 嵌套 dict）；GT/mutation/family
    任何字段进入 row → ValueError，请求整体失败。
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from .detector_v2_evidence import (
    EvidenceRow,
    HiddenView,
    OfficialView,
    RawView,
    assert_no_label_leak,
)

SCHEMA_VERSION = "research_v7_detector_v2_evidence_v1"


def _to_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        raise ValueError(f"non-numeric time/posterior value: {v!r}")


def _inverse_canonical_map(request_row: Mapping[str, Any]) -> dict[int, int]:
    """canonical_to_local（canonical_id -> local index）→ local index -> canonical_id 逆映射。"""
    c2l = request_row.get("canonical_to_local")
    if not c2l:
        raise ValueError(
            "request_row missing canonical_to_local: cannot bind output rows to canonical units")
    inv: dict[int, int] = {}
    for k, v in c2l.items():
        local = int(v)
        if local in inv:
            raise ValueError(f"canonical_to_local has duplicate local index {local}")
        inv[local] = int(k)
    return inv


def _index_rows(rows: Sequence[Mapping[str, Any]]) -> dict[int, dict]:
    out: dict[int, dict] = {}
    for row in rows:
        gci = row.get("global_character_index")
        if gci is not None:
            out[int(gci)] = dict(row)
    return out


def _require_official_rows(decoder_outputs: Mapping[str, Any]) -> list:
    blk = decoder_outputs.get("official")
    if not isinstance(blk, Mapping):
        raise ValueError("decoder_outputs['official'] missing or not an object")
    rows = blk.get("rows")
    if not isinstance(rows, list):
        raise ValueError("decoder_outputs['official'].rows missing or not a list")
    return rows


def _topk_pairs(post: Mapping[str, Any], side: str) -> tuple:
    classes = post.get(f"{side}_topk_classes") or ()
    probs = post.get(f"{side}_topk_probabilities") or ()
    return tuple((int(c), float(p)) for c, p in zip(classes, probs))


def _raw_view(row: Mapping[str, Any], gci: int,
              raw_by_index: Mapping[int, dict], post_by_index: Mapping[int, dict]) -> RawView:
    start, end = row.get("raw_global_start_sec"), row.get("raw_global_end_sec")
    if start is None or end is None:
        rrow = raw_by_index.get(gci) or {}
        if start is None:
            start = rrow.get("fixed_global_start_sec")
        if end is None:
            end = rrow.get("fixed_global_end_sec")
    post = post_by_index.get(gci) or {}
    topk = _topk_pairs(post, "start"), _topk_pairs(post, "end")
    topk = tuple(x for x in topk if x) or ()
    return RawView(
        start_sec=_to_float(start), end_sec=_to_float(end),
        start_entropy=_to_float(post.get("start_entropy")),
        end_entropy=_to_float(post.get("end_entropy")),
        start_margin=_to_float(post.get("start_margin")),
        end_margin=_to_float(post.get("end_margin")),
        topk=topk,
    )


def _official_view(row: Mapping[str, Any], move: Mapping[str, Any] | None,
                   trace_available: bool) -> OfficialView:
    start, end = row.get("official_fixed_global_start_sec"), row.get("official_fixed_global_end_sec")
    if start is None:
        start = row.get("fixed_global_start_sec")
    if end is None:
        end = row.get("fixed_global_end_sec")
    if trace_available and move is not None:
        shift_s = _to_float(move.get("start_shift_sec")) or 0.0
        shift_e = _to_float(move.get("end_shift_sec")) or 0.0
    elif trace_available:
        shift_s = shift_e = 0.0
    else:
        shift_s = shift_e = None
    return OfficialView(start_sec=_to_float(start), end_sec=_to_float(end),
                        repair_start_shift_sec=shift_s, repair_end_shift_sec=shift_e)


def _hidden_view(request_row: Mapping[str, Any],
                 decoder_outputs: Mapping[str, Any]) -> HiddenView:
    schema = request_row.get("hidden_schema")
    blk = decoder_outputs.get("_hidden")
    if not schema or not isinstance(blk, Mapping) or not isinstance(blk.get("rows"), list):
        return HiddenView(available=False, schema=schema or None)
    hidden_rows = _index_rows(blk["rows"])
    starts: dict[int, dict] = {}
    ends: dict[int, dict] = {}
    for gci, hrow in hidden_rows.items():
        s, e = hrow.get("start"), hrow.get("end")
        if isinstance(s, Mapping):
            starts[gci] = dict(s)
        if isinstance(e, Mapping):
            ends[gci] = dict(e)
    return HiddenView(available=True, schema=schema, start=starts, end=ends)


def _cross_view_for(groups: Sequence[dict], canonical_unit_id: int) -> dict:
    """groups 已按请求过滤；取第一个组（builder 保证每请求至多一组）。

    unit_covered_by：组内 canonical_ids 覆盖该 canonical unit 的 view request_ids。
    """
    if not groups:
        return {}
    g = groups[0]
    covers = [vid for vid in g["view_ids"] if canonical_unit_id in g["canonical_ids"]]
    return {
        "view_group": g["pair_id"],
        "n_views": g["n_views"],
        "view_ids": list(g["view_ids"]),
        "unit_covered_by": covers,
    }


def _recursive_leak_check(value: Any) -> None:
    """递归 assert_no_label_leak（顶层 + 任意嵌套 dict；hidden/cross_view 是透传风险点）。"""
    if isinstance(value, Mapping):
        assert_no_label_leak(value)
        for v in value.values():
            _recursive_leak_check(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            _recursive_leak_check(v)


def convert_evidence(
    evidence_json: Mapping[str, Any],
    request_row: Mapping[str, Any],
    *,
    multiview_groups: Sequence[Mapping[str, Any]] | None = None,
) -> list[EvidenceRow]:
    """旧 schema evidence json + REQUESTS 行 → EvidenceRow v2 列表。

    request_row 必须含 canonical_to_local、view_id、hidden_schema（canonical_to_local 缺失 raise）。
    multiview_groups：MULTIVIEW_MANIFEST 组（pair_id/views/canonical_ids），
    含本请求的组用于填充 cross_view。
    """
    attempt = evidence_json.get("attempt")
    if not isinstance(attempt, Mapping):
        raise ValueError("evidence_json missing 'attempt' object")
    decoder_outputs = attempt.get("decoder_outputs") or {}
    if not isinstance(decoder_outputs, Mapping):
        raise ValueError("attempt.decoder_outputs missing or not an object")

    inv = _inverse_canonical_map(request_row)
    official_rows = _require_official_rows(decoder_outputs)
    if not official_rows:
        return []

    raw_by_index = {}
    raw_blk = decoder_outputs.get("raw")
    if isinstance(raw_blk, Mapping) and isinstance(raw_blk.get("rows"), list):
        raw_by_index = _index_rows(raw_blk["rows"])

    post_by_index = {}
    post_blk = decoder_outputs.get("_posterior")
    if isinstance(post_blk, Mapping) and isinstance(post_blk.get("rows"), list):
        post_by_index = _index_rows(post_blk["rows"])

    repair_by_index: dict[int, dict] = {}
    trace_available = False
    rt = decoder_outputs.get("_repair_trace")
    if isinstance(rt, Mapping) and isinstance(rt.get("boundary_moves"), list):
        trace_available = True
        for m in rt["boundary_moves"]:
            gci = m.get("global_character_index")
            if gci is not None:
                repair_by_index[int(gci)] = m

    hidden = _hidden_view(request_row, decoder_outputs)
    groups = _select_multiview_groups(request_row, multiview_groups)
    request_identity = (
        evidence_json.get("content_identity")
        or request_row.get("request_identity")
        or (attempt.get("request") or {}).get("request_id")
    )
    view_id = request_row.get("view_id")

    out: list[EvidenceRow] = []
    for row in official_rows:
        gci = row.get("global_character_index")
        if gci is None:
            raise ValueError("official row missing global_character_index")
        gci = int(gci)
        if gci not in inv:
            raise ValueError(
                f"global_character_index {gci} not covered by canonical_to_local "
                "(rows must lie in request-local text space)")
        er = EvidenceRow(
            request_identity=request_identity,
            view_id=view_id,
            canonical_unit_id=inv[gci],
            raw=_raw_view(row, gci, raw_by_index, post_by_index),
            official=_official_view(row, repair_by_index.get(gci), trace_available),
            hidden=hidden,
            cross_view=_cross_view_for(groups, inv[gci]),
        )
        _recursive_leak_check(er.to_dict())
        out.append(er)
    return out


def _select_multiview_groups(
    request_row: Mapping[str, Any],
    multiview_groups: Sequence[Mapping[str, Any]] | None,
) -> list[dict]:
    """过滤出含本请求的 multiview 组（builder 保证每请求至多一组；多组时取第一个）。"""
    if not multiview_groups:
        return []
    rid = request_row.get("request_id")
    if not rid:
        return []
    for g in multiview_groups:
        views = list(g.get("views") or [])
        if rid not in views:
            continue
        return [{
            "pair_id": g.get("pair_id"),
            "n_views": len(views),
            "view_ids": views,
            "canonical_ids": set(int(c) for c in (g.get("canonical_ids") or [])),
        }]
    return []
