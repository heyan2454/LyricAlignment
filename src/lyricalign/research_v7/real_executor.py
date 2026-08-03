"""research_v7 real executor —— 用 frozen R2 LoRA 做一次真实对齐推理。

复用 scripts/demo/align_qwen_fa_serial_demo.load_model + infer_slice/full_alignment
（importlib 加载，脚本有 __main__ 保护），不依赖 SERIAL 窗口/Demucs。
输入：numpy 音频(16k mono) + 文本字符列表 → 返回逐字符 fixed 起止几何。
供 run_behavior_suite --real 使用；真实单 case smoke 用。
"""
from __future__ import annotations

import importlib.util
import sys
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
            decoder_top_k=8,
            decoder_beam_size=96,
            gpu_decoder_runtime=None,
        )
        self._processor, self._model = m.load_model(args, kind="lora", checkpoint=Path(self.checkpoint))
        self._args = args

    def align_units(self, audio: "object", units: Sequence[str]) -> list[dict]:
        """units 逐字符 -> 对齐 rows（含 fixed start/end）。audio 为 16k mono numpy。"""
        self._ensure()
        m = self._mod
        text = "\n".join(str(u) for u in units)
        document = m.process_lyric_text(text, language="Chinese") if hasattr(m, "process_lyric_text") else None
        if document is None:
            # fallback: 用 karaoke.parse_lyrics_text
            from lyricalign.demo.karaoke import parse_lyrics_text

            document = parse_lyrics_text(text, language="Chinese")
        rows, _audit = m.infer_slice(
            processor=self._processor,
            model=self._model,
            audio=audio,
            document=document,
            character_start=0,
            character_end=len(document.characters),
            global_audio_offset_sec=0.0,
            args=self._args,
        )
        return rows


def make_real_executor(aligner: RealAligner):
    """把 RealAligner 包成 v7 run_request 期望的 AlignmentRequest -> AlignmentAttempt。"""
    from .attempt import run_request  # noqa

    def executor(request: AlignmentRequest):
        try:
            rows = aligner.align_units(request.text_units) if hasattr(aligner, "align_units") else None
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
        return AlignmentAttempt(
            request=request,
            attempt_id=f"R-{request.item_id}-{request.mutation_type}",
            decoder_outputs={"official": {"rows": rows}},
            cursor_after=None,
            committed=False,
            status="ok",
        )

    return executor
