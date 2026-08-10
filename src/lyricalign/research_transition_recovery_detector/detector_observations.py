"""committed-observation binding（二次补充 Stage B1/B2）。

从 T2 records 构建 (request_id, canonical_id) -> exact committed row 的索引，
以及 canonical_id -> committed_request_id 的唯一 primary binding。

背景：第一次补充中 `rows_to_rowobjs()` 用 `{canonical_id: row}` 的 dict 推导
（后遍历的 overlap view 覆盖先前的 committed row），导致 label/特征混用不同
observation。本模块强制所有 correctness feature family 以 committed row 为
主样本，V 可以额外使用全部合法 observations。

不读 GT / future trajectory / mutation family 字段。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CommittedObservationIndex:
    """committed-observation 索引。

    committed_row: (request_id, canonical_id) -> exact committed row
    committed_request: canonical_id -> committed request_id（每 unit 一次）
    all_observations: canonical_id -> [(request_id, row), ...]（全部合法 view）
    mismatch_log: [(canonical_id, reason, request_ids), ...]
    """
    committed_row: dict[tuple[str, int], dict] = field(default_factory=dict)
    committed_request: dict[int, str] = field(default_factory=dict)
    all_observations: dict[int, list[tuple[str, dict]]] = field(default_factory=dict)
    mismatch_log: list[dict] = field(default_factory=list)
    n_records: int = 0
    n_committed_units: int = 0

    def primary_row(self, canonical_id: int) -> dict | None:
        """该 canonical unit 的 committed observation row（主样本）。"""
        req = self.committed_request.get(canonical_id)
        if req is None:
            return None
        return self.committed_row.get((req, canonical_id))

    def observations(self, canonical_id: int) -> list[tuple[str, dict]]:
        """该 canonical unit 的全部合法 view（V 族使用）。"""
        return self.all_observations.get(canonical_id, [])


def committed_observation_index(
    records: list[dict],
    *,
    song_id: str | None = None,
) -> CommittedObservationIndex:
    """构建 committed-observation 索引。

    - 每 record 用 [state_before.committed_end_exclusive, decision.committed_end_exclusive)
      区间内的 raw_global_rows 作为 committed rows；
    - 以 (request_id, canonical_id) 保存 exact row，重复 key 记为 mismatch；
    - canonical_id -> committed_request_id 每 unit 保存一次（首次即 committed），
      若后续 record 再次 commit 同一 unit，记为 mismatch；
    - all_observations 保存每个 unit 的全部合法 view（含非 committed 的 overlap）。
    """
    idx = CommittedObservationIndex()
    idx.n_records = len(records)

    for rec in records:
        request_id = rec["request"]["request_id"]
        before = int(rec["state_before"]["committed_end_exclusive"])
        after = int(rec["decision"]["committed_end_exclusive"])
        window_index = rec.get("window_index")
        for r in rec["evidence_summary"]["raw_global_rows"]:
            cid = int(r["global_character_index"])
            key = (request_id, cid)
            idx.all_observations.setdefault(cid, []).append((request_id, r))
            if before <= cid < after:
                if key in idx.committed_row:
                    idx.mismatch_log.append({
                        "song_id": song_id, "canonical_id": cid,
                        "reason": "duplicate_committed_row",
                        "request_ids": [request_id],
                        "window_index": window_index,
                    })
                else:
                    idx.committed_row[key] = r
                if cid not in idx.committed_request:
                    idx.committed_request[cid] = request_id
                    idx.n_committed_units += 1
                else:
                    idx.mismatch_log.append({
                        "song_id": song_id, "canonical_id": cid,
                        "reason": "recommit_after_first_commit",
                        "request_ids": [idx.committed_request[cid], request_id],
                        "window_index": window_index,
                    })
    return idx


def label_from_row(row: dict, gt: dict[int, dict] | None, *,
                   safe_ms: float, grey_ms: float,
                   key: str = "original_global_start_sec") -> int | None:
    """按 GT 对 committed row 计算三态标签（0=safe,1=grey,2=unsafe）。

    key 选择：raw 目标用 original_global_start_sec，official 目标用
    fixed_global_start_sec（与 v3 一致）。
    """
    if row is None or gt is None:
        return None
    cid = int(row["global_character_index"])
    g = gt.get(cid)
    if g is None:
        return None
    pred = row.get(key)
    if pred is None:
        return None
    err = abs(float(pred) - float(g["start_sec"]))
    if err <= safe_ms:
        return 0
    if err <= grey_ms:
        return 1
    return 2
