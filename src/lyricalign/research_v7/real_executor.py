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

from .attempt import AlignmentAttempt
from .requests import AlignmentRequest

_REPO = str(Path(__file__).resolve().parents[3])  # /home/hyan/LyricAlignment


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
                    language: str = "Chinese") -> list[dict]:
        """units 逐字符 -> 对齐 rows（含 fixed start/end）。audio 为 16k mono numpy。"""
        self._ensure()
        m = self._mod
        text = "\n".join(str(u) for u in units)
        document = m.process_lyric_text(text, language=language) if hasattr(m, "process_lyric_text") else None
        if document is None:
            # fallback: 用 karaoke.parse_lyrics_text
            from lyricalign.demo.karaoke import parse_lyrics_text

            document = parse_lyrics_text(text, language=language)
        rows, _audit = m.infer_slice(
            processor=self._processor,
            model=self._model,
            audio=audio,
            document=document,
            character_start=0,
            character_end=len(document.characters),
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
        if start < 0 or end <= start or end > len(audio):
            raise ValueError("request audio range is outside decoded audio")
        language = str(request.metadata.get("language") or "Chinese")
        rows = self.align_units(audio[start:end], request.text_units, request.timestamp_slot_indices, language=language)
        if request.input_variant == "strict_serial_committed_prefix_all_slots":
            current_start = int(request.mutation_parameters.get("source_text_start_index") or 0)
            rows = [row for row in rows if int(row.get("global_character_index", -1)) >= current_start]
        for row in rows:
            for key in ("raw_global_start_sec", "raw_global_end_sec", "fixed_global_start_sec", "fixed_global_end_sec"):
                if key in row:
                    row[key] = float(row[key]) + request.audio_start_sec
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
        decoder_outputs = {
            "raw": {"rows": raw_rows, "availability": "derived_from_official_decoder_raw_geometry"},
            "official": {"rows": rows},
            "top_k": {"availability": "per-boundary posterior in _posterior"},
            "weighted_isotonic": {"rows": weighted_rows, "availability": weighted_availability},
            "_posterior": {"top_k": 16, "rows": posterior_rows},
            "_repair_trace": {"decoder": "official", "changed_boundary_count": len(repair_moves),
                               "boundary_moves": repair_moves},
        }
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
