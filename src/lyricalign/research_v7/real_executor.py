"""research_v7 real executor —— 用 frozen R2 LoRA 做一次真实对齐推理。

复用 scripts/demo/align_qwen_fa_serial_demo.load_model + infer_slice/full_alignment
（importlib 加载，脚本有 __main__ 保护），不依赖 SERIAL 窗口/Demucs。
输入：numpy 音频(16k mono) + 文本字符列表 → 返回逐字符 fixed 起止几何。
供 run_behavior_suite --real 使用；真实单 case smoke 用。
"""
from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Sequence

import numpy as np

from .attempt import AlignmentAttempt
from .requests import AlignmentRequest

_REPO = str(Path(__file__).resolve().parents[3])  # /home/hyan/LyricAlignment


def remerge_fixed_slots(
    active_rows: Sequence[dict],
    fixed_slot_rows: Sequence[dict],
    *,
    total_units: int,
) -> list[dict]:
    """Restore frozen baseline slots after a sparse timestamp forward.

    The decoder receives the complete text; it produces timestamps for only
    active slots.  This function restores the complementary baseline geometry
    and rejects incomplete/overlapping coverage.
    """
    active_by_local: dict[int, dict] = {}
    for row in active_rows:
        local = row.get("global_character_index")
        if not isinstance(local, int) or local in active_by_local:
            raise ValueError("active sparse output requires unique local global_character_index")
        active_by_local[local] = dict(row)
    fixed_by_local: dict[int, dict] = {}
    for raw in fixed_slot_rows:
        local = raw.get("local_index")
        if not isinstance(local, int) or local in fixed_by_local:
            raise ValueError("fixed sparse rows require unique local_index")
        row = {k: v for k, v in raw.items() if k != "local_index"}
        start = row.get("fixed_global_start_sec", row.get("start_sec"))
        end = row.get("fixed_global_end_sec", row.get("end_sec"))
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)) or end < start:
            raise ValueError("fixed sparse rows require valid baseline geometry")
        row.setdefault("fixed_global_start_sec", float(start))
        row.setdefault("fixed_global_end_sec", float(end))
        row["global_character_index"] = local
        fixed_by_local[local] = row
    if set(active_by_local) & set(fixed_by_local):
        raise ValueError("sparse active output overlaps frozen slot")
    if set(active_by_local) | set(fixed_by_local) != set(range(total_units)):
        raise ValueError("sparse output plus frozen slots does not cover all text units")
    out = []
    for local in range(total_units):
        row = dict(active_by_local.get(local, fixed_by_local.get(local)))
        row["slot_origin"] = "active_forward" if local in active_by_local else "fixed_baseline"
        out.append(row)
    return out


def validate_active_sparse_rows(active_rows: Sequence[dict], fixed_slot_rows: Sequence[dict], *, total_units: int) -> None:
    """Validate the observable sparse contract before baseline remerge.

    An active-only decoder cannot report fixed-slot drift: fixed slots are not
    emitted.  What is observable (and therefore enforced) is complete active
    coverage, valid active geometry, and no crossing/non-monotonic timeline
    when active geometry is merged with frozen baseline rows.
    """
    active = {int(row.get("global_character_index", -1)): row for row in active_rows}
    expected = {int(row["local_index"]) for row in fixed_slot_rows}
    active_expected = set(range(total_units)) - expected
    if set(active) != active_expected:
        raise ValueError("SAFE_SLOT_INVARIANT_VIOLATION: active sparse output coverage mismatch")
    combined: dict[int, tuple[float, float]] = {}
    for local, row in active.items():
        start, end = row.get("fixed_global_start_sec"), row.get("fixed_global_end_sec")
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)) or end < start:
            raise ValueError("SAFE_SLOT_INVARIANT_VIOLATION: invalid active geometry")
        combined[local] = (float(start), float(end))
    for row in fixed_slot_rows:
        local = int(row["local_index"])
        start = row.get("fixed_global_start_sec", row.get("start_sec"))
        end = row.get("fixed_global_end_sec", row.get("end_sec"))
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)) or end < start:
            raise ValueError("SAFE_SLOT_INVARIANT_VIOLATION: invalid fixed baseline geometry")
        combined[local] = (float(start), float(end))
    ordered = [combined[index] for index in range(total_units)]
    if any(b[0] < a[0] or b[1] < a[1] for a, b in zip(ordered, ordered[1:])):
        raise ValueError("SAFE_SLOT_INVARIANT_VIOLATION: active geometry crosses frozen timeline")


def _load_serial_demo():
    if "qwen_fa_serial_demo" in sys.modules:
        return sys.modules["qwen_fa_serial_demo"]
    path = Path(_REPO) / "scripts/demo/align_qwen_fa_serial_demo.py"
    spec = importlib.util.spec_from_file_location("qwen_fa_serial_demo", str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["qwen_fa_serial_demo"] = mod
    spec.loader.exec_module(mod)
    return mod


def _try_import(path):
    spec = importlib.util.spec_from_file_location(path.stem, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[path.stem] = mod
    try:
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None


class RealAligner:
    """懒加载模型 + 单次对齐推理的封装。"""

    def __init__(self, model_dir: str, revision: str, checkpoint: str, device: str = "cuda"):
        self.model_dir = model_dir
        self.revision = revision
        self.checkpoint = checkpoint
        self.device = device
        self._mod = None
        self._runtime = None
        self._karaoke = None
        self._processor = None
        self._model = None
        self._checkpoint_content_sha = None

    def checkpoint_content_hash(self) -> str | None:
        """C2（review12）：checkpoint 内容 SHA（adapter/projector 等文件），用于 cache identity。

        同一 checkpoint 路径被重训覆盖或换内容时，identity 必须变化，避免旧 evidence 被复用。
        调用方在构造 request identity context 时并入该值；不加载模型、纯文件 hash。
        """
        import hashlib
        from pathlib import Path

        if self._checkpoint_content_sha is not None:
            return self._checkpoint_content_sha
        root = Path(self.checkpoint)
        if not root.is_dir():
            return None
        parts = []
        for f in sorted(root.rglob("*")):
            if f.is_file():
                try:
                    parts.append(f"{f.relative_to(root)}:{hashlib.sha256(f.read_bytes()).hexdigest()}")
                except OSError:
                    continue
        if not parts:
            return None
        self._checkpoint_content_sha = hashlib.sha256("|".join(parts).encode()).hexdigest()
        return self._checkpoint_content_sha

    def _ensure(self):
        if self._mod is not None:
            return
        m = _load_serial_demo()
        # decode_audio / parse_lyrics_text 的模块
        from lyricalign.training.qwen_fa_runtime import decode_audio  # noqa
        from lyricalign.demo.karaoke import parse_lyrics_text  # noqa
        self._mod = m
        self._runtime = sys.modules["lyricalign.training.qwen_fa_runtime"] if "lyricalign.training.qwen_fa_runtime" in sys.modules else None

        args = SimpleNamespace(
            device=self.device,
            model=self.model_dir,
            revision=self.revision,
            local_files_only=False,
            cache_dir=None,
            timestamp_segment_sec=0.08,
            decoder_kind="official",
            decoder_top_k=16,
            decoder_beam_size=96,
            gpu_decoder_runtime=None,
        )
        self._processor, self._model = m.load_model(args, kind="lora", checkpoint=Path(self.checkpoint))
        self._args = args

    def align_units(self, audio: "object", units: Sequence[str], slot_indices: Sequence[int] | None = None,
                    language: str = "Chinese", text_start_index: int = 0, text_end_index: int | None = None) -> list[dict]:
        """units 逐字符 -> 对齐 rows（含 fixed start/end）。audio 为 16k mono numpy。

        M4（review12）：text_start/end_index 是 request-local 索引，必须映射到 document
        character 空间；slot_indices 同样是 request-local unit 索引。v7 仅支持字符级 unit
        （中/日/英单字）；英文单词、日文词级 unit 是 known limitation（超出 v7 字符级范围），
        会显式拒绝（character↔unit 断言），不做静默错位。
        """
        self._ensure()
        m = self._mod
        text = "\n".join(str(u) for u in units)
        document = m.process_lyric_text(text, language=language) if hasattr(m, "process_lyric_text") else None
        if document is None:
            # fallback: 用 karaoke.parse_lyrics_text
            from lyricalign.demo.karaoke import parse_lyrics_text

            document = parse_lyrics_text(text, language=language)
        # request-local 索引空间：text_units 即本请求完整文本（local 0..N）
        if len(document.characters) != len(units):
            raise ValueError(
                f"document.characters({len(document.characters)}) != text_units({len(units)}): "
                "multi-character units break character↔unit mapping; "
                "request text must be character-aligned for real executor")
        end = len(units) if text_end_index is None else min(text_end_index, len(units))
        rows, _audit = m.infer_slice(
            processor=self._processor,
            model=self._model,
            audio=audio,
            document=document,
            character_start=text_start_index,
            character_end=end,
            global_audio_offset_sec=0.0,
            args=self._args,
            timestamp_slot_indices=slot_indices,
        )
        return rows

    def align_request(self, request: AlignmentRequest) -> list[dict]:
        """Decode the request's concrete audio path and honour its requested range.

        A v7 request is intentionally self-contained; a symbolic source such as
        ``demucs_vocal`` is not sufficient for real inference and is rejected.
        """
        from pathlib import Path
        from lyricalign.training.qwen_fa_runtime import decode_audio

        path = Path(request.audio_source)
        if not path.is_file():
            raise ValueError("real executor requires audio_source to be an existing audio file")
        audio = decode_audio(path)
        start = int(round(request.audio_start_sec * 16000))
        end = int(round(request.audio_end_sec * 16000))
        # M2（review12）：manifest 中 3~4 位小数时长与解码长度可有 ±1 sample 偏差，
        # 给 2 sample 容差并 clamp，避免合法窗口因舍入被整条拒绝。
        # P0/P1（realign gate）：audio_end == manifest duration 的窗口，解码样本可能
        # 比 round(end*16000) 少数个样本（+200ms 内）。这类是 manifest 时长 vs 解码
        # 样本的系统偏差，零填充补齐而非整条拒绝，与 P0-C 影子音频行为等价。
        if start < 0 or end <= start:
            raise ValueError("request audio range is outside decoded audio")
        pad_needed = end - len(audio)
        if pad_needed > 0 and pad_needed <= int(0.2 * 16000):
            audio = np.concatenate([audio, np.zeros(pad_needed, dtype=audio.dtype)])
        if end > len(audio) + 2:
            raise ValueError("request audio range is outside decoded audio")
        end = min(end, len(audio))
        start = min(start, len(audio) - 1) if len(audio) > 0 else 0
        if end <= start:
            raise ValueError("request audio range is outside decoded audio")
        language = str(request.metadata.get("language") or "Chinese")
        rows = self.align_units(audio[start:end], request.text_units, request.timestamp_slot_indices,
                                language=language,
                                text_start_index=request.text_start_index,
                                text_end_index=request.text_end_index)
        if request.input_variant == "strict_serial_committed_prefix_all_slots":
            current_start = int(request.mutation_parameters.get("source_text_start_index") or 0)
            rows = [row for row in rows if int(row.get("global_character_index", -1)) >= current_start]
        for row in rows:
            # C1（review12）：infer_slice 输出多组 global 坐标键
            # （raw_global_*/official_fixed_global_*/gpu_fixed_global_*/fixed_global_*）。
            # 全部必须随 audio_start_sec 平移，否则窗内 official 几何是局部坐标而 raw 是全局，
            # evidence 出现混坐标；features 的 official_* 键优先读 official_fixed_global_*，
            # 任何 audio_start_sec>0 的窗都会得到错误绝对时间。
            for key in list(row.keys()):
                if key.endswith("_global_start_sec") or key.endswith("_global_end_sec"):
                    if row[key] is not None:
                        row[key] = float(row[key]) + request.audio_start_sec
        if request.slot_constraint_schema == "realign_sparse_fixed_v1":
            validate_active_sparse_rows(rows, request.fixed_slot_rows or (), total_units=len(request.text_units))
            rows = remerge_fixed_slots(
                rows, request.fixed_slot_rows or (), total_units=len(request.text_units))
        return rows


def make_real_executor(aligner: RealAligner):
    """把 RealAligner 包成 v7 run_request 期望的 AlignmentRequest -> AlignmentAttempt。"""
    def executor(request: AlignmentRequest):
        started = time.monotonic()
        try:
            rows = aligner.align_request(request) if hasattr(aligner, "align_request") else None
        except Exception as e:  # noqa
            return AlignmentAttempt(
                request=request, attempt_id=f"R-{request.item_id}-{request.mutation_type}",
                decoder_outputs={}, status="error", error=str(e),
            )
        if rows is None:
            return AlignmentAttempt(
                request=request, attempt_id=f"R-{request.item_id}-{request.mutation_type}",
                decoder_outputs={}, status="error", error="aligner returned None",
            )
        posterior_rows = []
        repair_moves = []
        raw_rows = []
        for row in rows:
            raw_start = float(row.get("raw_global_start_sec", row.get("fixed_global_start_sec", 0.0)))
            raw_end = float(row.get("raw_global_end_sec", row.get("fixed_global_end_sec", 0.0)))
            fixed_start = float(row.get("fixed_global_start_sec", raw_start))
            fixed_end = float(row.get("fixed_global_end_sec", raw_end))
            raw_rows.append({**row, "fixed_global_start_sec": raw_start, "fixed_global_end_sec": raw_end,
                             "decoder_kind": "raw_argmax"})
            posterior_rows.append({
                "global_character_index": row.get("global_character_index"),
                "start_topk_classes": row.get("raw_start_topk_classes", []),
                "start_topk_probabilities": row.get("raw_start_topk_probabilities", []),
                "end_topk_classes": row.get("raw_end_topk_classes", []),
                "end_topk_probabilities": row.get("raw_end_topk_probabilities", []),
                "start_entropy": row.get("raw_start_entropy"), "end_entropy": row.get("raw_end_entropy"),
                "start_margin": row.get("raw_start_margin"), "end_margin": row.get("raw_end_margin"),
            })
            if abs(raw_start - fixed_start) > 1e-6 or abs(raw_end - fixed_end) > 1e-6:
                repair_moves.append({"global_character_index": row.get("global_character_index"),
                                     "start_shift_sec": fixed_start - raw_start,
                                     "end_shift_sec": fixed_end - raw_end})
        weighted_rows = []
        weighted_availability = "unavailable_missing_raw_geometry"
        if all("raw_global_start_sec" in row and "raw_global_end_sec" in row for row in rows):
            from lyricalign.research_v6.decoders import DecoderConfig, weighted_isotonic_rows
            weighted_rows = weighted_isotonic_rows(rows, DecoderConfig(
                name="weighted_isotonic", timestamp_step_sec=float(getattr(getattr(aligner, "_args", None), "timestamp_segment_sec", 0.08)), top_k=16,
            ))
            for weighted in weighted_rows:
                weighted["fixed_global_start_sec"] = float(weighted.pop("start_sec"))
                weighted["fixed_global_end_sec"] = float(weighted.pop("end_sec"))
                weighted["decoder_kind"] = "weighted_isotonic"
            weighted_availability = "posthoc_from_raw_geometry"
        sparse_constraint = None
        if request.slot_constraint_schema == "realign_sparse_fixed_v1":
            sparse_constraint = {
                "schema": request.slot_constraint_schema,
                "active_slot_indices": list(request.active_slot_indices or ()),
                "fixed_slot_count": len(request.fixed_slot_rows or ()),
                "full_text_unit_count": len(request.text_units),
                "validation_mode": "active_geometry_against_frozen_baseline",
                "remerge_status": "exact_baseline_rows_restored",
            }
        decoder_outputs = {
            "raw": {"rows": raw_rows, "availability": "derived_from_official_decoder_raw_geometry"},
            "official": {"rows": rows},
            "top_k": {"availability": "per-boundary posterior in _posterior"},
            "weighted_isotonic": {"rows": weighted_rows, "availability": weighted_availability},
            "_posterior": {"top_k": 16, "rows": posterior_rows},
            "_repair_trace": {"decoder": "official", "changed_boundary_count": len(repair_moves),
                               "boundary_moves": repair_moves},
        }
        if sparse_constraint is not None:
            decoder_outputs["_sparse_constraint"] = sparse_constraint
        return AlignmentAttempt(
            request=request,
            attempt_id=f"R-{request.item_id}-{request.mutation_type}",
            decoder_outputs=decoder_outputs,
            cursor_after=max((float(row.get("fixed_global_end_sec", row.get("end_sec", 0.0))) for row in rows), default=None),
            committed=True,
            runtime_sec=time.monotonic() - started,
            status="ok",
        )

    return executor
