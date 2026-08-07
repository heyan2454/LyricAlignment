"""Phase 1 shared runner：真实串行 forward 骨架（薄封装，不复制 serial demo 脚本）。

数据流（07 §3.3 上游）：
    audio -> preprocessing（可选压缩）-> window plan -> 每窗 WindowRequest
    -> backend.forward -> rows -> apply_transition_policy -> TransitionState

每窗记录 state-before / request / evidence / decision / state-after 追加到
<session_root>/02_transition/<song>__<transition>.jsonl。
时间约定：rows 的 fixed_global_* 与 request.model_bounds 均为 model/compressed clock；
original clock 映射由压缩 mapping 提供，记录在 records["silence_mapping"]。
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .contracts import (
    TRANSITION_T0_ORACLE,
    TRANSITION_T1_DIRECT,
    TRANSITION_T2_CORE,
    TRANSITION_T3_STABLE,
    TransitionState,
    WindowRequest,
)
from .identity import forward_cache_key
from .transitions import apply_transition_policy

DEFAULT_UNIT_DENSITY_SEC = 1.2


class BackendError(RuntimeError):
    pass


class FakeAlignerBackend:
    """CPU 合成 backend：按 query ids 生成单调 rows，支持注入错误行。

    error_spec: {window_index: {relative_index: {"start_sec": float}}}，
    把指定窗中相对索引行的 start 覆盖（用于制造越界/错误 commit）。
    """

    def __init__(
        self,
        *,
        unit_density_sec: float = DEFAULT_UNIT_DENSITY_SEC,
        error_spec: dict[int, dict[int, dict[str, float]]] | None = None,
    ) -> None:
        self.unit_density_sec = float(unit_density_sec)
        self.error_spec = error_spec or {}
        self.forward_calls = 0

    def forward(
        self, request: WindowRequest, audio: Any, document: Any, *, window_index: int = 0
    ) -> tuple[list[dict], dict]:
        self.forward_calls += 1
        rows: list[dict] = []
        errors = self.error_spec.get(window_index, {})
        for j, cid in enumerate(request.query_canonical_ids):
            start = int(cid) * self.unit_density_sec
            override = errors.get(j)
            if override is not None:
                start = float(override.get("start_sec", start))
            rows.append(
                {
                    "global_character_index": int(cid),
                    "character": f"c{cid}",
                    "start_sec": start,
                    "end_sec": start + 2.5,
                    "fixed_global_start_sec": start,
                    "fixed_global_end_sec": start + 2.5,
                    "source": "raw",
                }
            )
        audit = {"backend": "fake", "window_index": window_index, "row_count": len(rows)}
        return rows, audit


class RealAlignerBackend:
    """真实 forward 薄封装：infer_slice（demo/serial_demo 的 load_model 在脚本层完成）。

    forward 按 model-bounds 切窗音频（16k 单声道 numpy），query ids -> document 切片。
    """

    def __init__(
        self,
        *,
        processor: Any,
        model: Any,
        args: Any,
        sample_rate: int = 16000,
    ) -> None:
        self.processor = processor
        self.model = model
        self.args = args
        self.sample_rate = int(sample_rate)
        self.forward_calls = 0

    def forward(
        self, request: WindowRequest, audio: Any, document: Any, *, window_index: int = 0
    ) -> tuple[list[dict], dict]:
        from scripts.demo.align_qwen_fa_serial_demo import infer_slice

        self.forward_calls += 1
        is_, cs, ce, ie = request.model_bounds
        start_sample = max(0, int(round(is_ * self.sample_rate)))
        end_sample = min(len(audio), int(round(ie * self.sample_rate)))
        window_audio = audio[start_sample:end_sample]
        q0 = int(min(request.query_canonical_ids))
        q1 = int(max(request.query_canonical_ids)) + 1
        rows, audit = infer_slice(
            processor=self.processor,
            model=self.model,
            audio=window_audio,
            document=document,
            character_start=q0,
            character_end=q1,
            global_audio_offset_sec=is_,
            args=self.args,
            timestamp_slot_indices=None,
        )
        return rows, audit


def build_query_ids(
    *,
    transition: str,
    state: TransitionState,
    model_bounds: tuple[float, float, float, float],
    unit_density_sec: float,
    gt_timeline: dict[int, dict] | None,
    lookback_units: int,
    observations: dict[int, dict] | None = None,
) -> tuple[int, ...] | None:
    """构造本窗 query canonical ids。

    - T0 oracle：gt_timeline 中 start 位于 [core_start, core_end) 的 ids；GT 缺失返回 None。
    - T1/T2/T3：行范围由**时间位置**决定，避免把已唱过的字重新塞进当前窗音频：
      query 起点行 = observations 中 end_sec <= input_start 的最大 id + 1（无则用
      previous_committed_end_model_sec 按密度估算），再回看 lookback 行作声学上下文；
      query 终点行 = input_end 按密度估算。行号跨度与音频时间窗口匹配，
      相邻窗 query 仅随 observations 滑动（state 分叉后 query span 允许不同，07 §3.2）。
    """
    is_, cs, ce, ie = model_bounds
    if transition == TRANSITION_T0_ORACLE:
        if gt_timeline is None:
            return None
        ids = sorted(
            int(i) for i, row in gt_timeline.items() if cs - 1e-9 <= float(row["start_sec"]) < ce
        )
        return tuple(ids) if ids else None
    observations = observations or {}
    candidates = [
        int(i)
        for i, obs in observations.items()
        if float(obs["end_sec"]) <= is_ + 1e-9
    ]
    if candidates:
        time_start = max(candidates) + 1
    else:
        time_start = int(round(float(state.previous_committed_end_model_sec) / max(unit_density_sec, 1e-6)))
    # query 必须覆盖 committed 边界，保证未提交候选行可被重新观察（提交连续性）；
    # 时间估算起点只用于把 query 右移到当前观察区，不早于 committed 边界。
    start_row = max(0, min(time_start, state.committed_end_exclusive) - lookback_units)
    end_row = max(start_row + 1, int(round(ie / max(unit_density_sec, 1e-6))) + 1)
    return tuple(range(start_row, end_row))


def _project_plan_bounds(
    win: dict, mapping: dict | None
) -> tuple[tuple[float, float, float, float], tuple[float, float, float, float]]:
    original_bounds = (
        float(win["input_start_sec"]),
        float(win["core_start_sec"]),
        float(win["core_end_sec"]),
        float(win["input_end_sec"]),
    )
    if mapping is None:
        return original_bounds, original_bounds
    from .audio_preprocessing import map_original_to_compressed

    model_bounds = tuple(map_original_to_compressed(mapping, t) for t in original_bounds)
    return original_bounds, model_bounds  # type: ignore[return-value]


class TransitionRunner:
    """配置驱动 runner；resume 依据 forward_cache_key（命中则跳过真实 forward）。"""

    def __init__(
        self,
        config: dict,
        *,
        session_root: Path,
        backend: Any,
        audio_loader: Callable[[str], Any] | None = None,
        document_factory: Callable[[str, dict], Any] | None = None,
    ) -> None:
        self.config = config
        self.session_root = Path(session_root)
        self.backend = backend
        self.audio_loader = audio_loader
        self.document_factory = document_factory
        self.cache_root = self.session_root / "cache" / "forward"
        self.cache_root.mkdir(parents=True, exist_ok=True)
        self.model_identity = config.get("model_identity", {})
        self.env_identity = config.get("env_identity", "dev")
        self.config_hash = config.get("config_hash", "dev")
        self.unit_density_sec = float(config.get("unit_density_sec", DEFAULT_UNIT_DENSITY_SEC))
        self._effective_density = self.unit_density_sec
        self.lookback_units = int(config.get("lookback_units", 8))
        self.transition_dir = self.session_root / "02_transition"
        self.transition_dir.mkdir(parents=True, exist_ok=True)

    def _request_for(
        self,
        *,
        song_id: str,
        transition: str,
        state: TransitionState,
        win: dict,
        mapping: dict | None,
        gt_timeline: dict[int, dict] | None,
        window_index: int,
    ) -> WindowRequest | None:
        original_bounds, model_bounds = _project_plan_bounds(win, mapping)
        query_ids = build_query_ids(
            transition=transition,
            state=state,
            model_bounds=model_bounds,
            unit_density_sec=self._effective_density,
            gt_timeline=gt_timeline,
            lookback_units=self.lookback_units,
            observations=self._observations,
        )
        if query_ids is None:
            return None
        audio_identity = f"{song_id}@{self.config.get('audio_sha', '')}"
        request_id = f"{song_id}__{transition}__w{window_index:03d}"
        return WindowRequest(
            request_id=request_id,
            parent_state_hash="",
            audio_identity=audio_identity,
            original_bounds=original_bounds,
            model_bounds=model_bounds,
            query_canonical_ids=query_ids,
            slot_canonical_ids=(),
            decoder_evidence=("raw",),
            transition=transition,
        )

    def _cached_forward(self, request: WindowRequest, audio: Any, document: Any) -> list[dict]:
        key = forward_cache_key(
            request,
            config_hash=self.config_hash,
            model_identity=self.model_identity,
            env_identity=self.env_identity,
        )
        cache_path = self.cache_root / f"{key}.json"
        if cache_path.is_file():
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            return [dict(row) for row in payload["rows"]]
        rows, _audit = self.backend.forward(request, audio, document)
        tmp = cache_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"rows": rows}, ensure_ascii=False), "utf-8")
        tmp.replace(cache_path)
        return rows

    def run_song(
        self,
        *,
        song_id: str,
        audio: Any,
        document: Any,
        window_plan: dict,
        transition: str,
        gt_timeline: dict[int, dict] | None = None,
        compress: bool = False,
        retained_total_sec: float | None = None,
    ) -> list[dict]:
        mapping: dict | None = None
        if compress:
            from .audio_preprocessing import compress_long_silence_retained

            profile = self.config.get("audio_profile_provider", lambda a: None)(audio)
            min_sil = float(self.config.get("min_original_silence_sec", 5.0))
            audio, mapping = compress_long_silence_retained(
                audio, profile,
                sample_rate=int(self.config.get("sample_rate", 16000)),
                min_original_silence_sec=min_sil,
                retained_total_sec=float(retained_total_sec or 3.0),
            )
        # 动态单位密度：歌词总行数 / 实际（模型时钟）音频时长；无歌词时回退 config 值。
        n_units = max(1, len(getattr(document, "characters", ()) or ()))
        duration_model = float(len(audio) / int(self.config.get("sample_rate", 16000)))
        self._effective_density = float(n_units) / max(duration_model, 1e-6)
        state = TransitionState(
            song_id=song_id,
            transition=transition,
            window_index=0,
            next_input_cursor=0,
            committed_end_exclusive=0,
        )
        self._observations: dict[int, dict] = {}
        records: list[dict] = []
        windows = list(window_plan.get("windows") or [])
        for index, win in enumerate(windows):
            state_before = state
            request = self._request_for(
                song_id=song_id,
                transition=transition,
                state=state,
                win=win,
                mapping=mapping,
                gt_timeline=gt_timeline,
                window_index=index,
            )
            record: dict[str, Any] = {
                "song_id": song_id,
                "transition": transition,
                "window_index": index,
                "state_before": state_before.__dict__,
            }
            if request is None:
                record["skipped"] = "no_gt" if transition == TRANSITION_T0_ORACLE else "no_query"
                records.append(record)
                self._append_record(song_id, transition, record)
                continue
            rows = self._cached_forward(request, audio, document)
            rows = self._normalize_rows(rows)
            record["request"] = request.__dict__
            evidence = {
                "row_count": len(rows),
                "raw_global_rows": [
                    {
                        "global_character_index": int(r["global_character_index"]),
                        "fixed_global_start_sec": float(r["fixed_global_start_sec"]),
                        "fixed_global_end_sec": float(r["fixed_global_end_sec"]),
                        "original_global_start_sec": (
                            float(self._map_to_original(mapping, r["fixed_global_start_sec"]))
                            if mapping is not None
                            else float(r["fixed_global_start_sec"])
                        ),
                        "original_global_end_sec": (
                            float(self._map_to_original(mapping, r["fixed_global_end_sec"]))
                            if mapping is not None
                            else float(r["fixed_global_end_sec"])
                        ),
                    }
                    for r in rows
                ],
            }
            record["evidence_summary"] = evidence
            if transition == TRANSITION_T0_ORACLE:
                state_after = state_before
                record["decision"] = {"mode": "oracle_independent", "committed": []}
            else:
                state_after = apply_transition_policy(
                    transition, state_before, rows,
                    window_request=request,
                    previous_observation=self._observations,
                )
                record["decision"] = {
                    "committed_end_exclusive": state_after.committed_end_exclusive,
                    "provisional_ids": list(state_after.provisional_ids),
                    "unresolved_gap": state_after.unresolved_gap,
                }
                self._observations.update(
                    {
                        int(r["global_character_index"]): {
                            "global_character_index": int(r["global_character_index"]),
                            "start_sec": float(r["fixed_global_start_sec"]),
                            "end_sec": float(r["fixed_global_end_sec"]),
                            "source": str(r.get("source", "raw")),
                        }
                        for r in rows
                    }
                )
            record["state_after"] = state_after.__dict__
            if mapping is not None:
                record["silence_mapping"] = {
                    "original_duration_sec": mapping["original_duration_sec"],
                    "compressed_duration_sec": mapping["compressed_duration_sec"],
                    "parameters": mapping["parameters"],
                }
            records.append(record)
            self._append_record(song_id, transition, record)
            state = state_after
        return records

    @staticmethod
    def _normalize_rows(rows: list[dict]) -> list[dict]:
        """把 infer_slice 的 rows 规范化为 transition 合同字段（start_sec/end_sec/source）。"""
        normalized: list[dict] = []
        for row in rows:
            start = float(row.get("fixed_global_start_sec", row.get("raw_global_start_sec", row.get("start_sec"))))
            end = float(row.get("fixed_global_end_sec", row.get("raw_global_end_sec", row.get("end_sec"))))
            normalized.append({
                "global_character_index": int(row["global_character_index"]),
                "character": row.get("character", ""),
                "start_sec": start,
                "end_sec": end,
                "fixed_global_start_sec": start,
                "fixed_global_end_sec": end,
                "occurrence": row.get("occurrence", ""),
                "source": "raw",
            })
        return normalized

    @staticmethod
    def _map_to_original(mapping: dict, t_model: float) -> float:
        from .audio_preprocessing import map_compressed_to_original

        return map_compressed_to_original(mapping, t_model)

    def _append_record(self, song_id: str, transition: str, record: dict) -> None:
        path = self.transition_dir / f"{song_id}__{transition}.jsonl"
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def load_records(self, song_id: str, transition: str) -> list[dict]:
        path = self.transition_dir / f"{song_id}__{transition}.jsonl"
        if not path.is_file():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
