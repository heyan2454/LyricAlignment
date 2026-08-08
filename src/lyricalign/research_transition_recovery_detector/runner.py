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
from .identity import forward_cache_key, state_hash
from .query_estimator import QueryEstimator, DensityContractError
from .transitions import apply_transition_policy

DEFAULT_UNITS_PER_SEC = 1.0  # 每首歌按 n_units/duration 动态估计；仅缺歌词时回退


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
        sec_per_unit: float = 1.2,
        error_spec: dict[int, dict[int, dict[str, float]]] | None = None,
    ) -> None:
        # fake 合成行使用 sec_per_unit（seconds per unit）作为显式 reciprocal 字段；
        # 真实行为由 QueryEstimator（units_per_sec）决定。
        self.sec_per_unit = float(sec_per_unit)
        self.error_spec = error_spec or {}
        self.forward_calls = 0

    def forward(
        self, request: WindowRequest, audio: Any, document: Any, *, window_index: int = 0
    ) -> tuple[list[dict], dict]:
        self.forward_calls += 1
        rows: list[dict] = []
        errors = self.error_spec.get(window_index, {})
        for j, cid in enumerate(request.query_canonical_ids):
            start = int(cid) * self.sec_per_unit
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
    estimator: QueryEstimator,
    gt_timeline: dict[int, dict] | None,
    lookback_units: int,
    observations: dict[int, dict] | None = None,
) -> tuple[int, ...] | None:
    """构造本窗 query canonical ids（09 §2.1 Density contract，units_per_sec）。

    - T0 oracle：gt_timeline 中 start 位于 [core_start, core_end) 的 ids；GT 缺失返回 None。
    - T1/T2/T3：query 起点行 = observations 中 end_sec <= input_start 的最大 id + 1
      （无则用 previous_committed_end_model_sec * units_per_sec 估算），再回看 lookback；
      query 终点行 = input_end * units_per_sec（秒 × units/秒 = units）。
      禁止再做 span/units_per_sec 除法（单位倒置 bug 修复，09 §1）。
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
        time_start = int(round(float(state.previous_committed_end_model_sec) * estimator.units_per_sec))
    start_row = max(0, min(time_start, state.committed_end_exclusive) - lookback_units)
    end_row = estimator.query_end_id_exclusive(ie, start_id=start_row)
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
        legacy = config.get("unit_density_sec")
        if legacy is not None:
            # 旧字段同时表示两种物理量（09 §2.1）：fail closed，不静默解释。
            raise DensityContractError(
                "config field 'unit_density_sec' is ambiguous (sec/unit vs units/sec); "
                "remove it and let QueryEstimator derive units_per_sec from n_units/duration"
            )
        self._estimator: QueryEstimator | None = None
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
            estimator=self._estimator,
            gt_timeline=gt_timeline,
            lookback_units=self.lookback_units,
            observations=self._observations,
        )
        if query_ids is None:
            return None
        audio_identity = getattr(self, "_audio_identity", f"{song_id}@{self.config.get('audio_sha', '')}")
        request_id = f"{song_id}__{transition}__w{window_index:03d}"
        return WindowRequest(
            request_id=request_id,
            parent_state_hash=state_hash(state),
            audio_identity=audio_identity,
            original_bounds=original_bounds,
            model_bounds=model_bounds,
            query_canonical_ids=query_ids,
            slot_canonical_ids=(),
            decoder_evidence=("raw",),
            transition=transition,
            query_estimator_version=self._estimator.version,
            window_index=window_index,
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
        starting_state: TransitionState | None = None,
        start_window_index: int | None = None,
        observations: dict[int, dict] | None = None,
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
        # 音频内容身份（与歌名标签解耦，保证同音频跨 episode 共享 forward cache）。
        import hashlib as _hashlib

        audio_bytes = audio.tobytes() if hasattr(audio, "tobytes") else bytes(audio)
        self._audio_identity = f"audio-{_hashlib.sha256(audio_bytes).hexdigest()[:24]}"
        # 动态单位密度（09 §2.1）：units_per_sec = n_units / 实际（模型时钟）音频时长。
        n_units = max(1, len(getattr(document, "characters", ()) or ()))
        duration_model = float(len(audio) / int(self.config.get("sample_rate", 16000)))
        self._estimator = QueryEstimator(n_units=n_units, effective_audio_sec=max(duration_model, 1e-6))
        state = starting_state or TransitionState(
            song_id=song_id,
            transition=transition,
            window_index=0,
            next_input_cursor=0,
            committed_end_exclusive=0,
        )
        self._observations: dict[int, dict] = dict(observations or {})
        records: list[dict] = []
        self.last_observations: dict[int, dict] = {}
        windows = list(window_plan.get("windows") or [])
        # continuation：starting_state.window_index == k+1 时只执行 windows[k+1:]
        # （09 P0.2：propagation 不重放已执行窗口；request id 用绝对 window index）
        if start_window_index is None and starting_state is not None:
            start_window_index = starting_state.window_index
        start_window_index = start_window_index or 0
        if start_window_index > len(windows):
            raise ValueError(f"start_window_index {start_window_index} beyond {len(windows)} windows")
        windows = windows[start_window_index:]
        state = state.derive(window_index=state.window_index) if state.window_index == 0 and start_window_index > 0 else state
        for index, win in enumerate(windows):
            index = index + start_window_index
            if index < start_window_index:
                continue
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
                        "raw_start_entropy": r.get("raw_start_entropy"),
                        "raw_end_entropy": r.get("raw_end_entropy"),
                        "raw_start_margin": r.get("raw_start_margin"),
                        "raw_end_margin": r.get("raw_end_margin"),
                        "raw_start_top1_probability": r.get("raw_start_top1_probability"),
                        "raw_end_top1_probability": r.get("raw_end_top1_probability"),
                        "raw_start_topk_probabilities": list(r["raw_start_topk_probabilities"])
                        if r.get("raw_start_topk_probabilities") is not None else None,
                        "official_fixed_global_start_sec": r.get("official_fixed_global_start_sec"),
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
        self.last_observations = dict(self._observations)
        return records

    @staticmethod
    def _normalize_rows(rows: list[dict]) -> list[dict]:
        """把 infer_slice 的 rows 规范化为 transition 合同字段（start_sec/end_sec/source）。

        保留原始行全部字段（熵/边际/topk/official 等，供 detector 特征提取），
        只补充/覆盖合同字段。
        """
        normalized: list[dict] = []
        for row in rows:
            out = dict(row)
            start = float(row.get("fixed_global_start_sec", row.get("raw_global_start_sec", row.get("start_sec"))))
            end = float(row.get("fixed_global_end_sec", row.get("raw_global_end_sec", row.get("end_sec"))))
            out["global_character_index"] = int(row["global_character_index"])
            out["start_sec"] = start
            out["end_sec"] = end
            out["fixed_global_start_sec"] = start
            out["fixed_global_end_sec"] = end
            out.setdefault("occurrence", "")
            out["source"] = "raw"
            normalized.append(out)
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
